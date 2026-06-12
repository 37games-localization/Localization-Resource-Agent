#!/usr/bin/env python3
"""
Seed sanitized demo contract records into the configured Lark contract table.

This is a demo/test-data helper. It reads demo_fixtures/candidates.json and
creates or updates only fictional records whose contract.info_record_id is set.
The Badcase fixture intentionally has missing contract info and is skipped.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config, get_table_ref
from field_resolver import field_id_or
from lark_cli_utils import normalize_record_list_response, run_lark_cli_json


ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "demo_fixtures" / "candidates.json"

FIELDS = {
    "name": field_id_or("contract_info", "contract.name", "fld2JEyq9H"),
    "email": field_id_or("contract_info", "contract.email", "fldYELKkKa"),
    "id_number": field_id_or("contract_info", "contract.id_number", "fld3hdHuVd"),
    "address": field_id_or("contract_info", "contract.address", "fld8P0lZhg"),
    "phone": field_id_or("contract_info", "contract.phone", "fldu4lmuce"),
    "account_type": field_id_or("contract_info", "contract.account_type", "fld043Vzeo"),
    "personal_account_name": field_id_or("contract_info", "contract.bank_account_name", "fldvZMzuk3"),
    "personal_account_number": field_id_or("contract_info", "contract.bank_account_number", "fld7CGT1GH"),
    "personal_bank_name": field_id_or("contract_info", "contract.bank_name", "fldyPyrLdp"),
    "personal_bank_address": field_id_or("contract_info", "contract.bank_address", "fldDLk0Jh9"),
    "company_account_name": field_id_or("contract_info", "contract.company_bank_account_name", "fldfQSK0Lb"),
    "company_account_number": field_id_or("contract_info", "contract.company_bank_account_number", "fldIi83yp3"),
    "company_bank_name": field_id_or("contract_info", "contract.company_bank_name", "fldq0pIMo3"),
    "company_bank_address": field_id_or("contract_info", "contract.company_bank_address", "fld6xRZDjM"),
    "swift": field_id_or("contract_info", "contract.swift", "fld4ENGLJM"),
    "currency": field_id_or("contract_info", "contract.currency", "fldSZE1Shy"),
    "currency_other": field_id_or("contract_info", "contract.currency_other", "fldAvjeC5F"),
}


def load_fixtures() -> list[dict]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data.get("candidates", [])


def text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(text(item) for item in value if text(item)).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value).strip()


def list_existing(base_token: str, table_id: str) -> dict[str, str]:
    resp = run_lark_cli_json(
        "base", "+record-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--limit", "500",
        "--format", "json",
    )
    records = normalize_record_list_response(resp)
    by_key = {}
    for rec in records:
        fields = rec.get("fields", {})
        record_id = rec.get("record_id", "")
        name = text(fields.get(FIELDS["name"]))
        email = text(fields.get(FIELDS["email"]))
        for key in (name, email):
            if key and record_id:
                by_key[key.lower()] = record_id
    return by_key


def currency_fields(currency: str) -> dict:
    value = (currency or "").upper()
    if value in {"CNY", "RMB"}:
        return {
            FIELDS["currency"]: "人民币（CNY）",
            FIELDS["currency_other"]: "",
        }
    if value == "USD":
        return {
            FIELDS["currency"]: "美元 USD",
            FIELDS["currency_other"]: "",
        }
    return {
        FIELDS["currency"]: "其他 Other",
        FIELDS["currency_other"]: value or "OTHER",
    }


def demo_record(candidate: dict) -> dict | None:
    contract = candidate.get("contract") or {}
    info_record_id = contract.get("info_record_id") or ""
    if not info_record_id:
        return None

    name = candidate["name"]
    email = candidate["email"]
    region = contract.get("region", "overseas")
    currency = contract.get("currency", "USD")
    payee_type = contract.get("payee_type", "individual")

    record = {
        FIELDS["name"]: name,
        FIELDS["email"]: email,
        FIELDS["id_number"]: f"DEMO-ID-{candidate['record_id']}",
        FIELDS["address"]: f"Demo address for {candidate['location']}",
        FIELDS["phone"]: "+00000000000",
        FIELDS["swift"]: "DEMOUS00XXX",
    }
    record.update(currency_fields(currency))

    if payee_type == "company":
        record.update({
            FIELDS["account_type"]: "公司账户 Business account",
            FIELDS["company_account_name"]: name,
            FIELDS["company_account_number"]: f"DEMO-BIZ-{candidate['record_id']}",
            FIELDS["company_bank_name"]: "Demo Global Business Bank",
            FIELDS["company_bank_address"]: f"Demo branch, {candidate['location']}",
            FIELDS["personal_account_name"]: "",
            FIELDS["personal_account_number"]: "",
            FIELDS["personal_bank_name"]: "",
            FIELDS["personal_bank_address"]: "",
        })
    else:
        if region == "domestic":
            bank_name = "中国银行"
            bank_address = "北京市朝阳区 Demo Branch"
            id_number = "110101199003071234"
        else:
            bank_name = "Demo International Bank"
            bank_address = f"Demo overseas branch, {candidate['location']}"
            id_number = f"DEMO-PASSPORT-{candidate['record_id']}"
        record.update({
            FIELDS["account_type"]: "个人账户 Personal account",
            FIELDS["id_number"]: id_number,
            FIELDS["personal_account_name"]: name,
            FIELDS["personal_account_number"]: f"DEMO-PER-{candidate['record_id']}",
            FIELDS["personal_bank_name"]: bank_name,
            FIELDS["personal_bank_address"]: bank_address,
            FIELDS["company_account_name"]: "",
            FIELDS["company_account_number"]: "",
            FIELDS["company_bank_name"]: "",
            FIELDS["company_bank_address"]: "",
        })

    return record


def upsert_record(base_token: str, table_id: str, fields: dict, record_id: str = "", dry_run: bool = False):
    cmd = [
        "lark-cli", "base", "+record-upsert",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps(fields, ensure_ascii=False),
        "--format", "json",
    ]
    if record_id:
        cmd.extend(["--record-id", record_id])
    if dry_run:
        print(json.dumps({
            "action": "update" if record_id else "create",
            "record_id": record_id,
            "fields": fields,
        }, ensure_ascii=False, indent=2))
        return None
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout or "{}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed sanitized demo contract info into Lark.")
    parser.add_argument("--dry-run", action="store_true", help="print records without writing Lark")
    args = parser.parse_args()

    cfg = load_config()
    base_token, table_id = get_table_ref(cfg, "contract_info")
    if not base_token or not table_id:
        raise SystemExit("contract_info table is not configured")

    existing = {} if args.dry_run else list_existing(base_token, table_id)
    created = updated = skipped = 0

    for candidate in load_fixtures():
        fields = demo_record(candidate)
        if not fields:
            skipped += 1
            print(f"skip {candidate.get('record_id')}: missing contract info by design")
            continue
        name = text(fields[FIELDS["name"]])
        email = text(fields[FIELDS["email"]])
        record_id = existing.get(name.lower()) or existing.get(email.lower()) or ""
        upsert_record(base_token, table_id, fields, record_id=record_id, dry_run=args.dry_run)
        if record_id:
            updated += 1
            print(f"updated {name}")
        else:
            created += 1
            print(f"created {name}" if not args.dry_run else f"would create {name}")

    print(json.dumps({
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "dry_run": args.dry_run,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
