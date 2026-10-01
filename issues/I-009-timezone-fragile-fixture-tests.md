# [tests] Pi fork-replay tests are timezone-fragile — they fail on machines east of UTC+2:27, disabling the main regression guard for the #124/#126 fork-replay fix

## Summary

`tests/test_pi_fork_replay.py::test_parent_fork_and_views` (both parametrizations) stamps the fork's own turn at a fixed instant (`2026-09-17T21:33:00.000Z`) and asserts it appears in the local-day window `2026-09-17..2026-09-17`. Local-day windows are derived from the machine's timezone, so on any machine east of UTC+2:27 that instant is already Sep 18 local, the filtered view is empty, and the assertion fails. These are the two pre-existing failures on `main` acknowledged in PR #137.

The cost is specific: per its own module docstring, this test is the end-to-end regression guard for the Pi fork-replay replay-dedup fix ([issue #124](https://github.com/JingbiaoMei/Tokdash/issues/124)) — the code whose regression would silently double-count usage. That guard currently works only on machines west of UTC+2:27 and is red for all of Asia and much of Europe/Africa.

## Reproduction

Verified on Windows 11, Python 3.12, system timezone IST (UTC+5:30), commit `0a179d0`:

```bash
python -m pytest tests/test_pi_fork_replay.py -q
# 2 failed, 15 passed
# AssertionError: assert [] == [('child', 550)]
#   at the get_sessions_data("pi_agent", "today", "2026-09-17", "2026-09-17") assertion
```

Root-cause check (same machine, minimal fixture reproducing the mechanism): the turn's stamp `2026-09-17T21:33Z` converts to local date **2026-09-18** on this machine; the `2026-09-17..2026-09-17` filtered view returns `[]` while an unfiltered/year view returns the session with correct tokens (550). The accounting is correct — only the fixture's local-date assumption is wrong.

Boundary derivation: the test passes where `2026-09-17T21:33Z` is still Sep 17 local, i.e. for UTC offsets ≤ +2:27, and fails east of that. I demonstrated the failure at UTC+5:30 only; the boundary itself is arithmetic from the fixed stamp, not a sweep of timezones. (Note for Windows users: setting the `TZ` environment variable does not change Python's local timezone there, so this must be verified with the actual system timezone.)

## Expected behavior

A timezone-pinned test: fixture stamps that map to the same local date across the UTC−12…UTC+14 range (noon UTC serves), or expected dates derived from the fixture's own stamps rather than hardcoded. Timezone sensitivity should be explicit, not accidental — the project already ships `freezegun` for exactly this kind of control.

## Actual behavior

- The two parametrized cases fail deterministically east of UTC+2:27 and pass west of it.
- The failures are stable enough that PR #137 acknowledges them as pre-existing rather than fixing them; two permanently-red tests on main also erode the signal value of every other red suite.
- The dead assertions guard fork-replay dedup end-to-end (collect → store → sessions view), which is the pipeline [#126](https://github.com/JingbiaoMei/Tokdash/issues/126) was filed against.

## Impact

Demonstrated: the test failure at UTC+5:30 with the correct accounting elsewhere (minimal fixture above). Plausible consequence, not demonstrated: a future fork-replay regression would pass CI and local runs for maintainers west of UTC+2:27 while only the (already red) tests would have caught it.

## Root cause

Established: the fixture's fixed UTC stamp interacting with machine-local day windows. Not a product accounting bug.

## Evidence

- Baseline on IST: `4 failed, 3054 passed, 9 skipped` overall; the other two failures are companion-packaging environment tests, unrelated.
- Minimal mechanism fixture above (filtered view `[]`, year view correct).
- Module docstring and window assertion: [`tests/test_pi_fork_replay.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/tests/test_pi_fork_replay.py) (stamps at line ~28/`turn()`; window at line ~101).
- [PR #137](https://github.com/JingbiaoMei/Tokdash/pull/137) acknowledges the failures as pre-existing on main: "full suite 2990 passed with only the 4 pre-existing main failures: companion packaging ×2, Pi fork replay ×2".

## Suggested direction

Stamp fixture turns at noon UTC (same local date everywhere on Earth) or derive both the fixture stamps and the asserted window from one clock, so they cannot drift apart across timezones. Worth bundling with a conftest helper that runs date-sensitive tests under two fixed zones (e.g. `America/New_York` and `Asia/Kolkata`) via `freezegun` + `ZoneInfo`.
