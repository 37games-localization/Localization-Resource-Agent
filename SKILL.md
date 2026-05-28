---
name: loc-resume-screening
version: "2.2"
updated: "2026-05-28"
description: "本地化资源管理全流程 skill，覆盖译者简历筛选到入库的完整链路。触发场景：(1) VM 首次安装配置引导；(2) 新简历入库解析评分；(3) 发测试题邮件；(4) 生成并发送合同；(5) 合同签署核查；(6) 招募状态推进；(7) 手动纠正评分；(8) 全量重算。所有操作以飞书表为单一数据源，脚本确定性执行，不依赖 AI 上下文记忆状态。"
---

# 本地化资源管理全流程

## 核心原则

- **飞书是大脑**：状态/数据全在飞书，脚本每次从表里读，不靠上下文
- **config.yaml 是唯一配置入口**：VM 只改这一个文件，不动脚本
- **两阶段评分**：LLM 解析（一次性）→ 规则评分（可反复，确定性）
- **TEST_MODE 保护**：正式启用前所有邮件发到测试邮箱

## 配置与安装

VM 首次使用时，先读引导文档：[`references/onboarding.md`](references/onboarding.md)

配置验证指令（VM 说「帮我验证资源管理配置」时执行）：
```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/check_config.py
```

## 脚本速查

| 脚本 | 功能 | 触发语 |
|------|------|--------|
| `parse_resumes.py` | LLM 解析简历 PDF → 写飞书结构化字段 | 「解析简历」「新简历入库」 |
| `rescore_and_write.py` | 确定性重算评分 → 写回飞书 | 「重跑评分」「重算评分」 |
| `send_test_email.py` | 发测试题邮件 → 更新飞书状态 | 「发测试题给XXX」 |
| `generate_contract.py` | 生成合同 docx + 发邮件 → 更新飞书 | 「给XXX生成合同」「发合同」 |
| `check_signed_contract.py` | 核查签字合同 → 更新飞书状态 | 「XXX的合同已签字」 |
| `send_rejection_email.py` | 发婉拒邮件（二次确认）→ 更新飞书 | 「婉拒XXX」 |
| `update_status.py` | 手动推进招募状态 | 「把XXX状态改成XXX」 |

所有脚本从 skill 根目录下的 `config.yaml` 读取配置。

## 招募状态链（16节点）

```
📋 简历待筛选 → 🔍 初筛中 → ✅ 初筛通过 / ❌ 已拒绝
→ 📝 测试题待发 → 📤 测试中 → ✅ 测试通过 / ❌ 测试未通过
→ 📧 合同信息收集中 → 📄 合同待生成 → 📮 合同已发送
→ 🔏 等待签署 → ✅ 合同已签署
→ 💰 财务待登记 → 🔍 财务审批中 → ✅ 已入库 / ❌ 已拒绝
```

## 常用命令

```bash
# 全量解析（跳过已解析）
python3 scripts/parse_resumes.py

# 指定候选人解析
python3 scripts/parse_resumes.py --name "Kai Wichmann"

# 全量重算评分
python3 scripts/rescore_and_write.py

# 指定候选人评分
python3 scripts/rescore_and_write.py --name "青木遥"

# 先预览再执行（所有脚本都支持 --dry-run）
python3 scripts/generate_contract.py --name "宋赛楠" --dry-run
python3 scripts/generate_contract.py --name "宋赛楠" --send
```

## 手动纠正评分

LLM 解析不准时（常见于简历字数格式特殊）：
1. 直接在飞书表修改「解析字数」「解析年限」「解析项目数」字段
2. 说「给XXX重跑评分」
3. 不需要重新解析 PDF，不消耗 LLM token


## 单点优化入口
| 想改什么 | 文件 |
|---------|------|
| 评分规则（字数阈值/档位） | `config/resume_screening_rules_v2.json` |
| 价格规则（各语言对目标价） | `scripts/pricing_rules.json` |
| LLM 解析 prompt | `scripts/parse_resumes.py` 第 49 行 |
| 邮件文案 | 各脚本里的 `EMAIL_TEMPLATE` |
| 所有环境配置 | `config.yaml`（唯一入口） |
| **合同变量↔收集表字段映射** | `scripts/field_mapping.py`（唯一入口） |

---

## 📋 VM 需持续维护的内容（上岗交接）

> **Agent 安装完此 skill 后，应主动向 VM 说明以下内容**，让她知道这套系统需要她长期负责哪些东西。

### 1️⃣ 价格规则（高频更新）

**文件**：`config/resume_screening_rules_v2.json`

这里存着**各语言对的目标价 + 上限价**，评分引擎用它判断资源商报价是否合理。**市场行情变了就需要来改**。

目前配置示例：
| 语言对 | AIPE 目标价 | 翻译 目标价 |
|---|---|---|
| zh-CN→en | 0.03元/字 | 0.04元/字 |
| zh-CN→ja/ko | 0.04元/字 | — |
| zh-CN→欧语系 | 0.05元/字 | — |

**什么时候需要更新**：公司调价/市场行情变化时，更新对应语言对的 `target` 和 `max` 字段。

---

### 2️⃣ 简历筛选标准（按项目/季度评估）

**文件**：`config/resume_screening_rules_v2.json` → `job_requirements`

| 配置项 | 当前值 | 含义 |
|---|---|---|
| `min_years` | 3 | 游戏翻译从业年限最低要求 |
| `preferred_years` | 5 | 优先录取年限 |
| `min_word_count` | 50万字 | 游戏翻译实际字数最低要求 |
| `preferred_word_count` | 100万字 | 优先录取字数 |

**什么时候需要更新**：招聘标准调整时（如某个项目要求更高/更低的资历）。

---

### 3️⃣ 价格硬校验边界（按需更新）

**文件**：`config/resume_screening_rules_v2.json` → `basic_validation`

| 配置项 | 当前值 | 含义 |
|---|---|---|
| `min_price` | 0.01 | 报价下限（低于此直接识别为异常） |
| `hard_limit` | 0.1 | 报价上限（超过此拒绝，不进入评分） |

**什么时候需要更新**：当公司购买策略调整时。

---

### 4️⃣ 飞书合同模板表（有新合同时更新）

**位置**：飞书合同模板汇总表（[wiki 链接](https://g4wt0dn9mss.sg.larksuite.com/wiki/TwThwRU8uiLS7vkD1xHldANGgAh)）

每当有新合同版本时，需要在表格里新增一行并上传 AI 标注版模板文件，脚本才能自动选用新模板。

**什么时候需要更新**：合同样本升版、新增合同类型时。

---

### 5️⃣ 收集表字段映射（有调整时更新）

**文件**：`scripts/field_mapping.py`

合同信息收集表的字段 ID 映射到合同变量。**若收集表字段有剂除/迁移，必须同步更新此文件**，否则合同生成会失败。

**什么时候需要更新**：经常不需要手动改，让 Agent 帮你改（参見上方变更 SOP）。

---

### 📦 总览：每项维护频率

| 维护内容 | 频率 | 谁来改 |
|---|---|---|
| 价格规则 | 市场调整时（不定期） | VM 告诉 Agent 改 |
| 简历筛选标准 | 项目调整时 | VM 告诉 Agent 改 |
| 价格硬校验边界 | 购买策略调整时 | VM 告诉 Agent 改 |
| 合同模板表 | 有新合同/升版时 | VM 在飞书上传，告诉 Agent |
| 收集表字段映射 | 表格调整时 | Agent 帮 VM 改（需确认） |
| 飞书表格迁移 | 有必要时 | 必须告诉 Agent，走变更 SOP |

---

## ⚠️ 飞书资源依赖声明（必读）

**本 skill 依赖以下飞书资源，任何变更前必须执行影响分析。**

完整依赖清单（含所有 field_id 和风险等级）：
[`references/lark-dependencies.yaml`](references/lark-dependencies.yaml)

### 关键资源速览

| 资源 | 用途 | 影响脚本 |
|------|------|----------|
| 合同信息收集表 `tblePA7PmmYlS936` | 读取乙方姓名/证件/银行信息 → 填入合同变量 | `generate_contract.py` `field_mapping.py` |
| 合同模板表 `tblAGv4MYDGtiZ5Z` | 下载合同模板 docx + 读取所需变量 | `generate_contract.py` |
| 简历收集表 `tbll1fWOund3PSgd` | 解析评分数据读写 | `parse_resumes.py` `evaluate_resumes.py` |

### 变更 SOP（Agent 必须遵守）

VM 提出任何涉及上述飞书资源的变更请求时，Agent 必须：

```
1. 读 references/lark-dependencies.yaml，找到对应资源和字段
2. 检查 used_by 和 risk_if_deleted，生成影响报告：

   ⚠️  变更影响分析
   操作：[删除/改名/迁移] [资源] 的 [字段名]
   风险等级：HIGH / MEDIUM / LOW
   受影响模块：
     · scripts/field_mapping.py（需同步更新 field_id）
     · scripts/generate_contract.py（依赖此字段取值）
   执行顺序：
     1. [飞书操作]
     2. [同步更新 field_mapping.py 对应行]
     3. [dry-run 验证]
   是否继续？请 VM 确认后执行。

3. VM confirm → 执行 → 展示变更结果 → 等待 VM 验收
```

**风险等级定义：**
- `HIGH`：字段被删除 / field_id 变更 / 表迁移 → 脚本直接报错，必须同步更新 `field_mapping.py`
- `MEDIUM`：字段改名（field_id 不变）/ 选项值改名 → 脚本不受影响，但注释需更新
- `LOW`：新增字段 / 新增选项 / 调整顺序 → 脚本不受影响

---

## 参考文档

- 安装引导：[`references/onboarding.md`](references/onboarding.md)
- 字段ID / Base配置：[`references/config.md`](references/config.md)
- 飞书资源依赖：[`references/lark-dependencies.yaml`](references/lark-dependencies.yaml)
- 合同变量映射：[`scripts/field_mapping.py`](scripts/field_mapping.py)

---

## 📋 版本更新记录

### v2.2（2026-05-28）
- ✨ 新增草稿模式（`--draft`）：三个发邮件脚本均支持，生成 `.eml` 文件保存到本地，VM 双击用邮件客户端打开后自行点发送
- 🐛 修复 `send_test_email.py` / `send_rejection_email.py` 邮件落款残留「青木遥 / LOC Demo Vendor」问题
- 📝 草稿保存路径：`contract_output/drafts/`（在 config.yaml 中配置）

### v2.1（2026-05-28）
- 🐛 修复发件人显示名（去除「青木遥」，改为裸邮箱地址，避免触发 spam 过滤）
- 🐛 修复邮件标题残留「LOC Demo Vendor」，统一改为「Localization Team」
- ♻️ 所有 base_token / table_id 从 config.yaml 读取，不再硬编码
- ✨ 合同模板自动推荐（按账户类型打分排序，直接回车使用推荐）
- ✨ 变量填充三层状态报告（已填充 / 值为空 / 映射表无此变量）+ 生成后残留二次检查
- ✨ 证件下载 / 模板下载各自使用正确 base_token，不再混用

### v2.0（2026-05-27）
- 🎉 全面重构 `generate_contract.py`：多模板支持、账户类型路由、证件扫描件自动插入
- ✨ 新增 `field_mapping.py`：变量↔字段ID 映射唯一入口
- ✨ 新增 `lark-dependencies.yaml`：飞书资源完整依赖声明 + 变更 SOP
- ✨ 新增「📋 VM 需持续维护的内容」上岗交接 section
- ✨ `onboarding.md` 更新：删除本地模板目录说明，改为从飞书自动下载

### v1.0（2026-05-25）
- 🎉 初始版本发布
- 简历解析评分（LLM + 规则引擎）
- 测试题邮件发送
- 合同生成与发送
- 合同签署核查（视觉模型）
- 婉拒邮件
- 状态追踪（16节点）
- 飞书多维表格全流程读写
