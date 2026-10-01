"""EXP-23: API-path check for the store-poison finding (I-003).

Verifies, through the real FastAPI app:
  1. /api/usage returns 200 (not 500) while the store is poisoned.
  2. Every request reparses live (timed) — the index is bypassed.
  3. source_errors stays empty — the degradation is invisible.
  4. `tokdash db sync` (the CLI's _sync_usage_database) raises OverflowError.

Run from tokdash/: PYTHONPATH=src python ../output/exp23_api_poison.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

home = Path(tempfile.mkdtemp(prefix="exp23-"))
data = Path(tempfile.mkdtemp(prefix="exp23d-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = str(home / "usage.db")
os.environ["TOKDASH_COMPUTE_CONCURRENCY"] = "1"
import pathlib

pathlib.Path.home = classmethod(lambda cls: home)

sessions_dir = home / ".codex" / "sessions"
sessions_dir.mkdir(parents=True)
t0 = 1_770_000_000_000


def iso(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# A healthy file with many events (so a live reparse is measurable), plus one poisoned file.
lines = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta", "payload": {"id": "s1"}}),
         json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context", "payload": {"model": "gpt-5.3"}})]
for i in range(3000):
    info = {"id": f"u{i}",
            "total_token_usage": {"input_tokens": 100 + (i % 97), "cached_input_tokens": 10,
                                  "output_tokens": 50, "reasoning_output_tokens": 3},
            "last_token_usage": {"input_tokens": 100 + (i % 97), "cached_input_tokens": 10,
                                 "output_tokens": 50, "reasoning_output_tokens": 3}}
    lines.append(json.dumps({"timestamp": iso(t0 + i * 1000), "type": "event_msg",
                             "payload": {"type": "token_count", "info": info}}))
(sessions_dir / "rollout-healthy.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

poison = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta", "payload": {"id": "s2"}}),
          json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context", "payload": {"model": "gpt-5.3"}}),
          json.dumps({"timestamp": iso(t0 + 1), "type": "event_msg", "payload": {"type": "token_count",
                     "info": {"id": "ubig",
                              "total_token_usage": {"input_tokens": 10**25, "cached_input_tokens": 0,
                                                    "output_tokens": 5, "reasoning_output_tokens": 0},
                              "last_token_usage": {"input_tokens": 10**25, "cached_input_tokens": 0,
                                                   "output_tokens": 5, "reasoning_output_tokens": 0}}}})]
(sessions_dir / "rollout-poison.jsonl").write_text("\n".join(poison) + "\n", encoding="utf-8")

from fastapi.testclient import TestClient

from tokdash import api as api_mod
from tokdash.cli import _sync_usage_database

client = TestClient(api_mod.app)

print("== CLI path ==")
try:
    res = _sync_usage_database()
    print("db sync completed OK?! usage_entries:", res.get("usage_entries"))
except Exception as e:
    print(f"db sync RAISED: {type(e).__name__}: {e}")

print("== API path ==")
for i in (1, 2, 3):
    t = time.perf_counter()
    r = client.get("/api/usage", params={"period": "month"})
    ms = (time.perf_counter() - t) * 1000
    body = r.json()
    print(f"request {i}: {r.status_code} in {ms:.0f} ms | entries={len(body.get('entries', []))} "
          f"source_errors={body.get('source_errors')}")

print("done.")
