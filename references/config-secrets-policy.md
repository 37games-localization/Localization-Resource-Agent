# 配置与密钥隔离规则

## 文件角色

| 文件 | 是否可提交 | 用途 |
|---|---:|---|
| `config.example.yaml` | 是 | 可打包模板，只放占位符和说明 |
| `config.yaml` | 否 | 兼容旧安装方式的本机配置文件，不应进入 Git |
| `config.local.yaml` | 否 | 推荐的本机真实配置文件 |
| `config/lark-field-mapping.yaml` | 否 | 本机/目标表生成的字段映射，可能包含 base/table 信息 |
| `.env` / `.env.*` | 否 | 本机环境变量 |

脚本读取优先级：

1. `LOC_CONFIG_PATH`
2. `config.local.yaml`
3. `config.yaml`

## VM 安装流程

```bash
cd ~/.agents/skills/loc-resume-screening
cp config.example.yaml config.local.yaml
```

VM 只需要填写 `config.local.yaml`，不需要改脚本。

## 禁止提交内容

- 飞书 base token / table id
- SMTP 用户密码或授权码
- LLM API key
- GitHub token
- 本机生成的字段映射
- `.env` 文件

## 检查命令

```bash
git ls-files | grep -E 'config\\.yaml|config\\.local\\.yaml|lark-field-mapping\\.yaml|\\.env'
git check-ignore -v config.yaml config.local.yaml config/lark-field-mapping.yaml
python3 scripts/privacy_scan.py
python3 scripts/check_config.py
```

期望结果：

- 第一条不应返回真实配置文件。
- 第二条应显示这些文件被 `.gitignore` 命中。
- 第三条应通过当前 tracked 文件敏感信息扫描。
- 第四条应显示当前读取 `config.local.yaml`，并在关键配置失败时返回失败。

## Git 历史脱敏

如果真实 token、邮箱、本地路径或候选人信息曾经进入历史提交，仅清理当前 HEAD 不等于彻底消除风险。历史重写会导致 commit SHA 失效，并需要 force push 与协作者重新 clone，因此必须由项目负责人单独确认后执行。
