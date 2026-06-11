#!/usr/bin/env python3
"""
schema_gate.py
==============
Lightweight runtime gate for production workflow commands.

It checks config/lark-field-mapping.yaml only. Full Lark table inspection and
field creation are handled by schema_validator.py.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, is_test_mode
from field_resolver import FieldMappingError, load_field_mapping

SKILL_ROOT = Path(__file__).parent.parent
REQUIRED_SCHEMA_PATH = SKILL_ROOT / "references" / "lark-required-schema.yaml"


OPERATION_TABLES = {
    "score": ["candidate", "workflow_log"],
    "test-email": ["candidate", "workflow_log"],
    "contract": ["contract_info", "workflow_log"],
    "waiting": ["workflow_log"],
    "resume": ["workflow_log"],
    "all": ["candidate", "workflow_log", "contract_info"],
}


def load_required_schema() -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("缺少 pyyaml，请先安装 pyyaml") from exc
    return yaml.safe_load(REQUIRED_SCHEMA_PATH.read_text(encoding="utf-8")) or {}


def required_keys_for_table(schema: dict, table_key: str) -> list[str]:
    table = schema.get("tables", {}).get(table_key) or {}
    keys = []
    for field in table.get("required_fields", []):
        if field.get("required", False):
            keys.append(field["key"])
    return keys


def validate_mapping_for(operation: str) -> dict:
    if operation not in OPERATION_TABLES:
        raise RuntimeError(f"未知操作：{operation}")

    schema = load_required_schema()
    issues = []
    try:
        mapping = load_field_mapping()
    except FieldMappingError as exc:
        return {
            "ok": False,
            "operation": operation,
            "issues": [str(exc)],
            "missing_tables": OPERATION_TABLES[operation],
            "missing_fields": {},
        }

    missing_tables = []
    missing_fields = {}
    tables = mapping.get("tables") or {}
    for table_key in OPERATION_TABLES[operation]:
        table = tables.get(table_key)
        if not table or not table.get("base_token") or not table.get("table_id"):
            missing_tables.append(table_key)
            continue

        mapped_fields = table.get("fields") or {}
        for logical_key in required_keys_for_table(schema, table_key):
            field = mapped_fields.get(logical_key) or {}
            if not field.get("field_id"):
                missing_fields.setdefault(table_key, []).append(logical_key)

    for table_key in missing_tables:
        issues.append(f"缺少表映射：{table_key}")
    for table_key, fields in missing_fields.items():
        issues.append(f"{table_key} 缺少必需字段映射：{', '.join(fields)}")

    return {
        "ok": not issues,
        "operation": operation,
        "issues": issues,
        "missing_tables": missing_tables,
        "missing_fields": missing_fields,
    }


def should_enforce_schema_gate(cfg: dict) -> bool:
    if os.environ.get("LOC_SKIP_SCHEMA_GATE") == "1":
        return False
    if os.environ.get("LOC_REQUIRE_SCHEMA_READY") == "1":
        return True
    return not is_test_mode(cfg)


def assert_schema_ready(operation: str):
    cfg = load_config()
    if not should_enforce_schema_gate(cfg):
        return
    result = validate_mapping_for(operation)
    if result["ok"]:
        return
    command = (
        "python3 scripts/schema_validator.py --table all\n"
        "VM 确认差异后再运行：\n"
        "python3 scripts/schema_validator.py --table all --apply --create-missing-tables"
    )
    details = "\n".join(f"- {item}" for item in result["issues"])
    raise RuntimeError(
        "生产表准入未通过，已阻止执行。\n"
        f"{details}\n\n"
        f"请先运行：\n{command}"
    )


def main():
    parser = argparse.ArgumentParser(description="Check schema readiness before production workflow execution")
    parser.add_argument("--for", dest="operation", choices=sorted(OPERATION_TABLES), default="all")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--enforce", action="store_true", help="按生产门禁返回码执行；未通过则 exit=1")
    args = parser.parse_args()

    result = validate_mapping_for(args.operation)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["ok"]:
            print(f"✅ schema gate 通过：{args.operation}")
        else:
            print(f"❌ schema gate 未通过：{args.operation}")
            for item in result["issues"]:
                print(f"- {item}")
            print("\n请先运行：")
            print("python3 scripts/schema_validator.py --table all")
            print("VM 确认差异后再运行：")
            print("python3 scripts/schema_validator.py --table all --apply --create-missing-tables")

    if args.enforce and not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
