#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen


DEFAULT_ENDPOINTS = [
    "/api/usage?period=today",
    "/api/tools?period=today",
    "/api/openclaw?period=today",
    "/api/stats",
]


def _fetch(base_url: str, endpoint: str, timeout: int, retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            with urlopen(base_url.rstrip("/") + endpoint, timeout=timeout) as response:
                body = response.read()
            return json.loads(body)
        except HTTPError as exc:
            last_error = exc
            if exc.code != 503 or attempt >= retries:
                raise
            time.sleep(2 + attempt)
    if last_error:
        raise last_error
    raise RuntimeError("fetch failed without an exception")


def _get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _metrics(endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
    if endpoint.startswith("/api/stats"):
        return {
            "tokens": _get_path(data, "summary.totalTokens"),
            "cost": round(float(_get_path(data, "summary.totalCost") or 0.0), 2),
            "messages": _get_path(data, "stats.sessions"),
            "activeDays": _get_path(data, "summary.activeDays"),
        }
    return {
        "tokens": data.get("total_tokens") or data.get("totalTokens"),
        "cost": round(float(data.get("total_cost") or data.get("totalCost") or 0.0), 2),
        "messages": data.get("total_messages") or data.get("totalMessages"),
    }


def _compare_endpoint(
    stable_url: str,
    dev_url: str,
    endpoint: str,
    timeout: int,
    retries: int,
    settle_retries: int,
    settle_sleep: float,
) -> dict[str, Any]:
    attempts = []
    for attempt in range(max(1, settle_retries + 1)):
        # Stable first, dev second. In an actively logging environment this avoids
        # comparing a dev snapshot captured before a slower stable full parse.
        stable = _fetch(stable_url, endpoint, timeout, retries)
        dev = _fetch(dev_url, endpoint, timeout, retries)
        stable_metrics = _metrics(endpoint, stable)
        dev_metrics = _metrics(endpoint, dev)
        diff = {
            key: (dev_metrics.get(key) or 0) - (stable_metrics.get(key) or 0)
            for key in sorted(set(stable_metrics) | set(dev_metrics))
        }
        row_ok = all(value == 0 for value in diff.values())
        row = {
            "endpoint": endpoint,
            "ok": row_ok,
            "stable": stable_metrics,
            "dev": dev_metrics,
            "diff": diff,
            "attempt": attempt + 1,
        }
        attempts.append(row)
        if row_ok or attempt >= settle_retries:
            if len(attempts) > 1:
                row["attempts"] = [dict(item) for item in attempts[:-1]]
            return row
        time.sleep(settle_sleep)
    raise RuntimeError("unreachable settle loop")


def compare_once(
    stable_url: str,
    dev_url: str,
    endpoints: list[str],
    timeout: int,
    retries: int,
    settle_retries: int,
    settle_sleep: float,
) -> dict[str, Any]:
    rows = []
    ok = True
    for endpoint in endpoints:
        row = _compare_endpoint(
            stable_url,
            dev_url,
            endpoint,
            timeout,
            retries,
            settle_retries,
            settle_sleep,
        )
        ok = ok and bool(row.get("ok"))
        rows.append(row)
    return {"ok": ok, "checked_at": datetime.now(timezone.utc).isoformat(), "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare stable and dev Tokdash API totals over time.")
    parser.add_argument("--stable-url", required=True)
    parser.add_argument("--dev-url", required=True)
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--settle-retries", type=int, default=2)
    parser.add_argument("--settle-sleep", type=float, default=5.0)
    parser.add_argument("--endpoint", action="append", dest="endpoints")
    parser.add_argument("--output", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    endpoints = args.endpoints or DEFAULT_ENDPOINTS
    deadline = time.monotonic() + max(1, args.duration_seconds)
    results = []
    iteration = 0
    all_ok = True

    while True:
        iteration += 1
        result = compare_once(
            args.stable_url,
            args.dev_url,
            endpoints,
            args.timeout,
            args.retries,
            args.settle_retries,
            args.settle_sleep,
        )
        result["iteration"] = iteration
        results.append(result)
        all_ok = all_ok and bool(result.get("ok"))
        if not args.quiet:
            print(json.dumps(result, sort_keys=True), flush=True)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(max(0, args.interval_seconds), remaining))

    summary = {
        "ok": all_ok,
        "iterations": len(results),
        "stable_url": args.stable_url,
        "dev_url": args.dev_url,
        "endpoints": endpoints,
        "results": results,
    }
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
