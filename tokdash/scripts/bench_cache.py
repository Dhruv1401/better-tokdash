#!/usr/bin/env python3
"""Benchmark: parser-level caching in coding_tools.py.

Run from repo root:
    python scripts/bench_cache.py

Or if not installed editable:
    PYTHONPATH=src python scripts/bench_cache.py
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure src/ is importable when running as a script.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from tokdash.sources.coding_tools import BaseParser, CodingToolsUsageTracker  # noqa: E402


def _clear_caches():
    """Reset all parser-level caches to simulate a cold start."""
    BaseParser._entry_cache.clear()
    from tokdash.sources.coding_tools import _sig_cache, OpenCodeParser
    _sig_cache.clear()
    OpenCodeParser._query_cache.clear()
    OpenCodeParser._query_cache_sig = ()


def bench_collect(label: str, since: datetime, until: datetime) -> float:
    tracker = CodingToolsUsageTracker()
    t0 = time.perf_counter()
    tracker.collect(since, until)
    elapsed = time.perf_counter() - t0
    print(f"  {label}: {elapsed:.3f}s  ({len(tracker.entries)} entries)")
    return elapsed


def main():
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    three_days_ago = today_start - timedelta(days=3)

    print("=" * 60)
    print("Parser-level cache benchmark")
    print("=" * 60)

    # --- Cold run ---
    _clear_caches()
    print("\n1) Cold parse (no cache):")
    t_cold = bench_collect("today", today_start, now)

    # --- Warm run, same dates ---
    print("\n2) Warm run, same date range (full cache hit):")
    t_warm_same = bench_collect("today (cached)", today_start, now)

    # --- Warm run, different dates (the key improvement) ---
    print("\n3) Warm run, DIFFERENT date range (cache hit + in-memory filter):")
    t_warm_diff = bench_collect("yesterday", yesterday_start, today_start)

    # --- Warm run, another range ---
    print("\n4) Warm run, 3-day range:")
    bench_collect("last 3 days", three_days_ago, now)

    # --- compute_usage_with_comparison (calls collect twice internally) ---
    _clear_caches()
    from tokdash.compute import compute_usage_with_comparison
    print("\n5) compute_usage_with_comparison('today') - cold:")
    t0 = time.perf_counter()
    result = compute_usage_with_comparison("today")
    t_comp_cold = time.perf_counter() - t0
    print(f"  cold: {t_comp_cold:.3f}s  (cost=${result['total_cost']:.2f})")

    print("\n6) compute_usage_with_comparison('today') - warm:")
    t0 = time.perf_counter()
    result = compute_usage_with_comparison("today")
    t_comp_warm = time.perf_counter() - t0
    print(f"  warm: {t_comp_warm:.3f}s  (cost=${result['total_cost']:.2f})")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Cold parse:               {t_cold:.3f}s")
    print(f"  Warm same-range:          {t_warm_same:.3f}s")
    print(f"  Warm different-range:     {t_warm_diff:.3f}s")
    if t_cold > 0:
        print(f"  Speedup (date switch):    {t_cold / max(t_warm_diff, 0.001):.0f}x")
    print(f"  compute_usage cold:       {t_comp_cold:.3f}s")
    print(f"  compute_usage warm:       {t_comp_warm:.3f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
