# VM 配置引导：从零到正式启用

## 概览

本文档是给 Agent 执行安装引导用的，不是让 VM 自己照着命令清单处理。核心原则是：Agent 先做到底，VM 只做最后确认；能自动处理的，不要转给 VM。仅当 Agent 无法处理外部授权、组织权限或账号安全验证时，才提醒 VM 人工处理最小必要动作。

VM 安装完成后，只需要对 OpenClaw 说：

```text
帮我完成资源管理 Agent 初始化配置
```

Agent 必须按本文档一步步带 VM 走完整配置，整个过程约 20-30 分钟。
完成后你的 OpenClaw 可以处理简历筛选、测试题发送、合同生成、状态追踪的全流程。

VM 不需要读完整仓库，也不需要先理解命令行。首次安装由 Agent 解释每一步要填什么、为什么要填、填完后如何验证；日常使用直接用自然语言告诉 Agent 要处理什么。

---

## 第一步：安装依赖

Agent 先检查本机是否已有依赖；缺什么再提示 VM 安装或由 Agent 执行安装命令。

```bash
pip3 install pymupdf anthropic pyyaml python-docx
```

如果是 Windows，Agent 应提示使用 `pip` 代替 `pip3`，并检查 Python 路径是否可用。

---

## 第二步：绑定飞书 bot

Agent 先检查 `lark-cli` 是否可用；未绑定时，引导 VM 提供 App ID / App Secret 并执行绑定。

```bash
lark-cli config bind --source openclaw --identity bot-only
```

App ID / App Secret 请向当前项目管理员获取。

如果 VM 使用新的 Lark bot，需要先在 Lark 开发者后台申请并发布权限。最小权限包括：
- Base / 多维表格读取：`base:app:read`、`base:table:read`、`base:field:read`、`base:record:read`
- 字段自动补齐：`base:field:create`
- 评分、状态和日志写回：`base:record:update`、`base:record:create`
- 简历和合同模板附件下载：`docs:document.media:download`

验证环境可以先开通 Base / 多维表格相关读写权限，减少反复授权；生产环境再按 `check_config.py` 的提示收敛到最小权限。

---

## 第三步：确认飞书合同模板表权限

合同模板存储在**飞书合同模板汇总表**，脚本自动从飞书下载，**不需要在本地维护模板文件**。

Agent 需要确认 bot 有权限访问以下两张飞书表；如果没有权限，停止并告诉 VM 需要补哪张表的权限：
- 合同模板表（base-token: 如实填入 `config.local.yaml` 中的 `lark.template_base_token`）
- 合同信息收集表（base-token: `lark.contract_base_token`）

---

## 第四步：生成并填写 config.local.yaml

Agent 先从模板生成本机配置：

```bash
cd ~/.agents/skills/loc-resume-screening
cp config.example.yaml config.local.yaml
```

然后 Agent 逐项询问 VM 并写入 skill 目录下的 `config.local.yaml`：

```
~/.agents/skills/loc-resume-screening/config.local.yaml
```

VM 不需要自己理解 YAML；Agent 应把每个配置项翻译成人能理解的问题，拿到答案后写入配置，再复述已写入内容供 VM 确认。

### SMTP（邮件发送）

Agent 询问 VM 的发件邮箱、SMTP host、端口、授权码和展示名称，然后写入：

```yaml
smtp:
  host: "smtp.exmail.qq.com"    # 你的企业邮箱 SMTP 地址
  port: 465
  user: "你的邮箱@公司域名.com"
  password: ""                   # 邮箱密码或授权码
  sender_name: "本地化团队"
```

常见企业邮箱 SMTP 地址：
- 腾讯企业邮：`smtp.exmail.qq.com`
- 网易企业邮：`smtp.ym.163.com`
- 企业邮箱：`smtp.example.com`（port: 465）

### 飞书配置

Agent 询问或从 VM 粘贴的 Lark 链接中解析 base token / table id，并写入：

```yaml
lark:
  # 简历收集表（评分数据主表）
  base_token: "你的简历表 base token"
  resume_table_id: "你的简历表 table id"

  # 合同信息收集表（资源商填写银行/证件信息）
  contract_base_token: "你的合同信息表 base token"
  contract_table_id: "你的合同信息表 table id"
  contract_info_form_url: "你的签约信息收集 Lark 表单地址"

  # 合同模板表（AI标注版模板，脚本自动下载，无需本地维护）
  template_base_token: "你的合同模板表 base token"
  template_table_id: "你的合同模板表 table id"
```

> 找项目负责人获取测试表或生产表的 base token / table id，不要把真实值提交到 Git。

### LLM 配置

简历解析会调用 LLM，需要显式配置 API Key。skill 不会自动读取 OpenClaw 的本机 provider 或 `openclaw.json`，避免静默消耗 OpenClaw 月度额度。

Agent 需要向 VM 明确说明：没有可用 LLM key 时，简历解析节点会停止；评分重算等不依赖 LLM 的节点仍可运行。

```yaml
llm:
  base_url: "https://ai-proxy.37wan.com/anthropic"
  model: "claude-sonnet-4-5-20250929"
  api_key: ""                    # 你的 apiKey
```

如果不想把 key 写进 `config.local.yaml`，也可以设置环境变量：

```bash
export LOC_LLM_API_KEY="你的apiKey"
```

### 路径配置

Agent 询问 VM 希望合同 docx 保存在哪里；没有偏好时使用默认目录：

```yaml
paths:
  contract_output: "~/Documents/loc-contracts/output/"   # 生成的合同 docx 保存位置
```

> Windows 用户改为：`C:/Users/你的用户名/Documents/loc-contracts/output/`
> 合同模板无需本地维护，脚本自动从飞书下载。

### 测试模式（先不要改）

Agent 必须先保持 TEST_MODE，并让 VM 填自己的测试邮箱：

```yaml
test_mode:
  enabled: true           # ← 保持 true，TEST 跑完再改
  test_email: "你自己的邮箱@公司域名.com"   # ← 填你自己的邮箱
```

---

## 第五步：验证配置

对 OpenClaw 说：**「帮我验证资源管理配置」**

Agent 执行：

```bash
python3 scripts/check_config.py
```

并用自然语言向 VM 展示检查结果：
- ✅ config.local.yaml 格式正确
- ✅ SMTP 可以连通
- ✅ lark-cli bot 权限正常
- ✅ LLM api_key 有效
- ✅ 合同模板目录存在

如果失败，Agent 不要让 VM 自己排查命令；要指出失败项、需要 VM 提供的信息、以及下一步怎么修。

---

## 第六步：锁定安装目录

配置验证通过后，对 OpenClaw 说：**「锁定资源管理 Agent 安装目录」**

Agent 执行：

```bash
python3 scripts/lock_user_install.py
```

锁定后：
- `config.local.yaml`、`config.yaml`、`config/lark-field-mapping.yaml` 仍可正常写入。
- 核心脚本、评分引擎、前端源码/配置、引用文档和模板规则会变成只读。
- 当前 Git checkout 会禁用 `git push`，避免误把本地改动推到仓库。

如果日常使用中发现流程结果不符合预期，不要直接改脚本；请把它标记为 Badcase，或联系项目维护者处理。

---

## 可选：打开前端工作台

配置验证通过后，你可以直接对 Agent 说：

```text
打开资源管理工作台
```

Agent 执行：

```bash
python3 scripts/start_frontend.py
```

前端会读取你本机的 `config.local.yaml` 和 Lark 字段映射，展示候选人列表、真实执行事件流、checkpoint 和 workflow_log。

注意：同一个前端同时服务 dry-run、TEST_MODE 和 production。页面会显示当前真实执行模式；dry-run 不会被当成已写回。

## 第七步：TEST_MODE 完整走一遍

对 OpenClaw 说：**「帮我走一遍测试流程」**，OpenClaw 会引导你：

1. **简历解析**：找一条已有记录，解析 PDF，看结果是否合理
2. **评分重算**：重算该记录评分，确认写回飞书
3. **测试题发送**：选一个候选人，把测试题发到 TEST_MODE 邮箱
4. **签约信息收集**：测试通过后，给候选人生成签约信息收集邮件草稿，确认表单链接正确
5. **合同生成**：选一个合同信息完整的记录，生成 docx，并在 TEST_MODE 下验证邮件内容
6. **状态推进**：手动推进一条记录状态，确认飞书更新

Agent 每步都要展示：本步骤读了什么输入、调用了哪个脚本、输出了什么、是否写回 Lark、是否需要 VM 人工确认。每步确认无误后继续下一步。

---

## 第八步：正式启用

所有步骤验证通过后，Agent 再引导 VM 切正式环境，并修改 `config.local.yaml`：

```yaml
test_mode:
  enabled: false    # ← 改为 false
```

同时把 `lark.base_token` 等换成生产表的值。

**正式启用后，所有邮件会发到真实资源商，请确认无误再切换。**

---

---

## 🚨 新功能：Badcase 回流（v2.3 新增）

使用过程中如果 agent 判断不对，**不需要截图、不需要写技术复盘**。

**方式一：自然语言**（告诉我）：

```
把这个标成 badcase，应该进人工复核，不该直接婉拒
把 XXX 标成 badcase，合同应该用个人版模板
刚才那封邮件标成 badcase，语气要更委婉
```

**方式二：飞书直接标记**：

在资源候选人主表，找到该候选人那一行：
- 「**是否Badcase**」列 → 选「⚠️ 是」
- 「**期望结果**」列 → 写一句话（可不填）

没有别的了。上下文、运行日志、评分明细由系统自动收集，导出为统一协议的脱敏 snapshot JSON，并默认直接创建 GitHub issue。Lark 附件上传不再作为默认链路。

Agent 内部会按统一协议生成脱敏快照和 GitHub issue，VM 不需要理解 issue 格式。

脱敏快照不得包含真实姓名、邮箱、电话、证件号、银行账号、原始简历全文、合同正文、API key、SMTP 密码、Lark/GitHub token。脱敏校验失败时，Agent 必须停止上报并告诉 VM 需要项目维护者处理。

如需开启自动导出，VM 只需要对 Agent 说：

```text
帮我开启 Badcase 自动导出
```

Agent 会在 `config.local.yaml` 中设置：

```yaml
badcase_export:
  enabled: true
  default_target: "github_issue"
```

---

## 日常使用

装好之后，直接对 OpenClaw 说自然语言：

- 「帮我解析新来的简历」
- 「给测试候选人A重跑评分」
- 「给 测试候选人A 发测试题，附件在桌面的 test.pdf」
- 「给测试候选人A发签约信息收集」
- 「测试候选人B的合同信息已收集，帮我生成合同发给她」
- 「把测试候选人A的状态改成合同已发送」
- 「全量重算一下所有人的评分」

---

## 单点调整

| 想改什么 | 改哪里 |
|---------|--------|
| 评分规则、语言对目标价/上限价 | 飞书「评分规则配置」表 |
| 候选人信息、评分字段、合同信息 | 对应 Lark 多维表格 |
| 合同模板 | 飞书合同模板表 |

Prompt、邮件模板、核心脚本、前端/API 和 workflow 路由不属于 VM 日常调整范围。发现这些地方需要改时，请标记 Badcase 或联系项目维护者。

---

## 常见问题

**Q: `ModuleNotFoundError: fitz`**

把报错发给 Agent，Agent 会补装缺失依赖。手动备用命令：

```bash
pip3 install pymupdf
```

**Q: `ModuleNotFoundError: yaml`**

把报错发给 Agent，Agent 会补装缺失依赖。手动备用命令：

```bash
pip3 install pyyaml
```

**Q: SMTP 连接失败**
- 检查 host/port 是否正确
- 部分企业邮箱需要先在网页端开启 SMTP 权限
- 密码填「授权码」不是登录密码（腾讯企业邮是这样）

**Q: 飞书权限报错**
- 确认已用 bot 身份绑定 lark-cli
- 确认 bot 在目标表格有管理员权限

**Q: LLM api_key 找不到**
- 让 Agent 帮你写入 `config.local.yaml` 的 `llm.api_key`
- 或让 Agent 指引你设置环境变量：`LOC_LLM_API_KEY`
- skill 不会自动读取 OpenClaw provider；这是为了避免消耗 OpenClaw 月度额度
