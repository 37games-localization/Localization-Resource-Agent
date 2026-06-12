---
name: loc-resume-screening
version: "2.3"
updated: "2026-06-10"
description: "本地化资源管理全流程 skill，覆盖译者简历筛选到入库的完整链路。v2 工作流可视化版：每步行动实时展示，Human Decision 节点支持对话驱动暂停-恢复。触发场景：(1) VM 首次安装配置引导；(2) 新简历入库解析评分；(3) 发测试题邮件；(4) 生成并发送合同；(5) 合同签署核查；(6) 招募状态推进；(7) 手动纠正评分；(8) 全量重算。所有操作以飞书表为单一数据源，脚本确定性执行，不依赖 AI 上下文记忆状态。"
---

# 本地化资源管理全流程

## 核心原则

- **飞书是大脑**：状态/数据全在飞书，脚本每次从表里读，不靠上下文
- **config.local.yaml 是本机唯一配置入口**：VM 从模板生成后只改这一个文件，不动脚本；`config.yaml` / `config.example.yaml` 只保留占位模板
- **LLM Key 显式配置**：解析简历前必须配置 `llm.api_key` 或 `LOC_LLM_API_KEY`，不自动读取 OpenClaw 额度
- **两阶段评分**：LLM 解析（一次性）→ 规则评分（可反复，确定性）
- **TEST_MODE 保护**：正式启用前所有邮件发到测试邮箱

## 配置与安装

VM 首次使用时，先读引导文档：[`references/onboarding.md`](references/onboarding.md)

配置验证指令（VM 说「帮我验证资源管理配置」时执行）：
```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/check_config.py
```

配置与密钥隔离规则见 [`references/config-secrets-policy.md`](references/config-secrets-policy.md)。真实 token、邮箱密码、LLM key 只允许写入 `config.local.yaml` 或环境变量，不能提交或打包。

生产表接入/迁移校验（VM 更换 Lark 表，或说「帮我检查这张资源管理表能不能用」时执行）：
```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/schema_validator.py --table all
```

如果缺少必要字段，先把差异报告告诉 VM。VM 确认后才允许自动新增字段：
```bash
python3 scripts/schema_validator.py --table all --apply --create-missing-tables
```

说明：
- `--apply` 只在 VM 确认后使用。
- `--create-missing-tables` 只会创建 schema 允许自动创建的辅助表；当前仅允许创建 `Agent流程日志`，不会自动创建候选人主表或合同敏感信息表。
- 校验通过后会生成 `config/lark-field-mapping.yaml`。工作流日志写入和待决策查询会优先读取该映射中的 base/table/field_id，缺映射时才回退旧配置。
- 字段英文 key 的业务含义见 [`references/lark-field-dictionary.md`](references/lark-field-dictionary.md)。VM 改表头或换新表时，先用这份字典确认每列存什么信息、影响哪个节点。

## 脚本速查

| 脚本 | 功能 | 触发语 |
|------|------|--------|
| `workflow_runner.py` | **v2 统一入口**：按招募状态自动调度各 v2 脚本 | 「下一步」「处理XXX」「列出候选人」 |
| `parse_resumes.py` | LLM 解析简历 PDF → 写飞书结构化字段 | 「解析简历」「新简历入库」 |
| `rescore_and_write.py` | 确定性重算评分 → 写回飞书 | 「重跑评分」「重算评分」 |
| `send_test_email.py` | 发测试题邮件 → 更新飞书状态 | 「发测试题给XXX」 |
| `generate_contract.py` | 生成合同 docx + 发邮件 → 更新飞书 | 「给XXX生成合同」「发合同」 |
| `check_signed_contract.py` | 核查签字合同 → 更新飞书状态 | 「XXX的合同已签字」 |
| `send_rejection_email.py` | 发婉拒邮件（二次确认）→ 更新飞书 | 「婉拒XXX」 |
| `update_status.py` | 手动推进招募状态 | 「把XXX状态改成XXX」 |
| `export_badcase_snapshots.py` | 导出 badcase 脱敏快照 → git push → GitHub issue | 「导出badcase」「推送badcase」 |
| `schema_validator.py` | 生产表准入校验：表头识别、缺列/多列/类型差异、生成字段映射 | 「检查这张Lark表能不能用」「更换生产表」 |
| `schema_gate.py` | 生产运行门禁：检查字段映射完整性，正式环境未通过则阻止业务执行 | 切正式环境前自动生效 |
| `run_testmode_demo.py` | 真实 TEST_MODE demo 证据采集：调用现有脚本并保存 transcript/summary | 「跑一遍真实测试demo」「录制前验证」 |
| `integration_readiness.py` | v2 分步骤集成验收：只读检查原脚本、v2包装、schema映射，不执行业务动作 | 「检查v2现在能不能进入生产验证」「做一轮集成验收」 |
| `regression_report.py` | 变更后回归报告：区分主流程影响、旁路观测、准入/QA、文档改动 | 「改完后影响哪些主流程」「出一份回归报告」 |

所有脚本优先从 skill 根目录下的 `config.local.yaml` 读取本机配置；未生成时才读取模板 `config.yaml`。

### 本地前端工作台

当 VM 说「打开资源管理工作台」或「启动前端」时，执行：

```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/start_frontend.py
```

启动后把访问地址告诉 VM，默认是 `http://127.0.0.1:3000/agent-visual`。

说明：
- 这是同一个真实工作台，不区分 demo 前端和生产前端。
- `DRY-RUN` / `TEST MODE` / `PRODUCTION` 由页面运行模式和后端脚本共同决定。
- 页面读取 `config.local.yaml`、`config/lark-field-mapping.yaml`、Lark 候选人表和 `workflow_log`。
- dry-run 不允许被前端伪装成已写回；只有 production 简历评估 checkpoint 才允许确认/修改写回。

### 生产运行门禁

`test_mode.enabled=true` 时，业务脚本不强制阻断，方便 TEST_MODE demo 和单步验证。

切正式环境后（`test_mode.enabled=false`），`run_dialog.py` 和 `workflow_runner.py` 会先调用 `schema_gate.py`。如果 `config/lark-field-mapping.yaml` 缺少候选人表、流程日志表或合同表的必需字段映射，会直接停止执行，并提示 VM 先跑：

```bash
python3 scripts/schema_validator.py --table all
python3 scripts/schema_validator.py --table all --apply --create-missing-tables
```

如需在 TEST_MODE 提前模拟正式门禁：

```bash
LOC_REQUIRE_SCHEMA_READY=1 python3 scripts/run_dialog.py waiting
```

### 真实 TEST_MODE Demo 证据采集

录制 demo 前，使用真实 Lark 测试记录和本人测试邮箱跑一遍。脚本不会伪造终端输出，会调用现有业务脚本并保存证据：

```bash
python3 scripts/run_testmode_demo.py \
  --score-record-id recXXXX --score-decision 写入 \
  --test-email-record-id recXXXX --test-file ~/Downloads/test.pdf \
  --contract-record-id recYYYY --contract-dry-run
```

输出目录默认在 `~/.loc-resume-demo-runs/YYYYMMDD-HHMMSS/`，包含：
- `summary.md`：录屏前快速确认每步 PASS/FAIL
- `transcript.jsonl`：每步命令、返回码、JSON、stdout/stderr
- `*.stdout.txt` / `*.stderr.txt`：逐步终端证据

默认要求 `test_mode.enabled=true`；正式生产模式下会拒绝运行，除非显式加 `--allow-production`。

### 分步骤集成验收

v2 的推进原则是：原脚本继续作为已验收业务底座，v2 包装层只增加可视化、checkpoint、流程日志和对话输出。进入 VM 生产验证前，先跑只读检查：

```bash
python3 scripts/integration_readiness.py
```

详细计划见 [`references/integration-validation-plan.md`](references/integration-validation-plan.md)。

字段说明见 [`references/lark-field-dictionary.md`](references/lark-field-dictionary.md)。这份文档用于生产表迁移：即使 VM 修改表头，也能知道 `candidate.score`、`workflow.output_summary`、`contract.bank_account_number` 等内部 key 分别存什么信息。

当前建议：先验收 `score` / `test-email` / `contract` 三个手动子命令；`workflow_runner.py next` 暂不作为唯一主入口，等单步骤包装稳定后再启用。

### 受控手动串联

当前阶段可以进入受控手动串联：VM 明确说候选人和节点，Agent 调用对应单点脚本执行、展示输入输出、写回 Lark，并记录过程。不要默认启用全自动 `next`。

详细 runbook：[`references/manual-chain-runbook.md`](references/manual-chain-runbook.md)

稳定版 QA 清单：[`references/stable-qa-checklist.md`](references/stable-qa-checklist.md)

### 变更后回归报告

每次开发改动后，先跑：

```bash
python3 scripts/regression_report.py
```

报告会把改动分为：
- `影响主流程`：原业务脚本、配置读取、字段映射、合同变量映射；必须跑对应单节点 dry-run/TEST_MODE。
- `旁路观测`：v2 包装、流程日志、checkpoint、统一入口、demo 采集；必须证明只复用原脚本，不接管业务判断。
- `准入/QA`：schema、field mapping、门禁、验收脚本；必须跑 schema 校验和集成验收。
- `文档/交接`：不直接影响脚本，但必须和当前行为一致。

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
| `generate_contract_v2.py` | 生成合同 + 可视化，生成后有 dialog 确认 |
| `workflow_runner.py` | **统一入口**，按招募状态路由到对应 v2 脚本 |

### workflow_runner.py 用法

```bash
# 查看候选人状态
python3 scripts/workflow_runner.py status --name "青木遥"

# 自动判断下一步并执行
python3 scripts/workflow_runner.py next --name "青木遥"
python3 scripts/workflow_runner.py next --name "青木遥" --file ~/Downloads/test.pdf

# 手动指定某一步
python3 scripts/workflow_runner.py score --name "青木遥"
python3 scripts/workflow_runner.py test-email --name "青木遥" --file ~/test.pdf
python3 scripts/workflow_runner.py contract --name "青木遥"

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
| ✅ 测试通过 / 📄 合同待生成 | `generate_contract_v2.py` |
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

VM 只需要做这两件事，其余上下文收集、推送 GitHub issue 由系统自动处理。

当前主表已具备 Badcase 回流三列：
- 「是否Badcase」→ `candidate.badcase_flag`
- 「期望结果」→ `candidate.expected_result`
- 「Badcase快照」→ `candidate.badcase_snapshot`

字段含义和当前 Field ID 见 [`references/lark-field-dictionary.md`](references/lark-field-dictionary.md)。导出脚本会从 `config/lark-field-mapping.yaml` 读取映射，不再依赖硬编码字段 ID。

手动触发导出：

```bash
python3 scripts/export_badcase_snapshots.py --dry-run  # 预览
python3 scripts/export_badcase_snapshots.py            # 正式导出并推送
```

## 手动纠正评分

LLM 解析不准时（常见于简历字数格式特殊）：
1. 直接在飞书表修改「解析字数」「解析年限」「解析项目数」字段
2. 说「给XXX重跑评分」
3. 不需要重新解析 PDF，不消耗 LLM token


## 单点优化入口
| 想改什么 | 文件 |
|---------|------|
| 评分规则（含字数阈值/档位/各语言对价格范围） | `config/resume_screening_rules_v2.json` |
| LLM 解析 prompt | `scripts/parse_resumes.py` 第 49 行 |
| 邮件文案 | 各脚本里的 `EMAIL_TEMPLATE` |
| 所有环境配置 | `config.local.yaml`（本机唯一入口，由 `config.example.yaml` 复制生成） |
| **合同变量↔收集表字段映射** | `scripts/field_mapping.py`（唯一入口） |

---

## 📋 VM 需持续维护的内容（上岗交接）

> **Agent 安装完此 skill 后，应主动向 VM 说明以下内容**，让她知道这套系统需要她长期负责哪些东西。

### 1️⃣ 价格规则（高频更新）

**文件**：`config/resume_screening_rules_v2.json`

这里存着**各语言对的目标价 + 上限价**，评分引擎用它判断资源商报价是否合理。**市场行情变了就需要来改**。
`scripts/pricing_rules.json` 仅保留为历史/参考文件；主评分流程默认读取本文件中的 `price_rules`。

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

**位置**：飞书合同模板汇总表（由项目维护人提供链接和权限）

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

- 安装引导：[`references/onboarding.md`](references/onboarding.md)
- 字段ID / Base配置：[`references/config.md`](references/config.md)
- 飞书资源依赖：[`references/lark-dependencies.yaml`](references/lark-dependencies.yaml)
- 合同变量映射：[`scripts/field_mapping.py`](scripts/field_mapping.py)

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
- ✨ 新增 `export_badcase_snapshots.py`：脱敏快照导出 + git push + GitHub issue 自动创建
- ✨ 本机配置新增 `badcase_export` 和 `github` 配置块
- 📝 onboarding 增加 badcase 使用说明

### v2.2（2026-05-28）
- ✨ 新增草稿模式（`--draft`）：三个发邮件脚本均支持，生成 `.eml` 文件保存到本地，VM 双击用邮件客户端打开后自行点发送
- 🐛 修复 `send_test_email.py` / `send_rejection_email.py` 邮件落款残留「青木遥 / LOC Demo Vendor」问题
- 📝 草稿保存路径：`contract_output/drafts/`（在 config.local.yaml 中配置）

### v2.1（2026-05-28）
- 🐛 修复发件人显示名（去除「青木遥」，改为裸邮箱地址，避免触发 spam 过滤）
- 🐛 修复邮件标题残留「LOC Demo Vendor」，统一改为「Localization Team」
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
