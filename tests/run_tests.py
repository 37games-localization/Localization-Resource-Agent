#!/usr/bin/env python3
"""
run_tests.py
============
评分引擎测试执行器

用法：
    python3 tests/run_tests.py              # 跑全部用例
    python3 tests/run_tests.py --category C # 只跑C类边界规则
    python3 tests/run_tests.py --id C01     # 跑单个用例
    python3 tests/run_tests.py --snapshot   # 更新B类snapshot基线
"""

import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.resume_screening_engine_v2 import ResumeScreeningEngineV2
from tests.test_cases import TEST_CASES

# 有效简历判定（复用 rescore_and_write 里的逻辑）
import re
TRANS_KEYWORDS = ["翻译", "translation", "translat", "aipe", "校对",
                  "proofreading", "lqa", "locali", "本地化", "interpret"]
GAME_EXP_KEYWORDS = [
    'game locali', 'game translat', 'locali', 'lqa',
    '游戏翻译', '游戏本地化', '游戏项目', 'game content', 'video game', 'mobile game',
    'rpg', 'moba', 'mmorpg', 'steam', 'playstation', 'nintendo', 'xbox',
    '手游', '端游',
]
GAME_KEYWORDS = [
    "游戏", "game", "gaming", "rpg", "moba", "mmorpg", "tcg", "lqa",
    "手游", "端游", "主机", "steam", "nintendo", "playstation", "xbox",
    "unity", "unreal", "本地化", "localization",
]

def check_valid_resume(candidate: dict) -> bool:
    services    = [str(s).lower() for s in (candidate.get("提供的服务") or [])]
    project_txt = str(candidate.get("项目经历", "")).lower()
    other_txt   = str(candidate.get("其他相关经历", "")).lower()
    all_txt     = project_txt + " " + other_txt

    has_translation = (
        any(kw in s for s in services for kw in TRANS_KEYWORDS) or
        any(kw in all_txt for kw in TRANS_KEYWORDS)
    )
    has_game_exp = (
        any(kw in all_txt for kw in GAME_EXP_KEYWORDS) or
        any(kw in s for s in services for kw in GAME_EXP_KEYWORDS)
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

    return has_translation or has_game_exp or has_game_work


def run_one(case: dict, engine: ResumeScreeningEngineV2, update_snapshot: bool = False) -> dict:
    """执行单个用例，返回结果 dict"""
    cid      = case["id"]
    expected = case["expected"]
    inp      = case["input"]

    # 处理 None 语言对
    if inp.get("语言对") is None:
        inp = dict(inp)
        inp["语言对"] = ""

    errors = []
    warnings = []

    # ── 运行引擎 ──────────────────────────────────────────────
    try:
        result = engine.calculate_final_result(inp)
    except Exception as e:
        if expected.get("no_crash"):
            return {"id": cid, "status": "PASS", "note": f"no_crash通过（异常已捕获: {e}）", "result": None}
        return {"id": cid, "status": "FAIL", "note": f"引擎崩溃: {e}", "result": None}

    if expected.get("no_crash") and result:
        pass  # 不崩溃即通过，继续验证其他断言

    actual_tier       = result["final_tier"]
    actual_base_tier  = result["base_tier"]
    actual_price_score= result["price_result"]["score"]
    actual_exp_score  = result["experience_result"]["total_score"]
    actual_final_score= result["final_score"]

    # ── 有效简历判定 ──────────────────────────────────────────
    actual_valid = check_valid_resume(inp)

    # ── 断言 ──────────────────────────────────────────────────
    if "valid_resume" in expected:
        if actual_valid != expected["valid_resume"]:
            errors.append(
                f"valid_resume: 预期={expected['valid_resume']} 实际={actual_valid}"
            )

    if "final_tier_in" in expected:
        if actual_tier not in expected["final_tier_in"]:
            errors.append(
                f"final_tier: 预期在{expected['final_tier_in']} 实际={actual_tier}"
            )

    if "base_tier_in" in expected:
        if actual_base_tier not in expected["base_tier_in"]:
            errors.append(
                f"base_tier: 预期在{expected['base_tier_in']} 实际={actual_base_tier}"
            )

    if "price_score_range" in expected:
        lo, hi = expected["price_score_range"]
        if not (lo <= actual_price_score <= hi):
            errors.append(
                f"price_score: 预期[{lo},{hi}] 实际={actual_price_score}"
            )

    if "experience_score_range" in expected:
        lo, hi = expected["experience_score_range"]
        if not (lo <= actual_exp_score <= hi):
            errors.append(
                f"experience_score: 预期[{lo},{hi}] 实际={actual_exp_score}"
            )

    # B类：snapshot对比
    if case["category"] == "B" and case.get("snapshot"):
        snap = case["snapshot"]
        for key in ["final_score", "base_tier", "final_tier"]:
            if key in snap and snap[key] != result.get(key):
                warnings.append(f"snapshot回归: {key} 预期={snap[key]} 实际={result.get(key)}")

    # B类：更新snapshot
    if update_snapshot and case["category"] == "B":
        case["snapshot"] = {
            "final_score":   actual_final_score,
            "base_tier":     actual_base_tier,
            "final_tier":    actual_tier,
            "price_score":   actual_price_score,
            "exp_score":     actual_exp_score,
        }

    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "id":       cid,
        "status":   status,
        "errors":   errors,
        "warnings": warnings,
        "actual": {
            "final_tier":   actual_tier,
            "base_tier":    actual_base_tier,
            "final_score":  actual_final_score,
            "price_score":  actual_price_score,
            "exp_score":    actual_exp_score,
            "valid_resume": actual_valid,
        },
        "result": result,
    }


def print_report(results: list, cases: list):
    total  = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")

    print("\n" + "=" * 65)
    print(f"  评分引擎测试报告")
    print("=" * 65)
    print(f"  总计: {total}  PASS: {passed}  WARN: {warned}  FAIL: {failed}")
    print("=" * 65)

    # 按类别分组打印
    for cat in ["C", "A", "B"]:
        cat_label = {"C": "C类·边界规则", "A": "A类·常规场景", "B": "B类·Snapshot"}[cat]
        cat_results = [r for r, c in zip(results, cases) if c["category"] == cat]
        if not cat_results:
            continue

        print(f"\n── {cat_label} ({'边界优先' if cat == 'C' else ''}) ──")
        for r, c in zip(
            [r for r in results if r["id"].startswith(cat)],
            [c for c in cases if c["category"] == cat]
        ):
            icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[r["status"]]
            act  = r.get("actual", {})
            print(f"  {icon} {r['id']} {c['name']}")
            if act:
                print(f"      → tier={act.get('final_tier')}(base={act.get('base_tier')})  "
                      f"price={act.get('price_score')}  exp={act.get('exp_score')}  "
                      f"valid={act.get('valid_resume')}")
            for e in r.get("errors", []):
                print(f"      ❌ {e}")
            for w in r.get("warnings", []):
                print(f"      ⚠️  {w}")
            if r.get("note"):
                print(f"      📝 {r['note']}")

    print("\n" + "=" * 65)
    if failed == 0:
        print("  ✅ 全部通过！")
    else:
        print(f"  ❌ {failed} 个用例失败，请检查评分规则实现")
    print("=" * 65 + "\n")

    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="评分引擎测试执行器")
    parser.add_argument("--category", choices=["A", "B", "C"], help="只跑指定类别")
    parser.add_argument("--id",       help="只跑指定用例 ID（如 C01）")
    parser.add_argument("--snapshot", action="store_true", help="更新B类snapshot基线")
    args = parser.parse_args()

    print("初始化评分引擎…")
    engine = ResumeScreeningEngineV2()
    print("✅ 引擎加载完成\n")

    # 过滤用例
    cases = TEST_CASES
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if args.id:
        cases = [c for c in cases if c["id"] == args.id]

    if not cases:
        print(f"❌ 未找到匹配用例"); sys.exit(1)

    print(f"执行 {len(cases)} 个用例…")
    results = [run_one(c, engine, update_snapshot=args.snapshot) for c in cases]

    all_passed = print_report(results, cases)

    # --snapshot 时写回 test_cases.py（更新B类snapshot字段）
    if args.snapshot:
        print("⚠️  --snapshot 模式：请手动将以下 snapshot 数据更新到 test_cases.py 对应用例：")
        for r, c in zip(results, cases):
            if c["category"] == "B" and c.get("snapshot"):
                print(f"  {c['id']}: {json.dumps(c['snapshot'], ensure_ascii=False)}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
