# 原 Agent 基线验收

日期：2026-06-10

## 验收目的

本次只回答两个问题：

1. 已有 Agent 全流程是否已经通畅。
2. 已有 Agent 的单点能力是否可独立调用、可从流程中剥离。

如果 1+2 都满足，后续只做过程可见层；如果不满足，先修 Agent 顺畅度和单点解耦。

## 当前结论

结论：**单点能力基础存在，但“全流程通畅”和“全部节点可插拔”尚未完成系统性验收。**

因此当前不应继续扩大 v2，也不应直接进入前端。下一步应做原 Agent 的生产基线验证：用真实 record_id 和 TEST_MODE，按原脚本逐节点跑通并记录证据。

## 已确认事实

- 原脚本仍存在，且没有整体依赖 `workflow_runner.py next`。
- 多数原脚本支持 `--record-id` 或 `--name` 单点触发。
- 多数高风险脚本支持 `--dry-run`、`--draft`、交互确认或 `--yes`。
- Lark 主表、合同表、流程日志表 schema 当前可访问，字段映射已生成。
- SMTP 登录可用。
- 评分规则测试 25/25 PASS。
- 原评分脚本已用真实 record_id dry-run 跑通。
- 原测试题邮件脚本可只读列出候选人。
- 原合同脚本可只读列出合同信息记录。
- 状态推进脚本可只读列出 16 个状态。
- Badcase dry-run 可独立扫描，当前无待处理记录。
- LLM API 已改为显式配置：只读取 `config.yaml llm.api_key` 或 `LOC_LLM_API_KEY`，不再自动读取 OpenClaw provider/openclaw.json。
- 原脚本主要业务字段已改为映射优先、旧 ID 兜底：简历解析、测试题邮件、婉拒邮件、状态推进、合同生成、签字核查、合同变量映射。

## 当前阻塞

- 当前 `config.yaml` 未配置独立 LLM API Key，因此“简历解析”节点不会继续调用 LLM；需要安装/生产验证时显式配置 key。
- 全流程尚未按原脚本从头到尾跑完一遍。
- `check_signed_contract.py` 尚未用真实签字合同文件 dry-run 验证。
- `send_rejection_email.py` 尚未用真实候选人 dry-run 验证。
- `generate_contract.py --dry-run` 可能仍有模板选择交互；需要单独验证是否适合非交互 Agent 调用。
- 原 `rescore_and_write.py --dry-run` 输出中会出现“写入成功”文案，虽然实际未写入，容易误导 VM。

## 节点矩阵

| 节点 | 原脚本 | 单点入口 | 输入 | 输出/写回 | 人工确认 | 当前判断 |
|---|---|---|---|---|---|---|
| 配置自检 | `check_config.py` | 直接运行 | `config.yaml` | 终端报告 | 无 | 基础可用；LLM key 缺失时会提前停止，不消耗 OpenClaw 额度 |
| 简历解析 | `parse_resumes.py` | `--record-id` / `--name` / `--dry-run` | Lark 简历附件 + LLM | 解析字数/年限/项目数/实体写回 Lark | 无 | 入口具备；需显式配置 LLM key 后验证 |
| 评分重算 | `rescore_and_write.py` | `--record-id` / `--dry-run` | Lark 字段 + 简历文本 | 总分/评级/依据/建议/有效简历写回 Lark | 无 | 已 dry-run 跑通；可独立调用 |
| 测试题邮件 | `send_test_email.py` | `--record-id` / `--name` / `--file` / `--dry-run` | 候选人记录 + 测试附件 | 邮件发送；状态/发送时间写回 Lark | 有；`--yes` 可跳过 | 入口具备；需真实附件 dry-run 验证 |
| 合同生成 | `generate_contract.py` | `--record-id` / `--name` / `--dry-run` | 合同信息表 + 模板表 | docx / draft / send；合同状态写回 | 有；部分交互 | 只读 list 通过；需验证 dry-run 非交互性 |
| 签字核查 | `check_signed_contract.py` | `--record-id` / `--name` / `--file` / `--dry-run` | 签字合同文件 + Lark 合同信息 | 状态更新为合同已签署 | 有 | 入口具备；未实测文件 dry-run |
| 婉拒邮件 | `send_rejection_email.py` | `--record-id` / `--name` / `--dry-run` | 候选人记录 | 邮件发送；状态写回 | 有；`--yes` 可跳过 | 入口具备；未实测 dry-run |
| 状态推进 | `update_status.py` | `--record-id` / `--name` / `--status` | 候选人记录 + 目标状态 | 招募状态写回 Lark | 有；`--yes` 可跳过 | 状态列表验证通过；写回需生产验证 |
| Badcase 回流 | `export_badcase_snapshots.py` | `--dry-run` / 正式导出 | Lark badcase 标记 | 脱敏快照附件上传 | 无 | dry-run 通过；暂无待处理记录 |

## 是否满足 1+2

### 1. 全流程是否已经很通畅

当前答案：**未证明。**

理由：
- 已有多个单点能力可运行，但尚未按原脚本完成一次真实端到端链路。
- LLM key 未显式配置时会阻断简历解析节点；这是预期安全边界。
- 合同、签字核查、婉拒等节点仍缺少本轮原脚本证据。

### 2. 单点能力是否可独立调用、可剥离

当前答案：**大部分具备形态，但未全部验收。**

理由：
- 多数脚本具备 `--record-id`/`--name` 单点入口。
- 多数脚本输入来自 Lark 或显式文件参数。
- 输出主要写回 Lark 或生成文件。
- 主要业务字段已改成映射优先、旧 ID 兜底；剩余固定 ID 主要集中在合同模板表字段和历史依赖文档。
- 合同 dry-run 和签字核查仍需验证是否可稳定非交互调用。

## 下一步

只做原 Agent 生产基线验证，不继续扩大 v2：

1. 配置独立 LLM key 后，跑 `parse_resumes.py --record-id <rec> --dry-run` 或指定测试记录。
2. 用同一候选人跑 `rescore_and_write.py --record-id <rec> --dry-run`。
3. 用真实测试附件跑 `send_test_email.py --record-id <rec> --file <path> --dry-run`。
4. 用合同信息记录跑 `generate_contract.py --record-id <rec> --dry-run`，确认是否仍需要交互。
5. 用测试签字合同跑 `check_signed_contract.py --record-id <rec> --file <path> --dry-run`。
6. 用已拒绝候选人跑 `send_rejection_email.py --record-id <rec> --dry-run`。
7. 用 `update_status.py --record-id <rec> --status <status>` 在 TEST_MODE/测试记录上验证状态推进。

完成后再判断：

- 若全部通过：只加 trace 写入，前端只读 Lark 当前状态 + `Agent流程日志`。
- 若不通过：先修对应原脚本的顺畅度或解耦问题，再谈过程可见层。
