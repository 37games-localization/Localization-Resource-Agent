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
    python3 scripts/parse_resumes.py --name "测试候选人A"
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
from field_resolver import field_id_or
from lark_cli_utils import normalize_record_list_data

_CFG       = load_config()
_LARK      = get_lark(_CFG)
BASE_TOKEN = _LARK.get("base_token", "")
TABLE_ID   = _LARK.get("resume_table_id", "")
PDF_CACHE  = Path.home() / ".loc-resume-cache"
PDF_CACHE.mkdir(exist_ok=True)

# 飞书字段 ID：优先使用 schema_validator.py 生成的映射；缺映射时回退旧生产表 ID。
FIELD_IDS = {
    "姓名":         field_id_or("candidate", "candidate.name", "fldSAfsOJf"),
    "简历":         field_id_or("candidate", "candidate.resume", "fld7W0W7e2"),
    "解析字数":     field_id_or("candidate", "candidate.parsed_word_count", "flduKRhgTV"),
    "解析年限":     field_id_or("candidate", "candidate.parsed_years", "flde0kTB3Z"),
    "解析项目数":   field_id_or("candidate", "candidate.parsed_project_count", "fldfpo5X1f"),
    "解析知名实体": field_id_or("candidate", "candidate.parsed_entities", "fld3cWjCaA"),
    "简历解析时间": field_id_or("candidate", "candidate.resume_parsed_at", "fldh8Ebrxl"),
    "招募状态":     field_id_or("candidate", "candidate.status", "fldfp6Pn7l"),
}

PARSE_DONE_STATUS = "🔍 初筛中"
PARSE_STATUS_FROM = {"", "📋 新投递", "📋 简历待筛选"}

LLM_MODEL  = _CFG.get("llm", {}).get("model", "claude-sonnet-4-5-20250929")
LLM_PROMPT = """你是一个专业的游戏本地化简历解析助手。

请从以下简历文本中提取信息，只输出 JSON，不要有任何其他文字：

{
  "word_count": <游戏翻译实际字数（整数），优先读取简历中明确写出的累计/总计游戏本地化字数；如果只有分项目字数，则加总所有明确项目字数；如无则为 0>,
  "years": <游戏翻译从业年限（浮点数，保留1位小数），如无法判断则为 0>,
  "project_count": <游戏项目数量（整数），有名字的游戏项目才算，同一游戏不重复，如无则为 0>,
  "notable_entities": "<知名游戏/厂商/LSP名称，逗号分隔，如 World of Warcraft,Ubisoft,TransPerfect；如无则为空字符串>"
}

提取规则：
1. word_count：只使用明确写出的字数证据，不要估算，不要猜测；如果简历写了「累计 500 万字以上」「5,000,000+ words」「over 5 million words」这类总量，视为有效字数；如果没有总量但有分项目字数，把所有条目加总（如 WoW 500,000 + Mass Effect 400,000 = 900,000）
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
        page_records = normalize_record_list_data(db)
        records.extend(page_records)

        print(f"  第{page}页：{len(page_records)} 条，累计 {len(records)} 条")

        if not db.get("has_more"):
            break
        page_token = db.get("page_token")

    return records


def extract_text(val) -> str:
    if not val:
        return ""
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("name") or "")
            else:
                parts.append(str(item))
        text = " ".join(p for p in parts if p).strip()
    else:
        text = str(val).strip()
    return re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)


def download_pdf(file_token: str, record_id: str = "") -> str:
    """下载简历 PDF，返回本地路径，失败返回空字符串"""
    cache_path = PDF_CACHE / f"{file_token}.pdf"
    if cache_path.exists():
        return str(cache_path)

    if record_id:
        cmd = [
            "lark-cli", "base", "+record-download-attachment",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--record-id", record_id,
            "--file-token", file_token,
            "--output", cache_path.name,
            "--overwrite",
            "--format", "json",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PDF_CACHE))
    else:
        r = subprocess.run(
            ["lark-cli", "docs", "+media-download",
             "--token", file_token,
             "--output", str(cache_path),
             "--as", "bot"],
            capture_output=True, text=True
        )
    if r.returncode == 0 and not cache_path.exists():
        try:
            payload = json.loads(r.stdout or "{}")
            downloaded = (((payload.get("data") or {}).get("downloaded")) or [])
            saved = downloaded[0].get("saved_path", "") if downloaded else payload.get("saved_path", "")
            if saved and Path(saved).exists():
                Path(saved).replace(cache_path)
        except Exception:
            pass
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return str(cache_path)
    return ""


def extract_pdf_text(pdf_path: str) -> str:
    try:
        doc = fitz.open(pdf_path)
        return "\n".join(page.get_text() for page in doc)
    except Exception as e:
        return ""


# LLM 代理配置：apiKey 必须在 config.yaml 或 LOC_LLM_API_KEY 显式配置。
_PROXY_BASE_URL = _CFG.get("llm", {}).get("base_url", "https://ai-proxy.37wan.com/anthropic")
_LLM_MODEL_ID   = LLM_MODEL
_PROXY_API_KEY  = get_llm_api_key(_CFG)
_LLM_PROVIDER   = _CFG.get("llm", {}).get("provider", "anthropic")


def _call_openai_compatible(prompt: str) -> str:
    import ssl
    import urllib.request
    import urllib.error
    try:
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ssl_context = ssl.create_default_context()

    base_url = _PROXY_BASE_URL.rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = json.dumps(
        {
            "model": _LLM_MODEL_ID,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {_PROXY_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=ssl_context) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"OpenAI-compatible LLM HTTP {e.code}: {detail}") from e
    return body["choices"][0]["message"]["content"].strip()


def call_llm(text: str) -> dict | None:
    """调用 LLM 解析简历文本，返回结构化 dict"""
    prompt = LLM_PROMPT.replace("{text}", text[:8000])  # 截断防超长

    try:
        if _LLM_PROVIDER in {"deepseek", "openai_compatible"}:
            raw = _call_openai_compatible(prompt)
        else:
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


def next_status_after_parse(current_status: str) -> str | None:
    """Return the standard next status after successful resume parsing."""
    status = extract_text(current_status)
    if status in PARSE_STATUS_FROM:
        return PARSE_DONE_STATUS
    return None


def write_parsed_fields(record_id: str, parsed: dict, dry_run: bool, current_status: str = "") -> bool:
    """把解析结果写回飞书"""
    now_ms = int(time.time() * 1000)

    values = {
        FIELD_IDS["解析字数"]:     parsed.get("word_count", 0) or 0,
        FIELD_IDS["解析年限"]:     parsed.get("years", 0) or 0,
        FIELD_IDS["解析项目数"]:   parsed.get("project_count", 0) or 0,
        FIELD_IDS["解析知名实体"]: parsed.get("notable_entities", "") or "",
        FIELD_IDS["简历解析时间"]: now_ms,
    }
    next_status = next_status_after_parse(current_status)
    if next_status:
        values[FIELD_IDS["招募状态"]] = next_status

    if dry_run:
        print(f"    [DRY-RUN] 写入: {json.dumps(values, ensure_ascii=False)[:160]}")
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
        records = [
            r for r in records
            if args.name in extract_text(
                r["fields"].get("姓名") or r["fields"].get(FIELD_IDS["姓名"]) or ""
            )
        ]

    ok_count = err_count = skip_count = 0

    for i, rec in enumerate(records, 1):
        rid    = rec["record_id"]
        fields = rec["fields"]
        name   = extract_text(fields.get("姓名") or fields.get(FIELD_IDS["姓名"]) or rid)

        print(f"[{i}/{len(records)}] {name}")

        # 已解析且不强制重跑则跳过
        already_parsed = fields.get("简历解析时间") or fields.get(FIELD_IDS.get("简历解析时间", ""))
        if already_parsed and not args.force:
            print(f"  ⏭️  已有解析结果，跳过（--force 强制重跑）\n")
            skip_count += 1
            continue

        # 取简历附件
        resume = fields.get("简历") or fields.get(FIELD_IDS["简历"]) or []
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
        pdf_path = download_pdf(file_token, rid)
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
        current_status = fields.get("招募状态") or fields.get(FIELD_IDS["招募状态"], "")
        success = write_parsed_fields(rid, parsed, args.dry_run, current_status=current_status)
        if success:
            ok_count += 1
            status_msg = next_status_after_parse(current_status)
            if status_msg:
                print(f"  招募状态 → {status_msg}")
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
