#!/usr/bin/env python3
"""
privacy_scan.py
===============
Fail-fast scan for sensitive data that must not enter the shared repository.

This scans tracked files in the current working tree. It is intentionally
conservative: examples should use placeholders such as example.com, <record_id>,
<table_id>, and <local-file>.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_SKIP = {
    "references/legacy-pricing-rules-2026-05-28.json",
    "frontend/package-lock.json",
}

PATTERNS: list[tuple[str, str]] = [
    (r"(?<![\w.-])[A-Za-z0-9._%+\-]+@(?!example\.com\b)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "非示例邮箱"),
    (r"/Users/[A-Za-z0-9._\-]+", "macOS 本机绝对路径"),
    (r"\btbl(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,}\b", "Lark table_id 疑似"),
    (r"\brec(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,}\b", "Lark record_id 疑似"),
    (r"\b[A-Za-z0-9]{18,}@[A-Za-z0-9._-]+\b", "Lark/云文档 token 疑似"),
    (r"\b(?:sk|sk-proj|sk-ant|ghp|github_pat)-[A-Za-z0-9_\-]{12,}\b", "API/GitHub key 疑似"),
    (r"(?i)^\s*(?:password|secret|api[_-]?key|token)\s*:\s*['\"]?(?!$|<|your_|example|REDACTED|你的)[^\s'\"#]+", "密钥配置疑似"),
]

ALLOW_LINE_PATTERNS = [
    re.compile(r"example\.com"),
    re.compile(r"<[^>\n]+>"),
    re.compile(r"record_id"),
    re.compile(r"recipient_email"),
    re.compile(r"recommended_commands"),
    re.compile(r"def recommend|self\.recommend"),
]


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def should_skip(path: Path) -> bool:
    text = path.as_posix()
    if text in DEFAULT_SKIP:
        return True
    return any(part in {".git", "__pycache__", ".next"} for part in path.parts)


def is_allowed_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in ALLOW_LINE_PATTERNS)


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, label in PATTERNS:
            if re.search(pattern, line):
                if is_allowed_line(line):
                    continue
                findings.append(f"{path}:{lineno}: {label}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan tracked files for sensitive data")
    parser.add_argument("--show", action="store_true", help="显示命中位置；默认只显示摘要")
    args = parser.parse_args()

    findings: list[str] = []
    for path in tracked_files():
        if should_skip(path):
            continue
        findings.extend(scan_file(path))

    if findings:
        print(f"❌ privacy scan failed: {len(findings)} finding(s)")
        for item in findings if args.show else findings[:20]:
            print(item)
        if not args.show and len(findings) > 20:
            print(f"... 还有 {len(findings) - 20} 条，使用 --show 查看")
        return 1

    print("✅ privacy scan passed: tracked files contain no obvious sensitive data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
