"""
manual_trace.py
===============
Write lightweight workflow_log rows for controlled manual-chain runs.

This module is intentionally side-effect tolerant: logging failures must not
break the business action that the VM explicitly triggered.
"""

import json
import time
from datetime import datetime

from config_loader import get_table_ref, load_config
from field_resolver import FieldMappingError, field_id
from lark_cli_utils import run_lark_cli_json


def _workflow_field_map() -> dict:
    keys = [
        "workflow.run_id",
        "workflow.candidate_record_id",
        "workflow.candidate_name",
        "workflow.step_name",
        "workflow.step_type",
        "workflow.status",
        "workflow.input_summary",
        "workflow.output_summary",
        "workflow.decision",
        "workflow.created_at",
    ]
    return {key: field_id("workflow_log", key) for key in keys}


def log_manual_step(
    *,
    step_name: str,
    status: str,
    candidate_name: str = "",
    candidate_record_id: str = "",
    input_summary: str = "",
    output_summary: str = "",
    step_type: str = "action",
    decision: str = "",
    run_id: str = "",
) -> str:
    """Write one workflow_log row. Return record_id if available, else empty."""
    try:
        base_token, table_id = get_table_ref(load_config(), "workflow_log")
        fields = _workflow_field_map()
        if not base_token or not table_id:
            return ""
        actual_run_id = run_id or f"manual-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        payload = {
            fields["workflow.run_id"]: actual_run_id,
            fields["workflow.candidate_record_id"]: candidate_record_id,
            fields["workflow.candidate_name"]: candidate_name,
            fields["workflow.step_name"]: step_name,
            fields["workflow.step_type"]: step_type,
            fields["workflow.status"]: status,
            fields["workflow.input_summary"]: (input_summary or "")[:500],
            fields["workflow.output_summary"]: (output_summary or "")[:500],
            fields["workflow.decision"]: decision,
            fields["workflow.created_at"]: int(time.time() * 1000),
        }
        resp = run_lark_cli_json(
            "base",
            "+record-upsert",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps(payload, ensure_ascii=False),
            "--format",
            "json",
        )
        if not isinstance(resp, dict):
            return ""
        data = resp.get("data", resp)
        record = data.get("record") or {}
        record_ids = (
            data.get("record_id_list")
            or record.get("record_id_list")
            or []
        )
        return (
            data.get("record_id")
            or record.get("record_id")
            or (record_ids[0] if record_ids else "")
            or data.get("id", "")
            or ""
        )
    except (FieldMappingError, Exception):
        return ""
