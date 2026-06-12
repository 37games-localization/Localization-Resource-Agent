# 资源管理 Agent v0.1 交接说明

> 适用分支：`v2-workflow-viz`
> 当前冻结点：`v0.1 单节点 QA 通过版`
> 更新日期：2026-06-12

## 当前结论

## 本窗口默认工程化多 Agent 协同协议

后续在本窗口处理资源管理 Agent 的代码、前端、工作流、README、治理、eval、trace/span、Lark mapping 或发布相关任务时，默认按工程化多 Agent 协同方式执行，不需要 penny 每次单独提醒。

默认角色：

- **目标守门 Agent**：复核本轮是否偏离真实目标，尤其检查是否误改核心流程、是否把前端 Demo 当成真实 workflow、是否把 Lark 事实来源替换成上下文记忆。
- **实现 Agent**：负责具体代码、文档、前端、脚本和配置修改，优先复用已验收单点脚本，不重新发明业务逻辑。
- **QA / 治理 Agent**：负责回归、隐私、schema、eval、trace/span、README 口径和发布边界检查，明确哪些改动影响主流程，哪些只是旁路观测或前端展示。

默认边界：

- 不重构已有主流程，除非明确确认主流程本身不满足需求。
- 单点能力必须可独立调用，也可以被流程或前端 wrapper 组合调用。
- Lark 是业务状态、输入、输出、checkpoint 和 workflow_log 的事实来源。
- 前端是消费层 / 操作层，不伪造真实 workflow，不接管评分、合同选择、邮件生成等业务判断。
- dry-run、TEST_MODE、生产环境共用同一套前端和入口；差异只来自后端执行模式与写回权限。
- 每次对外或给 VM 的文案必须区分“已验证”“需生产验证”“仅旁路观测”，不能为了汇报夸大成熟度。

QA / 治理默认包含：

- **隐私扫描**：检查 README、handover、QA 报告、badcase、前端默认文案中是否出现真实姓名、邮箱、本地路径、Lark 表/记录 ID、API key、合同编号等敏感信息。
- **schema 准入**：涉及 Lark 表、字段映射、配置切换、生产表迁移时，默认纳入 `schema_validator.py --table all` 或等价检查。
- **主流程回归**：涉及业务脚本、评分规则、合同模板选择、邮件发送、状态推进时，默认纳入单元测试、集成验收或对应单节点 dry-run / TEST_MODE。
- **eval / regression report**：涉及已验收能力、Router、mapping、trace/span 或发版时，默认运行或更新 eval / regression report，并说明 pass / fail / changed / needs-production-validation。
- **trace/span 审计**：涉及过程可见、前端执行流、badcase 回流、checkpoint 时，默认检查是否保留 run_id/span 证据、是否可回放、是否脱敏。

每次收尾默认说明：

- 这次有没有改核心流程。
- 哪些只是旁路观测 / 前端展示 / 文档口径。
- 已跑哪些验证；哪些因为缺少真实 Lark/SMTP/LLM/生产权限没有跑，不能声称完成。
- 是否影响 VM 安装、自然语言唤起和现有单点能力。

当前版本已经完成本地 `v0.1` 分组冻结提交，可作为单节点稳定版继续交接。

已确认：

- 单节点能力可独立调用：评分、测试题邮件、合同生成、签字合同核查、状态推进、婉拒邮件、Badcase 导出。
- Lark 仍是唯一事实来源：状态、输入、输出、流程日志都应落在 Lark，不依赖 LLM 上下文记忆。
- 原业务脚本仍是执行层：v2 包装层只提供过程可见、checkpoint、日志和 Demo 证据，不接管业务判断。
- `workflow_runner next` 保留，但不是默认生产入口。
- 当前推荐使用方式是受控手动串联：VM 明确指定候选人和节点，Agent 调用对应单点脚本执行。

不要把当前版本表述为“已经可以无人值守跑完整链路”。更准确的说法是：核心单点能力已通过 QA，可以进入 VM 生产验证和过程可见层建设。

注意：workflow_log / 流程日志用于过程观察、恢复和审计；候选人状态、合同信息、评分结果等业务事实仍以对应 Lark 主表为准。

## 必读顺序

1. `SKILL.md`
   了解 Agent 的触发语、核心原则、安装配置和脚本速查。

2. `references/v0.1-freeze-review-2026-06-11.md`
   了解本地冻结范围、A/B/C/D 四组提交和剩余风险。

3. `references/single-node-qa-report-2026-06-11.md`
   了解已验证的单节点能力、测试候选人、测试附件和验证结果。

4. `references/manual-chain-runbook.md`
   了解当前推荐的“受控手动串联”执行方式。

5. `references/lark-field-dictionary.md`
   了解字段英文 key、业务含义、读写方和影响节点。VM 换表或改表头前必须看这份。

6. `references/stable-qa-checklist.md`
   了解稳定版 QA 清单、暂缓能力和前端可读字段。

## 当前提交

最近四个提交构成 `v0.1` 冻结主体：

```text
caf965b chore: isolate local config and setup checks
0719107 feat: add lark schema validation gates
a889386 fix: harden single-node workflow scripts
f77e1ac feat: add workflow visibility and qa docs
```

含义：

- A 组：配置安全与安装门禁。
- B 组：Lark 表结构准入与字段映射治理。
- C 组：单节点业务脚本稳定性修复。
- D 组：过程可见层、Demo 工具和 QA 文档。

## 文件地图

```text
loc-resume-screening/
├── SKILL.md                         # skill 触发语、原则、脚本速查
├── HANDOVER.md                      # 当前交接入口，只保留冻结态和下一步
├── config.example.yaml              # 可提交配置模板
├── config.local.yaml                # 本机真实配置，不能提交或打包
├── scripts/
│   ├── parse_resumes.py             # LLM 简历解析
│   ├── rescore_and_write.py         # 规则评分与写回
│   ├── send_test_email.py           # 测试题邮件
│   ├── generate_contract.py         # 合同生成
│   ├── check_signed_contract.py     # 签回合同核查
│   ├── update_status.py             # 状态推进
│   ├── export_badcase_snapshots.py  # Badcase 脱敏导出
│   ├── *_v2.py / workflow_*.py      # 过程可见包装层，非主流程替代
│   └── schema_*.py                  # Lark 表结构准入和门禁
├── references/                      # 字段字典、QA 报告、runbook、冻结报告
└── tests/                           # 评分规则回归测试
```

## 本机配置规则

真实配置只允许存在于：

- `config.local.yaml`
- 环境变量，例如 `LOC_LLM_API_KEY`

不要提交或打包：

- `config.local.yaml`
- `config.yaml`
- `config/lark-field-mapping.yaml`
- `.env` / `.env.*`
- 任何 SMTP 密码、LLM API key、Lark app secret、GitHub token

VM 安装时应从模板生成本机配置：

```bash
cp config.example.yaml config.local.yaml
python3 scripts/check_config.py
```

## 接手后先跑

```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/check_config.py
python3 tests/run_tests.py
python3 scripts/schema_validator.py --table all
PYTHONPYCACHEPREFIX=/tmp/loc-resume-pycache python3 scripts/integration_readiness.py
```

预期：

- `check_config.py` 通过，且显示读取 `config.local.yaml`。
- 评分测试 25/25 PASS。
- Lark 表结构只读准入通过。
- 集成验收 PASS，并提示 `workflow_runner next` 暂不建议作为唯一主入口。

## 当前推荐执行方式

### 单节点脚本

```bash
python3 scripts/rescore_and_write.py --record-id <candidate_record_id> --dry-run
python3 scripts/send_test_email.py --record-id <candidate_record_id> --file <test_file> --dry-run
python3 scripts/generate_contract.py --name "<候选人姓名>" --dry-run
python3 scripts/check_signed_contract.py --name "<候选人姓名>" --file <signed_contract> --dry-run
python3 scripts/update_status.py --record-id <candidate_record_id> --status "<目标状态>" --dry-run
python3 scripts/export_badcase_snapshots.py --dry-run
```

### 受控手动串联

当前阶段由 VM 明确指定：

- 候选人：record_id / 姓名 / 昵称。
- 节点：评分、发测试题、准备合同、检查签字合同、推进状态、导出 Badcase。
- 附件：测试题文件、签回合同文件等。

Agent 不应在信息不足时猜测下一步，也不应把 `workflow_runner next` 当成默认主入口。

## 表结构迁移规则

VM 更换 Lark 表或修改表头时，先跑只读识别：

```bash
python3 scripts/schema_validator.py --table all
```

如果缺字段或类型不匹配，先把差异报告给 VM。VM 确认后才允许：

```bash
python3 scripts/schema_validator.py --table all --apply --create-missing-tables
```

原则：

- 可以自动创建 schema 允许的辅助表，例如 `Agent流程日志`。
- 不自动创建候选人主表或合同敏感信息表。
- 字段用途以 `references/lark-field-dictionary.md` 为准。

## VM 日常维护的 Lark 表格

生产配置完成后，Agent 应主动向 VM 展示这份维护清单。VM 不需要记住技术字段名，但需要知道每张表为什么存在、什么时候要更新、哪些内容不能乱删。

| 表格 | 业务用途 | 人工维护内容 | Agent 写回内容 | 维护时机 |
|---|---|---|---|---|
| 候选人/简历招募主表 | 资源候选人的主状态机和简历评估入口 | 候选人基础信息、简历附件、人工初筛结论、测试结果、合同/供应商编号、Badcase 标记与期望结果 | 解析后的结构化字段、评分、评级、AI 建议、置信度、流程状态、Badcase 快照附件 | 每天处理新投递、测试回收、合同推进和异常反馈时维护 |
| 合同信息收集表 | 资源商填写合同变量的来源表 | 乙方姓名、邮箱、地址、证件、收款账号类型、账户地区、收款币种、银行信息、证件/附件 | 通常只读；必要时写回合同生成状态或核查结果 | 候选人进入签约前，由资源商/VM 确认完整性 |
| 合同模板表 | 合同模板和变量说明的维护入口 | 模板名称、适用规则、模板附件、变量说明、版本说明 | 通常只读；Agent 根据规则选择模板并下载附件 | 新增合同版本、调整模板变量、规则变化时维护 |
| Agent 流程日志表 | 每次执行的过程记录、失败排查和审计 | 一般不人工改；可查看失败原因和 checkpoint | run_id、候选人、节点、输入摘要、输出摘要、状态、人工确认记录 | Agent 每次执行自动写入；排查问题时查看 |
| Badcase 字段/快照 | 把 VM 发现的问题回流给项目侧迭代 | 是否Badcase、期望结果 | 脱敏 snapshot JSON 附件、处理状态 | VM 发现结果不符合预期时打标；项目侧处理后更新 |
| 评分规则配置表 | 生产评分价格维度的唯一来源，可独立于候选人主表 Base 复用，维护各语言对 AIPE/人工翻译预期价和上限价 | 语言对、AIPE 预期/上限、翻译预期/上限、规则版本、启用状态 | 读取命中的规则来源和版本，不写业务字段 | 规则变化、语种价格变化、评分策略调整时维护 |

风险边界：

- 字段可以改显示名，但不要删除字段；换表前必须让 Agent 做表头识别和依赖检查。
- 候选人主表、合同信息表、合同模板表是业务事实来源，不能靠 Agent 上下文记忆补。
- GitHub issue、README、handover、QA 报告只允许出现脱敏信息；不要写真实 base token、table id、邮箱、候选人姓名、本地路径、合同编号或供应商编号。
- 评分规则配置表是生产评分必需表，且允许独立配置 `pricing_rules.base_token/table_id`；VM 更换简历收集表时不应默认重建规则表。规则变更会影响评分和评级，必须记录维护人、变更原因和生效时间。

## 过程可见层边界

过程可见层可以做：

- 记录每步开始、输入、输出、成功、失败、人工确认。
- 写入/读取 workflow_log。
- 展示执行过程。
- 生成 Demo 证据。

过程可见层不可以做：

- 重写评分逻辑。
- 重写合同模板选择逻辑。
- 重写邮件生成和发送逻辑。
- 替代 Lark 状态机。
- 依赖 LLM 上下文记忆当前流程状态。

## 可选/非默认能力

以下能力可以保留和测试，但不要在生产里默认启用：

- `workflow_runner.py next`：自动路由入口，当前只适合显式测试，不作为 VM 默认生产入口。
- `run_dialog.py`：对话包装入口，可用于 checkpoint / resume 演示，不替代单节点脚本。
- checkpoint / waiting / resume：用于人工确认节点恢复，不代表 Agent 可以自己记住流程状态。
- `run_testmode_demo.py`：Demo 证据采集工具，只应在 TEST_MODE 下使用。

## 已知风险

- 旧状态「📋 新投递」与新状态「📋 简历待筛选」仍需要迁移或兼容策略。
- Badcase GitHub issue 回流目前仅验证 dry-run，正式启用需要 `badcase_export.enabled=true` 和 `gh` 登录。
- `workflow_runner next` 还不是生产默认入口。
- VM 生产验证仍需使用真实 record_id、真实附件、真实合同模板和真实签回文件逐项确认。

## 下一步

1. 给当前冻结点打 tag，例如 `v0.1-single-node-qa`。
2. 打包 skill，并检查包内不包含本机真实配置。
3. 推送远端前复查提交历史和打包内容。
4. 基于 `single-node-qa-report-2026-06-11.md` 录制真实 TEST_MODE Demo。
5. 进入 VM 生产验证。

## v0.2+ Backlog

以下不是 v0.1 默认交付范围：

- 更高程度的自动路由和自动 next。
- 多候选人并发调度。
- Layer 2 Agent 行为评测。
- 更多脚本接入 WorkflowEngine。
- 前端过程可见层接入正式数据库。
- 全自动闭环可行性评估。

历史过程、设计演进和更细任务请看：

- `V2-PROJECT.md`
- `references/original-agent-baseline-audit.md`
- `references/integration-validation-plan.md`
- `references/manual-chain-runbook.md`
- `references/stable-qa-checklist.md`

## 废弃/暂缓入口

- 不再使用 `config.yaml` 作为 VM 唯一配置入口。
- 不再自动读取 OpenClaw provider 或 `openclaw.json` 里的 LLM key。
- 不把 `workflow_runner next` 作为默认生产入口。
- 不把当前版本描述为全自动工作流闭环。
