"""
lark_cli_utils.py
=================
Shared lark-cli helpers with narrow retry handling for transient API errors.
"""

import json
import subprocess
import time


TRANSIENT_MARKERS = (
    "service unavailable",
    '"code": 2200',
    "timeout",
    "timed out",
    "temporarily unavailable",
    "bad gateway",
    "gateway timeout",
)


def is_transient_lark_error(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in TRANSIENT_MARKERS)


def run_lark_cli_json(*args, retries: int = 2, base_sleep: float = 1.0):
    """Run lark-cli and return parsed JSON, retrying only transient failures."""
    cmd = ["lark-cli"] + list(args)
    last_output = ""
    for attempt in range(retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        last_output = output.strip()

        if result.returncode == 0:
            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError:
                return result.stdout.strip()
            if isinstance(parsed, dict) and parsed.get("ok") is False:
                if attempt < retries and is_transient_lark_error(json.dumps(parsed, ensure_ascii=False)):
                    time.sleep(base_sleep * (attempt + 1))
                    continue
            return parsed

        if attempt < retries and is_transient_lark_error(output):
            time.sleep(base_sleep * (attempt + 1))
            continue
        raise RuntimeError(f"lark-cli 失败:\n{last_output}")

    raise RuntimeError(f"lark-cli 失败:\n{last_output}")


def normalize_record_list_data(data: dict) -> list[dict]:
    """Normalize lark-cli +record-list table output.

    lark-cli may return both human field names and field IDs. Business scripts
    use a mix of both while tables are being migrated, so each row keeps both
    aliases pointing to the same value.
    """
    field_names = data.get("fields") or []
    field_ids = data.get("field_id_list") or []
    record_ids = data.get("record_id_list") or []
    rows = data.get("data") or []

    records = []
    for rid, row in zip(record_ids, rows):
        fields = {}
        for idx, val in enumerate(row):
            if idx < len(field_names) and field_names[idx]:
                fields[field_names[idx]] = val
            if idx < len(field_ids) and field_ids[idx]:
                fields[field_ids[idx]] = val
        records.append({"record_id": rid, "fields": fields})
    return records


def normalize_record_list_response(resp: dict) -> list[dict]:
    """Normalize a lark-cli JSON response from base +record-list."""
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if isinstance(data, dict) and "records" in data and isinstance(data["records"], list):
        return data["records"]
    return normalize_record_list_data(data if isinstance(data, dict) else {})
