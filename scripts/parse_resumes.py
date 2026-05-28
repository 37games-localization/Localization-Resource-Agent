#!/usr/bin/env python3
"""
parse_resumes.py
================
用 LLM 解析简历 PDF，提取结构化数据写回飞书。

一次性运行，或按需对指定候选人重跑。
每份简历约 1000-2000 token，19份合计 < 0.1 美元。

用法：
    python3 scripts/parse_resumes.py                    # 全量（跳过已解析）
    python3 scripts/parse_resumes.py --force            # 全量强制重跑
    python3 scripts/parse_resumes.py --name "Kai Wichmann"
    python3 scripts/parse_resumes.py --record-id recXXX
    python3 scripts/parse_resumes.py --dry-run          # 只打印，不写飞书
"""

import sys
import json
import time
import argparse
import subprocess
import os
import re
from pathlib import Path
from datetime import datetime

import fitz  # pymupdf

# ── 配置（从 config.yaml 读取） ───────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_lark, get_llm_api_key, is_test_mode

_CFG       = load_config()
_LARK      = get_lark(_CFG)
BASE_TOKEN = _LARK.get("base_token", "")
TABLE_ID   = _LARK.get("resume_table_id", "")
PDF_CACHE  = Path.home() / ".loc-resume-cache"
PDF_CACHE.mkdir(exist_ok=True)

# 飞书字段 ID（固定，不会变）
FIELD_IDS = {
    "姓名":         "fldSAfsOJf",
    "简历":         "fld7W0W7e2",
    "解析字数":     "flduKRhgTV",
    "解析年限":     "flde0kTB3Z",
    "解析项目数":   "fldfpo5X1f",
    "解析知名实体": "fld3cWjCaA",
    "简历解析时间": "fldh8Ebrxl",
}

LLM_MODEL  = _CFG.get("llm", {}).get("model", "claude-sonnet-4-5-20250929")
LLM_PROMPT = """你是一个专业的游戏本地化简历解析助手。

请从以下简历文本中提取信息，只输出 JSON，不要有任何其他文字：

{
  "word_count": <游戏翻译实际字数（整数），把简历中所有明确写出字数的游戏翻译项目字数全部加总，如无则为 0>,
  "years": <游戏翻译从业年限（浮点数，保留1位小数），如无法判断则为 0>,
  "project_count": <游戏项目数量（整数），有名字的游戏项目才算，同一游戏不重复，如无则为 0>,
  "notable_entities": "<知名游戏/厂商/LSP名称，逗号分隔，如 World of Warcraft,Ubisoft,TransPerfect；如无则为空字符串>"
}

提取规则：
1. word_count：只统计明确写了字数的游戏翻译项目，把所有条目字数加总（如 WoW 500,000 + Mass Effect 400,000 = 900,000），不要估算，不要猜测
2. years：从「Full-time experience: N years」「从业N年」「XXXX-至今」等描述中提取，只算游戏相关经验
3. project_count：列出的有名字的游戏项目数量，计数单独的游戏作品
4. notable_entities：知名游戏（AAA/知名IP）、知名厂商（Ubisoft/Capcom/Blizzard等）、知名LSP（TransPerfect/RWS/Lionbridge/SIDE等）

简历文本：
---
{text}
---

只输出 JSON，不要解释。"""


# ── lark-cli 工具 ─────────────────────────────────────────────────────────────

def lark_cli(*args) -> dict:
    r = subprocess.run(
        ["lark-cli"] + list(args),
        capture_output=True, text=True
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "error": r.stdout + r.stderr}


def fetch_all_records() -> list[dict]:
    records = []
    page_token = None
    page = 0
    while True:
        page += 1
        args = [
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--as", "bot",
            "--format", "json",
            "--limit", "100",
        ]
        if page_token:
            args += ["--page-token", page_token]

        resp = lark_cli(*args)
        db = resp.get("data", {})
        field_names = db.get("fields", [])
        record_ids  = db.get("record_id_list", [])
        rows        = db.get("data", [])

        for rid, row in zip(record_ids, rows):
            fields = dict(zip(field_names, row))
            records.append({"record_id": rid, "fields": fields})

        print(f"  第{page}页：{len(record_ids)} 条，累计 {len(records)} 条")

        if not db.get("has_more"):
            break
        page_token = db.get("page_token")

    return records


def download_pdf(file_token: str) -> str:
    """下载简历 PDF，返回本地路径，失败返回空字符串"""
    cache_path = PDF_CACHE / f"{file_token}.pdf"
    if cache_path.exists():
        return str(cache_path)

    r = subprocess.run(
        ["lark-cli", "docs", "+media-download",
         "--token", file_token,
         "--output", str(cache_path),
         "--as", "bot"],
        capture_output=True, text=True
    )
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return str(cache_path)
    return ""


def extract_pdf_text(pdf_path: str) -> str:
    try:
        doc = fitz.open(pdf_path)
        return "\n".join(page.get_text() for page in doc)
    except Exception as e:
        return ""


# OpenClaw 代理配置
# apiKey 优先读环境变量 LOC_LLM_API_KEY，其次从 openclaw.json 自动读取
_PROXY_BASE_URL = _CFG.get("llm", {}).get("base_url", "https://ai-proxy.37wan.com/anthropic")
_LLM_MODEL_ID   = LLM_MODEL
_PROXY_API_KEY  = get_llm_api_key(_CFG)


def call_llm(text: str) -> dict | None:
    """调用 LLM 解析简历文本，返回结构化 dict"""
    prompt = LLM_PROMPT.replace("{text}", text[:8000])  # 截断防超长

    try:
        import anthropic
        client = anthropic.Anthropic(
            base_url=_PROXY_BASE_URL,
            api_key=_PROXY_API_KEY,
        )
        msg = client.messages.create(
            model=_LLM_MODEL_ID,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        # 提取 JSON
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        print(f"  ⚠️  LLM 返回非 JSON: {raw[:100]}")
    except Exception as e:
        print(f"  ⚠️  LLM 调用失败: {e}")
    return None


def write_parsed_fields(record_id: str, parsed: dict, dry_run: bool) -> bool:
    """把解析结果写回飞书"""
    now_ms = int(time.time() * 1000)

    values = {
        FIELD_IDS["解析字数"]:     parsed.get("word_count", 0) or 0,
        FIELD_IDS["解析年限"]:     parsed.get("years", 0) or 0,
        FIELD_IDS["解析项目数"]:   parsed.get("project_count", 0) or 0,
        FIELD_IDS["解析知名实体"]: parsed.get("notable_entities", "") or "",
        FIELD_IDS["简历解析时间"]: now_ms,
    }

    if dry_run:
        print(f"    [DRY-RUN] 写入: {json.dumps(values, ensure_ascii=False)[:120]}")
        return True

    resp = lark_cli(
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--record-id", record_id,
        "--as", "bot",
        "--json", json.dumps(values, ensure_ascii=False),
    )
    return resp.get("ok", False)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--force",      action="store_true", help="强制重跑（忽略已解析时间）")
    parser.add_argument("--name",       help="只处理该姓名")
    parser.add_argument("--record-id",  help="只处理该 record_id")
    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY-RUN 模式：不写入飞书\n")

    print("拉取飞书记录...")
    records = fetch_all_records()
    print(f"✅ 共 {len(records)} 条\n")

    # 过滤
    if args.record_id:
        records = [r for r in records if r["record_id"] == args.record_id]
    elif args.name:
        records = [r for r in records if args.name in str(r["fields"].get("姓名", ""))]

    ok_count = err_count = skip_count = 0

    for i, rec in enumerate(records, 1):
        rid    = rec["record_id"]
        fields = rec["fields"]
        name   = str(fields.get("姓名", rid))

        print(f"[{i}/{len(records)}] {name}")

        # 已解析且不强制重跑则跳过
        already_parsed = fields.get("简历解析时间") or fields.get(FIELD_IDS.get("简历解析时间", ""))
        if already_parsed and not args.force:
            print(f"  ⏭️  已有解析结果，跳过（--force 强制重跑）\n")
            skip_count += 1
            continue

        # 取简历附件
        resume = fields.get("简历") or []
        if not resume or not isinstance(resume, list):
            print(f"  ⚠️  无简历附件，跳过\n")
            skip_count += 1
            continue

        file_token = resume[0].get("file_token", "") if isinstance(resume[0], dict) else ""
        if not file_token:
            print(f"  ⚠️  file_token 为空，跳过\n")
            skip_count += 1
            continue

        # 下载 PDF
        pdf_path = download_pdf(file_token)
        if not pdf_path:
            print(f"  ❌  PDF 下载失败\n")
            err_count += 1
            continue

        pdf_text = extract_pdf_text(pdf_path)
        if not pdf_text.strip():
            print(f"  ❌  PDF 无法提取文本\n")
            err_count += 1
            continue

        print(f"  📄 PDF {len(pdf_text)} 字符，调用 LLM 解析...")

        # 将飞书字段也并入，补充 PDF 可能缺失的字数信息
        proj_field  = str(fields.get("项目经历", "") or "")
        other_field = str(fields.get("其他相关经验", "") or "")
        full_text   = pdf_text + "\n\n---飞书字段补充---\n" + proj_field + "\n" + other_field

        # LLM 解析
        parsed = call_llm(full_text)
        if not parsed:
            print(f"  ❌  LLM 解析失败\n")
            err_count += 1
            continue

        print(f"  ✅ 解析结果: 字数={parsed.get('word_count',0):,} "
              f"年限={parsed.get('years',0)} "
              f"项目数={parsed.get('project_count',0)} "
              f"知名实体={parsed.get('notable_entities','')[:60]}")

        # 写回飞书
        success = write_parsed_fields(rid, parsed, args.dry_run)
        if success:
            ok_count += 1
            print(f"  {'[DRY-RUN] ' if args.dry_run else ''}写入成功\n")
        else:
            err_count += 1
            print(f"  ❌ 写入飞书失败\n")

        time.sleep(0.5)

    print("=" * 60)
    print(f"完成：成功 {ok_count} | 跳过 {skip_count} | 失败 {err_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
