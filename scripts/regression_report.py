#!/usr/bin/env python3
"""
regression_report.py
====================
Read-only regression report after development changes.

The report separates changes that can affect the production business path
from changes that are only observational wrappers, docs, or schema gates.
"""

import argparse
import json
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent


MAIN_FLOW_SCRIPTS = {
    "scripts/check_config.py": "安装和生产前配置门禁会影响所有节点",
    "scripts/config_loader.py": "配置读取会影响所有节点",
    "scripts/field_resolver.py": "字段映射解析会影响 Lark 读写列",
    "scripts/lark_cli_utils.py": "Lark API 重试工具会影响所有 Lark 读写节点",
    "scripts/parse_resumes.py": "简历解析主流程",
    "scripts/evaluate_resumes.py": "LLM 简历解析+评分方向B主流程",
    "scripts/pricing_rules.py": "生产评分价格规则读取会影响评分价格维度",
    "scripts/rescore_and_write.py": "评分写回主流程",
    "scripts/send_test_email.py": "测试题邮件主流程",
    "scripts/generate_contract.py": "合同生成主流程",
    "scripts/field_mapping.py": "合同变量读取主流程",
    "scripts/check_signed_contract.py": "签字合同核查主流程",
    "scripts/send_rejection_email.py": "婉拒邮件主流程",
    "scripts/update_status.py": "招募状态推进主流程",
    "scripts/export_badcase_snapshots.py": "Badcase 回流执行节点",
    "config.yaml": "运行配置会影响所有节点",
}

CONFIG_GOVERNANCE = {
    ".gitignore": "配置与密钥文件追踪边界",
    "config.example.yaml": "VM 安装配置模板，不包含真实密钥",
}

OBSERVATION_LAYER = {
    "scripts/agent_router.py": "稳定唤起和短期会话 Router 协议层，只做意图分类和前置条件判断",
    "scripts/manual_trace.py": "受控手动串联流程日志写入模块",
    "scripts/trace_span.py": "trace/span 标准化旁路模型，不改变业务结果",
    "scripts/workflow_engine.py": "流程日志、checkpoint、可视化包装层",
    "scripts/workflow_runner.py": "统一入口和状态路由包装层",
    "scripts/run_dialog.py": "对话式恢复和待决策包装层",
    "scripts/rescore_and_write_v2.py": "评分可视化包装层",
    "scripts/send_test_email_v2.py": "测试题邮件可视化包装层",
    "scripts/generate_contract_v2.py": "合同生成可视化包装层",
    "scripts/run_testmode_demo.py": "Demo 证据采集工具",
    "scripts/run_fixture_demo.py": "脱敏最终演示 fixture runner，只生成旁路证据和 checkpoint transcript",
}

SCHEMA_AND_QA = {
    "scripts/schema_validator.py": "Lark 表准入校验",
    "scripts/schema_gate.py": "正式运行门禁",
    "scripts/schema_inspector.py": "表结构读取工具",
    "scripts/integration_readiness.py": "只读集成验收",
    "scripts/regression_report.py": "只读变更回归报告",
    "scripts/eval_runner.py": "Agent 治理 eval 自动化入口",
    "scripts/replay_run.py": "Agent 运行回放和 trace/span 证据导出",
    "scripts/verify_pricing_rule_coverage.py": "评分规则主流市场覆盖检查",
    "references/lark-required-schema.yaml": "Lark 必需字段定义",
    "references/lark-field-dictionary.md": "字段语义字典",
    "config/lark-field-mapping.yaml": "当前 Lark 字段映射结果",
}

DOC_PREFIXES = (
    "references/",
    "HANDOVER.md",
    "README.md",
    "V2-PROJECT.md",
    "SKILL.md",
)


def git_status() -> list[dict]:
    proc = subprocess.run(
        ["git", "status", "--short"],
        cwd=SKILL_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    items = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        status = line[:2].strip()
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        items.append({"status": status, "path": path})
    return items


def classify(path: str) -> dict:
    if path in MAIN_FLOW_SCRIPTS:
        return {
            "impact": "main_flow",
            "label": "影响主流程",
            "reason": MAIN_FLOW_SCRIPTS[path],
            "required_qa": "必须跑对应单节点 dry-run/TEST_MODE，并确认 Lark 读写字段、输出和安全边界",
        }
    if path in CONFIG_GOVERNANCE:
        return {
            "impact": "schema_qa",
            "label": "准入/QA",
            "reason": CONFIG_GOVERNANCE[path],
            "required_qa": "必须跑 check_config.py，并确认真实配置只存在本机 local 文件、模板无密钥",
        }
    if path in OBSERVATION_LAYER:
        return {
            "impact": "observation",
            "label": "旁路观测",
            "reason": OBSERVATION_LAYER[path],
            "required_qa": "必须跑集成验收，确认只复用原脚本，不接管业务判断",
        }
    if path in SCHEMA_AND_QA:
        return {
            "impact": "schema_qa",
            "label": "准入/QA",
            "reason": SCHEMA_AND_QA[path],
            "required_qa": "必须跑 schema_validator / integration_readiness，确认映射和门禁结果",
        }
    if path.startswith("tests/") or path.startswith("config/resume_screening_rules"):
        return {
            "impact": "rules_tests",
            "label": "规则/测试",
            "reason": "评分规则或测试用例会影响评分结果判断",
            "required_qa": "必须跑 tests/run_tests.py，并抽样验证真实候选人评分",
        }
    if path.startswith("demo_fixtures/"):
        return {
            "impact": "observation",
            "label": "旁路观测",
            "reason": "脱敏演示测试集，不写 Lark、不发送邮件、不改变主流程",
            "required_qa": "必须跑 scripts/run_fixture_demo.py，并确认 fixture 预期与真实评分引擎输出一致",
        }
    if path.startswith(DOC_PREFIXES):
        return {
            "impact": "docs",
            "label": "文档/交接",
            "reason": "不直接执行业务逻辑，但会影响 VM 安装和使用理解",
            "required_qa": "检查文档是否与当前脚本行为一致",
        }
    return {
        "impact": "unknown",
        "label": "未分类",
        "reason": "未纳入回归分类表，需要人工判断是否影响主流程",
        "required_qa": "先人工归类，再决定是否跑主流程单节点 QA",
    }


def build_report() -> dict:
    changed = []
    counts = {}
    for item in git_status():
        cls = classify(item["path"])
        row = {**item, **cls}
        changed.append(row)
        counts[row["impact"]] = counts.get(row["impact"], 0) + 1

    main_flow = [row for row in changed if row["impact"] == "main_flow"]
    unknown = [row for row in changed if row["impact"] == "unknown"]
    observation = [row for row in changed if row["impact"] == "observation"]

    if unknown:
        gate = "BLOCKED"
        conclusion = "存在未分类改动，不能直接判断是否可进入生产验证。"
    elif main_flow:
        gate = "NEEDS_NODE_QA"
        conclusion = "存在主流程影响改动，必须完成对应单节点 dry-run/TEST_MODE 后再宣称稳定。"
    elif observation:
        gate = "OBSERVATION_ONLY"
        conclusion = "当前改动主要是旁路观测层，重点确认不接管原业务逻辑。"
    else:
        gate = "LOW_RISK"
        conclusion = "当前未发现主流程影响改动。"

    return {
        "gate": gate,
        "conclusion": conclusion,
        "counts": counts,
        "changed": changed,
        "recommended_commands": [
            "PYTHONPYCACHEPREFIX=/tmp/loc-resume-pycache python3 scripts/integration_readiness.py",
            "python3 scripts/schema_validator.py --table all",
            "python3 tests/run_tests.py",
            "python3 scripts/rescore_and_write.py --record-id <rec> --dry-run",
            "python3 scripts/send_test_email.py --record-id <rec> --file <path> --dry-run",
            "python3 scripts/generate_contract.py --record-id <rec> --dry-run",
        ],
    }


def print_human(report: dict) -> None:
    print("资源管理 Agent 变更后回归报告")
    print("=" * 60)
    print(f"结论: {report['gate']}")
    print(report["conclusion"])
    print()

    if not report["changed"]:
        print("当前没有 git 变更。")
        return

    groups = [
        ("main_flow", "影响主流程"),
        ("observation", "旁路观测"),
        ("schema_qa", "准入/QA"),
        ("rules_tests", "规则/测试"),
        ("docs", "文档/交接"),
        ("unknown", "未分类"),
    ]
    for key, title in groups:
        rows = [row for row in report["changed"] if row["impact"] == key]
        if not rows:
            continue
        print(f"\n{title}：{len(rows)}")
        for row in rows:
            print(f"- {row['status']:<2} {row['path']}")
            print(f"  原因：{row['reason']}")
            print(f"  QA：{row['required_qa']}")

    print("\n建议命令：")
    for cmd in report["recommended_commands"]:
        print(f"- {cmd}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only regression report after changes")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)


if __name__ == "__main__":
    main()
