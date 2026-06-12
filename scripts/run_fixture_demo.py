#!/usr/bin/env python3
"""
Run the sanitized multi-case demo fixture set.

This is a demo/eval layer only. It does not read or write Lark, send mail,
generate production contracts, or advance real candidate status. It reuses the
existing scoring engine and emits transcript + trace/span evidence for final
demo preparation and regression checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from trace_span import TraceSpan, new_run_id, sanitize_value, validate_span


SKILL_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURE_DIR = SKILL_DIR / "demo_fixtures"
DEFAULT_OUT_ROOT = Path.home() / ".loc-resume-demo-fixture-runs"

sys.path.insert(0, str(SCRIPTS_DIR))

from resume_screening_engine_v2 import ResumeScreeningEngineV2  # noqa: E402


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def load_fixtures(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = data.get("candidates") or []
    if not candidates:
        raise SystemExit(f"no candidates in fixture file: {path}")
    return data


def candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    resume = candidate.get("resume") or {}
    return {
        "姓名": candidate.get("name", ""),
        "语言对": candidate.get("language_pair", ""),
        "人工翻译单价": candidate.get("translation_price"),
        "AIPE单价": candidate.get("aipe_price"),
        "报价商议空间": candidate.get("negotiation", ""),
        "提供的服务": candidate.get("services") or [],
        "常居地": candidate.get("location", ""),
        "项目经历": load_resume_excerpt(resume.get("fixture_path", "")),
        "其他相关经历": candidate.get("demo_notes", ""),
        "熟悉的IP": resume.get("parsed_entities", ""),
        "_parsed_word_count": resume.get("parsed_word_count"),
        "_parsed_years": resume.get("parsed_years"),
        "_parsed_project_cnt": resume.get("parsed_project_count"),
        "_parsed_entities": resume.get("parsed_entities", ""),
    }


def load_resume_excerpt(relative_path: str) -> str:
    if not relative_path:
        return ""
    path = FIXTURE_DIR / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def recommendation_for(result: dict[str, Any], expected: dict[str, Any]) -> str:
    if expected.get("recommendation"):
        return str(expected["recommendation"])
    tier = result.get("final_tier")
    return {
        "S": "优先录用",
        "A": "优先联系",
        "B": "可进入测试",
        "C": "建议人工复核或婉拒",
    }.get(tier, "人工复核")


def run_score_case(
    *,
    engine: ResumeScreeningEngineV2,
    run_id: str,
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    payload = candidate_payload(candidate)
    result = engine.calculate_final_result(payload)
    expected = candidate.get("expected") or {}
    resume = candidate.get("resume") or {}
    score = result.get("final_score", 0)
    tier = result.get("final_tier", "")
    price = result.get("price_result", {}).get("score", 0)
    exp = result.get("experience_result", {}).get("total_score", 0)
    adjustment = result.get("bonus_penalty", {}).get("net_adjustment", 0)
    recommendation = recommendation_for(result, expected)

    case_status = "pass"
    notes: list[str] = []
    if expected.get("tier") and tier != expected["tier"]:
        case_status = "changed"
        notes.append(f"预期档位 {expected['tier']}，实际 {tier}")
    if expected.get("score_min") is not None and score < expected["score_min"]:
        case_status = "changed"
        notes.append(f"预期总分 >= {expected['score_min']}，实际 {score}")
    if expected.get("score_max") is not None and score > expected["score_max"]:
        case_status = "changed"
        notes.append(f"预期总分 <= {expected['score_max']}，实际 {score}")

    transcript = [
        f"VM: 调用资源管理 Agent，看下 {candidate['name']} 的简历",
        f"Agent: 已定位候选人 {candidate['name']} / {candidate['record_id']}",
        f"Agent: 读取简历 fixture {resume.get('fixture_path', '-')}",
        f"Agent: 解析字段：字数 {resume.get('parsed_word_count')}, 年限 {resume.get('parsed_years')}, 项目数 {resume.get('parsed_project_count')}",
        f"Agent: {candidate['name']} 的评分结论：",
        f"  - 总分：{score}/100",
        f"  - 档位：{tier}",
        f"  - 价格：{price}/50",
        f"  - 资历：{exp}/50",
        f"  - 微调：{adjustment:+}",
        f"  - AI建议：{recommendation}",
        f"  - 置信度：{resume.get('confidence', '-')}",
        f"  - 依据：{resume.get('confidence_reason', '-')}",
        f"Checkpoint: 请 VM 确认是否推进到 {expected.get('next_status', '下一状态')}",
    ]

    spans = [
        TraceSpan(
            run_id=run_id,
            step="candidate-locate",
            span_type="lark_read",
            status="success",
            input={"candidate": candidate.get("name"), "record_id": candidate.get("record_id")},
            output={"status": candidate.get("status"), "language_pair": candidate.get("language_pair")},
        ).to_dict(),
        TraceSpan(
            run_id=run_id,
            step="resume-parse",
            span_type="llm_call",
            status="success",
            input={"resume_fixture": resume.get("fixture_path"), "mode": "fixture"},
            output={
                "word_count": resume.get("parsed_word_count"),
                "years": resume.get("parsed_years"),
                "project_count": resume.get("parsed_project_count"),
                "confidence": resume.get("confidence"),
                "confidence_reason": resume.get("confidence_reason"),
            },
        ).to_dict(),
        TraceSpan(
            run_id=run_id,
            step="score",
            span_type="tool_call",
            status="success" if case_status == "pass" else "skipped",
            input={"language_pair": candidate.get("language_pair"), "services": candidate.get("services")},
            output={
                "score": score,
                "tier": tier,
                "price_score": price,
                "experience_score": exp,
                "recommendation": recommendation,
                "case_status": case_status,
                "notes": notes,
            },
        ).to_dict(),
        TraceSpan(
            run_id=run_id,
            step="score-checkpoint",
            span_type="checkpoint",
            status="waiting_confirmation",
            input={"candidate": candidate.get("record_id")},
            output={
                "summary": f"{candidate['name']}：{score}/100，{tier}，{recommendation}",
                "next_status": expected.get("next_status"),
                "options": ["确认推进", "人工复核", "标记badcase"],
            },
        ).to_dict(),
    ]
    for span in spans:
        validate_span(span)

    summary = {
        "record_id": candidate.get("record_id"),
        "name": candidate.get("name"),
        "case_status": case_status,
        "notes": notes,
        "score": score,
        "tier": tier,
        "price_score": price,
        "experience_score": exp,
        "adjustment": adjustment,
        "recommendation": recommendation,
        "confidence": resume.get("confidence"),
        "confidence_reason": resume.get("confidence_reason"),
        "next_status": expected.get("next_status"),
    }
    return summary, spans, transcript


def run_action_case(run_id: str, candidate: dict[str, Any], action: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    name = candidate.get("name")
    record_id = candidate.get("record_id")
    contract = candidate.get("contract") or {}
    badcase = candidate.get("badcase") or {}

    if action == "test_email":
        transcript = [
            f"VM: 给 {name} 发送测试题，附件用 demo_fixtures/test_files/game_translation_test.xlsx",
            f"Agent: 前置条件检查通过：候选人、邮箱、附件、当前状态",
            f"Agent: 已生成测试邀约草稿，收件人 {candidate.get('email')}",
            "Checkpoint: 请 VM 确认邮件内容和附件后发送。",
        ]
        output = {
            "recipient_ref": record_id,
            "attachment": "demo_fixtures/test_files/game_translation_test.xlsx",
            "checkpoint": "confirm_test_email",
        }
        step = "test-email"
    elif action == "contract":
        transcript = [
            f"VM: 给 {name} 准备合同",
            f"Agent: 已读取合同信息 {contract.get('info_record_id') or '-'}",
            f"Agent: 模板选择：{contract.get('template_expected')}",
            f"Agent: 需人工处理字段：{', '.join(contract.get('required_manual_fields') or [])}",
            "Checkpoint: 请 VM 预览合同变量填充结果后确认。",
        ]
        output = {
            "contract_info_record_id": contract.get("info_record_id"),
            "template_expected": contract.get("template_expected"),
            "manual_fields": contract.get("required_manual_fields") or [],
            "checkpoint": "confirm_contract_draft",
        }
        step = "contract"
    elif action == "badcase":
        transcript = [
            f"VM: 把 {name} 标成 badcase，期望进入人工复核",
            "Agent: 已生成脱敏 snapshot 摘要。",
            f"Agent: 期望结果：{badcase.get('expected_result')}",
            "Checkpoint: 项目侧可按统一协议创建 issue。",
        ]
        output = {
            "snapshot_version": "2.0",
            "badcase_flag": badcase.get("flag"),
            "expected_result": badcase.get("expected_result"),
            "contains_raw_resume": False,
            "contains_payment_info": False,
        }
        step = "badcase"
    else:
        raise ValueError(f"unsupported action: {action}")

    span = TraceSpan(
        run_id=run_id,
        step=step,
        span_type="tool_call",
        status="waiting_confirmation",
        input={"candidate_record_id": record_id, "action": action},
        output=output,
    ).to_dict()
    validate_span(span)
    summary = {
        "record_id": record_id,
        "name": name,
        "case_status": "pass",
        "action": action,
        "checkpoint": output.get("checkpoint", step),
    }
    return summary, [span], transcript


def write_outputs(out_dir: Path, report: dict[str, Any], transcript_lines: list[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "fixture_demo_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "transcript.txt").write_text("\n".join(transcript_lines) + "\n", encoding="utf-8")

    lines = [
        "# Demo Fixture Run",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Created at: {report['created_at']}",
        f"- Overall status: **{report['overall_status'].upper()}**",
        f"- Candidate cases: {len(report['score_cases'])}",
        f"- Action cases: {len(report['action_cases'])}",
        f"- Span count: {len(report['spans'])}",
        f"- Output dir: `{out_dir}`",
        "",
        "## Score Cases",
        "",
        "| Candidate | Language | Score | Tier | Recommendation | Confidence | Status |",
        "|---|---|---:|---:|---|---|---|",
    ]
    by_id = {case["record_id"]: case for case in report["score_cases"]}
    for case in report["score_cases"]:
        candidate = report["fixture_index"].get(case["record_id"], {})
        lines.append(
            f"| {case['name']} | {candidate.get('language_pair', '-')} | {case['score']} | {case['tier']} | "
            f"{case['recommendation']} | {case.get('confidence', '-')} | {case['case_status']} |"
        )

    lines.extend(["", "## Action Cases", "", "| Candidate | Action | Checkpoint | Status |", "|---|---|---|---|"])
    for case in report["action_cases"]:
        lines.append(f"| {case['name']} | {case['action']} | {case['checkpoint']} | {case['case_status']} |")

    changed = [case for case in by_id.values() if case.get("case_status") != "pass"]
    if changed:
        lines.extend(["", "## Changed Cases", ""])
        for case in changed:
            lines.append(f"- {case['name']}: {'; '.join(case.get('notes') or [])}")

    lines.extend([
        "",
        "## Boundary",
        "",
        "- This runner is fixture/demo/eval only.",
        "- It does not write Lark, send email, generate production contracts, or advance real statuses.",
        "- Core scoring is calculated by `resume_screening_engine_v2.py`; other actions are checkpoint fixtures.",
    ])
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def overall_status(score_cases: list[dict[str, Any]], action_cases: list[dict[str, Any]]) -> str:
    statuses = {case.get("case_status") for case in score_cases + action_cases}
    if "fail" in statuses:
        return "fail"
    if "changed" in statuses:
        return "changed"
    return "pass"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run sanitized demo fixture matrix")
    parser.add_argument("--fixtures", type=Path, default=FIXTURE_DIR / "candidates.json")
    parser.add_argument("--output-dir", type=Path, help="默认 ~/.loc-resume-demo-fixture-runs/<timestamp>")
    parser.add_argument("--json", action="store_true", help="stdout 输出 JSON report")
    args = parser.parse_args()

    data = load_fixtures(args.fixtures)
    run_id = new_run_id("fixture_demo")
    out_dir = (args.output_dir or (DEFAULT_OUT_ROOT / now_stamp())).expanduser()
    engine = ResumeScreeningEngineV2(
        config_path=SKILL_DIR / "config" / "resume_screening_rules_v2.json",
        allow_local_rules=True,
    )

    score_cases: list[dict[str, Any]] = []
    action_cases: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    transcript_lines: list[str] = []

    candidates = data.get("candidates") or []
    for candidate in candidates:
        summary, case_spans, transcript = run_score_case(
            engine=engine,
            run_id=run_id,
            candidate=candidate,
        )
        score_cases.append(summary)
        spans.extend(case_spans)
        transcript_lines.extend(["", f"## {candidate['record_id']} / {candidate['name']}", *transcript])

    actions = [
        ("DEMO-JA-0001", "test_email"),
        ("DEMO-DE-0005", "contract"),
        ("DEMO-BAD-0006", "badcase"),
    ]
    candidate_by_id = {candidate["record_id"]: candidate for candidate in candidates}
    for record_id, action in actions:
        candidate = candidate_by_id.get(record_id)
        if not candidate:
            continue
        summary, case_spans, transcript = run_action_case(run_id, candidate, action)
        action_cases.append(summary)
        spans.extend(case_spans)
        transcript_lines.extend(["", f"## {record_id} / {action}", *transcript])

    report = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": "demo_fixtures",
        "overall_status": overall_status(score_cases, action_cases),
        "score_cases": score_cases,
        "action_cases": action_cases,
        "fixture_index": {
            candidate["record_id"]: {
                "name": candidate["name"],
                "language_pair": candidate.get("language_pair"),
                "status": candidate.get("status"),
            }
            for candidate in candidates
        },
        "spans": sanitize_value(spans),
        "output_dir": str(out_dir),
    }

    write_outputs(out_dir, report, transcript_lines)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Fixture demo status: {report['overall_status'].upper()}")
        print(f"Summary: {out_dir / 'summary.md'}")
        print(f"Transcript: {out_dir / 'transcript.txt'}")
        print(f"JSON: {out_dir / 'fixture_demo_report.json'}")
    return 0 if report["overall_status"] in {"pass", "changed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
