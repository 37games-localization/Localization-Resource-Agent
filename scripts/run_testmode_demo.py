#!/usr/bin/env python3
"""
run_testmode_demo.py
====================
Run a real TEST_MODE demo path and save evidence for recording.

This script does not mock terminal output. It calls the existing workflow
scripts and records command, return code, stdout/stderr, parsed JSON, and a
summary markdown file.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
SKILL_DIR = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))
from config_loader import load_config, is_test_mode, get_test_email


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def default_output_dir() -> Path:
    return Path.home() / ".loc-resume-demo-runs" / now_stamp()


def redact_command(cmd: list[str]) -> list[str]:
    redacted = []
    hide_next = False
    for part in cmd:
        if hide_next:
            redacted.append("***")
            hide_next = False
            continue
        redacted.append(part)
        if part.lower() in {"--password", "--token", "--api-key"}:
            hide_next = True
    return redacted


def run_command(cmd: list[str], out_dir: Path, step: str, timeout: int = 180) -> dict:
    started_at = datetime.now().isoformat(timespec="seconds")
    started = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(SKILL_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        rc = result.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        rc = 124
        timed_out = True

    duration = round(time.time() - started, 2)
    parsed_json = None
    try:
        parsed_json = json.loads(stdout)
    except Exception:
        parsed_json = None

    record = {
        "step": step,
        "started_at": started_at,
        "duration_seconds": duration,
        "returncode": rc,
        "timed_out": timed_out,
        "command": redact_command(cmd),
        "stdout": stdout[-8000:],
        "stderr": stderr[-4000:],
        "json": parsed_json,
    }

    safe_step = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in step)
    (out_dir / f"{safe_step}.stdout.txt").write_text(stdout, encoding="utf-8")
    (out_dir / f"{safe_step}.stderr.txt").write_text(stderr, encoding="utf-8")
    return record


def append_jsonl(path: Path, record: dict):
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def command_status(record: dict) -> str:
    if record["returncode"] == 0:
        return "PASS"
    if record.get("timed_out"):
        return "TIMEOUT"
    return "FAIL"


def write_summary(out_dir: Path, records: list[dict], metadata: dict):
    lines = [
        "# TEST_MODE Demo Evidence",
        "",
        f"- Created at: {datetime.now().isoformat(timespec='seconds')}",
        f"- TEST_MODE: {metadata.get('test_mode')}",
        f"- Test email: {metadata.get('test_email') or '(not configured)'}",
        f"- Output dir: `{out_dir}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Duration | Notes |",
        "|---|---:|---:|---|",
    ]
    for record in records:
        note = ""
        payload = record.get("json") or {}
        if payload:
            note = payload.get("message") or payload.get("status") or ""
            if payload.get("checkpoint_token"):
                note = f"checkpoint: {payload['checkpoint_token']}"
        if not note and record.get("stderr"):
            note = record["stderr"].splitlines()[-1][:120]
        lines.append(
            f"| {record['step']} | {command_status(record)} | {record['duration_seconds']}s | {note} |"
        )
    lines.extend([
        "",
        "## Replay Commands",
        "",
    ])
    for record in records:
        lines.append(f"### {record['step']}")
        lines.append("")
        lines.append("```bash")
        lines.append(" ".join(record["command"]))
        lines.append("```")
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def require_test_mode(allow_production: bool):
    cfg = load_config()
    test_mode = is_test_mode(cfg)
    if not test_mode and not allow_production:
        raise SystemExit(
            "当前 config.yaml 的 test_mode.enabled=false。"
            "run_testmode_demo.py 默认拒绝在正式生产模式执行；如确认需要，请加 --allow-production。"
        )
    return cfg


def add_name_or_record(cmd: list[str], name: str | None, record_id: str | None):
    if record_id:
        cmd += ["--record-id", record_id]
    elif name:
        cmd += ["--name", name]
    else:
        raise SystemExit("每个 demo 步骤必须提供 --*-record-id 或 --*-name")


def main():
    parser = argparse.ArgumentParser(description="Run real TEST_MODE demo commands and save evidence")
    parser.add_argument("--output-dir", type=Path, default=None, help="证据输出目录")
    parser.add_argument("--allow-production", action="store_true", help="允许在 test_mode=false 时运行")

    parser.add_argument("--score-record-id", help="评分 demo 候选人 record_id")
    parser.add_argument("--score-name", help="评分 demo 候选人姓名")
    parser.add_argument("--score-decision", choices=["写入", "跳过", "退出"], help="评分 checkpoint 的自动决策")

    parser.add_argument("--test-email-record-id", help="测试题邮件 demo 候选人 record_id")
    parser.add_argument("--test-email-name", help="测试题邮件 demo 候选人姓名")
    parser.add_argument("--test-file", type=Path, help="测试题附件路径")
    parser.add_argument("--test-email-draft", action="store_true", help="测试题邮件保存草稿，不连接 SMTP")

    parser.add_argument("--contract-record-id", help="合同 demo record_id")
    parser.add_argument("--contract-name", help="合同 demo 姓名")
    parser.add_argument("--contract-send", action="store_true", help="合同生成后发送邮件（TEST_MODE 下发到测试邮箱）")
    parser.add_argument("--contract-draft", action="store_true", help="合同生成后保存草稿")
    parser.add_argument("--contract-dry-run", action="store_true", help="只验证合同变量，不生成文件")

    args = parser.parse_args()
    cfg = require_test_mode(args.allow_production)

    out_dir = (args.output_dir or default_output_dir()).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = out_dir / "transcript.jsonl"
    metadata = {
        "test_mode": is_test_mode(cfg),
        "test_email": get_test_email(cfg),
    }
    records = []

    def run_and_store(step: str, cmd: list[str], timeout: int = 180) -> dict:
        record = run_command(cmd, out_dir, step, timeout=timeout)
        append_jsonl(transcript, record)
        records.append(record)
        print(f"{step}: {command_status(record)} ({record['duration_seconds']}s)")
        return record

    if not any([
        args.score_record_id or args.score_name,
        args.test_email_record_id or args.test_email_name,
        args.contract_record_id or args.contract_name,
    ]):
        raise SystemExit("请至少提供一个 demo 步骤参数，例如 --score-record-id recXXX")

    if args.score_record_id or args.score_name:
        cmd = [sys.executable, str(SCRIPTS_DIR / "run_dialog.py"), "score"]
        add_name_or_record(cmd, args.score_name, args.score_record_id)
        record = run_and_store("01_score_checkpoint", cmd, timeout=240)
        payload = record.get("json") or {}
        token = payload.get("checkpoint_token")
        if token and args.score_decision:
            resume_cmd = [
                sys.executable,
                str(SCRIPTS_DIR / "run_dialog.py"),
                "resume",
                "--token",
                token,
                "--decision",
                args.score_decision,
            ]
            run_and_store("02_score_resume", resume_cmd, timeout=180)

    if args.test_email_record_id or args.test_email_name:
        if not args.test_file:
            raise SystemExit("测试题邮件 demo 需要 --test-file")
        test_file = args.test_file.expanduser().resolve()
        if not test_file.exists():
            raise SystemExit(f"测试题附件不存在：{test_file}")
        cmd = [sys.executable, str(SCRIPTS_DIR / "send_test_email_v2.py")]
        add_name_or_record(cmd, args.test_email_name, args.test_email_record_id)
        cmd += ["--file", str(test_file), "--yes"]
        if args.test_email_draft:
            cmd += ["--draft"]
        run_and_store("03_test_email_send", cmd, timeout=240)

    if args.contract_record_id or args.contract_name:
        cmd = [sys.executable, str(SCRIPTS_DIR / "generate_contract_v2.py")]
        add_name_or_record(cmd, args.contract_name, args.contract_record_id)
        cmd += ["--yes"]
        if args.contract_send:
            cmd += ["--send"]
        if args.contract_draft:
            cmd += ["--draft"]
        if args.contract_dry_run:
            cmd += ["--dry-run"]
        run_and_store("04_contract_generate", cmd, timeout=300)

    write_summary(out_dir, records, metadata)
    print(f"\n证据目录：{out_dir}")
    print(f"摘要：{out_dir / 'summary.md'}")
    print(f"Transcript：{transcript}")


if __name__ == "__main__":
    main()
