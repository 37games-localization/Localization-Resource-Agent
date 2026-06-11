# 资源管理 Agent 稳定版 QA 清单

日期：2026-06-10

## 当前结论

当前阶段是 **Phase 1.5：受控手动串联**。

可以确认：
- 核心单点能力已经具备可用基础。
- 单点脚本可以独立调用，也可以按 VM 指令手动串联。
- 新增过程可见层已写入 Lark `workflow_log`，可作为后续前端只读数据源。

不能宣称：
- 全自动闭环已完成。
- `workflow_runner next` 可以作为默认生产入口。
- 简历 LLM 解析节点已经完成生产验证。

## QA 分层

| 层级 | 内容 | 当前状态 | 结论 |
|---|---|---|---|
| 原业务脚本 | 评分、测试题邮件、合同生成、签字核查、状态推进、婉拒邮件、Badcase 导出 | 部分已完成 TEST_MODE/真实写回验证 | 作为生产底座继续保留 |
| 过程可见层 | `manual_trace.py` + `workflow_log` 写入 | 已完成 dry-run 写日志验证 | 旁路观测，不接管主流程 |
| v2 包装层 | `*_v2.py`、`workflow_engine.py`、`run_dialog.py`、`workflow_runner.py` | 集成验收 PASS | 暂不作为默认主入口 |
| schema/映射层 | `schema_validator.py`、`field_resolver.py`、`lark-field-mapping.yaml` | 当前三表 0 缺失、0 疑似、0 类型错误 | 可支撑换表准入 |
| 前端展示层 | 读取 Lark 当前状态和 `workflow_log` | 未开始 | 下一阶段只读展示 |

## 已验证节点

| 节点 | 验证对象 | 验证方式 | 证据/结果 | 当前结论 |
|---|---|---|---|---|
| 评分重算 | 测试候选人A `<candidate_record_id>` | `rescore_and_write.py --record-id ... --dry-run` | 总分 100，S 档，有效简历=是；已写 `workflow_log` | 通过 dry-run |
| 测试题邮件 | 测试候选人A + 中译英测试题 | dry-run + TEST_MODE 真发送 | 测试邮箱收到；Lark 状态曾写回 `📤 测试中`；已写 `workflow_log` | 通过 TEST_MODE |
| 状态推进 | 测试候选人A | 真实 Lark 写回 | `📤 测试中` -> `✅ 测试通过` | 通过真实写回 |
| 合同生成 | 测试候选人A合同信息 | dry-run + 真实 docx 生成 | 12 个变量全部填充；证件图片插入；输出 docx 已生成；已写 `workflow_log` | 通过 |
| 婉拒邮件 | 测试候选人C | dry-run + TEST_MODE 真发送 | 测试邮箱收到 | 通过 TEST_MODE |
| 签字合同核查 | 测试候选人A signed PDF | dry-run + PDF 文本 diff | 签名页可提取；字段 diff 失败，原因是测试 PDF 与 Lark 假数据不一致；已写 failed 日志 | 能力验证通过，样本不一致 |
| schema 校验 | candidate / workflow_log / contract_info | `schema_validator.py --table all` | 0 缺失、0 疑似匹配、0 类型不匹配；映射已刷新 | 通过 |
| 集成验收 | v2 入口和包装层 | `integration_readiness.py` | PASS | 通过 |
| 评分规则 | 25 个规则用例 | `tests/run_tests.py` | 25/25 PASS | 通过 |

## 暂缓或未完成节点

| 节点 | 原因 | 进入下一步条件 |
|---|---|---|
| 简历 LLM 解析 | 当前未配置独立 LLM key；已移除 OpenClaw 隐式额度 fallback | 配置 `llm.api_key` 或 `LOC_LLM_API_KEY` 后，用测试简历单独验证 |
| 合同邮件 `--send` | 合同生成和邮件发送能力已分别验证，组合路径尚未补 TEST_MODE | 生产前补一次 TEST_MODE 合同发送 |
| 签字核查正式写回 | 当前 signed PDF 与 Lark 假数据不一致 | 提供与 Lark 合同信息一致的签回文件 |
| Badcase 快照上传 | 已接入日志，尚未用真实 Badcase 标记记录做上传验证 | 在测试记录标记 `是否Badcase=⚠️ 是` 后跑 dry-run / 正式上传 |
| `workflow_runner next` | 自动路由未完成生产串联验证 | 受控手动串联稳定后再启用 |

## 主流程影响改动

当前回归报告为 `NEEDS_NODE_QA`，原因是本轮改动涉及主流程脚本：

- 配置读取：`config_loader.py`、`check_config.py`
- Lark 字段映射：`field_resolver.py`、`lark_cli_utils.py`
- 主业务节点：`parse_resumes.py`、`rescore_and_write.py`、`send_test_email.py`、`generate_contract.py`、`check_signed_contract.py`、`send_rejection_email.py`、`update_status.py`、`export_badcase_snapshots.py`
- 合同变量映射：`field_mapping.py`

要求：
- 每次改这些脚本后，都必须跑对应单节点 dry-run / TEST_MODE。
- 不能只用 compile、schema 校验或集成验收替代业务节点 QA。

## 旁路观测改动

这些文件只应做过程可见、checkpoint、demo 或统一入口包装：

- `manual_trace.py`
- `workflow_engine.py`
- `run_dialog.py`
- `workflow_runner.py`
- `rescore_and_write_v2.py`
- `send_test_email_v2.py`
- `generate_contract_v2.py`
- `run_testmode_demo.py`

要求：
- 旁路观测层可以读 Lark、写 `workflow_log`、生成 checkpoint。
- 不得重新实现评分、邮件、合同、签字核查等业务判断。
- 不得绕过原脚本中的 dry-run、TEST_MODE、人工确认和阻断规则。

## 前端可读取字段

前端第一版建议只读以下内容：

### 候选人主表 candidate

- `candidate.name`
- `candidate.nickname`
- `candidate.email`
- `candidate.language_pair`
- `candidate.status`
- `candidate.score`
- `candidate.tier`
- `candidate.valid_resume`
- `candidate.score_basis`
- `candidate.ai_suggestion`
- `candidate.test_sent_at`
- `candidate.badcase_flag`
- `candidate.expected_result`
- `candidate.badcase_snapshot`

### 流程日志表 workflow_log

- `workflow.run_id`
- `workflow.candidate_record_id`
- `workflow.candidate_name`
- `workflow.step_name`
- `workflow.step_type`
- `workflow.status`
- `workflow.input_summary`
- `workflow.output_summary`
- `workflow.decision`
- `workflow.created_at`

前端第一版不做：
- 自动判断下一步。
- 直接改候选人核心字段。
- 直接发送邮件或生成合同。
- 绕过 VM 确认。

## 稳定版验收命令

```bash
cd ~/.agents/skills/loc-resume-screening

# 1. schema / 映射
python3 scripts/schema_validator.py --table all

# 2. v2 集成只读验收
PYTHONPYCACHEPREFIX=/tmp/loc-resume-pycache python3 scripts/integration_readiness.py

# 3. 评分规则
python3 tests/run_tests.py

# 4. 变更影响报告
python3 scripts/regression_report.py

# 5. 单点业务 smoke test
python3 scripts/rescore_and_write.py --record-id <candidate_record_id> --dry-run
python3 scripts/send_test_email.py --record-id <candidate_record_id> --file <test_file> --dry-run
python3 scripts/generate_contract.py --name "<candidate_name>" --dry-run
python3 scripts/check_signed_contract.py --name "<candidate_name>" --file <signed_pdf> --dry-run
python3 scripts/send_rejection_email.py --record-id <rejected_candidate_record_id> --dry-run
```

## 进入前端前的冻结条件

进入前端只读看板前，必须确认：

1. `config/lark-field-mapping.yaml` 已由当前生产表重新生成。
2. `workflow_log` 表字段稳定。
3. 至少评分、测试题邮件、合同生成、状态推进四个节点在目标测试表完成验证。
4. 前端只读，不接管业务动作。
5. `workflow_runner next` 仍不作为默认主入口。

## 对 VM / 管理层口径

建议表述：

> 资源管理 Agent 已完成核心单点能力验证，当前进入受控手动串联阶段。VM 明确指定候选人和节点后，Agent 可以执行对应脚本、展示输入输出、写回 Lark，并记录过程日志。下一步会基于 Lark 当前状态和 workflow_log 做只读可视化看板，先解决过程可见和 QA 留痕，再考虑更高程度自动路由。
