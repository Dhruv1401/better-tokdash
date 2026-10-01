"""EXP-17: OpenClaw `until` boundary — Overview inclusive vs Sessions exclusive.

SUPPORTED_CLIENTS.md admits: "Overview counts the window's `until` instant
inclusive while Sessions excludes it, so rows stamped exactly at a window
boundary can count in Overview alone; with the persistent store synced the
two agree boundary and all."

Test: craft an OpenClaw session with an assistant row stamped EXACTLY at
`until`; call get_usage_for_range(since, until) and compare against the
store path with the same range.
Run from tokdash/: PYTHONPATH=src python ../output/exp17_openclaw_boundary.py
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

home = Path(tempfile.mkdtemp(prefix="exp17-"))
data = Path(tempfile.mkdtemp(prefix="exp17d-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = "0"
import pathlib
pathlib.Path.home = classmethod(lambda cls: home)

since = datetime(2026, 9, 1, tzinfo=timezone.utc)
until = datetime(2026, 9, 30, tzinfo=timezone.utc)  # boundary instant
boundary_iso = until.strftime("%Y-%m-%dT%H:%M:%S.000Z")

agents = home / ".openclaw" / "agents" / "main" / "sessions"
agents.mkdir(parents=True)
hdr = {"type": "session", "id": "sess-boundary", "cwd": "/p", "timestamp": "2026-09-01T00:00:00.000Z"}
row = {"type": "message", "id": "m1", "timestamp": boundary_iso,
       "message": {"role": "assistant", "provider": "openai", "model": "gpt-5.5",
                   "usage": {"input": 1000, "output": 500, "cacheRead": 0, "cacheWrite": 0}}}
(agents / "s1.jsonl").write_text(json.dumps(hdr) + "\n" + json.dumps(row) + "\n", encoding="utf-8")

from tokdash.pricing import PricingDatabase
from tokdash.sources.openclaw import get_session_usage, get_usage_for_range, _collect_normalized_entries
pdb = PricingDatabase()

res = get_usage_for_range(since, until)
print("Overview path (get_usage_for_range, until INCLUSIVE per code `msg_dt > until`):")
print("  total_tokens:", res.get("total_tokens"), "total_cost:", round(res.get("total_cost", 0), 4),
      "messages:", res.get("total_messages"))

# Sessions side: the sessions harness collects via a different filter (ts >= until excluded).
from tokdash import sessions
sess = sessions.get_sessions_data("openclaw", "today", "2026-09-01", "2026-09-30")
# window is local midnight to local midnight+1; craft comparison on the same UTC window via _raw? 
# Use the raw loader to show the exclusive semantics:
from tokdash.sources.openclaw import _collect_normalized_entries
entries = _collect_normalized_entries([str(agents)], pdb, since, until)
print("entries normalized with until:", len(entries), "in:", sum(e["input"] for e in entries))
# Direct demonstration of the operator: > vs >=
e_incl = _collect_normalized_entries([str(agents)], pdb, since, until)
e_excl = _collect_normalized_entries([str(agents)], pdb, since, None)
print("with until filter (inclusive >):", len(e_incl), "| no until:", len(e_excl))
