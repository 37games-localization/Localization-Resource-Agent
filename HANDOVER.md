# 资源管理 Agent v0.1 交接说明

> 适用分支：`v2-workflow-viz`
> 当前冻结点：`v0.1 单节点 QA 通过版`
> 更新日期：2026-06-11

## 当前结论

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
