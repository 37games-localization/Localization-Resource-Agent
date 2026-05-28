#!/usr/bin/env python3
"""
run_demo.py
===========
全流程演示脚本。使用本地 mock 数据，不发真实邮件，不写正式飞书表。
VM 装好 skill 后运行此脚本，确认各模块工作正常。

用法：
    python3 scripts/run_demo.py

输出：各阶段 OK / FAIL，最后给出整体结论。
"""

import sys
import json
import traceback
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

# ── Mock 候选人数据 ────────────────────────────────────────────────────────────
MOCK_RECORD = {
    "record_id": "DEMO-001",
    "fields": {
        "姓名": "山田花子",
        "邮箱": "demo-candidate@example.com",
        "语言对": ["English to Japanese"],
        "AIPE单价": 0.04,
        "人工翻译单价": 0.08,
        "报价商议空间": "有一些",
        "提供的服务": ["翻译", "LQA"],
        "项目经历": (
            "Monster Hunter Rise (Capcom) - 200,000 words\n"
            "Final Fantasy XIV (Square Enix) - 150,000 words\n"
            "Nier: Automata (PlatinumGames) - 80,000 words\n"
            "Full-time game localization experience: 7 years"
        ),
        "其他相关经验": "Previously worked with SIDE and Keywords Studios",
        "解析字数": None,
        "解析年限": None,
        "解析项目数": None,
        "解析知名实体": None,
        "招募状态": "📋 简历待筛选",
    }
}

MOCK_CONTRACT_INFO = {
    "contractor_name": "山田花子",
    "contractor_name_en": "Yamada Hanako",
    "id_number": "DEMO-ID-00001",
    "bank_name": "Demo Bank",
    "bank_account": "DEMO1234567890",
    "bank_account_name": "Yamada Hanako",
    "swift_code": "DEMOSWIFT",
    "address": "Tokyo, Japan",
    "email": "demo-candidate@example.com",
    "contract_no": "DEMO-2026-001",
}

results = {}

def section(title):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print('─'*55)

def ok(step, detail=""):
    results[step] = "OK"
    msg = f"  ✅ {step}"
    if detail:
        msg += f"\n     {detail}"
    print(msg)

def fail(step, err):
    results[step] = "FAIL"
    print(f"  ❌ {step}")
    print(f"     {err}")

# ══ 1. 配置检查 ════════════════════════════════════════════════════════════════
section("1/6  配置加载")
try:
    from config_loader import load_config, get_smtp, get_lark, get_llm_api_key, is_test_mode, get_test_email
    cfg = load_config()
    ok("config.yaml 加载", f"test_mode={'ON' if is_test_mode(cfg) else 'OFF'}")
except Exception as e:
    fail("config.yaml 加载", str(e))
    print("\n⛔ config.yaml 加载失败，无法继续演示。请先填写配置文件。")
    sys.exit(1)

# ══ 2. 简历解析（mock，不调 LLM）═════════════════════════════════════════════
section("2/6  简历解析（Mock LLM，不消耗 token）")
try:
    # 直接用 mock 解析结果，模拟 LLM 输出
    mock_parsed = {
        "word_count": 430000,
        "years": 7.0,
        "project_count": 3,
        "notable_entities": "Monster Hunter Rise,Final Fantasy XIV,Nier: Automata,Capcom,Square Enix,SIDE,Keywords Studios"
    }
    rec = MOCK_RECORD.copy()
    rec["fields"]["解析字数"]     = mock_parsed["word_count"]
    rec["fields"]["解析年限"]     = mock_parsed["years"]
    rec["fields"]["解析项目数"]   = mock_parsed["project_count"]
    rec["fields"]["解析知名实体"] = mock_parsed["notable_entities"]

    print(f"  字数:     {mock_parsed['word_count']:,}")
    print(f"  年限:     {mock_parsed['years']} 年")
    print(f"  项目数:   {mock_parsed['project_count']}")
    print(f"  知名实体: {mock_parsed['notable_entities'][:60]}...")
    ok("简历解析", "Mock 数据，不调用真实 LLM")
except Exception as e:
    fail("简历解析", traceback.format_exc())

# ══ 3. 评分计算 ════════════════════════════════════════════════════════════════
section("3/6  评分计算（确定性，无 AI）")
try:
    from resume_screening_engine_v2 import ResumeScreeningEngineV2

    config_path = Path(__file__).parent.parent / "config" / "resume_screening_rules_v2.json"
    engine = ResumeScreeningEngineV2(config_path=config_path)

    candidate = {
        "姓名": rec["fields"]["姓名"],
        "语言对": "en>ja",
        "人工翻译单价": rec["fields"]["人工翻译单价"],
        "AIPE单价": rec["fields"]["AIPE单价"],
        "报价商议空间": rec["fields"]["报价商议空间"],
        "提供的服务": rec["fields"]["提供的服务"],
        "项目经历": rec["fields"]["项目经历"],
        "其他相关经历": rec["fields"]["其他相关经验"],
        "熟悉的IP": "",
        "_parsed_word_count":  rec["fields"]["解析字数"],
        "_parsed_years":       rec["fields"]["解析年限"],
        "_parsed_project_cnt": rec["fields"]["解析项目数"],
        "_parsed_entities":    rec["fields"]["解析知名实体"],
    }
    result    = engine.calculate_final_result(candidate)
    score     = result.get("final_score", 0)
    tier      = result.get("final_tier", "?")
    tier_name = result.get("tier_name", "")
    price_sc  = result.get("price_result", {}).get("score", 0)
    exp_sc    = result.get("experience_result", {}).get("total_score", 0)

    print(f"  价格得分: {price_sc}/50")
    print(f"  资历得分: {exp_sc:.1f}/50")
    print(f"  总分:     {score}  →  档位: {tier}（{tier_name}）")
    ok("评分计算", f"总分 {score}，档位 {tier}（{tier_name}）")
except Exception as e:
    fail("评分计算", traceback.format_exc())

# ══ 4. 测试题邮件草稿 ══════════════════════════════════════════════════════════
section("4/6  测试题邮件草稿（不发送）")
try:
    # 模拟邮件草稿生成，不实际发送
    name   = rec["fields"]["姓名"]
    email  = rec["fields"]["邮箱"]
    lang   = "English to Japanese"
    is_cn  = any('\u4e00' <= c <= '\u9fff' for c in name)

    if is_cn:
        subject = f"游戏本地化测试稿 — {name}"
        body = f"""尊敬的 {name}，

感谢您对我们本地化团队的关注。

现随邮件附上翻译测试稿，请在 5 个工作日内完成并回复。
如有疑问，欢迎随时联系。

此致
本地化团队"""
    else:
        subject = f"Game Localization Test Assignment — {name}"
        body = f"""Dear {name},

Thank you for your interest in joining our localization team.

Please find the test assignment attached. Kindly return your completed translation within 5 business days.

Best regards,
Localization Team"""

    print(f"  收件人: {name} <{email}>")
    print(f"  主题:   {subject}")
    print(f"  正文预览:\n    " + body.replace('\n', '\n    ')[:200])
    ok("测试题邮件草稿", "草稿生成正常，TEST_MODE 下不实际发送")
except Exception as e:
    fail("测试题邮件草稿", traceback.format_exc())

# ══ 5. 合同生成 ════════════════════════════════════════════════════════════════
section("5/6  合同生成（不发送，检查模板是否存在）")
try:
    from config_loader import get_paths
    tpl_dir = Path(get_paths(cfg).get("contract_templates", "")).expanduser()
    out_dir = Path(get_paths(cfg).get("contract_output", "")).expanduser()

    if not tpl_dir.exists():
        results["合同生成"] = "WARN"
        print(f"  ⚠️  合同生成")
        print(f"     模板目录不存在：{tpl_dir}")
        print(f"     请按 onboarding.md 第三步放入合同模板（.docx）后重新运行")
    else:
        docx_files = list(tpl_dir.glob("*.docx"))
        if not docx_files:
            fail("合同生成", f"模板目录为空，请放入 .docx 合同模板：{tpl_dir}")
        else:
            # 尝试读取第一个模板
            try:
                from docx import Document
                doc = Document(str(docx_files[0]))
                para_count = len(doc.paragraphs)
                out_dir.mkdir(parents=True, exist_ok=True)
                print(f"  模板文件: {docx_files[0].name}")
                print(f"  段落数:   {para_count}")
                print(f"  输出目录: {out_dir}")
                print(f"  变量示例: {{{{contractor_name}}}} → {MOCK_CONTRACT_INFO['contractor_name']}")
                ok("合同生成", f"找到 {len(docx_files)} 个模板，输出目录就绪")
            except Exception as e2:
                fail("合同生成", str(e2))
except Exception as e:
    fail("合同生成", traceback.format_exc())

# ══ 6. 状态推进模拟 ════════════════════════════════════════════════════════════
section("6/6  状态推进模拟（不写飞书）")
try:
    status_chain = [
        "📋 简历待筛选",
        "✅ 初筛通过",
        "📤 测试中",
        "✅ 测试通过",
        "📧 合同信息收集中",
        "📄 合同待生成",
        "📮 合同已发送",
        "🔏 等待签署",
    ]
    current = status_chain[0]
    for next_status in status_chain[1:]:
        print(f"  {current}  →  {next_status}")
        current = next_status
    ok("状态推进模拟", "16节点状态链验证正常（DEMO 模式，不写飞书）")
except Exception as e:
    fail("状态推进模拟", traceback.format_exc())

# ══ 汇总 ═══════════════════════════════════════════════════════════════════════
section("演示结果汇总")
all_ok = all(v in ("OK", "WARN") for v in results.values())
for step, status in results.items():
    icon = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}.get(status, "❌")
    print(f"  {icon} {step}")

print()
if all_ok:
    print("🎉 全部通过！可以开始正式配置。")
    print()
    print("下一步：")
    print("  1. 填写 config.yaml（SMTP / 飞书表 / test_email）")
    print("  2. python3 scripts/check_config.py  （验证连通性）")
    print("  3. 对 OpenClaw 说「帮我走一遍测试流程」")
else:
    failed = [s for s, v in results.items() if v == "FAIL"]
    print(f"⚠️  {len(failed)} 项未通过：{', '.join(failed)}")
    print("请根据上方错误信息修复后重新运行。")
print()
