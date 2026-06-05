# VM 配置引导：从零到正式启用

## 概览

安装完成后按以下顺序操作，整个过程约 20-30 分钟。
完成后你的 OpenClaw 可以处理简历筛选、测试题发送、合同生成、状态追踪的全流程。

---

## 第一步：安装依赖

```bash
pip3 install pymupdf anthropic pyyaml python-docx
```

如果用 Windows，用 `pip` 代替 `pip3`。

---

## 第二步：绑定飞书 bot

```bash
lark-cli config bind --source openclaw --identity bot-only
```

App ID 找 penny 获取（共用同一个 bot）。

---

## 第三步：确认飞书合同模板表权限

合同模板存储在**飞书合同模板汇总表**，脚本自动从飞书下载，**不需要在本地维护模板文件**。

确认 bot 有权限访问以下两张飞书表（找 penny 确认）：
- 合同模板表（base-token: 如实填入 `config.yaml` 中的 `lark.template_base_token`）
- 合同信息收集表（base-token: `lark.contract_base_token`）

---

## 第四步：填写 config.yaml

打开 skill 目录下的 `config.yaml`：
```
~/.agents/skills/loc-resume-screening/config.yaml
```

按照以下说明逐项填写：

### SMTP（邮件发送）

```yaml
smtp:
  host: "smtp.exmail.qq.com"    # 你的企业邮箱 SMTP 地址
  port: 465
  user: "你的邮箱@公司域名.com"
  password: "邮箱密码或授权码"
  sender_name: "本地化团队"
```

常见企业邮箱 SMTP 地址：
- 腾讯企业邮：`smtp.exmail.qq.com`
- 网易企业邮：`smtp.ym.163.com`
- 企业邮箱：`smtp.example.com`（port: 465）

### 飞书配置

```yaml
lark:
  # 简历收集表（评分数据主表）
  base_token: "JbkRbkGf6aAqfnsCDHHlJMjbg3b"
  resume_table_id: "tbll1fWOund3PSgd"

  # 合同信息收集表（资源商填写银行/证件信息）
  contract_base_token: "JbkRbkGf6aAqfnsCDHHlJMjbg3b"
  contract_table_id: "tblePA7PmmYlS936"

  # 合同模板表（AI标注版模板，脚本自动下载，无需本地维护）
  template_base_token: "WtNAb5ylMa0zqpsjciclnorugWb"
  template_table_id: "tblAGv4MYDGtiZ5Z"
```

> ⚠️ 上面是测试表的值，正式使用前换成生产表的值（找 penny 获取）。

### 路径配置

```yaml
paths:
  contract_output: "~/Documents/loc-contracts/output/"   # 生成的合同 docx 保存位置
```

> Windows 用户改为：`C:/Users/你的用户名/Documents/loc-contracts/output/`
> 合同模板无需本地维护，脚本自动从飞书下载。

### 测试模式（先不要改）

```yaml
test_mode:
  enabled: true           # ← 保持 true，TEST 跑完再改
  test_email: "你自己的邮箱@公司域名.com"   # ← 填你自己的邮箱
```

---

## 第五步：验证配置

对 OpenClaw 说：**「帮我验证资源管理配置」**

OpenClaw 会自动检查：
- ✅ config.yaml 格式正确
- ✅ SMTP 可以连通
- ✅ lark-cli bot 权限正常
- ✅ LLM api_key 有效
- ✅ 合同模板目录存在

---

## 第六步：TEST_MODE 完整走一遍

对 OpenClaw 说：**「帮我走一遍测试流程」**，OpenClaw 会引导你：

1. **简历解析**：找一条已有记录，解析 PDF，看结果是否合理
2. **评分重算**：重算该记录评分，确认写回飞书
3. **测试题发送**：选一个候选人，模拟发测试题到你自己邮箱
4. **合同生成**：选一个合同信息完整的记录，生成 docx，发到你自己邮箱
5. **状态推进**：手动推进一条记录状态，确认飞书更新

每步确认无误后继续下一步。

---

## 第七步：正式启用

所有步骤验证通过后，修改 config.yaml：

```yaml
test_mode:
  enabled: false    # ← 改为 false
```

同时把 `lark.base_token` 等换成生产表的值（找 penny 获取）。

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

没有别的了。上下文、运行日志、评分明细由系统自动收集，每次导出后在 GitHub 自动开 issue，由项目负责人分析修复。

**开启 Badcase 自动导出**：在 `config.yaml` 中设置：

```yaml
badcase_export:
  enabled: true
```

---

## 日常使用

装好之后，直接对 OpenClaw 说自然语言：

- 「帮我解析新来的简历」
- 「给青木遥重跑评分」
- 「给 Kai Wichmann 发测试题，附件在桌面的 test.pdf」
- 「宋赛楠的合同信息已收集，帮我生成合同发给她」
- 「把青木遥的状态改成合同已发送」
- 「全量重算一下所有人的评分」

---

## 单点优化

想自己调整规则？

| 想改什么 | 改哪里 |
|---------|--------|
| 评分规则（字数阈值、档位划分） | `config/resume_screening_rules_v2.json` |
| 价格规则（各语言对目标价/上限） | `scripts/pricing_rules.json` |
| LLM 解析 prompt | `scripts/parse_resumes.py` 第 49 行 `LLM_PROMPT` |
| 邮件文案模板 | 各脚本里的 `EMAIL_TEMPLATE` 变量 |

改完直接对 OpenClaw 说「重跑评分」或「重新解析简历」生效，不需要重装 skill。

---

## 常见问题

**Q: `ModuleNotFoundError: fitz`**
```bash
pip3 install pymupdf
```

**Q: `ModuleNotFoundError: yaml`**
```bash
pip3 install pyyaml
```

**Q: SMTP 连接失败**
- 检查 host/port 是否正确
- 部分企业邮箱需要先在网页端开启 SMTP 权限
- 密码填「授权码」不是登录密码（腾讯企业邮是这样）

**Q: 飞书权限报错**
- 确认已用 bot 身份绑定 lark-cli
- 确认 bot 在目标表格有管理员权限（找 penny 确认）

**Q: LLM api_key 找不到**
- 在 config.yaml 的 `llm.api_key` 里直接填
- 或设置环境变量：`export LOC_LLM_API_KEY="你的key"`
