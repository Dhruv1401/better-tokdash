# [performance] Cold Sessions assembly costs ~10–13 ms/session — first run at a plausible history size takes over a minute with no progress signal

## Summary

On the live-parse path (first run after install, after a store invalidation, or with the persistent DB disabled), Sessions assembly costs ~10–13 ms per session. Measured scaling on synthetic Codex corpora (empty store, live parse, Windows 11 / Python 3.12 / NVMe, three independent runs):

| sessions | run 1 | run 2 | run 3 |
|---|---|---|---|
| 10 | 176 ms | — | 104 ms |
| 100 | 1.93 s | — | 998 ms |
| 1,000 | 14.7 s | — | 11.2 s |
| 5,000 | 67.7 s | 37.8 s | 63.5 s |

Growth is linear — the earlier "superlinear" characterization applied only to a separate single-file probe (a 100k-event file parses 24× slower than a 10k one) and should not be read into the per-session curve. The finding is the *constant*: at a plausible history size (5,000 sessions over a couple of years of daily multi-client use), the first Sessions load takes roughly a minute with no "still indexing" state, which reads as a hang. The persistent store makes the warm path fast (measured 4–18 ms across runs on a warm `/api/usage`-class request, see [`output/exp24_api_poison_latency.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp24_api_poison_latency.py)), so the bad experience concentrates exactly at first-run and after any store invalidation — parser upgrades, pricing changes, schema bumps — none of which are the user's doing.

## Reproduction

[`output/exp09_scaling.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp09_scaling.py) (single command, ~10 minutes for the 5,000-session tier; the 1,000 tier alone suffices to see the curve):

```bash
PYTHONPATH=src python ../output/exp09_scaling.py
```

It synthesizes N Codex session files and times `sessions.get_sessions_data(...)`. Contact me if you want the raw run logs.

A quicker in-repo check on the same machine: 3,000-event Codex parse ≈ 0.7–1.0 s (`PYTHONPATH=src python ../output/exp24_api_poison_latency.py` includes timed live reparses of that size), consistent with ~0.3 ms/event — the per-session constant is dominated by per-session file work, not per-event parsing.

## Expected behavior

Reasonable-robustness expectation (not an existing spec): either the cold path exploits the available parallelism (per-file parsing is independent; `TOKDASH_COMPUTE_CONCURRENCY` currently governs request handling, not file parsing), or the UI communicates and stages the work. At minimum, a scale-budget test in CI would freeze the constant so a future regression (an accidental O(n²) in a new loader) is caught mechanically.

## Actual behavior

- Linear ~10–13 ms/session on the cold path; no parallelism across files.
- No user-facing progress or partial state: the Sessions view computes for the whole window before first data paint.
- The warm store path is fast, so the wait is invisible in everyday use and concentrated at first-run/invalidation — hard to notice in development, guaranteed to hit every new user with a large history.

## Impact

Measured: 38–68 s at 5,000 sessions on this machine (three runs; machine-dependent, the constant is the finding). Plausible consequence: users read it as a hang and kill the process, which re-triggers the same wait on the next launch until one full sync completes. Not demonstrated: that real users hit this — it depends on history size, and the store mitigates every load after the first successful sync.

## Root cause

Established by measurement: the cold path parses and assembles every session serially; no pool parallelism exists for file parsing (`TOKDASH_COMPUTE_CONCURRENCY` governs requests, not files). Single-file parse onset (24× for 10× at 10k→100k events in one file) suggests per-file costs also creep with log size — worth profiling separately, and consistent with the large-rollout latency the changelog's #64 entry ([PR #64](https://github.com/JingbiaoMei/Tokdash/pull/64), "Stop re-parsing a live Codex rollout per thread and per window") describes fixing once before.

## Evidence

- [`output/exp09_scaling.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp09_scaling.py) (all three runs' methodology; numbers above).
- Single-file onset: same script, Part A (100k events: 6.1 s vs 10k: 0.26 s).
- Warm-path contrast: ~4 ms warm vs ~5–12 s forced-refresh on a 200k-event corpus, measured in [`output/exp24_api_poison_latency.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp24_api_poison_latency.py) — the store architecture works; the cold path is the gap.

## Suggested direction

Behavior-level goals: (1) cold-path wall time should scale with cores, not sessions — per-file parse parallelism is the obvious lever; (2) the UI should show indexing progress rather than silence; (3) a CI scale-budget test (e.g. 1,000 synthetic sessions under N seconds) pins the constant. The #64 work ([PR #64](https://github.com/JingbiaoMei/Tokdash/pull/64): streamed line reading, single-flight syncs) already moved in this direction once; this is the remaining cold-path half.
