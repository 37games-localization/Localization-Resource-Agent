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

def check_gh_cli() -> tuple[bool, str]:
    """检查 gh CLI 是否安装且已登录"""
    import shutil
    if not shutil.which("gh"):
        return False, "未安装 gh CLI"
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if r.returncode == 0:
        # 提取登录账号
        for line in r.stdout.splitlines():
            if "Logged in" in line:
                return True, line.strip()
        return True, "已登录"
    return False, "未登录（需要 gh auth login）"


def check_badcase_config(cfg: dict) -> list[tuple[str, bool, str]]:
    """
    检查 badcase 回流相关配置，返回 [(item, ok, msg), ...]
    """
    results = []
    bc = cfg.get("badcase_export", {})
    gh = cfg.get("github", {})

    # badcase_export.enabled
    enabled = bc.get("enabled", False)
    results.append((
        "badcase_export.enabled",
        enabled,
        "已开启" if enabled else "未开启（设为 true 后才会自动导出）"
    ))

    if enabled:
        # export_dir 可写
        from pathlib import Path
        export_dir = Path(bc.get("export_dir", "~/Documents/loc-agent-badcase-exports/")).expanduser()
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
            results.append(("export_dir 可写", True, str(export_dir)))
        except Exception as e:
            results.append(("export_dir 可写", False, str(e)))

        # gh CLI
        ok, msg = check_gh_cli()
        results.append(("gh CLI", ok, msg))

        # github.token（备用）
        token = gh.get("token", "")
        if not ok:
            # gh 不可用时，token 就是必填
            results.append((
                "github.token",
                bool(token),
                "已配置" if token else "未配置（gh CLI 不可用时必填）"
            ))

    return results

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

    # 7. Badcase 回流
    print("\n🚨 Badcase 回流配置")
    bc_results = check_badcase_config(cfg)
    bc_enabled = cfg.get("badcase_export", {}).get("enabled", False)

    if not bc_enabled:
        print("  🟡 badcase_export.enabled = false（未开启）")
        print()
        print("  💡 开启方法：")
        print("     1. 在 config.yaml 中设置：")
        print("        badcase_export:")
        print("          enabled: true")
        print()
        print("     2. 确保機器上已安装 gh CLI 并登录：")
        print("        安装： https://cli.github.com")
        print("        登录： gh auth login")
        print()
        print("     3. 重新运行此脚本验证配置")
        print()
        print("  开启后，在飞书主表对候选人标记「⚠️ 是」即可回流 badcase，")
        print("  或者直接告诉 Agent 「把 XXX 标成 badcase」。")
        print("  系统自动收集上下文并在 GitHub 开 issue，无需 VM 手动整理。")
    else:
        all_ok = True
        for item, ok, msg in bc_results:
            icon = "✅" if ok else "❌"
            print(f"  {icon} {item}：{msg}")
            if not ok:
                all_ok = False

        if not all_ok:
            print()
            print("  💡 修复建议：")
            for item, ok, msg in bc_results:
                if not ok:
                    if "gh CLI" in item and "未安装" in msg:
                        print("     • 安装 gh CLI： https://cli.github.com")
                        print("       安装后运行： gh auth login")
                    elif "gh CLI" in item and "未登录" in msg:
                        print("     • 登录 GitHub： gh auth login")
                    elif "github.token" in item:
                        print("     • 在 config.yaml 配置 github.token（找 penny 获取 token）")
                    elif "export_dir" in item:
                        print(f"     • 检查导出目录路径权限：{msg}")

    print("\n" + "=" * 55)
    print("  配置检查完成，可以开始使用！")
    print("=" * 55)

if __name__ == "__main__":
    main()
