#!/usr/bin/env python3
"""
rescore_and_write.py
====================
从飞书简历收集表拉全量记录 → 用 V2 引擎确定性重算 → 批量写回

AI 彻底退出评分和写入环节，只做最后的「点评」文字生成。
每步计算结果打印到终端，方便核查。

用法：
    python rescore_and_write.py [--dry-run] [--record-id recXXX] [--limit N]

    --dry-run      只打印结果，不写飞书
    --record-id    只处理指定 record_id
    --limit        只处理前 N 条（默认全量）
"""

import sys
import json
import time
import argparse
import subprocess
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────────────────────────────────
# 引擎与当前脚本同目录（skill 自包含）
ENGINE_DIR = Path(__file__).parent
sys.path.insert(0, str(ENGINE_DIR))

from resume_screening_engine_v2 import ResumeScreeningEngineV2

# ── 从 config.yaml 读取配置 ───────────────────────────────────────────────────
from config_loader import load_config, get_lark
from field_resolver import field_id_or
from lark_cli_utils import normalize_record_list_data, run_lark_cli_json
from manual_trace import log_manual_step

_CFG       = load_config()
_LARK      = get_lark(_CFG)
BASE_TOKEN = _LARK.get("base_token", "")
TABLE_ID   = _LARK.get("resume_table_id", "")

# 写回字段优先使用字段映射，避免迁移表中同名公式字段不可写。
FIELD_SCORE         = field_id_or("candidate", "candidate.score", "总分")
FIELD_TIER          = field_id_or("candidate", "candidate.tier", "初始评级")
FIELD_SCORE_BASIS   = field_id_or("candidate", "candidate.score_basis", "评分依据")
FIELD_AI_SUGGEST    = field_id_or("candidate", "candidate.ai_suggestion", "AI建议")
FIELD_VALID         = field_id_or("candidate", "candidate.valid_resume", "有效简历")

# 「有效简历」判定关键词
GAME_KEYWORDS = [
    "游戏", "game", "gaming", "rpg", "moba", "mmorpg", "tcg", "lqa",
    "手游", "端游", "主机", "steam", "nintendo", "playstation", "xbox",
    "unity", "unreal", "本地化", "localization",
]

# ── 语言对标准化映射（飞书表里的中文描述 → engine 格式）────────────────────
LANG_PAIR_MAP = {
    "简中>英语":                     "zh-CN>en",
    "简中>英文":                     "zh-CN>en",
    "Simplified Chinese to English": "zh-CN>en",
    "中文>英语":                     "zh-CN>en",
    "简中>日语":                     "zh-CN>ja",
    "简中>韩语":                     "zh-CN>ko",
    "简中>越南语":                   "zh-CN>vi",
    "简中>泰语":                     "zh-CN>th",
    "简中>印尼语":                   "zh-CN>id",
    "简中>马来语":                   "zh-CN>ms",
    "简中>阿拉伯语":                 "zh-CN>ar",
    "英语>印尼语":                   "en>id",
    "English to Indonesian":         "en>id",
    "英语>俄语":                     "en>ru",
    "English to Russian":            "en>ru",
    "英语>德语":                     "en>de",
    "English to German":             "en>de",
    "英语>法语":                     "en>fr",
    "English to French":             "en>fr",
    "英语>意大利语":                 "en>it",
    "English to Italian":            "en>it",
    "英语>西班牙语":                 "en>es-LA",
    "English to Spanish":            "en>es-LA",
    "英语>葡萄牙语":                 "en>pt-BR",
    "English to Portuguese":         "en>pt-BR",
    "英语>波兰语":                   "en>pl",
    "English to Polish":             "en>pl",
    "英语>荷兰语":                   "en>nl",
    "English to Dutch":              "en>nl",
    "英语>土耳其语":                 "en>tr",
    "English to Turkish":            "en>tr",
    "英语>马来语":                   "en>ms",
    "English to Malay":              "en>ms",
    "英语>阿拉伯语":                 "en>ar",
    "English to Arabic":             "en>ar",
}

# 报价商议空间标准化
FLEX_MAP = {
    "可商议":                        "可商议",
    "Flexible 可商议":               "可商议",
    "有较大商议空间":                "有较大商议空间",
    "Very flexible 有较大商议空间":  "有较大商议空间",
    "有一些商议空间":                "有一些商议空间",
    "Somewhat flexible 有一些商议空间": "有一些商议空间",
    "固定":                          "固定",
    "Fixed 固定报价":                "固定",
    "未知":                          "未知",
}


# ── lark-cli 封装 ─────────────────────────────────────────────────────────────

def lark_cli(*args):
    """调用 lark-cli，返回解析后的 JSON（或抛出异常）"""
    return run_lark_cli_json(*args)


def fetch_all_records():
    """分页拉取所有记录，返回 list[dict(record_id, fields{name->value})]"""
    records = []
    page_token = None
    page = 1
    while True:
        args = [
            "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--format", "json",
            "--limit", "100",
        ]
        if page_token:
            args += ["--page-token", page_token]

        resp = lark_cli(*args)
        db = resp.get("data", {})

        page_records = normalize_record_list_data(db)
        records.extend(page_records)

        print(f"  第{page}页：获取 {len(page_records)} 条，累计 {len(records)} 条")

        has_more   = db.get("has_more", False)
        next_token = db.get("page_token")
        if not has_more or not next_token:
            break
        page_token = next_token
        page += 1
        time.sleep(0.3)
    return records


def write_record(record_id: str, fields: dict, dry_run: bool):
    """写回单条记录"""
    if dry_run:
        score = fields.get(FIELD_SCORE)
        tier  = fields.get(FIELD_TIER)
        print(f"    [DRY-RUN] record={record_id}  {FIELD_SCORE}={score}  {FIELD_TIER}={tier}")
        return

    payload = json.dumps(fields, ensure_ascii=False)
    lark_cli(
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--record-id", record_id,
        "--json", payload,
    )


# ── PDF 解析 ──────────────────────────────────────────────────────────────────

PDF_CACHE_DIR = Path.home() / ".loc-resume-cache"

def extract_pdf_text(file_token: str, candidate_name: str, record_id: str = "") -> str:
    """
    下载飞书附件简历 PDF 并提取全文。
    使用本地缓存，同一 file_token 不重复下载。
    """
    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = PDF_CACHE_DIR / f"{file_token}.pdf"

    # 优先用缓存
    if not cache_path.exists():
        try:
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
            else:
                cmd = [
                    "lark-cli", "api", "GET",
                    f"/drive/v1/medias/{file_token}/download",
                    "--format", "json",
                ]
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PDF_CACHE_DIR))
            import json as _json
            meta = _json.loads(r.stdout) if r.returncode == 0 else {}
            downloaded = (((meta.get("data") or {}).get("downloaded")) or [])
            saved = ""
            if downloaded:
                saved = downloaded[0].get("saved_path", "")
            if not saved:
                saved = meta.get("saved_path", "")
            if saved and Path(saved).exists():
                if Path(saved) != cache_path:
                    Path(saved).rename(cache_path)
            else:
                return ""  # 下载失败
        except Exception as e:
            print(f"    ⚠️  PDF 下载失败 ({candidate_name}): {e}")
            return ""

    # 提取文本
    try:
        import fitz
        doc = fitz.open(str(cache_path))
        text = "".join(page.get_text() for page in doc)
        return text
    except ImportError:
        print(f"    ⚠️  未安装 pymupdf，跳过 PDF 解析")
        return ""
    except Exception as e:
        print(f"    ⚠️  PDF 解析失败 ({candidate_name}): {e}")
        return ""


    """从各种格式中提取 float，失败返回 None"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_lang_pair(raw):
    """从飞书多选格式中提取并标准化语言对"""
    if not raw:
        return None

    # 多选返回 list
    if isinstance(raw, list):
        raw = raw[0] if raw else ""

    raw = str(raw).strip()

    # 直接命中映射
    if raw in LANG_PAIR_MAP:
        return LANG_PAIR_MAP[raw]

    # 尝试去掉括号内容再匹配
    import re
    clean = re.sub(r"\(.*?\)", "", raw).strip()
    if clean in LANG_PAIR_MAP:
        return LANG_PAIR_MAP[clean]

    # 尝试模糊匹配
    raw_lower = raw.lower()
    for key, val in LANG_PAIR_MAP.items():
        if key.lower() in raw_lower or raw_lower in key.lower():
            return val

    # 已经是标准格式
    import re
    if re.match(r"(zh-CN|en|ja|ko|vi|th|id|ms|ar|de|fr|it|es-LA|pt-BR|pl|nl|tr)>", raw):
        return raw

    return raw  # 返回原值让 engine 报错，更好追踪


def extract_float(val):
    """从各种格式中提取 float，失败返回 None"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_flex(raw):
    """标准化报价商议空间"""
    if not raw:
        return "未知"
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    raw = str(raw).strip()
    return FLEX_MAP.get(raw, raw)


def extract_text(val):
    """提取文本，多值合并"""
    if not val:
        return ""
    if isinstance(val, list):
        text = " ".join(str(v) for v in val)
    else:
        text = str(val)
    import re
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    return text


def build_candidate(rec: dict) -> dict:
    """把飞书 record fields 转成 engine 需要的 dict
    
    优先读「解析字数/年限/项目数/知名实体」这四个结构化字段（由 parse_resumes.py 写入）。
    若这四个字段有值，直接注入 candidate，引擎会优先使用；
    若无（简历未解析），降级为文本+PDF 拼合，作为 fallback。
    """
    f = rec.get("fields", {})

    # 读取 LLM 解析字段（有值则优先使用，包括值为 0 的情况）
    parsed_word_count   = f.get("解析字数")     # 可能是 0（int）或 None（未解析）
    parsed_years        = f.get("解析年限")     # 可能是 0.0 或 None
    parsed_project_cnt  = f.get("解析项目数")   # 可能是 0 或 None
    parsed_entities     = extract_text(f.get("解析知名实体") or "")

    cand = {
        "姓名":           extract_text(f.get("姓名")),
        "语言对":         extract_lang_pair(f.get("语言对")),
        "人工翻译单价":   extract_float(f.get("人工翻译单价")),
        "AIPE单价":       extract_float(f.get("AIPE单价")),
        "报价商议空间":   extract_flex(f.get("报价商议空间")),
        "提供的服务":     f.get("提供的服务", []),
        "项目经历":       extract_text(f.get("项目经历")),
        "其他相关经历":   extract_text(f.get("其他相关经验") or f.get("其他相关经历", "")),
        "熟悉的IP":       extract_text(f.get("熟悉的IP", "")),
        # LLM 解析字段（引擎优先读这些）
        "_parsed_word_count":  int(parsed_word_count)  if parsed_word_count  is not None else None,
        "_parsed_years":       float(parsed_years)      if parsed_years        is not None else None,
        "_parsed_project_cnt": int(parsed_project_cnt) if parsed_project_cnt is not None else None,
        "_parsed_entities":    parsed_entities,
    }
    return cand


# ── 结果格式化 ────────────────────────────────────────────────────────────────

def build_score_basis(result: dict, candidate: dict) -> str:
    """生成「评分依据」字段内容（确定性，无 LLM）"""
    pr = result["price_result"]
    er = result["experience_result"]
    bp = result["bonus_penalty"]

    lines = []
    lines.append(f"判定逻辑:")

    tier = result["final_tier"]
    base = result["base_tier"]
    if tier != base:
        lines.append(f"  基础档位 {base} → 微调后 {tier}")
    else:
        lines.append(f"  档位: {tier}（无档位变动）")

    lines.append("")
    lines.append(f"💰 价格维度: {pr['score']}/50")
    lines.append(f"  实际单价: {pr['adjusted_price']} USD")
    lines.append(f"  预期: ≤{pr.get('expected_price','?')} | 上限: ≤{pr.get('cap_price','?')}")
    lines.append(f"  ≤预期: {'✅' if pr['is_below_target'] else '❌'} | ≤上限: {'✅' if pr['is_below_max'] else '❌'}")

    lines.append("")
    lines.append(f"📚 资历维度: {er['total_score']}/50")
    lines.append(f"  主要关键词(字数): {er['primary_score']}/30")
    lines.append(f"    字数: {er.get('word_count', 0):,} / 500,000")
    lines.append(f"  次要关键词: {er['secondary_score']}/20")
    if er.get("notable_games"):
        lines.append(f"    知名游戏: {', '.join(er['notable_games'][:3])}")
    if er.get("notable_vendors"):
        lines.append(f"    知名厂商: {', '.join(er['notable_vendors'][:3])}")
    if er.get("lqa_items"):
        lines.append(f"    LQA/咨询: {', '.join(er['lqa_items'])}")

    if bp["bonus_reasons"] or bp["penalty_reasons"]:
        lines.append("")
        lines.append(f"⚖️ 微调: {bp['net_adjustment']:+d}")
        for r in bp["bonus_reasons"]:
            lines.append(f"  +  {r}")
        for r in bp["penalty_reasons"]:
            lines.append(f"  -  {r}")

    lines.append("")
    lines.append(f"最终档位: {tier} | 总分: {result['final_score']}/100")

    return "\n".join(lines)


def build_ai_suggest(result: dict) -> str:
    """生成「AI建议」字段（基于规则，确定性）"""
    tier = result["final_tier"]
    bp = result["bonus_penalty"]

    suggest_map = {
        "S": "优先录用",
        "A": "优先联系",
        "B": "备选考虑",
        "C": "暂不录用",
    }
    base = suggest_map.get(tier, "待定")

    caveats = []
    for r in bp["penalty_reasons"]:
        caveats.append(f"注意：{r}")

    if caveats:
        return base + "（" + "；".join(caveats) + "）"
    return base


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="重算简历评分并写回飞书")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入")
    parser.add_argument("--record-id", help="只处理指定 record_id")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条")
    args = parser.parse_args()

    dry_run = args.dry_run
    if dry_run:
        print("⚠️  DRY-RUN 模式：不会写入飞书\n")

    # 初始化引擎
    print("初始化引擎...")
    engine = ResumeScreeningEngineV2()
    print("✅ 引擎加载完成\n")

    # 拉取记录
    print("拉取飞书记录...")
    records = fetch_all_records()
    print(f"✅ 共 {len(records)} 条记录\n")

    # 过滤
    if args.record_id:
        records = [r for r in records if r.get("record_id") == args.record_id]
        print(f"过滤指定 record_id: {args.record_id}，剩余 {len(records)} 条\n")

    if args.limit > 0:
        records = records[:args.limit]
        print(f"限制前 {args.limit} 条\n")

    # 统计
    ok_count = 0
    skip_count = 0
    err_count = 0

    for i, rec in enumerate(records, 1):
        rid = rec.get("record_id", "?")
        fields = rec.get("fields", {})
        name = extract_text(fields.get("姓名") or fields.get("名字", ""))
        lang_raw = fields.get("语言对", "")

        print(f"[{i}/{len(records)}] {name or rid}  lang_raw={lang_raw}")

        # ── PDF 解析：下载简历提取全文，补充飞书表字段可能缺失的信息──
        resume_field = fields.get("简历", [])
        pdf_text = ""
        if resume_field and isinstance(resume_field, list) and resume_field[0]:
            file_token = resume_field[0].get("file_token", "") if isinstance(resume_field[0], dict) else ""
            if file_token:
                pdf_text = extract_pdf_text(file_token, name, rid)
                if pdf_text:
                    print(f"  📄 PDF 解析成功（{len(pdf_text)}字符）")
                else:
                    print(f"  ⚠️  PDF 无法解析，仅使用飞书表字段")

        # 将 PDF 内容合并进 fields，补充项目经历和其他经验
        if pdf_text:
            orig_proj  = extract_text(fields.get("项目经历", ""))
            orig_other = extract_text(fields.get("其他相关经验", ""))
            # 把 PDF 全文追加到字段内容后面，保留飞书表原有内容
            fields = dict(fields)  # 拷贝一份，不修改原始记录
            fields["项目经历"] = orig_proj + "\n" + pdf_text if orig_proj else pdf_text
            fields["其他相关经验"] = orig_other + "\n" + pdf_text if orig_other else pdf_text

        candidate = build_candidate({"record_id": rid, "fields": fields})

        if not candidate["语言对"]:
            print(f"  ⚠️  语言对为空，跳过\n")
            skip_count += 1
            continue

        try:
            result = engine.calculate_final_result(candidate)
        except Exception as e:
            print(f"  ❌ 引擎计算失败: {e}\n")
            err_count += 1
            continue

        final_score = result["final_score"]
        final_tier  = result["final_tier"]
        base_tier   = result["base_tier"]
        adj         = result["bonus_penalty"]["net_adjustment"]

        print(f"  价格: {result['price_result']['score']}/50  "
              f"资历: {result['experience_result']['total_score']}/50  "
              f"微调: {adj:+d}  "
              f"初始档: {base_tier} → 最终档: {final_tier}  "
              f"总分: {final_score}")

        score_basis = build_score_basis(result, candidate)
        ai_suggest  = build_ai_suggest(result)

        # ── 有效简历判定 ──────────────────────────────────────────
        services    = [str(s).lower() for s in (fields.get("提供的服务") or [])]
        project_txt = extract_text(fields.get("项目经历", "")).lower()
        other_txt   = extract_text(fields.get("其他相关经验", "")).lower()
        all_txt     = project_txt + " " + other_txt

        # 翻译经验：服务里有翻译/AIPE/校对/LQA，或项目文本里有翻译关键词
        TRANS_KEYWORDS = ["翻译", "translation", "translat", "aipe", "校对",
                          "proofreading", "lqa", "locali", "本地化", "interpret"]
        has_translation = (
            any(kw in s for s in services for kw in TRANS_KEYWORDS) or
            any(kw in all_txt for kw in TRANS_KEYWORDS)
        )
        # 游戏经验：文本里有游戏+翻译/本地化实质描述（两者共现，防止表单选项「Games」误匹配）
        GAME_EXP_KEYWORDS = [
            'game locali', 'game translat', 'locali', 'lqa', '\u6e38\u620f\u7ffb\u8bd1', '\u6e38\u620f\u672c\u5730\u5316',
            'game content', 'video game', 'mobile game', 'rpg', 'moba', 'mmorpg',
            'steam', 'playstation', 'nintendo', 'xbox', '\u624b\u6e38', '\u7aef\u6e38', '\u6e38\u620f\u9879\u76ee',
        ]
        has_game_exp = any(kw in all_txt for kw in GAME_EXP_KEYWORDS) or \
                       any(kw in s for s in services for kw in GAME_EXP_KEYWORDS)
        # 游戏从业经验：项目经历里有实际游戏翻译项目（有字数/项目名）
        # 游戏从业经验：项目经历 OR 其他经验里有游戏相关描述+数字（字数/项目数）
        import re as _re
        def _has_game_kw(txt):
            for kw in GAME_KEYWORDS:
                if len(kw) <= 4 and kw.isascii():
                    # 短英文关键词要词边界，防止 'games' 表单选项误匹配
                    if _re.search(r'(?<![\w])' + _re.escape(kw) + r'(?![\w])', txt, _re.IGNORECASE):
                        return True
                else:
                    if kw in txt:
                        return True
            return False

        has_game_work = (
            _has_game_kw(project_txt) and any(c.isdigit() for c in project_txt)
        ) or (
            _has_game_kw(other_txt) and any(c.isdigit() for c in other_txt)
        )

        is_valid = has_translation or has_game_exp or has_game_work
        valid_label = "是" if is_valid else "否"

        print(f"  有效简历判定: {'✅ 是' if is_valid else '❌ 否'} "
              f"（翻译经验:{has_translation} 游戏经验:{has_game_exp} 游戏从业:{has_game_work}）"
              f"{'  — 三项全无，建议忽略' if not is_valid else ''}")

        write_fields = {
            FIELD_SCORE:       final_score,
            FIELD_TIER:        final_tier,        # 单选字段传字符串
            FIELD_SCORE_BASIS: score_basis,
            FIELD_AI_SUGGEST:  ai_suggest,
            FIELD_VALID:       valid_label,
        }

        try:
            write_record(rid, write_fields, dry_run)
            if dry_run:
                print(f"  ✅ DRY-RUN 预览完成（未写入飞书）\n")
                log_manual_step(
                    step_name="评分重算 dry-run",
                    status="skipped",
                    candidate_name=name,
                    candidate_record_id=rid,
                    input_summary=f"语言对: {candidate['语言对']}",
                    output_summary=f"总分={final_score}, 档位={final_tier}, 有效简历={valid_label}",
                )
            else:
                print(f"  ✅ 写入成功\n")
                log_manual_step(
                    step_name="评分重算写回",
                    status="done",
                    candidate_name=name,
                    candidate_record_id=rid,
                    input_summary=f"语言对: {candidate['语言对']}",
                    output_summary=f"总分={final_score}, 档位={final_tier}, 有效简历={valid_label}",
                )
            ok_count += 1
        except Exception as e:
            print(f"  ❌ 写入失败: {e}\n")
            log_manual_step(
                step_name="评分重算失败",
                status="failed",
                candidate_name=name,
                candidate_record_id=rid,
                input_summary=f"语言对: {candidate.get('语言对', '')}",
                output_summary=str(e),
                step_type="error",
            )
            err_count += 1

        time.sleep(0.3)   # 飞书限流保护

    # 汇总
    print("=" * 60)
    print(f"完成：成功 {ok_count} | 跳过 {skip_count} | 失败 {err_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
