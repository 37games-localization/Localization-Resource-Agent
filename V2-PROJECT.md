# 资源管理 Agent v2 — 项目规划与进度

> 文档维护：槐序
> 创建：2026-06-10
> 最后更新：2026-06-10 11:14
> 分支：`v2-workflow-viz`（稳定版保底：`main`）

---

## 一、项目背景与目标

### 问题

v1 版本（`main` 分支）的资源管理 Agent 存在三个核心问题：

1. **行动黑盒**：Agent 执行过程不可见，用户不知道在哪步、做了什么、输入输出是什么
2. **终端强依赖**：Human Decision 节点靠 `input()` 阻塞，OpenClaw 对话驱动场景用不了
3. **分散调用**：多个独立脚本，没有统一入口，用户需要手动拼命令

### 目标

从「分散脚本 + 终端交互」升级为「统一入口 + 对话驱动 + 全流程可视化」，**生产环境直接可用**。

### 设计原则

- **不破坏稳定版**：所有 v2 改动在独立分支，随时 `git checkout main` 回滚
- **向后兼容**：v2 脚本参数接口与 v1 完全兼容，新增参数为可选项
- **飞书是大脑**：状态/数据全在飞书，脚本每次从表里读，不靠上下文
- **规则确定性**：评分引擎是纯规则型，结果可预测、可测试、可断言

---

## 二、工程架构

### 新增文件

```
scripts/
  workflow_engine.py        # 核心：行动可视化 + checkpoint 机制
  rescore_and_write_v2.py   # 评分写回（接入 WorkflowEngine）
  send_test_email_v2.py     # 发测试题（接入 WorkflowEngine）
  generate_contract_v2.py   # 生成合同（接入 WorkflowEngine）
  workflow_runner.py        # 统一入口（根据飞书状态自动路由）

tests/
  test_cases.py             # 测试用例定义（A/B/C 三类）
  run_tests.py              # 测试执行器 + 报告生成

issues/
  2026-06-10-env-issues.md  # 环境问题记录
```

### workflow_engine.py 核心接口

```python
engine = WorkflowEngine(candidate_name="青木遥", write_lark=True)

# 记录单步动作
engine.trace("读取简历", input_summary="recXXX", output_summary="字段加载完成")

# 包裹有开始/结束的动作
with engine.step("调用评分引擎", input_summary="语言对 EN→ZH") as s:
    result = do_score()
    s.finish(output=f"总分 {result['score']}")

# Human Decision 节点（cli 模式：终端等待；dialog 模式：写文件异步等待）
decision = engine.checkpoint(
    node="确认写入飞书",
    context={"总分": 82, "档位": "B+"},
    options=["写入", "跳过", "退出"],
    mode="cli",     # 或 "dialog"
)

# dialog 模式：从外部恢复
token = engine.checkpoint(..., mode="dialog")   # 返回 token，不阻塞
engine.resume(token, "写入")                    # 外部注入决策
decision = engine.wait_for_resume(token)        # 轮询等待

# 打印执行摘要
engine.summary()
```

### workflow_runner.py 子命令

```bash
python3 scripts/workflow_runner.py list                          # 列出所有候选人+状态
python3 scripts/workflow_runner.py status --name "青木遥"        # 查看状态+建议下一步
python3 scripts/workflow_runner.py next   --name "青木遥"        # 自动路由执行下一步
python3 scripts/workflow_runner.py score  --name "青木遥"        # 手动触发评分
python3 scripts/workflow_runner.py test-email --name "青木遥" --file ~/test.pdf
python3 scripts/workflow_runner.py contract   --name "青木遥"
python3 scripts/workflow_runner.py resume --token *** --decision "写入"
```

### next 自动路由规则

| 飞书招募状态 | 自动调用 |
|-------------|---------|
| 📋 简历待筛选 / 🔍 初筛中 / ✅ 初筛通过 | `rescore_and_write_v2.py --interactive` |
| 📝 测试题待发 | `send_test_email_v2.py`（需 `--file`）|
| 📄 合同待生成 | `generate_contract_v2.py` |
| 其他状态 | 打印当前状态 + 说明需人工操作 |

---

## 三、测试体系

### 层次设计

```
Layer 1：规则单元测试（当前执行中）
  → 验证评分引擎规则逻辑正确性
  → 确定性断言，不依赖 AI 行为

Layer 2：Agent 行为评测（待规划）
  → 验证 OpenClaw 对话驱动场景的任务完成质量
  → 量化指标：任务完成率、工具调用准确率、平均轮数、单任务成本
  → 支持 A/B 对比（v1 vs v2）
```

### Layer 1：规则单元测试

**用例分类**

| 类别 | 含义 | 数量 |
|------|------|------|
| C 类 | 边界规则验证（优先）| ≥12 个 |
| A 类 | 常规场景验证 | ≥8 个 |
| B 类 | Snapshot 基线（辅助回归）| ≥5 个 |

**C 类覆盖的边界规则**

1. 无翻译经验 → 有效简历=否
2. 报价超过 hard_limit(0.10) → 价格分=0，档位=C
3. 报价恰好等于 expected → 价格分=50（满分边界）
4. 报价恰好等于 cap → 价格分=25（边界值）
5. 报价在 expected~cap 之间 → 价格分 25~50 线性插值
6. 单价缺失（None）→ 价格分=0
7. 完全符合 + 单价>cap → 档位=A（不能是 S）
8. 部分符合 + 单价>cap → 档位=C
9. 游戏品类单一（-2）→ B 档下浮到 C
10. 多品类+长年限（+5）→ B 档上浮到 A
11. 语言对字段缺失 → 不崩溃，价格分=0
12. 有较大商议空间(×0.7) + 原价 0.05 → 实际 0.035，在 cap 内，价格分>25

**断言方式**

```python
# A + C 类：规则断言
assert result["final_tier"] in expected["final_tier_in"]
assert expected["price_score_range"][0] <= result["price_result"]["score"] <= expected["price_score_range"][1]
assert valid == expected["valid_resume"]

# B 类：snapshot 对比
assert result["final_score"] == snapshot["final_score"]
assert result["base_tier"] == snapshot["base_tier"]
```

### Layer 2：Agent 行为评测（规划中）

**评测指标**

| 指标 | 定义 | 采集方式 |
|------|------|---------|
| 任务完成率 | 给定自然语言指令，最终飞书状态符合预期的比例 | 跑前后飞书状态对比 |
| 工具调用准确率 | 实际调用脚本/工具链 vs 预期调用链的匹配度 | session_history 解析 |
| 平均轮数 | 完成一个任务的平均对话轮数 | session_history 计数 |
| 单任务成本 | token 消耗 × 单价 | session_status cost 字段 |
| A/B 成功率差 | v1 vs v2 同批任务完成率对比 | 两组并行跑取差值 |

**标准任务集（待定义，≥20 条）**

示例：
- 「帮我看看青木遥现在到哪一步了」
- 「给青木遥发测试题，附件是 test.pdf」
- 「把青木遥的状态改成测试通过」
- 「生成宋赛楠的合同」
- 「婉拒刘启航」

---

## 四、进度记录

### v2 开发进度

| 阶段 | 内容 | 状态 | Commit | 日期 |
|------|------|------|--------|------|
| 基础工程 | 创建 `v2-workflow-viz` 分支 | ✅ | — | 2026-06-10 |
| 基础工程 | `workflow_engine.py` 核心引擎 | ✅ | `b4479ff` | 2026-06-10 |
| 基础工程 | `rescore_and_write_v2.py` | ✅ | `b4479ff` | 2026-06-10 |
| Phase 1 | `check_config` v2 环境自检 | ✅ | `68006b0` | 2026-06-10 |
| Phase 2 | dialog 模式 checkpoint + resume | ✅ | `8ccbcdb` | 2026-06-10 |
| Bug Fix | `send_test_email_v2` build_email 重名 | ✅ | `f2b3dcf` | 2026-06-10 |
| Phase 3 | `workflow_runner.py` 统一入口 | ✅ | `30a0744` | 2026-06-10 |
| Phase 3 | `SKILL.md` v2.3 更新 | ✅ | `30a0744` | 2026-06-10 |
| 测试体系 | 规则单元测试集 v1.0（25用例全过）| ✅ | `fe5d538` | 2026-06-10 |
| 稳定性 | WorkflowEngine 熔断机制（连续失败≥5次强退）| ✅ | `6b491a7` | 2026-06-10 |
| **Demo** | **全流程实跑验证（rescore 可视化完整跑通）** | ✅ | — | 2026-06-10 |
| Layer 2 | Agent 行为评测框架设计 | 📅 待规划 | — | — |

### 已记录问题（issues/）

| 问题 | 根因 | 修复状态 |
|------|------|---------|
| 飞书 token 为空 → 404 | config.yaml 是空模板，未填写 | ✅ check_config 新增检查 |
| lark-cli 版本过旧 → 404 | 1.0.48 API 路径失效，需 ≥1.0.50 | ✅ check_config 新增版本检查 |
| pymupdf 在 conda 环境未安装 | pip3 装到系统 Python，conda 隔离 | ✅ check_config 新增软依赖警告 |
| build_email 重名 bug | 原版 send_test_email.py 有两个同名函数 | ✅ v2 自实现，绕过原版 |
| 子 agent 空参数死循环 | TestGen 子 agent exec 发出空命令循环 45min | ✅ WorkflowEngine 熔断机制（≥5次强退）|
| 测试集预期与引擎实际出入 | 完全符合门槛：字数≥500k AND 次要≥10，普通描述难达到 | ✅ C07 边界测试用例明确覆盖 |

---

## 五、回滚方法

```bash
# 随时回稳定版
git checkout main

# 查看 v2 进度
git checkout v2-workflow-viz
git log --oneline
```

---

## 六、待决策项

| 事项 | 当前状态 | 需要 penny 确认 |
|------|---------|----------------|
| Agent 行为评测何时启动 | 规划中 | TestRun 完成后确认 |
| v2 何时合并到 main | 未定 | 测试全部通过后 |
| dialog 模式在 OpenClaw 对话里的触发协议 | 已实现文件机制，SKILL.md 待补充 | — |
| Layer 2 标准任务集定义 | 待讨论 | 需要 penny 提供典型指令列表 |

---

## 七、待办事项

> 按优先级排列，dialog-driver 子 agent 完成后依次推进

### 🔴 P0 — dialog-driver 完成后立即做

- [ ] **checkpoint 持久化写飞书**（2026-06-10 确认方案）
  - 脚本跑到 dialog checkpoint 时，把 token 写入候选人记录的「自由状态补充」字段
  - resume 完成后清空该字段
  - 触发语：「有哪些候选人在等我决策」→ 查飞书「自由状态补充」非空的记录列出来
  - 触发语：「继续处理XXX」→ 读飞书拿 token，直接 resume，无需用户记 token
  - **设计原则**：零新增字段，复用现有「招募状态」+「自由状态补充」，跨天/跨 session 安全恢复

- [ ] **SKILL.md 补充「继续XXX」「有哪些在等我」触发语**

- [ ] **端到端对话 demo 验证**：完整跑一次「帮我处理李全鸿」→ checkpoint → 「写入」→ 完成

### 🟡 P1 — demo 录制前

- [ ] **填写 SMTP 配置**（smtp.user / smtp.password）——发测试题步骤依赖
- [ ] **填写 contract_table_id**——合同步骤依赖
- [ ] **录制全流程 demo**（评分 → 确认 → 写入飞书，在对话框里完成，不碰命令行）

### 🟢 P2 — 稳定后

- [ ] **Phase 4：并发任务调度**（主 session spawn 子 agent，多候选人同时处理）
- [ ] **Layer 2 Agent 行为评测框架**（任务完成率 / 工具调用准确率 / 成本）
- [ ] **v2 合并到 main**（所有测试通过后）
- [ ] **其余脚本接入 WorkflowEngine**（check_signed_contract / send_rejection_email / update_status）
