# F-004 (confirmed): A session file whose final line is unterminated is deferred indefinitely by the persistent store — parity loss vs a full parse for as long as the file stays at that size

## Summary
For the five `append_jsonl=True` sources (Gemini CLI, Kimi, WorkBuddy,
Qwen Code, MiniMax Code — confirmed by grep at coding_tools.py lines 1548,
2037, 5564, 6291, 7443), when a session file's final line has **no trailing
newline at the moment of a sync**, the store defers that line and then never
ingests it while the file stays at its current size. A full parse of the
identical bytes yields the deferred row; the default DB-on accounting path
does not. (Mechanism re-verified in the final review pass; an earlier
version of this note described a different — incorrect — mechanism.)

## Verified mechanism (measured, 2026-09-30 review pass)

Deterministic reproducer (Gemini CLI parser, real on-disk format, binary
writes, `TOKDASH_SIG_TTL=0`):

1. Terminated 14-line file → full sync: store holds 14 rows (in=1260);
   `file_state` records `size = safe_offset = 2720` (= real size).
2. Append one more line **without** a trailing newline (binary write),
   sync: still 14 rows. The tail reader
   (`compute._complete_jsonl_tail`, compute.py:118) correctly cuts at the
   last `\n` and emits nothing; the store then records
   `size = safe_offset = 2721` while the real file is 2915 bytes — the
   offset sits exactly at the start of the unterminated line.
3. Three more syncs with the file at rest: still 14 rows. Each sync
   re-reads from the recorded offset, again finds no *complete* line, and
   re-records the same state. Nothing errors, nothing logs.
4. Fresh store, full reparse of the identical file: **15 rows (in=1350)** —
   the persistent store disagrees with the live path about the same bytes.
5. Recovery probe: appending any later byte sequence containing another
   `\n` after the deferred line (a new terminated message, or even a lone
   `"\n"`) makes the next sync ingest the deferred line (15 rows, then
   16 with the new message). So: **the loss lasts exactly as long as the
   file never again contains a newline after the deferred line** — the
   normal end state of a finished session that ends unterminated.
   Active sessions self-heal.

## Why the earlier "stranded forever / mid-line fragment" story was wrong

- The stored offset is never *past* the last complete line — it equals the
  last complete line's end, so later tail reads start cleanly (not
  mid-line) and the deferred line is re-examined on every sync.
- The apparent "one-sync lag" in early experiments was a harness artifact:
  Windows text-mode appends turn `\n` into `\r\n` (changing the layout),
  and the parser's 5-second signature cache (`_timed_sigs`,
  `TOKDASH_SIG_TTL`, coding_tools.py:66–68) serves stale stats between
  quick successive syncs. With binary writes and TTL=0 the behavior is
  fully deterministic as described above.
- The `msg-9` "mid-line fragment" claim in `exp11b_tail_dissect.py`
  belonged to that flawed harness setup and should not be cited.

## Demonstrated divergence (final, verified)

| Step | Store rows / input tokens |
|---|---|
| full sync, terminated file | 14 / 1260 |
| sync while last line unterminated | 14 / 1260 |
| 3 more syncs, file at rest | 14 / 1260 |
| fresh store, full reparse of identical bytes | **15 / 1350** |
| after terminated append (file grows) | 16 / 1440 (deferred line recovered) |

Issue draft: `issues/I-001-tail-append-strands-last-line.md` (embeds the
full reproducer). Earlier experiments `output/exp11_tail_append.py` /
`exp11b_tail_dissect.py` show the same divergence but contain the flawed
harness artifacts described above — cite the issue's reproducer instead.

## Expected behavior
The audit's parity property (DB-backed totals == live totals for the same
files; measured 30/30 on randomized Codex corpora with terminated lines,
`output/exp20_parity_property.py`) is the invariant the store maintains
elsewhere; an unterminated final line breaks it. At minimum the deferred
line should be ingested once observed (the parsers tolerate it on full
parse), or explicitly tracked as pending.

## Impact
Silent, stable undercount of exactly the deferred line(s) on the default
DB-on path, invisible in `db verify` and `source_errors`. Not
demonstrated on a real client's byte stream (flagged in the issue).
Self-heals if the session continues; permanent for dormant sessions whose
file ends unterminated.

## Subsystem
`src/tokdash/compute.py` `_complete_jsonl_tail` (correct on its own);
`usage_store.py` `sync_files` tail branch + `file_state` upsert (records
`size = safe_offset` at the deferred line and has no revisit mechanism);
parsers with `append_jsonl=True` (five, listed above).
