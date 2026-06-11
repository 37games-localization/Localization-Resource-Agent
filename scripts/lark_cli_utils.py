"""
lark_cli_utils.py
=================
Shared lark-cli helpers with narrow retry handling for transient API errors.
"""

import json
import subprocess
import time


TRANSIENT_MARKERS = (
    "service unavailable",
    '"code": 2200',
    "timeout",
    "timed out",
    "temporarily unavailable",
    "bad gateway",
    "gateway timeout",
)


def is_transient_lark_error(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in TRANSIENT_MARKERS)


def run_lark_cli_json(*args, retries: int = 2, base_sleep: float = 1.0):
    """Run lark-cli and return parsed JSON, retrying only transient failures."""
    cmd = ["lark-cli"] + list(args)
    last_output = ""
    for attempt in range(retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = (result.stdout or "") + (result.stderr or "")
        last_output = output.strip()

        if result.returncode == 0:
            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError:
                return result.stdout.strip()
            if isinstance(parsed, dict) and parsed.get("ok") is False:
                if attempt < retries and is_transient_lark_error(json.dumps(parsed, ensure_ascii=False)):
                    time.sleep(base_sleep * (attempt + 1))
                    continue
            return parsed

        if attempt < retries and is_transient_lark_error(output):
            time.sleep(base_sleep * (attempt + 1))
            continue
        raise RuntimeError(f"lark-cli 失败:\n{last_output}")

    raise RuntimeError(f"lark-cli 失败:\n{last_output}")
