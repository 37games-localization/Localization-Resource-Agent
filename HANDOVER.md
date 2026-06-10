# 资源管理 Agent v2 — 交接文档

> 编写：槐序
> 日期：2026-06-10
> 适用对象：接手继续开发的 Agent
> 对应分支：`v2-workflow-viz`（稳定版：`main`）

---

## 一、项目状态速览

**你接手时，已经可以做到的事：**

在对话框里说「帮我处理李全鸿」，AI 调用 `run_dialog.py`，评分引擎跑完后在对话里问你「是否写入飞书？」，你回复「写入」，AI 调用 resume，写回飞书，汇报完成。全程不需要碰命令行。

**还差什么（按优先级）：**

见本文第四节「待办清单」。

---

## 二、必读文件（按顺序）

```
1. V2-PROJECT.md          # 完整规划 + 进度 + 待办
2. SKILL.md               # 触发语定义（含新增「对话驱动模式」section）
3. memory/resource-management-agent.md  # 原始设计、飞书表结构、字段 ID
   路径：~/.openclaw/workspace/memory/resource-management-agent.md
```

---

## 三、关键文件地图

```
~/.agents/skills/loc-resume-screening/
├── SKILL.md                          # 触发语 + 使用说明（v2.3）
├── V2-PROJECT.md                     # 规划 + 进度 + 待办
├── HANDOVER.md                       # 本文件
├── config.yaml                       # 唯一配置入口（含飞书token/SMTP）
├── scripts/
│   ├── workflow_engine.py            # ★ 核心：行动可视化 + checkpoint 机制
│   ├── run_dialog.py                 # ★ 对话驱动层（新）：供 AI 调用，输出 JSON
│   ├── workflow_runner.py            # 统一入口（命令行用）
│   ├── rescore_and_write_v2.py       # 评分写回（接入 WorkflowEngine）
│   ├── send_test_email_v2.py         # 发测试题（接入 WorkflowEngine）
│   ├── generate_contract_v2.py       # 生成合同（接入 WorkflowEngine）
│   ├── resume_screening_engine_v2.py # 评分引擎（规则型，不动）
│   ├── check_config.py               # 环境自检 v2（新增4项检查）
│   └── config_loader.py              # 配置读取工具
├── tests/
│   ├── test_cases.py                 # 25个测试用例（A/B/C三类）
│   └── run_tests.py                  # 测试执行器
└── issues/
    └── 2026-06-10-env-issues.md      # 已知环境问题记录
```

---

## 四、待办清单（接手后按顺序做）

### P0 — 最高优先级（做完才算生产可用）

**① checkpoint 持久化写流程日志表**

现状：dialog checkpoint 只写本地文件 `~/.loc-resume-checkpoints/{token}.json`，session 重启后 AI 不知道有待决策任务。

目标：checkpoint 时同时写一行到飞书**流程日志表**（`tblVQvjpJw9CO0kU`），字段：
- `run_id`：checkpoint token
- `step_name`：节点名（如「确认写入飞书」）
- `status`：`waiting`
- `candidate_name`：候选人姓名
- `input_summary`：summary JSON（总分/档位/建议）

resume 完成后把该行 `status` 更新为 `decided`。

改动位置：`scripts/workflow_engine.py` 的 `checkpoint()` dialog 分支，在写本地文件之后加飞书写入。

触发语补充到 SKILL.md：
- 「有哪些候选人在等我决策」→ 查流程日志表 `status=waiting` 的行
- 「继续处理XXX」→ 查流程日志找最近 waiting 行，拿 token 直接 resume

---

**② SKILL.md 补「继续XXX」「有哪些在等我」触发语**

在 `## 对话驱动模式` section 里补充。

---

**③ 端到端对话 demo 验证**

跑一次完整流程：
```
你说：「帮我处理李全鸿」
AI 调用：python3 scripts/run_dialog.py score --name "李全鸿"
AI 解析 JSON，在对话里说：「评分完成，总分 100/S，优先录用，是否写入飞书？」
你说：「写入」
AI 调用：python3 scripts/run_dialog.py resume --token ckpt-xxx --decision "写入"
AI 汇报：「✅ 已写入飞书」
```

---

### P1 — demo 录制前

**④ 填写 config.yaml**

```yaml
smtp:
  user: your@email.com       # 填真实 SMTP 账户
  password: xxxx             # SMTP 密码或应用专用密码
lark:
  contract_table_id: tblyMKA2XTECzRLs  # 合同信息表 ID（已知）
```

注意：
- SMTP 用 SSL，端口 465，已配置禁用证书验证
- test_mode.enabled 保持 true，邮件发到 demo@example.com

---

### P2 — 稳定后

- 并发任务调度（主 session spawn 子 agent，多候选人并行）
- Layer 2 Agent 行为评测（任务完成率/工具准确率/成本）
- v2 合并到 main 分支
- 其余脚本接入 WorkflowEngine（check_signed_contract / send_rejection_email / update_status）

---

## 五、核心接口速查

### run_dialog.py（AI 调用入口）

```bash
# 评分（按飞书招募状态自动路由）
python3 scripts/run_dialog.py score --name "李全鸿"

# 发测试题
python3 scripts/run_dialog.py test-email --name "青木遥" --file ~/Downloads/test.pdf

# 生成合同
python3 scripts/run_dialog.py contract --name "宋赛楠"

# 恢复 checkpoint
python3 scripts/run_dialog.py resume --token ckpt-xxx --decision "写入"
```

输出 JSON 格式：
```json
{
  "status": "checkpoint|done|error",
  "checkpoint_token": "ckpt-xxx",   // status=checkpoint 时有
  "node": "确认写入飞书",
  "candidate": "李全鸿",
  "summary": {"total_score": "100/100", "tier": "S", "suggestion": "优先录用"},
  "options": ["写入", "跳过", "退出"],
  "message": "...",                  // status=done/error 时有
  "raw_output": "..."
}
```

### WorkflowEngine（脚本内部用）

```python
wf = WorkflowEngine(candidate_name="李全鸿", write_lark=False, max_failures=5)
wf.trace("步骤名", input_summary="输入", output_summary="输出")
with wf.step("步骤名", input_summary="输入") as s:
    s.finish(output="结果")
token = wf.checkpoint("节点名", context={...}, options=["写入","跳过"], mode="dialog")
wf.resume(token, "写入")
wf.error("步骤名", "错误信息")  # 连续5次抛 RuntimeError（熔断）
wf.summary()
```

---

## 六、飞书关键配置

| 用途 | base_token | table_id |
|------|-----------|----------|
| 简历收集主表（日常用）| `JbkRbkGf6aAqfnsCDHHlJMjbg3b` | `tbll1fWOund3PSgd` |
| 流程日志表 | 同上 | `tblVQvjpJw9CO0kU` |
| 合同信息收集 | 同上 | `tblePA7PmmYlS936` |
| 资源管理主表（生产）| `HekabpDDkaUzyCsjKpqlCEFJgQf` | `tblkYSN55qkj9Td4` |

---

## 七、环境验证

接手后第一件事：

```bash
cd ~/.agents/skills/loc-resume-screening
git checkout v2-workflow-viz
python3 scripts/check_config.py        # 环境自检
python3 tests/run_tests.py             # 25个测试用例，全部应 PASS
python3 scripts/run_dialog.py score --name "李全鸿" 2>/dev/null
# 预期输出：JSON，status=checkpoint，tier=S
```

---

## 八、已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| SMTP 未配置 | ⬜ 待填 | 发测试题/合同步骤依赖 |
| contract_table_id 未填 | ⬜ 待填 | 合同步骤依赖 |
| checkpoint 仅写本地文件 | ⬜ P0待做 | 跨 session 需写飞书日志表 |
| workflow_runner list 字段映射 | ⬜ 低优先级 | 显示全为「—」，不影响功能 |

---

## 九、回滚

```bash
git checkout main    # 随时回稳定版
```
