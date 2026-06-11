#!/usr/bin/env python3
"""
pricing_rules.py
================
Shared pricing-rule loader for deterministic scoring and LLM review.

Production scoring must read Lark pricing rules. Packaged JSON rules are only
allowed for TEST_MODE or explicit local-rule fallback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config_loader import get_lark, is_test_mode, load_config
from lark_cli_utils import normalize_record_list_response, run_lark_cli_json

LOCAL_RULES_PATH = Path(__file__).parent.parent / "config" / "resume_screening_rules_v2.json"

LANG_RULE_FIELDS = {
    "language_pair": ("语言对", "Language pair", "lang_pair"),
    "aipe_target": ("AIPE预期价", "AIPE目标价", "AIPE target"),
    "aipe_max": ("AIPE上限价", "AIPE最高价", "AIPE max"),
    "trans_target": ("翻译预期价", "人工翻译预期价", "Translation target"),
    "trans_max": ("翻译上限价", "人工翻译上限价", "Translation max"),
    "version": ("规则版本", "版本", "Version"),
    "enabled": ("启用", "是否启用", "Enabled"),
}


class PricingRulesError(RuntimeError):
    pass


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("name") or item.get("value") or ""))
            else:
                parts.append(str(item))
        return " ".join(p for p in parts if p).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("value") or "").strip()
    return str(value).strip()


def value_for(fields: dict, logical_key: str) -> Any:
    for name in LANG_RULE_FIELDS[logical_key]:
        if name in fields:
            return fields.get(name)
    return None


def as_float(value: Any, field_name: str, lang_pair: str) -> float:
    text = extract_text(value)
    if text == "":
        raise PricingRulesError(f"价格规则「{lang_pair}」缺少字段：{field_name}")
    try:
        return float(text)
    except ValueError as exc:
        raise PricingRulesError(f"价格规则「{lang_pair}」字段 {field_name} 不是数字：{text}") from exc


def normalize_rule_key(raw: Any) -> str:
    text = extract_text(raw)
    return (
        text.replace(" ", "")
        .replace("＞", ">")
        .replace("→", ">")
        .replace("－", "-")
        .strip()
    )


def is_enabled(fields: dict) -> bool:
    raw = value_for(fields, "enabled")
    if raw is None or extract_text(raw) == "":
        return True
    text = extract_text(raw).lower()
    return text in {"true", "yes", "y", "1", "是", "启用", "enabled", "✅ 是"}


def load_packaged_price_rules() -> dict:
    if not LOCAL_RULES_PATH.exists():
        raise PricingRulesError(f"缺少包内评分规则文件：{LOCAL_RULES_PATH}")
    data = json.loads(LOCAL_RULES_PATH.read_text(encoding="utf-8"))
    price_rules = data.get("price_rules", {})
    aipe_rules = price_rules.get("aipe", {})
    trans_rules = price_rules.get("translation", {})
    keys = sorted(set(aipe_rules) | set(trans_rules))
    rules = {}
    for key in keys:
        aipe = aipe_rules.get(key, {})
        trans = trans_rules.get(key, {})
        rules[key] = {
            "aipe_target": float(aipe.get("target", 0.03)),
            "aipe_max": float(aipe.get("max", 0.04)),
            "trans_target": float(trans.get("target", aipe.get("target", 0.03))),
            "trans_max": float(trans.get("max", aipe.get("max", 0.04))),
            "source": "local",
            "version": "packaged",
        }
    if not rules:
        raise PricingRulesError("包内价格规则为空")
    return rules


def load_lark_price_rules(base_token: str, table_id: str) -> dict:
    if not base_token or not table_id:
        raise PricingRulesError("缺少 Lark 评分规则配置表：请填写 lark.base_token 和 lark.rules_table_id")

    resp = run_lark_cli_json(
        "base", "+record-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--as", "bot",
        "--limit", "500",
        "--format", "json",
    )
    records = normalize_record_list_response(resp if isinstance(resp, dict) else {})
    rules = {}
    for record in records:
        fields = record.get("fields") or {}
        if not is_enabled(fields):
            continue
        key = normalize_rule_key(value_for(fields, "language_pair"))
        if not key:
            continue
        rules[key] = {
            "aipe_target": as_float(value_for(fields, "aipe_target"), "AIPE预期价", key),
            "aipe_max": as_float(value_for(fields, "aipe_max"), "AIPE上限价", key),
            "trans_target": as_float(value_for(fields, "trans_target"), "翻译预期价", key),
            "trans_max": as_float(value_for(fields, "trans_max"), "翻译上限价", key),
            "source": "lark",
            "version": extract_text(value_for(fields, "version")) or "",
        }

    if not rules:
        raise PricingRulesError("Lark 评分规则配置表为空或没有启用的语言对规则")
    return rules


def load_price_rules(
    *,
    allow_local_rules: bool = False,
    require_lark_rules: bool | None = None,
) -> tuple[dict, dict]:
    cfg = load_config()
    lark = get_lark(cfg)
    require_lark = (not is_test_mode(cfg)) if require_lark_rules is None else require_lark_rules

    try:
        rules = load_lark_price_rules(lark.get("base_token", ""), lark.get("rules_table_id", ""))
        return rules, {
            "source": "lark",
            "table_id": lark.get("rules_table_id", ""),
            "count": len(rules),
        }
    except PricingRulesError as exc:
        if require_lark and not allow_local_rules:
            raise PricingRulesError(
                f"{exc}\n生产评分必须使用 Lark「评分规则配置」表。"
                "请让 VM 维护规则表后重试；测试场景才可显式使用 --allow-local-rules。"
            ) from exc

    if allow_local_rules or not require_lark:
        rules = load_packaged_price_rules()
        return rules, {
            "source": "local",
            "table_id": "",
            "count": len(rules),
        }

    raise PricingRulesError("价格规则加载失败")
