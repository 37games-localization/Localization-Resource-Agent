#!/usr/bin/env python3
"""
evaluate_resumes.py
===================
方向B 新脚本：LLM 一次性完成简历解析 + 评分，规则层只做价格硬校验。

价格标准默认读取包内规则；如配置了飞书「评分规则配置」表，则优先从飞书读取。
LLM 输出结构化 JSON，直接写回飞书候选人表。

用法：
    python3 scripts/evaluate_resumes.py                     # 全量（跳过已评分）
    python3 scripts/evaluate_resumes.py --force             # 全量强制重跑
    python3 scripts/evaluate_resumes.py --name "测试候选人A"
    python3 scripts/evaluate_resumes.py --record-id recXXX
    python3 scripts/evaluate_resumes.py --dry-run           # 只打印，不写飞书
    python3 scripts/evaluate_resumes.py --limit 5           # 只跑前5条
"""

import sys
import json
import time
import argparse
import subprocess
import re
from pathlib import Path
from datetime import datetime

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

sys.path.insert(0, str(Path(__file__).parent))
from config_loader import load_config, get_lark, get_llm_api_key
from lark_cli_utils import normalize_record_list_data

# ── 配置 ──────────────────────────────────────────────────────────────────────
_CFG        = load_config()
_LARK       = get_lark(_CFG)
BASE_TOKEN  = _LARK.get("base_token", "")
TABLE_ID    = _LARK.get("resume_table_id", "")
RULES_TABLE = _LARK.get("rules_table_id", "")
LOCAL_RULES_PATH = Path(__file__).parent.parent / "config" / "resume_screening_rules_v2.json"
PDF_CACHE   = Path.home() / ".loc-resume-cache"
PDF_CACHE.mkdir(exist_ok=True)

LLM_MODEL    = _CFG.get("llm", {}).get("model", "claude-sonnet-4-5-20250929")
PROXY_URL    = _CFG.get("llm", {}).get("base_url", "https://ai-proxy.37wan.com/anthropic")
PROXY_KEY    = get_llm_api_key(_CFG)

# 写回字段名（飞书表字段名，不是 field_id）
F_SCORE       = "总分"
F_TIER        = "初始评级"
F_BASIS       = "评分依据"
F_SUGGEST     = "AI建议"
F_COMMENT     = "点评"
F_VALID       = "有效简历"
F_WORD_COUNT  = "解析字数"
F_YEARS       = "解析年限"
F_PROJ_CNT    = "解析项目数"
F_ENTITIES    = "解析知名实体"
F_PARSE_TIME  = "简历解析时间"
F_WORD_SOURCE = "字数来源"
F_CONFIDENCE  = "评分置信度"

# ── PROMPT ────────────────────────────────────────────────────────────────────
# 评分逻辑固定在 prompt；价格数字运行时注入（从飞书表读）

SYSTEM_PROMPT = """你是一个专业的游戏本地化译者简历评审专家。
你的任务是根据提供的简历信息和评分规则，对候选人进行结构化评估。
只输出 JSON，不要有任何其他文字。JSON 必须严格符合要求的格式。"""

EVAL_PROMPT_TEMPLATE = """请根据以下信息对候选人进行评估，只输出 JSON。

## 候选人基本信息
- 姓名：{name}
- 语言对：{lang_pair}
- AIPE单价：{aipe_price}（USD/字）
- 人工翻译单价：{trans_price}（USD/字）
- 报价商议空间：{price_flex}
- 提供的服务：{services}

## 价格标准（该语言对）
- AIPE预期价：{aipe_target}（≤此价得满分）
- AIPE上限价：{aipe_max}（超过此价为不合格）
- 翻译预期价：{trans_target}
- 翻译上限价：{trans_max}

## 简历全文
{resume_text}

## 评分规则

### 一、价格维度（满分50分）
优先用 AIPE 单价评分；候选人无 AIPE 报价时改用人工翻译单价。

报价商议空间折算规则（先折算再评分）：
- "有较大商议空间" → 候选人报价 × 0.85
- "有一些商议空间" → 候选人报价 × 0.90
- "可商议" → 候选人报价 × 0.90
- "固定" 或 空 → 不折算

评分计算：
- 折算后单价 ≤ 预期价 → 50分（满分）
- 折算后单价 > 上限价 → 0分（不合格）
- 预期价 < 折算后单价 ≤ 上限价 → 25 + 25×(上限价 - 折算后单价)/(上限价 - 预期价)

### 二、资历维度（满分50分）

**主要关键词（30分）**：泛文娱领域翻译/校对/AIPE总字数
- 优先从简历中找明确写出字数的条目，全部加总
- 简历未明确写字数时，用从业年限估算：1年 ≈ 10万字（只用于兜底）
- 字数 ≥ 50万 → 30分；20-50万 → 线性插值；< 10万 → 0分
  公式（10万≤字数<50万）：30 × (字数 - 100000) / (500000 - 100000)

**次要关键词（20分）**：满足2项得20分，满足1项得10分，0项得0分
- 关键词1：有知名游戏项目经验 或 知名厂商/LSP合作经验
  （知名游戏：大型/知名IP游戏；知名厂商：Ubisoft/Capcom/米哈游/腾讯/网易等；知名LSP：TransPerfect/RWS/Lionbridge/SIDE等）
- 关键词2：有LQA、配音、本地化咨询等增值经验

### 三、加减分（总分微调，影响最终档位）
- +5：从业超过10年（游戏/文娱领域）
- +3：从业超过5年（游戏/文娱领域）
- +2：多品类游戏经验（≥4个游戏品类：RPG/FPS/MOBA/SLG/休闲/卡牌等）
- -2：游戏品类单一（仅1个品类）
- -3：价格超过上限（AIPE或翻译）

注意：加减分项之间可叠加，但+5和+3不同时生效（取最高一项）。

### 四、档位判定
初始分 = 价格维度 + 资历维度
最终分 = 初始分 + 加减分合计

| 最终分 | 档位 |
|--------|------|
| ≥ 90   | S    |
| 70-89  | A    |
| 50-69  | B    |
| < 50   | C    |

### 五、有效简历判定
满足以下任一项即为「是」：
- 有游戏翻译/本地化实际经验（项目经历里有具体游戏项目）
- 有翻译/校对/AIPE相关工作经验
- 有游戏行业从业经历（即使非翻译岗位）

## 输出格式（严格 JSON，不要有其他文字）

{{
  "word_count": <提取到的翻译总字数，整数，无则为0>,
  "years": <游戏/文娱从业年限，浮点数，无则为0>,
  "project_count": <有名字的游戏项目数量，整数，无则为0>,
  "notable_entities": "<知名游戏/厂商/LSP，逗号分隔，无则空字符串>",
  "price_score": <价格维度得分，数字，0-50>,
  "price_score_basis": "<价格维度计算过程，1-3句话，包含折算逻辑和结论>",
  "exp_score": <资历维度得分，数字，0-50>,
  "exp_score_basis": "<资历维度计算过程，说明字数来源/次要关键词满足情况>",
  "bonus": <加分合计，整数，≥0>,
  "penalty": <减分合计，整数，≥0，填正数>,
  "bonus_penalty_basis": "<加减分说明，列出每一项触发原因>",
  "initial_score": <价格分+资历分，数字>,
  "final_score": <initial_score + bonus - penalty，数字>,
  "tier": "<S/A/B/C>",
  "is_valid_resume": "<是/否>",
  "comment": "<词组格式，两行：第一行'✅ 优势：词组1 / 词组2 / 词组3'列出3-5个亮点（如：字数150万 / 知名IP Capcom / LQA经验 / 价格低于预期 / 多品类）；第二行'⚠️ 注意：词组1 / 词组2'列出1-3个风险点（如：年限仅2年 / 无LQA / 价格超上限 / 字数估算）。每个词组≤8字，不写完整句子，用\n分隔两行>",
  "action_note": "<VM操作建议，1-2句话，直接告诉VM下一步怎么做。根据档位和置信度判断：
S/A且置信度高中 → '建议优先联系，验证XXX（最重要的一个确认点）'
S/A且置信度低 → '建议联系后关注XXX（不确定因素）'
B → '建议先通过测试验证XXX再定，关注XXX'
C → '暂不建议合作，XXX不达标（具体原因）'
内容要具体指向候选人的实际情况，不写通用语。>",
  "word_count_source": "<字数来源，只填以下四选一：明确字数/年限估算/项目数估算/混合估算。明确字数=简历中有具体数字可直接加总；年限估算=无字数只能按年限推算；项目数估算=按项目数×均值估算；混合估算=部分明确+部分估算>",
  "confidence": "<评分置信度，只填以下三选一：高/中/低，建议复核。高=价格清晰+字数明确；中=有一项不确定；低=字数依赖估算或语言对未匹配或关键信息缺失>"
}}"""


# ── 飞书工具 ──────────────────────────────────────────────────────────────────

def lark_cli(*args) -> dict:
    r = subprocess.run(["lark-cli"] + list(args), capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": r.stdout + r.stderr}


def fetch_price_rules() -> dict:
    """读取价格标准，返回 {语言对标准化key: {aipe_target, aipe_max, trans_target, trans_max}}.

    默认使用包内规则，保证 VM 安装后不需要从 0 配规则表。
    如 config.local.yaml 配置了 lark.rules_table_id，则优先读取飞书规则表，
    便于后续团队替换或集中维护各语种单价范围。
    """
    if not BASE_TOKEN or not RULES_TABLE:
        return load_local_price_rules()
    resp = lark_cli(
        "api", "GET",
        f"/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{RULES_TABLE}/records",
        "--params", json.dumps({"page_size": 100}),
        "--format", "json",
    )
    rules = {}
    for item in resp.get("data", {}).get("items", []):
        f = item["fields"]
        def gv(k):
            v = f.get(k)
            if v is None: return None
            if isinstance(v, list): return v[0].get("text", "") if v else ""
            return v
        lang = str(gv("语言对") or "").strip()
        if not lang:
            continue
        # 标准化语言对 key（去空格，统一符号）
        key = lang.replace(" ", "").replace("＞", ">")
        rules[key] = {
            "aipe_target":  float(gv("AIPE预期价") or 0),
            "aipe_max":     float(gv("AIPE上限价") or 0),
            "trans_target": float(gv("翻译预期价") or 0),
            "trans_max":    float(gv("翻译上限价") or 0),
        }
    if not rules:
        print("⚠️  飞书评分规则表为空，回退使用包内默认规则")
        return load_local_price_rules()
    return rules


def load_local_price_rules() -> dict:
    """Load packaged price rules from config/resume_screening_rules_v2.json."""
    if not LOCAL_RULES_PATH.exists():
        raise RuntimeError(f"缺少包内评分规则文件：{LOCAL_RULES_PATH}")
    data = json.loads(LOCAL_RULES_PATH.read_text(encoding="utf-8"))
    price_rules = data.get("price_rules", {})
    aipe_rules = price_rules.get("aipe", {})
    trans_rules = price_rules.get("translation", {})
    keys = sorted(set(aipe_rules) | set(trans_rules))
    rules = {}
    for key in keys:
        aipe = aipe_rules.get(key, {})
        trans = trans_rules.get(key, {})
        rules[key] = {
            "aipe_target": float(aipe.get("target", 0.03)),
            "aipe_max": float(aipe.get("max", 0.04)),
            "trans_target": float(trans.get("target", aipe.get("target", 0.03))),
            "trans_max": float(trans.get("max", aipe.get("max", 0.04))),
        }
    return rules


def normalize_lang_pair(raw) -> str:
    """把飞书语言对字段值标准化为规则表的 key 格式
    规则表 key 格式：《源语言 > 目标语言》，如《英语 > 法语》《 zh-CN > 英语》
    """
    if not raw:
        return ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    s = str(raw).strip()

    # 英文语言名小写写法 → 规则表中文 key 映射
    EN_TO_CN = {
        # 源语言
        "simplified chinese": "zh-CN",
        "chinese": "zh-CN",
        "english": "英语",
        # 目标语言
        "english":     "英语",
        "japanese":    "日语",
        "korean":      "韩语",
        "german":      "德语",
        "french":      "法语",
        "italian":     "意大利语",
        "spanish":     "西班牙语(LA)",
        "portuguese":  "葡萄牙语(BR)",
        "russian":     "俄语",
        "polish":      "波兰语",
        "dutch":       "荷兰语",
        "turkish":     "土耳其语",
        "indonesian":  "印尼语",
        "malay":       "马来语",
        "vietnamese":  "越南语",
        "thai":        "泰语",
        "arabic":      "阿拉伯语",
    }

    # 优先处理已有《>》符号的格式（包括中英混合如《简中>英语 Simplified Chinese to English》）
    m2 = re.match(r'^(.+?)\s*>\s*(.+)$', s)
    if m2:
        src_raw = m2.group(1).strip()
        tgt_raw = m2.group(2).strip()
        # 取右侧第一个连续中文词（遇到空格+英文就截断，处理《英语 Simplified...》这种格式）
        tgt_cn_match = re.match(r'^([一-鿿a-zA-Z0-9\-_]+)', tgt_raw)
        if tgt_cn_match:
            tgt_raw = tgt_cn_match.group(1)
        tgt_raw = re.sub(r'[\(\uff08].*', '', tgt_raw).strip()
        # 源语言标准化
        SRC_CN = {"简中": "zh-CN", "中文": "zh-CN", "中": "zh-CN", "英": "英语", "英文": "英语"}
        src = SRC_CN.get(src_raw, EN_TO_CN.get(src_raw.lower(), src_raw))
        tgt = EN_TO_CN.get(tgt_raw.lower(), tgt_raw)
        return f"{src} > {tgt}"

    # 处理《X to Y》格式（纯英文无符号）
    m = re.match(r'^(.+?)\s+to\s+(.+)$', s, re.IGNORECASE)
    if m:
        src_raw = m.group(1).strip().lower()
        tgt_raw = m.group(2).strip().lower()
        src = EN_TO_CN.get(src_raw, m.group(1).strip())
        tgt = EN_TO_CN.get(tgt_raw, m.group(2).strip())
        return f"{src} > {tgt}"

    return s


def lookup_price_rule(lang_pair_raw, rules: dict) -> dict | None:
    """按语言对找到对应价格规则，找不到返回 None"""
    normalized = normalize_lang_pair(lang_pair_raw)
    # 精确匹配
    if normalized in rules:
        return rules[normalized]
    # 去空格再试
    key_ns = normalized.replace(" ", "")
    for k, v in rules.items():
        if k.replace(" ", "") == key_ns:
            return v
    # 模糊匹配：忽略括号内容（西班牙语(LA) vs 西班牙语）
    norm_base = re.sub(r'[\(\uff08（][^)）\uff09]*[)）\uff09]', '', normalized).strip()
    for k, v in rules.items():
        k_base = re.sub(r'[\(\uff08（][^)）\uff09]*[)）\uff09]', '', k).strip()
        if norm_base == k_base or norm_base.replace(" ", "") == k_base.replace(" ", ""):
            return v
    return None


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


def download_pdf(file_token: str, tmp_url: str = "") -> str:
    cache_path = PDF_CACHE / f"{file_token}.pdf"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return str(cache_path)

    # 最稳定路径： lark-cli api GET /drive/v1/medias/{token}/download
    # 会自动保存到当前目录，再移动到缓存
    try:
        r = subprocess.run(
            ["lark-cli", "api", "GET",
             f"/open-apis/drive/v1/medias/{file_token}/download",
             "--format", "json"],
            capture_output=True, text=True,
            cwd=str(PDF_CACHE)
        )
        resp = json.loads(r.stdout) if r.stdout.strip().startswith('{') else {}
        saved = resp.get("saved_path", "")
        if saved and Path(saved).exists() and Path(saved).stat().st_size > 0:
            Path(saved).rename(cache_path)
            return str(cache_path)
        # 也可能直接存到 cache 目录里
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return str(cache_path)
    except Exception as e:
        print(f"  ⚠️  PDF 下载异常: {e}")

    return ""


def extract_pdf_text(pdf_path: str) -> str:
    if not fitz:
        return ""
    try:
        doc = fitz.open(pdf_path)
        return "\n".join(page.get_text() for page in doc)
    except Exception:
        return ""


def extract_text(val) -> str:
    if not val:
        return ""
    if isinstance(val, list):
        parts = []
        for v in val:
            if isinstance(v, dict):
                parts.append(v.get("text", ""))
            else:
                parts.append(str(v))
        text = " ".join(parts)
    else:
        text = str(val)
    # 清理飞书 markdown 链接格式
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    return text.strip()


def write_record(record_id: str, fields: dict, dry_run: bool) -> bool:
    if dry_run:
        print(f"    [DRY-RUN] {json.dumps(fields, ensure_ascii=False)[:200]}")
        return True
    payload = json.dumps(fields, ensure_ascii=False)
    resp = lark_cli(
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--record-id", record_id,
        "--as", "bot",
        "--json", payload,
    )
    return resp.get("ok", False)


# ── LLM ───────────────────────────────────────────────────────────────────────

MAX_RETRIES = 3

LLM_PROVIDER = _CFG.get("llm", {}).get("provider", "anthropic")

def call_openai_compatible(prompt: str) -> str:
    import ssl
    import urllib.request
    import urllib.error
    try:
        import certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ssl_context = ssl.create_default_context()

    base_url = PROXY_URL.rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = json.dumps(
        {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {PROXY_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90, context=ssl_context) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:300]
        raise RuntimeError(f"OpenAI-compatible LLM HTTP {e.code}: {detail}") from e
    return body["choices"][0]["message"]["content"].strip()

def call_llm(prompt: str) -> dict | None:
    client = None
    if LLM_PROVIDER not in {"deepseek", "openai_compatible"}:
        import anthropic
        client = anthropic.Anthropic(base_url=PROXY_URL, api_key=PROXY_KEY)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if LLM_PROVIDER in {"deepseek", "openai_compatible"}:
                raw = call_openai_compatible(prompt)
            else:
                msg = client.messages.create(
                    model=LLM_MODEL,
                    max_tokens=2000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = msg.content[0].text.strip()
            raw = re.sub(r'^```[\w]*\n?', '', raw).strip()
            raw = re.sub(r'\n?```$', '', raw).strip()
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                result = json.loads(m.group())
                if attempt > 1:
                    print(f"  \u21ba  第{attempt}次重试成功")
                return result
            print(f"  ⚠️  [attempt {attempt}/{MAX_RETRIES}] 返回非 JSON: {raw[:80]}")
        except json.JSONDecodeError as e:
            print(f"  ⚠️  [attempt {attempt}/{MAX_RETRIES}] JSON 解析失败: {e}")
        except Exception as e:
            print(f"  ⚠️  [attempt {attempt}/{MAX_RETRIES}] 调用异常: {e}")
            break  # 网络错误不重试
        if attempt < MAX_RETRIES:
            time.sleep(1.5 * attempt)

    print(f"  ❌  重试 {MAX_RETRIES} 次均失败")
    return None


# ── 价格硬校验（T3：规则兜底层） ─────────────────────────────────────────────

def hard_validate_price(result: dict, price_rule: dict) -> list[str]:
    """
    检查 LLM 输出的价格分是否和规则一致，返回警告列表。
    不修改 LLM 的评分结果，只标注异常。
    """
    warnings = []
    aipe_max  = price_rule.get("aipe_max", 0)
    trans_max = price_rule.get("trans_max", 0)
    price_score = result.get("price_score", 0)

    # 如果价格超上限但 LLM 给了分，提示异常
    basis = result.get("price_score_basis", "")
    if "超过上限" in basis or "超出上限" in basis or "high" in basis.lower():
        if price_score > 0:
            warnings.append(f"⚠️ 价格超上限但 LLM 给了 {price_score} 分，请人工复核")
    return warnings


def clamp_final_score(result: dict) -> tuple[dict, float, bool]:
    """Cap final_score to 0-100 before writing to Lark."""
    raw_score = result.get("final_score", 0)
    try:
        raw_num = float(raw_score)
    except (TypeError, ValueError):
        raw_num = 0.0
    capped = max(0.0, min(100.0, raw_num))
    if capped.is_integer():
        capped_value = int(capped)
    else:
        capped_value = round(capped, 1)
    result["final_score"] = capped_value
    return result, raw_num, capped_value != raw_num


# ── 构建 prompt ───────────────────────────────────────────────────────────────

def build_prompt(rec: dict, price_rule: dict | None) -> str:
    f = rec["fields"]

    name       = extract_text(f.get("姓名"))
    lang_pair  = extract_text(f.get("语言对"))
    aipe_price = f.get("AIPE单价") or "未提供"
    trans_price= f.get("人工翻译单价") or "未提供"
    price_flex = extract_text(f.get("报价商议空间")) or "未知"
    services   = extract_text(f.get("提供的服务")) or "未知"

    if price_rule:
        aipe_target  = price_rule["aipe_target"]
        aipe_max     = price_rule["aipe_max"]
        trans_target = price_rule["trans_target"]
        trans_max    = price_rule["trans_max"]
    else:
        aipe_target = aipe_max = trans_target = trans_max = "未知（请根据候选人报价合理判断）"

    # 拼接简历文本：PDF全文 + 飞书关键字段补充
    pdf_text   = rec.get("_pdf_text", "")
    proj_text  = extract_text(f.get("项目经历"))
    other_text = extract_text(f.get("其他相关经验") or f.get("其他相关经历"))
    ip_text    = extract_text(f.get("熟悉的IP"))

    resume_parts = []
    if pdf_text:
        resume_parts.append(f"[简历PDF全文]\n{pdf_text[:6000]}")
    if proj_text:
        resume_parts.append(f"[项目经历（飞书表单）]\n{proj_text}")
    if other_text:
        resume_parts.append(f"[其他相关经验]\n{other_text}")
    if ip_text:
        resume_parts.append(f"[熟悉的IP]\n{ip_text}")
    resume_text = "\n\n".join(resume_parts) or "（无简历文本）"

    return EVAL_PROMPT_TEMPLATE.format(
        name=name,
        lang_pair=lang_pair,
        aipe_price=aipe_price,
        trans_price=trans_price,
        price_flex=price_flex,
        services=services,
        aipe_target=aipe_target,
        aipe_max=aipe_max,
        trans_target=trans_target,
        trans_max=trans_max,
        resume_text=resume_text,
    )


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--force",     action="store_true", help="强制重跑已评分记录")
    parser.add_argument("--name",      help="只处理该姓名")
    parser.add_argument("--record-id", help="只处理该 record_id")
    parser.add_argument("--limit",     type=int, help="只处理前N条")
    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY-RUN 模式：不写入飞书\n")

    # 读价格规则
    if BASE_TOKEN and RULES_TABLE:
        print("读取飞书价格规则配置...")
    else:
        print("读取包内默认价格规则配置...")
    price_rules = fetch_price_rules()
    print(f"✅ 已读取 {len(price_rules)} 条语言对价格规则\n")

    # 读候选人记录
    print("拉取飞书候选人记录...")
    records = fetch_all_records()
    print(f"✅ 共 {len(records)} 条\n")

    # 过滤
    if args.record_id:
        records = [r for r in records if r["record_id"] == args.record_id]
    elif args.name:
        records = [r for r in records if args.name in extract_text(r["fields"].get("姓名", ""))]
    if args.limit:
        records = records[:args.limit]

    ok_count = err_count = skip_count = 0

    for i, rec in enumerate(records, 1):
        rid    = rec["record_id"]
        fields = rec["fields"]
        name   = extract_text(fields.get("姓名")) or rid

        print(f"[{i}/{len(records)}] {name}")

        # 已评分且不强制重跑则跳过（用解析时间字段判断）
        if not args.force and fields.get(F_PARSE_TIME):
            print(f"  ⏭️  已有评分结果，跳过（--force 强制重跑）\n")
            skip_count += 1
            continue

        # 找价格规则
        lang_pair_raw = fields.get("语言对")
        price_rule = lookup_price_rule(lang_pair_raw, price_rules)
        if not price_rule:
            print(f"  ⚠️  找不到语言对「{extract_text(lang_pair_raw)}」的价格规则，继续（LLM 将自行判断）")

        # 下载 PDF
        resume_field = fields.get("简历") or []
        pdf_text = ""
        if resume_field and isinstance(resume_field, list):
            first = resume_field[0] if isinstance(resume_field[0], dict) else {}
            file_token = first.get("file_token", "")
            tmp_url    = first.get("tmp_url", "")
            if file_token:
                pdf_path = download_pdf(file_token, tmp_url)
                if pdf_path:
                    pdf_text = extract_pdf_text(pdf_path)
                    print(f"  📄 PDF {len(pdf_text)} 字符")
                else:
                    print(f"  ⚠️  PDF 下载失败，仅用飞书字段")
        rec["_pdf_text"] = pdf_text

        # 构建 prompt，调用 LLM
        prompt = build_prompt(rec, price_rule)
        print(f"  🤖 调用 LLM 评分...")
        result = call_llm(prompt)
        if not result:
            print(f"  ❌ LLM 返回失败\n")
            err_count += 1
            continue

        result, raw_final_score, score_was_capped = clamp_final_score(result)

        # 价格硬校验
        if price_rule:
            warnings = hard_validate_price(result, price_rule)
            for w in warnings:
                print(f"  {w}")

        # 打印摘要
        print(f"  ✅ 字数={result.get('word_count',0):,}  年限={result.get('years',0)}  "
              f"项目数={result.get('project_count',0)}  "
              f"价格分={result.get('price_score',0)}/50  资历分={result.get('exp_score',0)}/50  "
              f"加={result.get('bonus',0)} 减={result.get('penalty',0)}  "
              f"总分={result.get('final_score',0)}  档位={result.get('tier','?')}  "
              f"有效={result.get('is_valid_resume','?')}  "
              f"字数来源=[{result.get('word_count_source','?')}]  "
              f"置信度=[{result.get('confidence','?')}]")
        if score_was_capped:
            print(f"  ⚠️  LLM 原始总分 {raw_final_score:g}，按满分规则封顶为 {result.get('final_score',0)}")

        # 构建写回字段
        now_ms = int(time.time() * 1000)
        final_line = (
            f"最终：{result.get('initial_score',0)} + {result.get('bonus',0)} - {result.get('penalty',0)} = "
            f"{raw_final_score:g}分"
        )
        if score_was_capped:
            final_line += f"，按满分规则封顶为 {result.get('final_score',0)}分"
        final_line += f" → {result.get('tier','?')}档"
        basis_text = (
            f"【价格维度 {result.get('price_score',0)}/50】\n{result.get('price_score_basis','')}\n\n"
            f"【资历维度 {result.get('exp_score',0)}/50】\n{result.get('exp_score_basis','')}\n\n"
            f"【加减分 +{result.get('bonus',0)} -{result.get('penalty',0)}】\n{result.get('bonus_penalty_basis','')}\n\n"
            f"{final_line}"
        )

        write_fields = {
            F_SCORE:       result.get("final_score", 0),
            F_TIER:        result.get("tier", "C"),
            F_BASIS:       basis_text,
            F_SUGGEST:     result.get("comment", ""),
            F_COMMENT:     result.get("action_note", ""),
            F_VALID:       result.get("is_valid_resume", "否"),
            F_WORD_COUNT:  result.get("word_count", 0),
            F_YEARS:       result.get("years", 0),
            F_PROJ_CNT:    result.get("project_count", 0),
            F_ENTITIES:    result.get("notable_entities", ""),
            F_PARSE_TIME:  now_ms,
            F_WORD_SOURCE: result.get("word_count_source", "混合估算"),
            F_CONFIDENCE:  result.get("confidence", "中"),
        }

        success = write_record(rid, write_fields, args.dry_run)
        if success:
            ok_count += 1
            print(f"  {'[DRY-RUN] ' if args.dry_run else ''}写入成功\n")
        else:
            err_count += 1
            print(f"  ❌ 写入飞书失败\n")

        time.sleep(0.8)  # 限流保护

    print("=" * 60)
    print(f"完成：成功 {ok_count} | 跳过 {skip_count} | 失败 {err_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
