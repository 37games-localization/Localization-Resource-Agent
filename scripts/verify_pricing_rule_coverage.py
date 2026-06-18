#!/usr/bin/env python3
"""
Verify Lark pricing-rule coverage for main localization markets.

This check reads the configured pricing_rules table, normalizes language-pair
keys, and reports whether all required market directions are present.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pricing_rules import (
    LANG_RULE_FIELDS,
    PricingRulesError,
    extract_text,
    is_enabled,
    load_price_rules,
    normalize_rule_key,
    value_for,
)
from lark_cli_utils import normalize_record_list_response, run_lark_cli_json


REQUIRED_MAIN_MARKET_RULE_KEYS = {
    "en>ar",
    "en>de",
    "en>es",
    "en>fr",
    "en>id",
    "en>it",
    "en>ms",
    "en>nl",
    "en>pl",
    "en>pt",
    "en>ru",
    "en>th",
    "en>tr",
    "en>vi",
    "zh-CN>ar",
    "zh-CN>en",
    "zh-CN>id",
    "zh-CN>ja",
    "zh-CN>ko",
    "zh-CN>ms",
    "zh-CN>th",
    "zh-CN>vi",
}


def _build_label_diagnostics(records: list[dict[str, Any]] | None) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return display-label normalization and disabled-row diagnostics."""
    normalized = []
    disabled = []
    for record in records or []:
        fields = record.get("fields") or {}
        raw_label = extract_text(value_for(fields, "language_pair"))
        canonical = normalize_rule_key(raw_label)
        row = {
            "record_id": record.get("record_id") or "",
            "display_label": raw_label,
            "canonical_key": canonical,
        }
        if not is_enabled(fields):
            disabled.append(row)
            continue
        if raw_label and canonical and raw_label != canonical:
            normalized.append(row)
    return normalized, disabled


def build_pricing_rule_coverage_payload(
    rules: dict[str, Any],
    meta: dict[str, Any],
    *,
    records: list[dict[str, Any]] | None = None,
    required_keys: set[str] | None = None,
) -> dict[str, Any]:
    required = required_keys or REQUIRED_MAIN_MARKET_RULE_KEYS
    available = set(rules)
    missing = sorted(required - available)
    extra = sorted(available - required)
    normalized_labels, disabled_labels = _build_label_diagnostics(records)
    remediation = []
    if normalized_labels:
        remediation.append({
            "action": "rename_display_labels",
            "reason": "这些展示标签已被 Agent 兼容归一，但建议 VM 在 Lark 评分规则表中改成 canonical key，避免人工维护时误判。",
            "items": normalized_labels,
        })
    if missing:
        remediation.append({
            "action": "add_missing_canonical_keys",
            "reason": "生产主市场覆盖缺失；这些 canonical key 没有启用规则，正式评分遇到对应语言对会阻断。",
            "items": [{"canonical_key": key, "suggested_language_pair": key} for key in missing],
        })
    if disabled_labels:
        remediation.append({
            "action": "review_disabled_rules",
            "reason": "这些规则行未启用，若属于主市场语言对，需要 VM 启用或新增同名 canonical key。",
            "items": disabled_labels,
        })
    return {
        "ok": not missing,
        "source": meta.get("source"),
        "table_id": meta.get("table_id"),
        "required_count": len(required),
        "available_count": len(available),
        "missing": missing,
        "extra": extra,
        "available": sorted(available),
        "normalized_display_labels": normalized_labels,
        "disabled_display_labels": disabled_labels,
        "remediation": remediation,
        "vm_next_steps": [
            "在飞书「评分规则配置」表检查语言对列。",
            "把 normalized_display_labels 中的 display_label 重命名为 canonical_key。",
            "为 missing 中每个 canonical key 新增启用规则，或把 existing display label 改名到对应 canonical key。",
            "重跑 python3 scripts/verify_pricing_rule_coverage.py；ok=true 后再切正式评分。",
        ],
        "canonical_language_pair_field_aliases": list(LANG_RULE_FIELDS["language_pair"]),
    }


def load_pricing_rule_records_for_diagnostics(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Read raw enabled/disabled labels from the same Lark table for VM remediation."""
    base_token = meta.get("base_token") or ""
    table_id = meta.get("table_id") or ""
    if meta.get("source") != "lark" or not base_token or not table_id:
        return []
    resp = run_lark_cli_json(
        "base", "+record-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--as", "bot",
        "--limit", "500",
        "--format", "json",
    )
    return normalize_record_list_response(resp if isinstance(resp, dict) else {})


def main() -> int:
    try:
        rules, meta = load_price_rules(require_lark_rules=True)
    except PricingRulesError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    try:
        records = load_pricing_rule_records_for_diagnostics(meta)
    except Exception as exc:
        records = []
        meta = {**meta, "diagnostics_warning": f"无法读取原始规则行用于 display label 诊断：{exc}"}
    payload = build_pricing_rule_coverage_payload(rules, meta, records=records)
    if meta.get("diagnostics_warning"):
        payload["diagnostics_warning"] = meta["diagnostics_warning"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not payload["missing"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
