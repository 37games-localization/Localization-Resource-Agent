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
python3 scripts/check_config.py
```

期望结果：

- 第一条不应返回真实配置文件。
- 第二条应显示这些文件被 `.gitignore` 命中。
- 第三条应显示当前读取 `config.local.yaml`，并在关键配置失败时返回失败。
