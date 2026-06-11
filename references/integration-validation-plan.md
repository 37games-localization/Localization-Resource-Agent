# 资源管理 Agent v2 分层集成验收计划

## 当前判断

方向没有跑偏，但 v2 一次接入了可视化、字段映射、schema gate、checkpoint、统一入口和 demo 证据采集，跨度大于原有单步骤验收范围。

后续不推翻 v2，也不把原脚本废弃。正确推进方式是：把原本已经通过真实场景验收的单步骤脚本作为生产核心，把 v2 作为可视化与对话包装层，逐步证明包装层与原能力等价。

截至 2026-06-10，核心单点能力已完成足够验证，当前阶段推进为：**受控手动串联验证**。详见 [`manual-chain-runbook.md`](manual-chain-runbook.md)。

稳定版 QA 结论和前端前置条件见 [`stable-qa-checklist.md`](stable-qa-checklist.md)。

## 分层原则

1. 原脚本是底座：已验收的业务逻辑不随意改动。
2. v2 包装只增加可视化、checkpoint、流程日志和对话输出。
3. 前端第一阶段只读 Lark 与流程日志，不接管业务决策。
4. `workflow_runner next` 暂不作为唯一主入口，等单步骤包装验收通过后再升级。
5. 每一步都必须有真实 record_id/姓名输入、Lark 读写、日志输出和安全边界验证。

## 推进阶段

### Phase 0：冻结底座

目标：确认原脚本仍然存在，v2 没有替代或绕过原业务能力。

检查项：
- `rescore_and_write.py`
- `send_test_email.py`
- `generate_contract.py`
- `check_signed_contract.py`
- `update_status.py`
- `send_rejection_email.py`
- `export_badcase_snapshots.py`

输出：只允许 v2 复用原脚本能力，不允许在包装层另写一套业务逻辑。

### Phase 1：单步骤 v2 等价验收

目标：逐项证明 v2 包装层能稳定调用原能力，并生成可视化日志。

当前优先三项：

| 业务节点 | 原脚本 | v2 包装 | 验收标准 |
|---|---|---|---|
| 评分写回 | `rescore_and_write.py` | `rescore_and_write_v2.py` | 同一 record_id 下评分、档位、建议、有效简历判断一致；checkpoint 后可恢复写回 |
| 测试题邮件 | `send_test_email.py` | `send_test_email_v2.py` | TEST_MODE 下实际发送到测试邮箱，Lark 状态和测试发送时间写回一致 |
| 合同生成 | `generate_contract.py` | `generate_contract_v2.py` | 同一候选人下模板匹配、变量填充、dry-run 结果一致 |

只要单步骤没有通过，不推进统一入口。

### Phase 2：流程日志与前端只读看板

目标：把每一步输入、输出、状态、风险、人工确认节点沉淀到 Lark 流程日志表，供前端读取。

前端第一版只做：
- 候选人状态展示
- 最近执行步骤展示
- 每步输入/输出摘要
- checkpoint 待确认列表
- 错误原因与重跑入口提示

前端第一版不做：
- 自动判断下一步
- 直接修改候选人核心字段
- 绕过 VM 确认

### Phase 1.5：受控手动串联

目标：不启用全自动 `next`，由 VM 按候选人状态明确触发单点节点，Agent 负责执行、展示输入输出、写回 Lark，并记录过程。

当前定义：
- 可进入受控手动串联
- 不宣称全自动闭环完成
- 不默认启用 `workflow_runner next`

执行说明见 [`manual-chain-runbook.md`](manual-chain-runbook.md)。

### Phase 3：统一入口受控启用

目标：在单步骤包装稳定后，启用 `workflow_runner.py` 的手动子命令。

允许先启用：
- `status`
- `list`
- `waiting`
- `score`
- `test-email`
- `contract`
- `resume`

暂缓作为默认入口：
- `next`

`next` 只有在 VM 生产验证证明状态链稳定后，才作为默认调度入口。

## 日常检查命令

```bash
cd ~/.agents/skills/loc-resume-screening
python3 scripts/integration_readiness.py
```

这个检查只读，不会发邮件、不会写候选人、不会改状态。

如果要给外部或 VM 看结构化结果：

```bash
python3 scripts/integration_readiness.py --json
```

## 变更后回归报告

每次开发改动后，先跑：

```bash
python3 scripts/regression_report.py
```

报告必须把改动分成以下几类：

| 类型 | 含义 | 是否影响稳定版本功能 | QA 要求 |
|---|---|---|---|
| 影响主流程 | 原业务脚本、配置读取、字段映射、合同变量映射等 | 是 | 必须跑对应单节点 dry-run/TEST_MODE |
| 旁路观测 | v2 包装、流程日志、checkpoint、统一入口、demo 采集 | 不应影响原功能 | 必须证明只复用原脚本，不接管业务判断 |
| 准入/QA | schema、field mapping、schema gate、集成验收脚本 | 间接影响生产准入 | 必须跑 schema 校验和集成验收 |
| 规则/测试 | 评分规则、测试用例 | 影响评分结论 | 必须跑评分测试并抽样真实候选人 |
| 文档/交接 | SKILL、onboarding、handover | 不直接影响脚本，但影响 VM 使用 | 必须检查文档和脚本行为一致 |

回归报告结论解释：

- `NEEDS_NODE_QA`：存在主流程改动，不能只靠 compile 或集成验收，需要跑对应业务节点。
- `OBSERVATION_ONLY`：当前主要是旁路观测层，重点验证没有替代原业务逻辑。
- `BLOCKED`：存在未分类文件，先人工判断风险。
- `LOW_RISK`：未发现主流程影响改动。

## 当前可进入的下一步

用 VM 真实生产表做单步骤验收：

1. 指定候选人 record_id，验证评分 v2 包装。
2. 指定真实测试题附件，验证测试邮件 v2 包装。
3. 指定合同信息记录/姓名，使用 `--dry-run` 验证合同 v2 包装。

三项稳定后，再开始前端只读看板。

## 换表前置要求

进入生产验证前，VM 需要先确认新表字段语义，而不只是确认表头名称。

字段语义字典：[`lark-field-dictionary.md`](lark-field-dictionary.md)

这份字典说明：
- 每个英文 key 对应什么业务信息
- 是否必需
- 是 Agent 读取还是写入
- 缺失后会影响哪个节点

如果 VM 改了表头，但字段含义不变，可以通过 `schema_validator.py` 重新识别并写入映射；如果字段含义变了，则不能只靠改名解决，必须调整流程设计或脚本读取逻辑。
