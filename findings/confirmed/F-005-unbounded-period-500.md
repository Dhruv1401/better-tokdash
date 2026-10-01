# F-005 (confirmed): Unbounded numeric `period` values overflow date arithmetic — four API endpoints return 500 with raw exception text, including `OverflowError: Python int too large to convert to C int` for a ~400-digit value

## Summary
`compute.period_to_days()` accepts any integer (`max(1, int(period))` — the
deliberate D1 fix made unknown *tokens* fall back to all-time, but numeric
tokens of any magnitude pass through unchanged). `period_to_range_args()`
then does `end_date - timedelta(days=days - 1)`, which raises
`OverflowError: date value out of range` for values beyond ~3652059
(datetime.min year), and `ValueError`/`OverflowError` variants for even
larger values. Nothing between the query-string parser and that subtraction
bounds the number, so:

```
GET /api/usage?period=9999999        -> 500 {'detail': 'date value out of range'}
GET /api/tools?period=99999999       -> 500 {'detail': 'date value out of range'}
GET /api/insights?period=99999999    -> 500 {'detail': 'date value out of range'}
GET /api/sessions?tool=codex&period=99999999 -> 500 {'detail': 'date value out of range'}
GET /api/usage?period=<400 nines>    -> 500 {'detail': 'Python int too large to convert to C int'}
```

While `/api/stats?period=99999999` returns 200 (it doesn't build the range
the same way) — the same user-visible input silently means different
things per endpoint.

## Reproduction
`output/exp12_live_server.py` + the follow-up probe (from repo root:
`PYTHONPATH=src python - <<EOF ... TestClient(app)`):

```
200 /api/usage?period=36500            (documented all-time)
500 /api/usage?period=9999999          (one more 9 -> 500)
500 /api/usage?period=999999999999999999999999999999999999999999 -> OverflowError leaked
```

Minimal layer repro:
```python
from tokdash.compute import period_to_range_args
period_to_range_args("9999999")
# OverflowError: date value out of range (compute.py:711)
```

## Expected behavior
An out-of-range numeric period should clamp (the codebase already treats
"unrecognized → all time, visibly" as the correct failure mode —
`resolve_period` marks `recognized: False`) or be rejected with a 400.
Uniformly across endpoints.

## Actual behavior
500 with the exception's own text as the error detail. The 400-digit case
leaks `Python int too large to convert to C int` — an internal
implementation artifact — as the API error. This is also the only path
where the audit found raw exception text surfaced in a 500 `detail`
(`/api/session`'s broad `except Exception as e: HTTPException(500,
detail=str(e))` similarly echoes internal messages, e.g. filesystem paths,
to any caller — relevant on `--bind 0.0.0.0`).

## Why it matters
- Trivially reachable from the query string with no auth (read endpoints).
- Non-uniform behavior across endpoints (usage/tools/insights/sessions
  500; stats 200) means a wrapper or the frontend cannot treat "bad
  period" consistently; the multi-server merge feature sends the same
  period string to several Tokdash instances and mixes 200s with 500s.
- Detail leakage violates the project's own fail-closed style elsewhere
  (`_origin_value` returns "" specifically so the guard "never 500s").

## Suggested direction
Clamp `period_to_days` to a sane ceiling (e.g. `ALL_TIME_DAYS`) and/or wrap
`period_to_range_args` in try/except (OverflowError, ValueError,
OSError) → treat as the unrecognized-period fallback; add 400-level
validation instead of 500+str(e) in the four routes; audit the other
`detail=str(e)` sites.

## Subsystem
`src/tokdash/compute.py` (`period_to_days` / `period_to_range_args`),
`src/tokdash/api.py` (`/api/usage`, `/api/tools`, `/api/insights`,
`/api/sessions`), `src/tokdash/sessions.py` `_window_bounds`.
