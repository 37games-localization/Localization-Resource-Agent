"""
config_loader.py
================
统一配置读取模块，所有脚本 import 这里。
自动查找配置，路径优先级：
  1. 环境变量 LOC_CONFIG_PATH 指定路径
  2. skill 根目录 config.local.yaml（本机真实配置，不提交）
  3. skill 根目录 config.yaml（可提交模板 / VM 可复制后填写）
  4. ~/.agents/skills/loc-resume-screening/config.local.yaml
  5. ~/.agents/skills/loc-resume-screening/config.yaml
"""

import os
import sys
from pathlib import Path


def _find_config_path() -> Path:
    # 优先：环境变量
    env_path = os.environ.get("LOC_CONFIG_PATH")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    # 从当前脚本向上找本机私有配置，其次才读模板配置
    candidates = [
        Path(__file__).parent.parent / "config.local.yaml",
        Path(__file__).parent.parent / "config.yaml",   # skill 根目录
        Path(__file__).parent / "config.local.yaml",
        Path(__file__).parent / "config.yaml",           # scripts 目录
        Path.home() / ".agents" / "skills" / "loc-resume-screening" / "config.local.yaml",
        Path.home() / ".agents" / "skills" / "loc-resume-screening" / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p

    return None


def get_config_path() -> Path | None:
    """Return the active config path, mainly for diagnostics."""
    return _find_config_path()


def load_config() -> dict:
    """读取并返回配置 dict，缺失必填项时打印提示并退出"""
    try:
        import yaml
    except ImportError:
        print("❌ 缺少 pyyaml，请运行：pip3 install pyyaml")
        sys.exit(1)

    config_path = _find_config_path()
    if not config_path:
        print("❌ 找不到配置文件")
        print("   请先复制模板并填写本机配置：")
        print("   cd ~/.agents/skills/loc-resume-screening")
        print("   cp config.example.yaml config.local.yaml")
        print("   然后编辑 config.local.yaml")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 展开 ~ 路径
    paths = cfg.get("paths", {})
    for key in ["contract_templates", "contract_output"]:
        if paths.get(key):
            paths[key] = str(Path(paths[key]).expanduser())
    cfg["paths"] = paths

    return cfg


def get_smtp(cfg: dict) -> dict:
    return cfg.get("smtp", {})


def get_lark(cfg: dict) -> dict:
    return cfg.get("lark", {})


def get_paths(cfg: dict) -> dict:
    return cfg.get("paths", {})


def get_llm_api_key(cfg: dict) -> str:
    """LLM apiKey：优先配置文件，其次环境变量；不自动读取 OpenClaw 配额。"""
    key = cfg.get("llm", {}).get("api_key", "")
    if key:
        return key

    key = os.environ.get("LOC_LLM_API_KEY", "")
    if key:
        return key
    return ""


def is_test_mode(cfg: dict) -> bool:
    return cfg.get("test_mode", {}).get("enabled", True)


def get_test_email(cfg: dict) -> str:
    return cfg.get("test_mode", {}).get("test_email", "")


def validate_config(cfg: dict) -> list[str]:
    """返回配置问题列表，空列表表示配置完整"""
    issues = []

    smtp = get_smtp(cfg)
    if not smtp.get("user") or smtp.get("user") == "your-email@example.com":
        issues.append("smtp.user 未配置（当前是占位符）")
    if not smtp.get("password"):
        issues.append("smtp.password 未填写")
    if not smtp.get("host"):
        issues.append("smtp.host 未填写")

    lark = get_lark(cfg)
    if not lark.get("base_token"):
        issues.append("lark.base_token 未填写")
    if not lark.get("resume_table_id"):
        issues.append("lark.resume_table_id 未填写")
    if not lark.get("contract_table_id"):
        issues.append("lark.contract_table_id 未填写")

    if is_test_mode(cfg) and not get_test_email(cfg):
        issues.append("test_mode.enabled=true 但 test_email 未填写")

    if not get_llm_api_key(cfg):
        issues.append("LLM api_key 未配置（请填写 config.local.yaml 的 llm.api_key，或设置 LOC_LLM_API_KEY；不会自动读取 OpenClaw 配额）")

    return issues
