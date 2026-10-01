#!/usr/bin/env python3
"""Benchmark + totals diff for the OpenClaw source parser.

Prints per-window token/message/cost totals AND parse latency, so the
file-set restriction + dedup + cache change can be validated: today/7d must
stay identical, 30d/365d should drop (the
checkpoint double-count correction), and warm calls should be near-instant.

Run from repo root:  python scripts/bench_openclaw.py
"""

import sys
import time
from pathlib import Path

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from tokdash.sources import openclaw as O  # noqa: E402

WINDOWS = [("today", 1), ("7d", 7), ("30d", 30), ("365d", 365)]


def _fmt(n: float) -> str:
    return f"{n:,.0f}" if abs(n) >= 1000 else f"{n}"


def run() -> None:
    print(f"{'window':8s} {'cold(s)':>8s} {'warm(s)':>8s} {'tokens':>16s} {'messages':>10s} {'cost($)':>10s}")
    for label, days in WINDOWS:
        # Best-effort cache reset between windows so 'cold' reflects a fresh parse
        # if the implementation exposes an entry cache; harmless otherwise.
        for attr in ("_ENTRY_CACHE",):
            cache = getattr(O, attr, None)
            if isinstance(cache, dict):
                cache.clear()

        t0 = time.perf_counter()
        data = O.get_usage_for_days(days)
        cold = time.perf_counter() - t0

        t1 = time.perf_counter()
        O.get_usage_for_days(days)
        warm = time.perf_counter() - t1

        print(
            f"{label:8s} {cold:8.3f} {warm:8.3f} "
            f"{_fmt(data['total_tokens']):>16s} {_fmt(data['total_messages']):>10s} "
            f"{data['total_cost']:>10.2f}"
        )


if __name__ == "__main__":
    run()
