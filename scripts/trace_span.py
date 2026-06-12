#!/usr/bin/env python3
"""Trace/span normalization helpers for the resource-management Agent.

This module is an observation-layer adapter. It converts existing workflow
steps into a stable trace-span shape for replay, audit, frontend rendering,
and future eval reports. It does not write Lark and must not decide business
outcomes.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


AGENT_NAME = "loc-resource-management"
REDACTED = "[REDACTED]"

SPAN_TYPES = {
    "user_intent",
    "router",
    "tool_call",
    "llm_call",
    "lark_read",
    "lark_write",
    "checkpoint",
    "error",
}

STATUS_VALUES = {
    "running",
    "success",
    "failed",
    "waiting_confirmation",
    "decided",
    "skipped",
}

SENSITIVE_KEY_RE = re.compile(
    r"(email|mail|phone|mobile|bank|account|card|id_no|identity|passport|"
    r"address|secret|token|password|api[_-]?key|app[_-]?secret)",
    re.IGNORECASE,
)
SAFE_TECHNICAL_KEYS = {"checkpoint_token", "parent_span_id", "span_id", "run_id", "token_usage"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
LONG_NUMBER_RE = re.compile(r"\b\d{8,}\b")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def new_span_id(prefix: str = "span") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def stable_ref(value: str, salt: str = "loc-resource-management") -> str:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:12]
    return f"ref_{digest}"


def sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(k): (
                sanitize_value(v)
                if str(k) in SAFE_TECHNICAL_KEYS
                else (REDACTED if SENSITIVE_KEY_RE.search(str(k)) else sanitize_value(v))
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        text = EMAIL_RE.sub(REDACTED, value)
        text = LONG_NUMBER_RE.sub(REDACTED, text)
        return text
    return value


def coerce_payload(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return sanitize_value(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except Exception:
            return sanitize_value({"summary": stripped})
        return sanitize_value(parsed)
    return sanitize_value({"value": value})


def status_from_workflow(status: str) -> str:
    mapping = {
        "running": "running",
        "done": "success",
        "waiting": "waiting_confirmation",
        "decided": "decided",
        "skipped": "skipped",
        "failed": "failed",
        "error": "failed",
    }
    return mapping.get(str(status or "").lower(), "success")


def span_type_from_workflow(step_type: str, status: str = "") -> str:
    step_type = str(step_type or "").lower()
    status = str(status or "").lower()
    if step_type == "checkpoint" or status == "waiting":
        return "checkpoint"
    if step_type == "error" or status == "failed":
        return "error"
    if step_type == "decision":
        return "checkpoint"
    return "tool_call"


@dataclass
class TraceSpan:
    run_id: str
    step: str
    span_type: str
    status: str
    input: Any = field(default_factory=dict)
    output: Any = field(default_factory=dict)
    parent_span_id: str = ""
    span_id: str = field(default_factory=new_span_id)
    agent: str = AGENT_NAME
    duration_ms: int | None = None
    model: str = ""
    token_usage: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        if self.span_type not in SPAN_TYPES:
            raise ValueError(f"unsupported span_type: {self.span_type}")
        if self.status not in STATUS_VALUES:
            raise ValueError(f"unsupported status: {self.status}")
        return {
            "run_id": self.run_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "agent": self.agent,
            "step": self.step,
            "span_type": self.span_type,
            "input": sanitize_value(self.input),
            "output": sanitize_value(self.output),
            "status": self.status,
            "duration_ms": self.duration_ms,
            "model": self.model,
            "token_usage": sanitize_value(self.token_usage),
            "error": sanitize_value(self.error),
            "created_at": self.created_at,
        }


def span_from_workflow_step(step: Any, parent_span_id: str = "") -> dict[str, Any]:
    start_ts = getattr(step, "_start_ts", None)
    duration_ms = None
    if isinstance(start_ts, (int, float)):
        duration_ms = max(0, int((time.time() - start_ts) * 1000))

    span = TraceSpan(
        run_id=getattr(step, "run_id", ""),
        span_id=f"span_{getattr(step, 'step_id', '')}" if getattr(step, "step_id", "") else new_span_id(),
        parent_span_id=parent_span_id,
        step=getattr(step, "step_name", ""),
        span_type=span_type_from_workflow(
            getattr(step, "step_type", ""),
            getattr(step, "status", ""),
        ),
        input=coerce_payload(getattr(step, "input_summary", "")),
        output=coerce_payload(getattr(step, "output_summary", "")),
        status=status_from_workflow(getattr(step, "status", "")),
        duration_ms=duration_ms,
        error=coerce_payload(getattr(step, "output_summary", "")) if status_from_workflow(getattr(step, "status", "")) == "failed" else {},
        created_at=getattr(step, "created_at", "") or now_iso(),
    )
    return span.to_dict()


def validate_span(span: Mapping[str, Any]) -> None:
    required = {"run_id", "span_id", "agent", "step", "span_type", "status", "created_at"}
    missing = sorted(key for key in required if not span.get(key))
    if missing:
        raise ValueError(f"trace span missing required fields: {', '.join(missing)}")
    if span["span_type"] not in SPAN_TYPES:
        raise ValueError(f"unsupported span_type: {span['span_type']}")
    if span["status"] not in STATUS_VALUES:
        raise ValueError(f"unsupported status: {span['status']}")
    payload = json.dumps({
        "input": span.get("input", {}),
        "output": span.get("output", {}),
        "error": span.get("error", {}),
        "token_usage": sanitize_value(span.get("token_usage", {})),
    }, ensure_ascii=False)
    if EMAIL_RE.search(payload) or LONG_NUMBER_RE.search(payload):
        raise ValueError("trace span contains unsanitized sensitive payload")


def spans_from_workflow_steps(steps: list[Any]) -> list[dict[str, Any]]:
    spans = [span_from_workflow_step(step) for step in steps]
    for span in spans:
        validate_span(span)
    return spans
