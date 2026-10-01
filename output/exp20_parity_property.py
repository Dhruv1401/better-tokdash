"""EXP-20: DB-on vs DB-off parity property (randomized Codex corpora).

Property (the architecture's own promise): with the persistent usage store
enabled, totals must equal the live-parse totals for the same corpus.

For each of 30 randomized corpora (seeded): build N Codex rollout files with
M token_count events each (random sizes, random model switches, duplicate
timestamps, resumé-copies of one file into archived_sessions/), then compare:
  live:  TOKDASH_USAGE_DB=0 -> tracker.collect -> entries
  store: TOKDASH_USAGE_DB=1 -> sync_files -> query_entries
compared as multisets of (entry_key, model, input, output, cacheRead,
cacheWrite, timestamp, cost) and as parse_entries_json aggregates.

Run from tokdash/: PYTHONPATH=src python ../output/exp20_parity_property.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

MODELS = ["gpt-5.3", "gpt-5.3-codex", "gpt-5-mini", "o4-mini"]


def iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_corpus(home: Path, rng: random.Random):
    """N files, M events each; one file is resume-copied into archived_sessions."""
    sessions_root = home / ".codex" / "sessions"
    arch_root = home / ".codex" / "archived_sessions"
    n_files = rng.randint(1, 4)
    meta = []
    t0 = 1_770_000_000_000
    for f in range(n_files):
        n_events = rng.randint(1, 12)
        session_id = f"sess-{f}"
        model = rng.choice(MODELS)
        lines = [
            json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta",
                        "payload": {"id": session_id}}),
            json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context",
                        "payload": {"model": model}}),
        ]
        for i in range(n_events):
            if rng.random() < 0.15:
                model = rng.choice(MODELS)
            inp = rng.randint(0, 5000)
            cached = rng.randint(0, inp)
            out = rng.randint(0, 900)
            reason = rng.randint(0, 300)
            ts = t0 + rng.randint(0, 86_400_000)  # duplicate timestamps possible
            info = {"id": f"u{f}-{i}",
                    "total_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                                          "output_tokens": out, "reasoning_output_tokens": reason},
                    "last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                                         "output_tokens": out, "reasoning_output_tokens": reason}}
            lines.append(json.dumps({"timestamp": iso(ts), "type": "event_msg",
                                     "payload": {"type": "token_count", "info": info}}))
        p = sessions_root / f"rollout-{f}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        meta.append((f, session_id))
    # resume-copy: duplicate one file's content into archived_sessions under a
    # different filename but same session id (keys must collapse in both paths)
    if n_files > 1 and rng.random() < 0.5:
        f, _ = rng.choice(meta)
        src = sessions_root / f"rollout-{f}.jsonl"
        dst = arch_root / f"rollout-{f}-copy.jsonl"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def run_mode(db_on: bool, seed: int):
    home = Path(tempfile.mkdtemp(prefix=f"par{'on' if db_on else 'off'}-{seed}-"))
    data = Path(tempfile.mkdtemp(prefix=f"pard{'on' if db_on else 'off'}-{seed}-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data)
    os.environ["TOKDASH_USAGE_DB"] = "1" if db_on else "0"
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)
    rng = random.Random(seed)
    build_corpus(home, rng)

    from tokdash.compute import CodingToolsUsageTracker, _sync_usage_store
    from tokdash.compute import parse_entries_json
    from tokdash.sources.coding_tools import BaseParser

    BaseParser._entry_cache.clear()
    tracker = CodingToolsUsageTracker()
    if db_on:
        try:
            store, stored_sources = _sync_usage_store(tracker)
            entries = store.query_entries(sources=stored_sources, since=None, until=None)
        except Exception as e:
            return None, ("store-sync-raise", f"{type(e).__name__}: {e}")
    else:
        tracker.collect(None, None)
        entries = tracker.entries
    agg = parse_entries_json({"entries": entries})
    return entries, agg


def fingerprint(entries):
    items = []
    for e in entries:
        items.append((e.get("entry_key") or e.get("entry_id") or "", e.get("model"),
                      int(e.get("input", 0) or 0), int(e.get("output", 0) or 0),
                      int(e.get("cacheRead", 0) or 0), int(e.get("cacheWrite", 0) or 0),
                      int(e.get("timestamp", 0) or 0)))
    return sorted(items)


print("=" * 78)
print("EXP-20: DB-on vs DB-off parity over 30 randomized corpora")
fails = 0
for seed in range(30):
    live_entries, live_agg = run_mode(False, seed)
    store_entries, store_agg = run_mode(True, seed)
    if store_entries is None:
        print(f"  seed {seed}: STORE PATH RAISED: {store_agg}")
        fails += 1
        continue
    lf = fingerprint(live_entries)
    sf = fingerprint(store_entries)
    same = lf == sf
    if not same:
        fails += 1
        only_live = [x for x in lf if x not in sf][:3]
        only_store = [x for x in sf if x not in lf][:3]
        print(f"  seed {seed}: PARITY BREAK — live {len(lf)} vs store {len(sf)} rows")
        print(f"    live-only: {only_live}")
        print(f"    store-only: {only_store}")
print(f"result: {30 - fails}/30 corpora in parity, {fails} breaks")

print("=" * 78)
print("Aggregate-level check (parse_entries_json outputs) on seed 0")
live_entries, live_agg = run_mode(False, 0)
store_entries, store_agg = run_mode(True, 0)


def agg_totals(a):
    out = {}
    for app, info in a.get("apps", {}).items():
        out[app] = (info.get("tokens"), info.get("tokens_in"), info.get("tokens_out"),
                    info.get("tokens_cache"), info.get("tokens_reasoning"),
                    round(info.get("cost", 0.0), 6), info.get("messages"))
    return out


la, sa = agg_totals(live_agg), agg_totals(store_agg)
print("  live :", la)
print("  store:", sa)
print("  match:", la == sa)
print("done.")
