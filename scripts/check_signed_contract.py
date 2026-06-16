#!/usr/bin/env python3
"""
check_signed_contract.py
========================
VM 收到资源商签字合同后，将文件路径/URL 告知 agent，执行核查并更新飞书状态。

用法：
    # 指定本地文件路径
    python3 scripts/check_signed_contract.py --name "测试候选人B" --file ~/Downloads/contract.pdf

    # 指定多个文件（如合同+签名页分开）
    python3 scripts/check_signed_contract.py --name "测试候选人B" --file a.pdf --file b.jpg

    # 只核查不更新飞书
    python3 scripts/check_signed_contract.py --name "测试候选人B" --file contract.pdf --dry-run

    # 跳过确认直接更新

核查内容：
    1. 文件格式是否为 PDF 或图片
    2. 视觉模型判断是否有手写签名 + 日期填写
    3. 关键信息一致性（从飞书合同信息表读取，对比文件内容）
    4. VM 确认 → 更新飞书招募状态 → ✅ 合同已签署

后续扩展：
    IMAP 权限开通后，--file 参数改为可选，优先从邮箱自动拉取附件。
"""

import sys
import re
import json
import base64
import argparse
import subprocess
import shutil
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_smtp, get_lark, get_paths, is_test_mode, get_test_email, get_table_ref
from field_resolver import field_id_or
from lark_cli_utils import normalize_record_list_data, run_lark_cli_json
from manual_trace import log_manual_step

_CFG = load_config()

# ── 配置 ──────────────────────────────────────────────────────────────────────
MAIN_BASE_TOKEN, TABLE_ID_MAIN = get_table_ref(_CFG, "candidate")          # 简历收集主表
CONTRACT_BASE_TOKEN, TABLE_ID_CONTRACT = get_table_ref(_CFG, "contract_info")  # 合同信息收集表

# 飞书字段 ID（主表）
FLD_NAME   = field_id_or("candidate", "candidate.name", "fldSAfsOJf")
FLD_EMAIL  = field_id_or("candidate", "candidate.email", "fldWf5X8NR")
FLD_STATUS = field_id_or("candidate", "candidate.status", "fldfp6Pn7l")

# 合同信息表关键字段 ID（用于一致性核查）
FLD_C_NAME     = field_id_or("contract_info", "contract.name", "fld2JEyq9H")
FLD_C_EMAIL    = field_id_or("contract_info", "contract.email", "fldYELKkKa")
FLD_C_ID_NO    = field_id_or("contract_info", "contract.id_number", "fld3hdHuVd")
FLD_C_BANK     = field_id_or("contract_info", "contract.bank_account_number", "fld7CGT1GH")
FLD_C_ADDRESS  = field_id_or("contract_info", "contract.address", "fld8P0lZhg")
FLD_C_BANK_NAME = field_id_or("contract_info", "contract.bank_account_name", "fldvZMzuk3")
FLD_C_SWIFT    = field_id_or("contract_info", "contract.swift", "fld4ENGLJM")
FLD_C_PROGRESS = field_id_or("contract_info", "contract.progress", "fldtXTkTTi")

# 本地归档目录
ARCHIVE_DIR = Path(get_paths(_CFG).get("contract_output", "~/Documents/loc-contracts/output/")) / "signed"

# 支持的格式
VALID_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".webp"}

# ── lark-cli ──────────────────────────────────────────────────────────────────
def lark_cli(*args):
    resp = run_lark_cli_json(*args)
    if not isinstance(resp, dict):
        raise RuntimeError(f"lark-cli 返回非 JSON:\n{str(resp)[:200]}")
    return resp

def extract_text(val):
    if not val:
        return ""
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

def fetch_records(base_token, table_id):
    records = []
    page_token = None
    while True:
        args = ["base", "+record-list",
                "--base-token", base_token,
                "--table-id", table_id,
                "--format", "json", "--limit", "100"]
        if page_token:
            args += ["--page-token", page_token]
        resp = lark_cli(*args)
        db = resp["data"]
        records.extend(normalize_record_list_data(db))
        if not db.get("has_more") or not db.get("page_token"):
            break
        page_token = db["page_token"]
    return records

def update_record(base_token, table_id, record_id, fields: dict):
    payload = json.dumps(fields, ensure_ascii=False)
    resp = lark_cli("base", "+record-upsert",
                    "--base-token", base_token,
                    "--table-id", table_id,
                    "--record-id", record_id,
                    "--json", payload)
    if not resp.get("ok"):
        raise RuntimeError(f"写回失败: {resp.get('error')}")

# ── 格式核查 ──────────────────────────────────────────────────────────────────
def check_format(file_path: Path) -> tuple[bool, str]:
    ext = file_path.suffix.lower()
    if ext in VALID_EXTS:
        size_kb = file_path.stat().st_size // 1024
        return True, f"✅ 格式正常（{ext}，{size_kb} KB）"
    return False, f"❌ 不支持的格式：{ext}（支持：PDF / JPG / PNG / TIFF / HEIC）"

# ── 视觉核查 ──────────────────────────────────────────────────────────────────
def analyze_with_vision(file_path: Path) -> dict:
    """
    用 pymupdf 提取 PDF 签名页（最后两页）为图片，供 agent 调用 image tool 分析。
    图片类型直接返回路径。
    返回 {status, img_paths, total_pages} 或 {status, note}
    """
    ext = file_path.suffix.lower()
    img_paths = []

    if ext == ".pdf":
        try:
            import fitz
            doc   = fitz.open(str(file_path))
            total = len(doc)
            # 取最后两页（签名页通常在最后）
            pages = list(range(max(0, total - 2), total))
            for i in pages:
                page = doc[i]
                pix  = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                tmp_dir = Path(tempfile.gettempdir()) / "loc-resume-contract-vision"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                out  = tmp_dir / f".tmp_{file_path.stem}_p{i+1}.png"
                pix.save(str(out))
                img_paths.append(out)
            return {"status": "ok", "img_paths": img_paths, "total_pages": total}
        except ImportError:
            return {"status": "unclear",
                    "note": "未安装 pymupdf（pip3 install pymupdf），无法解析 PDF",
                    "img_paths": []}
        except Exception as e:
            return {"status": "error", "note": str(e), "img_paths": []}
    else:
        # 图片直接使用
        return {"status": "ok", "img_paths": [file_path], "total_pages": 1}

# ── 一致性核查 ────────────────────────────────────────────────────────────────
def fetch_contract_info(candidate_name: str) -> dict | None:
    """从合同信息收集表找到对应记录"""
    records = fetch_records(CONTRACT_BASE_TOKEN, TABLE_ID_CONTRACT)
    name_lower = candidate_name.lower()
    for r in records:
        name = extract_text(r["fields"].get(FLD_C_NAME))
        if name_lower in name.lower():
            return {
                "record_id": r["record_id"],
                "name":      name,
                "email":     extract_text(r["fields"].get(FLD_C_EMAIL)),
                "id_no":     extract_text(r["fields"].get(FLD_C_ID_NO)),
                "bank":      extract_text(r["fields"].get(FLD_C_BANK)),
                "address":   extract_text(r["fields"].get(FLD_C_ADDRESS)),
                "bank_name": extract_text(r["fields"].get(FLD_C_BANK_NAME)),
                "swift":     extract_text(r["fields"].get(FLD_C_SWIFT)),
            }
    return None


def normalize_for_compare(text: str) -> str:
    """Normalize text for robust contract field matching."""
    return re.sub(r"[\s,，.。:：;；/\\-]+", "", (text or "").lower())


def contains_expected(text: str, expected: str) -> bool:
    if not expected:
        return True
    return normalize_for_compare(expected) in normalize_for_compare(text)


def extract_file_text(file_path: Path) -> str:
    """Extract text from PDF for field-level diff checks."""
    if file_path.suffix.lower() != ".pdf":
        return ""
    try:
        import fitz
        doc = fitz.open(str(file_path))
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def compare_contract_text(text: str, contract_info: dict | None) -> list[tuple[str, str]]:
    """Return mismatched key fields found in signed contract text."""
    if not contract_info or not text:
        return []
    checks = [
        ("姓名", contract_info.get("name", "")),
        ("邮箱", contract_info.get("email", "")),
        ("证件号", contract_info.get("id_no", "")),
        ("银行账号", contract_info.get("bank", "")),
        ("地址", contract_info.get("address", "")),
        ("账户名", contract_info.get("bank_name", "")),
        ("SWIFT", contract_info.get("swift", "")),
    ]
    return [(label, value) for label, value in checks if value and not contains_expected(text, value)]

# ── 归档 ─────────────────────────────────────────────────────────────────────
def archive_file(src: Path, candidate_name: str) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    today    = datetime.now().strftime("%Y-%m-%d")
    safe     = re.sub(r'[^\w\-\u4e00-\u9fff.]', '_', candidate_name)
    dst      = ARCHIVE_DIR / f"{today}_{safe}_signed{src.suffix}"
    shutil.copy2(src, dst)
    return dst

# ── 主流程 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="合同签署核查脚本")
    parser.add_argument("--name",      help="资源商姓名（模糊匹配）")
    parser.add_argument("--record-id", help="飞书 record_id（精确）")
    parser.add_argument("--file",      action="append", dest="files",
                        metavar="PATH", help="合同文件路径（可多次指定）")
    parser.add_argument("--dry-run",   action="store_true", help="只核查不更新飞书")
    args = parser.parse_args()

    if not args.files:
        print("❌ 请用 --file 指定合同文件路径")
        print("   示例：--file ~/Downloads/contract.pdf")
        parser.print_help()
        sys.exit(1)

    # ── 1. 找飞书主表记录 ────────────────────────────────────────────────────
    print("拉取飞书记录...")
    records = fetch_records(MAIN_BASE_TOKEN, TABLE_ID_MAIN)

    target = None
    if args.record_id:
        for r in records:
            if r["record_id"] == args.record_id:
                target = r
                break
    elif args.name:
        matches = [r for r in records
                   if args.name.lower() in extract_text(r["fields"].get(FLD_NAME)).lower()]
        if len(matches) == 1:
            target = matches[0]
        elif len(matches) > 1:
            print(f"⚠️  找到 {len(matches)} 条，请用 --record-id 精确指定：")
            for r in matches:
                print(f"  {r['record_id']}  {extract_text(r['fields'].get(FLD_NAME))}")
            sys.exit(1)

    if not target:
        print(f"❌ 飞书中未找到：{args.name or args.record_id}")
        sys.exit(1)

    candidate_name  = extract_text(target["fields"].get(FLD_NAME))
    candidate_email = extract_text(target["fields"].get(FLD_EMAIL))
    print(f"✅ 候选人：{candidate_name}（{candidate_email}）\n")

    # ── 2. 从合同信息表拉关键字段（用于一致性提示）────────────────────────
    contract_info = fetch_contract_info(candidate_name)

    # ── 3. 核查文件 ──────────────────────────────────────────────────────────
    print("=" * 62)
    print("📋 合同核查报告")
    print("=" * 62)

    files        = [Path(f).expanduser().resolve() for f in args.files]
    all_ok       = True
    vision_queue = []   # 需要视觉分析的文件
    vision_imgs  = []   # 所有提取出的签名页图片路径
    archived     = []
    extracted_texts = []

    for f in files:
        print(f"\n▸ 文件：{f.name}")

        if not f.exists():
            print(f"  ❌ 文件不存在：{f}")
            all_ok = False
            continue

        # 格式检查
        fmt_ok, fmt_msg = check_format(f)
        print(f"  格式：{fmt_msg}")
        if not fmt_ok:
            all_ok = False
            continue

        # 归档
        if not args.dry_run:
            dst = archive_file(f, candidate_name)
            archived.append(dst)
            print(f"  归档：{dst}")
        else:
            archived.append(f)

        # 视觉分析准备
        vision_result = analyze_with_vision(f)
        vision_queue.append((f.name, vision_result))

        extracted_text = extract_file_text(f)
        if extracted_text:
            extracted_texts.append((f.name, extracted_text))

    # ── 4. 视觉分析结果 ─────────────────────────────────────────────────────
    print()
    print("─" * 62)
    print("🔍 签名核查（视觉模型）")
    print("─" * 62)

    for fname, vr in vision_queue:
        print(f"\n▸ {fname}")
        if vr["status"] == "error":
            print(f"  ❌ 分析失败：{vr['note']}")
            all_ok = False
        elif vr["status"] == "unclear":
            print(f"  ⚠️  {vr['note']}")
        elif vr["status"] == "ok":
            img_paths = vr.get("img_paths", [])
            total     = vr.get("total_pages", "?")
            print(f"  [PDF] 共 {total} 页，已提取签名页图片：")
            for p in img_paths:
                print(f"    → {p}")
            print(f"  ⏳ agent 将调用视觉模型分析…")
            # 存到 vision_imgs 供后续 agent 调用 image tool
            vision_imgs.extend(img_paths)

    # ── 5. 一致性提示 ────────────────────────────────────────────────────────
    print()
    print("─" * 62)
    print("📑 合同信息核对（请 VM 对照签回文件确认）")
    print("─" * 62)

    if contract_info:
        print(f"  姓名：      {contract_info['name']}")
        print(f"  邮箱：      {contract_info['email']}")
        print(f"  证件号：    {contract_info['id_no'] or '（未填）'}")
        print(f"  银行账号：  {contract_info['bank'] or '（未填）'}")
        print(f"  地址：      {contract_info.get('address') or '（未填）'}")
        print(f"  账户名：    {contract_info.get('bank_name') or '（未填）'}")
        print(f"  SWIFT：     {contract_info.get('swift') or '（未填）'}")
    else:
        print(f"  ⚠️  合同信息收集表中未找到「{candidate_name}」，请人工核对")

    print()
    print("─" * 62)
    print("🧾 自动字段 Diff（签回文件 vs Lark 合同信息）")
    print("─" * 62)
    if not extracted_texts:
        print("  ⚠️  未能抽取合同文本，无法自动 diff，请人工核对")
    elif not contract_info:
        print("  ⚠️  无 Lark 合同信息，无法自动 diff，请人工核对")
    else:
        any_mismatch = False
        for fname, text in extracted_texts:
            mismatches = compare_contract_text(text, contract_info)
            print(f"\n▸ {fname}")
            if not mismatches:
                print("  ✅ 关键字段均能在签回文件中匹配")
            else:
                any_mismatch = True
                all_ok = False
                print(f"  ❌ 发现 {len(mismatches)} 个关键字段不一致或未匹配：")
                for label, expected in mismatches:
                    print(f"    - {label}：Lark 期望「{expected}」")
        if any_mismatch:
            print("  结论：签回文件不应进入状态更新，请先确认是否拿错合同或合同信息表记录。")

    # ── 6. 核查摘要 ──────────────────────────────────────────────────────────
    print()
    print("=" * 62)
    print("核查摘要")
    print("=" * 62)
    print(f"  候选人：    {candidate_name}")
    print(f"  文件数量：  {len(files)}")
    print(f"  格式检查：  {'✅ 通过' if all_ok else '⚠️  有问题，见上方'}")
    print(f"  归档路径：  {ARCHIVE_DIR}")
    print()
    print("请 VM 确认：")
    print("  □ 签字页有手写签名（非打印）")
    print("  □ 合同日期已填写")
    print("  □ 姓名/证件号/银行信息与上方一致")

    if args.dry_run:
        print("\n[DRY-RUN] 不更新飞书状态")
        log_manual_step(
            step_name="签字合同核查 dry-run",
            status="skipped" if all_ok else "failed",
            candidate_name=candidate_name,
            candidate_record_id=target["record_id"],
            input_summary=f"文件数: {len(files)}",
            output_summary="格式/字段 diff 通过" if all_ok else "格式或字段 diff 未通过",
            step_type="action" if all_ok else "error",
        )
        return

    # ── 7. VM 确认 + 更新飞书 ────────────────────────────────────────────────
    print()
    ans = input("VM 确认无误，更新状态为「✅ 合同已签署」？[y/N] ").strip().lower()
    if ans != "y":
        print("❌ 已取消，状态未更新")
        sys.exit(0)

    print("\n更新飞书状态...")
    update_record(MAIN_BASE_TOKEN, TABLE_ID_MAIN, target["record_id"], {
        FLD_STATUS: "✅ 合同已签署",
    })
    print("✅ 招募状态已更新为「✅ 合同已签署」")
    log_manual_step(
        step_name="签字合同状态更新",
        status="done",
        candidate_name=candidate_name,
        candidate_record_id=target["record_id"],
        input_summary=f"文件数: {len(files)}",
        output_summary="状态=✅ 合同已签署",
        decision="confirmed",
    )
    print()
    print("下一步：")
    print("  1. VM 前往财务平台提交合同审批单 + 供应商信息入库单")
    print("  2. 完成后告知我，我将状态更新至「🔍 财务审批中」")


if __name__ == "__main__":
    main()
