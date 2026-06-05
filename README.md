# 本地化资源管理 Agent

> Localization Resource Agent · 当前版本：v2.3

覆盖外部译者从**投简历到正式入库**的完整招募链路，通过自然语言指令驱动，飞书多维表格作为数据中枢。

---

## 这个 skill 能做什么

| 功能 | 触发方式 |
|------|---------|
| 简历解析评分 | 「帮我解析今天新来的简历」 |
| 发测试题邮件 | 「给 XXX 发测试题，附件在桌面」 |
| 生成合同 | 「XXX 合同信息收集好了，帮我生成合同」|
| 发送合同邮件 | 「生成完发给她」或 `--draft` 保存草稿自己发 |
| 核查签字合同 | 「XXX 签字版回来了，帮我核查」 |
| 发婉拒邮件 | 「给 XXX 发婉拒」 |
| 状态推进 | 「XXX 财务审批通过了，更新状态」 |
| 查看候选人列表 | 「列出所有初筛通过的候选人」 |
| **标记 Badcase** | 「把这个标成 badcase，应该进人工复核」或直接在飞书打标 |

---

## Badcase 回流机制

类似 macOS 崩溃上报 / Sentry 一键上报的逻辑：**VM 感知到问题，标记一下，上下文自动收集**。

### VM 只需做两件事

**方式一：飞书打标**

在资源候选人主表找到对应候选人那一行：
- 「**是否Badcase**」列 → 选「⚠️ 是」
- 「**期望结果**」列 → 写一句话（可不填）

**方式二：自然语言**（告诉 Agent）：

```
把这个标成 badcase，应该进人工复核，不该直接婉拒
把 XXX 标成 badcase，合同应该用个人版模板
刚才那封邮件标成 badcase，语气太硬
```

### 系统自动完成

```
VM 打标
  ↓
Agent 生成脱敏快照 JSON（脱敏处理：真实姓名/邮箱/电话/证件全部移除）
  ↓
自动上传到飞书表「Badcase快照」附件字段
  ↓
项目负责人从飞书读取快照 → GitHub 自动开 issue → 追踪修复
```

VM 不需要任何 GitHub 权限，不需要写技术复盘，不需要整理截图和日志。

---

## 快速安装

### 方式一：直接下载（推荐）

```bash
# 克隆仓库到 skill 目录
git clone https://<your-token>@github.com/<org-or-user>/<repo>.git \
  ~/.agents/skills/loc-resume-screening
```

`<your-token>` 找 penny 获取（只读权限）。

### 方式二：手动解压

下载 `.skill` 文件后解压到 `~/.agents/skills/loc-resume-screening/`。

### Windows 用户

建议先安装 WSL2，在 Linux 环境下运行，避免路径和依赖兼容问题。

---

## 安装后第一步

```bash
cd ~/.agents/skills/loc-resume-screening
pip3 install pymupdf anthropic pyyaml python-docx
lark-cli config bind --source openclaw --identity bot-only
```

然后编辑 `config.yaml`，填写你自己的：
- 企业邮箱（SMTP）
- 飞书 base_token 和 table_id
- 合同输出路径

填完让 Agent 说「帮我验证资源管理配置」，通过后正式使用。

详细引导见 [`references/onboarding.md`](references/onboarding.md)

---

## 更新日志

### v2.3（2026-06-05）
**Badcase 回流上线**

- ✨ 飞书资源候选人主表新增「是否Badcase」+「期望结果」两个字段
  - VM 遇到问题：在飞书对应行标记「⚠️ 是」，可选填一句期望结果
  - 或直接告诉 Agent：「把这个标成 badcase，应该进人工复核」
- ✨ 新增 `export_badcase_snapshots.py`：自动导出脱敏快照 → git push → GitHub 开 issue
  - 脱敏处理：真实姓名/邮箱/电话/证件/银行信息全部移除，只保留匿名 ID、状态、评分摘要和 VM 期望结果
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
├── config.yaml                 # ← VM 唯一需要编辑的文件
├── config/
│   └── resume_screening_rules_v2.json   # 评分规则（价格/年限/字数）
├── scripts/
│   ├── generate_contract.py    # 合同生成 + 发送
│   ├── send_test_email.py      # 测试题邮件
│   ├── send_rejection_email.py # 婉拒邮件
│   ├── check_signed_contract.py# 签字合同核查
│   ├── parse_resumes.py        # 简历解析（LLM）
│   ├── evaluate_resumes.py     # 简历评分
│   ├── rescore_and_write.py    # 重算评分并写回飞书
│   ├── update_status.py        # 状态推进
│   ├── export_badcase_snapshots.py  # Badcase 导出 + GitHub issue
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
