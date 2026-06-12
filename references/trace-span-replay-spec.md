# Trace / Span 回放规范

## 定位

Trace/span 是资源管理 Agent 的旁路观测层，用于回放、审计、定位问题和前端展示。它不决定业务结果，不替代 Lark 主表状态，也不接管评分、合同、邮件和状态推进逻辑。

## 数据来源

当前支持两类来源：

1. Lark `workflow_log`
   - 来自 v2 wrapper 或手动单点脚本写入的过程日志。
   - 适合回放真实业务节点执行过程。

2. `eval_runner.py` 生成的 `eval_report.json`
   - 来自治理 eval 的检查结果。
   - 适合回放开发后 QA、隐私扫描、语种覆盖、集成验收等治理过程。

## 标准 Span 字段

每条 span 至少包含：

```json
{
  "run_id": "run_xxx",
  "span_id": "span_xxx",
  "parent_span_id": "",
  "agent": "loc-resource-management",
  "step": "评分重算",
  "span_type": "tool_call | checkpoint | error | lark_read | lark_write | llm_call | router | user_intent",
  "input": {},
  "output": {},
  "status": "running | success | failed | waiting_confirmation | decided | skipped",
  "duration_ms": 123,
  "model": "",
  "token_usage": {},
  "error": {},
  "created_at": "..."
}
```

## 回放命令

```bash
# 从 Lark workflow_log 回放指定 run
python3 scripts/replay_run.py --run-id run-xxxx

# 回放最新 run
python3 scripts/replay_run.py --latest

# 回放指定候选人最新 run
python3 scripts/replay_run.py --candidate-record-id recxxxx

# 回放 eval 结果
python3 scripts/replay_run.py --eval-report ~/.loc-resume-eval-runs/<run>/eval_report.json
```

输出：

- `replay.json`：机器可读 trace/span。
- `summary.md`：人类可读时间线。

## 状态解释

- `success`：步骤执行成功。
- `failed`：步骤失败，必须查看 `error` 和 output。
- `waiting_confirmation`：已到人工确认 checkpoint。
- `decided`：人工决策已记录。
- `skipped`：步骤被跳过，通常来自 dry-run、prepare 或人工选择。

## 边界原则

1. Replay 只能读日志，不能重新执行业务动作。
2. Replay 不能写 Lark、不能发邮件、不能生成合同、不能推进状态。
3. Replay 输出必须走脱敏逻辑，邮箱、长数字、密钥、证件/银行信息不能出现在 span 中。
4. 前端只读 `replay.json` 或 Lark `workflow_log`，不从前端推断业务状态。
5. 如果 `workflow_log` 缺少某个步骤，不允许前端或 replay 自动补造步骤；只能显示“日志缺失”。

## 后续扩展

后续可以新增 `agent_trace` 表，把标准 span 字段直接落 Lark。但在当前阶段，先复用 `workflow_log`，避免引入新的表迁移风险。
