"""
field_mapping.py — 合同变量名 ↔ 飞书收集表字段 ID 的映射

⚠️  Source of Truth：
    收集表字段发生变更时，只需更新本文件，无需改其他脚本。
    对应的飞书「变量映射」字段为人读说明，不参与程序逻辑。

⚠️  变更本文件前，必须先阅读：
    references/lark-dependencies.yaml → Agent 变更处理 SOP

飞书收集表信息：
    真实 base_token / table_id 从 config.local.yaml 读取。
    不要在本文件中填写真实 Lark token 或内部表单链接。

source 类型说明：
    "form"       — 从收集表自动读取，field_id 指向对应字段
    "attachment" — 从收集表附件字段下载文件，field_id 指向附件字段
    "vm"         — VM 手动输入（合同日期、月薪等）
    "auto"       — 由脚本自动计算（如签署年/月/日从日期拆分）
    "fixed"      — 甲方固定信息，由 VM 在 config.yaml 中配置
"""

from field_resolver import field_id_or


# 保留这两个符号用于兼容旧 import。运行时请使用 config.local.yaml 中的
# lark.contract_base_token / lark.contract_table_id。
FORM_BASE_TOKEN = ""
FORM_TABLE_ID   = ""

# ── 账户类型路由字段 ───────────────────────────────────────────
# 选项值：
#   个人账户 = "个人账户 Personal account"
#   公司账户 = "公司账户 Business account"
ACCOUNT_TYPE_FIELD_ID = field_id_or("contract_info", "contract.account_type", "fld043Vzeo")

# ── 个人账户字段组 ────────────────────────────────────────────
PERSONAL_ACCOUNT_FIELDS = {
    "收款账户户名": field_id_or("contract_info", "contract.bank_account_name", "fldvZMzuk3"),
    "收款银行账号": field_id_or("contract_info", "contract.bank_account_number", "fld7CGT1GH"),
    "收款银行名称": field_id_or("contract_info", "contract.bank_name", "fldyPyrLdp"),
    "收款银行地址": field_id_or("contract_info", "contract.bank_address", "fldDLk0Jh9"),
}

# ── 公司账户字段组 ────────────────────────────────────────────
COMPANY_ACCOUNT_FIELDS = {
    "收款账户户名": field_id_or("contract_info", "contract.company_bank_account_name", "fldfQSK0Lb"),
    "收款银行账号": field_id_or("contract_info", "contract.company_bank_account_number", "fldIi83yp3"),
    "收款银行名称": field_id_or("contract_info", "contract.company_bank_name", "fldq0pIMo3"),
    "收款银行地址": field_id_or("contract_info", "contract.company_bank_address", "fld6xRZDjM"),
}

# ── 通用文本字段（个人/公司账户共用） ────────────────────────
COMMON_FORM_FIELDS = {
    "乙方姓名":      field_id_or("contract_info", "contract.name", "fld2JEyq9H"),
    "乙方证件号":    field_id_or("contract_info", "contract.id_number", "fld3hdHuVd"),
    "乙方地址":      field_id_or("contract_info", "contract.address", "fld8P0lZhg"),
    "乙方邮箱":      field_id_or("contract_info", "contract.email", "fldYELKkKa"),
    "乙方手机号":    field_id_or("contract_info", "contract.phone", "fldu4lmuce"),
    "收款银行SWIFT": field_id_or("contract_info", "contract.swift", "fld4ENGLJM"),
    "币种":          field_id_or("contract_info", "contract.currency", "fldSZE1Shy"),
    "乙方签署":      field_id_or("contract_info", "contract.name", "fld2JEyq9H"),
}

# ── 附件字段 ──────────────────────────────────────────────────
# source="attachment"：generate_contract.py 会下载文件并插入合同末尾
ATTACHMENT_FIELDS = {
    "乙方证件扫描件": {
        "field_id": field_id_or("contract_info", "contract.id_scan", "fldia8GcRh"),
        "desc": "身份证/护照扫描件，插入合同末尾附件页",
        # 合同中匹配的段落关键词（命中任意一个即在该段落后插图）
        "anchor_keywords": [
            "附件一", "附件 一",
            "Copy of", "copy of",
            "Exhibit 1", "Appendix",
            "Passport", "passport",
            "ID Card", "id card",
            "身份证", "护照", "证件",
        ],
        # 公司合同不插身份证扫描件
        "skip_for_company": True,
    }
}

# ── VM 手动输入变量 ───────────────────────────────────────────
# generate_contract.py 会提示 VM 补充这些字段
VM_INPUT_VARS = {
    "合同生效日期":     "VM填写，格式 YYYY-MM-DD",
    "合同结束日期":     "VM填写，格式 YYYY-MM-DD（固定月薪合同用）",
    "合同开始日期":     "VM填写，格式 YYYY-MM-DD",
    "月服务费":         "VM填写，数字+货币单位，如 1000 USD",
    "乙方授权代表":     "VM填写，对方公司授权代表姓名（公司合同用）",
    "乙方联系人职位":   "VM填写，对方联系人职位（公司合同用）",
    "提前终止通知天数": "VM填写，默认 30",
    "验收工作日":       "VM填写，默认 3",
    "配音修改工作日":   "VM填写，默认 3",
}

# ── 自动计算变量 ──────────────────────────────────────────────
AUTO_VARS = {
    "签署年": "从签署日期自动拆分（YYYY）",
    "签署月": "从签署日期自动拆分（MM）",
    "签署日": "从签署日期自动拆分（DD）",
}

# ── 甲方固定信息（从 config.yaml 读取） ──────────────────────
FIXED_VARS = {
    "甲方联系人姓名": "config.yaml → jia_fang.contacts[甲方名].name",
    "甲方联系人邮箱": "config.yaml → jia_fang.contacts[甲方名].email",
    "甲方邮箱":       "config.yaml → jia_fang.contacts[甲方名].email",
}

# ── 是否为公司合同（公司合同不插身份证扫描件） ───────────────
COMPANY_CONTRACT_KEYWORDS = [
    "境外公司", "Services Agreement", "服务框架协议",
]


def get_account_fields(account_type: str) -> dict:
    """
    根据资源商填写的账户类型，返回对应的银行字段组。
    account_type: 飞书字段原始值，如 "个人账户 Personal account"
    """
    if "个人" in account_type or "Personal" in account_type:
        return PERSONAL_ACCOUNT_FIELDS
    elif "公司" in account_type or "Business" in account_type:
        return COMPANY_ACCOUNT_FIELDS
    else:
        raise ValueError(f"未知账户类型: {account_type}，请检查收集表选项值")


def get_all_form_fields(account_type: str) -> dict:
    """
    返回完整的 变量名 → field_id 映射（合并通用 + 账户类型对应的银行字段）。
    """
    fields = {}
    fields.update(COMMON_FORM_FIELDS)
    fields.update(get_account_fields(account_type))
    return fields


def is_company_contract(template_name: str) -> bool:
    """判断是否为公司合同（公司合同不插身份证扫描件）"""
    return any(kw in template_name for kw in COMPANY_CONTRACT_KEYWORDS)
