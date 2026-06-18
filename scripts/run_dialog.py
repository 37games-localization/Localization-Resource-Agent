#!/usr/bin/env python3
"""
run_dialog.py
=============
对话驱动层核心脚本。

供 AI（OpenClaw）在 SKILL.md 触发后调用，将工作流执行结果以结构化 JSON 输出，
方便 AI 直接解析后转化为自然语言与用户交互。

用法：
    python3 scripts/run_dialog.py score --name "李全鸿"
    python3 scripts/run_dialog.py test-email --name "测试候选人A" --file ~/test.pdf
    python3 scripts/run_dialog.py contract-info-email --name "测试候选人A"
    python3 scripts/run_dialog.py contract --name "测试候选人B"
    python3 scripts/run_dialog.py resume --token ckpt-xxx --decision "写入"

输出：纯 JSON（stdout），AI 解析后转成自然语言给用户。
"""

import sys
import json
import re
import argparse
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
SKILL_DIR   = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))
from schema_gate import assert_schema_ready

# ── 工具：结构化输出 ──────────────────────────────────────────────────────────

JSONL_MODE = False
CURRENT_RUN_ID = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def build_jsonl_event(event_type: str, *, run_id: str | None = None, payload: dict | None = None, **fields) -> dict:
    """Build one CLI-owned event for Thin GUI Wrapper streaming."""
    event = {
        "type": event_type,
        "event_type": event_type,
        "run_id": run_id or CURRENT_RUN_ID or new_run_id(),
        "event_id": new_event_id(),
        "ts": now_iso(),
        "source": "cli",
    }
    if payload is not None:
        event["payload"] = payload
    event.update(fields)
    return event


def checkpoint_type_for(command: str, node: str | None = None) -> str:
    node = node or ""
    mapping = {
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
    if "测试题" in node or "测试邮件" in node:
        return "test_email"
    if "签约信息" in node or "合同信息" in node:
        return "contract_info_email"
    if "合同" in node:
        return "contract"
    if "简历" in node or "评分" in node or "飞书" in node:
        return "resume"
    return mapping.get(command, "generic")


def writeback_fields_for(command: str) -> list[str]:
    mapping = {
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
    return mapping.get(command, ["workflow_log"])


def error_code_for(message: str) -> str:
    if "附件不存在" in message:
        return "missing_file"
    if "请提供 --name 或 --record-id" in message:
        return "missing_candidate"
    if "请提供 --file" in message:
        return "missing_attachment"
    if "请提供 --status" in message:
        return "missing_target_status"
    if "请提供 --token" in message:
        return "missing_checkpoint_token"
    if "请提供 --decision" in message:
        return "missing_decision"
    if "恢复执行失败" in message:
        return "resume_failed"
    if "读取待决策列表失败" in message:
        return "waiting_list_failed"
    if "脚本执行失败" in message:
        return "script_failed"
    if "脚本执行超时" in message:
        return "script_timeout"
    return "cli_error"


def infer_chat_command(message: str) -> str | None:
    """Route natural-language VM input inside the CLI, not in the GUI wrapper."""
    normalized = message.strip()
    sent_signal = re.search(r"已发送|已发出|已经发送|已经发出|人工发送|标记.*发送", normalized)
    contract_info_signal = re.search(r"签约信息|合同信息收集|收集合同信息|签约资料|收款信息", normalized)
    if sent_signal and contract_info_signal:
        return "contract-info-mark-sent"
    if contract_info_signal:
        return "contract-info-email"
    if sent_signal and "测试" in normalized:
        return "test-email-mark-sent"
    if re.search(r"发.*测试|测试题|测试稿|测试邀请|测试邮件", normalized):
        return "test-email"
    if re.search(r"签字|签署|核查|检查.*合同|签回", normalized):
        return "signed-contract"
    if re.search(r"badcase|Badcase|坏例|问题回流|标.*问题", normalized):
        return "badcase"
    if re.search(r"婉拒|拒绝|发拒信|拒信|不通过", normalized):
        return "rejection-email"
    if re.search(r"准备合同|生成合同|发合同|合同草稿", normalized):
        return "contract"
    if re.search(r"重算评分|重跑评分|重新评分", normalized):
        return "score"
    if re.search(r"看|查|简历|处理|评估|初筛", normalized):
        return "score"
    if re.search(r"状态|推进|财务登记", normalized):
        return "update-status"
    return None


def emit_jsonl_event(event_type: str, *, payload: dict | None = None, **fields):
    """Emit exactly one JSON object per stdout line."""
    print(json.dumps(build_jsonl_event(event_type, payload=payload, **fields), ensure_ascii=False, separators=(",", ":")))
    sys.stdout.flush()


def emit(data: dict):
    """向 stdout 输出纯 JSON，确保换行结束"""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.stdout.flush()


def emit_error(message: str, raw_output: str = "", *, code: str | None = None, recoverable: bool = True):
    if JSONL_MODE:
        emit_jsonl_event(
            "error",
            status="failed",
            error={
                "code": code or error_code_for(message),
                "message": message,
                "recoverable": recoverable,
                "raw_output": raw_output[:2000],
            },
        )
        emit_jsonl_event("run_done", status="failed")
        return
    emit({
        "status":     "error",
        "message":    message,
        "raw_output": raw_output[:2000],
    })


def emit_waiting_input(field: str, prompt: str, *, action: str | None = None, accept: list[str] | None = None, candidate: str = ""):
    if JSONL_MODE:
        emit_jsonl_event(
            "waiting_input",
            action=action,
            step=action,
            status="waiting_input",
            field=field,
            prompt=prompt,
            accept=accept or [field],
            candidate={"name": candidate} if candidate else {},
        )
        emit_jsonl_event("run_done", status="waiting_input", field=field)
        return
    emit({
        "status": "waiting_input",
        "field": field,
        "message": prompt,
        "candidate": candidate,
    })


def emit_blocked(message: str, raw_output: str = "", *, code: str = "blocked", suggestions: list[str] | None = None):
    if JSONL_MODE:
        emit_jsonl_event(
            "blocked",
            status="blocked",
            blocked={
                "code": code,
                "message": message,
                "suggestions": suggestions or [],
                "raw_output": raw_output[:2000],
            },
        )
        emit_jsonl_event("run_done", status="blocked")
        return
    emit({
        "status": "blocked",
        "message": message,
        "suggestions": suggestions or [],
        "raw_output": raw_output[:2000],
    })


def emit_done(candidate: str, message: str, raw_output: str = ""):
    if JSONL_MODE:
        emit_jsonl_event(
            "run_done",
            status="done",
            candidate={"name": candidate},
            message=message,
            raw_output=raw_output[:2000],
        )
        return
    emit({
        "status":     "done",
        "candidate":  candidate,
        "message":    message,
        "raw_output": raw_output[:2000],
    })


def ensure_schema_ready(operation: str) -> bool:
    try:
        assert_schema_ready(operation)
        return True
    except Exception as e:
        emit_error(str(e))
        return False


# ── 解析工具 ──────────────────────────────────────────────────────────────────

# ⏸ [CHECKPOINT] node=确认写入飞书 token=ckpt-xxx
CHECKPOINT_RE = re.compile(r"⏸\s*\[CHECKPOINT\]\s+node=(.+?)\s+token=(\S+)")

# 从 stdout 中提取 summary 字段
SUMMARY_PATTERNS = {
    "total_score": re.compile(r"总分[:：]\s*([^\s，,）\)]+)"),
    "tier":        re.compile(r"档位[:：]\s*([^\s，,→→)）\s]+)"),
    "suggestion":  re.compile(r"AI建议[:：]\s*([^\n\r]+?(?=\s{2,}|✅|\[|\n|\r|$))"),  # 截止到2空格/✅/[
    "valid_resume":re.compile(r"有效简历[:：]\s*([^\n\r\s，,]+)"),
}

# 档位 → 建议文案映射
TIER_SUGGESTION = {
    "S":  "优先录用",
    "A":  "推荐录用",
    "B":  "可考虑录用",
    "C":  "不建议录用",
    "D":  "不建议录用",
}


def normalize_score_tier(value: str) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"([SABCD])", text)
    return match.group(1) if match else text


def extract_summary(text: str) -> dict:
    """从脚本 stdout 中提取关键 summary 字段"""
    result = {}
    for key, pattern in SUMMARY_PATTERNS.items():
        m = pattern.search(text)
        if m:
            val = m.group(1).strip()
            # 清理末尾的 ✅ [time] 等工作流注释
            val = re.sub(r'\s*✅.*$', '', val, flags=re.DOTALL).strip()
            val = re.sub(r'\s+\[.*$', '', val).strip()
            val = re.sub(r'\s+(?:done|failed|skipped|success)\b.*$', '', val, flags=re.IGNORECASE).strip()
            if key == "tier":
                val = normalize_score_tier(val)
            if key == "valid_resume":
                raw_val = val
                lowered = raw_val.lower()
                if "无效" in raw_val or "否" in raw_val or "invalid" in lowered or "false" in lowered or "no" == lowered:
                    val = "否"
                elif "有效" in raw_val or "是" in raw_val or "valid" in lowered or "true" in lowered or "yes" == lowered:
                    val = "是"
            result[key] = val

    # 如果 suggestion 为空，根据 tier 推断
    if "suggestion" not in result and "tier" in result:
        tier_clean = normalize_score_tier(result["tier"])
        result["suggestion"] = TIER_SUGGESTION.get(tier_clean, "请人工判断")

    return result


def score_writeback_from_summary(summary: dict) -> dict:
    """Build the logical score writeback payload from a checkpoint summary."""
    writeback = {}
    raw_score = str(summary.get("total_score", "")).strip()
    if raw_score:
        score_text = raw_score.split("/", 1)[0].strip()
        try:
            score_value = float(score_text)
            writeback["score"] = int(score_value) if score_value.is_integer() else score_value
        except ValueError:
            writeback["score"] = score_text

    tier = normalize_score_tier(str(summary.get("tier", "")))
    if tier:
        writeback["rating"] = tier

    valid_resume = str(summary.get("valid_resume", "")).strip()
    if valid_resume:
        writeback["valid_resume"] = "否" if valid_resume in {"否", "无效"} else "是" if valid_resume in {"是", "有效"} else valid_resume

    suggestion = str(summary.get("suggestion", "")).strip()
    if suggestion:
        writeback["ai_suggestion"] = suggestion

    return writeback


def score_summary_from_checkpoint_file(token: str) -> dict:
    """Read the saved score checkpoint context without touching Lark."""
    ckpt_file = Path.home() / ".loc-resume-checkpoints" / f"{token}.json"
    try:
        ckpt_data = json.loads(ckpt_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    context = ckpt_data.get("context") or {}
    summary = {}
    if context.get("总分"):
        summary["total_score"] = str(context.get("总分"))
    if context.get("档位"):
        summary["tier"] = str(context.get("档位"))
    if context.get("AI建议"):
        summary["suggestion"] = str(context.get("AI建议"))
    if context.get("有效简历"):
        summary["valid_resume"] = str(context.get("有效简历"))
    return summary


def extract_candidate_from_output(text: str, fallback: str) -> str:
    """尝试从输出中提取候选人姓名（可选）"""
    m = re.search(r"候选人[:：]\s*(\S+)", text)
    return m.group(1) if m else fallback


def extract_target_status(message: str) -> str:
    patterns = [
        r"(?:状态(?:改成|改为|推进到)?|标记为)([^\s，。；;]+)",
        r"(财务登记中|财务待登记|财务审批中|已入库|已拒绝|测试中|测试通过|测试未通过|合同信息收集中|合同待生成|合同已发送|等待签署|合同已签署)",
    ]
    for pattern in patterns:
        m = re.search(pattern, message or "")
        if m:
            return m.group(1).strip()
    return ""


def find_record_id(name: str) -> tuple:
    """
    通过姓名在飞书记录里查找 record_id。
    返回 (record_id, display_name) 或 (None, error_message)。
    """
    try:
        from rescore_and_write import fetch_all_records
        records = fetch_all_records()
    except Exception as e:
        return None, f"无法读取飞书记录：{e}"

    matches = []
    for r in records:
        raw = r["fields"].get("姓名", "")
        # 飞书返回值可能是 str 或 list
        if isinstance(raw, list):
            candidate_name = " ".join(str(x) for x in raw).strip()
        else:
            candidate_name = str(raw).strip()
        if name.lower() in candidate_name.lower():
            matches.append((r["record_id"], candidate_name))

    if len(matches) == 1:
        return matches[0][0], matches[0][1]
    elif len(matches) == 0:
        return None, f"未找到候选人「{name}」"
    else:
        names = ", ".join(f"{m[1]}({m[0]})" for m in matches)
        return None, f"找到多条记录，请用 --record-id 精确指定：{names}"


def resolve_candidate(args) -> tuple[str | None, str | None]:
    """Resolve name/record_id once for wrapper commands."""
    if not getattr(args, "name", None) and not getattr(args, "record_id", None):
        emit_error("请提供 --name 或 --record-id")
        return None, None

    record_id = getattr(args, "record_id", None)
    candidate = getattr(args, "name", None) or record_id
    if getattr(args, "name", None) and not record_id:
        record_id, display = find_record_id(args.name)
        if record_id is None:
            emit_error(display)
            return None, None
        candidate = display
    return record_id, candidate


# ── 子命令：score ─────────────────────────────────────────────────────────────

def cmd_score(args):
    """
    调用 rescore_and_write_v2.py --dialog --interactive，
    后台运行直到输出 CHECKPOINT 行后返回 JSON。
    """
    if not args.name and not args.record_id:
        emit_error("请提供 --name 或 --record-id")
        return
    if not ensure_schema_ready("score"):
        return

    # 如果提供了姓名，先查 record_id（rescore_and_write_v2.py 只支持 --record-id）
    record_id = args.record_id
    candidate = args.name or args.record_id
    if args.name and not record_id:
        record_id, display = find_record_id(args.name)
        if record_id is None:
            emit_error(display)  # display 是错误信息
            return
        candidate = display

    parse_script = SCRIPTS_DIR / "parse_resumes.py"
    parse_result = subprocess.run(
        [sys.executable, str(parse_script), "--record-id", record_id],
        cwd=str(SKILL_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    parse_output = (parse_result.stdout + parse_result.stderr).strip()
    if parse_result.returncode != 0 or "失败 1" in parse_output or "LLM 解析失败" in parse_output:
        emit_error(
            "评分前置简历解析未完成，已停止评分。请先修复 LLM/API/附件后重试。",
            parse_output,
        )
        return

    # 构建子命令参数
    script = SCRIPTS_DIR / "rescore_and_write_v2.py"
    cmd = [sys.executable, "-u", str(script), "--interactive", "--dialog",
           "--record-id", record_id]

    _run_with_checkpoint(cmd, candidate, args)


def cmd_test_email(args):
    """调用 send_test_email_v2.py（如存在 dialog 支持），否则直接运行"""
    if not args.name and not args.record_id:
        emit_error("请提供 --name 或 --record-id")
        return
    if not args.file:
        emit_waiting_input(
            "attachment",
            "请提供测试题附件或本地路径。",
            action=args.command,
            accept=["file", "local_path"],
            candidate=args.name or args.record_id or "",
        )
        return

    file_path = Path(args.file).expanduser()
    if not file_path.exists():
        emit_error(f"附件不存在：{file_path}")
        return
    if not ensure_schema_ready("test-email"):
        return

    script = SCRIPTS_DIR / "send_test_email_v2.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return

    record_id, candidate = resolve_candidate(args)
    if record_id is None:
        return

    cmd = [sys.executable, str(script)]
    if record_id:
        cmd += ["--record-id", record_id]
    elif args.name:
        cmd += ["--name", args.name]
    # Dialog invocations are non-interactive. Generate a local draft by default
    # and leave the actual send/status writeback to the explicit mark-sent flow.
    cmd += ["--file", str(file_path), "--draft", "--yes"]

    _run_with_checkpoint(cmd, candidate, args)


def cmd_test_email_mark_sent(args):
    """VM 已人工发送测试题后，只写回状态和流程日志。"""
    if not ensure_schema_ready("test-email"):
        return
    script = SCRIPTS_DIR / "send_test_email_v2.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return
    record_id, candidate = resolve_candidate(args)
    if record_id is None:
        return
    cmd = [sys.executable, str(script), "--record-id", record_id, "--mark-sent", "--yes"]
    _run_simple(cmd, candidate, args)


def cmd_contract_info_email(args):
    """调用 send_contract_info_email_v2.py"""
    if not args.name and not args.record_id:
        emit_error("请提供 --name 或 --record-id")
        return
    if not ensure_schema_ready("contract-info-email"):
        return

    script = SCRIPTS_DIR / "send_contract_info_email_v2.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return

    record_id = args.record_id
    candidate = args.name or args.record_id
    if args.name and not record_id:
        record_id, display = find_record_id(args.name)
        if record_id is None:
            emit_error(display)
            return
        candidate = display

    cmd = [sys.executable, str(script)]
    if record_id:
        cmd += ["--record-id", record_id]
    elif args.name:
        cmd += ["--name", args.name]
    # Dialog invocations are non-interactive. Generate a local draft by default
    # and leave the actual send/status writeback to the explicit mark-sent flow.
    cmd += ["--draft", "--yes"]

    _run_with_checkpoint(cmd, candidate, args)


def cmd_contract_info_mark_sent(args):
    """VM 已人工发送签约信息收集邮件后，只写回状态和流程日志。"""
    if not ensure_schema_ready("contract-info-email"):
        return
    script = SCRIPTS_DIR / "send_contract_info_email_v2.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return
    record_id, candidate = resolve_candidate(args)
    if record_id is None:
        return
    cmd = [sys.executable, str(script), "--record-id", record_id, "--mark-sent", "--yes"]
    _run_simple(cmd, candidate, args)


def cmd_contract(args):
    """调用 generate_contract_v2.py"""
    if not args.name and not args.record_id:
        emit_error("请提供 --name 或 --record-id")
        return
    if not ensure_schema_ready("contract"):
        return

    script = SCRIPTS_DIR / "generate_contract_v2.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return

    record_id = args.record_id
    candidate = args.name or args.record_id
    if args.name and not record_id:
        record_id, display = find_record_id(args.name)
        if record_id is None:
            emit_error(display)
            return
        candidate = display

    cmd = [sys.executable, str(script)]
    if record_id:
        cmd += ["--record-id", record_id]
    elif args.name:
        cmd += ["--name", args.name]

    _run_simple(cmd, candidate, args)


def cmd_signed_contract(args):
    """调用签字合同核查脚本。"""
    if not args.name and not args.record_id:
        emit_error("请提供 --name 或 --record-id")
        return
    files = getattr(args, "files", None) or ([args.file] if getattr(args, "file", None) else [])
    if not files:
        emit_waiting_input(
            "attachment",
            "请提供签字合同 PDF 附件或本地路径。",
            action=args.command,
            accept=["file", "local_path"],
            candidate=args.name or args.record_id or "",
        )
        return
    checked_files = []
    for file in files:
        file_path = Path(file).expanduser()
        if not file_path.exists():
            emit_error(f"附件不存在：{file_path}")
            return
        checked_files.append(str(file_path))
    if not ensure_schema_ready("signed-contract"):
        return
    script = SCRIPTS_DIR / "check_signed_contract.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return
    record_id, candidate = resolve_candidate(args)
    if record_id is None:
        return
    cmd = [sys.executable, str(script), "--record-id", record_id]
    for file_path in checked_files:
        cmd += ["--file", file_path]
    # 签字核查正式状态推进仍由脚本内部人工确认；GUI 侧先提供可视化核查结果。
    cmd += ["--dry-run"]
    _run_simple(cmd, candidate, args)


def cmd_update_status(args):
    """调用状态推进脚本。"""
    status = getattr(args, "status", None) or extract_target_status(getattr(args, "message", "") or "")
    if not status:
        emit_waiting_input(
            "target_status",
            "请提供目标招募状态，例如：状态改成财务登记中。",
            action=args.command,
            accept=["target_status"],
            candidate=getattr(args, "name", None) or getattr(args, "record_id", None) or "",
        )
        return
    if not ensure_schema_ready("update-status"):
        return
    script = SCRIPTS_DIR / "update_status.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return
    record_id, candidate = resolve_candidate(args)
    if record_id is None:
        return
    cmd = [sys.executable, str(script), "--record-id", record_id, "--status", status, "--yes"]
    _run_simple(cmd, candidate, args)


def cmd_rejection_email(args):
    """生成婉拒邮件草稿，避免 GUI 直接发送。"""
    if not ensure_schema_ready("rejection-email"):
        return
    script = SCRIPTS_DIR / "send_rejection_email.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return
    record_id, candidate = resolve_candidate(args)
    if record_id is None:
        return
    cmd = [sys.executable, str(script), "--record-id", record_id, "--draft", "--yes"]
    _run_simple(cmd, candidate, args)


def cmd_badcase(args):
    """导出并按统一协议上报 Badcase。"""
    if not ensure_schema_ready("badcase"):
        return
    script = SCRIPTS_DIR / "export_badcase_snapshots.py"
    if not script.exists():
        emit_error(f"脚本不存在：{script}，请检查路径")
        return
    cmd = [sys.executable, str(script)]
    _run_simple(cmd, getattr(args, "name", None) or getattr(args, "record_id", None) or "badcase", args)


def cmd_chat(args):
    """Natural-language CLI entrypoint used by Thin GUI Wrapper."""
    command = infer_chat_command(args.message or "")
    if not command:
        emit_error("无法从 VM 指令中识别要执行的资源管理动作。请明确说明：看简历/评估、发测试题、准备合同，或使用固定按钮。", code="unknown_action")
        return

    forwarded = argparse.Namespace(
        command=command,
        name=args.name,
        record_id=args.record_id,
        file=args.file,
        files=[args.file] if args.file else [],
        status=extract_target_status(args.message or ""),
        message=args.message,
        jsonl=getattr(args, "jsonl", False),
        run_id=getattr(args, "run_id", None),
    )
    if command == "score":
        cmd_score(forwarded)
    elif command == "test-email":
        cmd_test_email(forwarded)
    elif command == "contract-info-email":
        cmd_contract_info_email(forwarded)
    elif command == "test-email-mark-sent":
        cmd_test_email_mark_sent(forwarded)
    elif command == "contract-info-mark-sent":
        cmd_contract_info_mark_sent(forwarded)
    elif command == "contract":
        cmd_contract(forwarded)
    elif command == "signed-contract":
        cmd_signed_contract(forwarded)
    elif command == "update-status":
        cmd_update_status(forwarded)
    elif command == "rejection-email":
        cmd_rejection_email(forwarded)
    elif command == "badcase":
        cmd_badcase(forwarded)
    else:
        emit_error(f"CLI chat 暂不支持该动作：{command}", code="unsupported_action")


# ── 子命令：resume ────────────────────────────────────────────────────────────

def cmd_resume(args):
    """
    从 dialog checkpoint 恢复执行：
    把用户决策写入 checkpoint 文件，后台脚本自动 pick up 并继续执行。
    然后等待后台脚本完成（通过轮询 checkpoint 文件状态）。
    """
    if not args.token:
        emit_error("请提供 --token（格式：ckpt-xxx）")
        return
    if not ensure_schema_ready("resume"):
        return
    if not args.decision:
        emit_error("请提供 --decision（如 '写入' 或 '跳过'）")
        return

    # 调用 workflow_runner.py resume 写入决策
    script = SCRIPTS_DIR / "workflow_runner.py"
    cmd = [
        sys.executable, str(script),
        "resume",
        "--token",    args.token,
        "--decision", args.decision,
    ]

    if JSONL_MODE:
        emit_jsonl_event(
            "vm_decision",
            action=args.command,
            step=args.command,
            token=args.token,
            decision=args.decision,
            status="submitted",
        )

    result = subprocess.run(
        cmd,
        cwd=str(SKILL_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    raw = (result.stdout + result.stderr).strip()

    if result.returncode != 0:
        emit_error(f"恢复执行失败（exit={result.returncode}）：{raw}", raw, code="resume_failed")
        return

    # 等待后台脚本完成（轮询 checkpoint 文件）
    ckpt_file = Path.home() / ".loc-resume-checkpoints" / f"{args.token}.json"
    deadline  = time.time() + 120  # 最多等 2 分钟
    completed = False
    while time.time() < deadline:
        if ckpt_file.exists():
            try:
                ckpt_data = json.loads(ckpt_file.read_text(encoding="utf-8"))
                if ckpt_data.get("status") in ("decided", "done", "completed"):
                    completed = True
                    break
            except Exception:
                pass
        time.sleep(1)

    # 根据决策内容生成自然语言结果
    decision = args.decision
    token    = args.token

    if decision == "退出":
        emit_done(
            candidate=token,
            message=f"用户选择退出，流程已终止",
            raw_output=raw,
        )
    elif decision == "跳过":
        emit_done(
            candidate=token,
            message=f"已跳过写入，评分结果未保存到飞书",
            raw_output=raw,
        )
    else:
        # 写入等情况，等待完成信号
        readback_summary = score_summary_from_checkpoint_file(token)
        readback_fields = score_writeback_from_summary(readback_summary)
        if JSONL_MODE and readback_fields:
            emit_jsonl_event(
                "readback",
                action=args.command,
                step=args.command,
                status="verified",
                token=token,
                checkpoint_token=token,
                checkpoint_type="resume",
                summary=readback_summary,
                writeback_fields=readback_fields,
            )
        if completed:
            emit_done(
                candidate=token,
                message=f"决策「{decision}」已执行，后台任务完成",
                raw_output=raw,
            )
        else:
            # 超时，但可能脚本已经在执行中
            emit_done(
                candidate=token,
                message=f"决策「{decision}」已写入，后台任务处理中（可能需要几秒完成）",
                raw_output=raw,
            )


def cmd_waiting(args):
    """列出流程日志表中等待人工决策的 checkpoint"""
    if not ensure_schema_ready("waiting"):
        return
    try:
        from workflow_runner import fetch_waiting_checkpoints
        rows = fetch_waiting_checkpoints(limit=args.limit)
    except Exception as e:
        emit_error(f"读取待决策列表失败：{e}")
        return

    if JSONL_MODE:
        emit_jsonl_event(
            "waiting_input",
            action=args.command,
            step=args.command,
            status="waiting" if rows else "empty",
            field="checkpoint",
            token=None,
            prompt="请选择等待人工决策的 checkpoint 并调用 resume",
            accept=["checkpoint_token", "decision"],
            waiting=rows,
            message=f"当前有 {len(rows)} 条待决策记录" if rows else "当前没有等待人工决策的候选人",
        )
        emit_jsonl_event("run_done", status="done", count=len(rows))
        return

    emit({
        "status": "done",
        "candidate": "",
        "message": f"当前有 {len(rows)} 条待决策记录" if rows else "当前没有等待人工决策的候选人",
        "waiting": rows,
    })


# ── 核心执行函数 ──────────────────────────────────────────────────────────────

def _run_with_checkpoint(cmd: list, candidate: str, args):
    """
    以后台方式启动脚本，逐行读取 stdout，
    找到 ⏸ [CHECKPOINT] 行后立即返回 checkpoint JSON。
    """
    try:
        emit_jsonl_event(
            "step_started",
            action=args.command,
            step=args.command,
            title=f"执行 {args.command}",
            candidate={"name": candidate},
        ) if JSONL_MODE else None
        proc = subprocess.Popen(
            cmd,
            cwd=str(SKILL_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # 合并 stderr 到 stdout
            text=True,
            encoding="utf-8",
            bufsize=1,  # 行缓冲
            env={**__import__('os').environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as e:
        emit_error(f"启动脚本失败：{e}")
        return

    collected_lines = []
    checkpoint_found = False
    checkpoint_token = None
    checkpoint_node  = None

    # 逐行读取，找到 CHECKPOINT 行后返回
    timeout_deadline = time.time() + 120  # 最多等 2 分钟
    for line in proc.stdout:
        line_stripped = line.rstrip()
        collected_lines.append(line_stripped)
        if JSONL_MODE and line_stripped:
            emit_jsonl_event(
                "tool_output",
                action=args.command,
                step=args.command,
                stream="stdout",
                text=line_stripped,
            )

        # 检测 CHECKPOINT 行
        m = CHECKPOINT_RE.search(line_stripped)
        if m:
            checkpoint_node  = m.group(1).strip()
            checkpoint_token = m.group(2).strip()
            checkpoint_found = True
            break  # 找到后立即返回，不继续等待

        if time.time() > timeout_deadline:
            break

    # 后台继续消费 proc.stdout（防止管道阻塞，但我们不再等待）
    def _drain(p):
        try:
            for _ in p.stdout:
                pass
        except Exception:
            pass

    if checkpoint_found:
        drain_thread = threading.Thread(target=_drain, args=(proc,), daemon=True)
        drain_thread.start()
    else:
        # 没找到 CHECKPOINT，等待进程结束
        try:
            remaining, _ = proc.communicate(timeout=30)
            if remaining:
                collected_lines.extend(remaining.splitlines())
        except subprocess.TimeoutExpired:
            proc.kill()
            collected_lines.append("[超时：进程已终止]")

    raw_output = "\n".join(collected_lines)

    # ── 输出结果 ──────────────────────────────────────────────────────────────
    if checkpoint_found:
        summary = extract_summary(raw_output)
        writeback_preview = score_writeback_from_summary(summary) if checkpoint_type_for(args.command, checkpoint_node) == "resume" else {}
        candidate_display = extract_candidate_from_output(raw_output, candidate)
        options = ["写入", "跳过", "退出"]
        if checkpoint_node and ("测试题邮件" in checkpoint_node or "签约信息收集邮件" in checkpoint_node):
            options = ["保存草稿", "取消"]

        if JSONL_MODE:
            emit_jsonl_event(
                "checkpoint",
                action=args.command,
                step=args.command,
                status="waiting_confirmation",
                token=checkpoint_token,
                checkpoint_token=checkpoint_token,
                checkpoint_type=checkpoint_type_for(args.command, checkpoint_node),
                title=checkpoint_node,
                candidate={"name": candidate_display},
                summary=summary,
                writeback_preview=writeback_preview,
                allowed_actions=options,
                writeback_fields=writeback_fields_for(args.command),
                mode_effective="cli",
                raw_output=raw_output[:2000],
            )
            emit_jsonl_event("run_done", status="waiting_confirmation", token=checkpoint_token)
            return
        emit({
            "status":            "checkpoint",
            "checkpoint_token":  checkpoint_token,
            "node":              checkpoint_node,
            "candidate":         candidate_display,
            "summary":           summary,
            "writeback_preview": writeback_preview,
            "options":           options,
            "raw_output":        raw_output[:2000],
        })
    else:
        # 脚本直接完成，没有 checkpoint（如 dry-run 或无需确认）
        rc = proc.returncode if proc.returncode is not None else 0
        if rc != 0:
            emit_error(f"脚本执行失败（exit={rc}）", raw_output)
        else:
            candidate_display = extract_candidate_from_output(raw_output, candidate)
            summary = extract_summary(raw_output)
            tier    = summary.get("tier", "")
            score   = summary.get("total_score", "")
            suggest = summary.get("suggestion", "")

            parts = []
            if score:
                parts.append(f"总分 {score}")
            if tier:
                parts.append(f"档位 {tier}")
            if suggest:
                parts.append(suggest)

            msg = "、".join(parts) if parts else "脚本已完成执行"
            emit_done(candidate_display, msg, raw_output)


def _run_simple(cmd: list, candidate: str, args=None):
    """
    简单运行脚本，等待完成后输出 JSON。
    用于无 checkpoint 的脚本（test-email、contract）。
    """
    try:
        emit_jsonl_event(
            "step_started",
            action=getattr(args, "command", "simple"),
            step=getattr(args, "command", "simple"),
            title="执行脚本",
            candidate={"name": candidate},
        ) if JSONL_MODE else None
        result = subprocess.run(
            cmd,
            cwd=str(SKILL_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        emit_error("脚本执行超时（>120s）")
        return
    except Exception as e:
        emit_error(f"启动脚本失败：{e}")
        return

    raw = (result.stdout + result.stderr).strip()
    if JSONL_MODE and raw:
        for line in raw.splitlines():
            if line.strip():
                emit_jsonl_event(
                    "tool_output",
                    action=getattr(args, "command", "simple"),
                    step=getattr(args, "command", "simple"),
                    stream="stdout",
                    text=line.rstrip(),
                )

    if result.returncode != 0:
        action = getattr(args, "command", "simple")
        if action == "contract" and "合同变量需要人工补充" in raw and "无法交互输入" in raw:
            emit_waiting_input(
                "contract_required_variables",
                "合同模板需要 VM 补充必填变量。请先补齐合同信息表后重试，或在确认可留空时使用 --yes。",
                action=action,
                accept=["contract_info_update", "explicit_yes"],
                candidate=candidate,
            )
            return
        if action == "contract" and "合同模板表中无 AI合同模版 附件" in raw:
            emit_blocked(
                "合同模板表缺少 AI合同模版附件，无法生成合同。请 VM 先在合同模板表上传模板附件后重试。",
                raw,
                code="missing_contract_template_attachment",
                suggestions=["在合同模板表补上传 AI合同模版 附件", "重新运行合同生成"],
            )
            return
        emit_error(f"脚本执行失败（exit={result.returncode}）", raw)
        return

    # 尝试提取关键信息
    summary = extract_summary(raw)
    candidate_display = extract_candidate_from_output(raw, candidate)

    # 生成成功消息
    if "contract_info" in str(cmd) or "contract-info" in str(cmd):
        if "草稿已保存" in raw:
            msg = f"{candidate_display} 的签约信息收集邮件草稿已生成，等待 VM 人工检查并发送"
        elif "📧 合同信息收集中" in raw and "人工发送" in raw:
            msg = f"{candidate_display} 已确认人工发送签约信息收集邮件，状态已更新为合同信息收集中"
        else:
            msg = f"签约信息收集邮件已处理：{candidate_display}"
    elif "test" in str(cmd) or "email" in str(cmd).lower():
        if "草稿已保存" in raw:
            msg = f"{candidate_display} 的测试题邮件草稿已生成，等待 VM 人工检查并发送"
        elif "📤 测试中" in raw and "人工发送" in raw:
            msg = f"{candidate_display} 已确认人工发送测试题，状态已更新为测试中"
        else:
            msg = f"测试题邮件已处理：{candidate_display}"
            if "TEST_MODE" in raw or "测试邮箱" in raw:
                msg += "（TEST_MODE：已发到测试邮箱）"
    elif "contract" in str(cmd):
        msg = f"{candidate_display} 的合同已生成"
    else:
        tier    = summary.get("tier", "")
        score   = summary.get("total_score", "")
        suggest = summary.get("suggestion", "")
        parts   = []
        if score:
            parts.append(f"总分 {score}")
        if tier:
            parts.append(f"档位 {tier}")
        if suggest:
            parts.append(suggest)
        msg = "、".join(parts) if parts else "脚本已完成执行"

    emit_done(candidate_display, msg, raw)


# ── 参数解析 ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_dialog.py",
        description="对话驱动层：AI 调用此脚本后获得结构化 JSON，转成自然语言与用户交互",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  score       python3 scripts/run_dialog.py score --name "李全鸿"
  test-email  python3 scripts/run_dialog.py test-email --name "测试候选人A" --file ~/test.pdf
  test-email-mark-sent  python3 scripts/run_dialog.py test-email-mark-sent --name "测试候选人A"
  contract-info-email  python3 scripts/run_dialog.py contract-info-email --name "测试候选人A"
  contract-info-mark-sent  python3 scripts/run_dialog.py contract-info-mark-sent --name "测试候选人A"
  contract    python3 scripts/run_dialog.py contract --name "测试候选人B"
  signed-contract python3 scripts/run_dialog.py signed-contract --name "测试候选人B" --file ~/signed.pdf
  update-status python3 scripts/run_dialog.py update-status --name "测试候选人B" --status "财务登记中"
  rejection-email python3 scripts/run_dialog.py rejection-email --name "测试候选人C"
  badcase python3 scripts/run_dialog.py badcase
  resume      python3 scripts/run_dialog.py resume --token ckpt-xxx --decision "写入"
        """,
    )
    parser.add_argument("--jsonl", action="store_true", help="以 JSONL event 流输出（Thin GUI Wrapper 使用）")
    parser.add_argument("--run-id", dest="run_id", help="指定 run_id；默认自动生成")

    sub = parser.add_subparsers(dest="command", title="子命令")
    sub.required = True

    def add_jsonl_option(p):
        p.add_argument("--jsonl", action="store_true", default=argparse.SUPPRESS, help="以 JSONL event 流输出（Thin GUI Wrapper 使用）")
        p.add_argument("--run-id", dest="run_id", default=argparse.SUPPRESS, help="指定 run_id；默认自动生成")
        return p

    # score
    p_score = sub.add_parser("score", help="评分写回（rescore_and_write_v2.py）")
    add_jsonl_option(p_score)
    p_score.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_score.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # test-email
    p_email = sub.add_parser("test-email", help="发测试题邮件")
    add_jsonl_option(p_email)
    p_email.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_email.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")
    p_email.add_argument("--file",      help="测试题 PDF 路径")

    # test-email-mark-sent
    p_email_mark_sent = sub.add_parser("test-email-mark-sent", help="VM 人工发送测试题后写回状态")
    add_jsonl_option(p_email_mark_sent)
    p_email_mark_sent.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_email_mark_sent.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # contract-info-email
    p_contract_info = sub.add_parser("contract-info-email", help="发送签约信息收集邮件")
    add_jsonl_option(p_contract_info)
    p_contract_info.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_contract_info.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # contract-info-mark-sent
    p_contract_info_mark_sent = sub.add_parser("contract-info-mark-sent", help="VM 人工发送签约信息收集邮件后写回状态")
    add_jsonl_option(p_contract_info_mark_sent)
    p_contract_info_mark_sent.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_contract_info_mark_sent.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # contract
    p_contract = sub.add_parser("contract", help="生成合同")
    add_jsonl_option(p_contract)
    p_contract.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_contract.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # signed-contract
    p_signed = sub.add_parser("signed-contract", help="核查签字合同")
    add_jsonl_option(p_signed)
    p_signed.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_signed.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")
    p_signed.add_argument("--file",      action="append", dest="files", help="签字合同 PDF 路径，可多次提供")

    # update-status
    p_status = sub.add_parser("update-status", help="手动推进候选人招募状态")
    add_jsonl_option(p_status)
    p_status.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_status.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")
    p_status.add_argument("--status",    help="目标招募状态")

    # rejection-email
    p_rejection = sub.add_parser("rejection-email", help="生成婉拒邮件草稿")
    add_jsonl_option(p_rejection)
    p_rejection.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_rejection.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # badcase
    p_badcase = sub.add_parser("badcase", help="导出并上报已标记 Badcase")
    add_jsonl_option(p_badcase)
    p_badcase.add_argument("--name",      help="候选人姓名（可选，仅用于展示）")
    p_badcase.add_argument("--record-id", dest="record_id", help="飞书 record_id（可选，仅用于展示）")

    # chat
    p_chat = sub.add_parser("chat", help="自然语言入口（由 CLI 判断资源管理动作）")
    add_jsonl_option(p_chat)
    p_chat.add_argument("--message", required=True, help="VM 原始自然语言指令")
    p_chat.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_chat.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")
    p_chat.add_argument("--file",      help="附件路径")

    # resume
    p_resume = sub.add_parser("resume", help="从 dialog checkpoint 恢复执行")
    add_jsonl_option(p_resume)
    p_resume.add_argument("--token",    required=True, help="checkpoint token（格式：ckpt-xxx）")
    p_resume.add_argument("--decision", required=True, help="决策内容（如 '写入' 或 '跳过'）")

    # waiting
    p_waiting = sub.add_parser("waiting", help="列出等待人工决策的 checkpoint")
    add_jsonl_option(p_waiting)
    p_waiting.add_argument("--limit", type=int, default=50, help="最多读取多少条")

    return parser


COMMAND_MAP = {
    "score":      cmd_score,
    "test-email": cmd_test_email,
    "test-email-mark-sent": cmd_test_email_mark_sent,
    "contract-info-email": cmd_contract_info_email,
    "contract-info-mark-sent": cmd_contract_info_mark_sent,
    "contract":   cmd_contract,
    "signed-contract": cmd_signed_contract,
    "update-status": cmd_update_status,
    "rejection-email": cmd_rejection_email,
    "badcase": cmd_badcase,
    "chat":       cmd_chat,
    "resume":     cmd_resume,
    "waiting":    cmd_waiting,
}


def main():
    global JSONL_MODE, CURRENT_RUN_ID
    parser = build_parser()
    args   = parser.parse_args()
    JSONL_MODE = bool(getattr(args, "jsonl", False))
    CURRENT_RUN_ID = getattr(args, "run_id", "") or new_run_id()

    handler = COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    if JSONL_MODE:
        emit_jsonl_event(
            "run_started",
            action=args.command,
            step=args.command,
            mode_requested="cli",
            mode_effective="cli",
            input={
                "command": args.command,
                "name": getattr(args, "name", None),
                "record_id": getattr(args, "record_id", None),
                "file": getattr(args, "file", None),
                "files": getattr(args, "files", None),
                "status": getattr(args, "status", None),
                "token": getattr(args, "token", None),
                "decision": getattr(args, "decision", None),
            },
        )
    handler(args)


if __name__ == "__main__":
    main()
