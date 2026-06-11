#!/usr/bin/env python3
"""
send_rejection_email.py
=======================
向「已拒绝」候选人发送婉拒邮件。
生成邮件预览 → VM 确认 → 发送（防误操作）

用法：
    python3 scripts/send_rejection_email.py --name "刘启航"
    python3 scripts/send_rejection_email.py --record-id recXXX
    python3 scripts/send_rejection_email.py --name "刘启航" --dry-run
    python3 scripts/send_rejection_email.py --name "刘启航" --yes
"""

import sys, re, json, argparse, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_smtp, get_lark, get_paths, is_test_mode, get_test_email
from field_resolver import field_id_or
from lark_cli_utils import normalize_record_list_data, run_lark_cli_json
from manual_trace import log_manual_step

_CFG = load_config()

# ── 配置 ──────────────────────────────────────────────────────────────────────
BASE_TOKEN = get_lark(_CFG).get("base_token", "")
TABLE_ID   = get_lark(_CFG).get("resume_table_id", "")

SMTP_HOST  = get_smtp(_CFG).get("host", "")
SMTP_PORT  = get_smtp(_CFG).get("port", 465)
SMTP_USER  = get_smtp(_CFG).get("user", "")
SMTP_PASS  = get_smtp(_CFG).get("password", "")

TEST_MODE  = is_test_mode(_CFG)
TEST_EMAIL = get_test_email(_CFG)

FLD_NAME   = field_id_or("candidate", "candidate.name", "fldSAfsOJf")
FLD_EMAIL  = field_id_or("candidate", "candidate.email", "fldWf5X8NR")
FLD_STATUS = field_id_or("candidate", "candidate.status", "fldfp6Pn7l")

# ── lark-cli ──────────────────────────────────────────────────────────────────
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
            if isinstance(v, dict):
                parts.append(v.get("name") or v.get("text") or "")
            else:
                parts.append(str(v))
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
        records.extend(normalize_record_list_data(db))
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

# ── 邮件构建 ──────────────────────────────────────────────────────────────────
def build_rejection_email(name: str, lang: str) -> tuple[str, str]:
    if lang == "zh":
        subject = f"【Localization Team】感谢您的申请 - {name}"
        body = f"""您好，{name}，

感谢您对本次翻译合作机会的关注，以及您所投入的时间和精力。

经过仔细评估，我们认为您目前的经历与我们当前的项目需求尚不完全匹配，因此暂时无法进一步推进合作。

这并不代表对您能力的否定。如果未来有合适的机会，我们会优先考虑与您联系。

再次感谢您的申请，祝您一切顺利！

此致
Localization Team"""
    else:
        subject = f"[Localization Team] Thank You for Your Application - {name}"
        body = f"""Dear {name},

Thank you for your interest in collaborating with us and for the time and effort you invested in your application.

After careful consideration, we have determined that your current profile does not fully align with our immediate project needs, and we are unable to move forward at this time.

This is in no way a reflection of your abilities. Should a suitable opportunity arise in the future, we would be happy to reach out to you.

Thank you again for applying, and we wish you all the best!

Best regards,
Localization Team"""
    return subject, body

# ── 发送邮件 ──────────────────────────────────────────────────────────────────
def save_draft(msg, draft_dir: Path, filename: str):
    """保存为 .eml 草稿文件，VM 双击用邮件客户端打开后点发送"""
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / filename
    draft_path.write_text(msg.as_string(), encoding="utf-8")
    return draft_path


def send_email(to_email: str, subject: str, body: str, draft: bool = False):
    import smtplib, ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    actual_to = TEST_EMAIL if TEST_MODE else to_email
    msg = MIMEMultipart()
    msg["From"]    = SMTP_USER
    msg["To"]      = actual_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if draft:
        draft_dir = Path(get_paths(_CFG).get("contract_output", "~/Documents/loc-contracts/output/")).expanduser() / "drafts"
        safe_name = re.sub(r'[^\w\-\u4e00-\u9fff.]', '_', to_email)
        draft_path = save_draft(msg, draft_dir, f"婉拒_{safe_name}.eml")
        print(f"📝 草稿已保存：{draft_path}")
        print(f"   双击用邮件客户端打开，确认无误后点发送")
        return

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as srv:
        srv.login(SMTP_USER, SMTP_PASS)
        srv.sendmail(SMTP_USER, actual_to, msg.as_string())

    tag = f"⚠️  [测试模式] 发到 {actual_to}（原始目标：{to_email}）" if TEST_MODE else f"✅ 已发至 {actual_to}"
    print(tag)

# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="婉拒邮件发送（含确认防误操作）")
    parser.add_argument("--name",      help="资源商姓名（模糊匹配）")
    parser.add_argument("--record-id", help="飞书 record_id（精确）")
    parser.add_argument("--dry-run",   action="store_true", help="只预览不发送")
    parser.add_argument("--yes",       action="store_true", help="跳过确认直接发送")
    parser.add_argument("--draft",     action="store_true", help="保存草稿而非直接发送，VM 双击 .eml 后点发送")
    args = parser.parse_args()

    if not args.name and not args.record_id:
        parser.print_help(); sys.exit(0)

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
            for r in matches:
                print(f"  {r['record_id']}  {extract_text(r['fields'].get(FLD_NAME))}")
            sys.exit(1)
        target = matches[0]

    if not target:
        print(f"❌ 未找到记录"); sys.exit(1)

    f      = target["fields"]
    name   = extract_text(f.get(FLD_NAME)) or "未知"
    email  = extract_text(f.get(FLD_EMAIL))
    status = extract_text(f.get(FLD_STATUS))
    lang   = "zh" if re.search(r'[\u4e00-\u9fff]', name) else "en"

    # 状态检查：只有「已拒绝」才能发婉拒邮件
    if "拒绝" not in status and "reject" not in status.lower():
        print(f"⚠️  当前状态为「{status}」，不是「已拒绝」")
        if args.dry_run:
            print("[DRY-RUN] 仅预览风险，不要求交互确认。")
        else:
            try:
                ans = input("确认仍要发送婉拒邮件？[y/N] ").strip().lower()
            except EOFError:
                print("❌ 非交互环境无法确认；请先把候选人状态改为「已拒绝」，或在人工确认后使用 --yes。")
                sys.exit(1)
            if ans != "y":
                print("❌ 已取消"); sys.exit(0)

    subject, body = build_rejection_email(name, lang)

    print(f"\n候选人：{name}  ({email})  当前状态：{status}\n")
    print("=" * 62)
    print("📧 婉拒邮件预览")
    print("=" * 62)
    print(f"收件人：{TEST_EMAIL if TEST_MODE else email}")
    print(f"主  题：{subject}")
    print("-" * 62)
    print(body)
    print("=" * 62)

    if TEST_MODE:
        print(f"\n⚠️  [测试模式] 实际发到：{TEST_EMAIL}（而非 {email}）")

    if args.dry_run:
        print("\n[DRY-RUN] 不发送")
        log_manual_step(
            step_name="婉拒邮件 dry-run",
            status="skipped",
            candidate_name=name,
            candidate_record_id=target["record_id"],
            input_summary=f"当前状态: {status}",
            output_summary=f"收件人(TEST_MODE): {TEST_EMAIL if TEST_MODE else email}",
        )
        return

    # 二次确认（防误操作核心）
    if not args.yes:
        print()
        print("⚠️  婉拒邮件发出后无法撤回，请确认候选人信息无误。")
        ans = input(f"确认向「{name}」发送婉拒邮件？[y/N] ").strip().lower()
        if ans != "y":
            print("❌ 已取消"); sys.exit(0)

    print("\n发送中...")
    send_email(email, subject, body, draft=args.draft)
    print("✅ 婉拒邮件已发送")
    log_manual_step(
        step_name="婉拒邮件发送",
        status="done",
        candidate_name=name,
        candidate_record_id=target["record_id"],
        input_summary=f"当前状态: {status}",
        output_summary=f"发送至: {TEST_EMAIL if TEST_MODE else email}",
        decision="yes" if args.yes else "confirmed",
    )

if __name__ == "__main__":
    main()
