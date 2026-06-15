#!/usr/bin/env python3
"""
schema_validator.py
===================
Validate a Lark Base table against the resource-management Agent schema.

Default mode is read-only. Use --apply to create missing fields after explicit
confirmation and refresh config/lark-field-mapping.yaml.
"""

import argparse
import json
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from schema_inspector import list_fields, resolve_table_from_config
from config_loader import load_config, get_lark

SKILL_ROOT = Path(__file__).parent.parent
REQUIRED_SCHEMA_PATH = SKILL_ROOT / "references" / "lark-required-schema.yaml"
MAPPING_PATH = SKILL_ROOT / "config" / "lark-field-mapping.yaml"
FIELD_DICTIONARY_PATH = SKILL_ROOT / "references" / "lark-field-dictionary.md"


def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError:
        raise RuntimeError("缺少 pyyaml，请先安装 pyyaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_yaml(path: Path, data: dict):
    try:
        import yaml
    except ImportError:
        raise RuntimeError("缺少 pyyaml，请先安装 pyyaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def norm(text: str) -> str:
    return "".join(str(text or "").lower().replace("（", "(").replace("）", ")").split())


def name_variants(text: str) -> list[str]:
    """Return normalized variants for exact matching of bilingual table headers."""
    raw = str(text or "").strip()
    parts = [raw]
    for sep in ("|", "｜", "/", "／"):
        if sep in raw:
            parts.append(raw.split(sep, 1)[0].strip())
    seen = set()
    variants = []
    for part in parts:
        key = norm(part)
        if key and key not in seen:
            seen.add(key)
            variants.append(key)
    return variants


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def field_type_matches(actual: str, expected: str, actual_multiple=None, expected_multiple=None) -> bool:
    actual_n = norm(actual)
    expected_n = norm(expected)
    aliases = {
        "text": ["text", "multilinetext", "url", "phone", "email"],
        "number": ["number", "currency", "percent", "rating"],
        "select": ["select", "singleoption", "multioption", "multiselect", "single_select"],
        "datetime": ["datetime", "date", "createdtime", "modifiedtime"],
        "attachment": ["attachment", "file"],
        "checkbox": ["checkbox", "bool", "boolean"],
    }
    allowed = aliases.get(expected_n, [expected_n])
    if not any(x in actual_n for x in allowed):
        return False
    # lark-cli versions differ: some return multiple as bool, some omit it.
    # Treat missing/non-bool multiplicity as acceptable; option shape is a soft check.
    if (
        expected_n == "select"
        and expected_multiple is not None
        and isinstance(actual_multiple, bool)
    ):
        return bool(expected_multiple) == bool(actual_multiple)
    return True


def build_create_payload(field_def: dict) -> dict:
    payload = {
        "name": field_def["name"],
        "type": field_def.get("type", "text"),
    }
    if field_def.get("type") == "select":
        payload["multiple"] = bool(field_def.get("multiple", False))
        options = field_def.get("options", [])
        if options:
            payload["options"] = [{"name": opt} for opt in options]
    return payload


def list_tables(base_token: str) -> list[dict]:
    cmd = [
        "lark-cli", "base", "+table-list",
        "--base-token", base_token,
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    payload = json.loads(result.stdout or "{}")
    data = payload.get("data", payload)
    raw_tables = []
    for key in ("items", "tables", "table_list"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            raw_tables = data[key]
            break
    if not raw_tables and isinstance(payload.get("items"), list):
        raw_tables = payload["items"]
    tables = []
    for table in raw_tables:
        tables.append({
            "table_id": table.get("table_id") or table.get("id") or "",
            "name": table.get("name") or table.get("table_name") or "",
            "raw": table,
        })
    return tables


def base_token_for_missing_table(table_key: str) -> str:
    cfg = load_config()
    schema = load_yaml(REQUIRED_SCHEMA_PATH)
    table = schema.get("tables", {}).get(table_key, {})
    keys = table.get("config_keys", {})
    dotted = keys.get("base_token", "")
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            cur = ""
            break
        cur = cur.get(part, "")
    if cur:
        return cur
    if table_key in ("workflow_log", "contract_info"):
        return get_lark(cfg).get("base_token", "")
    return ""


def build_table_fields(required_fields: list[dict]) -> list[dict]:
    return [
        build_create_payload(field)
        for field in required_fields
        if field.get("create_if_missing", False)
    ]


def extract_created_table_id(payload: dict) -> str:
    data = payload.get("data", payload)
    candidates = [
        data.get("table_id") if isinstance(data, dict) else "",
        data.get("table", {}).get("table_id") if isinstance(data, dict) else "",
        data.get("table", {}).get("id") if isinstance(data, dict) else "",
        data.get("id") if isinstance(data, dict) else "",
    ]
    for value in candidates:
        if value:
            return value
    return ""


def create_missing_table(base_token: str, table_def: dict, yes: bool) -> str:
    table_name = table_def.get("table_name") or table_def.get("desc") or "Agent流程日志"
    fields = build_table_fields(table_def.get("required_fields", []))
    for table in list_tables(base_token):
        if norm(table["name"]) == norm(table_name):
            print(f"\n✅ 已找到同名表：{table_name} ({table['table_id']})")
            return table["table_id"]

    print(f"\n将创建缺失表：{table_name}")
    print(f"字段数：{len(fields)}")
    if not yes:
        ans = input("\n确认创建该表？[y/N] ").strip().lower()
        if ans != "y":
            print("已取消创建表。")
            return ""

    cmd = [
        "lark-cli", "base", "+table-create",
        "--base-token", base_token,
        "--name", table_name,
        "--fields", json.dumps(fields, ensure_ascii=False),
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    payload = json.loads(result.stdout or "{}")
    table_id = extract_created_table_id(payload)
    if not table_id:
        for table in list_tables(base_token):
            if norm(table["name"]) == norm(table_name):
                table_id = table["table_id"]
                break
    if not table_id:
        raise RuntimeError("建表成功但无法解析 table_id，请用 +table-list 手动确认。")
    print(f"✅ 已创建表：{table_name} ({table_id})")
    return table_id


def match_required_field(field_def: dict, actual_fields: list[dict]) -> tuple[dict | None, str, float]:
    names = [field_def.get("name", "")] + field_def.get("aliases", [])
    by_exact = {}
    for field in actual_fields:
        for variant in name_variants(field["name"]):
            by_exact.setdefault(variant, field)
    for name in names:
        for variant in name_variants(name):
            if variant in by_exact:
                return by_exact[variant], "exact", 1.0

    best = None
    best_score = 0.0
    best_name = ""
    for name in names:
        for field in actual_fields:
            score = similarity(name, field["name"])
            if score > best_score:
                best = field
                best_score = score
                best_name = name
    if best and best_score >= 0.72:
        return best, f"fuzzy:{best_name}", best_score
    return None, "missing", 0.0


def validate_table(table_key: str, base_token: str, table_id: str, actual_fields: list[dict], required_fields: list[dict]) -> dict:
    mapped = {}
    missing = []
    fuzzy = []
    type_mismatches = []
    matched_actual_ids = set()

    for req in required_fields:
        found, match_type, score = match_required_field(req, actual_fields)
        if not found:
            if req.get("required", False) or req.get("create_if_missing", False):
                missing.append(req)
            continue

        matched_actual_ids.add(found["field_id"])
        mapped[req["key"]] = {
            "field_id": found["field_id"],
            "field_name": found["name"],
            "expected_name": req["name"],
            "match_type": match_type,
            "match_score": round(score, 3),
            "expected_type": req.get("type", "text"),
            "actual_type": found.get("type", ""),
        }
        if match_type.startswith("fuzzy"):
            fuzzy.append((req, found, score))
        if not field_type_matches(
            found.get("type", ""),
            req.get("type", "text"),
            found.get("multiple"),
            req.get("multiple"),
        ):
            type_mismatches.append((req, found))

    extra = [f for f in actual_fields if f.get("field_id") not in matched_actual_ids]

    return {
        "table_key": table_key,
        "base_token": base_token,
        "table_id": table_id,
        "mapped": mapped,
        "missing": missing,
        "fuzzy": fuzzy,
        "type_mismatches": type_mismatches,
        "extra": extra,
    }


def create_missing_fields(base_token: str, table_id: str, missing: list[dict], yes: bool) -> list[dict]:
    if not missing:
        return []
    print("\n将创建以下缺失字段：")
    for item in missing:
        print(f"- {item['name']} ({item.get('type', 'text')})")
    if not yes:
        ans = input("\n确认创建这些字段？[y/N] ").strip().lower()
        if ans != "y":
            print("已取消创建字段。")
            return []

    created = []
    for item in missing:
        payload = build_create_payload(item)
        cmd = [
            "lark-cli", "base", "+field-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps(payload, ensure_ascii=False),
            "--format", "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            print(f"❌ 创建失败：{item['name']} → {(result.stderr or result.stdout).strip()}")
            continue
        print(f"✅ 已创建字段：{item['name']}")
        created.append(item)
    return created


def print_report(result: dict):
    print(f"\n{'=' * 72}")
    print(f"表：{result['table_key']}  {result['table_id']}")
    print(f"{'=' * 72}")

    if result.get("error"):
        print(f"\n❌ 表结构读取失败：{result['error']}")
        print("建议：确认 config.yaml 中对应 base_token/table_id 是否指向当前生产表。")
        return

    print(f"\n已映射字段：{len(result['mapped'])}")
    for key, val in result["mapped"].items():
        print(f"  ✅ {key} -> {val['field_name']} ({val['field_id']}) [{val['match_type']}]")

    print(f"\n缺失字段：{len(result['missing'])}")
    for item in result["missing"]:
        is_required = item.get("required")
        level = "必需" if is_required else "建议"
        icon = "❌" if is_required else "⚠️ "
        print(f"  {icon} {item['key']} / {item['name']} ({item.get('type', 'text')}, {level})")
    if result["missing"]:
        print(f"  字段用途说明：{FIELD_DICTIONARY_PATH}")

    print(f"\n疑似匹配字段：{len(result['fuzzy'])}")
    for req, found, score in result["fuzzy"]:
        print(f"  ⚠️  {req['key']} 期望「{req['name']}」≈ 当前「{found['name']}」 score={score:.2f}")

    print(f"\n类型不匹配：{len(result['type_mismatches'])}")
    for req, found in result["type_mismatches"]:
        print(f"  ❌ {req['key']} 当前「{found['name']}」类型={found.get('type')}，期望={req.get('type')}")

    print(f"\n多余字段：{len(result['extra'])}")
    for field in result["extra"][:30]:
        print(f"  - {field['name']} ({field['field_id']})")
    if len(result["extra"]) > 30:
        print(f"  ... 还有 {len(result['extra']) - 30} 个")


def save_mapping(table_results: list[dict]):
    mapping = {
        "schema_version": "1.0",
        "generated_by": "schema_validator.py",
        "tables": {},
    }
    if MAPPING_PATH.exists():
        try:
            existing = load_yaml(MAPPING_PATH) or {}
            mapping["tables"].update(existing.get("tables") or {})
        except Exception:
            pass
    for result in table_results:
        mapping["tables"][result["table_key"]] = {
            "base_token": result["base_token"],
            "table_id": result["table_id"],
            "fields": result["mapped"],
        }
    write_yaml(MAPPING_PATH, mapping)
    print(f"\n✅ 映射已写入：{MAPPING_PATH}")


def main():
    parser = argparse.ArgumentParser(description="Validate Lark table schema for loc-resume-screening")
    parser.add_argument("--table", choices=["candidate", "pricing_rules", "workflow_log", "contract_info", "all"], default="candidate")
    parser.add_argument("--base-token", help="自定义 base token，仅 --table 非 all 时可用")
    parser.add_argument("--table-id", help="自定义 table id，仅 --table 非 all 时可用")
    parser.add_argument("--apply", action="store_true", help="创建缺失字段并重新生成映射")
    parser.add_argument(
        "--create-missing-tables",
        action="store_true",
        help="配合 --apply 创建 schema 允许自动创建的辅助表（当前仅流程日志表）",
    )
    parser.add_argument("--yes", action="store_true", help="配合 --apply 跳过确认")
    args = parser.parse_args()

    schema = load_yaml(REQUIRED_SCHEMA_PATH)
    table_keys = list(schema.get("tables", {}).keys()) if args.table == "all" else [args.table]
    results = []

    for table_key in table_keys:
        table_def = schema["tables"][table_key]
        try:
            if args.base_token and args.table_id and args.table != "all":
                base_token, table_id = args.base_token, args.table_id
            else:
                base_token, table_id = resolve_table_from_config(table_key)
        except Exception as e:
            if (
                args.apply
                and args.create_missing_tables
                and table_def.get("create_if_missing_table", False)
            ):
                try:
                    base_token = base_token_for_missing_table(table_key)
                    if not base_token:
                        raise RuntimeError(f"{table_key} 缺少 base_token，无法创建表")
                    table_id = create_missing_table(base_token, table_def, yes=args.yes)
                    actual_fields = list_fields(base_token, table_id)
                    result = validate_table(
                        table_key=table_key,
                        base_token=base_token,
                        table_id=table_id,
                        actual_fields=actual_fields,
                        required_fields=table_def.get("required_fields", []),
                    )
                    print_report(result)
                    results.append(result)
                    continue
                except Exception as create_error:
                    e = create_error
            result = {
                "table_key": table_key,
                "base_token": "",
                "table_id": "",
                "mapped": {},
                "missing": table_def.get("required_fields", []),
                "fuzzy": [],
                "type_mismatches": [],
                "extra": [],
                "error": str(e),
            }
            print_report(result)
            results.append(result)
            continue

        try:
            actual_fields = list_fields(base_token, table_id)
        except Exception as e:
            if (
                args.apply
                and args.create_missing_tables
                and table_def.get("create_if_missing_table", False)
            ):
                try:
                    table_id = create_missing_table(base_token, table_def, yes=args.yes)
                    actual_fields = list_fields(base_token, table_id)
                    result = validate_table(
                        table_key=table_key,
                        base_token=base_token,
                        table_id=table_id,
                        actual_fields=actual_fields,
                        required_fields=table_def.get("required_fields", []),
                    )
                    print_report(result)
                    results.append(result)
                    continue
                except Exception as create_error:
                    e = create_error
            result = {
                "table_key": table_key,
                "base_token": base_token,
                "table_id": table_id,
                "mapped": {},
                "missing": table_def.get("required_fields", []),
                "fuzzy": [],
                "type_mismatches": [],
                "extra": [],
                "error": str(e),
            }
            print_report(result)
            results.append(result)
            continue

        result = validate_table(
            table_key=table_key,
            base_token=base_token,
            table_id=table_id,
            actual_fields=actual_fields,
            required_fields=table_def.get("required_fields", []),
        )
        print_report(result)

        if args.apply and result["missing"]:
            create_missing_fields(base_token, table_id, result["missing"], yes=args.yes)
            actual_fields = list_fields(base_token, table_id)
            result = validate_table(
                table_key=table_key,
                base_token=base_token,
                table_id=table_id,
                actual_fields=actual_fields,
                required_fields=table_def.get("required_fields", []),
            )
            print("\n创建字段后重新校验：")
            print_report(result)

        results.append(result)

    hard_failures = sum(
        (1 if r.get("error") else 0)
        + len([item for item in r["missing"] if item.get("required")])
        + len(r["type_mismatches"])
        for r in results
    )

    mapping_write_failed = False
    if hard_failures:
        print("\n⚠️  准入未通过，暂不写入字段映射。请先处理上面的必需缺口或类型错误。")
    elif args.apply:
        try:
            save_mapping(results)
        except PermissionError as e:
            mapping_write_failed = True
            print(f"\n❌ 映射写入失败：{MAPPING_PATH}")
            print(f"原因：没有写入权限（{e}）")
            print("建议：确认当前用户有 skill 目录写权限，或在本机 OpenClaw 环境中重新运行。")
    else:
        print(f"\nℹ️  只读校验模式：未写入字段映射。需要刷新映射时请加 --apply。")

    if mapping_write_failed:
        hard_failures += 1
    if hard_failures:
        print(f"\n❌ 准入校验未通过：仍有 {hard_failures} 个必需缺口或类型错误。")
        sys.exit(1)

    print("\n✅ 准入校验通过：当前表结构可用于后续内部流程校验。")


if __name__ == "__main__":
    main()
