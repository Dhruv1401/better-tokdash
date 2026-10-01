"""EXP-03: numeric fuzz across Codex/Claude/Grok/OpenClaw-style parsers.

Looks for: bad input -> no exception -> plausible output -> WRONG result.
Focus: negative deltas, huge ints, NaN/Infinity (json.loads accepts them),
string numerics, nulls, booleans.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))


def iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def codex_line(ts_ms, inp, cached, out, reasoning=0):
    info = {"id": "u1",
            "total_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                                  "output_tokens": out, "reasoning_output_tokens": reasoning},
            "last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                                 "output_tokens": out, "reasoning_output_tokens": reasoning}}
    return json.dumps({"timestamp": iso(ts_ms), "type": "event_msg",
                       "payload": {"type": "token_count", "info": info}})


def claude_line(ts_ms, inp, out, cr=0, cw=0):
    return json.dumps({"type": "assistant", "timestamp": iso(ts_ms),
                       "message": {"id": "msg_1", "role": "assistant",
                                   "model": "claude-sonnet-4-6",
                                   "usage": {"input_tokens": inp, "output_tokens": out,
                                             "cache_read_input_tokens": cr,
                                             "cache_creation_input_tokens": cw}}})


CASES = [
    ("normal",            dict(inp=100, cached=20, out=50)),
    ("negative_total",    dict(inp=-500, cached=0, out=50)),
    ("cached>total",      dict(inp=10, cached=40, out=50)),   # fresh input goes negative
    ("huge_int",          dict(inp=10**18, cached=0, out=50)),
    ("overflow_int",      dict(inp=10**30, cached=0, out=50)),
    ("nan",               dict(inp=float("nan"), cached=0, out=50)),
    ("inf",               dict(inp=float("inf"), cached=0, out=50)),
    ("neg_inf",           dict(inp=float("-inf"), cached=0, out=50)),
    ("string_num",        dict(inp="100", cached=0, out=50)),
    ("bool_true",         dict(inp=True, cached=0, out=50)),
    ("null",              dict(inp=None, cached=0, out=50)),
]


def run_parser(name, lines, home_fn):
    home = Path(tempfile.mkdtemp(prefix=f"fuzz-{name}-"))
    data = Path(tempfile.mkdtemp(prefix=f"fuzzd-{name}-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data)
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)
    home_fn(home, lines)
    from tokdash.pricing import PricingDatabase
    from tokdash.sources.coding_tools import CodingToolsUsageTracker
    tracker = CodingToolsUsageTracker()
    results = {}
    for src, parser in tracker.parsers.items():
        try:
            entries = parser.collect(None, None)
        except Exception as exc:
            results[src] = f"EXC {type(exc).__name__}: {exc}"
            continue
        tot_in = sum(int(e.get("input", 0) or 0) for e in entries)
        tot_out = sum(int(e.get("output", 0) or 0) for e in entries)
        tot_cr = sum(int(e.get("cacheRead", 0) or 0) for e in entries)
        cost = sum(float(e.get("cost", 0.0) or 0.0) for e in entries)
        results[src] = dict(n=len(entries), in_=tot_in, out=tot_out, cache_read=tot_cr,
                            cost=round(cost, 4))
    return results


def codex_home(home, lines):
    d = home / ".codex" / "sessions"
    d.mkdir(parents=True)
    (d / "rollout-1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def claude_home(home, lines):
    d = home / ".claude" / "projects" / "p"
    d.mkdir(parents=True)
    (d / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    t0 = 1_770_000_000_000
    for cname, kw in CASES:
        vals = {k: (v if not isinstance(v, float) or math.isfinite(v) else v) for k, v in kw.items()}
        # json.dumps refuses NaN only with allow_nan=False; default emits NaN/Infinity literals
        line = codex_line(t0, **vals)
        r = run_parser("codex", [line], codex_home)
        interesting = {k: v for k, v in r.items() if v and v != {} and k in ("codex",)}
        print(f"CODEX {cname:15s} -> {interesting.get('codex')}")
    print()
    for cname, kw in CASES:
        line = claude_line(t0, inp=kw.get("inp", 0) or 0, out=kw.get("out", 0) or 0,
                           cr=kw.get("cached", 0) or 0)
        r = run_parser("claude", [line], claude_home)
        interesting = {k: v for k, v in r.items() if v and v != {} and k in ("claude",)}
        print(f"CLAUDE {cname:14s} -> {interesting.get('claude')}")


if __name__ == "__main__":
    main()
