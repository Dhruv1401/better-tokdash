"""EXP-04: huge integer token count -> persistent store OverflowError -> silent fallback?

Hypothesis: one corrupt line with a >2^63 token count makes every store sync
throw, so get_tools_data_for_range silently falls back to full live parsing on
EVERY request (perf cliff), and `tokdash db sync` hard-fails.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))


def iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def main():
    home = Path(tempfile.mkdtemp(prefix="exp04-"))
    data = Path(tempfile.mkdtemp(prefix="exp04d-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data)
    os.environ["TOKDASH_USAGE_DB"] = "1"
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)

    # 500 normal Codex events + ONE corrupt event with a huge int
    lines = []
    t0 = 1_770_000_000_000
    for i in range(500):
        info = {"id": f"u{i}",
                "total_token_usage": {"input_tokens": 100 + i, "cached_input_tokens": 10,
                                      "output_tokens": 50, "reasoning_output_tokens": 0},
                "last_token_usage": {"input_tokens": 100 + i, "cached_input_tokens": 10,
                                     "output_tokens": 50, "reasoning_output_tokens": 0}}
        lines.append(json.dumps({"timestamp": iso(t0 + i * 1000), "type": "event_msg",
                                 "payload": {"type": "token_count", "info": info}}))
    bad = {"id": "uboom",
           "total_token_usage": {"input_tokens": 10 ** 25, "cached_input_tokens": 0,
                                 "output_tokens": 1, "reasoning_output_tokens": 0},
           "last_token_usage": {"input_tokens": 10 ** 25, "cached_input_tokens": 0,
                                "output_tokens": 1, "reasoning_output_tokens": 0}}
    lines.append(json.dumps({"timestamp": iso(t0 + 999_000), "type": "event_msg",
                             "payload": {"type": "token_count", "info": bad}}))
    # give the file a real model signal so rows are billable
    lines.insert(0, json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta",
                                "payload": {"id": "sess1"}}))
    lines.insert(1, json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context",
                                "payload": {"model": "gpt-5.3"}}))

    d = home / ".codex" / "sessions"
    d.mkdir(parents=True)
    (d / "rollout.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    from tokdash.pricing import PricingDatabase
    from tokdash.sources.coding_tools import CodingToolsUsageTracker, CodexParser
    from tokdash.usage_store import UsageEntryStore

    pdb = PricingDatabase()
    parser = CodexParser(pdb)
    live = parser._parse_all()
    print(f"LIVE parse ok: {len(live)} entries, in={sum(e['input'] for e in live)}")

    store = UsageEntryStore(db_path=data / "usage.sqlite3")
    try:
        store.sync_files("codex", parser._file_signatures(),
                         parser={"object": "x", "version": 1},
                         parse_file_entries=lambda s: parser._parse_all(),
                         cross_file_stable_keys=True)
        rows = store.query_entries(sources=["codex"])
        print(f"STORE sync ok: {len(rows)} rows")
    except Exception as exc:
        print(f"STORE sync RAISED: {type(exc).__name__}: {str(exc)[:200]}")

    # Now the top-level compute path — does it hide the failure?
    from tokdash import compute
    try:
        result = compute.get_tools_data_for_range(None, None)
        print("compute.get_tools_data_for_range: OK,",
              "total_cost=", round(result.get("total_cost", 0), 4),
              "source_errors=", result.get("source_errors"))
    except Exception as exc:
        print(f"compute RAISED: {type(exc).__name__}: {str(exc)[:200]}")


if __name__ == "__main__":
    main()
