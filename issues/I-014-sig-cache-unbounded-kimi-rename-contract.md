# [design/tests] `_sig_cache` grows without bound; Kimi's file-path-bound dedup hash is an undocumented identity contract

## Summary

Two small design weaknesses around parser cache/identity contracts, filed together because they share a theme (implicit contracts that tests don't pin). Neither is a demonstrated live failure; per the project's own issue standards these are design notes, not defects.

1. **`_sig_cache` never evicts.** It is a module-level plain `dict` ([`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py), line 66: `_sig_cache: Dict[str, Tuple[float, tuple]] = {}`); `_timed_sigs` inserts and reads but nothing removes. Verified: 2,000 distinct scan keys → 2,000 retained entries in a fresh process. Realistic key cardinality is ~one per client per process (keys are root paths, not files), so this is not a leak today — but it is one refactoring mistake away from one, and it's the only unbounded cache in a codebase that otherwise bounds everything (`_OPENCODE_QUERY_CACHE_MAX=32`, `lru_cache(maxsize=...)` on session parsers, `TOKDASH_CACHE_MAX_ENTRIES`).

2. **Kimi's dedup key includes the file path.** Per its own docstring: "the dedup key is a SHA-1 of (file path, time, model, usage): including the path keeps identical rows from distinct sessions/agents countable" ([`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py), KimiParser). The consequence — the same rows re-ingest as new entries if the *file* is duplicated under a new path while the old one still exists (sync-tool conflict copies, a manual `cp` mid-session) — is stated nowhere user-facing: SUPPORTED_CLIENTS.md's Kimi paragraph doesn't mention it, unlike Codex/Pi/Cline/Qwen whose content-keyed, cross-file-stable contracts are documented there explicitly. No test pins the rename/copy behavior either way.

## Reproduction

Part 1 (verified in a fresh process):

```python
import os, sys, tempfile
from pathlib import Path
home = Path(tempfile.mkdtemp()); os.environ["TOKDASH_DATA_DIR"] = str(Path(tempfile.mkdtemp()))
os.environ["TOKDASH_USAGE_DB"] = "0"
import pathlib; pathlib.Path.home = classmethod(lambda cls: home)
from tokdash.sources.coding_tools import _sig_cache, _timed_sigs
for i in range(2000):
    _timed_sigs(f"k{i}", lambda i=i: ((f"/x/{i}.jsonl", 1, 1),))
print(len(_sig_cache), type(_sig_cache).__name__)   # 2000 dict
```

Part 2 (path-bound hash): by the docstring, the dedup key for Kimi Code `usage.record` rows is SHA-1 of `(file path, time, model, usage)` — so two identical rows at two paths produce two entries. I did not run a full Kimi double-count end-to-end (it requires a fixture in Kimi's wire format at two paths); the identity contract is quoted directly from the docstring and visible in the digest construction in the same file. A minimal test would: store one Kimi file, copy it to a second path, resync, and count rows before/after.

## Expected behavior

Two reasonable-robustness expectations, both matched by in-repo precedent: (a) process-lifetime caches carry a documented bound (the codebase's own standard); (b) entry-identity semantics under move/rename/copy are documented per client in SUPPORTED_CLIENTS.md and pinned by a metamorphic test ("same dataset at an equivalent path → same totals") — exactly as SUPPORTED_CLIENTS.md already does for Cline, Qwen Code, and MiniMax ("each message id is a stable, source-global dedup key… owned by the earliest timestamp").

## Actual behavior

- `_sig_cache`: unbounded `dict`; verified 2,000/2,000 retention.
- Kimi: path participates in identity; the conflict-copy window (both files present) double-counts by construction of the hash. Behavior undocumented and untested.

## Impact

Hypothetical by the project's own classification: no live failure shown. (1) becomes a leak only if a future caller puts per-file keys into `_timed_sigs`; (2) double-counts only while a path-duplicated copy coexists with its original. Filed because both are one refactoring step away from silent accounting bugs, and (2) contradicts the documented contract style used for every other content-keyed parser.

## Root cause

n/a (design notes): (1) an early convenience cache that outlived its key cardinality assumptions; (2) a deliberate collision-avoidance choice ("keeps identical rows from distinct sessions/agents countable") whose trade-off is undocumented.

## Evidence

- Inline check above (verified verbatim); the inline check is self-contained and needs no experiment file.
- `_sig_cache` declaration at [`src/tokdash/sources/coding_tools.py`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/src/tokdash/sources/coding_tools.py) line 66; Kimi docstring (dedup-key paragraph) and digest construction in the same file.
- Documented-contract precedents: [`docs/reference/SUPPORTED_CLIENTS.md`](https://github.com/Dhruv1401/better-tokdash/blob/audit/tokdash/docs/reference/SUPPORTED_CLIENTS.md) (Cline/Qwen Code/MiniMax paragraphs).

## Suggested direction

(1) Give `_sig_cache` a bound consistent with the codebase's other caches and a comment stating the intended key cardinality. (2) Either document the path-bound contract in SUPPORTED_CLIENTS.md and pin it with the copy-metamorphic test, or fold the path out of the hash and adopt the cross-file-stable contract the other content-keyed parsers use — whichever the maintainer prefers; the gap is that the choice is currently implicit.
