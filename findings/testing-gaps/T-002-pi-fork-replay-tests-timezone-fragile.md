# T-002 (testing gap / pre-existing CI failure): `test_pi_fork_replay::test_parent_fork_and_views` is timezone-dependent and fails for any UTC+ offset > +2:27

## Classification
Testing gap (broken CI on main); **not** a product accounting bug.

## Summary
Two tests fail on `main` (v2.6.8, 0a179d0) — confirmed by my baseline run
(3054 passed / 4 failed) and by the maintainer's own note in PR #137
("4 pre-existing main failures ... Pi fork replay ×2"). The failures are the
fixture's own clock assumption:

```python
def turn(mid, tokens, day=14):
    "timestamp": f"2026-09-{day:02}T21:33:00.000Z"   # day=17 for the child's own turn
...
data = sessions.get_sessions_data("pi_agent", "today", "2026-09-17", "2026-09-17")
assert [(r["session_id"], ...)] == [("child", 550)]
```

`21:33Z` on the 17th is already the 18th in any zone east of UTC+02:27.
`get_sessions_data` filters by local-day bounds (`_window_bounds` → local
`parse_date_range` semantics), so on UTC+3 or later machines — and on this
audit machine (India Standard Time, where the turn lands on 2026-09-18
03:03 local) — the assertion sees an empty list. The product behavior
(day-windowing in local time) is deliberate; the test hardcodes UTC.

## Evidence
- Baseline: `4 failed, 3054 passed` on Windows/IST; the same 4 failures
  acknowledged in PR #137 (opened 2026-09-29).
- Repro: `output/exp05_pi_date_filter.py` — same fixture, same day filter;
  `_load_pi_sessions` returns both sessions (accounting correct), the
  2026-09-17 window returns [] and the 2026 all-year window returns both.
- Turn 1789680780000 ms = 2026-09-18T03:03 local (IST).

## Why it matters
- main's CI is red for anyone not in UTC±2, which (a) normalizes "red is
  fine" and desensitizes maintainers to real regressions, and (b) blocks
  bisecting real bugs on those platforms.
- It silently disables the only end-to-end coverage of PR #126's fork-replay
  accounting on entire classes of contributor machines (all of Asia, much of
  Europe/Africa in summer) — the exact code most at risk of silent
  double-counting.

## Suggested direction
Build the fixture timestamps from a fixed local date instead of a fixed UTC
instant (e.g. compute `21:33` local, or use noon UTC which is the same local
date for UTC±10), or pin the process timezone in the fixture
(`TZ=UTC` / `time.tzset()` on POSIX; on Windows use ``zoneinfo``-aware
window injection). The same hardening applies to any test that asserts a
local-day boundary from a UTC-stamped fixture.

## Related pre-existing failure (not audited further)
`test_companion_packaging` ×2 fails because `python -m build` errors out in
the sandboxed environment (subprocess exit 1) — environment-dependent, left
as-is.
