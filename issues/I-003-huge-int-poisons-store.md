# [reliability] One >2^63 token count fails every store sync for its source and forces live reparse — silently at the API layer

## Summary

A single JSON row in any supported client's logs containing a token count above 2^63−1 (e.g. `input_tokens: 10^25` — legal JSON, no bound check in the parser) parses fine on the live path but raises `sqlite3.OverflowError` when the persistent store inserts it. Because the sync is per-source all-or-nothing, that source gets **zero rows stored** — healthy files included, since the batch fails before commit. Two distinct user-visible consequences, both measured:

1. **`tokdash db sync` fails**: `_sync_usage_database` raises `OverflowError: Python int too large to convert to SQLite INTEGER` on every run until the offending line disappears from the client's logs.
2. **The API keeps working but goes through the live path with no signal**: `/api/usage` returns 200 with correct live totals and `source_errors: []`. With a 200k-event corpus, every cache-bypassing request pays parse-class latency (~12 s first, ~5 s subsequent) instead of the ~4 ms warm-store response a healthy installation serves.

The condition persists until the offending log line is deleted or ages out of the client's retention window. Nothing in the dashboard or logs tells the user any of this.

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12. Self-contained:

```python
import json, os, tempfile
from pathlib import Path
home = Path(tempfile.mkdtemp()); os.environ["TOKDASH_DATA_DIR"] = str(Path(tempfile.mkdtemp()))
os.environ["TOKDASH_USAGE_DB"] = str(home / "usage.db")
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)

d = home / ".codex" / "sessions"; d.mkdir(parents=True)
rows = [
    {"timestamp": "2026-09-01T00:00:00.000Z", "type": "session_meta", "payload": {"id": "s1"}},
    {"timestamp": "2026-09-01T00:00:01.000Z", "type": "turn_context", "payload": {"model": "gpt-5.3"}},
    {"timestamp": "2026-09-01T00:00:02.000Z", "type": "event_msg", "payload": {"type": "token_count",
        "info": {"id": "u1",
                 "total_token_usage": {"input_tokens": 10**25, "cached_input_tokens": 0,
                                       "output_tokens": 5, "reasoning_output_tokens": 0},
                 "last_token_usage": {"input_tokens": 10**25, "cached_input_tokens": 0,
                                      "output_tokens": 5, "reasoning_output_tokens": 0}}}},
]
(d / "rollout.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

from tokdash.compute import CodingToolsUsageTracker, _sync_usage_store
for attempt in (1, 2, 3):
    try:
        store, sources = _sync_usage_store(CodingToolsUsageTracker())
        print(f"attempt {attempt}: ok")
    except Exception as e:
        print(f"attempt {attempt}: {type(e).__name__}")   # OverflowError, all 3 attempts

# API layer: works, silently, via live parse
from tokdash.compute import run_local_coding_tools_json
data = run_local_coding_tools_json(["--since", "2026-08-01", "--until", "2026-10-01"])
print("API fallback entries:", len(data["entries"]), "source_errors:", data.get("source_errors"))
```

Observed: `OverflowError` on all three sync attempts; API fallback succeeds with `source_errors: []`. The CLI check (`_sync_usage_database`, the code behind `tokdash db sync`) and the latency measurement are in [`output/exp24_api_poison_latency.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp24_api_poison_latency.py); the original store-level experiment is [`output/exp04_overflow_store.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp04_overflow_store.py).

## Expected behavior

The store is documented as a disposable cache, so refusing to cache one source is defensible — but the failure should be visible: `source_errors` (which already exists for exactly this purpose at the parser level) should report the sync failure, and healthy rows of the affected source arguably should still sync. The unbounded acceptance of the value itself is the upstream enabler: `_i()` in [`tokdash/src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py) accepts any JSON integer (only `bool` is rejected).

## Actual behavior

- `_sync_usage_store` raises `OverflowError` from the store's `executemany` on every attempt (verified ×3, plus through the DSH parser's `sync_files` path in [`output/exp18_dsh_corruption.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp18_dsh_corruption.py) S8).
- `run_local_coding_tools_json` / `get_tools_data_for_range` catch it with a bare `except Exception` and fall back to the live parsers, leaving `source_errors` empty.
- `/api/usage` serves live totals (the huge row included) with status 200 — plausible-looking output.
- Latency: with a 200k-event corpus, forced-refresh requests cost ~5–12 s each while poisoned (re-run at review time: 8.6 s / 4.8 s, plus a 5.2 s first healthy re-sync) vs 4–18 ms warm once healthy (measured, [`output/exp24_api_poison_latency.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp24_api_poison_latency.py)).
- `tokdash db sync` (via `_sync_usage_database`) raises and aborts.

## Impact

Demonstrated: the affected source's index permanently regenerates from scratch on every cache-bypassing request (seconds on realistic corpora, scaling with history), `tokdash db sync` is broken for the whole install, and nothing anywhere names the cause. The trigger is a single weird row — a client bug or corrupted write suffices; no adversarial intent required. The huge value also flows into API totals verbatim (measured: `total_tokens ≈ 10^25`), so a client that ever emits such a row also produces an absurd dashboard total rather than a flagged one.

## Root cause

Established: `sqlite3` cannot store integers above 2^63−1 and the parser imposes no ceiling (`_i()`), so any such row reaches the insert. The silence comes from compute's bare `except Exception` around the store sync, which predates and is separate from the insert failure ([`tokdash/src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py) — the only store error deliberately propagated is `UsageDatabaseSchemaTooNewError`).

## Evidence

- [`output/exp04_overflow_store.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp04_overflow_store.py) — 3 failed sync attempts, empty `source_errors`.
- [`output/exp24_api_poison_latency.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp24_api_poison_latency.py) — CLI raise, API 200s, latency comparison (poisoned 5–12 s/request vs 4 ms warm).
- Third-pass extension: the DSH parser hits the identical failure via `sync_files` ([`output/exp18_dsh_corruption.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp18_dsh_corruption.py) S8).

## Suggested direction

Two independent changes, either of which alone removes a distinct harm:

1. **Bound the value at parse time** — `_i()` returning `None` above a documented ceiling (e.g. 2^62) turns the poison into a skipped field; a real client never emits token counts near 2^63, so the risk of masking legitimate data is negligible. This also protects the timestamp columns, which accept the same unbounded integers.
2. **Surface the sync failure** — wire store-sync exceptions into `source_errors` (e.g. a `"usage-db"` pseudo-source) so the API response and dashboard can show "index unavailable, serving live data" instead of impersonating a healthy index.
