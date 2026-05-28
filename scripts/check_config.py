#!/usr/bin/env python3
"""
check_config.py
===============
验证 config.yaml 配置是否完整，检查 SMTP/飞书/LLM 连通性。
VM 首次配置完后运行，确认一切正常再走 TEST_MODE。

用法：
    python3 scripts/check_config.py
"""

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_smtp, get_lark, get_llm_api_key, validate_config, is_test_mode, get_test_email

def check_smtp(cfg):
    smtp = get_smtp(cfg)
    host = smtp.get("host", "")
    port = smtp.get("port", 465)
    user = smtp.get("user", "")
    pwd  = smtp.get("password", "")
    if not all([host, user, pwd]):
        return False, "host/user/password 未填写"
    try:
        import smtplib, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=8) as s:
            s.login(user, pwd)
        return True, f"{user} 登录成功"
    except Exception as e:
        return False, str(e)

def check_lark(cfg):
    lark = get_lark(cfg)
    token = lark.get("base_token", "")
    table = lark.get("resume_table_id", "")
    if not token or not table:
        return False, "base_token / resume_table_id 未填写"
    r = subprocess.run(
        ["lark-cli", "base", "+record-list",
         "--base-token", token, "--table-id", table,
         "--as", "bot", "--limit", "1", "--format", "json"],
        capture_output=True, text=True, timeout=15
    )
    if '"ok": true' in r.stdout or '"record_id_list"' in r.stdout:
        return True, "飞书表可正常访问"
    return False, r.stdout[:120] or r.stderr[:120]

def check_llm(cfg):
    key = get_llm_api_key(cfg)
    if not key:
        return False, "api_key 未找到（config.yaml / 环境变量 / openclaw.json 均未配置）"
    try:
        import anthropic
        base_url = cfg.get("llm", {}).get("base_url", "https://ai-proxy.37wan.com/anthropic")
        client = anthropic.Anthropic(base_url=base_url, api_key=key)
        msg = client.messages.create(
            model=cfg.get("llm", {}).get("model", "claude-sonnet-4-5-20250929"),
            max_tokens=16,
            messages=[{"role": "user", "content": "reply: ok"}]
        )
        return True, f"LLM 响应正常（{msg.usage.output_tokens} tokens）"
    except Exception as e:
        return False, str(e)[:120]

def check_templates(cfg):
    from config_loader import get_paths
    tdir = Path(get_paths(cfg).get("contract_templates", "")).expanduser()
    if not tdir.exists():
        return False, f"模板目录不存在：{tdir}"
    docx_files = list(tdir.glob("*.docx"))
    if not docx_files:
        return False, f"模板目录为空，请放入 .docx 合同模板：{tdir}"
    return True, f"找到 {len(docx_files)} 个模板文件"

def main():
    print("=" * 55)
    print("  loc-resume-screening 配置检查")
    print("=" * 55)

    cfg = load_config()

    # 1. 配置完整性
    print("\n📋 配置完整性检查")
    issues = validate_config(cfg)
    if issues:
        for iss in issues:
            print(f"  ❌ {iss}")
        print("\n请先填写 config.yaml 后再运行此脚本。")
        sys.exit(1)
    print("  ✅ config.yaml 字段完整")

    # 2. SMTP
    print("\n📧 SMTP 连通性")
    ok, msg = check_smtp(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")

    # 3. 飞书
    print("\n🪁 飞书 Base 访问")
    ok, msg = check_lark(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")

    # 4. LLM
    print("\n🤖 LLM API")
    ok, msg = check_llm(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")

    # 5. 合同模板
    print("\n📄 合同模板")
    ok, msg = check_templates(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")

    # 6. TEST_MODE 提示
    print("\n⚙️  运行模式")
    if is_test_mode(cfg):
        te = get_test_email(cfg)
        print(f"  🟡 TEST_MODE 开启，邮件将发送至：{te}")
        print("     确认全流程无误后，将 config.yaml 中 test_mode.enabled 改为 false")
    else:
        print("  🟢 正式模式，邮件将发送至真实资源商")

    print("\n" + "=" * 55)
    print("  配置检查完成，可以开始使用！")
    print("=" * 55)

if __name__ == "__main__":
    main()
