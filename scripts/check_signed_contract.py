#!/usr/bin/env python3
"""
check_signed_contract.py
========================
VM 收到资源商签字合同后，将文件路径/URL 告知 agent，执行核查并更新飞书状态。

用法：
    # 指定本地文件路径
    python3 scripts/check_signed_contract.py --name "宋赛楠" --file ~/Downloads/contract.pdf

    # 指定多个文件（如合同+签名页分开）
    python3 scripts/check_signed_contract.py --name "宋赛楠" --file a.pdf --file b.jpg

    # 只核查不更新飞书
    python3 scripts/check_signed_contract.py --name "宋赛楠" --file contract.pdf --dry-run

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
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_smtp, get_lark, get_paths, is_test_mode, get_test_email

_CFG = load_config()

# ── 配置 ──────────────────────────────────────────────────────────────────────
BASE_TOKEN        = get_lark(_CFG).get("base_token", "")
TABLE_ID_MAIN     = get_lark(_CFG).get("resume_table_id", "")      # 简历收集主表
TABLE_ID_CONTRACT = get_lark(_CFG).get("contract_table_id", "")    # 合同信息收集表

# 飞书字段 ID（主表）
FLD_NAME   = "fldSAfsOJf"
FLD_EMAIL  = "fldWf5X8NR"
FLD_STATUS = "fldfp6Pn7l"

# 合同信息表关键字段 ID（用于一致性核查）
FLD_C_NAME    = "fld2JEyq9H"   # 姓名（全名）
FLD_C_EMAIL   = "fldYELKkKa"   # 邮箱
FLD_C_ID_NO   = "fld3hdHuVd"   # 身份证/护照号
FLD_C_BANK    = "fld7CGT1GH"   # 银行账号
FLD_C_PROGRESS = "fldtXTkTTi"  # 合同进度

# 本地归档目录
ARCHIVE_DIR = Path(get_paths(_CFG).get("contract_output", "~/Documents/loc-contracts/output/")) / "signed"

# 支持的格式
VALID_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".webp"}

# ── lark-cli ──────────────────────────────────────────────────────────────────
def lark_cli(*args):
    r = subprocess.run(["lark-cli"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"lark-cli 失败:\n{r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"lark-cli 返回非 JSON:\n{r.stdout[:200]}")

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

def fetch_records(table_id):
    records = []
    page_token = None
    while True:
        args = ["base", "+record-list",
                "--base-token", BASE_TOKEN,
                "--table-id", table_id,
                "--format", "json", "--limit", "100"]
        if page_token:
            args += ["--page-token", page_token]
        resp = lark_cli(*args)
        db = resp["data"]
        field_ids  = db.get("field_id_list", db.get("fields", []))
        record_ids = db.get("record_id_list", [])
        rows       = db.get("data", [])
        for rid, row in zip(record_ids, rows):
            records.append({"record_id": rid, "fields": dict(zip(field_ids, row))})
        if not db.get("has_more") or not db.get("page_token"):
            break
        page_token = db["page_token"]
    return records

def update_record(table_id, record_id, fields: dict):
    payload = json.dumps(fields, ensure_ascii=False)
    resp = lark_cli("base", "+record-upsert",
                    "--base-token", BASE_TOKEN,
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
                out  = ARCHIVE_DIR / f".tmp_{file_path.stem}_p{i+1}.png"
                ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
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
    records = fetch_records(TABLE_ID_CONTRACT)
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
            }
    return None

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
    records = fetch_records(TABLE_ID_MAIN)

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
    else:
        print(f"  ⚠️  合同信息收集表中未找到「{candidate_name}」，请人工核对")

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
        return

    # ── 7. VM 确认 + 更新飞书 ────────────────────────────────────────────────
    print()
    ans = input("VM 确认无误，更新状态为「✅ 合同已签署」？[y/N] ").strip().lower()
    if ans != "y":
        print("❌ 已取消，状态未更新")
        sys.exit(0)

    print("\n更新飞书状态...")
    update_record(TABLE_ID_MAIN, target["record_id"], {
        FLD_STATUS: "✅ 合同已签署",
    })
    print("✅ 招募状态已更新为「✅ 合同已签署」")
    print()
    print("下一步：")
    print("  1. VM 前往财务平台提交合同审批单 + 供应商信息入库单")
    print("  2. 完成后告知我，我将状态更新至「🔍 财务审批中」")


if __name__ == "__main__":
    main()
