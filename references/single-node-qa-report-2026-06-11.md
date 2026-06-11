# 资源管理 Agent 单节点 QA 报告（2026-06-11）

## 结论

当前版本已完成一轮基于测试候选人「测试候选人A」的单节点 QA。配置门禁、Lark 表结构、评分引擎、评分重算、测试题邮件预览、合同生成预览、签字合同核查、状态推进预览、婉拒邮件预览、Badcase 导出预览均已验证。

这轮 QA 证明：现有 Agent 的单点能力仍可独立调用；v2 可视化/包装层没有接管核心业务判断；当前主要剩余工作是 VM 真实生产表/真实候选人下的验收，而不是重构 Agent 主流程。

## 测试环境

- Skill 目录：`<skill-dir>`
- 分支：`v2-workflow-viz`
- 配置文件：`config.local.yaml`
- 运行模式：TEST_MODE
- 测试收件箱：`test-inbox@example.com`
- 简历主表测试候选人：测试候选人A，`<candidate_record_id>`
- 合同信息表测试候选人：测试候选人A，`<contract_record_id>`
- 测试题附件：`<local-test-file.xlsx>`
- 签回合同：`<signed-contract.pdf>`

## 基础门禁

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 环境自检 | PASS | SMTP、Lark Base、LLM API、合同模板均可连通 |
| 评分引擎测试 | PASS | 25 个用例全部通过 |
| v2 集成验收 | PASS | 评分、测试题、合同生成包装层均复用核心脚本 |
| Lark 表结构只读准入 | PASS | 候选人表、流程日志表、合同信息表均 0 缺失、0 疑似、0 类型错误 |

## 单节点验证

| 节点 | 命令模式 | 结果 | 关键输出 |
| --- | --- | --- | --- |
| 评分重算 | `--record-id <candidate_record_id> --dry-run` | PASS | 测试候选人A总分 100，初始评级 S，有效简历=是 |
| 测试题邮件 | `--record-id <candidate_record_id> --file ... --dry-run --allow-language-mismatch` | PASS | 成功解析 Excel 附件 40 条有效行，生成邮件预览，TEST_MODE 收件箱正确 |
| 合同生成 | `--name 测试候选人A --dry-run` | PASS | 成功匹配合同信息表记录，推荐个人外币个人账户模板，12 个变量全部填充 |
| 签字合同核查 | `--name 测试候选人A --file ... --dry-run` | PASS | PDF 格式正常，关键字段均能在签回文件中匹配，输出 VM 人工确认清单 |
| 状态推进 | `--record-id <candidate_record_id> --status "📋 简历待筛选" --dry-run` | PASS | 能识别当前旧状态「📋 新投递」并预览目标状态，不写回飞书 |
| 婉拒邮件 | `--record-id <candidate_record_id> --dry-run` | PASS | 非已拒绝状态下给出风险提示并生成邮件预览，不再要求非交互确认 |
| Badcase 导出 | `--dry-run` | PASS | 当前没有待处理 badcase，脚本正常退出 |

## 本轮发现并修复的问题

1. `send_rejection_email.py` 在 `--dry-run` 下仍会要求交互确认，非交互执行时触发 EOF。
   - 已修复：dry-run 只输出风险提示和邮件预览，不要求交互。

2. `update_status.py` 没有 dry-run，状态推进 QA 必须真写飞书。
   - 已修复：新增 `--dry-run`，可预览当前状态和目标状态，不写回飞书。

3. `schema_validator.py` 默认只读模式仍会尝试写入 `config/lark-field-mapping.yaml`，导致表结构正确但准入失败。
   - 已修复：默认只读不写映射，只有 `--apply` 才刷新映射。

## 保留风险

- 当前候选人主表存在旧状态「📋 新投递」，而新状态枚举使用「📋 简历待筛选」。这不影响脚本运行，但生产切表前需要确认历史状态迁移或兼容策略。
- 合同生成按姓名查合同信息表已通过；但简历主表 record_id 与合同信息表 record_id 不同，不能跨表复用同一个 record_id。
- `regression_report.py` 仍会提示 `NEEDS_NODE_QA`，因为它按文件影响面分类，不记录本轮 QA 证据。实际准入判断应同时参考本报告。
- Badcase 回流当前配置为未开启，已验证 dry-run 扫描能力，正式 GitHub issue 回流需开启 `badcase_export.enabled` 并完成 gh 登录。

## 下一步

1. 将当前版本冻结为 `v0.1 单节点 QA 通过版`。
2. 如需录制 Demo，优先录制本报告中已验证的真实执行路径，不再使用纯模拟输出。
3. 前端/过程可见层只读取 Lark 当前状态和 workflow_log，不接管评分、合同选择、邮件生成、状态推进等业务逻辑。
4. VM 生产验证时按同样节点逐一确认：真实 record_id、真实附件、真实合同模板、真实签回文件、真实 badcase 标记。
