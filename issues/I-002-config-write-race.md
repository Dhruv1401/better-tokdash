# [reliability] Concurrent config writers crash on Windows and can lose updates — the consent store's write is unserialized with a shared temp filename

## Summary

`_write_config` in [`tokdash/src/tokdash/sources/quota/config.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/quota/config.py) writes `config.json` through a read-modify-write with one fixed temp filename (`config.json.tmp`) and no lock. Several independent writers use this file: the dashboard's quota handlers, the `tokdash quota consent` CLI, and the background poller. When two writers overlap, both `tmp.write_text(...)` and the final `tmp.replace(p)` can hit the other writer's open handle. On Windows this raises an unhandled `PermissionError` to the caller; on POSIX the same overlap silently discards one writer's changes (both write complete snapshots of the file, so the loser's write is gone).

Measured on Windows 11, Python 3.12: 62 of 80 writes fail with `PermissionError` under 4-thread contention, and 30+30 of 60 writes fail across two concurrent processes. The config file is the consent store that gates credentialed provider access (`credential_scan`, per-provider API switches), so a lost update means consent state silently reverting.

## Reproduction

Cross-process (dashboard + CLI shape), verified verbatim:

```python
# child.py — run two copies against the same TOKDASH_DATA_DIR concurrently
import os, sys
os.environ["TOKDASH_DATA_DIR"] = sys.argv[1]
from tokdash.sources.quota import config as qconf
errs = 0
for i in range(30):
    try:
        qconf.set_quota_consent({"credential_scan": i % 2 == 0})
        qconf.set_poll_interval_minutes(5 + (i % 10))
    except Exception:
        errs += 1
print(errs)
```

```
TOKDASH_DATA_DIR=<shared dir> python child.py <dir> & \
TOKDASH_DATA_DIR=<same dir>   python child.py <dir> & wait
# observed: 30 + 30 errors out of 60 writes on Windows 11
```

In-process variant (4 threads × 20 writes): 62/80 `PermissionError`. The audit's harness runs are [`output/exp10b_crash_rate.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp10b_crash_rate.py) (threads) and [`output/_f3_child.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/_f3_child.py) (processes).

## Expected behavior

At minimum, concurrent writers should not crash the caller: `tokdash quota consent` and the dashboard's quota toggles should either serialize cleanly or fail with a handled, retryable error — not an unhandled `PermissionError` from a temp-file collision. Loss of a just-written consent on overlap is a reasonable-robustness expectation for any RMW file, though I have not demonstrated the lost-update on a live multi-process run on POSIX (it follows from the code path: both writers read the same baseline and write complete snapshots).

## Actual behavior

- Both writers open the *same* `config.json.tmp`; on Windows the second open (or the `replace` over an open handle) raises `PermissionError`, which propagates uncaught out of `set_quota_consent`/`set_poll_interval_minutes`.
- Error type and rate verified: 62/80 in-process (all `PermissionError`), 30+30/60 cross-process.
- On POSIX no exception is raised; the surviving file is whichever snapshot `replace`d last, so a consent flipped by the losing writer reverts silently.

## Impact

Demonstrated: crashing writes on Windows at high rates under concurrent use (the dashboard writes this file from user actions; the poller can write it on schedule), with the failure surface being exactly the consent controls. Not demonstrated: an actual consent loss in the field — the POSIX lost-update is established from the code path, not observed.

## Root cause

Established by source inspection and the crash signature: `_write_config` performs an unserialized RMW with a single fixed temp path shared by all writers in [`tokdash/src/tokdash/sources/quota/config.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/quota/config.py). The usage database solves the same problem with `usage_db_process_lock`; the config store has no equivalent.

## Evidence

- Inline cross-process reproducer above (verified: 30+30/60 errors).
- [`output/exp10b_crash_rate.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp10b_crash_rate.py) — 4-thread run with tracebacks.
- `_write_config` source: `tmp = p.with_suffix(p.suffix + ".tmp")`, `tmp.write_text(...)`, `tmp.replace(p)` — no lock, fixed name.

## Suggested direction

The invariant: concurrent writers must not observe each other's temp file, and a replace must not race an open handle. A per-writer unique temp name (e.g. `tempfile.mkstemp` in the same directory) removes the collision; a lock file held across the RMW (the existing `usage_db_process_lock` pattern) additionally removes the lost-update window. Either change alone stops the Windows crashes; both together give serialized last-writer-wins semantics.
