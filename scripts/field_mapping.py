"""
field_mapping.py — 合同变量名 ↔ 飞书收集表字段 ID 的映射

⚠️  Source of Truth：
    收集表字段发生变更时，只需更新本文件，无需改其他脚本。
    对应的飞书「变量映射」字段为人读说明，不参与程序逻辑。

⚠️  变更本文件前，必须先阅读：
    references/lark-dependencies.yaml → Agent 变更处理 SOP

飞书收集表信息：
    base_token : JbkRbkGf6aAqfnsCDHHlJMjbg3b
    table_id   : tblePA7PmmYlS936
    表单链接    : https://g4wt0dn9mss.sg.larksuite.com/share/base/form/shrlgF4lJe3AZUz7PY5XuQ8Ugfd

source 类型说明：
    "form"       — 从收集表自动读取，field_id 指向对应字段
    "attachment" — 从收集表附件字段下载文件，field_id 指向附件字段
    "vm"         — VM 手动输入（合同日期、月薪等）
    "auto"       — 由脚本自动计算（如签署年/月/日从日期拆分）
    "fixed"      — 甲方固定信息，由 VM 在 config.yaml 中配置
"""

FORM_BASE_TOKEN = "JbkRbkGf6aAqfnsCDHHlJMjbg3b"
FORM_TABLE_ID   = "tblePA7PmmYlS936"

# ── 账户类型路由字段 ───────────────────────────────────────────
# 选项值：
#   个人账户 = "个人账户 Personal account"
#   公司账户 = "公司账户 Business account"
ACCOUNT_TYPE_FIELD_ID = "fld043Vzeo"

# ── 个人账户字段组 ────────────────────────────────────────────
PERSONAL_ACCOUNT_FIELDS = {
    "收款账户户名": "fldvZMzuk3",   # 个人账户 - 账户名
    "收款银行账号": "fld7CGT1GH",   # 个人账户 - 账号 / IBAN
    "收款银行名称": "fldyPyrLdp",   # 个人账户 - 银行名
    "收款银行地址": "fldDLk0Jh9",   # 个人账户 - 支行地址
}

# ── 公司账户字段组 ────────────────────────────────────────────
COMPANY_ACCOUNT_FIELDS = {
    "收款账户户名": "fldfQSK0Lb",   # 公司账户 - 账户名
    "收款银行账号": "fldIi83yp3",   # 公司账户 - 账号
    "收款银行名称": "fldq0pIMo3",   # 公司账户 - 银行名
    "收款银行地址": "fld6xRZDjM",   # 公司账户 - 支行地址
}

# ── 通用文本字段（个人/公司账户共用） ────────────────────────
COMMON_FORM_FIELDS = {
    "乙方姓名":      "fld2JEyq9H",   # 姓名（全名）
    "乙方证件号":    "fld3hdHuVd",   # 身份证或护照号（统一字段）
    "乙方地址":      "fld8P0lZhg",   # 个人住址
    "乙方邮箱":      "fldYELKkKa",   # 常用工作邮箱
    "乙方手机号":    "fldu4lmuce",   # 联系电话
    "收款银行SWIFT": "fld4ENGLJM",   # SWIFT（个人/公司账户共用）
    "币种":          "fldSZE1Shy",   # 收款货币（美元 USD / 其他 Other）
    "乙方签署":      "fld2JEyq9H",   # 同乙方姓名
}

# ── 附件字段 ──────────────────────────────────────────────────
# source="attachment"：generate_contract.py 会下载文件并插入合同末尾
ATTACHMENT_FIELDS = {
    "乙方证件扫描件": {
        "field_id": "fldia8GcRh",   # 身份证正反面或护照扫描件（图像文件）
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
    "甲方合同编号":     "VM填写，原合同编号",
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
