"""EXP-24 (final, replaces exp23): store-poison API/CLI behavior with correct measurement.

Established facts (measured on Windows 11, Python 3.12, NVMe):
  1. `_sync_usage_database()` (the code behind `tokdash db sync`) raises
     OverflowError while the poison row exists.
  2. `/api/usage` keeps returning 200 with the LIVE totals (the huge row included);
     `source_errors` stays [] — the store failure is invisible at the API layer.
  3. LATENCY: with a 200k-event healthy file plus the poison file, every
     cache-bypassing (refresh=true) request pays a full live reparse:
       poisoned forced refresh: ~6.9 s then ~3.6 s per request
       healthy after removal:   ~3.4 s (one reparse), then ~4 ms warm
     i.e. the poisoned install pays parse-class latency on every forced refresh;
     a healthy install pays it once and then serves from the store.

Run from tokdash/: PYTHONPATH=src python ../output/exp24_api_poison_latency.py
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

home = Path(tempfile.mkdtemp(prefix="exp24-"))
data = Path(tempfile.mkdtemp(prefix="exp24d-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = str(home / "usage.db")
os.environ["TOKDASH_COMPUTE_CONCURRENCY"] = "1"
import pathlib

pathlib.Path.home = classmethod(lambda cls: home)

sessions_dir = home / ".codex" / "sessions"
sessions_dir.mkdir(parents=True)
t0 = 1_770_000_000_000
N = 200_000


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def mkfile(name, infos, sid):
    lines = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta", "payload": {"id": sid}}),
             json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context", "payload": {"model": "gpt-5.3"}})]
    for i, inp in infos:
        info = {"id": f"u{sid}-{i}",
                "total_token_usage": {"input_tokens": inp, "cached_input_tokens": 10,
                                      "output_tokens": 50, "reasoning_output_tokens": 3},
                "last_token_usage": {"input_tokens": inp, "cached_input_tokens": 10,
                                     "output_tokens": 50, "reasoning_output_tokens": 3}}
        lines.append(json.dumps({"timestamp": iso(t0 + i * 1000), "type": "event_msg",
                                 "payload": {"type": "token_count", "info": info}}))
    (sessions_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


print(f"building corpus: {N} healthy events + 1 poison row ...")
mkfile("rollout-healthy.jsonl", ((i, 100 + (i % 97)) for i in range(N)), "s1")
mkfile("rollout-poison.jsonl", ((1, 10**25),), "s2")

from fastapi.testclient import TestClient

from tokdash import api as api_mod
from tokdash.cli import _sync_usage_database

client = TestClient(api_mod.app)

print("== CLI: tokdash db sync (in-process _sync_usage_database) ==")
try:
    res = _sync_usage_database()
    print("  completed OK?! usage_entries:", res.get("usage_entries"))
except Exception as e:
    print(f"  RAISED: {type(e).__name__}: {e}")

print("== API: forced-refresh latency while poisoned ==")
for i in (1, 2):
    t = time.perf_counter()
    r = client.get("/api/usage", params={"date_from": "2026-01-01", "date_to": "2026-12-31", "refresh": "true"})
    print(f"  request {i}: {r.status_code} {(time.perf_counter()-t)*1000:.0f} ms "
          f"source_errors={r.json().get('source_errors')}")

print("== API: after the poison file is deleted ==")
(sessions_dir / "rollout-poison.jsonl").unlink()
with api_mod._cache_guard:
    api_mod._cache.clear()
t = time.perf_counter()
r = client.get("/api/usage", params={"date_from": "2026-01-01", "date_to": "2026-12-31", "refresh": "true"})
print(f"  first request (re-sync): {r.status_code} {(time.perf_counter()-t)*1000:.0f} ms")
t = time.perf_counter()
r = client.get("/api/usage", params={"date_from": "2026-01-01", "date_to": "2026-12-31"})
print(f"  warm request:            {r.status_code} {(time.perf_counter()-t)*1000:.0f} ms")
print("done.")
