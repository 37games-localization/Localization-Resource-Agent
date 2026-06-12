#!/usr/bin/env python3
"""Regression tests for production validation issues."""

import sys
import unittest
import json
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lark_cli_utils import normalize_record_list_data
from evaluate_resumes import clamp_final_score
from pricing_rules import PricingRulesError, normalize_rule_key
from resume_screening_engine_v2 import ResumeScreeningEngineV2
from generate_contract import (
    ACCOUNT_TYPE_FIELD_ID,
    FLD_BANK_ADDR,
    FLD_BANK_NAME,
    FLD_CURRENCY,
    FLD_ID_NO,
    is_domestic_personal_account,
    send_email,
    score_contract_template,
)
from workflow_engine import WorkflowEngine
from workflow_engine import StepStatus, StepType, WorkflowStep
from badcase_protocol import (
    REDACTED,
    build_snapshot,
    issue_body,
    issue_labels,
    issue_title,
    sanitize_obj,
    validate_snapshot,
)
from trace_span import span_from_workflow_step, validate_span
from agent_router import ActiveAgentSession, classify_instruction
from config_loader import get_table_ref


class LarkRecordNormalizeTest(unittest.TestCase):
    def test_keeps_field_name_and_id_aliases(self):
        data = {
            "fields": ["姓名", "招募状态"],
            "field_id_list": ["fld_name", "fld_status"],
            "record_id_list": ["rec1"],
            "data": [["测试候选人A", "📋 新投递"]],
        }

        records = normalize_record_list_data(data)

        self.assertEqual(records[0]["fields"]["姓名"], "测试候选人A")
        self.assertEqual(records[0]["fields"]["fld_name"], "测试候选人A")
        self.assertEqual(records[0]["fields"]["招募状态"], "📋 新投递")
        self.assertEqual(records[0]["fields"]["fld_status"], "📋 新投递")


class ScoreCapTest(unittest.TestCase):
    def test_llm_final_score_is_capped_to_100(self):
        result, raw_score, was_capped = clamp_final_score({"final_score": 102})

        self.assertEqual(raw_score, 102)
        self.assertTrue(was_capped)
        self.assertEqual(result["final_score"], 100)

    def test_negative_score_is_capped_to_zero(self):
        result, raw_score, was_capped = clamp_final_score({"final_score": -3})

        self.assertEqual(raw_score, -3)
        self.assertTrue(was_capped)
        self.assertEqual(result["final_score"], 0)


class PricingRuleKeyNormalizeTest(unittest.TestCase):
    MAIN_MARKET_RULE_KEYS = {
        "en>ar",
        "en>de",
        "en>es",
        "en>fr",
        "en>id",
        "en>it",
        "en>ms",
        "en>nl",
        "en>pl",
        "en>pt",
        "en>ru",
        "en>th",
        "en>tr",
        "en>vi",
        "zh-CN>ar",
        "zh-CN>en",
        "zh-CN>id",
        "zh-CN>ja",
        "zh-CN>ko",
        "zh-CN>ms",
        "zh-CN>th",
        "zh-CN>vi",
    }

    def test_lark_chinese_language_names_normalize_to_engine_codes(self):
        self.assertEqual(normalize_rule_key("zh-CN>韩语"), "zh-CN>ko")
        self.assertEqual(normalize_rule_key("简中>韩语"), "zh-CN>ko")
        self.assertEqual(normalize_rule_key("简中>英语"), "zh-CN>en")

    def test_bilingual_language_pair_normalizes_by_known_language_names(self):
        self.assertEqual(
            normalize_rule_key("简中>韩语 Simplified Chinese to Korean"),
            "zh-CN>ko",
        )

    def test_main_market_rule_keys_are_stable_after_normalization(self):
        raw_pairs = [
            "英语>阿拉伯语",
            "英语>德语",
            "英语>西班牙语",
            "英语>法语",
            "英语>印尼语",
            "英语>意大利语",
            "英语>马来语",
            "英语>荷兰语",
            "英语>波兰语",
            "英语>葡萄牙语",
            "英语>俄语",
            "英语>泰语",
            "英语>土耳其语",
            "英语>越南语",
            "简中>阿拉伯语",
            "简中>英语",
            "简中>印尼语",
            "简中>日语",
            "简中>韩语",
            "简中>马来语",
            "简中>泰语",
            "简中>越南语",
        ]

        normalized = {normalize_rule_key(pair) for pair in raw_pairs}

        self.assertEqual(normalized, self.MAIN_MARKET_RULE_KEYS)

    def test_main_market_bilingual_labels_keep_target_language_priority(self):
        cases = {
            "英语>阿拉伯语 English to Arabic": "en>ar",
            "英语>德语 English to German": "en>de",
            "英语>西班牙语 English to Spanish": "en>es",
            "英语>法语 English to French": "en>fr",
            "英语>印尼语 English to Indonesian": "en>id",
            "英语>意大利语 English to Italian": "en>it",
            "英语>马来语 English to Malay": "en>ms",
            "英语>荷兰语 English to Dutch": "en>nl",
            "英语>波兰语 English to Polish": "en>pl",
            "英语>葡萄牙语 English to Portuguese": "en>pt",
            "英语>俄语 English to Russian": "en>ru",
            "英语>泰语 English to Thai": "en>th",
            "英语>土耳其语 English to Turkish": "en>tr",
            "英语>越南语 English to Vietnamese": "en>vi",
            "简中>阿拉伯语 Simplified Chinese to Arabic": "zh-CN>ar",
            "简中>英语 Simplified Chinese to English": "zh-CN>en",
            "简中>印尼语 Simplified Chinese to Indonesian": "zh-CN>id",
            "简中>日语 Simplified Chinese to Japanese": "zh-CN>ja",
            "简中>韩语 Simplified Chinese to Korean": "zh-CN>ko",
            "简中>马来语 Simplified Chinese to Malay": "zh-CN>ms",
            "简中>泰语 Simplified Chinese to Thai": "zh-CN>th",
            "简中>越南语 Simplified Chinese to Vietnamese": "zh-CN>vi",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_rule_key(raw), expected)


class ContractTemplateRoutingTest(unittest.TestCase):
    TEMPLATE_NAMES = [
        "（境内个人-人民币）翻译委托框架协议_LOC Demo.docx",
        "（境内个人-外币）翻译委托框架协议_LOC Demo.docx",
        "（境外个人-人民币）翻译委托框架协议_LOC Demo.docx",
        "（个人-外币-个人账户）翻译委托框架协议_LOC Demo.docx",
        "（境外公司）Services Agreement_LOC Demo.docx",
    ]

    def recommend(self, fields):
        return max(self.TEMPLATE_NAMES, key=lambda name: score_contract_template(name, fields))

    def personal_fields(self, *, domestic: bool, currency: str):
        fields = {
            ACCOUNT_TYPE_FIELD_ID: "个人账户 Personal account",
            FLD_CURRENCY: currency,
            FLD_ID_NO: "P1234567",
            FLD_BANK_NAME: "DBS Bank",
            FLD_BANK_ADDR: "Singapore",
        }
        if domestic:
            fields.update({
                FLD_ID_NO: "110101199003071234",
                FLD_BANK_NAME: "中国银行",
                FLD_BANK_ADDR: "北京市朝阳区",
            })
        return fields

    def test_domestic_personal_account_detects_china_signals(self):
        fields = {
            ACCOUNT_TYPE_FIELD_ID: "个人账户 Personal account",
            FLD_CURRENCY: "CNY 人民币",
            FLD_ID_NO: "110101199003071234",
            FLD_BANK_NAME: "中国银行",
            FLD_BANK_ADDR: "北京市朝阳区",
        }

        self.assertTrue(is_domestic_personal_account(fields))

    def test_company_account_is_not_domestic_personal(self):
        fields = {
            ACCOUNT_TYPE_FIELD_ID: "公司账户 Business account",
            FLD_CURRENCY: "CNY 人民币",
            FLD_ID_NO: "110101199003071234",
            FLD_BANK_NAME: "中国银行",
            FLD_BANK_ADDR: "北京市朝阳区",
        }

        self.assertFalse(is_domestic_personal_account(fields))

    def test_domestic_personal_cny_recommends_domestic_rmb_template(self):
        fields = self.personal_fields(domestic=True, currency="CNY 人民币")

        self.assertEqual(
            self.recommend(fields),
            "（境内个人-人民币）翻译委托框架协议_LOC Demo.docx",
        )

    def test_domestic_personal_foreign_currency_recommends_domestic_foreign_template(self):
        fields = self.personal_fields(domestic=True, currency="USD 美元")

        self.assertEqual(
            self.recommend(fields),
            "（境内个人-外币）翻译委托框架协议_LOC Demo.docx",
        )

    def test_overseas_personal_cny_recommends_overseas_rmb_template(self):
        fields = self.personal_fields(domestic=False, currency="CNY 人民币")

        self.assertEqual(
            self.recommend(fields),
            "（境外个人-人民币）翻译委托框架协议_LOC Demo.docx",
        )

    def test_overseas_personal_foreign_currency_recommends_personal_foreign_template(self):
        fields = self.personal_fields(domestic=False, currency="USD 美元")

        self.assertEqual(
            self.recommend(fields),
            "（个人-外币-个人账户）翻译委托框架协议_LOC Demo.docx",
        )

    def test_company_account_recommends_company_template_even_with_cny(self):
        fields = {
            ACCOUNT_TYPE_FIELD_ID: "公司账户 Business account",
            FLD_CURRENCY: "CNY 人民币",
            FLD_ID_NO: "110101199003071234",
            FLD_BANK_NAME: "中国银行",
            FLD_BANK_ADDR: "北京市朝阳区",
        }

        self.assertEqual(
            self.recommend(fields),
            "（境外公司）Services Agreement_LOC Demo.docx",
        )


class ProductionGuardrailTest(unittest.TestCase):
    def test_contract_direct_send_is_blocked_outside_test_mode(self):
        with patch("generate_contract.TEST_MODE", False):
            with patch("generate_contract.get_smtp", return_value={"user": "sender@example.com"}):
                with self.assertRaisesRegex(RuntimeError, "生产环境禁止直接发送合同邮件"):
                    send_email(
                        "candidate@example.com",
                        "候选人",
                        Path("/tmp/checked_contract.docx"),
                        draft=False,
                    )

    def test_cli_checkpoint_eof_is_not_treated_as_skip(self):
        engine = WorkflowEngine(candidate_name="测试候选人", silent=True, write_lark=False)
        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaisesRegex(RuntimeError, "未收到明确人工决策"):
                engine.checkpoint(
                    node="确认写入飞书",
                    context={"总分": "92/100"},
                    prompt="是否写入？",
                    options=["写入", "跳过"],
                )

    def test_required_schema_contains_contract_and_supplier_ids(self):
        schema_text = (ROOT / "references" / "lark-required-schema.yaml").read_text(encoding="utf-8")

        self.assertIn("candidate.contract_id", schema_text)
        self.assertIn("candidate.supplier_id", schema_text)

    def test_required_schema_contains_pricing_rules_table(self):
        schema_text = (ROOT / "references" / "lark-required-schema.yaml").read_text(encoding="utf-8")

        self.assertIn("pricing_rules:", schema_text)
        self.assertIn("pricing.language_pair", schema_text)
        self.assertIn("pricing.aipe_target", schema_text)
        self.assertIn("pricing.translation_max", schema_text)
        self.assertIn('base_token: "pricing_rules.base_token"', schema_text)
        self.assertIn('table_id: "pricing_rules.table_id"', schema_text)

    def test_lark_pricing_rules_override_engine_price_thresholds(self):
        lark_rules = {
            "zh-CN>en": {
                "aipe_target": 0.01,
                "aipe_max": 0.02,
                "trans_target": 0.01,
                "trans_max": 0.02,
            }
        }
        with patch("resume_screening_engine_v2.load_price_rules", return_value=(lark_rules, {"source": "lark", "count": 1})):
            engine = ResumeScreeningEngineV2(allow_local_rules=False, require_lark_rules=True)

        result = engine.calculate_price_score({
            "语言对": "zh-CN>en",
            "AIPE单价": 0.03,
            "人工翻译单价": "",
            "报价商议空间": "固定",
        })

        self.assertLess(result["score"], 25)
        self.assertEqual(result["target"], 0.01)
        self.assertEqual(result["max"], 0.02)
        self.assertEqual(result["rule_source"], "lark")

    def test_missing_lark_pricing_rule_blocks_production_scoring(self):
        lark_rules = {
            "zh-CN>en": {
                "aipe_target": 0.03,
                "aipe_max": 0.04,
                "trans_target": 0.04,
                "trans_max": 0.05,
            }
        }
        with patch("resume_screening_engine_v2.load_price_rules", return_value=(lark_rules, {"source": "lark", "count": 1})):
            engine = ResumeScreeningEngineV2(allow_local_rules=False, require_lark_rules=True)

        with self.assertRaisesRegex(PricingRulesError, "找不到语言对"):
            engine.calculate_price_score({
                "语言对": "en>pl",
                "AIPE单价": 0.03,
                "人工翻译单价": "",
                "报价商议空间": "固定",
            })


class BadcaseProtocolTest(unittest.TestCase):
    def test_snapshot_redacts_sensitive_agent_run_fields(self):
        snapshot = build_snapshot(
            record_id="record_test_sensitive",
            salt="unit-test",
            current_status="🔍 初筛中",
            expected_result="应该进入人工复核",
            language_pair="zh-CN>ko",
            services="翻译",
            score="92",
            tier="S",
            ai_suggestion="优先录用",
            score_basis="PDF 解析成功，识别到游戏本地化经验。",
            agent_run={
                "email": "real.person@example.com",
                "bank_account_number": "6222021234567890123",
                "output_summary": "Sent to real.person@example.com",
            },
        )

        validate_snapshot(snapshot)
        body = issue_body(snapshot)

        self.assertEqual(snapshot["agent_run"]["email"], REDACTED)
        self.assertEqual(snapshot["agent_run"]["bank_account_number"], REDACTED)
        self.assertNotIn("real.person@example.com", json.dumps(snapshot, ensure_ascii=False))
        self.assertNotIn("6222021234567890123", body)

    def test_issue_format_is_stable(self):
        snapshot = build_snapshot(
            record_id="rec1",
            salt="unit-test",
            current_status="📋 新投递",
            expected_result="合同应该用个人版模板",
            language_pair="zh-CN>en",
        )

        title = issue_title(snapshot)
        body = issue_body(snapshot)
        labels = issue_labels(snapshot)

        self.assertTrue(title.startswith("Badcase[contract]: cand_"))
        self.assertIn("## Badcase Summary", body)
        self.assertIn("## VM Expected Result", body)
        self.assertIn("## Required Fix Output", body)
        self.assertIn("badcase", labels)
        self.assertIn("badcase:contract", labels)

    def test_validate_snapshot_rejects_freeform_sensitive_payload(self):
        bad = build_snapshot(
            record_id="rec2",
            salt="unit-test",
            current_status="📋 新投递",
            expected_result="需要复核",
        )
        bad["badcase"]["vm_expected_result"] = "请联系 real.person@example.com"

        with self.assertRaisesRegex(ValueError, "安全扫描命中"):
            validate_snapshot(bad)


class TraceSpanTest(unittest.TestCase):
    def test_workflow_step_maps_to_standard_trace_span(self):
        step = WorkflowStep(
            run_id="run_test",
            step_name="测试题邮件",
            step_type=StepType.ACTION,
            input_summary='{"record_id":"rec1"}',
            candidate_name="测试候选人",
            candidate_record_id="rec1",
        )
        step.finish(output_summary="草稿已生成", status=StepStatus.DONE)

        span = span_from_workflow_step(step)
        validate_span(span)

        self.assertEqual(span["run_id"], "run_test")
        self.assertEqual(span["agent"], "loc-resource-management")
        self.assertEqual(span["step"], "测试题邮件")
        self.assertEqual(span["span_type"], "tool_call")
        self.assertEqual(span["status"], "success")

    def test_trace_span_redacts_sensitive_payload(self):
        step = WorkflowStep(
            run_id="run_sensitive",
            step_name="合同生成",
            step_type=StepType.ACTION,
            input_summary='{"email":"real.person@example.com","bank_account":"6222021234567890123"}',
        )
        step.finish(
            output_summary="Generated contract for real.person@example.com / 6222021234567890123",
            status=StepStatus.DONE,
        )

        span = span_from_workflow_step(step)
        validate_span(span)
        dumped = json.dumps(span, ensure_ascii=False)

        self.assertNotIn("real.person@example.com", dumped)
        self.assertNotIn("6222021234567890123", dumped)
        self.assertIn(REDACTED, dumped)

    def test_checkpoint_maps_to_waiting_confirmation(self):
        step = WorkflowStep(
            run_id="run_waiting",
            step_name="确认发送测试题",
            step_type=StepType.CHECKPOINT,
            input_summary='{"total_score":"92/100"}',
        )
        step.finish(output_summary='{"checkpoint_token":"ckpt-test"}', status=StepStatus.WAITING)

        span = span_from_workflow_step(step)
        validate_span(span)

        self.assertEqual(span["span_type"], "checkpoint")
        self.assertEqual(span["status"], "waiting_confirmation")
        self.assertEqual(span["output"]["checkpoint_token"], "ckpt-test")


class AgentRouterProtocolTest(unittest.TestCase):
    def test_first_resource_task_requires_wake_word(self):
        result = classify_instruction("给青木遥发测试邀请")

        self.assertFalse(result["can_execute"])
        self.assertIn("wake_word", result["missing"])

    def test_wake_word_classifies_test_email_and_missing_attachment(self):
        result = classify_instruction("调用资源管理 Agent，给青木遥发测试邀请")

        self.assertTrue(result["invoked"])
        self.assertEqual(result["step"], "test-email")
        self.assertEqual(result["candidate"], "青木遥")
        self.assertIn("attachment", result["missing"])
        self.assertFalse(result["can_execute"])

    def test_attachment_continues_active_session(self):
        session = ActiveAgentSession(
            candidate="青木遥",
            record_id="20260520-08",
            current_step="test-email",
            waiting_for="attachment",
        )

        result = classify_instruction("附件用 ~/Downloads/test.xlsx", session=session)

        self.assertEqual(result["step"], "test-email")
        self.assertEqual(result["record_id"], "20260520-08")
        self.assertTrue(result["attachment"].endswith("/Downloads/test.xlsx"))
        self.assertTrue(result["can_execute"])

    def test_checkpoint_confirmation_continues_active_session(self):
        session = ActiveAgentSession(
            candidate="青木遥",
            record_id="20260520-08",
            current_step="test-email",
            waiting_for="checkpoint",
            last_checkpoint_token="ckpt-test",
        )

        result = classify_instruction("确认发送", session=session)

        self.assertEqual(result["step"], "test-email")
        self.assertEqual(result["checkpoint_token"], "ckpt-test")
        self.assertTrue(result["can_execute"])

    def test_non_resource_task_invalidates_active_session(self):
        session = ActiveAgentSession(
            candidate="青木遥",
            record_id="20260520-08",
            current_step="test-email",
            waiting_for="checkpoint",
            last_checkpoint_token="ckpt-test",
        )

        result = classify_instruction("帮我改一下 README", session=session)

        self.assertTrue(result["session_invalidated"])
        self.assertFalse(result["can_execute"])
        self.assertIn("wake_word", result["missing"])


class ConfigTableRefTest(unittest.TestCase):
    def test_pricing_rules_can_use_independent_base_and_table(self):
        cfg = {
            "lark": {
                "base_token": "candidate_base",
                "resume_table_id": "candidate_table",
                "rules_table_id": "legacy_rules_table",
            },
            "pricing_rules": {
                "base_token": "rules_base",
                "table_id": "rules_table",
            },
        }

        with patch.dict("os.environ", {"LOC_PRICING_RULES_BASE_TOKEN": "", "LOC_PRICING_RULES_TABLE_ID": ""}):
            self.assertEqual(get_table_ref(cfg, "pricing_rules"), ("rules_base", "rules_table"))

    def test_pricing_rules_keeps_legacy_lark_rules_table_compatibility(self):
        cfg = {
            "lark": {
                "base_token": "candidate_base",
                "resume_table_id": "candidate_table",
                "rules_table_id": "legacy_rules_table",
            }
        }

        with patch.dict("os.environ", {"LOC_PRICING_RULES_BASE_TOKEN": "", "LOC_PRICING_RULES_TABLE_ID": ""}):
            self.assertEqual(get_table_ref(cfg, "pricing_rules"), ("candidate_base", "legacy_rules_table"))

    def test_contract_table_can_use_independent_base(self):
        cfg = {
            "lark": {
                "base_token": "candidate_base",
                "resume_table_id": "candidate_table",
                "contract_base_token": "contract_base",
                "contract_table_id": "contract_table",
            }
        }

        self.assertEqual(get_table_ref(cfg, "contract_info"), ("contract_base", "contract_table"))


if __name__ == "__main__":
    unittest.main()
