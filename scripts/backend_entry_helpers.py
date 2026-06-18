#!/usr/bin/env python3
"""Shared backend entry helpers.

This module is intentionally narrow: command metadata plus checkpoint
waiting/resume helpers only. It must not own business node behavior.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


RUN_DIALOG_CHECKPOINT_TYPES = {
    "score": "resume",
    "test-email": "test_email",
    "contract-info-email": "contract_info_email",
    "test-email-mark-sent": "test_email",
    "contract-info-mark-sent": "contract_info_email",
    "contract": "contract",
    "signed-contract": "signed_contract",
    "update-status": "status",
    "rejection-email": "rejection_email",
    "badcase": "badcase",
    "resume": "generic",
    "waiting": "generic",
}


RUN_DIALOG_WRITEBACK_FIELDS = {
    "score": ["score", "rating", "valid_resume", "ai_suggestion", "confidence", "resume_valid", "recruitment_status"],
    "test-email": ["recruitment_status", "workflow_log"],
    "contract-info-email": ["recruitment_status", "workflow_log"],
    "test-email-mark-sent": ["recruitment_status", "workflow_log"],
    "contract-info-mark-sent": ["recruitment_status", "workflow_log"],
    "contract": ["contract_file", "workflow_log"],
    "signed-contract": ["recruitment_status", "workflow_log"],
    "update-status": ["recruitment_status", "workflow_log"],
    "rejection-email": ["recruitment_status", "workflow_log"],
    "badcase": ["badcase_snapshot", "workflow_log"],
    "resume": ["workflow_log"],
}


RUN_DIALOG_COMMANDS = (
    "score",
    "test-email",
    "test-email-mark-sent",
    "contract-info-email",
    "contract-info-mark-sent",
    "contract",
    "signed-contract",
    "update-status",
    "rejection-email",
    "badcase",
    "chat",
    "resume",
    "waiting",
)


WORKFLOW_RUNNER_COMMANDS = (
    "status",
    "next",
    "score",
    "test-email",
    "contract-info-email",
    "contract",
    "resume",
    "list",
    "waiting",
)


CHECKPOINT_DONE_STATUSES = ("decided", "done", "completed")


def checkpoint_type_for_command(command: str, node: str | None = None) -> str:
    node = node or ""
    if "测试题" in node or "测试邮件" in node:
        return "test_email"
    if "签约信息" in node or "合同信息" in node:
        return "contract_info_email"
    if "合同" in node:
        return "contract"
    if "简历" in node or "评分" in node or "飞书" in node:
        return "resume"
    return RUN_DIALOG_CHECKPOINT_TYPES.get(command, "generic")


def writeback_fields_for_command(command: str) -> list[str]:
    return RUN_DIALOG_WRITEBACK_FIELDS.get(command, ["workflow_log"])


def workflow_runner_resume_command(
    checkpoint_token: str,
    decision: str,
    *,
    scripts_dir: Path,
    python_executable: str | None = None,
) -> list[str]:
    return [
        python_executable or sys.executable,
        str(scripts_dir / "workflow_runner.py"),
        "resume",
        "--token",
        checkpoint_token,
        "--decision",
        decision,
    ]


def checkpoint_file_path(checkpoint_token: str, *, home_dir: Path | None = None) -> Path:
    return (home_dir or Path.home()) / ".loc-resume-checkpoints" / f"{checkpoint_token}.json"


def wait_for_checkpoint_completion(
    checkpoint_token: str,
    *,
    timeout_seconds: int = 120,
    poll_seconds: float = 1,
    home_dir: Path | None = None,
) -> bool:
    ckpt_file = checkpoint_file_path(checkpoint_token, home_dir=home_dir)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if ckpt_file.exists():
            try:
                ckpt_data = json.loads(ckpt_file.read_text(encoding="utf-8"))
                if ckpt_data.get("status") in CHECKPOINT_DONE_STATUSES:
                    return True
            except Exception:
                pass
        time.sleep(poll_seconds)
    return False


def resume_checkpoint_with_engine(token: str, decision: str) -> bool:
    from workflow_engine import WorkflowEngine

    engine = WorkflowEngine.__new__(WorkflowEngine)
    return engine.resume(token, decision)


def waiting_status_for_rows(rows: list[dict]) -> str:
    return "waiting" if rows else "empty"


def waiting_message_for_rows(rows: list[dict]) -> str:
    return f"当前有 {len(rows)} 条待决策记录" if rows else "当前没有等待人工决策的候选人"
