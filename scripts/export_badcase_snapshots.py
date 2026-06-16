#!/usr/bin/env python3
"""
export_badcase_snapshots.py  (VM 侧)
=====================================
扫描飞书主表中标记了「是否Badcase=⚠️ 是」的候选人记录，
生成脱敏 JSON 快照，并默认直接创建 GitHub issue。

Lark 附件上传不再作为默认链路，仅保留 --upload-lark 兼容旧流程。

用法：
    python3 scripts/export_badcase_snapshots.py            # 正常上报 GitHub issue
    python3 scripts/export_badcase_snapshots.py --dry-run  # 预览，不创建 issue
    python3 scripts/export_badcase_snapshots.py --quiet    # 静默（定时任务用）
"""

import sys
import os
import json
import re
import hashlib
import subprocess
import tempfile
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config
from field_resolver import field_id, table_ref
from manual_trace import log_manual_step
from badcase_protocol import (
    SNAPSHOT_VERSION,
    build_snapshot as build_protocol_snapshot,
    issue_body,
    issue_labels,
    issue_title,
    validate_snapshot,
)

# ── 常量 ─────────────────────────────────────────────────────────────────────
SKILL_ROOT   = Path(__file__).parent.parent
SNAPSHOT_VER = SNAPSHOT_VERSION

MAIN_BASE_TOKEN = ""
MAIN_TABLE_ID   = ""
FIELDS: dict[str, str] = {}


def _init_lark_refs(require_snapshot_field: bool = False):
    """Load current table and field IDs from config/lark-field-mapping.yaml."""
    global MAIN_BASE_TOKEN, MAIN_TABLE_ID, FIELDS
    MAIN_BASE_TOKEN, MAIN_TABLE_ID = table_ref("candidate")
    FIELDS = {
        "badcase": field_id("candidate", "candidate.badcase_flag"),
        "expected": field_id("candidate", "candidate.expected_result"),
        "status": field_id("candidate", "candidate.status"),
        "language_pair": field_id("candidate", "candidate.language_pair"),
        "services": field_id("candidate", "candidate.services"),
        "score": field_id("candidate", "candidate.score"),
        "tier": field_id("candidate", "candidate.tier"),
        "ai_suggestion": field_id("candidate", "candidate.ai_suggestion"),
        "score_basis": field_id("candidate", "candidate.score_basis"),
    }
    if require_snapshot_field:
        FIELDS["snapshot"] = field_id("candidate", "candidate.badcase_snapshot")

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def _anon_id(record_id: str, salt: str) -> str:
    raw = (record_id + salt).encode()
    return "cand_" + hashlib.sha256(raw).hexdigest()[:12]

def _load_salt(cfg: dict) -> str:
    salt = cfg.get("badcase_export", {}).get("local_salt", "")
    if not salt:
        import secrets, yaml
        salt = secrets.token_hex(16)
        cfg_path = SKILL_ROOT / "config.yaml"
        text = cfg_path.read_text(encoding="utf-8")
        if "local_salt:" in text:
            text = re.sub(r'local_salt:\s*""', f'local_salt: "{salt}"', text)
        else:
            text += f'\n  local_salt: "{salt}"\n'
        cfg_path.write_text(text, encoding="utf-8")
        print(f"[init] 首次运行，已生成 local_salt 并写入 config.yaml")
    return salt

def _lark_cli(*args) -> dict:
    cmd = ["lark-cli"] + list(args) + ["--format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "error": r.stderr or r.stdout}

def _field_text(record: dict, field_id: str) -> str:
    val = record.get("fields", {}).get(field_id, "")
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text", item.get("name", str(item))))
            else:
                parts.append(str(item))
        return ", ".join(parts)
    return str(val) if val else ""

def _load_run_log(record_id: str) -> dict:
    cache_dir = Path.home() / ".loc-resume-cache" / "run_logs"
    if not cache_dir.exists():
        return {}
    logs = sorted(cache_dir.glob(f"*_{record_id}_*.json"), reverse=True)
    if not logs:
        logs = sorted(cache_dir.glob("*.json"), reverse=True)
        logs = [l for l in logs if record_id in l.read_text(encoding="utf-8", errors="ignore")]
    if not logs:
        return {}
    try:
        return json.loads(logs[0].read_text(encoding="utf-8"))
    except Exception:
        return {}


def _snapshot_dir(cfg: dict) -> Path:
    export_cfg = cfg.get("badcase_export", {})
    return Path(export_cfg.get("export_dir", "~/Documents/loc-agent-badcase-exports/")).expanduser()


def _github_repo(cfg: dict) -> str:
    repo = (cfg.get("github") or {}).get("repo", "")
    if repo and not repo.startswith("<"):
        return repo
    return ""


def _github_env(cfg: dict) -> dict:
    env = os.environ.copy()
    token = (cfg.get("github") or {}).get("token", "")
    if token and "GH_TOKEN" not in env:
        env["GH_TOKEN"] = token
    return env


# ── 核心流程 ──────────────────────────────────────────────────────────────────

def fetch_badcases(require_snapshot_field: bool = False) -> list[dict]:
    _init_lark_refs(require_snapshot_field=require_snapshot_field)
    result = _lark_cli(
        "base", "+record-list",
        "--base-token", MAIN_BASE_TOKEN,
        "--table-id", MAIN_TABLE_ID,
        "--filter-json", json.dumps({
            "logic": "and",
            "conditions": [[FIELDS["badcase"], "intersects", ["⚠️ 是"]]],
        }, ensure_ascii=False),
        "--limit", "200",
    )
    if not result.get("ok"):
        print(f"❌ 飞书查询失败：{result.get('error', result)}")
        return []
    data = result.get("data", result)
    for key in ("items", "records", "record_list"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    if isinstance(result.get("items"), list):
        return result["items"]
    return []


def build_snapshot(record: dict, salt: str) -> dict:
    rid = record.get("record_id", "")
    run_log = _load_run_log(rid)

    return build_protocol_snapshot(
        record_id=rid,
        salt=salt,
        current_status=_field_text(record, FIELDS["status"]),
        expected_result=_field_text(record, FIELDS["expected"]) or "(未填写)",
        language_pair=_field_text(record, FIELDS["language_pair"]),
        services=_field_text(record, FIELDS["services"]),
        score=_field_text(record, FIELDS["score"]),
        tier=_field_text(record, FIELDS["tier"]),
        ai_suggestion=_field_text(record, FIELDS["ai_suggestion"]),
        score_basis=_field_text(record, FIELDS["score_basis"]),
        agent_run=run_log,
    )


def upload_snapshot_to_lark(record_id: str, snap: dict, dry_run: bool, quiet: bool) -> bool:
    """把快照 JSON 写成临时文件，上传到飞书附件字段"""
    validate_snapshot(snap)
    anon = snap["resource_context"]["anonymous_id"]
    filename = f"badcase_{anon}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    content = json.dumps(snap, ensure_ascii=False, indent=2)

    if dry_run:
        if not quiet:
            print(f"\n[dry-run] 将上传至飞书附件字段（record: {record_id}）")
            print(f"[dry-run] 文件名：{filename}")
            print(content)
        return True

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="badcase_",
        encoding="utf-8", delete=False
    ) as f:
        f.write(content)
        tmp_path = f.name

    try:
        r = subprocess.run(
            [
                "lark-cli", "base", "+record-upload-attachment",
                "--base-token", MAIN_BASE_TOKEN,
                "--table-id", MAIN_TABLE_ID,
                "--record-id", record_id,
                "--field-id", FIELDS["snapshot"],
                "--file", tmp_path,
                "--format", "json"
            ],
            capture_output=True, text=True
        )
        result = json.loads(r.stdout) if r.stdout else {}
        if result.get("ok"):
            if not quiet:
                print(f"  📎 快照已上传至飞书附件：{filename}")
            return True
        else:
            if not quiet:
                print(f"  ❌ 上传失败：{result.get('error', r.stderr[:100])}")
            return False
    except Exception as e:
        if not quiet:
            print(f"  ❌ 上传异常：{e}")
        return False
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def save_snapshot_file(snap: dict, cfg: dict) -> Path:
    validate_snapshot(snap)
    anon = snap["resource_context"]["anonymous_id"]
    export_dir = _snapshot_dir(cfg)
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"badcase_{anon}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def push_snapshot_to_github(snap: dict, cfg: dict, dry_run: bool, quiet: bool) -> bool:
    validate_snapshot(snap)
    title = issue_title(snap)
    body = issue_body(snap)
    labels = issue_labels(snap)

    if dry_run:
        if not quiet:
            print("\n[dry-run] 将创建 GitHub issue")
            print(f"[dry-run] 标题：{title}")
            print(f"[dry-run] 标签：{', '.join(labels)}")
            print(body)
        return True

    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    repo = _github_repo(cfg)
    if repo:
        cmd += ["--repo", repo]
    for label in labels:
        cmd += ["--label", label]

    result = subprocess.run(cmd, capture_output=True, text=True, env=_github_env(cfg))
    if result.returncode != 0:
        if not quiet:
            print(f"  ❌ GitHub issue 创建失败：{result.stderr or result.stdout}")
        return False
    if not quiet:
        print(f"  ✅ GitHub issue 已创建：{result.stdout.strip()}")
    return True


def main():
    parser = argparse.ArgumentParser(description="导出 Badcase 脱敏快照并默认创建 GitHub issue")
    parser.add_argument("--dry-run", action="store_true", help="预览，不创建 issue、不写飞书")
    parser.add_argument("--quiet",   action="store_true", help="静默模式（定时任务用）")
    parser.add_argument("--upload-lark", action="store_true", help="兼容旧流程：上传 snapshot 到 Lark 附件字段，不创建 GitHub issue")
    args = parser.parse_args()

    cfg = load_config()
    export_cfg = cfg.get("badcase_export", {})

    if not export_cfg.get("enabled", False) and not args.dry_run:
        print("ℹ️  badcase_export.enabled=false，跳过导出。")
        print("   在 config.yaml 中设置 badcase_export.enabled: true 后生效")
        sys.exit(0)

    if not args.quiet:
        target = "Lark 附件" if args.upload_lark else "GitHub issue"
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}🔍 扫描飞书 Badcase 记录，目标：{target}...")

    records = fetch_badcases(require_snapshot_field=args.upload_lark)
    if not records:
        if not args.quiet:
            print("✅ 没有待处理的 badcase 记录")
        return

    salt = _load_salt(cfg)
    if not args.quiet:
        print(f"📋 发现 {len(records)} 条 badcase 记录\n")

    success = 0
    for record in records:
        rid = record.get("record_id", "unknown")
        snap = build_snapshot(record, salt)

        try:
            validate_snapshot(snap)
        except Exception as e:
            print(f"⛔ 记录 {rid} 脱敏协议校验失败，已跳过：{e}")
            continue

        if not args.quiet:
            status = snap["badcase"]["current_status"]
            expect = snap["badcase"]["vm_expected_result"]
            print(f"→ {rid}  状态：{status}  期望：{expect[:30]}")

        if not args.upload_lark:
            snapshot_path = save_snapshot_file(snap, cfg)
            if not args.quiet:
                print(f"  脱敏快照已保存：{snapshot_path}")

        ok = (
            upload_snapshot_to_lark(rid, snap, args.dry_run, args.quiet)
            if args.upload_lark else
            push_snapshot_to_github(snap, cfg, args.dry_run, args.quiet)
        )
        if ok:
            success += 1

    if not args.quiet:
        if args.dry_run:
            print(f"\n[dry-run] 完成，共 {len(records)} 条，未实际创建 issue")
            log_manual_step(
                step_name="Badcase GitHub issue dry-run",
                status="skipped",
                input_summary=f"Badcase 数量: {len(records)}",
                output_summary="已生成脱敏快照预览，未创建 GitHub issue",
            )
        else:
            if args.upload_lark:
                print(f"\n完成，{success}/{len(records)} 条快照已上传至飞书附件")
            else:
                print(f"\n完成，{success}/{len(records)} 条 GitHub issue 已创建")

    if not args.dry_run:
        log_manual_step(
            step_name="Badcase GitHub issue 上报" if not args.upload_lark else "Badcase 快照上传",
            status="done" if success == len(records) else "failed",
            input_summary=f"Badcase 数量: {len(records)}",
            output_summary=f"成功: {success}/{len(records)}",
            step_type="action" if success == len(records) else "error",
        )


if __name__ == "__main__":
    main()
