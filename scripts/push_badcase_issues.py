#!/usr/bin/env python3
"""
push_badcase_issues.py  (project side)
======================================
Create standardized GitHub issues from sanitized badcase snapshot JSON files.

This script intentionally does not accept free-form issue text. Every issue must
come from a snapshot that passes badcase_protocol.validate_snapshot().

Usage:
    python3 scripts/push_badcase_issues.py --snapshot badcase_xxx.json --dry-run
    python3 scripts/push_badcase_issues.py --dir ~/Downloads/badcase_snapshots --dry-run
    python3 scripts/push_badcase_issues.py --snapshot badcase_xxx.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from badcase_protocol import issue_body, issue_labels, issue_title, validate_snapshot


def load_snapshot(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_snapshot(data)
    return data


def iter_snapshot_paths(args) -> list[Path]:
    paths: list[Path] = []
    for item in args.snapshot or []:
        paths.append(Path(item).expanduser())
    if args.dir:
        base = Path(args.dir).expanduser()
        paths.extend(sorted(base.glob("badcase_*.json")))
    unique = []
    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def create_issue(snapshot: dict, dry_run: bool) -> bool:
    title = issue_title(snapshot)
    body = issue_body(snapshot)
    labels = issue_labels(snapshot)

    if dry_run:
        print("\n" + "=" * 72)
        print(f"[dry-run] GitHub issue title:\n{title}")
        print(f"[dry-run] Labels: {', '.join(labels)}")
        print("-" * 72)
        print(body)
        print("=" * 72)
        return True

    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels:
        cmd += ["--label", label]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ GitHub issue 创建失败：{result.stderr or result.stdout}")
        return False
    print(f"✅ GitHub issue 已创建：{result.stdout.strip()}")
    return True


def main():
    parser = argparse.ArgumentParser(description="从脱敏 badcase snapshot 创建统一格式 GitHub issue")
    parser.add_argument("--snapshot", action="append", help="单个 snapshot JSON 路径；可重复传入")
    parser.add_argument("--dir", help="包含 badcase_*.json 的目录")
    parser.add_argument("--dry-run", action="store_true", help="只打印 issue 标题/正文/label，不创建")
    args = parser.parse_args()

    paths = iter_snapshot_paths(args)
    if not paths:
        print("❌ 请提供 --snapshot 或 --dir")
        sys.exit(1)

    ok = 0
    for path in paths:
        try:
            snapshot = load_snapshot(path)
        except Exception as e:
            print(f"⛔ 跳过 {path}：snapshot 校验失败：{e}")
            continue
        if create_issue(snapshot, args.dry_run):
            ok += 1

    print(f"\n完成：成功 {ok}/{len(paths)}")
    sys.exit(0 if ok == len(paths) else 1)


if __name__ == "__main__":
    main()
