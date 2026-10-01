# [accounting] Reasonix: byte-identical rows split across two files undercount ~50% in the DB-backed view

## Summary

Reasonix rows have no request id, so the parser identifies them by content digest plus an occurrence counter (`reasonix:{digest}`, `reasonix:{digest}:1`, …) to keep byte-identical requests countable. The counter is a local variable scoped to one `_parse_all()` call in [`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py):

- **Live path (DB off):** `_parse_all()` runs over all files, so the counter spans files → two identical rows get distinct ids and both count.
- **Store path (DB on, the default):** the store parses *per file* (`file_replace`, `cross_file_stable_keys` not set → unique index on `(source, entry_key)`), so each file's parse restarts the counter → both files emit the bare `reasonix:{digest}` → the unique index keeps one row.

The same corpus split across two files therefore yields 2 entries live but 1 row stored. Measured with two byte-identical rows in `stats/2026-09-15.jsonl` and `stats/2026-09-15-archive.jsonl`: live input total **16,238**, stored total **8,119**. The trigger is mundane — Reasonix's scanned glob is `stats/*.jsonl`, so any backup, conflict copy, or renamed day file inside the directory plus a repeated row creates it; no adversarial input is involved.

## Reproduction

Verified on v2.6.8 (`0a179d0`), Windows 11, Python 3.12. Self-contained:

```python
import json, os, tempfile
from pathlib import Path

home = Path(tempfile.mkdtemp())
os.environ["TOKDASH_DATA_DIR"] = str(Path(tempfile.mkdtemp()))
os.environ["TOKDASH_USAGE_DB"] = str(home / "usage.db")
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)
os.environ["REASONIX_HOME"] = str(home / ".reasonix")

ROW = {"ts": "2026-09-15T12:24:35.556495944+01:00", "model": "minimax-cn/MiniMax-M3",
       "prompt": 8247, "completion": 56, "cache_hit": 128, "cache_miss": 8119}
stats = home / ".reasonix" / "stats"
stats.mkdir(parents=True)
(stats / "2026-09-15.jsonl").write_text(json.dumps(ROW) + "\n", encoding="utf-8")
(stats / "2026-09-15-archive.jsonl").write_text(json.dumps(ROW) + "\n", encoding="utf-8")

from tokdash.pricing import PricingDatabase
from tokdash.sources.coding_tools import ReasonixParser

live = ReasonixParser(PricingDatabase()).collect(None, None)
print("live:", len(live), sum(e["input"] for e in live))          # 2 16238

from tokdash.compute import _collect_parser_file
from tokdash.sources.coding_tools import _sig_cache, BaseParser
from tokdash.usage_store import UsageEntryStore

_sig_cache.clear(); BaseParser._entry_cache.clear()
parser = ReasonixParser(PricingDatabase())
store = UsageEntryStore()
store.sync_files("reasonix", parser._file_signatures(),
                 parser=parser.persistent_parser_signature(), pricing_identity=(),
                 parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                 cross_file_stable_keys=False)
rows = store.query_entries(sources=["reasonix"])
print("store:", len(rows), sum(int(r.get("input", 0) or 0) for r in rows))  # 1 8119
```

Observed (verified verbatim): live `2 / 16238`, stored `1 / 8119`. Control: two byte-identical rows in *one* file count correctly everywhere (live 2, stored 2) — only the split layout breaks it, which is why existing tests pass. Full harness: [`output/exp21_reasonix_split.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp21_reasonix_split.py) (scenarios A/B/C).

## Expected behavior

The metamorphic property the rest of the content-keyed parsers honor: splitting a corpus into multiple files must not change aggregates, and the DB-backed view must equal the live view for the same corpus. (SUPPORTED_CLIENTS.md makes equivalent same-corpus promises for other sources, e.g. Qoder CLI's shared fold.)

## Actual behavior

- `seen_digests` initializes inside `_parse_all()`; the store calls `_parse_all()` once per file signature, resetting the counter each time.
- Both files emit `reasonix:{digest}`; the store's unique index on `(source, entry_key)` keeps one row and silently discards the other.
- No error and no `source_errors` entry; the DB-backed totals are simply half of the live totals for the same corpus.

## Impact

Demonstrated: a silent 50% undercount in the default view for a split corpus, with the DB-off view showing the correct numbers — so two modes of the same install disagree. Under-counting is the worst failure direction for a usage tool: the user paid for the tokens the dashboard no longer shows. Trigger frequency depends on Reasonix users' file habits (backups/renames inside the scanned directory); I have not captured a real-world split corpus.

## Root cause

Established: the occurrence counter's scope (per `_parse_all()` call) does not match the store's per-file parse granularity. The digest itself is fine; the *counter* is the part that cannot survive per-file parsing.

## Evidence

- Inline reproducer above (verified verbatim); [`output/exp21_reasonix_split.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/output/exp21_reasonix_split.py) for the full matrix.
- Counter code: `seen_digests: Dict[str, int] = {}` then `entry_id = f"reasonix:{digest}" if not occurrence else ...` in [`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py) (ReasonixParser._parse_all).
- Store granularity: `file_replace` mode with per-file parse + `(source, entry_key)` unique index in [`src/tokdash/usage_store.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/usage_store.py).

## Suggested direction

The invariant: occurrence ids must be a function of the *corpus*, not of how the store batches file parses. The store's per-file parse hook (`prepare_file_context` / `file_context` in `compute._sync_usage_store`) exists for exactly this kind of cross-file parse state and could carry `seen_digests` across the per-file calls of one sync. A split-file metamorphic test ("same rows in one file vs two files → same totals") pins it.
