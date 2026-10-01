# [consistency] OpenClaw: a row stamped exactly at a range boundary counts in Overview but not in Sessions — with the same window bounds

## Summary

Small, documented, and cheap to close: in live-fallback mode (no persistent store), the OpenClaw Overview range filter keeps a row stamped exactly at the window's `until` bound, while the Sessions date-window filter drops it. A message stamped exactly at `until` therefore counts in Overview totals but is missing from the Sessions panel for the identical window.

Verified with *identical* bounds on both surfaces (this matters: the Sessions date-window derives its bounds from the same `parse_date_range` call, so the comparison must use those bounds, not two different windows). With an OpenClaw session whose only billable row is stamped exactly at `until` of the `2026-09-29..2026-09-29` window:

- Overview (`get_usage_for_range(since, until)`): `total_tokens 1500`, `total_messages 1` — boundary row **included** (`msg_dt > until` keeps it; strict `>` excludes only rows *after* the bound) in [`src/tokdash/sources/openclaw.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/openclaw.py).
- Sessions (`get_sessions_data("openclaw", "today", "2026-09-29", "2026-09-29")`): `[]` — `_summarize_session` drops turns with `ts_ms >= until_ms` in [`src/tokdash/sessions.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sessions.py).

[`docs/reference/SUPPORTED_CLIENTS.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/reference/SUPPORTED_CLIENTS.md) documents exactly this ("Overview counts the window's `until` instant inclusive while Sessions excludes it, so rows stamped exactly at a window boundary can count in Overview alone; with the persistent store synced the two agree boundary and all"), so this is a known, accepted quirk — filed because it is a reproducible Overview↔Sessions disagreement with a one-comparison-operator fix shape, the same consistency class the project has fixed elsewhere (Qoder CLI's fold was rewritten so the two surfaces "cannot drift").

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12, IST system timezone:

```python
import json, os, tempfile
from pathlib import Path

home = Path(tempfile.mkdtemp()); os.environ["TOKDASH_DATA_DIR"] = str(Path(tempfile.mkdtemp()))
os.environ["TOKDASH_USAGE_DB"] = "0"   # live-fallback mode, where the quirk lives
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)

from tokdash.dateutil import parse_date_range
since, until = parse_date_range("2026-09-29", "2026-09-29")

agents = home / ".openclaw" / "agents" / "main" / "sessions"
agents.mkdir(parents=True)
hdr = {"type": "session", "id": "sess-boundary", "cwd": "/p",
       "timestamp": "2026-09-01T00:00:00.000Z"}
stamp = until.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + until.strftime("%z")[:3] + ":" + until.strftime("%z")[3:]
row = {"type": "message", "id": "m1", "timestamp": stamp,
       "message": {"role": "assistant", "provider": "openai", "model": "gpt-5.5",
                   "usage": {"input": 1000, "output": 500, "cacheRead": 0, "cacheWrite": 0}}}
(agents / "s1.jsonl").write_text(json.dumps(hdr) + "\n" + json.dumps(row) + "\n", encoding="utf-8")

from tokdash.sources.openclaw import get_usage_for_range
res = get_usage_for_range(since, until)
print("Overview:", res["total_tokens"], res["total_messages"])   # 1500 1

from tokdash import sessions
sd = sessions.get_sessions_data("openclaw", "today", "2026-09-29", "2026-09-29")
print("Sessions:", [(s["session_id"], s["tokens"]) for s in sd["sessions"]])  # []
```

Observed (verified verbatim, same window bounds both sides): `Overview: 1500 1`, `Sessions: []`. Harness: [`output/exp17_openclaw_boundary.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp17_openclaw_boundary.py).

## Expected behavior

At minimum, consistency between the two surfaces for the same window: either both treat the interval as half-open `[since, until)` (Sessions' semantics, and what the store path applies — with the DB synced the two surfaces already agree), or both inclusive. The project's own documented ideal for other sources is that Overview and Sessions share one corpus and one winner set, so they "can never disagree".

## Actual behavior

- Overview keeps rows with `timestamp == until` (the filter is `msg_dt > until_date`, strict greater-than, in [`src/tokdash/sources/openclaw.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/openclaw.py)).
- Sessions drops turns with `timestamp_ms >= until_ms` in [`src/tokdash/sessions.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sessions.py).
- The quirk is confined to live-fallback mode; with the persistent store synced, both paths read the store and agree.

## Impact

Demonstrated: a session contributing to Overview totals that Sessions does not list for the same window — the boundary case (a row stamped exactly at local midnight) is most likely exactly when daily-summary-style rows land. Cosmetic-to-confusing rather than an accounting error: totals across both surfaces are each internally consistent; only the boundary row's membership differs, only in live-fallback mode. Documented as intended behavior, hence "consistency nit", not bug.

## Root cause

Established: two different boundary predicates (`>` vs `>=`) applied to the same window on the two surfaces.

## Evidence

- Inline reproducer above (verified verbatim, same bounds both sides).
- [`src/tokdash/sources/openclaw.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/openclaw.py) (Overview filter), [`src/tokdash/sessions.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sessions.py) `_summarize_session` (Sessions filter).
- Documented status: [`docs/reference/SUPPORTED_CLIENTS.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/reference/SUPPORTED_CLIENTS.md), OpenClaw paragraph, final sentence.

## Suggested direction

Make the live Overview filter use the same half-open comparison as Sessions (drop `>= until`), or route both live surfaces through one shared range predicate; then pin it with the boundary-stamped fixture above (it is already a minimal test).
