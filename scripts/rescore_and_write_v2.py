#!/usr/bin/env python3
"""
rescore_and_write_v2.py
=======================
rescore_and_write.py 的 v2 版本：接入 WorkflowEngine，实现：
  1. Agent 行动可视化（每步输入/输出实时展示）
  2. Human Decision 节点暂停-恢复（单条处理时支持交互确认）

与原版完全兼容，参数接口不变，新增：
  --interactive   启用 Human Decision 节点（批量时不建议开启）
  --no-lark-log   不写飞书流程日志（仅终端展示）

用法：
    # 批量重算（可视化，自动推进，行为与原版一致）
    python3 scripts/rescore_and_write_v2.py [--dry-run] [--limit N]

    # 单条处理 + 交互确认（先预览评分，你确认后再写入）
    python3 scripts/rescore_and_write_v2.py --record-id recXXX --interactive

    # 只看终端输出，不写飞书日志
    python3 scripts/rescore_and_write_v2.py --limit 3 --no-lark-log
"""

import sys
import json
import time
import re
import argparse
import subprocess
from pathlib import Path

ENGINE_DIR = Path(__file__).parent
sys.path.insert(0, str(ENGINE_DIR))

from resume_screening_engine_v2 import ResumeScreeningEngineV2
from config_loader import load_config, get_lark
from workflow_engine import WorkflowEngine, StepStatus

# ── 从原版复用配置和工具函数 ──────────────────────────────────────────────────
# （直接 import，保持单一来源）
from rescore_and_write import (
    BASE_TOKEN, TABLE_ID,
    FIELD_SCORE, FIELD_TIER, FIELD_SCORE_BASIS, FIELD_AI_SUGGEST, FIELD_VALID,
    GAME_KEYWORDS,
    LANG_PAIR_MAP, FLEX_MAP,
    lark_cli, fetch_all_records, write_record,
    extract_pdf_text, extract_lang_pair, extract_float, extract_flex,
    extract_text, build_candidate, build_score_basis, build_ai_suggest,
)


# ── 单条候选人处理（接入 WorkflowEngine）─────────────────────────────────────

def process_one(
    rec: dict,
    engine_v2: ResumeScreeningEngineV2,
    dry_run: bool,
    interactive: bool,
    write_lark_log: bool,
    index: int,
    total: int,
) -> str:
    """
    处理单条候选人记录，返回结果状态：'ok' / 'skip' / 'error'

    interactive=True 时，评分完成后暂停，等待人确认是否写入。
    """
    rid    = rec.get("record_id", "?")
    fields = rec.get("fields", {})
    name   = extract_text(fields.get("姓名") or fields.get("名字", "")) or rid

    wf = WorkflowEngine(
        candidate_name=name,
        write_lark=write_lark_log,
    )
    # 覆盖 run_id 前缀让日志更好读
    wf.run_id = f"rescore-{rid[:8]}-{int(time.time())}"

    print(f"\n[{index}/{total}] 开始处理：{name}")

    # ── Step 1: 读取飞书字段 ──────────────────────────────────────────────────
    lang_raw = fields.get("语言对", "")
    with wf.step("读取飞书字段", input_summary=f"record: {rid}") as s:
        if not lang_raw:
            s.finish(output="语言对为空，跳过", status=StepStatus.SKIPPED)
        else:
            s.finish(output=f"语言对: {lang_raw}，字段加载完成")

    if not lang_raw:
        return "skip"

    # ── Step 2: PDF 解析（可选）───────────────────────────────────────────────
    pdf_text = ""
    resume_field = fields.get("简历", [])
    if resume_field and isinstance(resume_field, list) and resume_field[0]:
        file_token = resume_field[0].get("file_token", "") if isinstance(resume_field[0], dict) else ""
        if file_token:
            with wf.step("解析简历 PDF", input_summary=f"file_token: {file_token[:12]}…") as s:
                pdf_text = extract_pdf_text(file_token, name)
                if pdf_text:
                    s.finish(output=f"提取成功，{len(pdf_text)} 字符")
                else:
                    s.finish(output="PDF 无法解析，仅使用飞书表字段", status=StepStatus.SKIPPED)

    # 将 PDF 内容合并进 fields（补充项目经历）
    if pdf_text:
        orig_proj  = extract_text(fields.get("项目经历", ""))
        orig_other = extract_text(fields.get("其他相关经验", ""))
        fields = dict(fields)
        fields["项目经历"]    = (orig_proj + "\n" + pdf_text) if orig_proj else pdf_text
        fields["其他相关经验"] = (orig_other + "\n" + pdf_text) if orig_other else pdf_text

    # ── Step 3: 构建候选人数据结构 ───────────────────────────────────────────
    with wf.step("构建候选人数据", input_summary=f"语言对: {lang_raw}") as s:
        candidate = build_candidate({"record_id": rid, "fields": fields})
        s.finish(output=f"价格: {candidate.get('人工翻译单价')} | 商议: {candidate.get('报价商议空间')}")

    if not candidate["语言对"]:
        wf.error("语言对解析失败", f"原始值: {lang_raw}")
        return "skip"

    # ── Step 4: 评分引擎计算 ──────────────────────────────────────────────────
    try:
        with wf.step("调用评分引擎", input_summary=f"语言对: {candidate['语言对']}") as s:
            result = engine_v2.calculate_final_result(candidate)
            final_score = result["final_score"]
            final_tier  = result["final_tier"]
            base_tier   = result["base_tier"]
            adj         = result["bonus_penalty"]["net_adjustment"]
            s.finish(
                output=(
                    f"总分: {final_score}/100  档位: {base_tier}→{final_tier}  "
                    f"价格: {result['price_result']['score']}/50  "
                    f"资历: {result['experience_result']['total_score']}/50  "
                    f"微调: {adj:+d}"
                )
            )
    except Exception as e:
        wf.error("评分引擎异常", str(e), input_summary=f"record: {rid}")
        return "error"

    # ── Step 5: 生成文本字段 ──────────────────────────────────────────────────
    with wf.step("生成评分文案", input_summary="评分结果 → 评分依据 + AI建议") as s:
        score_basis = build_score_basis(result, candidate)
        ai_suggest  = build_ai_suggest(result)
        s.finish(output=f"AI建议: {ai_suggest}")

    # ── Step 6: 有效简历判定 ──────────────────────────────────────────────────
    with wf.step("判定有效简历", input_summary="翻译/游戏经验关键词匹配") as s:
        services    = [str(sv).lower() for sv in (fields.get("提供的服务") or [])]
        project_txt = extract_text(fields.get("项目经历", "")).lower()
        other_txt   = extract_text(fields.get("其他相关经验", "")).lower()
        all_txt     = project_txt + " " + other_txt

        TRANS_KEYWORDS = ["翻译", "translation", "translat", "aipe", "校对",
                          "proofreading", "lqa", "locali", "本地化", "interpret"]
        has_translation = (
            any(kw in sv for sv in services for kw in TRANS_KEYWORDS) or
            any(kw in all_txt for kw in TRANS_KEYWORDS)
        )
        GAME_EXP_KEYWORDS = [
            'game locali', 'game translat', 'locali', 'lqa',
            '游戏翻译', '游戏本地化', 'game content', 'video game', 'mobile game',
            'rpg', 'moba', 'mmorpg', 'steam', 'playstation', 'nintendo', 'xbox',
            '手游', '端游', '游戏项目',
        ]
        has_game_exp = (
            any(kw in all_txt for kw in GAME_EXP_KEYWORDS) or
            any(kw in sv for sv in services for kw in GAME_EXP_KEYWORDS)
        )

        def _has_game_kw(txt):
            for kw in GAME_KEYWORDS:
                if len(kw) <= 4 and kw.isascii():
                    if re.search(r'(?<![\w])' + re.escape(kw) + r'(?![\w])', txt, re.IGNORECASE):
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

        is_valid   = has_translation or has_game_exp or has_game_work
        valid_label = "是" if is_valid else "否"
        s.finish(
            output=(
                f"{'✅ 有效' if is_valid else '❌ 无效'}  "
                f"（翻译:{has_translation} 游戏:{has_game_exp} 从业:{has_game_work}）"
            )
        )

    write_fields = {
        FIELD_SCORE:       final_score,
        FIELD_TIER:        final_tier,
        FIELD_SCORE_BASIS: score_basis,
        FIELD_AI_SUGGEST:  ai_suggest,
        FIELD_VALID:       valid_label,
    }

    # ── Step 7: Human Decision 节点（仅 interactive 模式）────────────────────
    if interactive:
        decision = wf.checkpoint(
            node="确认写入飞书",
            context={
                "候选人":   name,
                "总分":     f"{final_score}/100",
                "档位":     final_tier,
                "AI建议":   ai_suggest,
                "有效简历": valid_label,
                "DRY-RUN":  "是（不会实际写入）" if dry_run else "否（将写入飞书）",
            },
            prompt="是否确认将以上评分写入飞书？",
            options=["写入", "跳过", "退出"],
        )

        if decision == "退出":
            print("\n⚠️  用户选择退出，终止处理")
            sys.exit(0)
        if decision == "跳过":
            wf.trace("跳过写入", input_summary=name, output_summary="用户选择跳过", status=StepStatus.SKIPPED)
            wf.summary()
            return "skip"

    # ── Step 8: 写回飞书 ─────────────────────────────────────────────────────
    try:
        with wf.step("写回飞书", input_summary=f"record: {rid}  字段数: {len(write_fields)}") as s:
            write_record(rid, write_fields, dry_run)
            s.finish(
                output="[DRY-RUN] 未实际写入" if dry_run else f"✅ 写入成功  总分:{final_score} 档位:{final_tier}"
            )
    except Exception as e:
        wf.error("写回飞书失败", str(e), input_summary=f"record: {rid}")
        return "error"

    wf.summary()
    return "ok"


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="rescore_and_write v2（工作流可视化版）")
    parser.add_argument("--dry-run",      action="store_true", help="只打印，不写入飞书")
    parser.add_argument("--record-id",    help="只处理指定 record_id")
    parser.add_argument("--limit",        type=int, default=0, help="只处理前 N 条")
    parser.add_argument("--interactive",  action="store_true", help="启用 Human Decision 确认节点")
    parser.add_argument("--no-lark-log",  action="store_true", help="不写飞书流程日志")
    args = parser.parse_args()

    dry_run        = args.dry_run
    interactive    = args.interactive
    write_lark_log = not args.no_lark_log

    # interactive 批量处理时警告
    if interactive and not args.record_id and not args.limit:
        print("⚠️  --interactive 在全量模式下会逐条暂停，建议配合 --limit 或 --record-id 使用")
        print("   继续？(y/n) ", end="")
        if input().strip().lower() != "y":
            sys.exit(0)

    if dry_run:
        print("⚠️  DRY-RUN 模式：不会写入飞书\n")

    # 初始化评分引擎
    print("初始化评分引擎…")
    engine_v2 = ResumeScreeningEngineV2()
    print("✅ 引擎加载完成\n")

    # 拉取记录
    print("拉取飞书记录…")
    records = fetch_all_records()
    print(f"✅ 共 {len(records)} 条记录\n")

    if args.record_id:
        records = [r for r in records if r.get("record_id") == args.record_id]
        print(f"过滤指定 record_id: {args.record_id}，剩余 {len(records)} 条\n")

    if args.limit > 0:
        records = records[:args.limit]
        print(f"限制前 {args.limit} 条\n")

    ok_count   = 0
    skip_count = 0
    err_count  = 0

    for i, rec in enumerate(records, 1):
        status = process_one(
            rec=rec,
            engine_v2=engine_v2,
            dry_run=dry_run,
            interactive=interactive,
            write_lark_log=write_lark_log,
            index=i,
            total=len(records),
        )
        if status == "ok":
            ok_count += 1
        elif status == "skip":
            skip_count += 1
        else:
            err_count += 1

        time.sleep(0.3)   # 飞书限流保护

    print("=" * 60)
    print(f"全部完成：成功 {ok_count} | 跳过 {skip_count} | 失败 {err_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
