#!/usr/bin/env python3
"""
workflow_runner.py
==================
资源管理 Agent 统一入口脚本 v2

根据飞书招募状态，自动判断并调用对应 v2 脚本。

子命令：
  status      查看候选人当前状态
  next        自动判断下一步并执行
  score       手动触发评分写回
  test-email  手动发测试题邮件（需要 --file）
  contract    手动生成合同
  resume      从 dialog checkpoint 恢复执行
  list        列出所有候选人及当前状态

用法示例：
    python3 scripts/workflow_runner.py status --name "青木遥"
    python3 scripts/workflow_runner.py next --name "青木遥"
    python3 scripts/workflow_runner.py next --name "青木遥" --file ~/Downloads/test.pdf
    python3 scripts/workflow_runner.py score --name "青木遥"
    python3 scripts/workflow_runner.py test-email --name "青木遥" --file ~/test.pdf
    python3 scripts/workflow_runner.py contract --name "青木遥"
    python3 scripts/workflow_runner.py resume --token ckpt-xxx --decision "写入"
    python3 scripts/workflow_runner.py list
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path

# ── 路径设置 ─────────────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).parent
SKILL_DIR   = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))

# ── 从各脚本复用字段常量与工具函数 ─────────────────────────────────────────────
from send_test_email import (
    FLD_NAME, FLD_EMAIL, FLD_LANG_PAIR, FLD_STATUS,
    lark_cli, extract_text, BASE_TOKEN, TABLE_ID,
)
from rescore_and_write import fetch_all_records

# ── 招募状态常量 ──────────────────────────────────────────────────────────────
STATUS_LABELS = [
    "📋 简历待筛选",
    "🔍 初筛中",
    "✅ 初筛通过",
    "❌ 已拒绝",
    "📝 测试题待发",
    "📤 测试中",
    "✅ 测试通过",
    "❌ 测试未通过",
    "📧 合同信息收集中",
    "📄 合同待生成",
    "📮 合同已发送",
    "🔏 等待签署",
    "✅ 合同已签署",
    "💰 财务待登记",
    "🔍 财务审批中",
    "✅ 已入库",
]

# 状态 → 建议下一步说明
NEXT_STEP_HINTS = {
    "📋 简历待筛选":   "➡  建议：运行评分写回（score 子命令）",
    "🔍 初筛中":       "➡  建议：运行评分写回（score 子命令）",
    "✅ 初筛通过":     "➡  建议：运行评分写回（score 子命令），或发测试题（test-email 子命令）",
    "❌ 已拒绝":       "⚠️  已拒绝，无需操作",
    "📝 测试题待发":   "➡  建议：发测试题（next --file <pdf> 或 test-email --file <pdf>）",
    "📤 测试中":       "⏳  等待候选人提交测试，需人工确认测试结果",
    "✅ 测试通过":     "➡  建议：进入合同信息收集，或直接生成合同（contract 子命令）",
    "❌ 测试未通过":   "⚠️  测试未通过，可发婉拒邮件（send_rejection_email.py）",
    "📧 合同信息收集中": "⏳  等待候选人提供合同信息，需人工核实",
    "📄 合同待生成":   "➡  建议：生成合同（contract 子命令）",
    "📮 合同已发送":   "⏳  等待候选人签署，需人工跟进",
    "🔏 等待签署":     "⏳  等待签署中，可用 check_signed_contract.py 核查",
    "✅ 合同已签署":   "➡  建议：推进财务登记（人工操作飞书）",
    "💰 财务待登记":   "⏳  等待财务登记，需人工操作",
    "🔍 财务审批中":   "⏳  财务审批中，等待结果",
    "✅ 已入库":       "🎉  已完成入库，全流程结束",
}

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def find_candidate(name: str = None, record_id: str = None):
    """在飞书表里查找候选人，返回 record dict 或 None"""
    records = fetch_all_records()
    if record_id:
        for r in records:
            if r["record_id"] == record_id:
                return r
        return None
    if name:
        matches = [
            r for r in records
            if name.lower() in extract_text(r["fields"].get(FLD_NAME, "")).lower()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            print(f"⚠️  找到多条记录，请使用 --record-id 精确指定：")
            for r in matches:
                n = extract_text(r["fields"].get(FLD_NAME, ""))
                s = extract_text(r["fields"].get(FLD_STATUS, ""))
                print(f"   {r['record_id']}  {n}  {s}")
            return None
        return None
    return None


def get_status_text(record: dict) -> str:
    """提取招募状态文本"""
    raw = record["fields"].get(FLD_STATUS, "")
    return extract_text(raw) or "（未知）"


def run_script(script_name: str, extra_args: list = None):
    """subprocess 调用 scripts/ 目录下的脚本，保证进程隔离"""
    script_path = SCRIPTS_DIR / script_name
    cmd = [sys.executable, str(script_path)] + (extra_args or [])
    print(f"\n🚀 执行：{' '.join(cmd)}\n{'─' * 60}")
    result = subprocess.run(cmd, cwd=str(SKILL_DIR))
    return result.returncode


# ── 子命令实现 ────────────────────────────────────────────────────────────────

def cmd_status(args):
    """查看候选人当前招募状态"""
    if not args.name and not args.record_id:
        print("❌ 请提供 --name 或 --record-id")
        return 1

    rec = find_candidate(name=args.name, record_id=args.record_id)
    if rec is None:
        print(f"❌ 未找到候选人：{args.name or args.record_id}")
        return 1

    f = rec["fields"]
    name      = extract_text(f.get(FLD_NAME, "")) or "未知"
    email     = extract_text(f.get(FLD_EMAIL, "")) or "—"
    lang_pair = extract_text(f.get(FLD_LANG_PAIR, "")) or "—"
    status    = get_status_text(rec)
    hint      = NEXT_STEP_HINTS.get(status, "❓ 未知状态，请人工确认")

    print(f"\n{'=' * 50}")
    print(f"  候选人：{name}")
    print(f"  邮箱  ：{email}")
    print(f"  语言对：{lang_pair}")
    print(f"  Record：{rec['record_id']}")
    print(f"  状态  ：{status}")
    print(f"  {hint}")
    print(f"{'=' * 50}\n")
    return 0


def cmd_next(args):
    """根据招募状态自动选择并执行下一步"""
    if not args.name and not args.record_id:
        print("❌ 请提供 --name 或 --record-id")
        return 1

    rec = find_candidate(name=args.name, record_id=args.record_id)
    if rec is None:
        print(f"❌ 未找到候选人：{args.name or args.record_id}")
        return 1

    record_id = rec["record_id"]
    status    = get_status_text(rec)
    name      = extract_text(rec["fields"].get(FLD_NAME, "")) or record_id

    print(f"\n候选人：{name}  |  当前状态：{status}")

    # ── 根据状态决定调用哪个脚本 ────────────────────────────────────────────
    if status in ("📋 简历待筛选", "🔍 初筛中", "✅ 初筛通过"):
        return run_script("rescore_and_write_v2.py", [
            "--record-id", record_id,
            "--interactive",
        ])

    elif status == "📝 测试题待发":
        if not args.file:
            print("⚠️  发测试题需要 --file 参数（测试题 PDF 路径）")
            print("   示例：python3 scripts/workflow_runner.py next"
                  f" --name \"{name}\" --file ~/Downloads/test.pdf")
            return 1
        return run_script("send_test_email_v2.py", [
            "--record-id", record_id,
            "--file", str(args.file),
        ])

    elif status in ("✅ 测试通过", "📄 合同待生成"):
        return run_script("generate_contract_v2.py", [
            "--record-id", record_id,
        ])

    else:
        hint = NEXT_STEP_HINTS.get(status, "❓ 未知状态，请人工确认")
        print(f"\n⚠️  当前状态「{status}」需要人工操作：")
        print(f"   {hint}\n")
        return 0


def cmd_score(args):
    """手动触发评分写回"""
    if not args.name and not args.record_id:
        print("❌ 请提供 --name 或 --record-id")
        return 1

    extra = []
    if args.record_id:
        extra += ["--record-id", args.record_id]
    elif args.name:
        extra += ["--name", args.name]
    extra.append("--interactive")

    return run_script("rescore_and_write_v2.py", extra)


def cmd_test_email(args):
    """手动发测试题邮件"""
    if not args.name and not args.record_id:
        print("❌ 请提供 --name 或 --record-id")
        return 1
    if not args.file:
        print("❌ 请提供 --file（测试题 PDF 路径）")
        return 1

    extra = []
    if args.record_id:
        extra += ["--record-id", args.record_id]
    elif args.name:
        extra += ["--name", args.name]
    extra += ["--file", str(args.file)]

    return run_script("send_test_email_v2.py", extra)


def cmd_contract(args):
    """手动生成合同"""
    if not args.name and not args.record_id:
        print("❌ 请提供 --name 或 --record-id")
        return 1

    extra = []
    if args.record_id:
        extra += ["--record-id", args.record_id]
    elif args.name:
        extra += ["--name", args.name]

    return run_script("generate_contract_v2.py", extra)


def cmd_resume(args):
    """从 dialog checkpoint 恢复执行"""
    if not args.token:
        print("❌ 请提供 --token（checkpoint token，格式：ckpt-xxx）")
        return 1
    if not args.decision:
        print("❌ 请提供 --decision（决策内容，如 '写入' 或 '跳过'）")
        return 1

    # 导入 WorkflowEngine 并调用 resume
    from workflow_engine import WorkflowEngine
    engine = WorkflowEngine.__new__(WorkflowEngine)  # 不触发 __init__
    ok = engine.resume(args.token, args.decision)
    if ok:
        print(f"✅ checkpoint {args.token} 已恢复，决策：{args.decision}")
    else:
        print(f"❌ 恢复失败，token 不存在或已处理：{args.token}")
    return 0 if ok else 1


def cmd_list(args):
    """列出所有候选人及当前状态"""
    records = fetch_all_records()
    if not records:
        print("⚠️  飞书表中无记录")
        return 0

    # 表头
    header = f"{'#':<4} {'record_id':<24} {'姓名':<18} {'招募状态':<20} {'邮箱'}"
    print(f"\n{header}")
    print("─" * 90)

    for i, r in enumerate(records, 1):
        f         = r["fields"]
        name      = extract_text(f.get(FLD_NAME, "")) or "—"
        status    = extract_text(f.get(FLD_STATUS, "")) or "—"
        email     = extract_text(f.get(FLD_EMAIL, "")) or "—"
        record_id = r["record_id"]
        print(f"{i:<4} {record_id:<24} {name:<18} {status:<20} {email}")

    print(f"\n共 {len(records)} 条记录\n")
    return 0


# ── 参数解析 ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workflow_runner.py",
        description="资源管理 Agent 统一入口（v2）— 根据飞书招募状态驱动工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令示例：
  status      python3 scripts/workflow_runner.py status --name "青木遥"
  next        python3 scripts/workflow_runner.py next --name "青木遥"
  next+file   python3 scripts/workflow_runner.py next --name "青木遥" --file ~/test.pdf
  score       python3 scripts/workflow_runner.py score --name "青木遥"
  test-email  python3 scripts/workflow_runner.py test-email --name "青木遥" --file ~/test.pdf
  contract    python3 scripts/workflow_runner.py contract --name "青木遥"
  resume      python3 scripts/workflow_runner.py resume --token ckpt-xxx --decision "写入"
  list        python3 scripts/workflow_runner.py list

招募状态链（16 节点）：
  📋 简历待筛选 → 🔍 初筛中 → ✅ 初筛通过 / ❌ 已拒绝
  → 📝 测试题待发 → 📤 测试中 → ✅ 测试通过 / ❌ 测试未通过
  → 📧 合同信息收集中 → 📄 合同待生成 → 📮 合同已发送
  → 🔏 等待签署 → ✅ 合同已签署
  → 💰 财务待登记 → 🔍 财务审批中 → ✅ 已入库 / ❌ 已拒绝
        """,
    )

    sub = parser.add_subparsers(dest="command", title="子命令")
    sub.required = True

    # ── status ───────────────────────────────────────────────────────────────
    p_status = sub.add_parser("status", help="查看候选人当前招募状态")
    p_status.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_status.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # ── next ─────────────────────────────────────────────────────────────────
    p_next = sub.add_parser("next", help="自动判断下一步并执行")
    p_next.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_next.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")
    p_next.add_argument("--file",      type=Path, help="附件路径（发测试题时必填）")

    # ── score ────────────────────────────────────────────────────────────────
    p_score = sub.add_parser("score", help="手动触发评分写回（rescore_and_write_v2.py）")
    p_score.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_score.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # ── test-email ───────────────────────────────────────────────────────────
    p_email = sub.add_parser("test-email", help="手动发测试题邮件（send_test_email_v2.py）")
    p_email.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_email.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")
    p_email.add_argument("--file",      type=Path, required=True, help="测试题 PDF 路径（必填）")

    # ── contract ─────────────────────────────────────────────────────────────
    p_contract = sub.add_parser("contract", help="手动生成合同（generate_contract_v2.py）")
    p_contract.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_contract.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

    # ── resume ───────────────────────────────────────────────────────────────
    p_resume = sub.add_parser("resume", help="从 dialog checkpoint 恢复执行")
    p_resume.add_argument("--token",    required=True, help="checkpoint token（格式：ckpt-xxx）")
    p_resume.add_argument("--decision", required=True, help="决策内容（如 '写入' 或 '跳过'）")

    # ── list ─────────────────────────────────────────────────────────────────
    sub.add_parser("list", help="列出所有候选人及当前招募状态")

    return parser


# ── 入口 ─────────────────────────────────────────────────────────────────────

COMMAND_MAP = {
    "status":     cmd_status,
    "next":       cmd_next,
    "score":      cmd_score,
    "test-email": cmd_test_email,
    "contract":   cmd_contract,
    "resume":     cmd_resume,
    "list":       cmd_list,
}


def main():
    parser = build_parser()
    args   = parser.parse_args()

    handler = COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    rc = handler(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
