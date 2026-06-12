# 本地化资源管理 Agent

> Localization Resource Agent · 当前版本：v2.5

覆盖外部译者从**投简历到正式入库**的完整招募链路，通过自然语言指令驱动，飞书多维表格作为数据中枢。当前版本已进入生产端验证闭环：单点能力可独立调用，关键节点有日志/人工确认/安全准备模式，Badcase 可回流到 GitHub issue 追踪修复。

| 🔧 Skill 能力节点 | ✅ 业务节点验证 | ⚡ 自动执行节点 | 👤 固定人工介入节点 |
|:-:|:-:|:-:|:-:|
| 8 个 | 16 个 | 6 个 | 4 个 |

---

## 这个 skill 能做什么

| 功能 | 触发方式 |
|------|---------|
| 简历解析评分 | 「帮我解析今天新来的简历」 |
| 发测试题邮件 | 「给 XXX 发测试题，附件在桌面」 |
| 生成合同 | 「XXX 合同信息收集好了，帮我生成合同」|
| 合同邮件草稿 | 「帮我生成合同邮件草稿」 |
| 核查签字合同 | 「XXX 签字版回来了，帮我核查」 |
| 发婉拒邮件 | 「给 XXX 发婉拒」 |
| 状态推进 | 「XXX 财务审批通过了，更新状态」 |
| 查看候选人列表 | 「列出所有初筛通过的候选人」 |
| **标记 Badcase** | 「把这个标成 badcase，应该进人工复核」 |

---

## Badcase 回流机制

类似 macOS 崩溃上报 / Sentry 一键上报的逻辑：**VM 感知到问题，标记一下，上下文自动收集**。

### VM 只需要自然语言告诉 Agent

```
把这个标成 badcase，应该进人工复核，不该直接婉拒
把 XXX 标成 badcase，合同应该用个人版模板
刚才那封邮件标成 badcase，语气太硬
```

### 系统自动完成

```
VM 自然语言告诉 Agent
  ↓
Agent 生成脱敏快照 JSON（脱敏处理：真实姓名/邮箱/电话/证件全部移除）
  ↓
自动上传到飞书表「Badcase快照」附件字段
  ↓
项目负责人从飞书读取快照 → 按统一模板开 GitHub issue → 追踪修复
```

VM 不需要任何 GitHub 权限，不需要写技术复盘，不需要整理截图和日志。

---

## 快速安装

### Git 拉取（推荐）

```bash
git clone https://<your-token>@github.com/<org-or-user>/<repo>.git \
  ~/.agents/skills/loc-resume-screening

cd ~/.agents/skills/loc-resume-screening
git checkout main
```

`<your-token>` 找 penny 获取（只读权限）。

也可以下载 `.skill` 文件后解压到 `~/.agents/skills/loc-resume-screening/`。

Windows 用户如果不确定怎么装，直接让 Agent 按 onboarding 指引带着配置，不需要先理解 WSL / 依赖 / 路径差异。

---

## 安装后第一步

打开 OpenClaw / Codex，对资源管理 Agent 说：

```text
帮我完成资源管理 Agent 初始化配置
```

Agent 会逐步引导 VM 完成：

- 安装依赖。
- 绑定飞书机器人。
- 生成本机配置文件。
- 填写 Lark 表、SMTP、LLM key、输出路径等本机配置。
- 识别飞书表头，检查缺列/多列/字段改名。
- VM 确认后自动补齐允许创建的辅助列，并完成内部校验。

配置通过后，VM 日常只需要用自然语言调用，例如「看下 XXX 的简历」「给 XXX 准备合同」「把这个标成 badcase」。技术命令和排障步骤保留在 onboarding 文档里，不作为 VM 的默认入口。

详细引导见 [`references/onboarding.md`](references/onboarding.md)

v2.4 发布说明与 VM 通知话术见 [`references/v2.4-release-notes-2026-06-11.md`](references/v2.4-release-notes-2026-06-11.md)

生产表维护清单见 [`HANDOVER.md`](HANDOVER.md#vm-日常维护的-lark-表格)

---

## 更新日志

### v2.5（2026-06-12）
**评分规则治理 + 全语种覆盖回归**

- ✨ 评分规则配置表支持独立 Lark Base/Table：`pricing_rules.base_token/table_id` 可与候选人主表、合同信息表分开维护，并兼容旧配置。
- ✨ 新增本机 `.env.local` / `LOC_PRICING_RULES_*` 配置读取：敏感表引用可留在本机，不进入仓库或 skill 包。
- 🐛 修复中英混写语言对匹配：例如「简中>韩语 Simplified Chinese to Korean」可稳定归一化为 `zh-CN>ko`，并命中 Lark 评分规则。
- ✨ 新增 22 个主流市场语言对回归：覆盖英文源 14 个方向、简中源 8 个方向，支持中文标签和“中文 + 英文解释”的双语标签。
- ✨ 新增 `verify_pricing_rule_coverage.py`：直接读取 Lark「评分规则配置」表，检查主流市场语言对是否齐全，输出 missing / extra / available。
- ✨ 新增 `eval_runner.py`：统一运行 issue 回归、评分规则测试、Lark 语种覆盖、集成验收、隐私扫描和变更影响报告，输出 JSON + Markdown + trace/span 证据。
- ✨ 新增 `replay_run.py`：可按 Lark `workflow_log` 的 `run_id` 或本地 `eval_report.json` 回放 Agent 执行时间线，输出 `replay.json` 和 `summary.md`。
- 🐛 修复 schema 校验的手动映射优先级：已确认的 `candidate.score -> Agent总分` 不再被同名公式字段「总分」误判为类型错误。
- 🛡️ 更新回归报告分类：价格规则覆盖检查归为准入/QA，避免与业务主流程改动混淆。
- ✅ 验证：Agent 治理 eval PASS；Lark 实表覆盖 22/22，missing 0，extra 0；issue/eval 回归测试 39/39；评分引擎测试 25/25；schema 全量准入 PASS；集成验收 PASS；隐私扫描 PASS。

### v2.4（2026-06-11）
**生产端验证修复 + 工作流可视化稳定版**

- ✨ 新增工作流可视化/过程日志能力：v2 wrapper 可展示每步开始、输入、输出、成功、失败和人工确认节点。
- ✨ 新增表结构验证与字段映射机制：切换新飞书表时可检查缺失列、疑似匹配列和多余列，避免依赖 LLM 上下文记忆。
- 🐛 修复 Lark `record-list` 字段名 / field_id 读取不一致问题：统一 normalize 层，主脚本同时支持字段名和字段 ID 访问。
- 🐛 修复 LLM 评分路径最终分超过 100 的问题：写回前强制封顶，并在评分依据保留原始计算过程。
- 🐛 修复简历解析写回后状态不推进：初始投递类状态解析成功后推进到 `🔍 初筛中`。
- 🐛 修复 `--draft` 与状态写回耦合：测试题草稿不再推进 `📤 测试中`，合同草稿/发送不再勾选“合同签署”。
- ✨ 新增测试题邮件 `--prepare`：只输出可复制邮件包，不发送、不写状态。
- 🐛 修复合同模板推荐：按账户类型、账户地区、收款币种联合打分；新增国内/海外 × 人民币/外币四象限测试集。
- 🐛 修复合同 docx 自动打开体验：优先 WPS，失败时输出明确文件路径。
- 🐛 修复生产评分规则来源：价格维度必须读取 Lark「评分规则配置」表；缺表、缺字段、缺语言对时阻断评分，不再静默使用包内旧规则。
- 🛡️ 新增仓库脱敏扫描：防止 README、handover、QA 报告和 badcase 内容带入邮箱、本机路径、Lark 表/记录 ID、API key 等敏感信息。
- ✅ 验证：生产 issue / Badcase 协议回归测试 19/19，评分引擎测试 25/25，全脚本语法检查通过。

### v2.3（2026-06-05）
**Badcase 回流上线**

- ✨ 飞书资源候选人主表新增「是否Badcase」+「期望结果」+「Badcase快照」三个字段
  - VM 遇到问题：在飞书对应行标记「⚠️ 是」，可选填一句期望结果
  - 或直接告诉 Agent：「把这个标成 badcase，应该进人工复核」
- ✨ 新增 `export_badcase_snapshots.py`：自动生成脱敏快照 JSON 并上传到飞书「Badcase快照」附件字段
  - 脱敏处理：真实姓名/邮箱/电话/证件/银行信息全部移除，只保留匿名 ID、状态、评分摘要和 VM 期望结果
  - **VM 不需要任何 GitHub 权限**，快照存在飞书表，由项目负责人集中拉取并开 GitHub issue
  - 在 `config.yaml` 设置 `badcase_export.enabled: true` 后生效
- 📝 onboarding.md 新增 Badcase 使用说明

### v2.2（2026-05-28）
**草稿模式上线 + 旧品牌信息清理**

- ✨ 三个发邮件脚本（合同/测试题/婉拒）均新增 `--draft` 参数
  - 不再直接发送，生成 `.eml` 文件保存到本地
  - VM 双击用 Outlook/Mail 打开，确认无误后自己点发送
  - 草稿保存路径：`config.yaml` 中 `contract_output` 目录下的 `drafts/` 子目录
- 🐛 修复邮件落款残留「青木遥 / LOC Demo Vendor / LOC Demo Vendor」
  - 统一改为「Localization Team / Localization Team」

### v2.1（2026-05-28）
**配置全面迁入 config.yaml + 模板自动推荐**

- 🐛 修复发件人显示名（去除「青木遥」，改为裸邮箱，解决 spam 误判）
- 🐛 邮件标题统一改为「Localization Team」
- ♻️ 合同模板表 base_token / table_id 从硬编码改为读 config.yaml
- ✨ 合同模板按账户类型自动打分推荐，直接回车使用推荐模板
- ✨ 变量填充三层状态报告（已填充 / 值为空待确认 / 映射表无此变量）
- ✨ 合同生成后残留变量二次检查兜底
- 📝 SKILL.md 加入版本号字段，VM 可随时查询当前版本

### v2.0（2026-05-27）
**合同模块全面重构**

- 🎉 generate_contract.py 重构：支持 12 份合同模板，按账户类型路由
- ✨ 证件扫描件自动下载并插入合同末尾附件页（公司合同自动跳过）
- ✨ 新增 field_mapping.py：变量↔字段 ID 映射唯一代码入口
- ✨ 新增 lark-dependencies.yaml：飞书资源依赖声明 + 变更 SOP
- ✨ SKILL.md 新增「VM 需持续维护的内容」上岗交接清单
- 📝 onboarding.md 更新：合同模板改为从飞书自动下载，删除本地维护说明

### v1.0（2026-05-25）
**初始版本发布**

- 简历解析评分（LLM + 规则引擎双层）
- 测试题邮件发送
- 合同生成与发送
- 合同签署核查（视觉模型 + 信息一致性比对）
- 婉拒邮件
- 16 节点状态链追踪
- 飞书多维表格全流程读写

---

## 目录结构

```
loc-resume-screening/
├── SKILL.md                    # Agent 读取的主入口
├── config.example.yaml         # 配置模板
├── config.local.yaml           # ← VM 本机唯一需要编辑的文件（不提交）
├── config/
│   └── resume_screening_rules_v2.json   # 包内测试规则；生产价格规则以 Lark 表为准
├── scripts/
│   ├── generate_contract.py    # 合同生成 + 发送
│   ├── send_test_email.py      # 测试题邮件
│   ├── send_rejection_email.py # 婉拒邮件
│   ├── check_signed_contract.py# 签字合同核查
│   ├── parse_resumes.py        # 简历解析（LLM）
│   ├── evaluate_resumes.py     # LLM 一次性解析+评分（可选路径）
│   ├── rescore_and_write.py    # 重算评分并写回飞书
│   ├── pricing_rules.py        # 读取 Lark 评分规则配置表
│   ├── eval_runner.py          # Agent 治理 eval 统一入口
│   ├── replay_run.py           # Agent run_id / eval_report 回放
│   ├── verify_pricing_rule_coverage.py # 检查 Lark 评分规则主流市场覆盖
│   ├── workflow_runner.py      # 手动串联入口
│   ├── workflow_engine.py      # 过程日志/人工确认基础能力
│   ├── schema_validator.py     # 飞书表头检查与字段映射
│   ├── update_status.py        # 状态推进
│   ├── export_badcase_snapshots.py  # VM 侧 Badcase 脱敏快照导出
│   ├── push_badcase_issues.py       # 项目侧统一格式 GitHub issue 创建
│   ├── check_config.py         # 配置验证
│   └── field_mapping.py        # 变量↔飞书字段 ID 映射
└── references/
    ├── onboarding.md           # 安装引导（从这里开始）
    ├── lark-dependencies.yaml  # 飞书资源依赖声明
    ├── config.md               # 配置字段说明
    └── demo-data.md            # 测试数据
```

---

## 维护联系

有问题找 penny（本地化工具管理者）或在仓库提 Issue。
