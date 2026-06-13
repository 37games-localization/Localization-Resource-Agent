#!/usr/bin/env python3
"""
Lock a VM/user installation so daily usage cannot casually edit core files.

This is a guardrail, not a security boundary. A user with filesystem ownership
can still unlock files, but the default Agent workflow should treat locked core
files as read-only and route change requests through Badcase / maintainer review.
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROTECTED_PATHS = [
    ROOT / "README.md",
    ROOT / "SKILL.md",
    ROOT / "config.example.yaml",
    ROOT / "config" / "resume_screening_rules_v2.json",
    ROOT / "frontend" / "src",
    ROOT / "frontend" / "package.json",
    ROOT / "frontend" / "package-lock.json",
    ROOT / "frontend" / "tsconfig.json",
    ROOT / "frontend" / "next.config.mjs",
    ROOT / "frontend" / ".eslintrc.json",
    ROOT / "references",
    ROOT / "scripts",
]

ALLOWED_WRITABLE = {
    ROOT / "config.local.yaml",
    ROOT / "config.yaml",
    ROOT / "config" / "lark-field-mapping.yaml",
}


def iter_existing_paths(paths: list[Path]):
    for target in paths:
        if not target.exists():
            continue
        if target.is_dir():
            for child in target.rglob("*"):
                if "__pycache__" in child.parts:
                    continue
                yield child
        yield target


def remove_write_bits(mode: int) -> int:
    return mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH


def add_user_write_bit(mode: int) -> int:
    return mode | stat.S_IWUSR


def chmod_path(path: Path, *, unlock: bool) -> tuple[bool, str]:
    if path in ALLOWED_WRITABLE:
        return False, "allowed-writable"
    try:
        current = path.stat().st_mode
        next_mode = add_user_write_bit(current) if unlock else remove_write_bits(current)
        if next_mode == current:
            return False, "unchanged"
        os.chmod(path, next_mode)
        return True, "updated"
    except PermissionError:
        return False, "permission-denied"
    except FileNotFoundError:
        return False, "missing"


def disable_git_push() -> str:
    if not (ROOT / ".git").exists():
        return "not-a-git-checkout"
    result = subprocess.run(
        ["git", "remote", "set-url", "--push", "origin", "DISABLED"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return f"failed: {result.stderr.strip() or result.stdout.strip()}"
    return "disabled"


def main() -> int:
    parser = argparse.ArgumentParser(description="Lock or unlock VM install core files.")
    parser.add_argument("--unlock", action="store_true", help="Maintainer-only: restore user write bit on protected files.")
    parser.add_argument(
        "--keep-git-push",
        action="store_true",
        help="Do not disable git push URL. Default lock behavior disables accidental push.",
    )
    args = parser.parse_args()

    if args.unlock and os.environ.get("LOC_AGENT_MAINTAINER") != "1":
        print("Refusing unlock: set LOC_AGENT_MAINTAINER=1 if you are the project maintainer.")
        return 2

    updated = 0
    skipped = 0
    failures: list[str] = []

    for path in iter_existing_paths(PROTECTED_PATHS):
        changed, reason = chmod_path(path, unlock=args.unlock)
        if changed:
            updated += 1
        elif reason == "permission-denied":
            failures.append(str(path.relative_to(ROOT)))
        else:
            skipped += 1

    push_status = "not-changed"
    if not args.unlock and not args.keep_git_push:
        push_status = disable_git_push()

    action = "unlocked" if args.unlock else "locked"
    print(f"{action}: updated={updated}, skipped={skipped}, git_push={push_status}")

    if failures:
        print("permission denied:")
        for item in failures:
            print(f"- {item}")
        return 1

    if not args.unlock:
        print("Writable user files remain: config.local.yaml, config.yaml, config/lark-field-mapping.yaml")
        print("Core workflow changes should be reported as Badcase or handled by the maintainer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
