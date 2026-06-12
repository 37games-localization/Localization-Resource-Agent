#!/usr/bin/env python3
"""
Replay a resource-management Agent run from workflow_log or eval_report.json.

This is a read-only governance tool. It reconstructs a run timeline, emits
standard trace/span records, and writes human-readable Markdown plus optional
JSON. It does not call business scripts and does not write Lark.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from field_resolver import FieldMappingError, load_field_mapping, table_ref
from lark_cli_utils import normalize_record_list_response, run_lark_cli_json
from trace_span import (
    TraceSpan,
    coerce_payload,
    sanitize_value,
    span_type_from_workflow,
    stable_ref,
    status_from_workflow,
    validate_span,
)


SKILL_DIR = Path(__file__).parent.parent
DEFAULT_REPLAY_ROOT = Path.home() / ".loc-resume-replays"

WORKFLOW_KEYS = [
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

WORKFLOW_FALLBACKS = {
    "workflow.run_id": "run_id",
    "workflow.candidate_record_id": "candidate_record_id",
    "workflow.candidate_name": "candidate_name",
    "workflow.step_name": "step_name",
    "workflow.step_type": "step_type",
    "workflow.status": "status",
    "workflow.input_summary": "input_summary",
    "workflow.output_summary": "output_summary",
    "workflow.decision": "decision",
    "workflow.created_at": "created_at",
}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def workflow_mapping() -> dict:
    return load_field_mapping().get("tables", {}).get("workflow_log", {})


def workflow_field_ref(logical_key: str, mapping: dict) -> str:
    field = (mapping.get("fields") or {}).get(logical_key) or {}
    return field.get("field_id") or field.get("field_name") or WORKFLOW_FALLBACKS[logical_key]


def workflow_field_value(fields: dict, logical_key: str, mapping: dict) -> Any:
    field = (mapping.get("fields") or {}).get(logical_key) or {}
    candidates = [
        field.get("field_id"),
        field.get("field_name"),
        field.get("expected_name"),
        WORKFLOW_FALLBACKS[logical_key],
    ]
    for key in candidates:
        if key and key in fields:
            return fields.get(key)
    return ""


def created_at_iso(value: Any) -> str:
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc).isoformat()
    if text.isdigit():
        return created_at_iso(int(text))
    return text


def fetch_workflow_rows(limit: int = 500) -> list[dict[str, Any]]:
    mapping = workflow_mapping()
    try:
        base_token, table_id = table_ref("workflow_log")
    except FieldMappingError as exc:
        raise RuntimeError(f"workflow_log 字段映射不可用：{exc}") from exc

    field_refs = [workflow_field_ref(key, mapping) for key in WORKFLOW_KEYS]
    cmd = [
        "base",
        "+record-list",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--limit",
        str(limit),
        "--format",
        "json",
    ]
    for ref in dict.fromkeys(field_refs):
        cmd += ["--field-id", ref]

    resp = run_lark_cli_json(*cmd, retries=2)
    rows = []
    for item in normalize_record_list_response(resp if isinstance(resp, dict) else {}):
        fields = item.get("fields") or {}
        row = {"record_id": item.get("record_id") or item.get("id") or ""}
        for key in WORKFLOW_KEYS:
            row[key] = workflow_field_value(fields, key, mapping)
        rows.append(row)
    return rows


def filter_rows(
    rows: list[dict[str, Any]],
    *,
    run_id: str = "",
    candidate_record_id: str = "",
    latest: bool = False,
) -> list[dict[str, Any]]:
    if run_id:
        rows = [row for row in rows if str(row.get("workflow.run_id") or "") == run_id]
    if candidate_record_id:
        rows = [row for row in rows if str(row.get("workflow.candidate_record_id") or "") == candidate_record_id]
    if latest and rows:
        latest_run_id = sorted(
            rows,
            key=lambda row: str(row.get("workflow.created_at") or ""),
            reverse=True,
        )[0].get("workflow.run_id")
        rows = [row for row in rows if row.get("workflow.run_id") == latest_run_id]
    return sort_rows(rows)


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("workflow.created_at") or ""))


def span_from_workflow_log_row(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row.get("workflow.run_id") or "")
    record_id = str(row.get("record_id") or "")
    step = str(row.get("workflow.step_name") or "workflow_log")
    status = str(row.get("workflow.status") or "")
    step_type = str(row.get("workflow.step_type") or "")
    output_payload = coerce_payload(row.get("workflow.output_summary"))
    span = TraceSpan(
        run_id=run_id,
        span_id=f"span_{stable_ref(record_id or json.dumps(row, ensure_ascii=False))}",
        step=step,
        span_type=span_type_from_workflow(step_type, status),
        status=status_from_workflow(status),
        input=coerce_payload(row.get("workflow.input_summary")),
        output=output_payload,
        error=output_payload if status_from_workflow(status) == "failed" else {},
        created_at=created_at_iso(row.get("workflow.created_at")),
    ).to_dict()
    validate_span(span)
    return span


def build_replay_from_workflow(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("未找到可回放的 workflow_log 记录")
    spans = [span_from_workflow_log_row(row) for row in rows]
    statuses = {span["status"] for span in spans}
    run_id = spans[0]["run_id"]
    return {
        "source": "workflow_log",
        "run_id": run_id,
        "candidate_record_id": sanitize_value(rows[0].get("workflow.candidate_record_id") or ""),
        "candidate_name": sanitize_value(rows[0].get("workflow.candidate_name") or ""),
        "span_count": len(spans),
        "status": "failed" if "failed" in statuses else ("waiting_confirmation" if "waiting_confirmation" in statuses else "success"),
        "spans": spans,
    }


def build_replay_from_eval_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    spans = data.get("spans") or []
    for span in spans:
        validate_span(span)
    return {
        "source": "eval_report",
        "run_id": data.get("run_id", ""),
        "candidate_record_id": "",
        "candidate_name": "",
        "span_count": len(spans),
        "status": data.get("overall_status", ""),
        "spans": spans,
        "eval_results": data.get("results", []),
    }


def write_outputs(out_dir: Path, replay: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "replay.json").write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Agent Run Replay",
        "",
        f"- Source: `{replay.get('source')}`",
        f"- Run ID: `{replay.get('run_id')}`",
        f"- Status: **{str(replay.get('status', '')).upper()}**",
        f"- Span count: {replay.get('span_count')}",
    ]
    if replay.get("candidate_name") or replay.get("candidate_record_id"):
        lines.append(f"- Candidate: {replay.get('candidate_name') or '-'} / `{replay.get('candidate_record_id') or '-'}`")
    lines.extend(["", "## Timeline", ""])

    for index, span in enumerate(replay.get("spans") or [], start=1):
        lines.append(f"### {index}. {span.get('step')}")
        lines.append("")
        lines.append(f"- Type: `{span.get('span_type')}`")
        lines.append(f"- Status: `{span.get('status')}`")
        lines.append(f"- Created at: {span.get('created_at')}")
        if span.get("input"):
            lines.append(f"- Input: `{compact_json(span.get('input'))}`")
        if span.get("output"):
            lines.append(f"- Output: `{compact_json(span.get('output'))}`")
        if span.get("error"):
            lines.append(f"- Error: `{compact_json(span.get('error'))}`")
        lines.append("")

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def compact_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= 280 else text[:277] + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay resource-management Agent runs")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-id", help="从 Lark workflow_log 回放指定 run_id")
    source.add_argument("--candidate-record-id", help="从 Lark workflow_log 回放指定候选人的最新 run")
    source.add_argument("--latest", action="store_true", help="从 Lark workflow_log 回放最新 run")
    source.add_argument("--eval-report", type=Path, help="从 eval_report.json 回放 eval run")
    parser.add_argument("--limit", type=int, default=500, help="读取 workflow_log 的最大行数")
    parser.add_argument("--output-dir", type=Path, help="输出目录")
    parser.add_argument("--json", action="store_true", help="stdout 输出 replay JSON")
    args = parser.parse_args()

    if args.eval_report:
        replay = build_replay_from_eval_report(args.eval_report.expanduser())
    else:
        rows = fetch_workflow_rows(limit=args.limit)
        rows = filter_rows(
            rows,
            run_id=args.run_id or "",
            candidate_record_id=args.candidate_record_id or "",
            latest=bool(args.latest or args.candidate_record_id),
        )
        replay = build_replay_from_workflow(rows)

    out_dir = (args.output_dir or (DEFAULT_REPLAY_ROOT / now_stamp())).expanduser()
    write_outputs(out_dir, replay)

    if args.json:
        print(json.dumps(replay, ensure_ascii=False, indent=2))
    else:
        print(f"Replay status: {str(replay.get('status', '')).upper()}")
        print(f"Summary: {out_dir / 'summary.md'}")
        print(f"JSON: {out_dir / 'replay.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
