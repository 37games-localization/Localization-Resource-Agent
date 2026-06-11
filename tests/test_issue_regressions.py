#!/usr/bin/env python3
"""Regression tests for production validation issues."""

import sys
import unittest
from pathlib import Path

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
    score_contract_template,
)


class LarkRecordNormalizeTest(unittest.TestCase):
    def test_keeps_field_name_and_id_aliases(self):
        data = {
            "fields": ["姓名", "招募状态"],
            "field_id_list": ["fld_name", "fld_status"],
            "record_id_list": ["rec1"],
            "data": [["青木遥", "📋 新投递"]],
        }

        records = normalize_record_list_data(data)

        self.assertEqual(records[0]["fields"]["姓名"], "青木遥")
        self.assertEqual(records[0]["fields"]["fld_name"], "青木遥")
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


if __name__ == "__main__":
    unittest.main()
