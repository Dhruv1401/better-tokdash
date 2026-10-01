# [observability] Store-sync failures are invisible to `source_errors` — an index failure silently converts every cache-bypassing request into a full live reparse

## Summary

`compute.run_local_coding_tools_json` and `get_tools_data_for_range` in [`src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py) wrap the store sync in `except Exception` and fall back to the live parsers. The fallback is the right resilience call — the DB is documented as a cache — but the failure is recorded nowhere: `source_errors` (the mechanism that exists precisely so the UI can show "unavailable" instead of a zero) only ever receives *parser* errors, never store-layer ones. The only store error deliberately propagated is `UsageDatabaseSchemaTooNewError`.

Verified with two independent store failures, both in a fresh process:

1. **Corrupt DB file** (`usage.db` = garbage bytes): `run_local_coding_tools_json(["--today"])` succeeds with `entries: 0` and `source_errors: None`; `get_tools_data_for_range(...)` succeeds with `source_errors: []`.
2. **Poisoned store** (one >2^63 token row, see [I-003](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-003-huge-int-poisons-store.md)): every sync raises `OverflowError`; the API keeps serving live totals with `source_errors: []`, and every cache-bypassing request pays parse-class latency (~5–12 s on a 200k-event corpus) instead of the ~4 ms warm-store response.

In both cases the dashboard looks completely healthy while silently re-deriving everything from the raw logs.

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12:

```python
import os, tempfile
from pathlib import Path
home = Path(tempfile.mkdtemp()); d = Path(tempfile.mkdtemp())
os.environ["TOKDASH_DATA_DIR"] = str(d)
os.environ["TOKDASH_USAGE_DB"] = str(d / "usage.db")
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)

(d / "usage.db").write_bytes(b"this is not a sqlite database" * 10)   # corrupt store

from tokdash import compute
data = compute.run_local_coding_tools_json(["--today"])
print("fallback ok, source_errors:", data.get("source_errors"))        # None (key absent)

res = compute.get_tools_data_for_range(None, None)
print("source_errors:", res.get("source_errors"))                      # []
```

Observed (verified verbatim): both calls succeed via live fallback; neither records anything. The poisoned-store variant with latency numbers is [`output/exp24_api_poison_latency.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp24_api_poison_latency.py).

## Expected behavior

The codebase's own design language treats "degraded but visible" as the standard: per-parser `source_errors` exist so the UI can show unavailable states, and the schema-too-new case deliberately *raises* rather than hides ("reparsing the logs instead would hide the skew behind a permanent full-history reparse" — the comment sits directly above the generic `except Exception` that does exactly that for every other store failure). A store-sync failure should reach `source_errors` the same way a parser failure does — e.g. a `"usage-db"` pseudo-source entry — so the UI can say "index unavailable, showing live data".

## Actual behavior

- `run_local_coding_tools_json`: `except Exception:` → live fallback, no record (the returned dict carries `source_errors` only from the parser layer, or the key not at all).
- `get_tools_data_for_range`: same pattern; `result["source_errors"] = [e["source"] for e in tracker.source_errors]` — tracker errors only.
- `_sync_usage_store` propagates only `UsageDatabaseSchemaTooNewError`.

## Impact

Demonstrated: two distinct store failures (corrupt file, poisoned row) both degrade invisibly; the observable cost is parse-class latency on every cache-bypassing request, scaling with history ([I-003](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-003-huge-int-poisons-store.md) measurements), plus a CLI (`tokdash db sync`) that fails outright with no correlation to what the dashboard shows. The observability gap is what turns any store poison from a ten-minute diagnosis into a support mystery.

## Root cause

Established: the fallback sites discard the exception; `source_errors` is populated exclusively from `tracker.source_errors`, which the store layer never feeds.

## Evidence

- Inline reproducer above (verified verbatim).
- Fallback sites and the deliberate `SchemaTooNewError` contrast: [`src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py) (`run_local_coding_tools_json`, `get_tools_data_for_range`, `_sync_usage_store`).
- Latency of the invisible degradation: [`output/exp24_api_poison_latency.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp24_api_poison_latency.py).
- The store-poison that motivates the visibility: [I-003](https://github.com/Dhruv1401/better-tokdash/blob/audit/issues/I-003-huge-int-poisons-store.md).

## Suggested direction

The invariant: a request served by fallback must be distinguishable from one served by a healthy index. Mechanically: catch, log (`exc_info=True`), and append a `{"source": "usage-db", "error": ...}` entry (or a boolean like `usage_db_degraded: true`) to the response so the dashboard can badge it. Either alone fixes the invisibility; the change is a few lines at the two fallback sites.
