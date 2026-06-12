#!/usr/bin/env python3
"""
integration_readiness.py
========================
Read-only readiness check for the v2 workflow-visualization layer.

This script does not run business actions. It checks whether the verified
single-step scripts are still present, whether the v2 wrappers are wired to
reuse those scripts, whether key entrypoints compile, and whether the schema
mapping gate is ready for each operation.
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
SKILL_DIR = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))

from config_loader import load_config, is_test_mode
from schema_gate import validate_mapping_for


CHECKS = [
    {
        "id": "score",
        "name": "评分写回",
        "core_script": "rescore_and_write.py",
        "v2_script": "rescore_and_write_v2.py",
        "must_contain": [
            "from rescore_and_write import",
            "write_record",
            "WorkflowEngine",
        ],
        "schema_operation": "score",
        "production_ready_after": "VM 用真实 record_id 验证评分结果、Lark 写回字段、流程日志均一致",
    },
    {
        "id": "test-email",
        "name": "测试题邮件",
        "core_script": "send_test_email.py",
        "v2_script": "send_test_email_v2.py",
        "must_contain": [
            "from send_test_email import",
            "update_record",
            "WorkflowEngine",
        ],
        "schema_operation": "test-email",
        "production_ready_after": "VM 用真实附件验证 TEST_MODE 收件、状态写回、发送时间写回均一致",
    },
    {
        "id": "contract",
        "name": "合同生成",
        "core_script": "generate_contract.py",
        "v2_script": "generate_contract_v2.py",
        "must_contain": [
            "from generate_contract import",
            "pick_template_for_candidate",
            "WorkflowEngine",
        ],
        "schema_operation": "contract",
        "production_ready_after": "VM 用真实合同信息验证模板匹配、变量填充、dry-run 结果均一致",
    },
]

ENTRYPOINTS = [
    "workflow_engine.py",
    "run_dialog.py",
    "workflow_runner.py",
    "schema_gate.py",
    "run_testmode_demo.py",
]


def check_file(path: Path) -> dict:
    return {
        "path": str(path.relative_to(SKILL_DIR)),
        "ok": path.exists(),
        "message": "exists" if path.exists() else "missing",
    }


def check_compile(path: Path) -> dict:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        return {"path": str(path.relative_to(SKILL_DIR)), "ok": True, "message": "compile ok"}
    except Exception as exc:
        return {"path": str(path.relative_to(SKILL_DIR)), "ok": False, "message": str(exc)}


def check_wrapper_uses_core(v2_path: Path, needles: list[str]) -> dict:
    if not v2_path.exists():
        return {"ok": False, "missing": needles, "message": "v2 script missing"}
    text = v2_path.read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in text]
    return {
        "ok": not missing,
        "missing": missing,
        "message": "wrapper reuses core" if not missing else "wrapper wiring is incomplete",
    }


def operation_result(item: dict) -> dict:
    core_path = SCRIPTS_DIR / item["core_script"]
    v2_path = SCRIPTS_DIR / item["v2_script"]
    schema = validate_mapping_for(item["schema_operation"])
    checks = {
        "core_script": check_file(core_path),
        "v2_script": check_file(v2_path),
        "v2_compile": check_compile(v2_path) if v2_path.exists() else {
            "path": str(v2_path.relative_to(SKILL_DIR)),
            "ok": False,
            "message": "missing",
        },
        "wrapper_reuses_core": check_wrapper_uses_core(v2_path, item["must_contain"]),
        "schema_mapping": schema,
    }
    ok = all([
        checks["core_script"]["ok"],
        checks["v2_script"]["ok"],
        checks["v2_compile"]["ok"],
        checks["wrapper_reuses_core"]["ok"],
        schema.get("ok", False),
    ])
    return {
        "id": item["id"],
        "name": item["name"],
        "ok": ok,
        "checks": checks,
        "production_ready_after": item["production_ready_after"],
    }


def build_report() -> dict:
    cfg = load_config()
    entrypoint_checks = []
    for script in ENTRYPOINTS:
        path = SCRIPTS_DIR / script
        item = check_file(path)
        if item["ok"]:
            compile_result = check_compile(path)
            item["compile_ok"] = compile_result["ok"]
            item["compile_message"] = compile_result["message"]
            item["ok"] = item["ok"] and compile_result["ok"]
        entrypoint_checks.append(item)

    operations = [operation_result(item) for item in CHECKS]
    overall_ok = all(item["ok"] for item in entrypoint_checks) and all(op["ok"] for op in operations)
    return {
        "ok": overall_ok,
        "test_mode": is_test_mode(cfg),
        "entrypoints": entrypoint_checks,
        "operations": operations,
        "next_gate": (
            "可以进入 VM 单步骤生产验证；暂不建议把 workflow_runner next 作为唯一主入口"
            if overall_ok else
            "先修复未通过项，再进入 VM 单步骤生产验证"
        ),
    }


def print_human(report: dict):
    print("资源管理 Agent v2 分步骤集成验收")
    print("=" * 60)
    print(f"TEST_MODE: {report['test_mode']}")
    print(f"总状态: {'PASS' if report['ok'] else 'BLOCKED'}")
    print()

    print("入口脚本")
    for item in report["entrypoints"]:
        status = "PASS" if item["ok"] else "FAIL"
        message = item.get("compile_message") or item["message"]
        print(f"- {status:<5} {item['path']}  {message}")
    print()

    print("单步骤等价包装")
    for op in report["operations"]:
        print(f"- {'PASS' if op['ok'] else 'FAIL'} {op['name']} ({op['id']})")
        for key, value in op["checks"].items():
            ok = value.get("ok", False)
            msg = value.get("message") or "; ".join(value.get("issues", [])) or "ok"
            print(f"  - {'PASS' if ok else 'FAIL'} {key}: {msg}")
        print(f"  - 下一验收条件：{op['production_ready_after']}")
    print()
    print(f"下一步：{report['next_gate']}")


def main():
    parser = argparse.ArgumentParser(description="Read-only v2 integration readiness check")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)

    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
