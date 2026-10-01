#!/usr/bin/env python3
"""Measure per-endpoint latency to identify remaining bottlenecks."""

import sys
import time
from pathlib import Path

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from tokdash.sources.coding_tools import BaseParser, _sig_cache, OpenCodeParser  # noqa: E402


def _clear_caches():
    BaseParser._entry_cache.clear()
    _sig_cache.clear()
    OpenCodeParser._query_cache.clear()
    OpenCodeParser._query_cache_sig = ()

from fastapi.testclient import TestClient  # noqa: E402
from tokdash.api import app, _cache  # noqa: E402

client = TestClient(app)


def timed(label, fn):
    t0 = time.perf_counter()
    r = fn()
    elapsed = time.perf_counter() - t0
    status = r.status_code if hasattr(r, 'status_code') else '?'
    print(f"  {label:45s} {elapsed:.3f}s  (status={status})")
    return elapsed


def run_suite(title, date_from, date_to):
    print(f"\n--- {title} (date_from={date_from}, date_to={date_to}) ---")
    _cache.clear()  # clear API-level cache to simulate fresh date switch

    t_usage = timed("/api/usage", lambda: client.get("/api/usage", params={"date_from": date_from, "date_to": date_to}))
    t_codex = timed("/api/sessions?tool=codex", lambda: client.get("/api/sessions", params={"tool": "codex", "date_from": date_from, "date_to": date_to}))
    t_claude = timed("/api/sessions?tool=claude", lambda: client.get("/api/sessions", params={"tool": "claude", "date_from": date_from, "date_to": date_to}))
    t_opencode = timed("/api/sessions?tool=opencode", lambda: client.get("/api/sessions", params={"tool": "opencode", "date_from": date_from, "date_to": date_to}))

    total = t_usage + t_codex + t_claude + t_opencode
    worst = max(t_usage, t_codex, t_claude, t_opencode)
    print(f"  {'TOTAL (sequential)':45s} {total:.3f}s")
    print(f"  {'WORST (parallel lower bound)':45s} {worst:.3f}s")


def main():
    print("=" * 60)
    print("API endpoint latency benchmark")
    print("=" * 60)

    # 1) Cold — no parser cache, no API cache
    _clear_caches()
    _cache.clear()
    run_suite("COLD (first load)", "2026-04-13", "2026-04-13")

    # 2) Same date, API cache cleared — parser cache warm
    run_suite("WARM same date", "2026-04-13", "2026-04-13")

    # 3) Different date — parser cache warm, new date filter
    run_suite("WARM different date", "2026-04-12", "2026-04-12")

    # 4) Another different date
    run_suite("WARM another date", "2026-04-10", "2026-04-11")

    print()


if __name__ == "__main__":
    main()
