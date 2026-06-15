#!/usr/bin/env python3
"""
Complete resume evaluation node for the visual workbench.

The normal "look at this resume" path must run both existing capabilities:
1. LLM resume parsing writes structured facts to Lark.
2. The deterministic scoring engine reads those facts and writes score fields.

Explicit "rescore" requests still use the scoring script directly.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def run_stage(label: str, command: list[str]) -> int:
    print(f"\n=== {label} ===", flush=True)
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
    return proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="完整简历评估节点：解析简历 + 评分写回")
    parser.add_argument("--record-id", dest="record_id", help="候选人 Lark record_id")
    parser.add_argument("--name", help="候选人姓名")
    parser.add_argument("--dry-run", action="store_true", help="预览执行，不写回 Lark")
    args = parser.parse_args()

    if args.record_id:
        locator = ["--record-id", args.record_id]
    elif args.name:
        locator = ["--name", args.name]
    else:
        print("❌ 请提供 --record-id 或 --name", file=sys.stderr)
        return 2

    mode_args = ["--dry-run"] if args.dry_run else []

    parse_rc = run_stage(
        "STEP 1/2  LLM 简历解析并写回结构化字段",
        [sys.executable, "-u", str(SCRIPTS / "parse_resumes.py"), *locator, *mode_args],
    )
    if parse_rc != 0:
        print("\n❌ 简历解析阶段失败，已停止评分。", flush=True)
        return parse_rc

    score_rc = run_stage(
        "STEP 2/2  规则引擎评分并写回结果",
        [sys.executable, "-u", str(SCRIPTS / "rescore_and_write_v2.py"), *locator, *mode_args],
    )
    if score_rc != 0:
        print("\n❌ 评分写回阶段失败。", flush=True)
        return score_rc

    print("\nRESUME_EVALUATION_NODE_DONE parse_stage=success score_stage=success", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
