# [accounting] DeepSeek Harness: duplicate session copies and repeated `(turn, step)` events make Overview and Sessions disagree

## Summary

DSH entry identity is `dsh:{session_id}:{turn}:{step}` (no file path, no content hash) so that duplicate physical copies of one session never bill twice. Two untested corners of that design make the dashboard's two surfaces disagree, both verified by experiment:

1. **Duplicate physical files with different content.** The parser docstring itself names the case: "duplicate physical files for one session id (both suffixes present, or one id under two project keys) never bill twice" ([`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py)). But which copy *wins* differs by surface: the Overview/usage path keeps the last-parsed copy (`by_entry_id[id] = entry`, files in sorted path order), while the Sessions path's turn dedup keeps the *first* occurrence. With different usage recorded in the two copies, Overview bills 999/99 while Sessions shows 100/10 for the identical corpus.
2. **Non-adjacent repeated `(turn, step)`.** The replace-not-add fold in [`src/tokdash/sources/dsh_log.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/dsh_log.py) replaces the previous sample only when the duplicate is *adjacent* (`last_key == key`). A later, non-adjacent repeat appends a second sample sharing the same entry id. Overview then collapses both to the last (one sample's tokens vanish from that key), while Sessions keeps both turns. Measured on one file with samples `(0,0)=100/10`, `(1,0)=300/30`, `(0,0)=111/22` (in that order): Overview totals 411 input tokens across 2 entries; Sessions totals 511 across 3 turns.

Both outcomes are silent and plausible-looking; the session detail and the Overview simply tell different stories.

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12. Requires `zstandard` (a Tokdash runtime dependency). Scenario 1 (duplicate files):

```python
import json, os, tempfile
from pathlib import Path
from zstandard import ZstdCompressor

home = Path(tempfile.mkdtemp())
os.environ["TOKDASH_DATA_DIR"] = str(Path(tempfile.mkdtemp()))
os.environ["TOKDASH_USAGE_DB"] = "0"
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)
os.environ["DSH_HOME"] = str(home / ".dsh")
TS = 1786735098528

def header(id="s5"):
    return {"type": "session", "version": 0, "id": id, "createdAt": TS, "cwd": "/p"}

def msg(seq, turn, step, inp, outp):
    return {"type": "assistant/message", "seq": seq, "time": TS + seq,
            "data": {"turn": turn, "step": step,
                     "usage": {"inputTokens": inp, "outputTokens": outp},
                     "message": {"role": "assistant", "source": {
                         "kind": "model", "provider": "deepseek",
                         "model": "deepseek-v4-flash"}}}}

def frame(rows):
    return ZstdCompressor().compress(
        b"".join((json.dumps(r) + "\n").encode() for r in rows))

# same session id "s5" in two files, different usage for (0, 0)
pa = home / ".dsh" / "sessions" / "projA" / "s5" / "session.jsonl"
pa.parent.mkdir(parents=True)
pa.write_text("".join(json.dumps(r) + "\n" for r in
                      [header(), msg(1, 0, 0, 100, 10)]), encoding="utf-8")
pb = home / ".dsh" / "sessions" / "projB" / "s5" / "session.jsonl.zstd"
pb.parent.mkdir(parents=True)
pb.write_bytes(frame([header()]) + frame([msg(1, 0, 0, 999, 99)]))

from tokdash.sources.coding_tools import DSHParser
from tokdash.pricing import PricingDatabase
usage = DSHParser(PricingDatabase()).collect(None, None)
print("Overview:", [(e["entry_id"], e["input"], e["output"]) for e in usage])
# [('dsh:s5:0:0', 999, 99)]

from tokdash import sessions
sess = sessions._load_dsh_sessions(sessions._dsh_session_signatures(), ())
print("Sessions:", [(t["_event_key"], t["tokens_in"], t["tokens_out"])
                    for t in sess["s5"]["turns"]])
# [('dsh:s5:0:0', 100, 10)]
```

Scenario 2 (non-adjacent repeat) appends to the same script: one file with rows `[header("s6"), msg(1,0,0,100,10), msg(2,1,0,300,30), msg(3,0,0,111,22)]` → Overview `[(s6:1:0, 300, 30), (s6:0:0, 111, 22)]` (411 input), Sessions `[(s6:0:0, 100, 10), (s6:1:0, 300, 30), (s6:0:0, 111, 22)]` (511 input). Both scenarios verified verbatim; the full harness is [`output/exp18_dsh_corruption.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp18_dsh_corruption.py) (S5/S6).

## Expected behavior

Established by the project's own conventions rather than by code: SUPPORTED_CLIENTS.md documents, for other sources, that Overview and Sessions "resolve a duplicate request id to the same winner" (Qoder CLI) and that the OpenClaw Sessions tab "consumes the exact corpus Overview parses... so the two can never disagree about the winner set" ([`docs/reference/SUPPORTED_CLIENTS.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/reference/SUPPORTED_CLIENTS.md)). DSH currently has no such guarantee, and the docstring's stated intent ("duplicate physical files... never bill twice") doesn't determine *which* copy wins — today the two surfaces pick different winners.

## Actual behavior

- Overview: `DSHParser._parse_all` builds `by_entry_id` over files in sorted order; the last file parsed overwrites earlier entries with the same id.
- Sessions: `_load_dsh_sessions` → the turn merge keeps the first occurrence of each `_event_key`; the second file's divergent turn is dropped.
- Non-adjacent fold: `fold_dsh_usage_samples` gates replacement on adjacency (`if last_key == key and samples`), so a repeated `(turn, step)` appends; Overview collapses by id (last wins), Sessions keeps both turns.

## Impact

Demonstrated: for a session whose copies disagree (resume-from-copy with corrected numbers, an interrupted rewrite, a manual copy between projects), the same dashboard shows two different token totals, and for repeated keys the *total* differs between surfaces (411 vs 511 input tokens on a 3-sample file). Not demonstrated: a real dsh corpus exhibiting duplicate files — the layout is one the parser docstring explicitly anticipates, but I constructed the divergence.

## Root cause

Established: winner selection is an implementation side effect (sorted-file order on one path, first-seen on the other) rather than a shared rule; the fold's adjacency gate contradicts its docstring's "replace-not-add" description for non-adjacent repeats of the same key.

## Evidence

- Inline scenarios above (verified verbatim).
- [`output/exp18_dsh_corruption.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp18_dsh_corruption.py) S5/S6.
- Winner-selection code: `by_entry_id[entry["entry_id"]] = entry` in [`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py); first-occurrence turn dedup in [`src/tokdash/sessions.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sessions.py).
- Cross-surface consistency precedent: [`docs/reference/SUPPORTED_CLIENTS.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/reference/SUPPORTED_CLIENTS.md) (Qoder CLI, OpenClaw paragraphs).

## Suggested direction

The invariant: for the same corpus, Overview and Sessions must resolve duplicate identity to the same winner, and a repeated `(turn, step)` must fold to one sample on both surfaces. A shared winner-selection helper (the Qoder CLI approach — one fold shared by the usage parser and the session loader) plus a dict-based fold keyed on `(turn, step)` for the whole file (not just the previous sample) would give both properties; a two-file metamorphic test ("same session id in two files → Overview total == Sessions total") pins it.
