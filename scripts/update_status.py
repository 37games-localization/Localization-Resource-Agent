#!/usr/bin/env python3
"""
update_status.py
================
手动更新候选人招募状态的小工具。
用于财务流程、状态推进等 VM 主动触发的节点。

用法：
    # 查看所有状态选项
    python3 scripts/update_status.py --list-statuses

    # 查看所有候选人
    python3 scripts/update_status.py --list

    # 更新状态（交互确认）
    python3 scripts/update_status.py --name "青木遥" --status "🔍 财务审批中"
    python3 scripts/update_status.py --name "青木遥" --status "✅ 已入库"
    python3 scripts/update_status.py --record-id recXXX --status "💰 财务待登记"

    # 跳过确认
    python3 scripts/update_status.py --name "青木遥" --status "✅ 已入库" --yes

    # 只预览，不写回
    python3 scripts/update_status.py --name "青木遥" --status "✅ 已入库" --dry-run
"""

import sys, json, argparse, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_smtp, get_lark, get_paths, is_test_mode, get_test_email
from field_resolver import field_id_or
from lark_cli_utils import run_lark_cli_json
from manual_trace import log_manual_step

_CFG = load_config()

BASE_TOKEN = get_lark(_CFG).get("base_token", "")
TABLE_ID   = get_lark(_CFG).get("resume_table_id", "")

FLD_NAME   = field_id_or("candidate", "candidate.name", "fldSAfsOJf")
FLD_EMAIL  = field_id_or("candidate", "candidate.email", "fldWf5X8NR")
FLD_STATUS = field_id_or("candidate", "candidate.status", "fldfp6Pn7l")

# 完整状态列表（顺序即流程顺序）
ALL_STATUSES = [
    "📋 简历待筛选",
    "🔍 初筛中",
    "✅ 初筛通过",
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
    "❌ 已拒绝",
]

def lark_cli(*args):
    resp = run_lark_cli_json(*args)
    if not isinstance(resp, dict):
        raise RuntimeError(f"非 JSON 返回:\n{str(resp)[:200]}")
    return resp

def extract_text(val):
    if not val: return ""
    if isinstance(val, list):
        parts = []
        for v in val:
            parts.append(v.get("name") or v.get("text") or "" if isinstance(v, dict) else str(v))
        text = " ".join(p for p in parts if p).strip()
    else:
        text = str(val).strip()
    import re
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    return text

def fetch_records():
    records, page_token = [], None
    while True:
        args = ["base", "+record-list", "--base-token", BASE_TOKEN,
                "--table-id", TABLE_ID, "--format", "json", "--limit", "100"]
        if page_token:
            args += ["--page-token", page_token]
        resp = lark_cli(*args)
        db = resp["data"]
        fids = db.get("field_id_list", db.get("fields", []))
        for rid, row in zip(db.get("record_id_list", []), db.get("data", [])):
            records.append({"record_id": rid, "fields": dict(zip(fids, row))})
        if not db.get("has_more") or not db.get("page_token"):
            break
        page_token = db["page_token"]
    return records

def update_record(record_id, fields):
    resp = lark_cli("base", "+record-upsert", "--base-token", BASE_TOKEN,
                    "--table-id", TABLE_ID, "--record-id", record_id,
                    "--json", json.dumps(fields, ensure_ascii=False))
    if not resp.get("ok"):
        raise RuntimeError(f"写回失败: {resp.get('error')}")

def main():
    parser = argparse.ArgumentParser(description="招募状态手动更新工具")
    parser.add_argument("--name",           help="资源商姓名（模糊匹配）")
    parser.add_argument("--record-id",      help="飞书 record_id（精确）")
    parser.add_argument("--status",         help="目标状态（见 --list-statuses）")
    parser.add_argument("--list",           action="store_true", help="列出所有候选人")
    parser.add_argument("--list-statuses",  action="store_true", help="列出所有可用状态")
    parser.add_argument("--dry-run",        action="store_true", help="只预览不写回")
    parser.add_argument("--yes",            action="store_true", help="跳过确认")
    args = parser.parse_args()

    if args.list_statuses:
        print("可用状态（按流程顺序）：")
        for i, s in enumerate(ALL_STATUSES, 1):
            print(f"  {i:>2}. {s}")
        return

    records = fetch_records()

    if args.list:
        print(f"{'#':<4} {'record_id':<22} {'姓名':<20} {'邮箱':<30} {'招募状态'}")
        print("-" * 100)
        for i, rec in enumerate(records, 1):
            f = rec["fields"]
            print(f"{i:<4} {rec['record_id']:<22} "
                  f"{extract_text(f.get(FLD_NAME)):<20} "
                  f"{extract_text(f.get(FLD_EMAIL)):<30} "
                  f"{extract_text(f.get(FLD_STATUS))}")
        return

    if not (args.name or args.record_id):
        parser.print_help(); sys.exit(0)

    if not args.status:
        print("❌ 请用 --status 指定目标状态")
        print("   运行 --list-statuses 查看所有选项")
        sys.exit(1)

    # 模糊匹配状态（允许省略 emoji）
    target_status = args.status
    if target_status not in ALL_STATUSES:
        matches = [s for s in ALL_STATUSES if args.status.strip() in s]
        if len(matches) == 1:
            target_status = matches[0]
        elif len(matches) > 1:
            print(f"⚠️  状态「{args.status}」匹配到多个，请精确指定：")
            for m in matches:
                print(f"  {m}")
            sys.exit(1)
        else:
            print(f"❌ 未知状态「{args.status}」，运行 --list-statuses 查看所有选项")
            sys.exit(1)

    # 找候选人
    target = None
    if args.record_id:
        for r in records:
            if r["record_id"] == args.record_id:
                target = r; break
    elif args.name:
        matches = [r for r in records
                   if args.name.lower() in extract_text(r["fields"].get(FLD_NAME)).lower()]
        if not matches:
            print(f"❌ 未找到：{args.name}"); sys.exit(1)
        if len(matches) > 1:
            print(f"⚠️  找到 {len(matches)} 条，请用 --record-id 精确指定：")
            for r in matches:
                print(f"  {r['record_id']}  {extract_text(r['fields'].get(FLD_NAME))}")
            sys.exit(1)
        target = matches[0]

    if not target:
        print("❌ 未找到记录"); sys.exit(1)

    f           = target["fields"]
    name        = extract_text(f.get(FLD_NAME))
    curr_status = extract_text(f.get(FLD_STATUS))

    print(f"\n候选人：{name}  ({target['record_id']})")
    print(f"当前状态：{curr_status}")
    print(f"目标状态：{target_status}\n")

    if curr_status == target_status:
        print("ℹ️  状态相同，无需更新"); return

    if args.dry_run:
        print("[DRY-RUN] 不写回飞书")
        log_manual_step(
            step_name="状态推进 dry-run",
            status="skipped",
            candidate_name=name,
            candidate_record_id=target["record_id"],
            input_summary=f"当前状态: {curr_status}",
            output_summary=f"目标状态: {target_status}",
        )
        return

    if not args.yes:
        ans = input("确认更新？[y/N] ").strip().lower()
        if ans != "y":
            print("❌ 已取消"); sys.exit(0)

    update_record(target["record_id"], {FLD_STATUS: target_status})
    print(f"✅ 状态已更新：{curr_status} → {target_status}")
    log_manual_step(
        step_name="状态推进",
        status="done",
        candidate_name=name,
        candidate_record_id=target["record_id"],
        input_summary=f"当前状态: {curr_status}",
        output_summary=f"目标状态: {target_status}",
        decision="yes" if args.yes else "confirmed",
    )

if __name__ == "__main__":
    main()
