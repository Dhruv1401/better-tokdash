"""EXP-05: why does sessions.get_sessions_data drop sessions whose turns are
stamped 2026-09-17?  Date-window vs started/last-seen bounds, Windows clock,
timezone bucketing.  Run from repo root: PYTHONPATH=src python ../output/exp05_pi_date_filter.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

import tempfile
import os
from datetime import datetime

tmp = Path(tempfile.mkdtemp(prefix="exp05-"))
os.environ["PI_AGENT_DIR"] = str(tmp / "pi")
os.environ["TOKDASH_DATA_DIR"] = str(tmp / "data")
os.environ["TOKDASH_USAGE_DB"] = "0"
import pathlib
pathlib.Path.home = classmethod(lambda cls: tmp)

from tokdash import sessions
from tokdash.pricing import PricingDatabase
from tokdash.sources.coding_tools import PiAgentParser, _sig_cache
from tokdash.usage_store import UsageEntryStore

print("today is:", datetime.now().astimezone().date().isoformat(),
      "| now:", datetime.now().isoformat())


def turn(mid, tokens, day=14):
    return {
        "type": "message", "id": mid, "parentId": "previous-" + mid,
        "timestamp": f"2026-09-{day:02}T21:33:00.000Z",
        "message": {"role": "assistant", "model": "test-model", "provider": "test",
                    "usage": {"input": tokens, "output": tokens // 10,
                              "cacheRead": 0, "cacheWrite": 0,
                              "cost": {"total": tokens / 1000}}},
    }


root = tmp / "pi"
root.mkdir(parents=True)
parent = root / "2026-09-14_parent.jsonl"
parent.write_text(json.dumps({"type": "session", "version": 3, "id": "parent", "cwd": "/p"}) + "\n"
                  + json.dumps(turn("34f479e3", 1000)) + "\n", encoding="utf-8")
child = root / "forks" / "2026-09-14_child.jsonl"
child.parent.mkdir()
child.write_text(json.dumps({"type": "session", "version": 3, "id": "child",
                             "cwd": "/p", "parentSession": str(parent)}) + "\n"
                 + json.dumps(turn("34f479e3", 1000)) + "\n"
                 + json.dumps(turn("bbb00001", 500, 17)) + "\n", encoding="utf-8")

sigs = tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*.jsonl")))

_sig_cache.clear()
raw = sessions._load_pi_sessions(sigs)
print("_load_pi_sessions ->", {sid: len(s["turns"]) for sid, s in raw.items()})
for sid, s in raw.items():
    print("  ", sid, "started=", s.get("started_at_ms"), "last_seen=", s.get("last_seen_at_ms"),
          "turn ts:", [t.get("timestamp_ms") for t in s.get("turns", [])])

data = sessions.get_sessions_data("pi_agent", "today", "2026-09-17", "2026-09-17")
print("sessions for 2026-09-17:", [(r["session_id"], r["tokens"]) for r in data["sessions"]])
data_all = sessions.get_sessions_data("pi_agent", "today", "2026-01-01", "2026-12-31")
print("sessions for all-2026:  ", [(r["session_id"], r["tokens"]) for r in data_all["sessions"]])
