#!/usr/bin/env python3
"""
badcase_protocol.py
===================
Shared badcase snapshot and GitHub issue protocol.

Goal:
- VM-side agents export one stable, sanitized JSON shape.
- Project-side issue pushers render one stable GitHub issue format.
- Secrets or raw personal/payment data fail closed before upload/push.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SNAPSHOT_VERSION = "2.0"
ISSUE_TEMPLATE_VERSION = "1.0"

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = {
    "name",
    "full_name",
    "candidate_name",
    "email",
    "recipient",
    "recipient_email",
    "phone",
    "mobile",
    "wechat",
    "id_number",
    "passport",
    "address",
    "bank",
    "bank_name",
    "bank_address",
    "account",
    "account_name",
    "account_number",
    "bank_account",
    "bank_account_name",
    "bank_account_number",
    "iban",
    "swift",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "resume_text",
    "contract_text",
}

DANGER_PATTERNS = [
    (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "邮箱地址"),
    (r"\b1[3-9]\d{9}\b", "中国手机号疑似"),
    (r"\b\d{15,18}[\dXx]?\b", "身份证号疑似"),
    (r"\b\d{16,20}\b", "银行卡/账号疑似"),
    (r"BEGIN (RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY", "私钥"),
    (r"(api[_-]?key|password|secret|token)\s*[=:]\s*['\"]?[^'\"\s]+", "密钥/密码"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def anonymize_id(source_id: str, salt: str) -> str:
    raw = (source_id + salt).encode("utf-8")
    return "cand_" + hashlib.sha256(raw).hexdigest()[:12]


def sanitize_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    for pattern, _label in DANGER_PATTERNS:
        text = re.sub(pattern, REDACTED, text, flags=re.IGNORECASE)
    return text[:3000]


def sanitize_obj(value: Any, path: str = "") -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in SENSITIVE_KEYS:
                cleaned[key_text] = REDACTED
            else:
                cleaned[key_text] = sanitize_obj(item, f"{path}.{key_text}" if path else key_text)
        return cleaned
    if isinstance(value, list):
        return [sanitize_obj(item, f"{path}[]") for item in value[:50]]
    return sanitize_scalar(value)


def scan_sensitive(obj: Any, path: str = "root") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, str):
        for pattern, label in DANGER_PATTERNS:
            if re.search(pattern, obj, re.IGNORECASE):
                hits.append(f"{path}: {label}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            key_text = str(key)
            if value == REDACTED:
                continue
            hits.extend(scan_sensitive(value, f"{path}.{key_text}"))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            hits.extend(scan_sensitive(value, f"{path}[{idx}]"))
    return hits


def normalize_badcase_type(step_name: str, expected_result: str) -> str:
    text = f"{step_name} {expected_result}".lower()
    if any(k in text for k in ["resume", "简历", "评分", "初筛"]):
        return "resume_scoring"
    if any(k in text for k in ["test", "测试题", "测试邀约"]):
        return "test_invitation"
    if any(k in text for k in ["contract", "合同", "签约"]):
        return "contract"
    if any(k in text for k in ["status", "状态", "推进"]):
        return "status_transition"
    if any(k in text for k in ["badcase", "snapshot", "回流"]):
        return "badcase_feedback"
    return "unknown"


def build_snapshot(
    *,
    record_id: str,
    salt: str,
    current_status: str,
    expected_result: str,
    language_pair: str = "",
    services: str = "",
    score: str = "",
    tier: str = "",
    ai_suggestion: str = "",
    score_basis: str = "",
    agent_run: dict | None = None,
) -> dict:
    anon = anonymize_id(record_id, salt)
    run = sanitize_obj(agent_run or {})
    last_step = ""
    if isinstance(run, dict):
        last_step = str(run.get("step_name") or run.get("last_step") or "")
    badcase_type = normalize_badcase_type(last_step, expected_result)
    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "issue_template_version": ISSUE_TEMPLATE_VERSION,
        "exported_at": now_iso(),
        "source": {
            "skill": "loc-resume-screening",
            "record_id_hash": anon,
            "agent_version": "",
            "environment": "vm-local",
        },
        "badcase": {
            "type": badcase_type,
            "severity": "unknown",
            "vm_expected_result": sanitize_scalar(expected_result) or "(未填写)",
            "actual_result": "",
            "current_status": sanitize_scalar(current_status),
            "repro_command": "",
        },
        "resource_context": {
            "anonymous_id": anon,
            "language_pair": sanitize_scalar(language_pair),
            "services": sanitize_scalar(services),
        },
        "assessment_context": {
            "ai_score": sanitize_scalar(score),
            "score_grade": sanitize_scalar(tier),
            "ai_suggestion": sanitize_scalar(ai_suggestion),
            "score_basis": sanitize_scalar(score_basis),
        },
        "agent_run": run,
        "redaction": {
            "policy": "loc-badcase-snapshot-v2",
            "removed_fields": [
                "name",
                "email",
                "phone",
                "id_number",
                "address",
                "bank_account",
                "raw_resume",
                "contract_text",
                "secrets",
            ],
            "contains_raw_resume": False,
            "contains_contract_text": False,
            "contains_payment_info": False,
        },
    }
    validate_snapshot(snapshot)
    return snapshot


def validate_snapshot(snapshot: dict) -> None:
    required_paths = [
        ("snapshot_version",),
        ("issue_template_version",),
        ("exported_at",),
        ("source", "skill"),
        ("source", "record_id_hash"),
        ("badcase", "type"),
        ("badcase", "vm_expected_result"),
        ("badcase", "current_status"),
        ("resource_context", "anonymous_id"),
        ("redaction", "policy"),
    ]
    missing = []
    for path in required_paths:
        cur: Any = snapshot
        for part in path:
            if not isinstance(cur, dict) or part not in cur:
                missing.append(".".join(path))
                break
            cur = cur[part]
    if missing:
        raise ValueError(f"badcase snapshot 缺少必需字段：{', '.join(missing)}")
    hits = scan_sensitive(snapshot)
    if hits:
        raise ValueError("badcase snapshot 脱敏校验命中：" + "; ".join(hits))


def issue_title(snapshot: dict) -> str:
    b = snapshot.get("badcase", {})
    ctx = snapshot.get("resource_context", {})
    kind = b.get("type", "unknown")
    anon = ctx.get("anonymous_id", "unknown")
    status = b.get("current_status", "unknown")
    return f"Badcase[{kind}]: {anon} / {status}"


def issue_body(snapshot: dict) -> str:
    validate_snapshot(snapshot)
    b = snapshot["badcase"]
    ctx = snapshot["resource_context"]
    assess = snapshot.get("assessment_context", {})
    redaction = snapshot["redaction"]
    run = snapshot.get("agent_run", {})
    return "\n".join([
        "## Badcase Summary",
        "",
        f"- Snapshot version: `{snapshot['snapshot_version']}`",
        f"- Issue template version: `{snapshot['issue_template_version']}`",
        f"- Exported at: `{snapshot['exported_at']}`",
        f"- Type: `{b.get('type', 'unknown')}`",
        f"- Severity: `{b.get('severity', 'unknown')}`",
        f"- Candidate: `{ctx.get('anonymous_id', 'unknown')}`",
        f"- Current status: `{b.get('current_status', '')}`",
        "",
        "## VM Expected Result",
        "",
        str(b.get("vm_expected_result") or "(未填写)"),
        "",
        "## Actual Result",
        "",
        str(b.get("actual_result") or "(由项目侧根据 snapshot / 日志补充)"),
        "",
        "## Context",
        "",
        f"- Language pair: `{ctx.get('language_pair', '')}`",
        f"- Services: `{ctx.get('services', '')}`",
        f"- Score: `{assess.get('ai_score', '')}`",
        f"- Tier: `{assess.get('score_grade', '')}`",
        f"- AI suggestion: `{assess.get('ai_suggestion', '')}`",
        "",
        "## Score Basis / Evidence Summary",
        "",
        str(assess.get("score_basis") or "(无)"),
        "",
        "## Agent Run Snapshot",
        "",
        "```json",
        json.dumps(sanitize_obj(run), ensure_ascii=False, indent=2)[:8000],
        "```",
        "",
        "## Redaction Checklist",
        "",
        f"- Policy: `{redaction.get('policy')}`",
        f"- Contains raw resume: `{redaction.get('contains_raw_resume')}`",
        f"- Contains contract text: `{redaction.get('contains_contract_text')}`",
        f"- Contains payment info: `{redaction.get('contains_payment_info')}`",
        f"- Removed fields: `{', '.join(redaction.get('removed_fields', []))}`",
        "",
        "## Required Fix Output",
        "",
        "- Root cause:",
        "- Fix plan:",
        "- Regression test:",
        "- Release note:",
    ])


def issue_labels(snapshot: dict) -> list[str]:
    kind = snapshot.get("badcase", {}).get("type", "unknown")
    return ["bug", "badcase", f"badcase:{kind}"]
