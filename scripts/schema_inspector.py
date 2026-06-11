#!/usr/bin/env python3
"""
schema_inspector.py
===================
Read a Lark Base table schema and print normalized field metadata.

Usage:
  python3 scripts/schema_inspector.py --base-token <base> --table-id <tbl>
  python3 scripts/schema_inspector.py --table candidate
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_lark


def _get_nested(config: dict, dotted_key: str) -> str:
    cur = config
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(part, "")
    return cur or ""


def _load_required_schema() -> dict:
    try:
        import yaml
    except ImportError:
        raise RuntimeError("缺少 pyyaml，请先安装 pyyaml")
    path = Path(__file__).parent.parent / "references" / "lark-required-schema.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _table_ref_from_mapping(table_key: str) -> tuple[str, str]:
    try:
        import yaml
    except ImportError:
        return "", ""
    path = Path(__file__).parent.parent / "config" / "lark-field-mapping.yaml"
    if not path.exists():
        return "", ""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", ""
    table = (data.get("tables") or {}).get(table_key) or {}
    return table.get("base_token", ""), table.get("table_id", "")


def resolve_table_from_config(table_key: str) -> tuple[str, str]:
    schema = _load_required_schema()
    table = schema.get("tables", {}).get(table_key)
    if not table:
        raise RuntimeError(f"required schema 中不存在表：{table_key}")

    cfg = load_config()
    keys = table.get("config_keys", {})
    base_token = _get_nested(cfg, keys.get("base_token", ""))
    table_id = _get_nested(cfg, keys.get("table_id", ""))

    if table_key == "workflow_log" and not table_id:
        mapped_base, mapped_table = _table_ref_from_mapping(table_key)
        base_token = mapped_base or base_token
        table_id = mapped_table or table_id

    if not base_token and table_key == "contract_info":
        base_token = get_lark(cfg).get("base_token", "")

    if not base_token or not table_id:
        raise RuntimeError(f"{table_key} 缺少 base_token/table_id 配置")
    return base_token, table_id


def list_fields(base_token: str, table_id: str) -> list[dict]:
    cmd = [
        "lark-cli", "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--format", "json",
        "--limit", "200",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    payload = json.loads(result.stdout or "{}")
    return normalize_fields(payload)


def normalize_fields(payload: dict) -> list[dict]:
    data = payload.get("data", payload)
    raw_fields = []
    for key in ("items", "fields", "field_list"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            raw_fields = data[key]
            break
    if not raw_fields and isinstance(payload.get("items"), list):
        raw_fields = payload["items"]

    fields = []
    for field in raw_fields:
        name = field.get("field_name") or field.get("name") or field.get("text") or ""
        field_id = field.get("field_id") or field.get("id") or ""
        field_type = field.get("type") or field.get("ui_type") or field.get("property", {}).get("type") or ""
        multiple = field.get("multiple")
        options = []
        prop = field.get("property") or {}
        for opt in prop.get("options", []) or field.get("options", []) or []:
            if isinstance(opt, dict):
                options.append(opt.get("name") or opt.get("text") or "")
            else:
                options.append(str(opt))
        fields.append({
            "field_id": field_id,
            "name": name,
            "type": str(field_type),
            "multiple": multiple,
            "options": [o for o in options if o],
            "raw": field,
        })
    return fields


def main():
    parser = argparse.ArgumentParser(description="Inspect Lark Base table fields")
    parser.add_argument("--table", choices=["candidate", "pricing_rules", "workflow_log", "contract_info"], help="从 config.yaml 读取对应表")
    parser.add_argument("--base-token", help="Base token")
    parser.add_argument("--table-id", help="Table ID")
    args = parser.parse_args()

    if args.table:
        base_token, table_id = resolve_table_from_config(args.table)
    else:
        if not args.base_token or not args.table_id:
            parser.error("请提供 --table 或 --base-token + --table-id")
        base_token, table_id = args.base_token, args.table_id

    fields = list_fields(base_token, table_id)
    print(json.dumps({
        "base_token": base_token,
        "table_id": table_id,
        "field_count": len(fields),
        "fields": fields,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
