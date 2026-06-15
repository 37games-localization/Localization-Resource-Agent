#!/usr/bin/env python3
"""
send_contract_info_email_v2.py
==============================
Send the contract-information collection form to a candidate.

This step sits between "test passed" and "contract ready". It reads the
candidate from the resume table, uses lark.contract_info_form_url from local
config, generates a draft by default, and only writes Lark status after an
explicit send/direct-send or --mark-sent confirmation.
"""

import argparse
import re
import smtplib
import ssl
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config_loader import get_lark, get_paths, get_smtp, get_test_email, is_test_mode, load_config
from send_test_email import (
    FLD_EMAIL,
    FLD_NAME,
    FLD_STATUS,
    TEST_EMAIL,
    TEST_MODE,
    extract_text,
    fetch_records,
    list_records,
    update_record,
)
from workflow_engine import StepStatus, WorkflowEngine


_CFG = load_config()


def contract_info_form_url() -> str:
    lark = get_lark(_CFG)
    return (
        lark.get("contract_info_form_url")
        or lark.get("contract_form_url")
        or (_CFG.get("contract_info") or {}).get("form_url")
        or ""
    )


def build_subject_body(name: str, form_url: str, lang: str) -> tuple[str, str]:
    if lang == "zh":
        subject = f"【Localization Team】签约信息收集 - {name}"
        body = f"""您好，{name}，

恭喜您通过本次翻译测试！

为了准备后续签约材料，请通过以下链接补充签约所需信息：
{form_url}

请重点确认：
- 姓名 / 邮箱 / 手机号
- 证件信息
- 收款账户、银行信息和币种
- 如以公司主体签约，请填写公司账户信息

信息提交后，我们会基于您填写的内容准备合同，并在发送前再次核对。

谢谢！
Localization Team"""
    else:
        subject = f"[Localization Team] Contract Information Collection - {name}"
        body = f"""Dear {name},

Congratulations on passing the translation test!

To prepare the contract materials, please submit the required contract information through the form below:
{form_url}

Please make sure the following information is accurate:
- Full name / email / phone number
- ID information
- Payment account, bank details, and currency
- Company account information, if you will sign as a company

After you submit the form, we will prepare the contract based on your information and review it before sending.

Best regards,
Localization Team"""
    return subject, body


def save_or_send_email(to_email: str, subject: str, body: str, draft: bool = True) -> str:
    from email.mime.text import MIMEText

    smtp = get_smtp(_CFG)
    actual_to = TEST_EMAIL if TEST_MODE else to_email

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = smtp.get("sender_email") or smtp.get("user", "")
    msg["To"] = actual_to
    msg["Subject"] = subject

    if draft:
        draft_dir = Path(get_paths(_CFG).get("contract_output", "~/Documents/loc-contracts/output/")).expanduser() / "drafts"
        draft_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w\-\u4e00-\u9fff.]", "_", to_email)
        draft_path = draft_dir / f"签约信息收集_{safe_name}.eml"
        draft_path.write_text(msg.as_string(), encoding="utf-8")
        print(f"草稿已保存：{draft_path}")
        return str(draft_path)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with smtplib.SMTP_SSL(smtp["host"], smtp.get("port", 465), context=ctx) as srv:
        srv.login(smtp["user"], smtp["password"])
        srv.sendmail(smtp["user"], actual_to, msg.as_string())

    print(f"已发送至：{actual_to}")
    return actual_to


def find_target(records: list[dict], name: str = "", record_id: str = "") -> dict | None:
    if record_id:
        return next((r for r in records if r.get("record_id") == record_id), None)
    matches = [
        r for r in records
        if name.lower() in extract_text(r.get("fields", {}).get(FLD_NAME)).lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"找到 {len(matches)} 条，请用 --record-id 精确指定：")
        list_records(matches)
        sys.exit(1)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="签约信息收集邮件发送 v2（工作流可视化版）")
    parser.add_argument("--name", help="资源商姓名（模糊匹配）")
    parser.add_argument("--record-id", help="飞书 record_id（精确）")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="预览但不生成草稿、不发送、不写状态")
    parser.add_argument("--prepare", action="store_true", help="仅输出可复制邮件包，不生成草稿、不写状态")
    parser.add_argument("--yes", action="store_true", help="跳过确认，生成草稿或显式 direct-send")
    parser.add_argument("--draft", action="store_true", help="保存草稿而非直接发送")
    parser.add_argument("--send-direct", action="store_true", help="显式允许 SMTP 直发；生产默认禁用直发")
    parser.add_argument("--mark-sent", action="store_true", help="VM 已人工发送签约信息收集邮件后，仅写回合同信息收集中")
    parser.add_argument("--no-lark-log", action="store_true", help="不写飞书流程日志")
    args = parser.parse_args()

    records = fetch_records()
    if args.list:
        list_records(records)
        return

    if not args.name and not args.record_id:
        parser.print_help()
        sys.exit(0)

    target = find_target(records, name=args.name or "", record_id=args.record_id or "")
    if not target:
        print(f"未找到：{args.name or args.record_id}")
        sys.exit(1)

    fields = target["fields"]
    name = extract_text(fields.get(FLD_NAME)) or "未知"
    email = extract_text(fields.get(FLD_EMAIL))
    lang = "zh" if re.search(r"[\u4e00-\u9fff]", name) else "en"
    form_url = contract_info_form_url()

    wf = WorkflowEngine(
        candidate_name=name,
        candidate_record_id=target["record_id"],
        write_lark=not args.no_lark_log,
    )
    wf.run_id = f"contract-info-email-{target['record_id'][:8]}-{int(time.time())}"

    wf.trace(
        "读取候选人信息",
        input_summary=f"record: {target['record_id']}",
        output_summary=f"姓名: {name}  邮箱: {email}",
    )

    if not form_url:
        wf.trace("配置检查失败", output_summary="缺少 lark.contract_info_form_url", status=StepStatus.FAILED)
        print("缺少合同信息收集表单地址：请让 Agent 在 config.local.yaml 写入 lark.contract_info_form_url")
        sys.exit(1)

    if args.mark_sent:
        with wf.step("确认人工发送并写回状态", input_summary=f"record: {target['record_id']}") as s:
            update_record(target["record_id"], {FLD_STATUS: "📧 合同信息收集中"})
            s.finish(output="VM 已确认邮件发送；招募状态 → 📧 合同信息收集中")
        wf.summary()
        return

    if not args.send_direct:
        args.draft = True

    with wf.step("构建签约信息收集邮件", input_summary=f"form_url: {form_url}") as s:
        subject, body = build_subject_body(name, form_url, lang)
        actual_to = get_test_email(_CFG) if is_test_mode(_CFG) else email
        s.finish(output=f"主题: {subject}  收件人: {actual_to}")

    print("\n" + "=" * 62)
    print("签约信息收集邮件预览")
    print("=" * 62)
    print(f"收件人：{actual_to}")
    print(f"主  题：{subject}")
    print(f"表单链接：{form_url}")
    print("-" * 62)
    print(body)
    print("=" * 62)
    if TEST_MODE:
        print(f"\n[测试模式] 实际发到：{TEST_EMAIL}（原始目标：{email}）")

    if args.dry_run or args.prepare:
        wf.trace(
            "跳过发送",
            output_summary="[PREPARE] 不生成草稿、不写状态" if args.prepare else "[DRY-RUN] 不生成草稿、不写状态",
            status=StepStatus.SKIPPED,
        )
        wf.summary()
        return

    if not args.yes:
        decision = wf.checkpoint(
            node="确认发送签约信息收集邮件",
            context={
                "候选人": name,
                "收件人": actual_to,
                "表单链接": form_url,
                "测试模式": "是" if TEST_MODE else "否",
            },
            prompt=(
                "生产默认生成草稿，不直接发送。确认生成草稿，或显式选择 direct-send。"
                if not args.send_direct else
                "确认直接发送以上签约信息收集邮件？"
            ),
            options=["保存草稿", "取消"] if not args.send_direct else ["发送", "保存草稿", "取消"],
        )
        if decision == "取消":
            print("已取消")
            sys.exit(0)
        if decision == "保存草稿":
            args.draft = True

    with wf.step("生成签约信息收集邮件", input_summary=f"→ {actual_to}") as s:
        result = save_or_send_email(email, subject, body, draft=args.draft)
        s.finish(output=f"草稿已保存：{result}" if args.draft else f"发送成功：{result}")

    if args.draft:
        wf.trace(
            "跳过状态写回",
            output_summary=(
                "本地草稿已保存；未发送，未写招募状态。"
                f"VM 人工发送后由 Agent 标记：send_contract_info_email_v2.py --record-id {target['record_id']} --mark-sent"
            ),
            status=StepStatus.SKIPPED,
        )
        wf.summary()
        return

    with wf.step("更新飞书招募状态", input_summary=f"record: {target['record_id']}") as s:
        update_record(target["record_id"], {FLD_STATUS: "📧 合同信息收集中"})
        s.finish(output="招募状态 → 📧 合同信息收集中")

    wf.summary()


if __name__ == "__main__":
    main()
