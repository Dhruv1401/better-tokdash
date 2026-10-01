# F-001 (confirmed): A single >2^63 token count poisons the persistent usage store — every subsequent request silently degrades to a full live reparse

## Summary
`BaseParser._i()` accepts arbitrarily large JSON integers (`int("1" * 25)` is
legal JSON). A single event carrying a token count ≥ 2^63 (a corrupt file, a
log written by a broken client build, or hand-edited data) is parsed fine by
every live path, but **kills every `UsageEntryStore` sync with
`OverflowError: Python int too large to convert to SQLite INTEGER`**. The
compute layer treats that exception as "cache is sick, fall back to live
parsing" (`compute.get_tools_data_for_range` → bare `except Exception`), so:

- the dashboard still renders — plausible numbers, no error anywhere;
- **every** request re-fails the sync first (parse whole corpus → open store →
  attempt insert → OverflowError → live reparse), so the user pays the full
  reparse cost on every request forever;
- `source_errors` stays empty (the parser itself didn't fail; the store did),
  so nothing distinguishes this from a healthy machine.

This is exactly the "bad input → no exception → plausible output → wrong
outcome" class: not a wrong number, but a silent permanent performance and
diagnostics collapse triggered by one line.

## Reproduction
`output/exp04_overflow_store.py` (from repo root:
`PYTHONPATH=src python ../output/exp04_overflow_store.py`):
500 normal Codex `token_count` events + 1 event with
`"input_tokens": 10**25`.

Output:
```
LIVE parse ok: 501 entries, in=10000000000000000000169750
STORE sync RAISED: OverflowError: Python int too large to convert to SQLite INTEGER
compute.get_tools_data_for_range: OK, total_cost= 0.0 source_errors= []
```

## Expected behavior
One malformed numeric field should be quarantined: the offending row dropped
(or clamped) with a parser warning/source error, and the other 500 rows stored.

## Actual behavior
Sync raises; compute's bare `except Exception` hides it; every request repeats
the failed sync + full live reparse. `tokdash db sync` also hard-fails
(verified by the same OverflowError at the store layer).

## Why it matters
- A local dashboard that silently becomes 100x slower with no signal is a
  support burden ("tokdash got slow" with nothing in the logs).
- The same failure class covers any INTEGER column (timestamp columns
  included: a `timestamp` of 10^25 in a raw entry also raises — see
  `_timestamp_ms`, which only catches `Exception` around int conversion, and
  a huge-but-valid int passes through).
- SQLite is the documented "performance index" — its contract ("falls back to
  live parsing if it is disabled or unavailable") does not anticipate
  *repeatedly paying* that fallback due to one unpoisonable row.

## Evidence
- `usage_store.py` `_sync_files_now` → `conn.executemany(insert_sql, ...)` —
  sqlite3 raises `OverflowError` on ints outside ±(2^63−1); nothing catches it.
- `compute.py` `get_tools_data_for_range` / `run_local_coding_tools_json`:
  `except Exception: pass` → live reparse.
- `BaseParser._i`: `int(v or 0)` with no bound check; `usage_billing_pricing`
  re-serializes the same int into `billing_json` fine (JSON has no 64-bit
  limit), so the row survives in raw_json but cannot be written to the typed
  INTEGER columns.

## Suggested direction
Clamp or reject non-physical token counts at the parser boundary (the parsers
already reject `bool`; extend to a sane bound, e.g. > 10^9 tokens per event is
not a real usage record) and count the rejection in parser diagnostics; or
catch `OverflowError` per-row in `_sync_files_now` and route the file to the
same missing/quarantine state. Add a fuzz fixture with `10**25` to the store
tests.
