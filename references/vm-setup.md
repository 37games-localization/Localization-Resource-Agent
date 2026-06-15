# VM 安装配置指南

> 这是手动备用参考。VM 默认不需要自己照着命令操作；正常入口是对 OpenClaw 说「帮我完成资源管理 Agent 初始化配置」，由 Agent 读取 `references/onboarding.md` 后一步步引导、写配置、验证和展示结果。

## 前置要求

| 工具 | 版本要求 | 安装方式 |
|------|---------|---------|
| OpenClaw | 最新版 | 已有 |
| Python | 3.10+ | `python3 --version` 确认 |
| lark-cli | 最新版 | `npm install -g lark-cli` |
| PyMuPDF | 任意 | `pip3 install pymupdf` |
| anthropic SDK | 任意 | `pip3 install anthropic` |

## 第一步：安装 skill

把 `loc-resume-screening.skill` 文件复制到任意目录，然后：

```bash
# 解压到 ~/.agents/skills/（OpenClaw 会自动识别）
mkdir -p ~/.agents/skills
cd ~/.agents/skills
unzip /path/to/loc-resume-screening.skill -d loc-resume-screening
```

确认安装成功：
```bash
openclaw skills list | grep loc-resume
```
看到 `✓ ready` 就好了。

## 第二步：配置 LLM API Key

LLM API Key 需要显式配置，skill 不会自动读取 OpenClaw 的个人或团队额度，避免静默消耗月度限额。

推荐先复制模板，再写入本机配置 `config.local.yaml`：

```bash
cd ~/.agents/skills/loc-resume-screening
cp config.example.yaml config.local.yaml
```

```yaml
llm:
  base_url: "https://ai-proxy.37wan.com/anthropic"
  model: "claude-sonnet-4-5-20250929"
  api_key: ""                    # 你的 apiKey
```

也可以设置环境变量：

```bash
# 加到 ~/.zshrc 或 ~/.bashrc
export LOC_LLM_API_KEY="你的apiKey"
```

验证：
```bash
python3 ~/.agents/skills/loc-resume-screening/scripts/parse_resumes.py \
  --name "任意候选人名" --dry-run
```
看到 `✅ 解析结果` 就成功了。

## 第三步：绑定飞书 bot

```bash
# 绑定企业版飞书 bot（使用共享的 bot App ID）
lark-cli config bind --source openclaw --identity bot-only
```

飞书 App 信息：
- App ID：由项目维护人提供，不写入 skill 包

## 第四步：确认可用

```bash
cd ~/.agents/skills/loc-resume-screening

# 拉取飞书记录（确认 lark-cli 正常）
python3 scripts/rescore_and_write.py --dry-run --limit 1
```

---

## 日常使用

安装完成后，直接在 OpenClaw 对话里说：

- 「帮我解析新入库的简历」→ 自动跑 parse_resumes.py
- 「给 测试候选人A 重跑评分」→ 自动跑 rescore_and_write.py
- 「全量重算评分」→ 全量重跑

## 单点调整

想调整评分规则、候选人信息或合同信息，请在对应飞书表里修改，然后让 Agent 重跑对应步骤。

不要直接修改本地脚本、评分引擎、prompt、邮件模板、前端/API 或仓库结构。发现这些地方需要改时，请标记 Badcase 或联系项目维护者。

## 手动纠正评分

当 LLM 解析结果不准时：
1. 直接在飞书表里修改「解析字数」「解析年限」「解析项目数」字段
2. 对 OpenClaw 说「给 XXX 重跑评分」
3. 不需要重新解析 PDF

---

## 常见问题

**Q: `ModuleNotFoundError: fitz`**
```bash
pip3 install pymupdf
```

**Q: `ModuleNotFoundError: anthropic`**
```bash
pip3 install anthropic
```

**Q: lark-cli 报权限错误**
- 确认已用 bot 身份绑定，且 bot 是表格管理员
- 联系项目维护者确认 bot 权限

**Q: API Key 读取失败**
- 设置环境变量 `export LOC_LLM_API_KEY="你的key"`
- 或在 `config.local.yaml` 的 `llm.api_key` 里填写
- skill 不会自动读取 OpenClaw provider，避免消耗 OpenClaw 月度额度
