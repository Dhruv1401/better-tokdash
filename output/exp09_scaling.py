"""EXP-09: performance scaling.

Part A: Codex parse + store sync + aggregate at 1k / 10k / 100k events.
Part B: sessions assembly at 10 / 100 / 1000 / 5000 sessions.
Flags superlinear growth (time ratio >> size ratio).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))


def iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build_codex(n, home, t0=1_770_000_000_000):
    d = home / ".codex" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta",
                         "payload": {"id": "sess1"}}),
             json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context",
                         "payload": {"model": "gpt-5.3"}})]
    for i in range(n):
        info = {"id": f"u{i}",
                "total_token_usage": {"input_tokens": 100 + (i % 97), "cached_input_tokens": 10,
                                      "output_tokens": 50, "reasoning_output_tokens": 3},
                "last_token_usage": {"input_tokens": 100 + (i % 97), "cached_input_tokens": 10,
                                     "output_tokens": 50, "reasoning_output_tokens": 3}}
        lines.append(json.dumps({"timestamp": iso(t0 + i * 1000), "type": "event_msg",
                                 "payload": {"type": "token_count", "info": info}}))
    (d / "rollout.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return (time.perf_counter() - t) * 1000.0, out


def part_a():
    print("== Part A: Codex events ==")
    prev = None
    for n in (1_000, 10_000, 100_000):
        home = Path(tempfile.mkdtemp(prefix=f"perf-{n}-"))
        data = Path(tempfile.mkdtemp(prefix=f"perfd-{n}-"))
        os.environ["TOKDASH_DATA_DIR"] = str(data)
        os.environ["TOKDASH_USAGE_DB"] = "0"
        import pathlib
        pathlib.Path.home = classmethod(lambda cls: home)
        build_codex(n, home)
        from tokdash.pricing import PricingDatabase
        from tokdash.sources.coding_tools import CodexParser
        from tokdash import compute
        parser = CodexParser(PricingDatabase())
        ms, entries = timed(parser._parse_all)
        from tokdash.sources.coding_tools import BaseParser
        BaseParser._entry_cache.clear()
        ms2, agg = timed(lambda: compute.get_tools_data_for_range(None, None, sync=False))
        ratio = f"  x{ms/prev:.1f} vs prev parse" if prev else ""
        print(f"n={n:>7}: parse {ms:8.0f} ms{ratio} | aggregate(no-sync) {ms2:8.0f} ms | "
              f"cost={agg.get('total_cost', 0):.4f}")
        prev = ms


def part_b():
    print("== Part B: Codex session assembly ==")
    import tokdash.compute as compute
    import tokdash.sessions as sessions

    prev = None
    for n_sessions in (10, 100, 1000, 5000):
        home = Path(tempfile.mkdtemp(prefix=f"sperf-{n_sessions}-"))
        data = Path(tempfile.mkdtemp(prefix=f"sperfd-{n_sessions}-"))
        os.environ["TOKDASH_DATA_DIR"] = str(data)
        os.environ["TOKDASH_USAGE_DB"] = "0"
        import pathlib
        pathlib.Path.home = classmethod(lambda cls: home)
        t0 = 1_770_000_000_000
        d = home / ".codex" / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        for s in range(n_sessions):
            lines = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta",
                                 "payload": {"id": f"sess{s}"}}),
                     json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context",
                                 "payload": {"model": "gpt-5.3"}})]
            for i in range(20):  # 20 events per session
                info = {"id": f"u{s}-{i}",
                        "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 10,
                                              "output_tokens": 50, "reasoning_output_tokens": 3},
                        "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 10,
                                             "output_tokens": 50, "reasoning_output_tokens": 3}}
                lines.append(json.dumps({"timestamp": iso(t0 + i * 1000 + s), "type": "event_msg",
                                         "payload": {"type": "token_count", "info": info}}))
            (d / f"rollout-{s}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        sessions._sig_cache.clear() if hasattr(sessions, "_sig_cache") else None
        ms, result = timed(lambda: sessions.get_sessions_data("codex", "year"))
        k = len(result.get("sessions", []))
        ratio = f"  x{ms/prev:.1f}" if prev else ""
        print(f"sessions={n_sessions:>5}: assemble {ms:8.0f} ms{ratio} | returned {k}")
        prev = ms


if __name__ == "__main__":
    part_a()
    part_b()
