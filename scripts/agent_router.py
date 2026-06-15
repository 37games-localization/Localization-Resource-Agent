#!/usr/bin/env python3
"""Lightweight natural-language router protocol for the resource Agent.

The router only classifies a VM instruction into an existing single-step
capability and identifies missing inputs. It must not replace Lark state,
business scripts, scoring logic, contract-template selection, or human
confirmation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


AGENT_NAME = "loc-resource-management"
WAKE_PATTERNS = (
    "调用资源管理agent",
    "调用资源管理 agent",
    "继续资源管理agent",
    "继续资源管理 agent",
    "资源管理agent",
    "资源管理 agent",
)

NON_RESOURCE_KEYWORDS = (
    "readme",
    "README",
    "文档",
    "报错",
    "前端",
    "storybook",
    "builder",
    "git",
    "commit",
    "push",
)

STEP_PATTERNS = {
    "score": ("看简历", "简历", "评分", "初筛", "重算"),
    "test-email": ("测试题", "测试邀请", "发测试", "测试邮件"),
    "contract-info-email": ("签约信息", "合同信息收集", "签约信息收集", "收集合同信息"),
    "contract": ("生成合同", "准备合同", "发合同", "签约邀请", "合同"),
    "signed-contract": ("签字合同", "签署合同", "已签字", "已签署", "核查签字"),
    "status": ("状态", "推进", "改成", "标记为"),
    "badcase": ("badcase", "Badcase", "坏例", "问题回流"),
}

STEP_REQUIRED_INPUTS = {
    "score": ("candidate",),
    "test-email": ("candidate", "attachment"),
    "contract-info-email": ("candidate",),
    "contract": ("candidate",),
    "signed-contract": ("candidate", "attachment"),
    "status": ("candidate", "target_status"),
    "badcase": ("candidate", "expected_result"),
}

RECORD_ID_RE = re.compile(r"\b(rec[a-zA-Z0-9]+|\d{8}-\d+|CAN-[A-Za-z0-9-]+)\b")
ABS_PATH_RE = re.compile(r"(/Users/[^\s，。；;]+|~/[^\s，。；;]+)")
TARGET_STATUS_RE = re.compile(r"(?:状态(?:改成|改为|推进到)?|标记为)([^\s，。；;]+)")
EXPECTED_RE = re.compile(r"(?:应该|期望|预期)(.+)$")


@dataclass
class ActiveAgentSession:
    agent: str = AGENT_NAME
    candidate: str = ""
    record_id: str = ""
    current_step: str = ""
    waiting_for: str = ""
    last_checkpoint_token: str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=30))

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.agent == AGENT_NAME and now < self.expires_at


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def has_wake_word(text: str) -> bool:
    compact = normalize_text(text).lower().replace(" ", "")
    return any(pattern.replace(" ", "").lower() in compact for pattern in WAKE_PATTERNS)


def is_non_resource_instruction(text: str) -> bool:
    lower = normalize_text(text).lower()
    return any(keyword.lower() in lower for keyword in NON_RESOURCE_KEYWORDS)


def detect_step(text: str) -> str:
    lower = normalize_text(text).lower()
    for step, patterns in STEP_PATTERNS.items():
        if any(pattern.lower() in lower for pattern in patterns):
            return step
    return ""


def extract_record_id(text: str) -> str:
    match = RECORD_ID_RE.search(text or "")
    return match.group(1) if match else ""


def extract_attachment(text: str) -> str:
    match = ABS_PATH_RE.search(text or "")
    if not match:
        return ""
    return str(Path(match.group(1)).expanduser())


def extract_candidate(text: str) -> str:
    text = normalize_text(text)
    record_id = extract_record_id(text)
    if record_id:
        return ""
    patterns = [
        r"(?:给|处理|继续|看下|看看|生成|检查|核查|婉拒)([^，。；;\s]+)",
        r"候选人[:：]?\s*([^，。；;\s]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = match.group(1).strip()
            candidate = re.sub(r"(的)?(简历|合同|测试题|测试邀请|签字合同)$", "", candidate)
            candidate = re.sub(r"(发|准备|生成|检查|核查)$", "", candidate)
            if candidate and not any(token in candidate.lower() for token in ("资源管理", "agent")):
                return candidate
    return ""


def extract_target_status(text: str) -> str:
    match = TARGET_STATUS_RE.search(text or "")
    return match.group(1).strip() if match else ""


def extract_expected_result(text: str) -> str:
    match = EXPECTED_RE.search(text or "")
    return match.group(1).strip() if match else ""


def classify_instruction(text: str, session: ActiveAgentSession | None = None) -> dict[str, Any]:
    text = normalize_text(text)
    invoked = has_wake_word(text)
    session_active = bool(session and session.is_active())

    if is_non_resource_instruction(text) and not invoked:
        return {
            "agent": AGENT_NAME,
            "invoked": False,
            "session_active": session_active,
            "session_invalidated": session_active,
            "step": "",
            "can_execute": False,
            "missing": ["wake_word"],
            "reason": "检测到非资源管理任务，短期资源管理 session 应失效。",
        }

    step = detect_step(text)
    record_id = extract_record_id(text)
    candidate = extract_candidate(text)
    attachment = extract_attachment(text)
    target_status = extract_target_status(text)
    expected_result = extract_expected_result(text)

    if session_active and not invoked:
        step = step or session.current_step
        record_id = record_id or session.record_id
        candidate = candidate or session.candidate
        if session.waiting_for == "attachment" and attachment:
            step = step or session.current_step
        if session.waiting_for == "checkpoint" and re.search(r"确认|同意|发送|写入|通过", text):
            return {
                "agent": AGENT_NAME,
                "invoked": False,
                "session_active": True,
                "session_invalidated": False,
                "step": session.current_step,
                "decision": text,
                "checkpoint_token": session.last_checkpoint_token,
                "can_execute": bool(session.last_checkpoint_token),
                "missing": [] if session.last_checkpoint_token else ["checkpoint_token"],
                "reason": "短期 session 内识别为 checkpoint 人工确认。",
            }

    if not invoked and not session_active:
        return {
            "agent": AGENT_NAME,
            "invoked": False,
            "session_active": False,
            "session_invalidated": False,
            "step": step,
            "can_execute": False,
            "missing": ["wake_word"],
            "reason": "首次进入资源管理 Agent 必须显式唤起。",
        }

    available = {
        "candidate": bool(candidate or record_id),
        "attachment": bool(attachment),
        "target_status": bool(target_status),
        "expected_result": bool(expected_result),
    }
    required = STEP_REQUIRED_INPUTS.get(step, ())
    missing = [key for key in required if not available.get(key)]
    if not step:
        missing.append("step")

    return {
        "agent": AGENT_NAME,
        "invoked": invoked,
        "session_active": session_active,
        "session_invalidated": False,
        "step": step,
        "candidate": candidate,
        "record_id": record_id,
        "attachment": attachment,
        "target_status": target_status,
        "expected_result": expected_result,
        "can_execute": not missing,
        "missing": missing,
        "reason": "ok" if not missing else "执行前置条件不满足。",
    }
