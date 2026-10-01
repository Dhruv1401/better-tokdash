"""EXP-16: session active-time edge cases.

sessions.py documents active_ms = capped inter-event gaps. Probe:
- two turns 1 hour apart (gap > 300s cap): span=3600s, active=?
- identical timestamps (parallel events)
- timestamp=0 / negative
- a single-event session (active=0)
- boundary: gap exactly 300s
- out-of-order timestamps (file with descending ts)
Run from tokdash/: PYTHONPATH=src python ../output/exp16_activetime.py
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


def codex_rollout(events):
    """events: list of (offset_ms, input). Returns file content."""
    t0 = 1_770_000_000_000
    lines = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta", "payload": {"id": "s"}}),
             json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context", "payload": {"model": "gpt-5.3"}})]
    for off, inp in events:
        info = {"id": f"u{off}", "total_token_usage": {"input_tokens": inp, "cached_input_tokens": 0,
                                                       "output_tokens": 1, "reasoning_output_tokens": 0},
                "last_token_usage": {"input_tokens": inp, "cached_input_tokens": 0,
                                     "output_tokens": 1, "reasoning_output_tokens": 0}}
        lines.append(json.dumps({"timestamp": iso(t0 + off), "type": "event_msg",
                                 "payload": {"type": "token_count", "info": info}}))
    return "\n".join(lines) + "\n"


def main():
    home = Path(tempfile.mkdtemp(prefix="exp16-"))
    data = Path(tempfile.mkdtemp(prefix="exp16d-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data)
    os.environ["TOKDASH_USAGE_DB"] = "0"
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)
    d = home / ".codex" / "sessions"
    d.mkdir(parents=True)
    (d / "rollout-1h.jsonl").write_text(codex_rollout([(0, 100), (3_600_000, 100)]), encoding="utf-8")
    (d / "rollout-parallel.jsonl").write_text(codex_rollout([(0, 100), (0, 200), (0, 300)]), encoding="utf-8")
    (d / "rollout-gap300.jsonl").write_text(codex_rollout([(0, 100), (300_000, 100), (600_000, 100)]), encoding="utf-8")
    (d / "rollout-gap301.jsonl").write_text(codex_rollout([(0, 100), (301_000, 100), (602_000, 100)]), encoding="utf-8")

    from tokdash import sessions
    res = sessions.get_sessions_data("codex", "year")
    for s in res.get("sessions", []):
        print(f"{s['session_id'][:20]:22s} span_ms={s.get('span_ms'):>9} active_ms={s.get('active_ms'):>9} "
              f"agent_ms={s.get('active_ms_sum', s.get('agent_ms', '?'))} events={s.get('events', s.get('turns', '?'))}")


if __name__ == "__main__":
    main()
