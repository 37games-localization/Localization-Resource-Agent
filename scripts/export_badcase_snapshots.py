#!/usr/bin/env python3
"""
export_badcase_snapshots.py
============================
扫描飞书主表中标记了「是否Badcase=⚠️ 是」的候选人记录，
生成脱敏 JSON 快照，写入本地导出目录，再 git commit + push，
最后在 GitHub 项目仓库自动开 issue。

用法：
    python3 scripts/export_badcase_snapshots.py            # 正常导出
    python3 scripts/export_badcase_snapshots.py --dry-run  # 预览，不写文件不推送
    python3 scripts/export_badcase_snapshots.py --quiet    # 无交互输出（定时任务用）
"""

import sys
import os
import json
import re
import hashlib
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_lark

# ── 常量 ─────────────────────────────────────────────────────────────────────
SKILL_ROOT   = Path(__file__).parent.parent
SNAPSHOT_VER = "1.0"

# 飞书主表（资源候选人）
MAIN_BASE_TOKEN = "HekabpDDkaUzyCsjKpqlCEFJgQf"
MAIN_TABLE_ID   = "tblkYSN55qkj9Td4"

# Badcase 相关字段 ID
FIELD_NAME         = "fldQDTAGAO"   # 姓名
FIELD_BADCASE      = "fldxTGrPF3"   # 是否Badcase
FIELD_EXPECTED     = "fldqs6UgTv"   # 期望结果
FIELD_STATUS       = "fldOJfq2kS"   # 当前状态
FIELD_LANG         = "fldiy5OSEA"   # 语言对
FIELD_SERVICE      = "fldssgQ0Dw"   # 服务类型
FIELD_SCORE        = "fldbBEzyvM"   # AI评分
FIELD_SCORE_GRADE  = "fld2zpqoEt"   # 评分等级
FIELD_AI_SUGGEST   = "fld6ZTTzTd"   # AI建议
FIELD_SCORE_BASIS  = "fld60e9uZ2"   # 评分依据
FIELD_EMAIL        = "fldj0abHtB"   # 邮箱（脱敏）
FIELD_PHONE        = "fldk0lFw0v"   # 电话（脱敏）

# 敏感字段：绝对不写入 snapshot
REDACT_FIELDS = {FIELD_EMAIL, FIELD_PHONE}

# 安全扫描模式（发现时阻断并提示）
DANGER_PATTERNS = [
    (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "邮箱地址"),
    (r"\d{15,18}",                                           "身份证号疑似"),
    (r"\d{16,20}",                                           "银行账号疑似"),
    (r"BEGIN PRIVATE KEY",                                   "私钥"),
    (r"api_key\s*[=:]\s*\S+",                               "api_key"),
    (r"password\s*[=:]\s*\S+",                              "密码"),
]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def _anon_id(record_id: str, salt: str) -> str:
    raw = (record_id + salt).encode()
    return "cand_" + hashlib.sha256(raw).hexdigest()[:12]

def _load_salt(cfg: dict) -> str:
    salt = cfg.get("badcase_export", {}).get("local_salt", "")
    if not salt:
        # 自动生成并写回 config.yaml（仅第一次）
        import secrets, yaml
        salt = secrets.token_hex(16)
        cfg_path = SKILL_ROOT / "config.yaml"
        text = cfg_path.read_text(encoding="utf-8")
        # 插入 local_salt 到 badcase_export 块
        if "local_salt:" in text:
            text = re.sub(r"local_salt:\s*\"\"", f'local_salt: "{salt}"', text)
        else:
            text += f'\n  local_salt: "{salt}"\n'
        cfg_path.write_text(text, encoding="utf-8")
        print(f"[init] 首次运行，已生成 local_salt 并写入 config.yaml")
    return salt

def _lark_cli(*args) -> dict:
    """调用 lark-cli，返回解析后的 JSON dict"""
    cmd = ["lark-cli"] + list(args) + ["--format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "error": r.stderr or r.stdout}

def _scan_secrets(obj, path="root") -> list[str]:
    """递归扫描 dict/list 中的敏感模式，返回发现列表"""
    hits = []
    if isinstance(obj, str):
        for pattern, label in DANGER_PATTERNS:
            if re.search(pattern, obj, re.IGNORECASE):
                hits.append(f"{path}: {label}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits.extend(_scan_secrets(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(_scan_secrets(v, f"{path}[{i}]"))
    return hits

def _field_text(record: dict, field_id: str) -> str:
    """从 record 中安全取文本值"""
    val = record.get("fields", {}).get(field_id, "")
    if isinstance(val, list):
        # 多值字段（select / attachment 等）
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text", item.get("name", str(item))))
            else:
                parts.append(str(item))
        return ", ".join(parts)
    return str(val) if val else ""


# ── 核心流程 ──────────────────────────────────────────────────────────────────

def fetch_badcases() -> list[dict]:
    """从飞书主表拉取所有 是否Badcase=⚠️ 是 的记录"""
    result = _lark_cli(
        "base", "+record-search",
        "--base-token", MAIN_BASE_TOKEN,
        "--table-id", MAIN_TABLE_ID,
        "--filter", json.dumps({
            "conjunction": "and",
            "conditions": [{
                "field_id": FIELD_BADCASE,
                "operator": "is",
                "value": ["⚠️ 是"]
            }]
        })
    )
    if not result.get("ok"):
        print(f"❌ 飞书查询失败：{result.get('error', result)}")
        return []
    return result.get("data", {}).get("items", [])


def build_snapshot(record: dict, salt: str) -> dict:
    """构建单条脱敏 snapshot"""
    rid = record.get("record_id", "")
    fields = record.get("fields", {})

    # 脱敏姓名 → 匿名 ID
    anon = _anon_id(rid, salt)

    # 读取 run log（如果存在）
    run_log = _load_run_log(rid)

    snapshot = {
        "snapshot_version": SNAPSHOT_VER,
        "exported_at": _now_iso(),
        "source": {
            "skill": "loc-resume-screening",
            "record_id_hash": anon,
        },
        "badcase": {
            "vm_expected_result": _field_text(record, FIELD_EXPECTED) or "(未填写)",
            "current_status": _field_text(record, FIELD_STATUS),
        },
        "resource": {
            "anonymous_id": anon,
            "language_pair":  _field_text(record, FIELD_LANG),
            "services":       _field_text(record, FIELD_SERVICE),
        },
        "assessment": {
            "ai_score":       _field_text(record, FIELD_SCORE),
            "score_grade":    _field_text(record, FIELD_SCORE_GRADE),
            "ai_suggestion":  _field_text(record, FIELD_AI_SUGGEST),
            "score_basis":    _field_text(record, FIELD_SCORE_BASIS),
        },
        "agent_run": run_log,
        "redaction": {
            "removed_fields": ["email", "phone", "name", "id_number", "bank_account"],
            "contains_raw_resume": False,
            "contains_contract_text": False,
            "contains_payment_info": False,
        }
    }
    return snapshot


def _load_run_log(record_id: str) -> dict:
    """从本地 run log 目录读取该候选人最近一次运行记录"""
    cache_dir = Path.home() / ".loc-resume-cache" / "run_logs"
    if not cache_dir.exists():
        return {}
    # 按文件名排序取最新
    logs = sorted(cache_dir.glob(f"*_{record_id}_*.json"), reverse=True)
    if not logs:
        # 尝试宽泛搜索（record_id 可能不在文件名中）
        logs = sorted(cache_dir.glob("*.json"), reverse=True)
        logs = [l for l in logs if record_id in l.read_text(encoding="utf-8", errors="ignore")]
    if not logs:
        return {}
    try:
        return json.loads(logs[0].read_text(encoding="utf-8"))
    except Exception:
        return {}


def export_snapshots(dry_run: bool, quiet: bool, cfg: dict) -> list[Path]:
    """主导出流程，返回写出的文件列表"""
    salt = _load_salt(cfg)
    export_cfg = cfg.get("badcase_export", {})
    export_dir = Path(export_cfg.get("export_dir", "~/Documents/loc-agent-badcase-exports/")).expanduser()
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = export_dir / today

    records = fetch_badcases()
    if not records:
        if not quiet:
            print("✅ 没有待导出的 badcase 记录")
        return []

    if not quiet:
        print(f"📋 发现 {len(records)} 条 badcase 记录")

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for record in records:
        rid = record.get("record_id", "unknown")
        snap = build_snapshot(record, salt)

        # 安全扫描
        hits = _scan_secrets(snap)
        if hits:
            print(f"⛔ 记录 {rid} 安全扫描发现敏感内容，已跳过：")
            for h in hits:
                print(f"   · {h}")
            continue

        anon = snap["resource"]["anonymous_id"]
        status_slug = snap["badcase"]["current_status"].replace(" ", "_").replace("/", "_")[:20]
        filename = f"bc_{anon}_{status_slug}.json"
        out_path = out_dir / filename

        if dry_run:
            if not quiet:
                print(f"[dry-run] 将写入：{out_path}")
                print(json.dumps(snap, ensure_ascii=False, indent=2))
        else:
            out_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            if not quiet:
                print(f"✅ 已写入：{out_path}")
            written.append(out_path)

    return written


def git_commit_and_push(files: list[Path], quiet: bool):
    """git add + commit + push 写出的 snapshot 文件"""
    if not files:
        return
    skill_dir = SKILL_ROOT

    # 把文件相对路径加入暂存
    for f in files:
        rel = f.relative_to(skill_dir) if f.is_relative_to(skill_dir) else f
        subprocess.run(["git", "-C", str(skill_dir), "add", str(f)], capture_output=True)

    today = datetime.now().strftime("%Y-%m-%d")
    msg = f"badcase: export snapshots {today} ({len(files)} records)"
    r = subprocess.run(
        ["git", "-C", str(skill_dir), "commit", "-m", msg],
        capture_output=True, text=True
    )
    if r.returncode != 0 and "nothing to commit" not in r.stdout + r.stderr:
        if not quiet:
            print(f"⚠️  git commit 异常：{r.stderr.strip()}")
        return

    r2 = subprocess.run(
        ["git", "-C", str(skill_dir), "push"],
        capture_output=True, text=True
    )
    if not quiet:
        if r2.returncode == 0:
            print(f"🚀 git push 成功")
        else:
            print(f"⚠️  git push 失败：{r2.stderr.strip()}")


def create_github_issues(snapshots: list[dict], cfg: dict, quiet: bool):
    """为每条 badcase snapshot 在 GitHub 仓库开 issue"""
    gh_cfg = cfg.get("github", {})
    repo = gh_cfg.get("repo", "<org-or-user>/<repo>")
    token = gh_cfg.get("token", "")

    if not token:
        # 尝试从 git remote URL 中提取（已配置 HTTPS token 时）
        r = subprocess.run(
            ["git", "-C", str(SKILL_ROOT), "remote", "get-url", "origin"],
            capture_output=True, text=True
        )
        url = r.stdout.strip()
        m = re.search(r"ghp_\w+", url)
        if m:
            token = m.group(0)

    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token

    for snap in snapshots:
        anon    = snap["resource"]["anonymous_id"]
        status  = snap["badcase"]["current_status"]
        expect  = snap["badcase"]["vm_expected_result"]
        lang    = snap["resource"]["language_pair"]
        service = snap["resource"]["services"]
        score   = snap["assessment"]["ai_score"]
        grade   = snap["assessment"]["score_grade"]
        suggest = snap["assessment"]["ai_suggestion"]
        exported_at = snap["exported_at"]

        title = f"[Badcase] {status} — {anon[:16]}"
        body = f"""## Badcase 回流

**匿名候选人 ID**：`{anon}`
**当前状态**：{status}
**语言对**：{lang}
**服务类型**：{service}

### VM 期望结果
{expect}

### Agent 评估摘要
- 评分：{score}（{grade}）
- AI建议：{suggest}

### 快照信息
- 导出时间：{exported_at}
- Snapshot 版本：{snap["snapshot_version"]}

---
*此 issue 由 export_badcase_snapshots.py 自动生成，脱敏处理，不含真实姓名/邮箱/证件/银行信息。*
*项目负责人处理：判断归因 → 修复 → 补测试用例 → 关闭 issue。*
"""

        cmd = [
            "gh", "issue", "create",
            "--repo", repo,
            "--title", title,
            "--body", body,
            "--label", "badcase"
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if not quiet:
            if r.returncode == 0:
                print(f"📌 GitHub issue 已创建：{r.stdout.strip()}")
            else:
                # label 不存在时自动降级（去掉 --label 重试）
                if "Label" in r.stderr or "label" in r.stderr:
                    cmd2 = [c for c in cmd if c != "--label" and c != "badcase"]
                    r2 = subprocess.run(cmd2, capture_output=True, text=True, env=env)
                    if r2.returncode == 0:
                        print(f"📌 GitHub issue 已创建（无label）：{r2.stdout.strip()}")
                    else:
                        print(f"⚠️  GitHub issue 创建失败：{r2.stderr.strip()}")
                else:
                    print(f"⚠️  GitHub issue 创建失败：{r.stderr.strip()}")


def mark_exported(record_ids: list[str], dry_run: bool, quiet: bool):
    """将已导出的记录状态从 '⚠️ 是' 更新为 '✅ 已处理'（可选，不阻断主流程）"""
    if dry_run or not record_ids:
        return
    for rid in record_ids:
        r = _lark_cli(
            "base", "+record-upsert",
            "--base-token", MAIN_BASE_TOKEN,
            "--table-id", MAIN_TABLE_ID,
            "--record-id", rid,
            "--json", json.dumps({FIELD_BADCASE: "✅ 已处理"})
        )
        if not quiet and not r.get("ok"):
            print(f"⚠️  回写飞书状态失败（{rid}）：{r.get('error', '')}")


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="导出 Badcase 脱敏快照并推送到 GitHub")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写文件，不推送")
    parser.add_argument("--quiet",   action="store_true", help="静默模式（定时任务用）")
    args = parser.parse_args()

    cfg = load_config()
    export_cfg = cfg.get("badcase_export", {})

    if not export_cfg.get("enabled", False) and not args.dry_run:
        print("ℹ️  badcase_export.enabled=false，跳过导出。")
        print("   如需启用，在 config.yaml 中设置 badcase_export.enabled: true")
        sys.exit(0)

    if not args.quiet:
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}🔍 扫描飞书 Badcase 记录...")

    # 拉取 + 导出
    records = fetch_badcases()
    if not records:
        if not args.quiet:
            print("✅ 没有待处理的 badcase 记录")
        return

    salt = _load_salt(cfg)
    export_dir = Path(export_cfg.get("export_dir", "~/Documents/loc-agent-badcase-exports/")).expanduser()
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = export_dir / today

    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    written_paths = []
    written_snapshots = []
    written_record_ids = []

    if not args.quiet:
        print(f"📋 发现 {len(records)} 条 badcase 记录")

    for record in records:
        rid = record.get("record_id", "unknown")
        snap = build_snapshot(record, salt)

        hits = _scan_secrets(snap)
        if hits:
            print(f"⛔ 记录 {rid} 安全扫描命中，已跳过：")
            for h in hits:
                print(f"   · {h}")
            continue

        anon = snap["resource"]["anonymous_id"]
        status_slug = snap["badcase"]["current_status"].replace(" ", "_")[:20]
        filename = f"bc_{anon}_{status_slug}.json"
        out_path = out_dir / filename

        if args.dry_run:
            if not args.quiet:
                print(f"\n[dry-run] → {out_path}")
                print(json.dumps(snap, ensure_ascii=False, indent=2))
        else:
            out_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            if not args.quiet:
                print(f"✅ 已写入：{out_path}")
            written_paths.append(out_path)
            written_snapshots.append(snap)
            written_record_ids.append(rid)

    if args.dry_run:
        if not args.quiet:
            print("\n[dry-run] 完成，未写入任何文件")
        return

    # git commit + push
    if written_paths:
        git_commit_and_push(written_paths, args.quiet)

    # 开 GitHub issue
    if written_snapshots:
        create_github_issues(written_snapshots, cfg, args.quiet)

    # 回写飞书状态（可选）
    auto_mark = export_cfg.get("auto_mark_exported", False)
    if auto_mark:
        mark_exported(written_record_ids, args.dry_run, args.quiet)

    if not args.quiet:
        print(f"\n🎉 完成，共处理 {len(written_paths)} 条 badcase")


if __name__ == "__main__":
    main()
