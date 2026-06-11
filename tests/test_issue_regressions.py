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
from badcase_protocol import (
    REDACTED,
    build_snapshot,
    issue_body,
    issue_labels,
    issue_title,
    sanitize_obj,
    validate_snapshot,
)


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


if __name__ == "__main__":
    unittest.main()
