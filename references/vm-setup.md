# VM 安装配置指南

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

skill 会自动从你的 `~/.openclaw/openclaw.json` 里读取 `ai-proxy.37wan.com` 的 apiKey。

**如果自动读取失败**，可以设置环境变量：

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

飞书 App 信息（找 penny 获取）：
- App ID：`cli_a9361aaf32619eed`

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
- 「给 Kai Wichmann 重跑评分」→ 自动跑 rescore_and_write.py
- 「全量重算评分」→ 全量重跑

## 单点优化

想调整评分规则？改这个文件：
```
~/.agents/skills/loc-resume-screening/config/resume_screening_rules_v2.json
```

想调整 LLM 解析 prompt？改这个文件第 49 行的 `LLM_PROMPT`：
```
~/.agents/skills/loc-resume-screening/scripts/parse_resumes.py
```

改完直接重跑对应脚本，不需要重装 skill。

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
- 找 penny 确认 bot 权限

**Q: API Key 读取失败**
- 设置环境变量 `export LOC_LLM_API_KEY="你的key"`
- 或在 OpenClaw 里配置 `ai-proxy.37wan.com` provider
