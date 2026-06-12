#!/usr/bin/env python3
"""
Run production-governance evals for the resource-management Agent.

This runner is a QA layer. It calls existing tests/checks, captures evidence,
and writes a machine-readable JSON report plus a human-readable Markdown
summary. It does not call business actions, write Lark records, or decide
candidate outcomes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trace_span import TraceSpan, new_run_id, validate_span


SKILL_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
DEFAULT_EVAL_ROOT = Path.home() / ".loc-resume-eval-runs"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    title: str
    command: list[str]
    kind: str
    timeout: int = 300
    allow_changed: bool = False


EVAL_CASES = [
    EvalCase(
        case_id="issue_regressions",
        title="生产 issue / badcase 回归",
        command=[sys.executable, "-m", "unittest", "tests.test_issue_regressions"],
        kind="unit_test",
    ),
    EvalCase(
        case_id="scoring_engine_rules",
        title="评分引擎规则测试",
        command=[sys.executable, "tests/run_tests.py"],
        kind="unit_test",
    ),
    EvalCase(
        case_id="pricing_rule_coverage",
        title="Lark 评分规则 22 个主流市场覆盖",
        command=[sys.executable, "scripts/verify_pricing_rule_coverage.py"],
        kind="lark_config_eval",
    ),
    EvalCase(
        case_id="integration_readiness",
        title="v2 分步骤集成验收",
        command=[sys.executable, "scripts/integration_readiness.py"],
        kind="integration_eval",
    ),
    EvalCase(
        case_id="privacy_scan",
        title="仓库敏感信息扫描",
        command=[sys.executable, "scripts/privacy_scan.py"],
        kind="safety_eval",
    ),
    EvalCase(
        case_id="regression_report",
        title="变更影响面回归报告",
        command=[sys.executable, "scripts/regression_report.py", "--json"],
        kind="change_impact_eval",
        allow_changed=True,
    ),
    EvalCase(
        case_id="demo_fixture_matrix",
        title="最终演示虚拟测试集矩阵",
        command=[sys.executable, "scripts/run_fixture_demo.py"],
        kind="demo_fixture_eval",
    ),
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def clean_tail(text: str, limit: int = 12000) -> str:
    if not text:
        return ""
    text = text[-limit:]
    return text.strip()


def run_case(case: EvalCase, out_dir: Path) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    started = time.time()
    timed_out = False
    command = command_for_case(case, out_dir)
    try:
        proc = subprocess.run(
            command,
            cwd=SKILL_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=case.timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
        )
        returncode = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""

    duration_ms = int((time.time() - started) * 1000)
    parsed = parse_case_output(case, stdout, stderr, returncode, timed_out)
    status = parsed["status"]
    evidence = {
        "case_id": case.case_id,
        "title": case.title,
        "kind": case.kind,
        "status": status,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
        "started_at": started_at,
        "command": command,
        "stdout_tail": clean_tail(stdout),
        "stderr_tail": clean_tail(stderr, limit=6000),
        "metrics": parsed.get("metrics", {}),
        "notes": parsed.get("notes", []),
    }

    (out_dir / f"{case.case_id}.stdout.txt").write_text(stdout, encoding="utf-8")
    (out_dir / f"{case.case_id}.stderr.txt").write_text(stderr, encoding="utf-8")
    return evidence


def command_for_case(case: EvalCase, out_dir: Path) -> list[str]:
    if case.case_id == "demo_fixture_matrix":
        return [*case.command, "--output-dir", str(out_dir / case.case_id)]
    return case.command


def parse_case_output(
    case: EvalCase,
    stdout: str,
    stderr: str,
    returncode: int,
    timed_out: bool,
) -> dict[str, Any]:
    if timed_out:
        return {"status": "fail", "notes": ["command timed out"]}
    if returncode != 0:
        return {"status": "fail", "notes": [last_line(stderr) or last_line(stdout) or "non-zero returncode"]}

    if case.case_id == "pricing_rule_coverage":
        payload = load_json(stdout)
        ok = bool(payload.get("ok"))
        return {
            "status": "pass" if ok else "fail",
            "metrics": {
                "required_count": payload.get("required_count"),
                "available_count": payload.get("available_count"),
                "missing_count": len(payload.get("missing") or []),
                "extra_count": len(payload.get("extra") or []),
            },
            "notes": [f"table_id={payload.get('table_id')}"] if payload else [],
        }

    if case.case_id == "integration_readiness":
        passed = "总状态: PASS" in stdout
        return {"status": "pass" if passed else "fail", "notes": ["integration readiness PASS" if passed else "missing PASS marker"]}

    if case.case_id == "regression_report":
        payload = load_json(stdout)
        gate = payload.get("gate", "")
        status = "pass" if gate in {"LOW_RISK", "OBSERVATION_ONLY"} else "changed"
        if gate == "BLOCKED":
            status = "fail"
        return {
            "status": status,
            "metrics": payload.get("counts", {}),
            "notes": [f"gate={gate}", payload.get("conclusion", "")],
        }

    return {"status": "pass", "notes": [last_line(stdout)] if last_line(stdout) else []}


def load_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}


def last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def overall_status(results: list[dict[str, Any]]) -> str:
    statuses = {result["status"] for result in results}
    if "fail" in statuses:
        return "fail"
    if "changed" in statuses:
        return "changed"
    return "pass"


def build_spans(run_id: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans = []
    for result in results:
        span = TraceSpan(
            run_id=run_id,
            step=result["case_id"],
            span_type="tool_call",
            status="success" if result["status"] in {"pass", "changed"} else "failed",
            input={
                "title": result["title"],
                "kind": result["kind"],
                "command": result["command"],
            },
            output={
                "eval_status": result["status"],
                "metrics": result.get("metrics", {}),
                "notes": result.get("notes", []),
            },
            duration_ms=result["duration_ms"],
            error={"stderr_tail": result.get("stderr_tail", "")} if result["status"] == "fail" else {},
        ).to_dict()
        validate_span(span)
        spans.append(span)
    return spans


def write_report(out_dir: Path, payload: dict[str, Any]) -> None:
    (out_dir / "eval_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Resource Agent Eval Report",
        "",
        f"- Run ID: `{payload['run_id']}`",
        f"- Created at: {payload['created_at']}",
        f"- Overall status: **{payload['overall_status'].upper()}**",
        f"- Output dir: `{out_dir}`",
        "",
        "## Cases",
        "",
        "| Case | Status | Duration | Notes |",
        "|---|---:|---:|---|",
    ]
    for result in payload["results"]:
        notes = "; ".join(str(note) for note in result.get("notes", []) if note)
        lines.append(
            f"| {result['title']} | {result['status']} | {result['duration_ms']}ms | {notes} |"
        )

    lines.extend([
        "",
        "## Governance Meaning",
        "",
        "- `pass`: 当前检查通过。",
        "- `changed`: 检查本身通过，但发现需要人工关注的变更影响面，例如主流程改动后仍需单节点 QA。",
        "- `fail`: 检查失败，不能宣称本轮 Agent 稳定。",
        "",
        "## Trace Spans",
        "",
        f"- Span count: {len(payload['spans'])}",
        "- `eval_report.json` contains sanitized trace/span records for replay and audit.",
    ])
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def selected_cases(case_ids: list[str] | None) -> list[EvalCase]:
    if not case_ids:
        return EVAL_CASES
    wanted = set(case_ids)
    cases = [case for case in EVAL_CASES if case.case_id in wanted]
    missing = sorted(wanted - {case.case_id for case in cases})
    if missing:
        raise SystemExit(f"unknown eval case(s): {', '.join(missing)}")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Run resource-management Agent governance evals")
    parser.add_argument("--case", action="append", dest="cases", help="只运行指定 case_id，可重复")
    parser.add_argument("--output-dir", type=Path, help="输出目录，默认 ~/.loc-resume-eval-runs/<timestamp>")
    parser.add_argument("--json", action="store_true", help="只在 stdout 输出 eval_report.json 内容")
    args = parser.parse_args()

    run_id = new_run_id("eval")
    out_dir = (args.output_dir or (DEFAULT_EVAL_ROOT / now_stamp())).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    results = [run_case(case, out_dir) for case in selected_cases(args.cases)]
    payload = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "overall_status": overall_status(results),
        "results": results,
        "spans": build_spans(run_id, results),
        "output_dir": str(out_dir),
    }
    write_report(out_dir, payload)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Eval status: {payload['overall_status'].upper()}")
        print(f"Report: {out_dir / 'summary.md'}")
        print(f"JSON: {out_dir / 'eval_report.json'}")
    return 0 if payload["overall_status"] in {"pass", "changed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
