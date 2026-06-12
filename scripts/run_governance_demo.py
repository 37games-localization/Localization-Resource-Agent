#!/usr/bin/env python3
"""
Build the final governance demo package for the resource-management Agent.

This script is a demo/orchestration layer. It does not write Lark, send mail,
generate production contracts, or advance real statuses. It runs existing demo
and governance tools, then assembles a terminal-style transcript and an MP4
that show workflow, badcase governance, trace/span replay, and eval.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from badcase_protocol import build_snapshot, issue_body, issue_labels, issue_title
from trace_span import sanitize_value, validate_span


SKILL_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURE_PATH = SKILL_DIR / "demo_fixtures" / "candidates.json"
DEFAULT_OUT_ROOT = Path.home() / ".loc-resume-governance-demo-runs"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run_command(command: list[str], out_dir: Path, name: str, timeout: int = 600) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        command,
        cwd=SKILL_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    duration_ms = int((time.time() - started) * 1000)
    (out_dir / f"{name}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (out_dir / f"{name}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    return {
        "name": name,
        "command": command,
        "returncode": proc.returncode,
        "duration_ms": duration_ms,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
        "ok": proc.returncode == 0,
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compact(value: Any, limit: int = 240) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 3] + "..."


def display_text(value: Any) -> str:
    return str(value or "").replace("⚠️ ", "").replace("✅ ", "").replace("❌ ", "").strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fixture_by_id() -> dict[str, dict[str, Any]]:
    data = load_json(FIXTURE_PATH)
    return {item["record_id"]: item for item in data.get("candidates", [])}


def selected_case(report: dict[str, Any], record_id: str) -> dict[str, Any]:
    for case in report.get("score_cases") or []:
        if case.get("record_id") == record_id:
            return case
    raise KeyError(record_id)


def spans_for(report: dict[str, Any], record_id: str) -> list[dict[str, Any]]:
    spans = []
    for span in report.get("spans") or []:
        payload = json.dumps({"input": span.get("input"), "output": span.get("output")}, ensure_ascii=False)
        if record_id in payload:
            validate_span(span)
            spans.append(span)
    return spans


def build_trace_replay(report: dict[str, Any]) -> dict[str, Any]:
    spans = report.get("spans") or []
    for span in spans:
        validate_span(span)
    statuses = {span.get("status") for span in spans}
    return {
        "source": "governance_demo_fixture",
        "run_id": report.get("run_id"),
        "status": "failed" if "failed" in statuses else "waiting_confirmation",
        "span_count": len(spans),
        "spans": sanitize_value(spans),
    }


def write_trace_summary(path: Path, replay: dict[str, Any]) -> None:
    lines = [
        "# Governance Demo Trace Replay",
        "",
        f"- Run ID: `{replay.get('run_id')}`",
        f"- Status: **{str(replay.get('status')).upper()}**",
        f"- Span count: {replay.get('span_count')}",
        "",
        "## Timeline",
        "",
    ]
    for index, span in enumerate(replay.get("spans") or [], start=1):
        lines.extend([
            f"### {index}. {span.get('step')}",
            "",
            f"- Type: `{span.get('span_type')}`",
            f"- Status: `{span.get('status')}`",
            f"- Input: `{compact(span.get('input', {}))}`",
            f"- Output: `{compact(span.get('output', {}))}`",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_badcase_package(report: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    fixtures = fixture_by_id()
    candidate = fixtures["DEMO-BAD-0006"]
    score_case = selected_case(report, "DEMO-BAD-0006")
    run_spans = spans_for(report, "DEMO-BAD-0006")
    expected = (candidate.get("badcase") or {}).get("expected_result") or "应进入人工复核"
    snapshot = build_snapshot(
        record_id=candidate["record_id"],
        salt="public-demo-fixture",
        current_status=candidate.get("status", ""),
        expected_result=expected,
        language_pair=candidate.get("language_pair", ""),
        services=", ".join(candidate.get("services") or []),
        score=str(score_case.get("score", "")),
        tier=str(score_case.get("tier", "")),
        ai_suggestion=str(score_case.get("recommendation", "")),
        score_basis=str(score_case.get("confidence_reason", "")),
        agent_run={
            "run_id": report.get("run_id"),
            "step_name": "badcase",
            "last_step": "badcase",
            "spans": run_spans,
        },
    )
    title = issue_title(snapshot)
    body = issue_body(snapshot)
    labels = issue_labels(snapshot)
    write_json(out_dir / "badcase_snapshot.json", snapshot)
    (out_dir / "badcase_issue.md").write_text(
        "\n".join([
            f"# {title}",
            "",
            f"Labels: {', '.join(labels)}",
            "",
            body,
        ]),
        encoding="utf-8",
    )
    return {
        "snapshot": snapshot,
        "issue_title": title,
        "issue_labels": labels,
        "issue_path": str(out_dir / "badcase_issue.md"),
        "snapshot_path": str(out_dir / "badcase_snapshot.json"),
    }


def terminal_script(
    *,
    fixture_report: dict[str, Any],
    badcase: dict[str, Any],
    trace_replay: dict[str, Any],
    eval_report: dict[str, Any],
    paths: dict[str, str],
) -> list[str]:
    ja = selected_case(fixture_report, "DEMO-JA-0001")
    ko = selected_case(fixture_report, "DEMO-KO-0002")
    en = selected_case(fixture_report, "DEMO-EN-0003")
    es = selected_case(fixture_report, "DEMO-ES-0004")
    de = selected_case(fixture_report, "DEMO-DE-0005")
    bad = selected_case(fixture_report, "DEMO-BAD-0006")
    eval_cases = eval_report.get("results") or []
    pass_count = sum(1 for case in eval_cases if case.get("status") == "pass")
    changed_count = sum(1 for case in eval_cases if case.get("status") == "changed")
    fail_count = sum(1 for case in eval_cases if case.get("status") == "fail")

    lines = [
        "$ 调用资源管理 Agent，运行最终治理演示",
        "",
        "Resource Management Agent / Governance Demo",
        "目标：展示 workflow、badcase 治理、trace/span、eval 自检，而不是单点脚本列表。",
        "",
        "────────────────────────────────────────────────────────────",
        "1/4 WORKFLOW：自然语言进入流程，Agent 连续推进多个节点",
        "────────────────────────────────────────────────────────────",
        "VM > 调用资源管理 Agent，看下青木遥的简历",
        "Agent > 已定位候选人 DEMO-JA-0001 / 青木遥",
        "Agent > 读取简历附件，完成结构化解析，并调用确定性评分引擎",
        f"Agent > 评分结论：总分 {ja['score']}/100，档位 {ja['tier']}，建议：{ja['recommendation']}",
        f"Agent > 置信度：{ja['confidence']}；依据：{ja['confidence_reason']}",
        "Agent > 下一步：进入测试邀约节点，生成 checkpoint 供 VM 确认",
        "",
        "VM > 给青木遥发送测试题，附件用 demo_fixtures/test_files/game_translation_test.xlsx",
        "Agent > 前置条件检查：候选人、邮箱、附件、当前状态均通过",
        "Agent > 已生成测试邀约草稿；高风险动作保留人工确认",
        "",
        "VM > 给 Meyer Studio GmbH 准备合同",
        f"Agent > 已读取合同信息，模板选择：overseas_company_foreign_currency",
        "Agent > 已列出已填字段 / 缺失字段 / 需人工确认字段",
        "Agent > 合同节点停在 checkpoint，不直接替 VM 发送或推进生产状态",
        "",
        "评分矩阵摘要：",
        f"- 青木遥：{ja['score']}/100，{ja['tier']}，主线强候选人",
        f"- 朴敏雅：{ko['score']}/100，{ko['tier']}，复杂中英混写语言对归一化",
        f"- Alex Chen：{en['score']}/100，{en['tier']}，中等置信度进入测试",
        f"- Lucía García：{es['score']}/100，{es['tier']}，低分/低置信度复核分支",
        f"- Meyer Studio GmbH：{de['score']}/100，{de['tier']}，公司主体合同场景",
        "",
        "────────────────────────────────────────────────────────────",
        "2/4 BADCASE：问题回流、脱敏、归因、沉淀为回归资产",
        "────────────────────────────────────────────────────────────",
        "VM > 把 Badcase Demo 标成 badcase，期望进入人工复核",
        f"Agent > 当前结果：{bad['score']}/100，{bad['tier']}，{bad['recommendation']}",
        "Agent > 已生成 snapshot_version=2.0 的脱敏快照",
        f"Agent > 匿名候选人：{badcase['snapshot']['resource_context']['anonymous_id']}",
        f"Agent > Issue 标题：{display_text(badcase['issue_title'])}",
        f"Agent > Issue 标签：{', '.join(badcase['issue_labels'])}",
        "Agent > Redaction：raw_resume=false, payment_info=false, contract_text=false",
        "Agent > 成长闭环：badcase snapshot → GitHub issue → 修复 → 转为 eval regression",
        "",
        "────────────────────────────────────────────────────────────",
        "3/4 TRACE/SPAN：每次运行可回放、可审计、可定位问题",
        "────────────────────────────────────────────────────────────",
        "$ python3 scripts/replay_run.py --eval-report <eval_report.json>",
        f"Replay > run_id={trace_replay['run_id']}",
        f"Replay > span_count={trace_replay['span_count']}",
        "Replay > timeline:",
    ]
    for index, span in enumerate((trace_replay.get("spans") or [])[:10], start=1):
        output = span.get("output") or {}
        lines.append(
            f"  {index:02d}. {span.get('span_type')} / {span.get('step')} / {span.get('status')} / {compact(output, 120)}"
        )
    lines.extend([
        "",
        "────────────────────────────────────────────────────────────",
        "4/4 EVAL：开发后自动回归，不靠感觉判断有没有改坏",
        "────────────────────────────────────────────────────────────",
        "$ python3 scripts/eval_runner.py",
        f"Eval > overall_status={eval_report.get('overall_status', '').upper()}",
        f"Eval > cases: pass={pass_count}, changed={changed_count}, fail={fail_count}",
    ])
    for case in eval_cases:
        lines.append(f"  - {case.get('title')}: {case.get('status')}")
    lines.extend([
        "",
        "Demo 结论：",
        "- 它能跑 workflow：自然语言触发，多节点串联，关键动作 checkpoint。",
        "- 它能治理 badcase：问题脱敏回流，进入统一 issue 和回归资产。",
        "- 它能留下 trace/span：按 run_id 回放执行链路。",
        "- 它能做 eval：每次改动后自动检查主流程、规则、隐私和演示矩阵。",
        "",
        "Artifacts:",
        f"- Workflow fixture summary: {paths['fixture_summary']}",
        f"- Badcase issue: {badcase['issue_path']}",
        f"- Trace replay: {paths['trace_summary']}",
        f"- Eval summary: {paths['eval_summary']}",
    ])
    return lines


def write_summary(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Final Governance Demo Package",
        "",
        f"- Created at: {report['created_at']}",
        f"- Status: **{report['status'].upper()}**",
        f"- Output dir: `{report['output_dir']}`",
        "",
        "## What This Demo Shows",
        "",
        "1. Workflow: natural-language trigger, candidate routing, multi-step checkpoints.",
        "2. Badcase governance: sanitized snapshot, standard issue, regression loop.",
        "3. Trace/span: run-level replay and span timeline.",
        "4. Eval: automated post-change validation.",
        "",
        "## Artifacts",
        "",
    ]
    for key, value in report.get("artifacts", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend([
        "",
        "## Boundary",
        "",
        "- This package uses sanitized fixtures.",
        "- It does not write Lark, send mail, generate production contracts, or advance real statuses.",
        "- The fixture workflow and eval outputs are produced by executable scripts, not hand-written terminal text.",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def find_font() -> str | None:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ]
    for item in candidates:
        if Path(item).exists():
            return item
    return None


def render_video(lines: list[str], output_path: Path, frames_dir: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False

    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    width, height = 1920, 1080
    margin_x, margin_y = 90, 70
    line_h = 33
    font_path = find_font()
    font = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()
    title_font = ImageFont.truetype(font_path, 34) if font_path else font
    max_chars = 96

    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        if len(line) <= max_chars:
            wrapped.append(line)
        else:
            wrapped.extend(textwrap.wrap(line, width=max_chars, break_long_words=False, replace_whitespace=False))

    lines_per_frame = (height - margin_y * 2 - 70) // line_h
    frame_index = 0
    # Render a readable terminal scroll. At 1 fps and two frames per line, a
    # 90-line transcript becomes roughly three minutes.
    cursors = list(range(1, len(wrapped) + 1))
    if not cursors:
        cursors = [1]
        wrapped = ["Resource Management Agent Governance Demo"]

    for cursor in cursors:
        start = max(0, cursor - lines_per_frame)
        screen = wrapped[start:cursor]
        hold = 3 if cursor in {1, len(wrapped)} else 2
        for _repeat in range(hold):
            img = Image.new("RGB", (width, height), "#0b1020")
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, width, 54), fill="#111827")
            draw.text((margin_x, 14), "Resource Management Agent · Governance Demo", fill="#e5e7eb", font=title_font)
            y = margin_y
            for line in screen:
                color = "#e5e7eb"
                if line.startswith("$") or line.startswith("VM >"):
                    color = "#93c5fd"
                elif line.startswith("Agent >") or line.startswith("Replay >") or line.startswith("Eval >"):
                    color = "#86efac"
                elif line.startswith("─") or line.endswith("能力") or "/4 " in line:
                    color = "#fbbf24"
                elif line.startswith("  -") or line.startswith("- "):
                    color = "#d1d5db"
                draw.text((margin_x, y), line, fill=color, font=font)
                y += line_h
            img.save(frames_dir / f"frame_{frame_index:04d}.png")
            frame_index += 1

    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        "1",
        "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        str(output_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    (frames_dir.parent / "render_video.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (frames_dir.parent / "render_video.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    return proc.returncode == 0 and output_path.exists()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build final governance demo package")
    parser.add_argument("--output-dir", type=Path, help="默认 ~/.loc-resume-governance-demo-runs/<timestamp>")
    parser.add_argument("--skip-video", action="store_true", help="只生成文本/JSON/Markdown，不渲染 MP4")
    parser.add_argument("--json", action="store_true", help="stdout 输出 demo package JSON")
    args = parser.parse_args()

    out_dir = (args.output_dir or (DEFAULT_OUT_ROOT / now_stamp())).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    fixture_dir = out_dir / "01_workflow_fixture"
    eval_dir = out_dir / "04_eval"
    trace_dir = out_dir / "03_trace_replay"
    badcase_dir = out_dir / "02_badcase_governance"
    for item in (fixture_dir, eval_dir, trace_dir, badcase_dir):
        item.mkdir(parents=True, exist_ok=True)

    commands = []
    commands.append(run_command([sys.executable, "scripts/run_fixture_demo.py", "--output-dir", str(fixture_dir)], out_dir, "run_fixture_demo"))
    fixture_report = load_json(fixture_dir / "fixture_demo_report.json")

    badcase = build_badcase_package(fixture_report, badcase_dir)

    trace_replay = build_trace_replay(fixture_report)
    write_json(trace_dir / "trace_replay.json", trace_replay)
    write_trace_summary(trace_dir / "summary.md", trace_replay)

    commands.append(run_command([sys.executable, "scripts/eval_runner.py", "--output-dir", str(eval_dir)], out_dir, "eval_runner"))
    eval_report = load_json(eval_dir / "eval_report.json")

    eval_replay_dir = trace_dir / "eval_replay"
    commands.append(run_command(
        [sys.executable, "scripts/replay_run.py", "--eval-report", str(eval_dir / "eval_report.json"), "--output-dir", str(eval_replay_dir)],
        out_dir,
        "replay_eval_report",
    ))

    paths = {
        "fixture_summary": str(fixture_dir / "summary.md"),
        "fixture_report": str(fixture_dir / "fixture_demo_report.json"),
        "trace_summary": str(trace_dir / "summary.md"),
        "trace_replay": str(trace_dir / "trace_replay.json"),
        "eval_summary": str(eval_dir / "summary.md"),
        "eval_report": str(eval_dir / "eval_report.json"),
    }
    transcript = terminal_script(
        fixture_report=fixture_report,
        badcase=badcase,
        trace_replay=trace_replay,
        eval_report=eval_report,
        paths=paths,
    )
    transcript_path = out_dir / "terminal_recording_script.txt"
    transcript_path.write_text("\n".join(transcript) + "\n", encoding="utf-8")

    video_path = out_dir / "resource-agent-governance-demo.mp4"
    video_ok = False
    if not args.skip_video:
        video_ok = render_video(transcript, video_path, out_dir / "video_frames")

    status = "pass" if all(cmd["ok"] for cmd in commands) and fixture_report.get("overall_status") == "pass" and eval_report.get("overall_status") == "pass" else "fail"
    package = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "output_dir": str(out_dir),
        "commands": [{k: v for k, v in cmd.items() if k not in {"stdout", "stderr"}} for cmd in commands],
        "workflow": {
            "run_id": fixture_report.get("run_id"),
            "overall_status": fixture_report.get("overall_status"),
            "score_case_count": len(fixture_report.get("score_cases") or []),
            "action_case_count": len(fixture_report.get("action_cases") or []),
        },
        "badcase": {
            "issue_title": badcase["issue_title"],
            "issue_labels": badcase["issue_labels"],
            "snapshot_path": badcase["snapshot_path"],
            "issue_path": badcase["issue_path"],
        },
        "trace": {
            "run_id": trace_replay.get("run_id"),
            "span_count": trace_replay.get("span_count"),
            "summary_path": paths["trace_summary"],
        },
        "eval": {
            "run_id": eval_report.get("run_id"),
            "overall_status": eval_report.get("overall_status"),
            "case_count": len(eval_report.get("results") or []),
            "summary_path": paths["eval_summary"],
        },
        "artifacts": {
            "terminal_recording_script": str(transcript_path),
            "video": str(video_path) if video_ok else "",
            "workflow_summary": paths["fixture_summary"],
            "badcase_issue": badcase["issue_path"],
            "trace_summary": paths["trace_summary"],
            "eval_summary": paths["eval_summary"],
            "package_json": str(out_dir / "governance_demo_package.json"),
        },
        "video_rendered": video_ok,
    }
    write_json(out_dir / "governance_demo_package.json", package)
    write_summary(out_dir / "summary.md", package)

    if args.json:
        print(json.dumps(package, ensure_ascii=False, indent=2))
    else:
        print(f"Governance demo status: {status.upper()}")
        print(f"Summary: {out_dir / 'summary.md'}")
        print(f"Transcript: {transcript_path}")
        if video_ok:
            print(f"Video: {video_path}")
        else:
            print("Video: not rendered")
        print(f"JSON: {out_dir / 'governance_demo_package.json'}")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
