# F-003 (confirmed): `config.json` writes are unserialized read-modify-write with a *shared* `.tmp` filename — concurrent writers crash with unhandled `PermissionError` on Windows (78.8% failure rate measured) and silently lose updates anywhere

## Summary
Every quota-config mutation (`set_quota_consent`, `set_quota_enabled`,
`set_poll_interval_minutes`, `ensure_quota_consent_migrated` — also the
`onboard`/updatecheck consent write) does:

```python
cfg = _read_config()                      # 1. read
quota[...] = ...                          # 2. mutate in memory
tmp = p.with_suffix(p.suffix + ".tmp")    # 3. ONE fixed tmp name
tmp.write_text(...)                       # 4. write
tmp.replace(p)                            # 5. atomic-ish replace
```

Two problems:

1. **The `.tmp` filename is fixed** (`config.json.tmp`). Two concurrent
   writers open/write/replace the *same* tmp file. On Windows, step 4 or 5
   raises unhandled `PermissionError`/`Access is denied` when another
   thread/process holds the tmp file. **Measured: 63 errors out of 80
   writes (78.8%)** with 4 threads × 20 writes (exp10b).
2. Even where the replace survives, the **read-modify-write is not
   serialized** (no process lock, no file lock, no compare-and-swap): the
   last writer wins and the other writer's key silently reverts (lost
   update). POSIX will not error — it just corrupts intent silently.

### Cross-process confirmation (second-pass review)
The crash is **not** limited to in-process thread races. Two separate
`python` processes each performing 30 consent writes against one data dir:

```
cross-process: child errors: 16 | child errors: 16
```

i.e. 32 of 60 writes (53%) crash across the process boundary
(`output/_f3_child.py` harness). This means the documented multi-writer
combinations (dashboard + `tokdash quota consent` CLI + companion app)
crash on Windows today, not merely hypothetically.

## Real-world trigger paths
- Dashboard: two quota consent checkboxes toggled in quick succession → two
  concurrent POSTs → FastAPI runs the sync handlers on a thread pool →
  in-process race (no 500 surfaced today only because of timing luck).
- Dashboard POST racing `tokdash quota consent ...` from a terminal.
- `ensure_quota_consent_migrated()` (any early request path) racing a
  consent write from the Quota tab.
- Companion app + dashboard writing settings simultaneously (two
  processes).

Impact of a hit: unhandled 500 to the user (write failed mid-save) or, on
POSIX, a silently reverted consent/interval — e.g. a just-granted
`credential_scan` consent reverting to off with no signal.

## Reproduction
- `output/exp10b_crash_rate.py` — 4 threads × 20 mixed consent/interval
  writes → `errors: 63 (78.8%)`, all `PermissionError` on
  `config.json.tmp` (both `Errno 13` on open and `WinError 5` on replace).
- `output/exp10_config_race.py` — 2-thread variant; one observed run
  crashed with `PermissionError: [WinError 32]` (file in use) mid-run.
- `output/_f3_child.py` — 2 independent processes × 30 writes → 16 + 16
  errors (53%).

## Expected behavior
Concurrent config writers serialize (process lock like
`usage_db_process_lock`, or atomic unique-tmp + lock), and each writer's
merged result persists.

## Actual behavior
Shared tmp name + unlocked RMW: crashes on Windows, lost updates anywhere.

## Why it matters
- This is the *consent store* for network access to provider accounts.
  A silently reverted consent is a security-adjacent surprise (user granted
  access, system later acts as if they didn't); a crashed one leaves the
  dashboard's toggle lying about what was saved.
- Windows is an explicitly supported (if "experimental") platform — the
  crash is deterministic under contention there.

## Suggested direction
Take `filelock.process_lock(config_path)` (the existing seam) around the
whole RMW, and give each write a unique tmp name
(`f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp"`), or write via
`tempfile.NamedTemporaryFile(dir=p.parent, delete=False)` before replace.
Add a regression test with 4 threads × N writes asserting zero exceptions
and both writers' final keys present.

## Subsystem
`src/tokdash/sources/quota/config.py` `_write_config` and all callers;
same pattern in `onboard/updatecheck.py` consent write.
