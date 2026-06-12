# 资源管理 Agent v2 — 项目规划与进度

> 文档维护：槐序
> 创建：2026-06-10
> 最后更新：2026-06-12
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
- **分层验收**：原脚本是已验收业务底座；v2 先作为可视化/对话包装层逐项证明等价，再升级统一入口


## 一点五、本窗口默认工程化多 Agent 协同协议

后续在本窗口处理资源管理 Agent 的代码、前端、工作流、README、治理、eval、trace/span、Lark mapping 或发布相关任务时，默认按工程化多 Agent 协同方式执行，不需要 penny 每次单独提醒。

### 默认角色

| 角色 | 默认职责 |
|---|---|
| 目标守门 Agent | 复核本轮是否偏离真实目标；检查是否误改核心流程、是否把前端 Demo 当成真实 workflow、是否把 Lark 事实来源替换成上下文记忆 |
| 实现 Agent | 负责具体代码、文档、前端、脚本和配置修改；优先复用已验收单点脚本，不重新发明业务逻辑 |
| QA / 治理 Agent | 负责回归、隐私、schema、eval、trace/span、README 口径和发布边界检查；明确哪些改动影响主流程，哪些只是旁路观测或前端展示 |

### 默认边界

- 不重构已有主流程，除非明确确认主流程本身不满足需求。
- 单点能力必须可独立调用，也可以被流程或前端 wrapper 组合调用。
- Lark 是业务状态、输入、输出、checkpoint 和 workflow_log 的事实来源。
- 前端是消费层 / 操作层，不伪造真实 workflow，不接管评分、合同选择、邮件生成等业务判断。
- dry-run、TEST_MODE、生产环境共用同一套前端和入口；差异只来自后端执行模式与写回权限。
- 每次对外或给 VM 的文案必须区分“已验证”“需生产验证”“仅旁路观测”，不能为了汇报夸大成熟度。

### eval / trace / QA 是否需要单独拆

不需要每次单独拆给 penny 确认。它们默认包含在 QA / 治理 Agent 的职责里，但按改动范围分级执行：

| 改动类型 | 默认检查 |
|---|---|
| 仅前端展示 | 前端 lint / typecheck、真实数据来源检查、不得伪造 workflow、checkpoint 展示边界检查 |
| 文档 / README / onboarding | 隐私扫描、口径审计、VM 可理解性检查、避免把内部治理命令写成用户必须理解的操作 |
| Lark 字段 / mapping / 表迁移 | schema 准入、字段字典一致性、配置切换回归、生产表依赖检查 |
| 业务脚本 / 评分 / 合同 / 邮件 / 状态推进 | 单元测试、单节点 dry-run 或 TEST_MODE、集成验收、必要时生产验证 |
| Router / 对话唤起 / checkpoint | Router 回归、短期 session 边界、上下文失效、缺信息停机、checkpoint resume 检查 |
| trace/span / badcase / eval | trace 可回放、脱敏快照、issue 格式、eval_runner / regression_report、pass/fail/changed 分类 |
| 合并 / 发版 / 对外开放 | 隐私扫描、eval 或等价全量回归、README 口径、安装路径与 VM 使用路径复核 |

### 每次收尾默认回答

- 这次有没有改核心流程。
- 哪些只是旁路观测 / 前端展示 / 文档口径。
- 已跑哪些验证；哪些因为缺少真实 Lark/SMTP/LLM/生产权限没有跑，不能声称完成。
- 是否影响 VM 安装、自然语言唤起和现有单点能力。

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
engine = WorkflowEngine(candidate_name="测试候选人A", write_lark=True)

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
python3 scripts/workflow_runner.py status --name "测试候选人A"        # 查看状态+建议下一步
python3 scripts/workflow_runner.py next   --name "测试候选人A"        # 自动路由执行下一步
python3 scripts/workflow_runner.py score  --name "测试候选人A"        # 手动触发评分
python3 scripts/workflow_runner.py test-email --name "测试候选人A" --file ~/test.pdf
python3 scripts/workflow_runner.py contract   --name "测试候选人A"
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

## 二点五、稳定唤起与短期会话路由层（v0.2 规划）

### 背景

当前 v0.1 已经证明：资源管理 Agent 的单节点能力可独立调用，Lark 可以作为状态、输入、输出和流程日志的事实来源。但如果后续交给 VM 在 Claude Code / OpenClaw 等工具里长期使用，会出现新的稳定性问题：

- VM 不一定只在一个对话里持续处理资源管理流程；
- 同一个 Claude Code / OpenClaw 窗口可能同时处理 README、报错排查、文档修改、资源管理等任务；
- 如果依赖当前聊天上下文“记得自己正在跑资源管理 Agent”，跨任务、跨对话、多候选人并行时仍会漂移。

因此，资源管理 Agent 的稳定调用不应依赖 LLM 上下文记忆，而应建立固定入口协议：

```text
固定唤起词 + Step Router + Lark 状态机 + 单点脚本
```

### 目标

为现有 Agent 增加一层轻量稳定入口，使 VM 可以用自然语言稳定切入任意单点节点，同时不破坏当前已验收的业务脚本和 Lark 状态机。

典型调用：

```text
调用资源管理 Agent，给青木遥发测试邀请
调用资源管理 Agent，继续青木遥的合同步骤
继续资源管理 Agent，处理 20260520-08
```

系统应执行：

```text
自然语言指令
→ 识别资源管理 Agent 唤起词
→ Step Router 判断节点
→ 从 Lark 定位候选人和当前状态
→ 检查前置条件
→ 调用对应单点脚本
→ 写回 Lark / workflow_log
→ 输出 checkpoint 给 VM 确认
```

### 设计原则

1. **首次进入必须有唤起词**
   - 例如“调用资源管理 Agent”“继续资源管理 Agent”。
   - 避免普通任务被误判为资源管理流程。

2. **当前短期 session 内可以省略唤起词**
   - 如果 Agent 刚刚提示“缺少测试题附件”，VM 后续说“附件用 ~/Downloads/test.xlsx”应视为继续当前资源管理任务。
   - 如果 Agent 刚刚输出 checkpoint，VM 说“确认发送”应视为对当前 checkpoint 的人工确认。

3. **插入非资源管理任务后 session 失效**
   - 例如 VM 中途说“帮我改 README”“查一下这个报错”，资源管理短期上下文应暂停或失效。
   - 之后回到资源管理流程时，必须重新显式唤起。

4. **短期 session 只负责承接，不作为业务事实来源**
   - `active_agent_session` 只能保存当前对话内的候选人、step、等待信息和过期时间。
   - 候选人状态、合同信息、评分结果、workflow_log、checkpoint、Badcase 等事实仍以 Lark 为准。

5. **信息不足必须停下，不允许猜测执行**
   - 缺附件、候选人重名、目标状态不明、合同信息不完整、当前状态不满足前置条件时，必须输出前置条件缺失说明。

6. **每个 step 必须可独立唤起**
   - 评分、测试题、合同生成、签字核查、状态推进、Badcase 导出都应能单独触发。
   - 不要求 VM 必须从流程第 1 步跑到第 8 步。

### active_agent_session 草案

`active_agent_session` 是当前对话内的轻量缓存，用于承接“附件用这个”“确认发送”“继续”等短指令。

示例：

```json
{
  "agent": "loc-resource-management",
  "candidate": "青木遥",
  "record_id": "DEMO-JA-0001",
  "current_step": "test-email",
  "waiting_for": "attachment",
  "expires_at": "30 minutes",
  "last_user_intent": "send_test_email",
  "last_checkpoint_token": "ckpt-xxx"
}
```

允许保存：

- 当前 Agent 名称；
- 当前候选人定位信息；
- 当前 step；
- 正在等待 VM 补充的信息；
- 最近 checkpoint token；
- session 过期时间。

不允许保存为事实来源：

- 候选人真实状态；
- 邮箱、银行账号、合同信息等敏感事实；
- 评分结果和评级；
- workflow_log 正式记录；
- Badcase 快照和处理状态。

### Router 职责边界

Step Router 只负责“识别要调用哪个已存在能力”，不重写业务逻辑。

Router 可以做：

- 识别唤起词；
- 识别候选人定位方式：record_id / 姓名 / 昵称 / 邮箱；
- 判断用户意图：评分、发测试题、生成合同、核查签字合同、推进状态、导出 Badcase；
- 从 Lark 读取当前状态和依赖字段；
- 做前置条件检查；
- 调用对应单点脚本；
- 把执行过程写入 workflow_log；
- 输出 checkpoint。

Router 不可以做：

- 自己生成评分结果；
- 自己决定合同模板选择规则；
- 跳过原脚本的校验；
- 用聊天上下文替代 Lark 状态；
- 在缺少关键输入时猜测执行。

### 与现有能力的关系

这项能力应排在 v0.2，不进入 v0.1 冻结交付范围。

它与现有模块关系如下：

- **单点脚本**：继续作为业务执行层；
- **Lark 主表 / 合同表 / 流程日志表**：继续作为事实来源；
- **workflow_engine / checkpoint**：继续负责过程记录和人工确认；
- **workflow_runner next**：仍不作为默认生产入口，后续可被 Router 调用或替换为显式 step 调度；
- **前端 wrapper / Storybook**：用于展示 Router 识别结果、前置条件、执行过程和 checkpoint。

### 验收标准

v0.2 稳定唤起层至少需要通过以下场景：

1. 首次唤起：
   - 输入“调用资源管理 Agent，给青木遥发测试邀请”；
   - 能定位候选人、识别 step、检查附件和邮箱前置条件。

2. 缺信息续接：
   - Agent 提示缺附件后，VM 只说“附件用 ~/Downloads/test.xlsx”；
   - 系统能继续当前 `test-email` step，不要求 VM 重新说明完整任务。

3. checkpoint 续接：
   - Agent 输出“测试邀请待确认”；
   - VM 说“确认发送”；
   - 系统能识别为当前 checkpoint 决策，而不是新任务。

4. 插入其他任务后失效：
   - VM 中途说“帮我改 README”；
   - 再说“确认发送”时，系统不应继续资源管理流程，必须要求重新唤起或说明上下文已失效。

5. 单点独立调用：
   - “调用资源管理 Agent，生成青木遥合同”；
   - 即使没有从评分、测试步骤串联过来也能独立执行前置检查和合同生成。

6. Lark 状态优先：
   - 即使短期 session 里记录了候选人状态，执行前仍必须重新读取 Lark 当前状态和依赖字段。

### 待办拆分

- [x] 定义稳定唤起词和保留短语：调用资源管理 Agent / 继续资源管理 Agent / 资源管理 Agent 处理 XXX。
- [x] 定义 Step Router 意图分类：评分、测试题、合同生成、签字核查、状态推进、Badcase。
- [x] 定义 `active_agent_session` 数据结构与失效规则。
- [x] 定义“插入非资源管理任务”的判定规则。
- [ ] 为每个 step 补前置条件清单：候选人、附件、邮箱、合同信息、目标状态等。
- [x] 设计 Router 回归测试集，覆盖首次唤起、缺信息续接、checkpoint 续接、上下文失效、单点独立调用。
- [ ] 前端 wrapper 增加 Router 识别结果展示：识别到的候选人、step、前置条件、阻塞原因、checkpoint。

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
- 「帮我看看测试候选人A现在到哪一步了」
- 「给测试候选人A发测试题，附件是 test.pdf」
- 「把测试候选人A的状态改成测试通过」
- 「生成测试候选人B的合同」
- 「婉拒测试候选人C」

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
| P0 | checkpoint 写飞书流程日志 + resume 更新 decided | ✅ | — | 2026-06-10 |
| P0 | `run_dialog.py waiting` / `workflow_runner.py waiting` 待决策列表 | ✅ | — | 2026-06-10 |
| P0 | SKILL.md 补「继续XXX」「有哪些在等我」触发语 | ✅ | — | 2026-06-10 |
| Schema | Lark 表接入/迁移准入底座：required schema、表头识别、差异校验、映射生成 | ✅ | — | 2026-06-10 |
| P0 | checkpoint 语义修正：`run_id` 保持 workflow run，token 写入 `output_summary` 元数据 | ✅ | — | 2026-06-10 |
| P0 | 工作流日志写入优先使用字段映射，缺映射时回退旧字段名 | ✅ | — | 2026-06-10 |
| Schema | 允许 VM 确认后自动创建 `Agent流程日志` 辅助表，并让运行时优先使用映射表引用 | ✅ | — | 2026-06-10 |
| Schema | `schema_gate.py` 生产运行门禁：正式环境未通过字段映射准入时阻止业务执行 | ✅ | — | 2026-06-10 |
| Demo | `run_testmode_demo.py` 真实 TEST_MODE 证据采集器：保存 summary/transcript/stdout | ✅ | — | 2026-06-10 |
| 收敛 | `integration_readiness.py` 分步骤集成验收，只读检查 v2 包装是否可进入生产验证 | ✅ | — | 2026-06-10 |
| 收敛 | 新增 `references/integration-validation-plan.md`，明确先单步骤等价验收，再前端只读看板，最后启用统一入口 | ✅ | — | 2026-06-10 |
| 治理 | `trace_span.py` 标准化旁路模型：将 workflow step 映射为 run/span 结构并支持脱敏 | ✅ | — | 2026-06-12 |
| 治理 | `agent_router.py` 稳定唤起协议层：只做唤起词、step、候选人、附件、checkpoint 续接识别，不接管业务脚本 | ✅ | — | 2026-06-12 |
| 治理 | issue 回归测试新增 Trace/Router 协议测试，锁定首次唤起、缺信息续接、checkpoint 续接、session 失效边界 | ✅ | — | 2026-06-12 |
| 配置治理 | #19 修复：评分规则配置表支持独立 `pricing_rules.base_token/table_id`，不再默认绑定候选人主表 Base，保留旧配置兼容 | ✅ | — | 2026-06-12 |
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

### 🟠 当前收敛路线 — 先分步骤验收，再统一入口

- [x] 新增只读集成验收脚本：`python3 scripts/integration_readiness.py`
- [x] 明确 v2 不推翻原脚本：原脚本继续作为业务底座，v2 只做可视化/对话包装
- [ ] VM 生产表单步骤验收：评分写回
- [ ] VM 生产表单步骤验收：测试题邮件
- [ ] VM 生产表单步骤验收：合同 dry-run
- [ ] 基于 Lark 流程日志建设前端只读看板
- [ ] 三个单步骤稳定后，再把 `workflow_runner.py next` 作为默认调度入口

### 🔴 P0 — dialog-driver 完成后立即做（已完成，待生产实表验收）

- [x] **checkpoint 持久化写飞书**（2026-06-10 确认方案）
  - 脚本跑到 dialog checkpoint 时，写入**流程日志表**一行（status=waiting）
  - `run_id` 保持本次 workflow run ID；`checkpoint_token` 写入 `output_summary` JSON，避免破坏同一执行实例的追踪
  - 同时写入 `candidate_record_id`，供后续前端看板按候选人记录聚合日志
  - resume 完成后更新该行 status=decided
  - VM 触发时说「继续李全鸿 record_id=recXXX」→ 我先查流程日志有无 status=waiting 行，有则直接 resume
  - 触发语：「有哪些候选人在等我决策」→ 查流程日志表 status=waiting 的行列出来
  - **设计原则**：复用配置中的流程日志表，零新增字段，与原始 Agent 设计完全对齐
  - **原始设计基础**：流程日志表本就记录每步输入输出，VM 触发时提供 record_id，状态从飞书读不靠上下文

- [x] **SKILL.md 补充「继续XXX」「有哪些在等我」触发语**

- [ ] **端到端对话 demo 验证**：完整跑一次「帮我处理李全鸿」→ checkpoint → 「写入」→ 完成

已完成本地验证：
- `python3 -m py_compile scripts/workflow_engine.py scripts/workflow_runner.py scripts/run_dialog.py`
- `python3 tests/run_tests.py`：25/25 PASS
- `python3 scripts/run_dialog.py resume --token ckpt-nonexistent --decision 写入`：错误路径返回 JSON

### 🟡 P1 — demo 录制前

- [ ] **填写 SMTP 配置**（smtp.user / smtp.password）——发测试题步骤依赖
- [ ] **填写 contract_table_id**——合同步骤依赖
- [ ] **生产表准入校验**：先运行 `python3 scripts/schema_validator.py --table all` 预览差异；VM 确认后运行 `python3 scripts/schema_validator.py --table all --apply --create-missing-tables`，补字段、必要时创建 `Agent流程日志`，并生成 `config/lark-field-mapping.yaml`
- [x] **生产运行门禁**：`test_mode.enabled=false` 或 `LOC_REQUIRE_SCHEMA_READY=1` 时，业务入口会先检查字段映射完整性；未通过则阻止执行并提示准入命令
- [x] **TEST_MODE demo 证据采集器**：`run_testmode_demo.py` 调用真实业务脚本并保存 summary/transcript/stdout
- [ ] **录制全流程 demo**（评分 → 确认 → 写入飞书，在对话框里完成，不碰命令行）

### 🟢 P2 — 稳定后

- [ ] **Phase 4：并发任务调度**（主 session spawn 子 agent，多候选人同时处理）
- [ ] **Layer 2 Agent 行为评测框架**（任务完成率 / 工具调用准确率 / 成本）
- [ ] **v2 合并到 main**（所有测试通过后）
- [ ] **其余脚本接入 WorkflowEngine**（check_signed_contract / send_rejection_email / update_status）
- [ ] **业务脚本迁移到 field_resolver.py**：逐步替换硬编码 field_id，改为读取 `config/lark-field-mapping.yaml`
- [ ] **稳定唤起与短期会话路由层**：固定唤起词 + Step Router + active_agent_session + Lark 状态机，支持 VM 跨任务后稳定重新切入资源管理节点
- [ ] **Trace / Span 标准化**：将 workflow_log 升级为可按 run_id 回放的标准 trace-span 观测模型，支持审计、排查和 Badcase 归因
- [ ] **Eval 自动化与开发后 Regression Report**：建立固定测试集，每次改动后自动区分主流程影响、旁路观测影响、前端展示影响和需生产验证项

### 🟣 P3 — 生产化治理与长期运营边界

- [ ] **合同产物回写候选人主表**：合同 docx 生成后，上传到资源商简历信息所在行的「生成合同附件」字段；本地文件只作为临时缓存，Lark 候选人主表保留最终可查版本。
- [ ] **邮箱草稿箱集成**：当前先保留 `.eml` / draft 文件路径；后续评估接入外部邮箱草稿箱，让合同/测试/婉拒邮件写入真实草稿箱，由 VM 人工检查后发送。
- [ ] **Trace 证据 Git 归档**：将脱敏 trace/span、eval report、regression report、badcase snapshot 摘要按 run_id 或日期推送到 Git 仓库长期保留；录屏和一次性 demo 素材不纳入长期归档。
- [ ] **QA 回归责任矩阵**：明确改评分、合同、邮件、Router、前端、Lark mapping、README 时分别必须跑哪些测试，哪些需要 VM 生产验证，哪些只需自动化回归。
- [ ] **维护责任矩阵**：明确 VM、项目维护者、业务负责人、IT/平台、Agent 各自维护什么：规则、模板、权限、SMTP/邮箱、Lark bot、badcase 处理、发版回归和生产事故排查。
- [ ] **权限边界梳理**：区分谁能读取候选人主表、合同敏感信息、合同模板、workflow_log、badcase snapshot；谁能触发 production、发送邮件、修改评分规则、修改合同模板和 push issue。


---

## 八、后续待办补充：行业标准能力（Trace / Eval / Regression）

当前系统已经具备业务过程可观测和人工 Badcase 回流能力：

- step start / input / output / success / failed / checkpoint；
- workflow_log / agent_trace 思路；
- Lark 状态写回；
- 前端执行流展示；
- Badcase 标记、脱敏快照和 GitHub issue 回流。

但从生产级 Agent 的行业标准看，当前仍更接近“业务过程日志”，尚未完整具备标准化 `trace-span` 和自动化 `eval`。这部分应作为 v0.2+ 的生产治理能力规划，不进入 v0.1 冻结范围。

### 8.1 Trace / Span 标准化

#### 目标

让每一次 Agent 运行都可以按 `run_id` 回放完整链路，支持排查、审计、性能分析和 Badcase 归因。

期望回放链路：

```text
VM 指令
→ 候选人定位
→ Lark 读取
→ 脚本调用
→ LLM 解析
→ 规则计算
→ Lark 写回
→ checkpoint
```

#### 当前已有基础

- `workflow_engine` 已能记录 step 开始、输入、输出、成功、失败、checkpoint。
- `workflow_log` 已用于过程观察、恢复和审计。
- 前端 wrapper 已能展示执行流。
- Badcase 快照已经能把问题上下文脱敏回流。

#### 待补标准字段

后续可将现有业务日志升级为更标准的 span 结构：

```json
{
  "run_id": "run_xxx",
  "span_id": "span_xxx",
  "parent_span_id": "span_parent_xxx",
  "agent": "loc-resource-management",
  "step": "test-email",
  "span_type": "llm_call | tool_call | lark_read | lark_write | checkpoint | error",
  "input": {},
  "output": {},
  "status": "success | failed | waiting_confirmation",
  "duration_ms": 1234,
  "model": "deepseek / openclaw / claude",
  "token_usage": {},
  "error": {},
  "created_at": "..."
}
```

#### 设计原则

- Trace / Span 是观测层，不改变业务脚本结果。
- Lark 主表仍是业务事实来源；Trace 只记录执行过程和证据。
- `input` / `output` 必须支持脱敏视图，不能把合同敏感信息、邮箱、银行账号、证件号直接写入外部 issue 或公开报告。
- `span_id` / `parent_span_id` 应能表达一次运行中的父子关系，例如：用户指令 span → Lark read span → tool call span → checkpoint span。
- 前端 wrapper 后续应支持按 `run_id` 展示完整 trace 树，而不只是线性日志。

#### 验收标准

- 任意一次执行可按 `run_id` 查询完整 span 列表。
- 每个 span 至少包含：`run_id`、`span_id`、`agent`、`step`、`span_type`、`status`、`created_at`。
- 关键调用 span 能记录耗时：Lark 读取、脚本调用、LLM 调用、Lark 写回。
- 失败 span 能记录结构化错误和下一步建议。
- checkpoint span 能关联人工确认结果。
- Badcase snapshot 能引用相关 run/span，但对外导出时仍保持脱敏。

### 8.2 Eval 自动化

#### 目标

让每次代码、字段映射、前端 wrapper、规则配置或提示词改动后，可以自动判断主流程是否被破坏，而不是只靠人工感觉。

当前已有基础：

- 单点能力验证；
- 生产测试案例；
- regression report 思路；
- Badcase 标记；
- 脱敏快照；
- GitHub issue 回流；
- 人工判断结果是否符合预期。

但还没有形成完整自动化 eval。

#### 固定测试集方向

后续可沉淀以下固定测试集：

```text
简历解析测试集
合同模板选择测试集
测试邮件生成测试集
签字合同核查测试集
状态推进测试集
Badcase 脱敏上报测试集
Router 稳定唤起测试集
Lark mapping / 表结构迁移测试集
```

每次改动后自动跑：

```text
输入测试案例
→ 执行 Agent step
→ 对比期望输出
→ 标记 pass / fail / changed
→ 输出 regression report
```

#### 核心指标

- 简历字段抽取准确率；
- 评分结果一致性；
- 语言对 / 报价规则匹配准确率；
- 合同模板选择准确率；
- 邮件草稿字段完整率；
- 状态写回正确率；
- Badcase 脱敏字段合规率；
- Router 意图识别准确率；
- Lark mapping 兼容率；
- 主流程是否被前端或 mapping 改动影响。

#### 设计原则

- Eval 要优先覆盖已验收单点能力，避免 wrapper、Router 或 mapping 改动破坏主流程。
- LLM 解析类 eval 应允许“语义等价”，但结构化字段、评分结果、模板选择、状态写回必须可断言。
- Eval 输出不能只给 pass/fail，还要说明 diff：字段变化、状态变化、脚本变化、前端展示变化。
- Badcase 一旦被确认，应能转入测试集，形成回归保护。

### 8.3 开发后 QA / Regression Report

#### 目标

把 eval 与已有 regression report 思路结合，形成每次开发后的检查报告，明确本次改动是否影响主流程。

报告结构建议：

```text
本次改动影响范围：
- 主流程逻辑：是否影响
- 单点脚本：是否影响
- Lark mapping：是否影响
- 前端展示：是否影响
- 文档 / onboarding：是否影响
- 旁路观测：是否影响
```

输出结果必须明确区分：

```text
哪些改动影响主流程
哪些只是旁路观测
哪些只是前端展示
哪些需要重新生产验证
哪些可以只跑自动化回归
```

#### 推荐报告字段

- 改动摘要；
- 影响范围分类；
- 触及文件和模块；
- 是否影响 v0.1 单点能力；
- 是否影响 Lark 字段映射；
- 是否影响 workflow_log / trace / badcase；
- 已运行测试；
- 未覆盖风险；
- 是否需要 VM 生产验证；
- 回滚建议。

### 8.4 与现有规划的关系

- **与 workflow_log 的关系**：workflow_log 是当前业务日志；trace-span 是后续标准化观测模型。
- **与 Badcase 回流的关系**：Badcase 是人工发现问题；eval 是把已发现问题沉淀为自动回归保护。
- **与 Layer 2 Agent 行为评测的关系**：Layer 2 关注自然语言任务完成质量；eval 自动化关注每次改动是否破坏已验收能力。
- **与前端 wrapper 的关系**：前端可展示 trace 树、eval 结果和 regression report，但不应接管业务判断。
- **与稳定唤起 Router 的关系**：Router 本身也应纳入 eval，验证唤起词、短期 session、上下文失效和单点切入是否稳定。

### 8.5 待办拆分

- [x] 定义 `trace_span` 标准字段和脱敏策略。
- [x] 将现有 workflow_log 映射到 trace-span 视图，先不破坏现有 Lark 表结构。
- [x] 为 Lark read / Lark write / tool call / LLM call / checkpoint / error 建立 span 类型枚举。
- [ ] 前端 wrapper 支持按 `run_id` 展示 trace 树和 span 详情。
- [ ] 建立固定 eval 测试集目录：简历解析、合同模板、测试邮件、签字核查、状态推进、Badcase、Router、Lark mapping。
- [ ] 将已确认 Badcase 转为回归用例。
- [x] 增加开发后 regression report 模板，区分主流程、单点脚本、Lark mapping、前端展示、文档、旁路观测。
- [ ] 每次合并前运行 eval，并输出 pass / fail / changed / needs-production-validation。

### 8.6 一句话总结

资源管理 Agent 后续不仅要解决“同事如何稳定唤起并切入 step”，还要补齐两个生产级能力：

```text
Trace-span 标准化：让每次执行可回放、可审计、可定位问题
Eval 自动化：让每次改动后能自动判断主流程有没有被破坏
```

这样它才会从“能用的业务 Agent”继续升级为“可交接、可治理、可持续迭代的生产级 Agent”。
