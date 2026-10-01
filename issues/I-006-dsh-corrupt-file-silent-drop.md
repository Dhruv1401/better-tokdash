# [reliability] DeepSeek Harness: a corrupt or unsupported session file is dropped whole — including rows already stored — with no diagnostic

## Summary

The DeepSeek Harness (DSH) decoder is all-or-nothing per file: `decode_dsh_session_file` in [`src/tokdash/sources/dsh_log.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/dsh_log.py) returns a `skip_reason` for the entire file when anything fails — a corrupted byte inside any zstd frame (`decode-error`), a future header `version` (`unsupported-version`), or a missing/invalid header. The parser then skips the file, and the store's `file_replace` sync treats the empty parse as the file's new truth.

Two consequences, all verified by experiment:

1. **Already-stored rows are deleted.** A file that synced cleanly and then becomes unreadable loses its stored rows on the next resync. Measured: 1 stored row before the corruption, 0 after. (Recovery *is* possible — if the file becomes readable again, its rows return on the next sync — the loss lasts as long as the corruption does.)
2. **Nothing reports any of it.** A whole-source scan containing one corrupt and one unsupported-version file emits zero log records across `tokdash.*` (verified with handlers at DEBUG on every `tokdash` logger). The design doc anticipated a counter — [`docs/development/technical-notes/DSH_SUPPORT_DESIGN.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/development/technical-notes/DSH_SUPPORT_DESIGN.md): "skip that file and expose a count through parser diagnostics if one is added" — none was added.

A realistic mid-life format bump shows the compounding effect: with four healthy files, flipping one file's header to `version: 1` silently reduces the stored source from 4 rows to 3.

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12. Requires the `zstandard` package (already a Tokdash runtime dependency). Self-contained script:

```python
import json, os, tempfile
from pathlib import Path
from zstandard import ZstdCompressor

home = Path(tempfile.mkdtemp())
os.environ["TOKDASH_DATA_DIR"] = str(Path(tempfile.mkdtemp()))
os.environ["TOKDASH_USAGE_DB"] = str(home / "usage.db")
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)
os.environ["DSH_HOME"] = str(home / ".dsh")
TS = 1786735098528

def header(id="s9", version=0):
    return {"type": "session", "version": version, "id": id, "createdAt": TS, "cwd": "/p"}

def msg(seq, inp, outp):
    return {"type": "assistant/message", "seq": seq, "time": TS + seq,
            "data": {"turn": 0, "step": 0,
                     "usage": {"inputTokens": inp, "outputTokens": outp},
                     "message": {"role": "assistant", "source": {
                         "kind": "model", "provider": "deepseek",
                         "model": "deepseek-v4-flash"}}}}

def frame(rows):
    # dsh concatenates one independently framed, checksummed zstd frame per
    # durable append batch (see DSH_SUPPORT_DESIGN.md "Zstandard decoding")
    return ZstdCompressor().compress(
        b"".join((json.dumps(r) + "\n").encode() for r in rows))

p = home / ".dsh" / "sessions" / "proj" / "s9" / "session.jsonl.zstd"
p.parent.mkdir(parents=True)
p.write_bytes(frame([header()]) + frame([msg(1, 500, 50)]))

from tokdash.compute import _collect_parser_file
from tokdash.sources.coding_tools import DSHParser, _sig_cache, BaseParser
from tokdash.pricing import PricingDatabase
from tokdash.usage_store import UsageEntryStore

def sync():
    _sig_cache.clear(); BaseParser._entry_cache.clear()
    parser = DSHParser(PricingDatabase())
    store = UsageEntryStore()
    store.sync_files("dsh", parser._file_signatures(),
                     parser=parser.persistent_parser_signature(), pricing_identity=(),
                     parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                     cross_file_stable_keys=False)
    return len(store.query_entries(sources=["dsh"]))

print("healthy:", sync())   # 1

# corrupt one byte in the middle of the file (inside a frame's compressed payload)
raw = bytearray(p.read_bytes()); raw[len(raw) // 2] ^= 0xFF
p.write_bytes(bytes(raw))
os.utime(p, ns=(2_000_000_000, 2_000_000_000))   # change mtime so the file resyncs
print("after corrupt:", sync())  # 0
```

Observed (verified verbatim): `healthy: 1`, `after corrupt: 0`. The version-bump scenario (4 healthy files, then `version: 1` on one → 4 → 3 stored rows, 0 log records during both syncs) is the S7/S10 section of [`output/exp18_dsh_corruption.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp18_dsh_corruption.py), which also covers torn-tail and truncation controls.

## Expected behavior

At minimum, the failure should be surfaced rather than silently treated as a successful empty parse: the design doc's own suggestion (a skipped-file count exposed through parser diagnostics), a warning log, or a `source_errors` entry — any of these makes the loss diagnosable. Beyond that minimum (proposed, not established by existing code): a corrupt *frame* is exactly the failure mode the multi-frame design was built to contain — each append batch is an independently framed, checksummed zstd stream per [`docs/development/technical-notes/DSH_SUPPORT_DESIGN.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/development/technical-notes/DSH_SUPPORT_DESIGN.md) — so rows from frames that still decode could survive a corrupt one, as torn *tails* already do (maintainer tests `test_torn_final_zstd_frame_keeps_complete_rows` / `test_trailing_partial_json_line_is_dropped` in [`tests/test_dsh_parser.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/tests/test_dsh_parser.py) cover the tail case only).

## Actual behavior

- One flipped byte inside either frame's interior → `skip_reason="decode-error"`, zero events from the whole file (verified; also with the corruption in the final frame's interior).
- A previously stored row is deleted on the next resync of the now-unreadable file (1 → 0, verified).
- Zero log records from any `tokdash.*` logger during a scan containing corrupt and unsupported-version files (verified at DEBUG level).
- The version-gate behaves as designed ("unsupported, not corrupt... skip") but with the counter absent, a future dsh format bump silently erases affected sessions from the dashboard until the files are readable again under a Tokdash that supports the version.
- Truncation at a frame boundary and a torn final frame are handled gracefully (complete rows kept) — the corrupt-interior path is strictly lossier than the already-handled torn-tail path.

## Impact

Demonstrated: history silently disappears from the dashboard while the file is unreadable, with no signal anywhere; recovers if the file becomes readable again. Not demonstrated: real-world DSH files with corrupted frames (I constructed the corruption) — the trigger is rare but plausible (interrupted writes, failing disks, sync-tool races), and the *stored-row deletion* consequence is what converts a transient read problem into a dashboard regression a user cannot explain.

## Root cause

Established: `decode_dsh_session_file` is all-or-nothing per file; both consumers treat any non-None `skip_reason` as "skip file" ([`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py) `DSHParser._parse_all`, [`src/tokdash/sessions.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sessions.py) `_parse_dsh_session_file`); and `file_replace` sync semantics treat a per-file empty parse as authoritative (documented in a comment in [`src/tokdash/usage_store.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/usage_store.py)), which conflates "file has zero entries" with "file could not be read".

## Evidence

- Inline reproducer above (verified verbatim).
- [`output/exp18_dsh_corruption.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp18_dsh_corruption.py) — S2/S2b (corrupt interior frames), S3/S4 (torn tail/truncation controls, both graceful), S7 (zero diagnostics), S8 (the unrelated huge-int failure through this path), S9 (stored-row deletion), S10 (version-bump 4→3).
- Design basis for multi-frame independence: [`docs/development/technical-notes/DSH_SUPPORT_DESIGN.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/development/technical-notes/DSH_SUPPORT_DESIGN.md), "Zstandard decoding" — "dsh writes a separately checksummed zstd frame for the header and each durable append batch, then concatenates those frames."

## Suggested direction

Behavior-level goal: a per-file skip must be countable and visible, and must not delete previously stored rows while the file is merely unreadable. Implementation options (unvalidated, for consideration): decode frame-by-frame so intact frames keep their rows (the framing already supports it); expose the design doc's skipped-file counter into `source_errors`; and/or distinguish "skipped (unreadable)" from "empty" in the `file_replace` bookkeeping so skip outcomes preserve stored rows until the file is readable again or deleted.
