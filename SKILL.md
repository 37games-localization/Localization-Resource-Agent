---
name: loc-resume-screening
version: "2.8"
updated: "2026-06-15"
description: "本地化资源管理全流程 skill，覆盖译者简历筛选到入库的完整链路。v2 工作流可视化版：每步行动实时展示，Human Decision 节点支持对话驱动暂停-恢复。触发场景：(1) VM 首次安装配置引导；(2) 新简历入库解析评分；(3) 发测试题邮件；(4) 发送签约信息收集邮件；(5) 生成并发送合同；(6) 合同签署核查；(7) 招募状态推进；(8) 手动纠正评分；(9) 全量重算。所有操作以飞书表为单一数据源，脚本确定性执行，不依赖 AI 上下文记忆状态。"
---

# 本地化资源管理全流程

## 核心原则

- **飞书是大脑**：状态/数据全在飞书，脚本每次从表里读，不靠上下文
- **config.local.yaml 是本机唯一配置入口**：首次安装由 Agent 从模板生成并引导 VM 填写，只改这一个本机文件，不动脚本；`config.yaml` / `config.example.yaml` 只保留占位模板
- **LLM Key 显式配置**：解析简历前必须配置 `llm.api_key` 或 `LOC_LLM_API_KEY`，不自动读取 OpenClaw 额度
- **两阶段评分**：LLM 解析（一次性）→ 规则评分（可反复，确定性）
- **TEST_MODE 保护**：正式启用前所有邮件发到测试邮箱
- **日常使用不改核心流程**：VM 的日常指令只允许配置、运行、查看、写回、标记 Badcase 和调整 Lark 数据/规则；不得直接修改核心脚本、评分引擎、workflow 路由、前端/API 或仓库结构

## 配置与安装

VM 首次使用时，默认对 Agent 说「帮我完成资源管理 Agent 初始化配置」。Agent 必须先读引导文档 [`references/onboarding.md`](references/onboarding.md)，再一步步带 VM 完成配置、验证、锁定和功能展示。

配置验证指令（VM 说「帮我验证资源管理配置」时执行）：
```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/check_config.py
```

安装保护指令（配置验证通过后执行一次）：
```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/lock_user_install.py
```

说明：
- 该脚本会把核心脚本、前端源码/配置、引用文档和规则模板设为只读，并禁用当前 checkout 的 `git push`。
- 它不会锁定 `config.local.yaml`、`config.yaml`、`config/lark-field-mapping.yaml`，不影响 VM 配置和 Lark 表映射。
- 如果 VM 需要修改核心流程，不要解锁；请标记 Badcase 或联系项目维护者。

配置与密钥隔离规则见 [`references/config-secrets-policy.md`](references/config-secrets-policy.md)。真实 token、邮箱密码、LLM key 只允许写入 `config.local.yaml` 或环境变量，不能提交或打包。

生产表接入/迁移校验（VM 更换 Lark 表，或说「帮我检查这张资源管理表能不能用」时执行）：
```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/schema_mapping_checkpoint.py propose --table all
```

如果缺少必要字段，先把 checkpoint 中的缺失字段、疑似映射和字段用途展示给 VM。VM 确认需要新增字段后，才允许补齐缺失列并重新生成 checkpoint：
```bash
python3 scripts/schema_mapping_checkpoint.py propose --table all --create-missing-fields --yes
```

说明：
- `propose` 只生成 checkpoint，不会保存字段映射。
- 如 VM 认为疑似映射不正确，按 VM 描述调整：`python3 scripts/schema_mapping_checkpoint.py adjust --token <checkpoint_token> --note "把 candidate.resume 映射到 简历附件"`。
- VM 确认映射无误后，才运行：`python3 scripts/schema_mapping_checkpoint.py confirm --token <checkpoint_token>`。
- `confirm` 后才会生成或刷新 `config/lark-field-mapping.yaml`。工作流日志写入和待决策查询会优先读取该映射中的 base/table/field_id，缺映射时才回退旧配置。
- 字段英文 key 的业务含义见 [`references/lark-field-dictionary.md`](references/lark-field-dictionary.md)。VM 改表头或换新表时，先用这份字典确认每列存什么信息、影响哪个节点。

## 脚本速查

| 脚本 | 功能 | 触发语 |
|------|------|--------|
| `workflow_runner.py` | **v2 统一入口**：按招募状态自动调度各 v2 脚本 | 「下一步」「处理XXX」「列出候选人」 |
| `parse_resumes.py` | LLM 解析简历 PDF → 写飞书结构化字段 | 「解析简历」「新简历入库」 |
| `rescore_and_write.py` | 确定性重算评分 → 写回飞书 | 「重跑评分」「重算评分」 |
| `send_test_email.py` | 发测试题邮件 → 更新飞书状态 | 「发测试题给XXX」 |
| `send_contract_info_email_v2.py` | 发送签约信息收集邮件 → 更新飞书状态 | 「给XXX发签约信息收集」「收集XXX合同信息」 |
| `generate_contract.py` | 生成合同 docx + 发邮件 → 更新飞书 | 「给XXX生成合同」「发合同」 |
| `check_signed_contract.py` | 核查签字合同 → 更新飞书状态 | 「XXX的合同已签字」 |
| `send_rejection_email.py` | 发婉拒邮件（二次确认）→ 更新飞书 | 「婉拒XXX」 |
| `update_status.py` | 手动推进招募状态 | 「把XXX状态改成XXX」 |
| `export_badcase_snapshots.py` | VM 侧导出脱敏快照并默认创建 GitHub issue | 「导出badcase」「推送badcase」 |
| `push_badcase_issues.py` | 从本地 snapshot 补推统一格式 GitHub issue | 维护补推 |
| `schema_mapping_checkpoint.py` | 生产表准入校验：表头识别、缺列/疑似匹配/类型差异，VM 确认后保存字段映射 | 「检查这张Lark表能不能用」「更换生产表」 |
| `schema_validator.py` | 底层只读 schema 校验引擎，供 checkpoint 使用 | 维护排查 |
| `schema_gate.py` | 生产运行门禁：检查字段映射完整性，正式环境未通过则阻止业务执行 | 切正式环境前自动生效 |
| `lock_user_install.py` | 锁定用户安装：核心文件只读，禁用误 push | 初始化配置完成后 |
| `verify_pricing_rule_coverage.py` | 读取 Lark 评分规则表，检查 22 个主流市场语言对是否齐全 | 「检查评分规则语种覆盖」 |

所有脚本优先从 skill 根目录下的 `config.local.yaml` 读取本机配置；未生成时才读取模板 `config.yaml`。

### 本地前端工作台

当 VM 说「打开资源管理工作台」或「启动前端」时，执行：

```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/start_frontend.py
```

启动后把访问地址告诉 VM，默认是 `http://127.0.0.1:3000/agent-visual`。

说明：
- 这是同一个真实工作台。
- `DRY-RUN` / `TEST MODE` / `PRODUCTION` 由页面运行模式和后端脚本共同决定。
- 页面读取 `config.local.yaml`、`config/lark-field-mapping.yaml`、Lark 候选人表和 `workflow_log`。
- dry-run 不允许被前端伪装成已写回；只有 production 简历评估 checkpoint 才允许确认/修改写回。

### 操作边界

当 VM 要求“改逻辑”“改脚本”“改评分引擎”“改工作流”“改前端/API”“直接修代码”时，不要直接修改仓库文件。应先把问题标记为 Badcase 或生成问题说明，交由项目维护者处理。

允许 VM 日常执行的变更：
- 修改 `config.local.yaml` 中的本机配置。
- 运行 `schema_mapping_checkpoint.py` 检查字段映射；在 checkpoint 展示缺失字段后，经 VM 确认再补齐允许自动创建的 Lark 辅助字段。
- 调整 Lark 里的候选人数据、评分规则、合同信息、合同模板记录。
- 标记 Badcase、填写期望结果、导出脱敏快照。
- 运行 `lock_user_install.py` 锁定安装目录。

不允许 VM 日常直接执行的变更：
- 修改 `scripts/` 下的核心业务脚本、评分引擎、workflow 路由。
- 修改 `frontend/`、API、仓库结构或依赖版本。
- 执行 `git commit`、`git push`、删除文件、重写历史。

如果确实需要改核心流程，先停止当前业务操作，并提示 VM 联系项目维护者。

### 生产运行门禁

`test_mode.enabled=true` 时，业务脚本不强制阻断，方便 TEST_MODE 和单步验证。

切正式环境后（`test_mode.enabled=false`），`run_dialog.py` 和 `workflow_runner.py` 会先调用 `schema_gate.py`。如果 `config/lark-field-mapping.yaml` 缺少候选人表、流程日志表或合同表的必需字段映射，会直接停止执行，并提示 VM 先跑：

```bash
python3 scripts/schema_mapping_checkpoint.py propose --table all
python3 scripts/schema_mapping_checkpoint.py adjust --token <checkpoint_token> --note "把 candidate.resume 映射到 简历附件"
python3 scripts/schema_mapping_checkpoint.py confirm --token <checkpoint_token>
```

如需在 TEST_MODE 提前模拟正式门禁：

```bash
LOC_REQUIRE_SCHEMA_READY=1 python3 scripts/run_dialog.py waiting
```

### 受控手动串联

当前阶段可以进入受控手动串联：VM 明确说候选人和节点，Agent 调用对应单点脚本执行、展示输入输出、写回 Lark，并记录过程。不要默认启用全自动 `next`。

如果候选人、附件、合同信息或目标状态不明确，必须停下来询问 VM，不允许猜测执行。

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
python3 scripts/parse_resumes.py --name "测试候选人A"

# 全量重算评分
python3 scripts/rescore_and_write.py

# 指定候选人评分
python3 scripts/rescore_and_write.py --name "测试候选人A"

# 先预览再执行（所有脚本都支持 --dry-run）
python3 scripts/generate_contract.py --name "测试候选人B" --dry-run
python3 scripts/generate_contract.py --name "测试候选人B" --send
```

## v2 工作流可视化版

### v2 脚本说明

所有 `*_v2.py` 脚本都接入了 `workflow_engine.py`，提供：
- **行动可视化**：每一步的输入/输出实时打印到终端，操作有据可查
- **Human Decision 节点**：关键步骤可以暂停，等待人类确认后再继续
- **飞书流程日志**：每步执行记录写入飞书流程日志表（可关闭）

| 脚本 | 功能 |
|------|------|
| `rescore_and_write_v2.py` | 评分写回 + 可视化，支持 `--interactive` 交互确认 |
| `send_test_email_v2.py` | 发测试题 + 可视化，发送前有 dialog 确认 |
| `send_contract_info_email_v2.py` | 签约信息收集邮件 + 可视化，默认生成草稿 |
| `generate_contract_v2.py` | 生成合同 + 可视化，生成后有 dialog 确认 |
| `workflow_runner.py` | **统一入口**，按招募状态路由到对应 v2 脚本 |

### workflow_runner.py 用法

```bash
# 查看候选人状态
python3 scripts/workflow_runner.py status --name "测试候选人A"

# 自动判断下一步并执行
python3 scripts/workflow_runner.py next --name "测试候选人A"
python3 scripts/workflow_runner.py next --name "测试候选人A" --file ~/Downloads/test.pdf

# 手动指定某一步
python3 scripts/workflow_runner.py score --name "测试候选人A"
python3 scripts/workflow_runner.py test-email --name "测试候选人A" --file ~/test.pdf
python3 scripts/workflow_runner.py contract-info-email --name "测试候选人A"
python3 scripts/workflow_runner.py contract --name "测试候选人A"

# 恢复 dialog checkpoint
python3 scripts/workflow_runner.py resume --token ckpt-xxx --decision "写入"

# 列出所有候选人 + 状态
python3 scripts/workflow_runner.py list
```

### next 自动路由规则

| 当前招募状态 | 自动调用 |
|------------|----------|
| 📋 简历待筛选 / 🔍 初筛中 / ✅ 初筛通过 | `rescore_and_write_v2.py --interactive` |
| 📝 测试题待发 | `send_test_email_v2.py --file <pdf>`（需 `--file`）|
| ✅ 测试通过 | `send_contract_info_email_v2.py` |
| 📄 合同待生成 | `generate_contract_v2.py` |
| 其他状态 | 打印当前状态 + 人工操作说明 |

### dialog 模式工作原理

1. Agent 调用 `workflow_runner.py next`，v2 脚本在关键决策节点触发 `checkpoint(mode="dialog")`
2. 脚本打印 checkpoint 信息（含 `token=ckpt-xxx`）后**退出等待，不阻塞终端**
3. 用户/对话 Agent 查看信息后，回复决策（如「写入」「跳过」）
4. 对话 Agent 调用 `workflow_runner.py resume --token ckpt-xxx --decision "写入"` 恢复执行
5. checkpoint 文件存储在 `~/.loc-resume-checkpoints/` 目录

### 回滚方法

如需切回无可视化的原版脚本：

```bash
git checkout main
```

---

## Badcase 回流

使用过程中遇到 agent 判断不对，直接说：

```
把这个标成 badcase，应该进人工复核，不该直接婉拒
把 XXX 标成 badcase，合同应该用个人版模板
把刚才那封邮件标成 badcase，语气太硬
```

或者直接在飞书主表「是否Badcase」列选「⚠️ 是」，可选填「期望结果」一句话说明。

VM 只需要做这两件事，其余上下文收集、脱敏 snapshot 生成和 GitHub issue 创建由系统自动处理。

当前主表至少需要 Badcase 回流两列：
- 「是否Badcase」→ `candidate.badcase_flag`
- 「期望结果」→ `candidate.expected_result`

「Badcase快照」附件列仅作为旧流程兼容字段，不再是默认上报必需字段。

字段含义和当前 Field ID 见 [`references/lark-field-dictionary.md`](references/lark-field-dictionary.md)。导出脚本会从 `config/lark-field-mapping.yaml` 读取映射，不再依赖硬编码字段 ID。

手动触发导出：

```bash
python3 scripts/export_badcase_snapshots.py --dry-run  # 预览 GitHub issue
python3 scripts/export_badcase_snapshots.py            # 正式创建 GitHub issue
```

如需从本地 snapshot 补推 GitHub issue：

```bash
python3 scripts/push_badcase_issues.py --snapshot badcase_xxx.json --dry-run
python3 scripts/push_badcase_issues.py --snapshot badcase_xxx.json
```

Badcase 回流必须遵守统一协议：

- VM 侧只生成 `snapshot_version=2.0` 的脱敏 JSON。
- 项目侧只允许从 snapshot 生成 issue，不允许不同 Agent 自由拼标题和正文。
- issue 标题、正文、label 由 `scripts/badcase_protocol.py` 统一生成。
- snapshot 校验失败时必须跳过，不允许强行上传/开 issue。
- 禁止包含真实姓名、邮箱、电话、证件号、银行账号、原始简历全文、合同正文、API key、SMTP 密码、Lark/GitHub token。

## 手动纠正评分

LLM 解析不准时（常见于简历字数格式特殊）：
1. 直接在飞书表修改「解析字数」「解析年限」「解析项目数」字段
2. 说「给XXX重跑评分」
3. 不需要重新解析 PDF，不消耗 LLM token


## 单点调整入口

| 想改什么 | VM 应该怎么做 |
|---------|------|
| 价格规则（各语言对目标价/上限价） | 修改飞书「评分规则配置」表 |
| 候选人解析字段、评分输入字段 | 修改候选人所在 Lark 行，然后重跑评分 |
| 合同信息、银行信息、证件信息 | 修改合同信息收集表对应行 |
| 合同模板 | 在飞书合同模板表维护模板记录 |
| 本机环境配置 | 修改 `config.local.yaml` |
| 表头变化 / 换表 | 让 Agent 运行 `schema_mapping_checkpoint.py` 生成 checkpoint，VM 确认后保存字段映射 |
| prompt、邮件文案、评分引擎、核心脚本、前端/API | 不允许 VM 日常直接修改；请标记 Badcase 或联系项目维护者 |

---

## 📋 VM 需持续维护的内容（上岗交接）

> **Agent 安装完此 skill 后，应主动向 VM 说明以下内容**，让她知道这套系统需要她长期负责哪些东西。

### 1️⃣ 价格规则（高频更新）

**生产来源**：飞书「评分规则配置」表。该表是独立规则资产，可通过 `pricing_rules.base_token/table_id` 单独配置；VM 更换简历收集表时，不需要默认重建评分规则表。

这里存着**各语言对的目标价 + 上限价**，评分引擎用它判断资源商报价是否合理。**市场行情变了就需要来改**。
包内 `config/resume_screening_rules_v2.json` 仅作为 TEST_MODE / 显式 `--allow-local-rules` 的测试 fallback；生产评分缺 Lark 规则表、缺字段、缺语言对时必须阻断。

目前配置示例：
| 语言对 | AIPE 目标价 | 翻译 目标价 |
|---|---|---|
| zh-CN→en | 0.03元/字 | 0.04元/字 |
| zh-CN→ja/ko | 0.04元/字 | — |
| zh-CN→欧语系 | 0.05元/字 | — |

**什么时候需要更新**：公司调价/市场行情变化时，更新飞书规则表对应语言对的 AIPE/翻译预期价和上限价。

---

### 2️⃣ 简历筛选标准（按项目/季度评估）

简历筛选标准由当前 Agent 版本内置。VM 日常不要直接修改本地规则文件；如果项目招聘标准变化，请标记 Badcase 或联系项目维护者调整版本。

| 配置项 | 当前值 | 含义 |
|---|---|---|
| `min_years` | 3 | 游戏翻译从业年限最低要求 |
| `preferred_years` | 5 | 优先录取年限 |
| `min_word_count` | 50万字 | 游戏翻译实际字数最低要求 |
| `preferred_word_count` | 100万字 | 优先录取字数 |

**什么时候需要反馈**：招聘标准调整时（如某个项目要求更高/更低的资历）。

---

### 3️⃣ 价格硬校验边界（按需更新）

价格硬校验边界由当前 Agent 版本内置。VM 日常不要直接修改本地规则文件；如果购买策略变化，请标记 Badcase 或联系项目维护者调整版本。

| 配置项 | 当前值 | 含义 |
|---|---|---|
| `min_price` | 0.01 | 报价下限（低于此直接识别为异常） |
| `hard_limit` | 0.1 | 报价上限（超过此拒绝，不进入评分） |

**什么时候需要反馈**：当公司购买策略调整时。

---

### 4️⃣ 飞书合同模板表（有新合同时更新）

**位置**：飞书合同模板汇总表（由项目维护人提供链接和权限）

每当有新合同版本时，需要在表格里新增一行并上传 AI 标注版模板文件，脚本才能自动选用新模板。

**什么时候需要更新**：合同样本升版、新增合同类型时。

---

### 5️⃣ 收集表字段映射（有调整时更新）

合同信息收集表的字段 ID 映射到合同变量。若收集表字段有删除、改名或迁移，VM 不要手动改脚本；请让 Agent 运行表结构校验，并在确认后重新生成字段映射。

**什么时候需要更新**：经常不需要手动改。表结构变化时，让 Agent 先检查差异，再由 VM 确认是否生成新映射。

---

### 📦 总览：每项维护频率

| 维护内容 | 频率 | 谁来改 |
|---|---|---|
| 价格规则 | 市场调整时（不定期） | VM 在飞书规则表调整 |
| 简历筛选标准 | 项目调整时 | VM 标记 Badcase / 联系维护者 |
| 价格硬校验边界 | 购买策略调整时 | VM 标记 Badcase / 联系维护者 |
| 合同模板表 | 有新合同/升版时 | VM 在飞书上传，告诉 Agent |
| 收集表字段映射 | 表格调整时 | Agent 跑校验并生成映射（需确认） |
| 飞书表格迁移 | 有必要时 | 必须告诉 Agent，走变更 SOP |

---

## ⚠️ 飞书资源依赖声明（必读）

**本 skill 依赖以下飞书资源，任何变更前必须执行影响分析。**

完整依赖清单（含所有 field_id 和风险等级）：
[`references/lark-dependencies.yaml`](references/lark-dependencies.yaml)

### 关键资源速览

| 资源 | 用途 | 影响脚本 |
|------|------|----------|
| 合同信息收集表 `<contract_table_id>` | 读取乙方姓名/证件/银行信息 → 填入合同变量 | `generate_contract.py` `field_mapping.py` |
| 合同模板表 `<template_table_id>` | 下载合同模板 docx + 读取所需变量 | `generate_contract.py` |
| 简历收集表 `<resume_table_id>` | 解析评分数据读写 | `parse_resumes.py` `rescore_and_write.py` |

### 变更 SOP（Agent 必须遵守）

VM 提出任何涉及上述飞书资源的变更请求时，Agent 必须：

```
1. 读 references/lark-dependencies.yaml，找到对应资源和字段
2. 检查 used_by 和 risk_if_deleted，生成影响报告：

   ⚠️  变更影响分析
   操作：[删除/改名/迁移] [资源] 的 [字段名]
   风险等级：HIGH / MEDIUM / LOW
   受影响模块：
     · config/lark-field-mapping.yaml（需重新生成字段映射）
     · scripts/generate_contract.py（依赖此字段取值）
   执行顺序：
     1. [飞书操作]
     2. [重新运行 schema_mapping_checkpoint.py 生成 checkpoint，确认后保存字段映射]
     3. [dry-run 验证]
   是否继续？请 VM 确认后执行。

3. VM confirm → 执行 → 展示变更结果 → 等待 VM 验收
```

**风险等级定义：**
- `HIGH`：字段被删除 / field_id 变更 / 表迁移 → 脚本直接报错，必须重新生成字段映射
- `MEDIUM`：字段改名（field_id 不变）/ 选项值改名 → 脚本不受影响，但注释需更新
- `LOW`：新增字段 / 新增选项 / 调整顺序 → 脚本不受影响

---

---

## 对话驱动模式（生产使用）

当用户说以下任意触发语时，使用对话驱动模式，不要让用户手动执行命令行。

> **核心脚本**：`scripts/run_dialog.py`
> **执行目录**：`cd ~/.agents/skills/loc-resume-screening`

### 触发语 → 操作映射

| 用户说 | AI 做 |
|--------|-------|
| 「处理XXX」「帮我处理XXX」「下一步 XXX」 | 调用 `run_dialog.py score --name "XXX"`，根据招募状态自动路由 |
| 「评分XXX」「重算XXX的分」 | 调用 `run_dialog.py score --name "XXX"` |
| 「发测试题给XXX」 | 调用 `run_dialog.py test-email --name "XXX" --file <最近用过的附件>` |
| 「给XXX发签约信息收集」「收集XXX合同信息」 | 调用 `run_dialog.py contract-info-email --name "XXX"` |
| 「给XXX生成合同」「发合同给XXX」 | 调用 `run_dialog.py contract --name "XXX"` |
| 「列出候选人」「看看现在都到哪步了」 | 调用 `workflow_runner.py list` |
| 「XXX的状态」「XXX到哪步了」 | 调用 `workflow_runner.py status --name "XXX"` |
| 「有哪些候选人在等我决策」「有哪些在等我」 | 调用 `run_dialog.py waiting`，列出流程日志表 `status=waiting` 的 checkpoint |
| 「继续处理XXX」「继续XXX」「继续刚才那个」 | 先调用 `run_dialog.py waiting`，按 `record_id`/姓名/昵称找到对应 token，再调用 `run_dialog.py resume --token <token> --decision "<用户决策>"` |

### AI 执行流程

1. 解析用户意图，提取候选人姓名
2. 调用 `python3 scripts/run_dialog.py <操作> --name "XXX"`
3. 解析 JSON 输出：
   - `status=checkpoint`：把 summary 格式化成自然语言告诉用户，问 options 里的选项
   - `status=done`：把 message 告诉用户
   - `status=error`：报告错误，建议用户检查配置
4. 用户回复决策后：调用 `python3 scripts/run_dialog.py resume --token <token> --decision "<用户回复>"`
5. 重复 3-4 直到 status=done

### 待决策恢复规则

当用户问「有哪些在等我」时：

```bash
python3 scripts/run_dialog.py waiting
```

当用户说「继续处理XXX」但当前对话上下文里没有 checkpoint token 时：

1. 调用 `run_dialog.py waiting`
2. 从返回的 `waiting[]` 中优先按 `candidate_record_id` 匹配；没有 record_id 时再按姓名/昵称匹配
3. 若唯一匹配，取 `token` 调用 `run_dialog.py resume`
4. 若多条匹配，先让用户确认候选人/节点，不要猜

流程日志表中 `run_id` 必须保持本次 workflow run ID；checkpoint token 写入 `output_summary` JSON 的 `checkpoint_token` 字段。本地 checkpoint 文件仍负责唤醒后台脚本。

### JSON 输出格式

**checkpoint 状态（等待用户决策）：**
```json
{
  "status": "checkpoint",
  "checkpoint_token": "ckpt-xxx",
  "node": "确认写入飞书",
  "candidate": "李全鸿",
  "summary": {
    "total_score": "100/100",
    "tier": "S",
    "suggestion": "优先录用"
  },
  "options": ["写入", "跳过", "退出"],
  "raw_output": "..."
}
```

**done 状态（流程完成）：**
```json
{
  "status": "done",
  "candidate": "李全鸿",
  "message": "决策「写入」已执行，后台任务完成",
  "raw_output": "..."
}
```

**waiting 状态（待决策列表）：**
```json
{
  "status": "done",
  "message": "当前有 1 条待决策记录",
  "waiting": [
    {
      "token": "ckpt-run-xxx",
      "candidate_name": "李全鸿",
      "step_name": "确认写入飞书",
      "status": "waiting",
      "input_summary": "{...}"
    }
  ]
}
```

**error 状态（出错）：**
```json
{
  "status": "error",
  "message": "错误原因",
  "raw_output": "..."
}
```

### 示例对话

```
用户：帮我处理李全鸿
AI 调用：python3 scripts/run_dialog.py score --name "李全鸿"
AI 回复：评分完成，李全鸿总分 100/100，档位 S，优先录用。是否写入飞书？[写入/跳过/退出]

用户：写入
AI 调用：python3 scripts/run_dialog.py resume --token ckpt-xxx --decision "写入"
AI 回复：✅ 已写入飞书，李全鸿档位 S，优先录用。
```

### 注意事项

- 所有调用都在 `cd ~/.agents/skills/loc-resume-screening` 下执行
- 不要把原始命令行输出粘给用户，要转成自然语言
- checkpoint 的 token 要记在当前对话上下文里，不要丢失
- TEST_MODE 下邮件发到测试邮箱，要告知用户
- `score` 操作约需 10-30 秒，可告知用户「正在评分，请稍候」


## 参考文档

- 安装引导：[`references/onboarding.md`](references/onboarding.md)（VM 首次配置）
- 字段ID / Base配置：[`references/config.md`](references/config.md)（配置排错 / 换表）
- 字段用途字典：[`references/lark-field-dictionary.md`](references/lark-field-dictionary.md)（表头变更 / 字段含义）
- 飞书资源依赖：[`references/lark-dependencies.yaml`](references/lark-dependencies.yaml)（飞书表或合同字段变更）
- 合同变量映射：[`scripts/field_mapping.py`](scripts/field_mapping.py)（合同变量维护）

---

## 📋 版本更新记录

### v2.4（2026-06-10）
- ✨ 新增 `run_dialog.py`：对话驱动层核心脚本，AI 调用后获得结构化 JSON，自动转化为自然语言与用户交互
- ✨ `run_dialog.py` 支持 `score` / `test-email` / `contract` / `resume` 四个子命令
- ✨ `score` 子命令以后台方式运行评分，捕获 `⏸ [CHECKPOINT]` 行提取 token 和 summary
- ✨ `resume` 子命令将用户决策写入 checkpoint 文件，让后台脚本继续执行
- 📝 SKILL.md 新增「对话驱动模式（生产使用）」section，含触发语映射、AI 执行流程、JSON 格式说明

### v2.3（2026-06-10）
- ✨ 新增 `workflow_runner.py`：v2 工作流统一入口，支持 `status` / `next` / `score` / `test-email` / `contract` / `resume` / `list` 7 个子命令
- ✨ `next` 子命令根据飞书招募状态自动路由到对应 v2 脚本，进程隔离调用（subprocess）
- ✨ `resume` 子命令支持 dialog checkpoint 恢复，对话 Agent 可将用户决策写回工作流
- 📝 SKILL.md 补充『v2 工作流可视化版』说明段落

### v2.3（2026-06-05）
- ✨ 新增 badcase 回流能力：飞书主表加「是否Badcase」+「期望结果」两个字段
- ✨ 新增 `export_badcase_snapshots.py`：脱敏快照导出，默认创建 GitHub issue；Lark 附件上传仅作为显式兼容选项
- ✨ 本机配置新增 `badcase_export` 和 `github` 配置块
- 📝 onboarding 增加 badcase 使用说明

### v2.2（2026-05-28）
- ✨ 新增草稿模式（`--draft`）：三个发邮件脚本均支持，生成 `.eml` 文件保存到本地，VM 双击用邮件客户端打开后自行点发送
- 🐛 修复 `send_test_email.py` / `send_rejection_email.py` 邮件落款残留个人姓名 / 旧供应商主体信息问题
- 📝 草稿保存路径：`contract_output/drafts/`（在 config.local.yaml 中配置）

### v2.1（2026-05-28）
- 🐛 修复发件人显示名（去除个人姓名，改为裸邮箱地址，避免触发 spam 过滤）
- 🐛 修复邮件标题残留旧供应商主体信息，统一改为团队级别标题
- ♻️ 所有 base_token / table_id 从本机配置读取，不再硬编码
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
