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
  contract-info-email  发送签约信息收集邮件
  contract    手动生成合同
  resume      从 dialog checkpoint 恢复执行
  list        列出所有候选人及当前状态

用法示例：
    python3 scripts/workflow_runner.py status --name "测试候选人A"
    python3 scripts/workflow_runner.py next --name "测试候选人A"
    python3 scripts/workflow_runner.py next --name "测试候选人A" --file ~/Downloads/test.pdf
    python3 scripts/workflow_runner.py score --name "测试候选人A"
    python3 scripts/workflow_runner.py test-email --name "测试候选人A" --file ~/test.pdf
    python3 scripts/workflow_runner.py contract-info-email --name "测试候选人A"
    python3 scripts/workflow_runner.py contract --name "测试候选人A"
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
from config_loader import get_table_ref, load_config, get_lark
from schema_gate import assert_schema_ready
try:
    from field_resolver import load_field_mapping, get_table_mapping
except Exception:
    load_field_mapping = None
    get_table_mapping = None

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
    "✅ 测试通过":     "➡  建议：发送签约信息收集邮件（contract-info-email 子命令）",
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


PARSED_FIELD_CANDIDATES = {
    "word_count": ("解析字数", "candidate.parsed_word_count"),
    "years": ("解析年限", "candidate.parsed_years"),
    "project_count": ("解析项目数", "candidate.parsed_project_count"),
    "parsed_at": ("简历解析时间", "candidate.resume_parsed_at"),
}


def _candidate_field(fields: dict, *keys: str):
    for key in keys:
        if not key:
            continue
        if key in fields:
            return fields.get(key)
        if "." in key and load_field_mapping and get_table_mapping:
            try:
                mapping = get_table_mapping("candidate", load_field_mapping())
                field = (mapping.get("fields") or {}).get(key) or {}
                for mapped_key in (field.get("field_id"), field.get("field_name"), field.get("expected_name")):
                    if mapped_key and mapped_key in fields:
                        return fields.get(mapped_key)
            except Exception:
                pass
    return None


def parsed_resume_ready(record: dict) -> bool:
    """评分前必须能在 Lark 行里看到解析事实，避免 transient PDF 影响评分可审计性。"""
    fields = record.get("fields", {})
    parsed_at = _candidate_field(fields, *PARSED_FIELD_CANDIDATES["parsed_at"])
    if parsed_at:
        return True
    word_count = _candidate_field(fields, *PARSED_FIELD_CANDIDATES["word_count"])
    years = _candidate_field(fields, *PARSED_FIELD_CANDIDATES["years"])
    project_count = _candidate_field(fields, *PARSED_FIELD_CANDIDATES["project_count"])
    return any(value not in (None, "") for value in (word_count, years, project_count))


def ensure_resume_parsed(record: dict) -> bool:
    """If parsed facts are missing, run the parser first and require it to succeed."""
    if parsed_resume_ready(record):
        return True
    record_id = record.get("record_id", "")
    name = extract_text(record.get("fields", {}).get(FLD_NAME, "")) or record_id
    print("\n📄 评分前未发现持久化简历解析字段，先执行解析并写回 Lark。")
    rc = run_script("parse_resumes.py", ["--record-id", record_id])
    if rc != 0:
        print(f"❌ {name} 的简历解析未完成，停止评分。请先修复 LLM/API/附件后重试。")
        return False
    return True


def ensure_schema_ready(operation: str) -> bool:
    try:
        assert_schema_ready(operation)
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False


def _extract_lark_records(payload):
    """兼容 lark-cli record-list 的不同 JSON 包装格式"""
    data = payload.get("data", payload)
    for key in ("items", "records", "record_list"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    if isinstance(payload.get("items"), list):
        return payload["items"]
    return []


WORKFLOW_FIELD_FALLBACKS = {
    "workflow.run_id": "run_id",
    "workflow.candidate_record_id": "candidate_record_id",
    "workflow.candidate_name": "candidate_name",
    "workflow.step_name": "step_name",
    "workflow.status": "status",
    "workflow.input_summary": "input_summary",
    "workflow.output_summary": "output_summary",
    "workflow.created_at": "created_at",
}


def _workflow_log_mapping() -> dict:
    if not load_field_mapping or not get_table_mapping:
        return {}
    try:
        return get_table_mapping("workflow_log", load_field_mapping())
    except Exception:
        return {}


def _workflow_field_ref(logical_key: str, mapping: dict) -> str:
    field = (mapping.get("fields") or {}).get(logical_key) or {}
    return field.get("field_id") or field.get("field_name") or WORKFLOW_FIELD_FALLBACKS[logical_key]


def _workflow_field_value(fields: dict, logical_key: str, mapping: dict):
    field = (mapping.get("fields") or {}).get(logical_key) or {}
    candidates = [
        field.get("field_id"),
        field.get("field_name"),
        field.get("expected_name"),
        WORKFLOW_FIELD_FALLBACKS[logical_key],
    ]
    for key in candidates:
        if key and key in fields:
            return fields.get(key)
    return ""


def _checkpoint_token_from_fields(fields: dict, mapping: dict) -> str:
    output_summary = _workflow_field_value(fields, "workflow.output_summary", mapping)
    if isinstance(output_summary, str) and output_summary:
        try:
            payload = json.loads(output_summary)
            token = payload.get("checkpoint_token", "")
            if token:
                return token
        except Exception:
            pass

    legacy_run_id = _workflow_field_value(fields, "workflow.run_id", mapping)
    if isinstance(legacy_run_id, str) and legacy_run_id.startswith("ckpt-"):
        return legacy_run_id
    return ""


def fetch_waiting_checkpoints(limit: int = 50) -> list[dict]:
    """从流程日志表读取 status=waiting 的 checkpoint 行"""
    cfg = load_config()
    base_token, log_table_id = get_table_ref(cfg, "workflow_log")
    if not base_token:
        raise RuntimeError("lark.base_token 未配置")

    mapping = _workflow_log_mapping()
    status_field = _workflow_field_ref("workflow.status", mapping)
    filter_json = json.dumps({
        "logic": "and",
        "conditions": [[status_field, "==", "waiting"]],
    }, ensure_ascii=False)
    field_refs = [
        _workflow_field_ref("workflow.run_id", mapping),
        _workflow_field_ref("workflow.candidate_record_id", mapping),
        _workflow_field_ref("workflow.step_name", mapping),
        _workflow_field_ref("workflow.status", mapping),
        _workflow_field_ref("workflow.candidate_name", mapping),
        _workflow_field_ref("workflow.input_summary", mapping),
        _workflow_field_ref("workflow.output_summary", mapping),
        _workflow_field_ref("workflow.created_at", mapping),
    ]
    cmd = [
        "lark-cli", "base", "+record-list",
        "--base-token", base_token,
        "--table-id", log_table_id,
    ]
    for ref in dict.fromkeys(field_refs):
        cmd += ["--field-id", ref]
    cmd += [
        "--filter-json", filter_json,
        "--limit", str(limit),
        "--format", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())

    payload = json.loads(result.stdout or "{}")
    rows = []
    for item in _extract_lark_records(payload):
        fields = item.get("fields", item)
        token = _checkpoint_token_from_fields(fields, mapping)
        rows.append({
            "record_id": item.get("record_id", item.get("id", "")),
            "token": token,
            "run_id": _workflow_field_value(fields, "workflow.run_id", mapping),
            "candidate_record_id": _workflow_field_value(fields, "workflow.candidate_record_id", mapping),
            "step_name": _workflow_field_value(fields, "workflow.step_name", mapping),
            "status": _workflow_field_value(fields, "workflow.status", mapping),
            "candidate_name": _workflow_field_value(fields, "workflow.candidate_name", mapping),
            "input_summary": _workflow_field_value(fields, "workflow.input_summary", mapping),
            "created_at": _workflow_field_value(fields, "workflow.created_at", mapping),
        })
    return rows


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
        if not ensure_schema_ready("score"):
            return 1
        if not ensure_resume_parsed(rec):
            return 1
        return run_script("rescore_and_write_v2.py", [
            "--record-id", record_id,
            "--interactive",
        ])

    elif status == "📝 测试题待发":
        if not ensure_schema_ready("test-email"):
            return 1
        if not args.file:
            print("⚠️  发测试题需要 --file 参数（测试题 PDF 路径）")
            print("   示例：python3 scripts/workflow_runner.py next"
                  f" --name \"{name}\" --file ~/Downloads/test.pdf")
            return 1
        return run_script("send_test_email_v2.py", [
            "--record-id", record_id,
            "--file", str(args.file),
        ])

    elif status == "✅ 测试通过":
        if not ensure_schema_ready("contract-info-email"):
            return 1
        return run_script("send_contract_info_email_v2.py", [
            "--record-id", record_id,
        ])

    elif status == "📄 合同待生成":
        if not ensure_schema_ready("contract"):
            return 1
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
    if not ensure_schema_ready("score"):
        return 1

    rec = find_candidate(name=args.name, record_id=args.record_id)
    if rec is None:
        print(f"❌ 未找到候选人：{args.name or args.record_id}")
        return 1
    if not ensure_resume_parsed(rec):
        return 1

    extra = []
    if rec.get("record_id"):
        extra += ["--record-id", rec["record_id"]]
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
    if not ensure_schema_ready("test-email"):
        return 1

    extra = []
    if args.record_id:
        extra += ["--record-id", args.record_id]
    elif args.name:
        extra += ["--name", args.name]
    extra += ["--file", str(args.file)]

    return run_script("send_test_email_v2.py", extra)


def cmd_contract_info_email(args):
    """手动发送签约信息收集邮件"""
    if not args.name and not args.record_id:
        print("❌ 请提供 --name 或 --record-id")
        return 1
    if not ensure_schema_ready("contract-info-email"):
        return 1

    extra = []
    if args.record_id:
        extra += ["--record-id", args.record_id]
    elif args.name:
        extra += ["--name", args.name]

    return run_script("send_contract_info_email_v2.py", extra)


def cmd_contract(args):
    """手动生成合同"""
    if not args.name and not args.record_id:
        print("❌ 请提供 --name 或 --record-id")
        return 1
    if not ensure_schema_ready("contract"):
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
    if not ensure_schema_ready("resume"):
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


def cmd_waiting(args):
    """列出等待人工决策的 checkpoint"""
    if not ensure_schema_ready("waiting"):
        return 1
    try:
        rows = fetch_waiting_checkpoints(limit=args.limit)
    except Exception as e:
        print(f"❌ 读取待决策列表失败：{e}")
        return 1

    if not rows:
        print("\n当前没有等待人工决策的候选人。\n")
        return 0

    header = f"{'#':<4} {'token':<42} {'候选人':<16} {'节点':<20} {'状态'}"
    print(f"\n{header}")
    print("─" * 100)
    for i, row in enumerate(rows, 1):
        print(
            f"{i:<4} {str(row['token'] or '—'):<42} "
            f"{str(row['candidate_name'] or '—'):<16} "
            f"{str(row['step_name'] or '—'):<20} "
            f"{row['status'] or 'waiting'}"
        )
    print(f"\n共 {len(rows)} 条待决策记录。继续处理时使用：")
    print('python3 scripts/workflow_runner.py resume --token <token> --decision "写入"\n')
    return 0


# ── 参数解析 ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workflow_runner.py",
        description="资源管理 Agent 统一入口（v2）— 根据飞书招募状态驱动工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
子命令示例：
  status      python3 scripts/workflow_runner.py status --name "测试候选人A"
  next        python3 scripts/workflow_runner.py next --name "测试候选人A"
  next+file   python3 scripts/workflow_runner.py next --name "测试候选人A" --file ~/test.pdf
  score       python3 scripts/workflow_runner.py score --name "测试候选人A"
  test-email  python3 scripts/workflow_runner.py test-email --name "测试候选人A" --file ~/test.pdf
  contract-info-email  python3 scripts/workflow_runner.py contract-info-email --name "测试候选人A"
  contract    python3 scripts/workflow_runner.py contract --name "测试候选人A"
  resume      python3 scripts/workflow_runner.py resume --token ckpt-xxx --decision "写入"
  list        python3 scripts/workflow_runner.py list
  waiting     python3 scripts/workflow_runner.py waiting

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

    # ── contract-info-email ─────────────────────────────────────────────────
    p_contract_info = sub.add_parser("contract-info-email", help="发送签约信息收集邮件（send_contract_info_email_v2.py）")
    p_contract_info.add_argument("--name",      help="候选人姓名（模糊匹配）")
    p_contract_info.add_argument("--record-id", dest="record_id", help="飞书 record_id（精确）")

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

    # ── waiting ──────────────────────────────────────────────────────────────
    p_waiting = sub.add_parser("waiting", help="列出等待人工决策的 checkpoint")
    p_waiting.add_argument("--limit", type=int, default=50, help="最多读取多少条")

    return parser


# ── 入口 ─────────────────────────────────────────────────────────────────────

COMMAND_MAP = {
    "status":     cmd_status,
    "next":       cmd_next,
    "score":      cmd_score,
    "test-email": cmd_test_email,
    "contract-info-email": cmd_contract_info_email,
    "contract":   cmd_contract,
    "resume":     cmd_resume,
    "list":       cmd_list,
    "waiting":    cmd_waiting,
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
