#!/usr/bin/env python3
"""
check_config.py
===============
验证本机配置是否完整，检查 SMTP/飞书/LLM 连通性。
VM 首次配置完后运行，确认一切正常再走 TEST_MODE。

用法：
    python3 scripts/check_config.py
"""

import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_config_path, get_smtp, get_lark, get_llm_api_key, validate_config, is_test_mode, get_test_email

# ──────────────────────────────────────────────
# 新增：基础依赖检查
# ──────────────────────────────────────────────

def check_pyyaml() -> tuple[bool, str]:
    """硬依赖：检查 pyyaml 是否安装"""
    try:
        import yaml  # noqa: F401
        return True, "pyyaml 已安装"
    except ImportError:
        return False, "pyyaml 未安装 → 运行：pip install pyyaml"


def check_lark_cli_version(min_version: str = "1.0.50") -> tuple[bool, str]:
    """硬依赖：检查 lark-cli 是否安装且版本 >= min_version"""
    import shutil

    if not shutil.which("lark-cli"):
        return False, "lark-cli 未安装 → 请先安装 lark-cli"

    try:
        r = subprocess.run(
            ["lark-cli", "--version"],
            capture_output=True, text=True, timeout=10
        )
        raw = (r.stdout + r.stderr).strip()
        # 解析版本号，支持 "lark-cli 1.0.50" / "1.0.50" 等格式
        import re
        m = re.search(r"(\d+\.\d+\.\d+)", raw)
        if not m:
            return False, f"无法解析 lark-cli 版本号：{raw[:80]}"
        version_str = m.group(1)

        def parse_ver(v):
            return tuple(int(x) for x in v.split("."))

        current = parse_ver(version_str)
        minimum = parse_ver(min_version)

        if current >= minimum:
            return True, f"lark-cli {version_str}（满足最低版本要求 ≥{min_version}）"
        else:
            return False, (
                f"lark-cli {version_str} 低于最低版本 {min_version} "
                f"→ 请运行：lark-cli update"
            )
    except Exception as e:
        return False, f"lark-cli 版本检查失败：{e}"


def check_pymupdf() -> tuple[bool, str]:
    """软依赖：检查 pymupdf 是否安装（失败只警告，不 exit）"""
    try:
        import fitz  # noqa: F401
        return True, "pymupdf 已安装"
    except ImportError:
        return False, (
            "pymupdf 未安装 → PDF 简历将无法解析，评分仅依赖飞书表字段，精度下降\n"
            "     安装命令：pip install pymupdf"
        )


# ──────────────────────────────────────────────
# 新增：飞书 token 非空检查（硬依赖）
# ──────────────────────────────────────────────

def check_lark_tokens(cfg: dict) -> list[tuple[str, bool, str]]:
    """
    硬依赖：检查飞书 base_token / resume_table_id 非空。
    返回 [(field, ok, msg), ...]
    """
    lark = get_lark(cfg)
    results = []

    base_token = lark.get("base_token", "")
    if base_token:
        results.append(("base_token", True, "已填写"))
    else:
        results.append((
            "base_token", False,
            "未填写 → 请在 config.local.yaml 的 lark.base_token 填入飞书多维表格 base token"
        ))

    resume_table_id = lark.get("resume_table_id", "")
    if resume_table_id:
        results.append(("resume_table_id", True, "已填写"))
    else:
        results.append((
            "resume_table_id", False,
            "未填写 → 请在 config.local.yaml 的 lark.resume_table_id 填入简历表 table ID"
        ))

    return results


# ──────────────────────────────────────────────
# 已有检查（保留，不破坏）
# ──────────────────────────────────────────────

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
        return False, "api_key 未配置：请填写 config.local.yaml 的 llm.api_key，或设置 LOC_LLM_API_KEY；不会自动读取 OpenClaw 配额"
    try:
        provider = cfg.get("llm", {}).get("provider", "anthropic")
        base_url = cfg.get("llm", {}).get("base_url", "https://ai-proxy.37wan.com/anthropic")
        model = cfg.get("llm", {}).get("model", "claude-sonnet-4-5-20250929")
        if provider in {"deepseek", "openai_compatible"}:
            import json
            import ssl
            import urllib.request
            try:
                import certifi
                ssl_context = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ssl_context = ssl.create_default_context()
            req = urllib.request.Request(
                f"{base_url.rstrip('/')}/chat/completions",
                data=json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": "reply: ok"}],
                    "max_tokens": 16,
                    "temperature": 0,
                }).encode("utf-8"),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, f"LLM 响应正常（{provider}: {content[:20].strip()}）"
        import anthropic
        client = anthropic.Anthropic(base_url=base_url, api_key=key)
        msg = client.messages.create(
            model=model,
            max_tokens=16,
            messages=[{"role": "user", "content": "reply: ok"}]
        )
        return True, f"LLM 响应正常（{msg.usage.output_tokens} tokens）"
    except Exception as e:
        return False, str(e)[:120]

def check_templates(cfg):
    lark = get_lark(cfg)
    base = lark.get("template_base_token", "")
    table = lark.get("template_table_id", "")
    if not base or not table:
        return False, "lark.template_base_token / template_table_id 未填写"
    r = subprocess.run(
        ["lark-cli", "base", "+record-list",
         "--base-token", base, "--table-id", table,
         "--as", "bot", "--limit", "3", "--format", "json"],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[:160]
    return True, "飞书合同模板表可访问"

def check_gh_cli() -> tuple[bool, str]:
    """检查 gh CLI 是否安装且已登录"""
    import shutil
    if not shutil.which("gh"):
        return False, "未安装 gh CLI"
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if r.returncode == 0:
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

    enabled = bc.get("enabled", False)
    results.append((
        "badcase_export.enabled",
        enabled,
        "已开启" if enabled else "未开启（设为 true 后才会自动导出）"
    ))

    if enabled:
        export_dir = Path(bc.get("export_dir", "~/Documents/loc-agent-badcase-exports/")).expanduser()
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
            results.append(("export_dir 可写", True, str(export_dir)))
        except Exception as e:
            results.append(("export_dir 可写", False, str(e)))

        ok, msg = check_gh_cli()
        results.append(("gh CLI", ok, msg))

        token = gh.get("token", "")
        if not ok:
            results.append((
                "github.token",
                bool(token),
                "已配置" if token else "未配置（gh CLI 不可用时必填）"
            ))

    return results


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  loc-resume-screening 环境自检 v2")
    print("=" * 60)

    # ── Section 1：基础依赖（硬+软） ──────────────────────────
    print("\n🔧 基础依赖")

    hard_dep_failed = False

    # pyyaml（硬依赖）
    ok, msg = check_pyyaml()
    print(f"  {'✅' if ok else '❌'} {msg}")
    if not ok:
        print("     → 请运行：pip install pyyaml")
        hard_dep_failed = True

    # lark-cli 版本（硬依赖）
    ok, msg = check_lark_cli_version("1.0.50")
    print(f"  {'✅' if ok else '❌'} {msg}")
    if not ok:
        hard_dep_failed = True

    # pymupdf（软依赖）
    ok, msg = check_pymupdf()
    if ok:
        print(f"  ✅ {msg}")
    else:
        print(f"  ⚠️  {msg}")

    if hard_dep_failed:
        print("\n❌ 基础依赖检查未通过，请修复后重新运行。")
        sys.exit(1)

    # ── Section 2：配置完整性 ─────────────────────────────────
    print("\n📋 配置完整性")

    cfg = load_config()
    active_config = get_config_path()
    if active_config:
        print(f"  ℹ️  当前读取配置：{active_config}")

    # 2a. 飞书 token 非空（硬依赖）
    token_results = check_lark_tokens(cfg)
    token_failed = False
    for field, ok, msg in token_results:
        print(f"  {'✅' if ok else '❌'} {field}：{msg}")
        if not ok:
            token_failed = True

    if token_failed:
        print("\n❌ 飞书配置缺失，请填写后重新运行。")
        sys.exit(1)

    # 2b. 通用配置完整性
    issues = validate_config(cfg)
    if issues:
        for iss in issues:
            print(f"  ❌ {iss}")
        print("\n请先复制模板并填写本机配置后再运行此脚本：")
        print("  cp config.example.yaml config.local.yaml")
        print("  然后编辑 config.local.yaml")
        sys.exit(1)
    print("  ✅ 配置文件其余字段完整")

    # ── Section 3：SMTP 连通性 ────────────────────────────────
    runtime_failed = False

    print("\n📧 SMTP 连通性")
    ok, msg = check_smtp(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")
    if not ok:
        runtime_failed = True

    # ── Section 4：飞书 Base 访问 ─────────────────────────────
    print("\n🪁 飞书 Base 访问")
    ok, msg = check_lark(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")
    if not ok:
        runtime_failed = True

    # ── Section 5：LLM API ────────────────────────────────────
    print("\n🤖 LLM API")
    ok, msg = check_llm(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")
    if not ok:
        runtime_failed = True

    # ── Section 6：合同模板 ───────────────────────────────────
    print("\n📄 合同模板")
    ok, msg = check_templates(cfg)
    print(f"  {'✅' if ok else '❌'} {msg}")
    if not ok:
        runtime_failed = True

    # ── Section 7：TEST_MODE 提示 ─────────────────────────────
    print("\n⚙️  运行模式")
    if is_test_mode(cfg):
        te = get_test_email(cfg)
        print(f"  🟡 TEST_MODE 开启，邮件将发送至：{te}")
        print("     确认全流程无误后，将 config.local.yaml 中 test_mode.enabled 改为 false")
    else:
        print("  🟢 正式模式，邮件将发送至真实资源商")

    # ── Section 8：Badcase 回流 ───────────────────────────────
    print("\n🚨 Badcase 回流配置")
    bc_results = check_badcase_config(cfg)
    bc_enabled = cfg.get("badcase_export", {}).get("enabled", False)

    if not bc_enabled:
        print("  🟡 badcase_export.enabled = false（未开启）")
        print()
        print("  💡 开启方法：")
        print("     1. 在 config.local.yaml 中设置：")
        print("        badcase_export:")
        print("          enabled: true")
        print()
        print("     2. 确保机器上已安装 gh CLI 并登录：")
        print("        安装： https://cli.github.com")
        print("        登录： gh auth login")
        print()
        print("     3. 重新运行此脚本验证配置")
        print()
        print("  开启后，在飞书主表对候选人标记「⚠️ 是」即可回流 badcase，")
        print("  或者直接告诉 Agent 「把 XXX 标成 badcase」。")
        print("  系统默认直接创建 GitHub issue；Lark 附件上传仅作为显式兼容选项。")
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
                        print("     • 在 config.local.yaml 配置 github.token（找项目负责人获取 token）")
                    elif "export_dir" in item:
                        print(f"     • 检查导出目录路径权限：{msg}")

    print("\n" + "=" * 60)
    if runtime_failed:
        print("  ❌ 环境自检未完全通过，请先修复以上失败项。")
        print("     已通过的单点能力仍可按需测试，但不要切正式环境。")
        print("=" * 60)
        sys.exit(1)

    print("  ✅ 环境自检完成，可以开始使用！")
    print("=" * 60)


if __name__ == "__main__":
    main()
