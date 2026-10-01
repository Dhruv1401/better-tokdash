# [correctness] Custom date-range windows anchor to the machine's *current* DST offset, so target dates in the other DST phase get the wrong UTC window

## Summary

`parse_date_range` in [`tokdash/src/tokdash/dateutil.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/dateutil.py) builds the local-midnight bounds for a custom date range with:

```python
local_tz = datetime.now().astimezone().tzinfo
```

Python's `datetime.now().astimezone()` returns a datetime carrying a **fixed-offset `timezone`** derived from the C runtime's *current* local time — not a named zone that can resolve other dates (this is CPython behavior on Windows and Linux, verified here on Windows 11 / Python 3.12). Applying that fixed offset to *other* dates with `.replace(tzinfo=local_tz)` is only correct while the target date is in the same DST phase as today. On any DST-observing install, a custom range for a date in the other phase produces a UTC window shifted by the phase difference (one hour in most zones; more where the base offset has a sub-hour component).

The heatmap's day bucketing in [`tokdash/src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py) uses SQLite's `'localtime'` conversion — true per-date local time — so on the same dashboard the heatmap cell for a day and the Overview/report numbers for that day can be computed over different UTC windows. The shift keeps all numbers *plausible* (boundary-hour deltas only), so nothing looks broken.

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12 (needs the `tzdata` package for the `ZoneInfo` simulation on Windows). The reporter's own machine (UTC+5:30, no DST) cannot exhibit the bug live, so the simulation patches `tokdash.dateutil.datetime` with a clock that mimics a New York machine *exactly the way Python implements it*: `now()` returns a naive instance and `astimezone()` resolves through the C runtime to the **fixed current offset** (EDT, −4, in September):

```python
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
import tokdash.dateutil as m
from tokdash.dateutil import parse_date_range

NY = ZoneInfo("America/New_York")
EDT = timezone(timedelta(hours=-4))   # fixed offset the C runtime reports in September

class NYClock(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return datetime.now(tz)
        return cls(2026, 9, 15, 12, 0)
    def astimezone(self, tz=None):
        if tz is None:
            return datetime(2026, 9, 15, 12, 0, tzinfo=EDT)   # what Python's real astimezone() does
        return super().astimezone(tz)

def window(d):
    with patch.object(m, "datetime", NYClock):
        return parse_date_range(d, d)

s, u = window("2026-01-05")
print("Jan  5 window:", s.astimezone(timezone.utc), "->", u.astimezone(timezone.utc), "| offset:", s.utcoffset())
s2, u2 = window("2026-09-15")
print("Sep 15 window:", s2.astimezone(timezone.utc), "->", u2.astimezone(timezone.utc), "| offset:", s2.utcoffset())

lo = datetime(2026, 1, 5, tzinfo=NY).astimezone(timezone.utc)   # true local-day bounds
hi = datetime(2026, 1, 6, tzinfo=NY).astimezone(timezone.utc)
ev = datetime(2026, 1, 5, 23, 30, tzinfo=NY).astimezone(timezone.utc)   # 11:30 PM Jan 5 local (EST)
print("true Jan 5 local-day window:", lo, "->", hi)
print("event 2026-01-05T23:30-05:00 =", ev)
print("captured by returned window?", s <= ev < u, "| captured by true window?", lo <= ev < hi)
```

Observed output (verified verbatim against this checkout):

```
Jan  5 window: 2026-01-05 04:00:00+00:00 -> 2026-01-06 04:00:00+00:00 | offset: -1 day, 20:00:00
Sep 15 window: 2026-09-15 04:00:00+00:00 -> 2026-09-16 04:00:00+00:00 | offset: -1 day, 20:00:00
true Jan 5 local-day window: 2026-01-05 05:00:00+00:00 -> 2026-01-06 05:00:00+00:00
event 2026-01-05T23:30-05:00 = 2026-01-06 04:30:00+00:00
captured by returned window? False | captured by true window? True
```

Two things to note in the output: the January window is anchored at **04:00Z (EDT, −4)** instead of **05:00Z (EST, −5)**, and the *control* (a September date, same phase as the anchor) is exactly correct — so the failure is specific to cross-phase dates, which is why ordinary testing misses it.

## Expected behavior

Established by the codebase's own semantics: the heatmap already treats "Jan 5" as true local time (`strftime('%Y-%m-%d', timestamp, 'localtime')` in [`tokdash/src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py)), and `sessions._window_bounds` in [`tokdash/src/tokdash/sessions.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sessions.py) shares this same helper — so every consumer implicitly claims local-day semantics. The invariant a date range should satisfy: it covers exactly the target local days *as they existed on those dates* (per-date DST resolution), not days re-anchored to today's offset.

## Actual behavior

- For a target date in the other DST phase, both window bounds are shifted by the phase difference (one hour here); demonstrated above through the real helper.
- Events in the last hour of the target local day fall outside the returned window (the 11:30 PM example), and symmetrically early-morning events of the *following* local day can be pulled in.
- Both the API custom-range endpoints and the CLI `--since/--until` reports inherit this via the shared helper; the heatmap does not, so the two surfaces can disagree about the same day.
- Fixed-offset zones (e.g. UTC+5:30 year-round) are unaffected — the anchor is coincidentally correct, which is why the behavior hides in most testing.

## Impact

Demonstrated: the window arithmetic, via the real helper under a faithful simulation of a DST-observing machine (including the same-phase control). Not demonstrated end-to-end: a misattributed event/cost in a live dashboard query — the reporter's machine cannot exhibit DST, and no live corpus spanning a DST boundary was available. Affected population: installs in DST-observing zones querying dates in the opposite phase (for a northern-hemisphere install, plausibly several months of dates per year). Consequences are boundary-hour attribution errors that do not look wrong to a user.

## Root cause

Established by source inspection plus the simulation: the anchor `datetime.now().astimezone().tzinfo` is a fixed-offset `timezone` captured from *current* local time ([`tokdash/src/tokdash/dateutil.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/dateutil.py)), and `.replace(tzinfo=...)` applies it verbatim to other dates. Python cannot recover the correct historical offset from a fixed offset — the zone identity is lost at capture time.

## Evidence

- Inline reproducer above (verified verbatim on this checkout; the control run distinguishes the phase bug from any generic offset error).
- Helper: `parse_date_range` in [`tokdash/src/tokdash/dateutil.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/dateutil.py).
- Internal-inconsistency partner: the heatmap's `'localtime'` bucketing in [`tokdash/src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py).
- Shared consumers: `get_tools_data_for_range_str` in [`tokdash/src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py); `sessions._window_bounds` in [`tokdash/src/tokdash/sessions.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sessions.py).

## Suggested direction

The invariant: resolve each boundary against the machine's IANA zone per date (`ZoneInfo`, letting per-date DST resolution apply) rather than reusing the current offset as a fixed `tzinfo`. A regression test needs no real DST machine: the same clock-patching shown above pins the property on any CI runner. Related prior art in-repo: the changelog shows the project already treats cross-surface window mismatches as bugs worth regression tests (e.g. the Sessions/Overview consistency work in [#126](https://github.com/JingbiaoMei/Tokdash/pull/126)).

---

*Full experiment scripts and run logs are not in this repository; contact me (via the audit repo this file is hosted in) if you want them.*
