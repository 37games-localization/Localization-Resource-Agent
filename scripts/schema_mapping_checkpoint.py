#!/usr/bin/env python3
"""
schema_mapping_checkpoint.py
============================
Human-confirmed Lark schema mapping workflow.

This is the checkpoint layer above schema_validator.py:
- propose: inspect Lark tables and save a mapping proposal locally
- adjust: let VM override specific logical-field -> Lark-field mappings
- confirm: persist the confirmed proposal to config/lark-field-mapping.yaml

It does not replace schema_validator.py. The validator remains the deterministic
schema engine; this file adds human review before a mapping becomes effective.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from schema_inspector import list_fields, resolve_table_from_config
from schema_validator import (
    FIELD_DICTIONARY_PATH,
    MAPPING_PATH,
    REQUIRED_SCHEMA_PATH,
    create_missing_fields,
    load_existing_mapping,
    load_yaml,
    validate_table,
    write_yaml,
)


CHECKPOINT_DIR = Path.home() / ".loc-resume-schema-checkpoints"


def checkpoint_token() -> str:
    return f"schema-{time.strftime('%Y%m%d%H%M%S')}"


def checkpoint_path(token: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", token)
    return CHECKPOINT_DIR / f"{safe}.json"


def field_purpose(table_key: str, logical_key: str, schema: dict[str, Any]) -> str:
    table = (schema.get("tables") or {}).get(table_key) or {}
    for field in table.get("required_fields", []):
        if field.get("key") == logical_key:
            required = "必需" if field.get("required") else "可选"
            return f"{field.get('name', logical_key)} / {field.get('type', 'text')} / {required}"
    return logical_key


def table_status(result: dict[str, Any]) -> str:
    if result.get("error"):
        return "blocked"
    if result.get("type_mismatches"):
        return "blocked"
    required_missing = [item for item in result.get("missing", []) if item.get("required")]
    if required_missing:
        return "blocked"
    if result.get("fuzzy"):
        return "needs_review"
    if result.get("missing"):
        return "needs_review"
    return "ready"


def proposal_table_from_result(result: dict[str, Any], actual_fields: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    mapped = []
    for key, value in sorted(result.get("mapped", {}).items()):
        mapped.append({
            "logical_key": key,
            "purpose": field_purpose(result["table_key"], key, schema),
            "field_id": value.get("field_id", ""),
            "field_name": value.get("field_name", ""),
            "expected_name": value.get("expected_name", ""),
            "match_type": value.get("match_type", ""),
            "match_score": value.get("match_score", 0),
            "expected_type": value.get("expected_type", ""),
            "actual_type": value.get("actual_type", ""),
            "confirmed": not str(value.get("match_type", "")).startswith("fuzzy"),
        })

    fuzzy = []
    for req, found, score in result.get("fuzzy", []):
        fuzzy.append({
            "logical_key": req.get("key", ""),
            "expected_name": req.get("name", ""),
            "field_name": found.get("name", ""),
            "field_id": found.get("field_id", ""),
            "score": round(score, 3),
            "purpose": field_purpose(result["table_key"], req.get("key", ""), schema),
        })

    return {
        "table_key": result["table_key"],
        "base_token": result.get("base_token", ""),
        "table_id": result.get("table_id", ""),
        "status": table_status(result),
        "mapped": mapped,
        "missing": [
            {
                "logical_key": item.get("key", ""),
                "expected_name": item.get("name", ""),
                "type": item.get("type", "text"),
                "required": bool(item.get("required")),
                "create_if_missing": bool(item.get("create_if_missing")),
                "purpose": field_purpose(result["table_key"], item.get("key", ""), schema),
            }
            for item in result.get("missing", [])
        ],
        "fuzzy": fuzzy,
        "type_mismatches": [
            {
                "logical_key": req.get("key", ""),
                "expected_name": req.get("name", ""),
                "field_name": found.get("name", ""),
                "field_id": found.get("field_id", ""),
                "expected_type": req.get("type", "text"),
                "actual_type": found.get("type", ""),
            }
            for req, found in result.get("type_mismatches", [])
        ],
        "extra": [
            {
                "field_id": field.get("field_id", ""),
                "field_name": field.get("name", ""),
                "type": field.get("type", ""),
            }
            for field in result.get("extra", [])[:80]
        ],
        "actual_fields": [
            {
                "field_id": field.get("field_id", ""),
                "field_name": field.get("name", ""),
                "type": field.get("type", ""),
            }
            for field in actual_fields
        ],
        "error": result.get("error", ""),
    }


def hard_failures(proposal: dict[str, Any]) -> list[str]:
    failures = []
    for table in proposal.get("tables", []):
        if table.get("error"):
            failures.append(f"{table['table_key']}: {table['error']}")
        for item in table.get("missing", []):
            if item.get("required"):
                failures.append(f"{table['table_key']}.{item['logical_key']}: 缺少必需字段 {item['expected_name']}")
        for item in table.get("type_mismatches", []):
            failures.append(
                f"{table['table_key']}.{item['logical_key']}: 类型不匹配 {item['actual_type']} != {item['expected_type']}"
            )
    return failures


def proposal_status(proposal: dict[str, Any]) -> str:
    failures = hard_failures(proposal)
    if failures:
        return "blocked"
    if any(table.get("fuzzy") or table.get("missing") for table in proposal.get("tables", [])):
        return "needs_review"
    return "ready"


def build_mapping_from_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "schema_version": "1.0",
        "generated_by": "schema_mapping_checkpoint.py",
        "tables": {},
    }
    if MAPPING_PATH.exists():
        try:
            existing = load_yaml(MAPPING_PATH) or {}
            mapping["tables"].update(existing.get("tables") or {})
        except Exception:
            pass

    for table in proposal.get("tables", []):
        fields = {}
        for item in table.get("mapped", []):
            fields[item["logical_key"]] = {
                "field_id": item["field_id"],
                "field_name": item["field_name"],
                "expected_name": item.get("expected_name", ""),
                "match_type": item.get("match_type", "confirmed"),
                "match_score": item.get("match_score", 1.0),
                "expected_type": item.get("expected_type", ""),
                "actual_type": item.get("actual_type", ""),
            }
        mapping["tables"][table["table_key"]] = {
            "base_token": table.get("base_token", ""),
            "table_id": table.get("table_id", ""),
            "fields": fields,
        }
    return mapping


def save_proposal(proposal: dict[str, Any]) -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_path(proposal["checkpoint_token"]).write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_proposal(token: str) -> dict[str, Any]:
    path = checkpoint_path(token)
    if not path.exists():
        raise SystemExit(f"checkpoint 不存在：{token}")
    return json.loads(path.read_text(encoding="utf-8"))


def find_actual_field(table: dict[str, Any], hint: str) -> dict[str, Any] | None:
    hint_norm = normalize(hint)
    for field in table.get("actual_fields", []):
        if field.get("field_id") == hint:
            return field
        if normalize(field.get("field_name", "")) == hint_norm:
            return field
    for field in table.get("actual_fields", []):
        if hint_norm and hint_norm in normalize(field.get("field_name", "")):
            return field
    return None


def normalize(text: str) -> str:
    return "".join(str(text or "").lower().replace("（", "(").replace("）", ")").split())


def set_mapping(proposal: dict[str, Any], logical_key: str, field_hint: str, note: str = "") -> bool:
    table_key = logical_key.split(".", 1)[0]
    table_alias = {"contract": "contract_info", "workflow": "workflow_log", "pricing": "pricing_rules"}.get(table_key, table_key)
    for table in proposal.get("tables", []):
        if table["table_key"] not in {table_key, table_alias}:
            continue
        actual = find_actual_field(table, field_hint)
        if not actual:
            return False
        current = next((item for item in table.get("mapped", []) if item["logical_key"] == logical_key), None)
        if current:
            current.update({
                "field_id": actual["field_id"],
                "field_name": actual["field_name"],
                "actual_type": actual.get("type", ""),
                "match_type": "vm_override",
                "match_score": 1.0,
                "confirmed": True,
                "vm_note": note,
            })
        else:
            current = {
                "logical_key": logical_key,
                "purpose": logical_key,
                "field_id": actual["field_id"],
                "field_name": actual["field_name"],
                "expected_name": logical_key,
                "match_type": "vm_override",
                "match_score": 1.0,
                "expected_type": "",
                "actual_type": actual.get("type", ""),
                "confirmed": True,
                "vm_note": note,
            }
            table.setdefault("mapped", []).append(current)
        table["fuzzy"] = [item for item in table.get("fuzzy", []) if item.get("logical_key") != logical_key]
        table["missing"] = [item for item in table.get("missing", []) if item.get("logical_key") != logical_key]
        return True
    return False


def parse_adjustments(text: str) -> list[tuple[str, str]]:
    """Parse simple natural-language overrides.

    Supported examples:
    - candidate.resume=简历附件
    - 把 candidate.resume 映射到 简历附件
    - 将 contract.email 改成 常用工作邮箱
    """
    items: list[tuple[str, str]] = []
    for logical_key, field_hint in re.findall(r"([a-z]+(?:_[a-z]+)?\.[a-z0-9_]+)\s*=\s*([^,，\n]+)", text):
        items.append((logical_key.strip(), field_hint.strip(" 「」\"'")))
    pattern = re.compile(
        r"(?:把|将)\s*([a-z]+(?:_[a-z]+)?\.[a-z0-9_]+)\s*(?:映射到|改成|设为|对应到)\s*([^,，。\n]+)"
    )
    for logical_key, field_hint in pattern.findall(text):
        items.append((logical_key.strip(), field_hint.strip(" 「」\"'")))
    return items


def human_summary(proposal: dict[str, Any]) -> str:
    lines = [
        f"Schema Mapping Checkpoint: {proposal['checkpoint_token']}",
        f"状态：{proposal['status']}",
        "",
        "请 VM 核对：左侧为 Agent 内部字段，右侧为当前 Lark 表字段。确认后才会保存映射。",
        "",
    ]
    for table in proposal.get("tables", []):
        lines.append(f"## {table['table_key']} ({table.get('table_id', '')}) - {table.get('status')}")
        if table.get("error"):
            lines.append(f"- 读取失败：{table['error']}")
            continue
        if table.get("fuzzy"):
            lines.append("- 需要确认的疑似映射：")
            for item in table["fuzzy"][:12]:
                lines.append(
                    f"  - {item['logical_key']} / {item['purpose']} -> {item['field_name']} "
                    f"(score={item['score']})"
                )
        if table.get("missing"):
            lines.append("- 缺失字段：")
            for item in table["missing"][:12]:
                level = "必需" if item.get("required") else "建议"
                lines.append(f"  - {item['logical_key']} / {item['expected_name']} ({level})")
        lines.append("- 已映射字段：")
        for item in table.get("mapped", [])[:16]:
            mark = "?" if not item.get("confirmed") else "OK"
            lines.append(f"  - [{mark}] {item['logical_key']} -> {item['field_name']} ({item['match_type']})")
        lines.append("")
    lines.append(f"字段用途说明：{FIELD_DICTIONARY_PATH}")
    return "\n".join(lines)


def propose(args: argparse.Namespace) -> dict[str, Any]:
    schema = load_yaml(REQUIRED_SCHEMA_PATH)
    existing_mapping = load_existing_mapping()
    table_keys = list(schema.get("tables", {}).keys()) if args.table == "all" else [args.table]
    tables = []

    for table_key in table_keys:
        table_def = schema["tables"][table_key]
        try:
            base_token, table_id = resolve_table_from_config(table_key)
            actual_fields = list_fields(base_token, table_id)
            result = validate_table(
                table_key=table_key,
                base_token=base_token,
                table_id=table_id,
                actual_fields=actual_fields,
                required_fields=table_def.get("required_fields", []),
                existing_mapping=existing_mapping,
            )
            if args.create_missing_fields and result.get("missing"):
                create_missing_fields(base_token, table_id, result["missing"], yes=args.yes)
                actual_fields = list_fields(base_token, table_id)
                result = validate_table(
                    table_key=table_key,
                    base_token=base_token,
                    table_id=table_id,
                    actual_fields=actual_fields,
                    required_fields=table_def.get("required_fields", []),
                    existing_mapping=existing_mapping,
                )
        except Exception as exc:
            actual_fields = []
            result = {
                "table_key": table_key,
                "base_token": "",
                "table_id": "",
                "mapped": {},
                "missing": table_def.get("required_fields", []),
                "fuzzy": [],
                "type_mismatches": [],
                "extra": [],
                "error": str(exc),
            }
        tables.append(proposal_table_from_result(result, actual_fields, schema))

    proposal = {
        "checkpoint_token": checkpoint_token(),
        "created_at": int(time.time() * 1000),
        "status": "needs_review",
        "tables": tables,
        "field_dictionary": str(FIELD_DICTIONARY_PATH),
        "mapping_path": str(MAPPING_PATH),
    }
    proposal["status"] = proposal_status(proposal)
    proposal["hard_failures"] = hard_failures(proposal)
    proposal["summary"] = human_summary(proposal)
    save_proposal(proposal)
    return proposal


def adjust(args: argparse.Namespace) -> dict[str, Any]:
    proposal = load_proposal(args.token)
    raw_adjustments = []
    for item in args.set or []:
        if "=" not in item:
            raise SystemExit(f"--set 格式错误，应为 logical.key=字段名：{item}")
        logical_key, field_hint = item.split("=", 1)
        raw_adjustments.append((logical_key.strip(), field_hint.strip()))
    if args.note:
        raw_adjustments.extend(parse_adjustments(args.note))
    if not raw_adjustments:
        raise SystemExit("没有识别到映射调整。示例：--set candidate.resume=简历附件")

    failed = []
    applied = []
    for logical_key, field_hint in raw_adjustments:
        ok = set_mapping(proposal, logical_key, field_hint, note=args.note or "")
        if ok:
            applied.append({"logical_key": logical_key, "field_hint": field_hint})
        else:
            failed.append({"logical_key": logical_key, "field_hint": field_hint})
    proposal["status"] = proposal_status(proposal)
    proposal["hard_failures"] = hard_failures(proposal)
    proposal["last_adjustment"] = {"applied": applied, "failed": failed, "note": args.note or ""}
    proposal["summary"] = human_summary(proposal)
    save_proposal(proposal)
    return proposal


def confirm(args: argparse.Namespace) -> dict[str, Any]:
    proposal = load_proposal(args.token)
    failures = hard_failures(proposal)
    if failures and not args.force:
        return {
            "ok": False,
            "checkpoint_token": args.token,
            "status": "blocked",
            "hard_failures": failures,
            "message": "仍有必需缺口或类型错误，未写入映射。修复后再次确认。",
        }
    mapping = build_mapping_from_proposal(proposal)
    write_yaml(MAPPING_PATH, mapping)
    proposal["status"] = "confirmed"
    proposal["confirmed_at"] = int(time.time() * 1000)
    save_proposal(proposal)
    return {
        "ok": True,
        "checkpoint_token": args.token,
        "status": "confirmed",
        "mapping_path": str(MAPPING_PATH),
        "message": "字段映射已确认并写入。",
    }


def print_result(payload: dict[str, Any], json_only: bool = False) -> None:
    if json_only:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if "summary" in payload:
        print(payload["summary"])
        print("\n机器可读 JSON：")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Human-confirmed Lark schema mapping checkpoint")
    sub = parser.add_subparsers(dest="command", required=True)

    p_propose = sub.add_parser("propose", help="生成字段映射 checkpoint，不直接保存映射")
    p_propose.add_argument("--table", choices=["candidate", "pricing_rules", "workflow_log", "contract_info", "all"], default="all")
    p_propose.add_argument("--create-missing-fields", action="store_true", help="创建缺失字段后再生成 checkpoint")
    p_propose.add_argument("--yes", action="store_true", help="创建字段时跳过交互确认")
    p_propose.add_argument("--json", action="store_true", help="仅输出 JSON")

    p_adjust = sub.add_parser("adjust", help="根据 VM 描述调整 checkpoint 映射")
    p_adjust.add_argument("--token", required=True)
    p_adjust.add_argument("--set", action="append", help="覆盖映射，如 candidate.resume=简历附件")
    p_adjust.add_argument("--note", help="VM 自然语言修正说明")
    p_adjust.add_argument("--json", action="store_true", help="仅输出 JSON")

    p_confirm = sub.add_parser("confirm", help="确认 checkpoint 并写入 lark-field-mapping.yaml")
    p_confirm.add_argument("--token", required=True)
    p_confirm.add_argument("--force", action="store_true", help="维护者强制确认，忽略 hard failures")
    p_confirm.add_argument("--json", action="store_true", help="仅输出 JSON")

    args = parser.parse_args()
    if args.command == "propose":
        payload = propose(args)
    elif args.command == "adjust":
        payload = adjust(args)
    else:
        payload = confirm(args)
    print_result(payload, json_only=getattr(args, "json", False))
    return 0 if payload.get("status") != "blocked" and payload.get("ok", True) is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
