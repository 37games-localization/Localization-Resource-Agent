# 环境检查 Issues — 2026-06-10

记录首次在新机器跑 v2 工作流可视化版本时发现的环境问题，
目标是后续改进 `check_config.py`，让装完 agent 的人能一键发现并修复所有问题，
而不是等实际跑脚本时才撞到报错。

---

## Issue #1: config.yaml 飞书 token 为空，直接 404

**现象**
```
RuntimeError: lark-cli 失败: HTTP 404: 404 page not found
```
**原因**  
`config.yaml` 是空模板，`base_token` / `resume_table_id` 未填写，
lark-cli 用空字符串拼 URL，飞书返回 404。

**影响脚本**  
所有需要拉取飞书记录的脚本（`rescore_and_write`、`send_test_email`、`generate_contract` 等）

**修复方向（check_config）**  
- 启动时检测 `base_token` 和 `resume_table_id` 是否为空字符串
- 若为空，打印填写指引并 `sys.exit(1)`，不让脚本继续跑

---

## Issue #2: lark-cli 版本过旧，API 路径失效

**现象**
```
RuntimeError: lark-cli 失败: HTTP 404: 404 page not found
log_id: 202606100939133703D0E522DA542D5893
```
同样是 404，但原因是 lark-cli 1.0.48 的 API 路径在新版飞书已失效，
升级到 1.0.50 后恢复正常。

**修复方向（check_config）**  
- 运行 `lark-cli --version` 拿到版本号
- 与已知最低可用版本（当前 1.0.50）比较
- 低于最低版本时提示 `lark-cli update`

---

## Issue #3: pymupdf 未在当前 Python 环境安装，PDF 解析静默跳过

**现象**
```
← 输入：file_token: SQsbbzsBCow4…
⚠️  未安装 pymupdf，跳过 PDF 解析
```
脚本不崩溃，但 PDF 简历内容完全丢失，评分仅依赖飞书表字段，精度下降。

**原因**  
`(base)` conda 环境下 `python3` 指向的 Python 没有 pymupdf，
系统 Python 3.10 有，但 conda 环境不共享。

**修复方向（check_config）**  
- `import fitz` 尝试导入，失败时打印安装命令
- 区分「硬依赖缺失（退出）」和「软依赖缺失（警告，降级运行）」
- pymupdf 属于软依赖，警告即可，但要让用户知道评分会受影响

---

## 后续改进目标

`check_config.py` 改造为完整的「首次环境自检」入口，覆盖：

| 检查项 | 类型 | 当前状态 |
|--------|------|----------|
| config.yaml 必填字段（飞书 token / table_id）| 硬依赖 | ❌ 未检查 |
| lark-cli 最低版本 | 硬依赖 | ❌ 未检查 |
| pymupdf 安装 | 软依赖 | ❌ 未检查 |
| SMTP 连通性 | 软依赖 | ✅ 已有 |
| 飞书 API 连通性 | 硬依赖 | ✅ 已有（但在 token 空时会 404） |
| LLM API 连通性 | 软依赖 | ✅ 已有 |
| pyyaml 安装 | 硬依赖 | ❌ 未检查（缺失时直接崩溃） |

目标：新机器装完 skill 后，先跑 `python3 scripts/check_config.py`，
所有问题一次性暴露，给出修复命令，检查通过后再跑业务脚本。
