"""EXP-21: Reasonix occurrence counter scope — split-file metamorphic.

The `:N` occurrence suffix that keeps byte-identical rows countable is scoped
per _parse_all() call: whole-source (all files) on the live path, per-file on
the store path (file_replace, no cross_file_stable_keys -> unique index on
(source, entry_key)).

Metamorphic property under test: "same dataset split into multiple files must
produce the same aggregate" (prompt §8).

  A) two byte-identical rows in ONE day file  -> live 2 entries (digest, :1);
     store: per-file counter also yields digest + :1 -> 2 rows. Predict OK.
  B) the same two rows SPLIT across two files -> live digest (file A) +
     digest:1 (file B) = 2 entries; store: BOTH files emit bare `digest` ->
     unique index collapses them -> 1 row. Predict UNDERCOUNT.

Run from tokdash/: PYTHONPATH=src python ../output/exp21_reasonix_split.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

home = Path(tempfile.mkdtemp(prefix="exp21-"))
data = Path(tempfile.mkdtemp(prefix="exp21d-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = "0"
os.environ["TOKDASH_COMPUTE_CONCURRENCY"] = "1"
import pathlib

pathlib.Path.home = classmethod(lambda cls: home)

REASONIX_HOME = home / ".reasonix"
os.environ["REASONIX_HOME"] = str(REASONIX_HOME)

from tokdash.compute import _collect_parser_file
from tokdash.pricing import PricingDatabase
from tokdash.sources.coding_tools import BaseParser, ReasonixParser, _sig_cache
from tokdash.usage_store import UsageEntryStore

TS = "2026-09-15T12:24:35.556495944+01:00"
ROW = {"ts": TS, "model": "minimax-cn/MiniMax-M3", "prompt": 8247,
       "completion": 56, "cache_hit": 128, "cache_miss": 8119}


def stats_dir():
    d = REASONIX_HOME / "stats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fresh():
    _sig_cache.clear()
    BaseParser._entry_cache.clear()
    return ReasonixParser(PricingDatabase())


def write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def live_entries():
    parser = fresh()
    return parser.collect(None, None)


def store_rows():
    os.environ["TOKDASH_USAGE_DB"] = str(data / f"usage-{len(list(data.iterdir()))}.db")
    parser = fresh()
    store = UsageEntryStore()
    store.sync_files("reasonix", parser._file_signatures(),
                     parser=parser.persistent_parser_signature(), pricing_identity=(),
                     parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                     cross_file_stable_keys=False)
    return store.query_entries(sources=["reasonix"])


def report(label, live, stored):
    print(f"{label}")
    print(f"  live : {len(live)} entries  ids={sorted(e['entry_id'][:20] + ('…' if len(e['entry_id']) > 20 else '') for e in live)}")
    print(f"  store: {len(stored)} rows      ids={sorted((r.get('entry_key') or '')[:20] + ('…' if len(r.get('entry_key') or '') > 20 else '') for r in stored)}")
    print(f"  parity: {len(live) == len(stored)}   (live input total {sum(e['input'] for e in live)} vs store {sum(int(r.get('input', 0) or 0) for r in stored)})")


print("=" * 78)
print("A) two byte-identical rows in ONE day file")
write(stats_dir() / "2026-09-15.jsonl", [ROW, ROW])
report("A", live_entries(), store_rows())

print("=" * 78)
print("B) the same two rows SPLIT across two files (renamed/archive layout is globbed)")
d = stats_dir()
(d / "2026-09-15.jsonl").write_text(json.dumps(ROW) + "\n", encoding="utf-8")
write(d / "2026-09-15-archive.jsonl", [ROW])
report("B", live_entries(), store_rows())

print("=" * 78)
print("C) same scenario as B but with the store DISABLED check: totals users see")
parser = fresh()
e = parser.collect(None, None)
print("  DB-off live totals (what an F-001-poisoned store would fall back to):",
      len(e), "entries, input", sum(x['input'] for x in e))
print("done.")
