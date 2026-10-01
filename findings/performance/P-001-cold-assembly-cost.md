# P-001 (performance, measured): Session-assembly cost is ~13.5 ms per session cold; 5,000 sessions cost 68 s on the live-parse path — the per-file parse cache is the only thing between a big history and a multi-minute Sessions tab

## Measurements (Windows 11, Python 3.12, NVMe, exp09)
Codex event parse (`_parse_all`), single file:
- 1k events: 45 ms
- 10k events: 253 ms (x5.6 for x10 — fine)
- 100k events: 6,125 ms (x24 for x10 — superlinear onset; likely the
  `event_index_by_key` dict growth plus entry churn is fine, more likely
  memory/GC; still ~60 µs/event, acceptable)

Session assembly (`sessions.get_sessions_data("codex", "year")`, empty
store, forced live parse of N files x 20 events):
- 10 sessions: 176 ms
- 100: 1,927 ms (x11 for x10)
- 1,000: 14,728 ms (x7.6)
- 5,000: 67,705 ms (x4.6; ≈13.5 ms/session)

## Why it matters
- The Sessions tab cold path is linear-with-a-big-constant. The mitigations
  are real (persistent `session_records` store + per-file parse cache
  keyed on (mtime,size)), so warm requests are fast; but the cold case is
  exactly what a first run after install, after `tokdash db resync`, or on
  a machine where `TOKDASH_USAGE_DB=0` hits — and it is 1–2 orders of
  magnitude away from interactive for realistic histories (5k sessions ≈
  68 s, 50k would be ~11 minutes).
- The per-file signature scan that precedes the assembly is O(files) on
  every request even when everything is cached (stat storm over 5,000
  files is included in the numbers above; it is the cheap half).

## Suggested direction
- Batch-parse in parallel (the parse is embarrassingly parallel per file;
  `TOKDASH_COMPUTE_CONCURRENCY` exists for requests but file parsing is
  serial in `_parse_all`).
- Show progressive results / a "still indexing" state in the UI after a
  threshold instead of an apparently-hung tab.
- Add a benchmark regression test at 1k sessions with a budget assert
  (test_api_benchmark.py exists but does not cover this scale).
