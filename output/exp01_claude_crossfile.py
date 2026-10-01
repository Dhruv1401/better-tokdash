"""EXP-01: Claude cross-file duplicate — live (DB-off) parse vs persistent store.

Hypothesis: the same message id appearing in two session files is collapsed by
the parser (fullest-total-wins supersede), but the persistent store keeps ONE
row per (source, entry_key) whose winner is whichever file synced LAST
(INSERT OR REPLACE), not whichever write was fullest. When two files hold the
same id with different splits (e.g. a /export, a backup copy, an editor temp
copy, or a session fork that copies history), the two surfaces can disagree.

Run:  PYTHONPATH=src python ../output/exp01_claude_crossfile.py  (from tokdash/)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

T0 = 1_770_000_000_000  # fixed epoch ms


def claude_line(msg_id, ts_ms, inp, out, cr=0, cw=0, model="claude-sonnet-4-6"):
    ts = ts_ms
    stamp = __import__("datetime").datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return json.dumps({"type": "assistant", "timestamp": stamp,
                       "message": {"id": msg_id, "role": "assistant", "model": model,
                                   "usage": {"input_tokens": inp, "output_tokens": out,
                                             "cache_read_input_tokens": cr,
                                             "cache_creation_input_tokens": cw}}})


def main():
    home = Path(tempfile.mkdtemp(prefix="exp01-claude-home-"))
    data_dir = Path(tempfile.mkdtemp(prefix="exp01-data-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data_dir)
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)  # isolate discovery

    proj = home / ".claude" / "projects" / "proj"
    proj.mkdir(parents=True)

    # The real (canonical) session: one turn, id m1, partial write then full write.
    # Fullest total wins => 1000 in / 500 out.
    (proj / "main.jsonl").write_text("\n".join([
        claude_line("m1", T0, inp=1000, out=100),
        claude_line("m1", T0 + 2_000, inp=1000, out=500),
    ]) + "\n", encoding="utf-8")

    # A second file carrying the same id with a DIFFERENT (smaller) write —
    # e.g. an export/backup/fork copy stamped mid-stream.
    (proj / "copy.jsonl").write_text(claude_line("m1", T0, inp=1000, out=100) + "\n",
                                     encoding="utf-8")

    from tokdash.pricing import PricingDatabase
    from tokdash.sources.coding_tools import ClaudeParser

    pdb = PricingDatabase()
    parser = ClaudeParser(pdb)

    # --- Live parse (what DB-off / parser-level dedup produces) ---
    live = parser._parse_all()
    live_out = sum(e["output"] for e in live)
    live_in = sum(e["input"] for e in live)
    print(f"LIVE  parse: entries={len(live)}  in={live_in}  out={live_out}")
    for e in live:
        print(f"   from {e.get('entry_id')}: in={e['input']} out={e['output']} ts={e['timestamp']}")

    # --- Persistent store path ---
    os.environ["TOKDASH_USAGE_DB"] = "1"
    for mod in ("tokdash.usage_store",):
        if mod in sys.modules:
            del sys.modules[mod]
    from tokdash.usage_store import UsageEntryStore
    store = UsageEntryStore(db_path=data_dir / "usage.sqlite3")
    sigs = parser._file_signatures()
    # Sort file sigs so 'copy.jsonl' syncs AFTER 'main.jsonl' (worst case order:
    # the smaller copy lands last).
    sigs = tuple(sorted(sigs, key=lambda s: s[0]))
    print("file order:", [s[0] for s in sigs])
    for sig in sigs:
        store.sync_files("claude", [sig], parser={"object": "test", "version": 2},
                         parse_file_entries=lambda s=sig: parser._parse_file_strict(s),
                         cross_file_stable_keys=False)
    rows = store.query_entries()
    store_out = sum(r.get("output", 0) for r in rows)
    store_in = sum(r.get("input", 0) for r in rows)
    print(f"STORE rows: {len(rows)}  in={store_in}  out={store_out}")
    for r in rows:
        print(f"   file={r.get('source','')} ts={r['timestamp']} in={r['input']} out={r['output']}"
              f" raw_file={r.get('_raw_file', '?')}")

    print()
    if store_out != live_out:
        print(f"MISMATCH: live out={live_out}, store out={store_out} "
              f"(delta {store_out - live_out})")
        return 1
    print("match — hypothesis not confirmed at this layer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
