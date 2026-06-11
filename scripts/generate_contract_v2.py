#!/usr/bin/env python3
"""
generate_contract_v2.py
=======================
generate_contract.py 的 v2 版本：接入 WorkflowEngine，实现行动可视化 + Human Decision 节点。

用法（与原版完全兼容）：
    python3 scripts/generate_contract_v2.py --list
    python3 scripts/generate_contract_v2.py --name "测试候选人B"
    python3 scripts/generate_contract_v2.py --name "测试候选人B" --send
    python3 scripts/generate_contract_v2.py --name "测试候选人B" --dry-run
"""

import sys, re, json, argparse, tempfile, time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_smtp, get_lark, get_paths, is_test_mode, get_test_email
from workflow_engine import WorkflowEngine, StepStatus

# 复用原版所有工具函数
from generate_contract import (
    COLLECT_BASE, COLLECT_TABLE, TEMPLATE_BASE, TEMPLATE_TABLE,
    OUTPUT_DIR, TEST_MODE, TEST_EMAIL,
    FLD_NAME, FLD_EMAIL, FLD_ACCT_NAME, FLD_ID_SCAN, FLD_SIGNED,
    TEMPLATE_VARS_FLD, TEMPLATE_ATT_FLD, VM_INPUT_VARS,
    lark, lark_download_attachment,
    fetch_collect_records, fetch_template_records,
    extract_text, extract_attachments, open_docx,
    match_template, pick_template_for_candidate, is_company_contract,
    build_var_map, parse_required_vars,
    replace_para, fill_template_vars, insert_id_scan, download_id_scan_images,
    check_name_match, send_email, list_records,
)

_CFG = load_config()


def main():
    parser = argparse.ArgumentParser(description="合同生成 v2（工作流可视化版）")
    parser.add_argument("--name",      help="按姓名查找（模糊匹配）")
    parser.add_argument("--record-id", dest="record_id", help="按 record_id 精确查找")
    parser.add_argument("--list",      action="store_true", help="列出所有记录")
    parser.add_argument("--dry-run",   action="store_true", help="只打印变量，不生成文件")
    parser.add_argument("--send",      action="store_true", help="为已确认合同生成签约邮件草稿；必须配合 --contract-file")
    parser.add_argument("--contract-file", type=Path, help="已人工检查确认的合同 docx 路径，发送/草稿阶段必须显式指定")
    parser.add_argument("--draft",     action="store_true", help="保存草稿")
    parser.add_argument("--send-direct", action="store_true", help="仅 TEST_MODE 下允许直发；生产环境禁止 direct-send")
    parser.add_argument("--yes",       action="store_true", help="跳过所有交互确认")
    parser.add_argument("--no-lark-log", action="store_true", help="不写飞书流程日志")
    args = parser.parse_args()

    # ── --list 走原版逻辑 ─────────────────────────────────────────────────────
    if args.list:
        records = fetch_collect_records()
        list_records(records)
        return

    if not args.name and not args.record_id:
        parser.print_help(); sys.exit(0)

    # ── 拉取合同信息收集表 ────────────────────────────────────────────────────
    print("拉取合同信息收集表…")
    collect_records = fetch_collect_records()
    print(f"  共 {len(collect_records)} 条")

    target = None
    if args.record_id:
        for rec in collect_records:
            if rec["record_id"] == args.record_id:
                target = rec; break
        if not target:
            print(f"❌ 未找到 record_id={args.record_id}"); sys.exit(1)
    elif args.name:
        matches = [r for r in collect_records
                   if args.name.lower() in extract_text(r["fields"].get(FLD_NAME, "")).lower()]
        if not matches:
            print(f"❌ 未找到姓名包含「{args.name}」的记录"); sys.exit(1)
        if len(matches) > 1:
            print(f"⚠️  找到 {len(matches)} 条，请用 --record-id 精确指定：")
            list_records(matches); sys.exit(1)
        target = matches[0]

    fields     = target["fields"]
    name       = extract_text(fields.get(FLD_NAME, "")) or "未知"
    acct_name  = extract_text(fields.get(FLD_ACCT_NAME, ""))
    email_addr = extract_text(fields.get(FLD_EMAIL, ""))

    # ── 初始化 WorkflowEngine ─────────────────────────────────────────────────
    wf = WorkflowEngine(
        candidate_name=name,
        candidate_record_id=target["record_id"],
        write_lark=not args.no_lark_log,
    )
    wf.run_id = f"contract-{target['record_id'][:8]}-{int(time.time())}"

    if args.send and not args.contract_file:
        print("❌ --send 不再重新生成合同。请先生成并检查合同，再提供 --contract-file <已确认docx路径>。")
        sys.exit(1)
    if args.send_direct and not TEST_MODE:
        print("❌ 生产环境禁止直接发送合同邮件。请生成草稿，由 VM 在邮箱客户端人工发送。")
        sys.exit(1)

    # ── Step 1: 读取合同信息 ──────────────────────────────────────────────────
    with wf.step("读取合同信息", input_summary=f"record: {target['record_id']}") as s:
        id_scans = extract_attachments(fields.get(FLD_ID_SCAN, []))
        s.finish(
            output=(
                f"姓名: {name}  邮箱: {email_addr}  "
                f"账户名: {acct_name or '未填'}  "
                f"证件扫描件: {len(id_scans)} 张"
            )
        )

    if args.send:
        checked_contract = args.contract_file.expanduser().resolve()
        if not checked_contract.exists():
            print(f"❌ 已确认合同文件不存在：{checked_contract}")
            sys.exit(1)
        if checked_contract.suffix.lower() != ".docx":
            print(f"❌ 合同附件必须是 .docx：{checked_contract}")
            sys.exit(1)
        args.draft = True if not args.send_direct else args.draft
        lang = "zh" if re.search(r'[\u4e00-\u9fff]', name) else "en"
        with wf.step("生成签约邮件草稿", input_summary=f"已确认合同: {checked_contract.name}") as s:
            send_email(email_addr, name, checked_contract, lang=lang, draft=not args.send_direct or args.draft)
            s.finish(
                output=(
                    "草稿已保存，等待 VM 人工发送"
                    if (not args.send_direct or args.draft) else
                    "✅ TEST_MODE 直发完成"
                )
            )
        wf.trace(
            "合同邮件状态",
            input_summary=f"record: {target['record_id']}",
            output_summary=(
                "已为人工确认过的合同文件生成草稿；未更新「合同已发送」状态。"
                if (not args.send_direct or args.draft) else
                "TEST_MODE 直发完成；生产环境仍需人工发送。"
            ),
            status=StepStatus.SKIPPED if (not args.send_direct or args.draft) else StepStatus.DONE,
        )
        wf.summary()
        return

    # ── Step 2: 银行账户名校验 ────────────────────────────────────────────────
    with wf.step("银行账户名校验", input_summary=f"姓名: {name}  账户名: {acct_name}") as s:
        need_confirm, name_msg = check_name_match(name, acct_name)
        s.finish(
            output=name_msg,
            status=StepStatus.DONE if not need_confirm else StepStatus.DONE,
        )

    if need_confirm and not args.yes and not args.dry_run:
        decision = wf.checkpoint(
            node="账户名异常确认",
            context={"姓名": name, "银行账户名": acct_name, "检查结果": name_msg},
            prompt="账户名与姓名不完全一致，是否确认无误继续？",
            options=["继续", "取消"],
        )
        if decision == "取消":
            print("已取消"); sys.exit(0)

    # ── Step 3: 拉取合同模板 ──────────────────────────────────────────────────
    with wf.step("拉取合同模板表", input_summary=f"base: {TEMPLATE_BASE[:12]}…") as s:
        template_records = fetch_template_records()
        s.finish(output=f"共 {len(template_records)} 个模板")

    # ── Step 4: 选择合同模板 ──────────────────────────────────────────────────
    with wf.step("匹配合同模板", input_summary=f"候选人字段匹配") as s:
        template_rec, template_name = pick_template_for_candidate(
            template_records,
            fields,
            auto_confirm=args.yes,
        )
        if not template_rec:
            s.finish(output="❌ 未选择模板", status=StepStatus.FAILED)
            print("❌ 未选择模板，退出"); sys.exit(1)
        is_company = is_company_contract(template_name)
        s.finish(output=f"已选：{template_name}  类型: {'公司' if is_company else '个人'}")

    # ── Step 5: 解析变量 ──────────────────────────────────────────────────────
    with wf.step("解析合同变量", input_summary=f"模板: {template_name}") as s:
        vars_text      = extract_text(template_rec.get("fields", {}).get(TEMPLATE_VARS_FLD, ""))
        required_vars  = parse_required_vars(vars_text)
        vm_overrides   = {"签署日期": datetime.now().strftime("%Y-%m-%d")}

        # VM 手动输入缺失变量（非 --yes 模式）
        needs_vm = [v for v in required_vars if v in VM_INPUT_VARS]
        if needs_vm and not args.dry_run and not args.yes:
            print(f"\n以下变量需要手动输入（直接回车跳过）：")
            for var in needs_vm:
                hint = VM_INPUT_VARS[var]
                val = input(f"  {var}（{hint}）: ").strip()
                if val:
                    vm_overrides[var] = val

        var_map, missing, filled, empty, unmatched = build_var_map(fields, required_vars, vm_overrides)
        s.finish(
            output=(
                f"共 {len(required_vars)} 个变量  "
                f"填充: {len(filled)}  空值: {len(empty)}  未知: {len(unmatched)}"
            )
        )

    # 变量异常时 Human Decision
    if (empty or unmatched) and not args.yes and not args.dry_run:
        ctx = {"已填充": len(filled), "空值变量": ", ".join(empty) or "无", "未知变量": ", ".join(unmatched) or "无"}
        decision = wf.checkpoint(
            node="变量填充异常确认",
            context=ctx,
            prompt=f"有 {len(empty)+len(unmatched)} 个变量未能自动填充，合同对应位置将留空，是否继续？",
            options=["继续", "取消"],
        )
        if decision == "取消":
            print("已取消，请补全信息后重新运行"); sys.exit(0)

    if args.dry_run:
        wf.trace("跳过生成", output_summary="[DRY-RUN] 不生成文件", status=StepStatus.SKIPPED)
        wf.summary()
        return

    # ── Step 6: 下载模板 docx ─────────────────────────────────────────────────
    att_list = extract_attachments(template_rec.get("fields", {}).get(TEMPLATE_ATT_FLD, []))
    if not att_list:
        wf.error("下载模板失败", "合同模板表中无 AI合同模版 附件")
        sys.exit(1)

    import subprocess as sp
    from docx import Document

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        template_docx = tmpdir / att_list[0]["name"]

        with wf.step("下载合同模板 docx", input_summary=att_list[0]["name"]) as s:
            r = sp.run(
                ["lark-cli", "base", "+attachment-download",
                 "--base-token", TEMPLATE_BASE,
                 "--file-token", att_list[0]["file_token"],
                 "--output", str(template_docx)],
                capture_output=True, text=True
            )
            if r.returncode != 0:
                s.finish(output=f"下载失败: {r.stderr[:100]}", status=StepStatus.FAILED)
                sys.exit(1)
            s.finish(output=f"✅ 下载完成  {template_docx.stat().st_size // 1024} KB")

        # ── Step 7: 填充变量 ──────────────────────────────────────────────────
        with wf.step("填充合同变量", input_summary=f"{len(filled)} 个变量替换") as s:
            doc = Document(template_docx)
            fill_template_vars(doc, var_map)

            # 二次残留检查
            all_text   = "\n".join(p.text for p in doc.paragraphs)
            remaining  = re.findall(r'\{\{[^}]+\}\}', all_text)
            status_msg = f"填充完成，残留 {len(remaining)} 处未替换" if remaining else "✅ 所有变量已替换"
            s.finish(output=status_msg)

        # ── Step 8: 插入证件扫描件 ────────────────────────────────────────────
        if id_scans and not is_company:
            with wf.step("下载并插入证件扫描件", input_summary=f"{len(id_scans)} 张") as s:
                img_paths = download_id_scan_images(fields, tmpdir)
                if img_paths:
                    insert_id_scan(doc, img_paths)
                    s.finish(output=f"✅ 插入 {len(img_paths)} 张")
                else:
                    s.finish(output="⚠️  下载失败，跳过插图", status=StepStatus.SKIPPED)
        else:
            wf.trace("跳过证件插入", output_summary="公司合同或无扫描件", status=StepStatus.SKIPPED)

        # ── Step 9: 保存合同文件 ──────────────────────────────────────────────
        with wf.step("保存合同文件", input_summary=str(OUTPUT_DIR)) as s:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            date_str   = datetime.now().strftime("%Y-%m-%d")
            safe_name  = re.sub(r'[^\w\-\u4e00-\u9fff]', '_', name)
            output_path = OUTPUT_DIR / f"{date_str}_{safe_name}_{template_name}"
            doc.save(output_path)
            s.finish(output=str(output_path))

        open_docx(output_path)

        print(f"\n合同已打开预览，确认无误后生成签约邮件草稿：")
        print(f"  python3 scripts/generate_contract_v2.py --record-id {target['record_id']} --send --contract-file '{output_path}'")

    wf.summary()


if __name__ == "__main__":
    main()
