#!/usr/bin/env python3
"""
export_badcase_snapshots.py  (VM 侧)
=====================================
扫描飞书主表中标记了「是否Badcase=⚠️ 是」的候选人记录，
生成脱敏 JSON 快照，上传到飞书对应记录的「Badcase快照」附件字段。

VM 不需要任何 GitHub 权限。issue 由项目负责人那边集中开。

用法：
    python3 scripts/export_badcase_snapshots.py            # 正常导出
    python3 scripts/export_badcase_snapshots.py --dry-run  # 预览，不写飞书
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

# ── 常量 ─────────────────────────────────────────────────────────────────────
SKILL_ROOT   = Path(__file__).parent.parent
SNAPSHOT_VER = "1.0"

MAIN_BASE_TOKEN = ""
MAIN_TABLE_ID   = ""
FIELDS: dict[str, str] = {}


def _init_lark_refs():
    """Load current table and field IDs from config/lark-field-mapping.yaml."""
    global MAIN_BASE_TOKEN, MAIN_TABLE_ID, FIELDS
    MAIN_BASE_TOKEN, MAIN_TABLE_ID = table_ref("candidate")
    FIELDS = {
        "badcase": field_id("candidate", "candidate.badcase_flag"),
        "expected": field_id("candidate", "candidate.expected_result"),
        "snapshot": field_id("candidate", "candidate.badcase_snapshot"),
        "status": field_id("candidate", "candidate.status"),
        "language_pair": field_id("candidate", "candidate.language_pair"),
        "services": field_id("candidate", "candidate.services"),
        "score": field_id("candidate", "candidate.score"),
        "tier": field_id("candidate", "candidate.tier"),
        "ai_suggestion": field_id("candidate", "candidate.ai_suggestion"),
        "score_basis": field_id("candidate", "candidate.score_basis"),
    }

# 安全扫描模式
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

def _scan_secrets(obj, path="root") -> list[str]:
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


# ── 核心流程 ──────────────────────────────────────────────────────────────────

def fetch_badcases() -> list[dict]:
    _init_lark_refs()
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
    anon = _anon_id(rid, salt)
    run_log = _load_run_log(rid)

    return {
        "snapshot_version": SNAPSHOT_VER,
        "exported_at": _now_iso(),
        "source": {
            "skill": "loc-resume-screening",
            "record_id_hash": anon,
        },
        "badcase": {
            "vm_expected_result": _field_text(record, FIELDS["expected"]) or "(未填写)",
            "current_status": _field_text(record, FIELDS["status"]),
        },
        "resource": {
            "anonymous_id": anon,
            "language_pair": _field_text(record, FIELDS["language_pair"]),
            "services":      _field_text(record, FIELDS["services"]),
        },
        "assessment": {
            "ai_score":      _field_text(record, FIELDS["score"]),
            "score_grade":   _field_text(record, FIELDS["tier"]),
            "ai_suggestion": _field_text(record, FIELDS["ai_suggestion"]),
            "score_basis":   _field_text(record, FIELDS["score_basis"]),
        },
        "agent_run": run_log,
        "redaction": {
            "removed_fields": ["email", "phone", "name", "id_number", "bank_account"],
            "contains_raw_resume": False,
            "contains_contract_text": False,
            "contains_payment_info": False,
        }
    }


def upload_snapshot_to_lark(record_id: str, snap: dict, dry_run: bool, quiet: bool) -> bool:
    """把快照 JSON 写成临时文件，上传到飞书附件字段"""
    anon = snap["resource"]["anonymous_id"]
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
                "--filename", filename,
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


def main():
    parser = argparse.ArgumentParser(description="导出 Badcase 脱敏快照并上传至飞书附件")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写飞书")
    parser.add_argument("--quiet",   action="store_true", help="静默模式（定时任务用）")
    args = parser.parse_args()

    cfg = load_config()
    export_cfg = cfg.get("badcase_export", {})

    if not export_cfg.get("enabled", False) and not args.dry_run:
        print("ℹ️  badcase_export.enabled=false，跳过导出。")
        print("   在 config.yaml 中设置 badcase_export.enabled: true 后生效")
        sys.exit(0)

    if not args.quiet:
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}🔍 扫描飞书 Badcase 记录...")

    records = fetch_badcases()
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

        hits = _scan_secrets(snap)
        if hits:
            print(f"⛔ 记录 {rid} 安全扫描命中，已跳过：")
            for h in hits:
                print(f"   · {h}")
            continue

        if not args.quiet:
            status = snap["badcase"]["current_status"]
            expect = snap["badcase"]["vm_expected_result"]
            print(f"→ {rid}  状态：{status}  期望：{expect[:30]}")

        ok = upload_snapshot_to_lark(rid, snap, args.dry_run, args.quiet)
        if ok:
            success += 1

    if not args.quiet:
        if args.dry_run:
            print(f"\n[dry-run] 完成，共 {len(records)} 条，未实际上传")
            log_manual_step(
                step_name="Badcase 快照 dry-run",
                status="skipped",
                input_summary=f"Badcase 数量: {len(records)}",
                output_summary="已生成脱敏快照预览，未上传附件",
            )
        else:
            print(f"\n🎉 完成，{success}/{len(records)} 条快照已上传至飞书附件")
            if success > 0:
                print("   项目负责人可运行 push_badcase_issues.py 从飞书读取并开 GitHub issue")

    if not args.dry_run:
        log_manual_step(
            step_name="Badcase 快照上传",
            status="done" if success == len(records) else "failed",
            input_summary=f"Badcase 数量: {len(records)}",
            output_summary=f"上传成功: {success}/{len(records)}",
            step_type="action" if success == len(records) else "error",
        )


if __name__ == "__main__":
    main()
