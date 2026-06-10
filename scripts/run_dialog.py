#!/usr/bin/env python3
"""
run_dialog.py
=============
对话驱动层核心脚本。

供 AI（OpenClaw）在 SKILL.md 触发后调用，将工作流执行结果以结构化 JSON 输出，
方便 AI 直接解析后转化为自然语言与用户交互。

用法：
    python3 scripts/run_dialog.py score --name "李全鸿"
    python3 scripts/run_dialog.py test-email --name "青木遥" --file ~/test.pdf
    python3 scripts/run_dialog.py contract --name "宋赛楠"
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
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
SKILL_DIR   = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))

# ── 工具：结构化输出 ──────────────────────────────────────────────────────────

def emit(data: dict):
    """向 stdout 输出纯 JSON，确保换行结束"""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.stdout.flush()


def emit_error(message: str, raw_output: str = ""):
    emit({
        "status":     "error",
        "message":    message,
        "raw_output": raw_output[:2000],
    })


def emit_done(candidate: str, message: str, raw_output: str = ""):
    emit({
        "status":     "done",
        "candidate":  candidate,
        "message":    message,
        "raw_output": raw_output[:2000],
    })


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
            result[key] = val

    # 如果 suggestion 为空，根据 tier 推断
    if "suggestion" not in result and "tier" in result:
        tier_clean = re.sub(r"[^A-Z]", "", result["tier"].upper())
        result["suggestion"] = TIER_SUGGESTION.get(tier_clean, "请人工判断")

    return result


def extract_candidate_from_output(text: str, fallback: str) -> str:
    """尝试从输出中提取候选人姓名（可选）"""
    m = re.search(r"候选人[:：]\s*(\S+)", text)
    return m.group(1) if m else fallback


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


# ── 子命令：score ─────────────────────────────────────────────────────────────

def cmd_score(args):
    """
    调用 rescore_and_write_v2.py --dialog --interactive，
    后台运行直到输出 CHECKPOINT 行后返回 JSON。
    """
    if not args.name and not args.record_id:
        emit_error("请提供 --name 或 --record-id")
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
        emit_error("发测试题需要 --file 参数（测试题 PDF 路径）")
        return

    file_path = Path(args.file).expanduser()
    if not file_path.exists():
        emit_error(f"附件不存在：{file_path}")
        return

    script = SCRIPTS_DIR / "send_test_email_v2.py"
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
    cmd += ["--file", str(file_path)]

    _run_simple(cmd, candidate)


def cmd_contract(args):
    """调用 generate_contract_v2.py"""
    if not args.name and not args.record_id:
        emit_error("请提供 --name 或 --record-id")
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

    _run_simple(cmd, candidate)


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

    result = subprocess.run(
        cmd,
        cwd=str(SKILL_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    raw = (result.stdout + result.stderr).strip()

    if result.returncode != 0:
        emit_error(f"恢复执行失败（exit={result.returncode}）：{raw}", raw)
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


# ── 核心执行函数 ──────────────────────────────────────────────────────────────

def _run_with_checkpoint(cmd: list, candidate: str, args):
    """
    以后台方式启动脚本，逐行读取 stdout，
    找到 ⏸ [CHECKPOINT] 行后立即返回 checkpoint JSON。
    """
    try:
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
        candidate_display = extract_candidate_from_output(raw_output, candidate)

        emit({
            "status":            "checkpoint",
            "checkpoint_token":  checkpoint_token,
            "node":              checkpoint_node,
            "candidate":         candidate_display,
            "summary":           summary,
            "options":           ["写入", "跳过", "退出"],
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


def _run_simple(cmd: list, candidate: str):
    """
    简单运行脚本，等待完成后输出 JSON。
    用于无 checkpoint 的脚本（test-email、contract）。
    """
    try:
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

    if result.returncode != 0:
        emit_error(f"脚本执行失败（exit={result.returncode}）", raw)
        return

    # 尝试提取关键信息
    summary = extract_summary(raw)
    candidate_display = extract_candidate_from_output(raw, candidate)

    # 生成成功消息
    if "test" in str(cmd) or "email" in str(cmd).lower():
        msg = f"测试题邮件已发送给 {candidate_display}"
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
  test-email  python3 scripts/run_dialog.py test-email --name "青木遥" --file ~/test.pdf
  contract    python3 scripts/run_dialog.py contract --name "宋赛楠"
  resume      python3 scripts/run_dialog.py resume --token ckpt-xxx --decision "写入"
        """,
    )

    sub = parser.add_subparsers(dest="command", title="子命令")
    sub.required = True

    # score
    p_score = sub.add_parser("score", help="评分写回（rescore_and_write_v2.py）")
    p_score.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_score.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # test-email
    p_email = sub.add_parser("test-email", help="发测试题邮件")
    p_email.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_email.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")
    p_email.add_argument("--file",      required=True, help="测试题 PDF 路径")

    # contract
    p_contract = sub.add_parser("contract", help="生成合同")
    p_contract.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_contract.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # resume
    p_resume = sub.add_parser("resume", help="从 dialog checkpoint 恢复执行")
    p_resume.add_argument("--token",    required=True, help="checkpoint token（格式：ckpt-xxx）")
    p_resume.add_argument("--decision", required=True, help="决策内容（如 '写入' 或 '跳过'）")

    return parser


COMMAND_MAP = {
    "score":      cmd_score,
    "test-email": cmd_test_email,
    "contract":   cmd_contract,
    "resume":     cmd_resume,
}


def main():
    parser = build_parser()
    args   = parser.parse_args()

    handler = COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
