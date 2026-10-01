# [accounting] A session file whose final line is unterminated loses that line from the persistent store for as long as the file stays at that size — Gemini CLI, Kimi, WorkBuddy, Qwen Code, MiniMax Code

## Summary

The persistent usage store ingests the five `append_jsonl=True` sources incrementally. When a session file's **final line has no trailing newline at the moment of a sync**, the tail reader correctly refuses to emit that unterminated line — but the store still records the resume state as if everything up to the current file size were consumed (`file_state.size = safe_offset = <offset at the unterminated line>`, measured: 2721 recorded vs 2915 real bytes). On every later sync while the file does not grow, the store re-reads from that offset, again finds no *complete* line, and again advances the recorded state — so the deferred line is never ingested, with no error and no diagnostic.

The result is a stable parity violation: a full parse of the identical file yields 15 rows / 1,350 input tokens, while the persistent store — the default DB-on accounting path behind Overview and Stats — holds 14 rows / 1,260 input tokens, across arbitrarily many syncs. The line is still in the file and a fresh store parses it fine; the loss lasts exactly as long as the file never again contains a newline after that line. If the session continues (any later write introduces another `\n`), the deferred line is picked up on the next sync, so active sessions self-heal; finished sessions whose file happens to end without a final newline keep the gap permanently.

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12, using the real Gemini CLI parser and on-disk format. Self-contained:

```python
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
os.environ["TOKDASH_SIG_TTL"] = "0"   # deterministic: never serve cached file signatures

def iso(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def gl(i, t0):
    return json.dumps({"id": f"msg-{i}", "timestamp": iso(t0 + i * 1000), "type": "gemini",
                       "model": "gemini-3-pro",
                       "tokens": {"input": 100, "output": 50, "cached": 10, "thoughts": 5, "tool": 0, "total": 155}})

home = Path(tempfile.mkdtemp()); data = Path(tempfile.mkdtemp())
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = "1"
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)

chats = home / ".gemini" / "tmp" / "hash" / "chats"; chats.mkdir(parents=True)
t0 = 1_770_000_000_000
f = chats / "session-abc.jsonl"
f.write_bytes(("\n".join(gl(i, t0) for i in range(14)) + "\n").encode())   # terminated base

from tokdash.pricing import PricingDatabase
from tokdash.sources.coding_tools import GeminiCLIParser
from tokdash.usage_store import UsageEntryStore
from tokdash.compute import _collect_parser_tail

parser = GeminiCLIParser(PricingDatabase())
def sigs():
    s = f.stat(); return ((str(f), s.st_mtime_ns, s.st_size),)
psig = {"object": "GeminiCLIParser", "version": 1}
store = UsageEntryStore(db_path=data / "u.sqlite3")

def sync():
    store.sync_files("gemini_cli", sigs(), parser=psig,
                     parse_file_entries=lambda s: parser._parse_all(),
                     parse_file_tail_entries=lambda s, o: _collect_parser_tail(parser, s, o))

def rows():
    r = store.query_entries(sources=["gemini_cli"])
    return len(r), sum(x["input"] for x in r)

sync(); print("1) full sync of terminated file:", rows())            # (14, 1260)
with f.open("ab") as h: h.write(("\n" + gl(14, t0)).encode())        # final line, no trailing \n
sync(); print("2) sync while last line unterminated:", rows())       # (14, 1260)
for _ in range(3): sync()
print("3) after 3 more syncs (file at rest):", rows())               # (14, 1260)

store2 = UsageEntryStore(db_path=data / "u2.sqlite3")
store2.sync_files("gemini_cli", sigs(), parser=psig,
                  parse_file_entries=lambda s: parser._parse_all(),
                  parse_file_tail_entries=lambda s, o: _collect_parser_tail(parser, s, o))
r2 = store2.query_entries(sources=["gemini_cli"])
print("4) fresh store, full reparse of IDENTICAL bytes:", len(r2), sum(x["input"] for x in r2))
# (15, 1350)

with f.open("ab") as h: h.write(("\n" + gl(15, t0) + "\n").encode())  # file grows again
sync(); print("5) after a terminated append:", rows())               # (16, 1440) — deferred line recovered
```

Observed output (verified verbatim): `(14, 1260)` in steps 1–3, `(15, 1350)` in step 4, `(16, 1440)` in step 5. The persistent store's totals for the same bytes differ from a full parse by one row / 90 input tokens for as long as the file stays at its current size. Also verified: writing a lone `"\n"` after the deferred line (no new message) makes the next sync ingest it (15 rows) — the client's own later terminator rescues the line; dormancy does not.

Note on methodology: use binary writes (`.open("ab")`) and `TOKDASH_SIG_TTL=0`; Windows text-mode appends translate `\n` to `\r\n` (which changes the byte layout), and the parser's 5-second signature cache ([`tokdash/src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py), `_timed_sigs` / `TOKDASH_SIG_TTL`, default 5.0) otherwise serves stale file stats between steps.

## Expected behavior

The store is documented as "the persistent cache behind Overview, Stats, `/api/usage`, `/api/tools` and `tokdash export`" ([`tokdash/docs/development/technical-notes/USAGE_CACHE_IDENTITY.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/development/technical-notes/USAGE_CACHE_IDENTITY.md)); the audit's parity property (DB-backed totals == live totals for the same files) holds on randomized corpora when files end with terminated lines, so incremental-vs-full parity is clearly the maintained invariant. At minimum, an unterminated final line should either be (a) ingested despite the missing terminator — the parsers tolerate it when reached by a full parse — or (b) explicitly tracked as pending, so the store converges without waiting for unrelated bytes.

## Actual behavior

- A sync that observes the file while the final line lacks a terminator defers that line indefinitely; measured `file_state` after the deferral sync: `size = safe_offset = 2721` while the real file is 2915 bytes.
- Subsequent syncs re-read from that offset, find no complete line, and re-record the same state; three consecutive at-rest syncs kept 14 rows.
- A fresh store parsing the identical file yields 15 rows — the two accounting paths disagree about the same bytes.
- Recovery happens only when a later byte sequence introduces another `\n` after the deferred line (new message or the client's own terminator); a session that ends with an unterminated final line keeps the gap permanently.
- No exception, no `source_errors` entry, no log output anywhere in the path.

## Impact

Demonstrated: undercount of exactly the deferred line(s) — one row / 90 input tokens here — on the default accounting path, stable across syncs while the file is at rest, invisible to the user. Not demonstrated: that real clients produce unterminated final lines at moments a sync can observe; the byte layout is a normal mid-session state for append-style writers, but I could not capture it from a live client's stream. Affected surfaces: the five parsers declaring `append_jsonl=True` in [`tokdash/src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py) — `GeminiCLIParser`, `KimiParser`, `WorkBuddyParser`, `QwenCodeParser`, `MiniMaxCodeParser` (confirmed by grep at lines 1548, 2037, 5564, 6291, 7443). With the store disabled (`TOKDASH_USAGE_DB=0`) the same install shows the correct totals, so two users can disagree about the same history.

## Root cause

Established by measurement and source inspection: [`_complete_jsonl_tail`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py) (compute.py:118) cuts the tail at the last `\n` and returns the offset *before* an unterminated final line — correct on its own. The store's incremental path then records `size = safe_offset` as the consumed state ([`tokdash/src/tokdash/usage_store.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/usage_store.py), the `file_state` upsert after tail syncs), and the next sync's tail read starting at that offset structurally cannot emit the deferred line until another `\n` arrives. The deferral is intended (the reader must not emit a line a client might still be writing); the gap is that a line deferred at the *end* of the file is never revisited by any other mechanism while the file stays at that size.

## Evidence

- Inline reproducer above (verified verbatim on this checkout).
- [`output/exp11_tail_append.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp11_tail_append.py) — earlier file-level experiment; note its scenario A1/A2 numbers include the same deferral effect.
- [`output/exp11b_tail_dissect.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp11b_tail_dissect.py) — prints `file_state` bookkeeping around the deferral.
- [`output/exp20_parity_property.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp20_parity_property.py) — the parity property (30/30 on randomized corpora with terminated lines), the invariant this input breaks.
- Store sync internals: [`tokdash/src/tokdash/usage_store.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/usage_store.py) (`sync_files`, tail branch); tail reader: [`tokdash/src/tokdash/compute.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/compute.py) (`_complete_jsonl_tail`).

## Suggested direction

The invariant to restore: incremental ingestion of a file's bytes must converge to the same rows a full parse of those bytes yields, without requiring further writes. Behavior-level options (not validated by me): ingest the unterminated final line at the next sync after it has been observed unchanged at least once (a "stable tail" heuristic), or track deferred-tail state explicitly and reparse the file fully when the recorded offset equals the current size but the raw bytes from the offset are non-empty. A standing parity test over randomized appends *including unterminated tails* (the property harness in [`output/exp20_parity_property.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp20_parity_property.py) is a starting point) would pin this for all five affected parsers.

---

*Full experiment scripts and run logs are not in this repository; contact me (via the audit repo this file is hosted in) if you want them.*
