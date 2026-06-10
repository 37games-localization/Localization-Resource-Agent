#!/usr/bin/env python3
"""
send_test_email_v2.py
=====================
send_test_email.py 的 v2 版本：接入 WorkflowEngine，实现行动可视化 + Human Decision 节点。

用法（与原版完全兼容）：
    python3 scripts/send_test_email_v2.py --list
    python3 scripts/send_test_email_v2.py --name "青木遥" --file ~/Downloads/test.pdf
    python3 scripts/send_test_email_v2.py --name "青木遥" --file test.pdf --dry-run
    python3 scripts/send_test_email_v2.py --name "青木遥" --file test.pdf --yes
"""

import sys, re, json, argparse, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_smtp, get_lark, is_test_mode, get_test_email
from workflow_engine import WorkflowEngine, StepStatus

# 复用原版所有工具函数，不重复实现
from send_test_email import (
    BASE_TOKEN, TABLE_ID, TEST_MODE, TEST_EMAIL,
    FLD_NAME, FLD_EMAIL, FLD_LANG_PAIR, FLD_STATUS, FLD_TEST_SENT_AT,
    VALID_EXTS,
    lark_cli, extract_text, fetch_records, update_record,
    summarize_attachment, build_email, send_email, list_records,
)

_CFG = load_config()


def main():
    parser = argparse.ArgumentParser(description="测试题邮件发送 v2（工作流可视化版）")
    parser.add_argument("--name",      help="资源商姓名（模糊匹配）")
    parser.add_argument("--record-id", help="飞书 record_id（精确）")
    parser.add_argument("--file",      metavar="PATH", help="测试题附件路径")
    parser.add_argument("--list",      action="store_true")
    parser.add_argument("--dry-run",   action="store_true", help="预览但不发送")
    parser.add_argument("--yes",       action="store_true", help="跳过确认直接发送")
    parser.add_argument("--draft",     action="store_true", help="保存草稿而非直接发送")
    parser.add_argument("--no-lark-log", action="store_true", help="不写飞书流程日志")
    args = parser.parse_args()

    # ── --list 走原版逻辑 ─────────────────────────────────────────────────────
    if args.list:
        records = fetch_records()
        list_records(records)
        return

    if not args.name and not args.record_id:
        parser.print_help(); sys.exit(0)

    if not args.file:
        print("❌ 请用 --file 指定测试题附件路径"); sys.exit(1)

    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        print(f"❌ 文件不存在：{file_path}"); sys.exit(1)
    if file_path.suffix.lower() not in VALID_EXTS:
        print(f"❌ 不支持的格式：{file_path.suffix}（支持：{' / '.join(VALID_EXTS)}）"); sys.exit(1)

    # ── 拉取飞书记录 ──────────────────────────────────────────────────────────
    records = fetch_records()

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
            list_records(matches); sys.exit(1)
        target = matches[0]

    if not target:
        print("❌ 未找到记录"); sys.exit(1)

    f         = target["fields"]
    name      = extract_text(f.get(FLD_NAME)) or "未知"
    email     = extract_text(f.get(FLD_EMAIL))
    lang_pair = extract_text(f.get(FLD_LANG_PAIR))
    lang      = "zh" if re.search(r'[\u4e00-\u9fff]', name) else "en"

    # ── 初始化 WorkflowEngine ─────────────────────────────────────────────────
    wf = WorkflowEngine(
        candidate_name=name,
        write_lark=not args.no_lark_log,
    )
    wf.run_id = f"test-email-{target['record_id'][:8]}-{int(time.time())}"

    # ── Step 1: 读取候选人信息 ────────────────────────────────────────────────
    wf.trace(
        "读取候选人信息",
        input_summary=f"record: {target['record_id']}",
        output_summary=f"姓名: {name}  邮箱: {email}  语言对: {lang_pair}",
    )

    # ── Step 2: 校验附件 ──────────────────────────────────────────────────────
    with wf.step("校验测试题附件", input_summary=str(file_path)) as s:
        size_kb = file_path.stat().st_size // 1024
        s.finish(output=f"{file_path.name}  {size_kb} KB  格式: {file_path.suffix}")

    # ── Step 3: 分析附件内容 ──────────────────────────────────────────────────
    with wf.step("分析附件内容", input_summary=file_path.name) as s:
        summary = summarize_attachment(file_path)
        if summary.startswith("__VISION__"):
            s.finish(output="PDF/图片附件，需视觉模型分析", status=StepStatus.DONE)
            attachment_summary = f"【附件路径】{summary.replace('__VISION__', '')}"
        else:
            lines = summary.splitlines()
            s.finish(output=lines[0] if lines else "分析完成")
            attachment_summary = summary

    # ── Step 4: 构建邮件 ──────────────────────────────────────────────────────
    with wf.step("构建邮件内容", input_summary=f"语言: {'中文' if lang == 'zh' else '英文'}") as s:
        subject, body = build_email(name, lang_pair, lang, file_path.name)
        actual_to = TEST_EMAIL if TEST_MODE else email
        s.finish(output=f"主题: {subject[:40]}…  收件人: {actual_to}")

    # ── Step 5: Human Decision 节点 ───────────────────────────────────────────
    if not args.yes:
        # 先打印附件摘要和邮件预览
        print("\n" + "=" * 62)
        print("📎 附件内容摘要")
        print("=" * 62)
        print(attachment_summary)
        print()
        print("=" * 62)
        print("📧 邮件预览")
        print("=" * 62)
        print(f"收件人：{actual_to}")
        print(f"附  件：{file_path.name}  ({size_kb} KB)")
        print(f"主  题：{subject}")
        print("-" * 62)
        print(body)
        print("=" * 62)
        if TEST_MODE:
            print(f"\n⚠️  [测试模式] 实际发到：{TEST_EMAIL}（而非 {email}）")

        if args.dry_run:
            wf.trace("跳过发送", output_summary="[DRY-RUN] 不发送", status=StepStatus.SKIPPED)
            wf.summary()
            return

        decision = wf.checkpoint(
            node="确认发送测试题邮件",
            context={
                "候选人":   name,
                "收件人":   actual_to,
                "附件":     f"{file_path.name} ({size_kb} KB)",
                "主题":     subject,
                "测试模式": "是" if TEST_MODE else "否",
            },
            prompt="确认发送以上邮件（含附件）？",
            options=["发送", "保存草稿", "取消"],
        )

        if decision == "取消":
            print("已取消"); sys.exit(0)
        if decision == "保存草稿":
            args.draft = True
    else:
        if args.dry_run:
            wf.trace("跳过发送", output_summary="[DRY-RUN] 不发送", status=StepStatus.SKIPPED)
            wf.summary()
            return

    # ── Step 6: 发送邮件 ──────────────────────────────────────────────────────
    with wf.step("发送邮件", input_summary=f"→ {actual_to}  附件: {file_path.name}") as s:
        send_email(email, subject, body, file_path, draft=args.draft)
        s.finish(output="草稿已保存" if args.draft else f"✅ 发送成功 → {actual_to}")

    # ── Step 7: 更新飞书状态 ──────────────────────────────────────────────────
    with wf.step("更新飞书招募状态", input_summary=f"record: {target['record_id']}") as s:
        update_record(target["record_id"], {
            FLD_STATUS:       "📤 测试中",
            FLD_TEST_SENT_AT: int(time.time() * 1000),
        })
        s.finish(output="招募状态 → 📤 测试中，测试发送时间已记录")

    wf.summary()


if __name__ == "__main__":
    main()
