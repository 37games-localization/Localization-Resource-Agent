#!/usr/bin/env python3
"""
Verify Lark pricing-rule coverage for main localization markets.

This check reads the configured pricing_rules table, normalizes language-pair
keys, and reports whether all required market directions are present.
"""

from __future__ import annotations

import json
import sys

from pricing_rules import PricingRulesError, load_price_rules


REQUIRED_MAIN_MARKET_RULE_KEYS = {
    "en>ar",
    "en>de",
    "en>es",
    "en>fr",
    "en>id",
    "en>it",
    "en>ms",
    "en>nl",
    "en>pl",
    "en>pt",
    "en>ru",
    "en>th",
    "en>tr",
    "en>vi",
    "zh-CN>ar",
    "zh-CN>en",
    "zh-CN>id",
    "zh-CN>ja",
    "zh-CN>ko",
    "zh-CN>ms",
    "zh-CN>th",
    "zh-CN>vi",
}


def main() -> int:
    try:
        rules, meta = load_price_rules(require_lark_rules=True)
    except PricingRulesError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    available = set(rules)
    missing = sorted(REQUIRED_MAIN_MARKET_RULE_KEYS - available)
    extra = sorted(available - REQUIRED_MAIN_MARKET_RULE_KEYS)
    payload = {
        "ok": not missing,
        "source": meta.get("source"),
        "table_id": meta.get("table_id"),
        "required_count": len(REQUIRED_MAIN_MARKET_RULE_KEYS),
        "available_count": len(available),
        "missing": missing,
        "extra": extra,
        "available": sorted(available),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
