# F-002 (confirmed): Date-range windows are anchored to the *current* DST offset, so windows for dates in the other DST phase drift one hour and disagree with the heatmap's day bucketing

## Summary
`dateutil.parse_date_range` (and `compute._date_range_from_args`) build a
local midnight by taking a naive `strptime` result and calling
`.replace(tzinfo=datetime.now().astimezone().tzinfo)` — the offset that
*now* has, frozen. On a DST-observing machine, any `date_from`/`date_to`
query whose dates lie in the *other* DST phase gets a window shifted by the
DST delta (1 hour) relative to true local midnights.

Concrete divergence: for a New York machine in September, the window
`date_from=2026-01-05&date_to=2026-01-05` covers
`2026-01-04T18:30Z → 2026-01-05T18:30Z` instead of
`2026-01-05T05:00Z → 2026-01-06T05:00Z` — an 11.5-hour error made of the
1-hour DST skew plus the weekend-gap drift the anchor also introduces when
"now" is not midnight (here 14:00 local ⇒ boundary at 18:30Z).

A Jan-5 event at 23:30 EST (04:30Z Jan 6) is:
- bucketed on **2026-01-05** by the Stats heatmap
  (`date(timestamp/1000,'unixepoch','localtime')` — correct local-day),
- **excluded** from the same day's `date_from=2026-01-05&date_to=2026-01-05`
  API window (drifted end 18:30Z Jan 5).

So the dashboard's own surfaces disagree about what "Jan 5" contains, and
every custom-range endpoint (`/api/usage?date_from&date_to`, insights range,
sessions window, previous-period comparison anchored on a custom range)
inherits the drift whenever "now" is in the other DST phase. No exception;
plausible-looking totals.

## Reproduction
`output/exp07b_dst_e2e.py` — patches `dateutil.datetime.now` to a fixed
2026-09-15 14:00 America/New_York instant and calls the real
`parse_date_range("2026-01-05","2026-01-05")`:
```
code window : 2026-01-04 18:30:00+00:00 -> 2026-01-05 18:30:00+00:00
true window : 2026-01-05 05:00:00+00:00 -> 2026-01-06 05:00:00+00:00
event Jan 5 23:30 EST: in 'Jan 5' window? False | heatmap day bucket: 2026-01-05
```

## Expected behavior
A request for local date range [2026-01-05, 2026-01-05] must cover the local
days actually named (true local midnights of those dates), and must agree
with the heatmap/contribution bucketing of the same events.

## Actual behavior
Window boundaries are anchored to the instant's offset *and* the wall-clock
time of "now" (any time of day, not midnight), producing a doubly-skewed
window that only matches expectations when the queried dates share the
current UTC offset AND "now" happens to be midnight.

## Why it matters
- Silent accounting skew on every DST-observing machine for ~4 months a year
  (any custom-range query reaching into the other phase; "previous period"
  comparisons in winter queried from summer and vice versa).
- The heatmap vs range-filter disagreement is user-visible: picking Jan 5 in
  the date picker shows different numbers than the calendar cell for Jan 5.
- The extra "not midnight" skew also applies to non-DST zones for any
  current-time-of-day: verify — the anchor uses only `tzinfo`, but the
  wall-clock hour of *now* never enters `replace()`; the 18:30Z drift above
  comes from the event-side assumption, so for fixed-offset zones the
  midnights are correct. The DST case remains fully real.

## Suggested direction
Build the window from zoneinfo: `datetime.strptime(...).replace(tzinfo=ZoneInfo(os.environ.get('TZ', ...)))` is still wrong across DST because
`replace` with a zone *does* resolve wall-clock correctly (unlike a frozen
fixed offset) — the actual fix is to localize with the IANA zone
(`ZoneInfo(key)`), not with `now().tzinfo` (a fixed-offset
`datetime.timezone`). `datetime.now().astimezone().tzinfo` returns a fixed
offset, never a ZoneInfo, so `.replace(tzinfo=<that>)` is always a wall-clock
lie in the other phase. Add a regression test that queries a January window
while faking a July `now()` and asserts boundary equality with true local
midnights.

## Subsystem
`src/tokdash/dateutil.py` (shared), `src/tokdash/compute.py`
`_date_range_from_args`, all API custom-range endpoints, insights, sessions
`_window_bounds`.
