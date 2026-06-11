# 资源管理 Agent 受控手动串联 Runbook

日期：2026-06-10

## 当前定位

当前阶段定义为：**核心单点能力已验收，具备受控手动串联运行条件。**

不宣称：
- 全自动闭环已完成
- `workflow_runner next` 已可作为默认主入口
- 简历 LLM 解析已完成生产验证

建议对外表述：

> 资源管理 Agent 已完成核心单点能力验证，并具备手动串联运行条件。VM 按候选人状态手动触发各节点，Agent 负责执行、展示输入输出、写回 Lark，并记录过程日志。下一阶段进入受控串联验证，暂不默认启用全自动 next 调度。

## 已验收节点

| 节点 | 验收方式 | 当前结论 |
|---|---|---|
| 评分重算 | 测试候选人A真实 record_id dry-run | 通过 |
| 测试题邮件 | dry-run + TEST_MODE 真发送 + 用户收件确认 | 通过 |
| 合同生成 | dry-run + 真实 docx 生成 | 通过 |
| 状态推进 | 测试候选人A真实 Lark 写回 | 通过 |
| 婉拒邮件 | dry-run + TEST_MODE 真发送 + 用户收件确认 | 通过 |
| 签字合同核查 | signed PDF dry-run + 自动字段 diff | 通过能力验证；样例合同字段不一致，因此不更新状态 |
| Lark schema/mapping | `schema_validator.py --table all` | 通过 |
| 回归报告 | `regression_report.py` | 可区分主流程影响/旁路观测 |

## 暂缓节点

| 节点 | 暂缓原因 | 后续条件 |
|---|---|---|
| 简历 LLM 解析 | 缺独立 LLM key | 配好 `llm.api_key` 或 `LOC_LLM_API_KEY` 后单独验证 |
| 合同邮件 `--send` | 已验证邮件发送和合同生成，风险重复度较高 | 进入生产前可补一次 TEST_MODE |
| 签字核查非 dry-run 写回 | 当前 signed PDF 与 Lark 测试数据不一致 | 有匹配签回合同后再执行 |
| `workflow_runner next` | 状态自动判断尚未串联验证 | 受控手动串联稳定后再启用 |

## 受控手动串联原则

1. VM 明确指定候选人：优先 record_id，其次姓名/昵称。
2. Agent 每一步只调用对应单点脚本，不自行跳过人工确认。
3. 每一步执行前展示输入来源，执行后展示输出和 Lark 写回结果。
4. 高风险动作保留 `--dry-run`、TEST_MODE、人工确认或显式 `--yes`。
5. 若字段 diff、附件解析、语言方向、Lark schema 任一不通过，停止串联，不自动绕路。
6. `workflow_runner next` 暂不作为默认入口；使用明确子命令或原脚本。

## 标准输出格式

每个节点对 VM 汇报时使用同一结构：

```text
节点：
候选人：
输入：
执行：
输出：
Lark 写回：
风险/阻塞：
下一步建议：
```

## 串联节点清单

### 1. 评分重算

VM 触发：

```text
给测试候选人A重跑评分
```

推荐命令：

```bash
python3 scripts/rescore_and_write.py --record-id <candidate_record_id> --dry-run
```

输入：
- Lark 候选人主表
- 简历附件文本
- 价格/服务/经验字段

输出：
- 总分
- 初始评级
- 有效简历
- 评分依据
- AI建议

写回：
- dry-run 不写回
- 正式执行写回评分相关字段

下一步：
- 若初筛通过，VM 可推进到测试题待发或直接触发测试题邮件。

### 2. 测试题邮件

VM 触发：

```text
给测试候选人A发测试题，附件是 /path/to/test.xlsx
```

推荐命令：

```bash
python3 scripts/send_test_email.py --record-id <candidate_record_id> --file <test_file> --dry-run
python3 scripts/send_test_email.py --record-id <candidate_record_id> --file <test_file> --yes
```

输入：
- Lark 候选人姓名、邮箱、语言对
- 本地测试题附件
- SMTP/TEST_MODE 配置

输出：
- 附件摘要
- 邮件预览
- TEST_MODE 实际收件人

写回：
- 正式发送后写回「招募状态=📤 测试中」
- 写回「测试发送时间」

风险检查：
- 附件为空或无法解析：阻断
- 附件语言方向与候选人语言对不一致：正式发送默认阻断

下一步：
- 用户确认测试邮箱收到后，该节点通过。

### 3. 状态推进

VM 触发：

```text
把测试候选人A状态改成测试通过
```

推荐命令：

```bash
python3 scripts/update_status.py --record-id <candidate_record_id> --status "✅ 测试通过"
```

输入：
- 候选人 record_id
- 目标状态

输出：
- 当前状态
- 目标状态
- 写回确认

写回：
- 招募状态

风险检查：
- 生产环境不建议无预览直接 `--yes`

下一步：
- 若测试通过，进入合同信息收集/合同生成。

### 4. 合同生成

VM 触发：

```text
给测试候选人A生成合同
```

推荐命令：

```bash
python3 scripts/generate_contract.py --name "测试候选人A" --dry-run
python3 scripts/generate_contract.py --name "测试候选人A" --yes
```

输入：
- Lark 合同信息收集表
- Lark 合同模板表
- 证件扫描件附件

输出：
- 推荐模板
- 变量填充报告
- 生成 docx 路径
- 未替换变量二次检查

写回：
- 单纯生成 docx 不写回候选人状态
- `--send` 路径另行验证

风险检查：
- 银行账户名与中文姓名不一致时提示 VM 确认
- `甲方合同编号` 自动置空，不要求 VM 在乙方签字前填写
- 模板/附件下载依赖当前 lark-cli 的 `base +record-download-attachment`

下一步：
- VM 检查 docx 后，可发合同或等待签回。

### 5. 签字合同核查

VM 触发：

```text
测试候选人A合同已签字，文件是 /path/to/signed.pdf
```

推荐命令：

```bash
python3 scripts/check_signed_contract.py --name "测试候选人A" --file <signed_pdf> --dry-run
```

输入：
- signed PDF
- Lark 候选人主表
- Lark 合同信息表

输出：
- 格式检查
- 签名页图片路径
- Lark 合同信息摘要
- 自动字段 diff

写回：
- dry-run 不写回
- 正式执行且 VM 确认后写回「✅ 合同已签署」

风险检查：
- 仅有签名不够，必须关键字段 diff 通过
- diff 字段：姓名、邮箱、证件号、银行账号、地址、账户名、SWIFT

下一步：
- diff 通过且 VM 确认后，进入财务登记/审批。

### 6. 婉拒邮件

VM 触发：

```text
给测试候选人C发婉拒邮件
```

推荐命令：

```bash
python3 scripts/send_rejection_email.py --record-id <candidate_record_id> --dry-run
python3 scripts/send_rejection_email.py --record-id <candidate_record_id> --yes
```

输入：
- 已拒绝候选人记录
- SMTP/TEST_MODE 配置

输出：
- 邮件预览
- TEST_MODE 实际收件人

写回：
- 不改 Lark 状态

风险检查：
- 当前候选人不是「已拒绝」时要求人工确认

下一步：
- 用户确认测试邮箱收到后，该节点通过。

### 7. Badcase 回流

VM 触发：

```text
把这个标成 badcase，期望结果是 xxx
```

推荐命令：

```bash
python3 scripts/export_badcase_snapshots.py --dry-run
python3 scripts/export_badcase_snapshots.py
```

输入：
- Lark 候选人主表「是否Badcase」「期望结果」

输出：
- 脱敏 snapshot JSON
- 上传到 Lark Badcase 快照附件字段

写回：
- Badcase 快照附件

风险检查：
- snapshot 必须脱敏
- VM 不需要 GitHub 权限

## 当前下一步

1. 不再扩功能，先把受控手动串联接入 `workflow_log`。
2. 前端第一版只读 Lark 状态和流程日志。
3. `workflow_runner next` 继续暂缓，直到手动串联在 VM 生产验证中稳定。
