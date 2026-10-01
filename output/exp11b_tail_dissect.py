"""EXP-11b: dissect the tail-append row loss. Prints safe_offset vs size and
which rows exist after each sync. Hypothesis: with NO trailing newline, the
tail reader returns "" and safe_offset=old, but the store then records
safe_offset = new size (from the parse_file_tail_entries return? or size?),
so the next tail starts PAST the un-newlined line and it is never parsed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))


def iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def gemini_line(i, t0, model="gemini-3-pro"):
    return json.dumps({
        "id": f"msg-{i}",
        "timestamp": iso(t0 + i * 1000),
        "type": "gemini",
        "model": model,
        "tokens": {"input": 100, "output": 50, "cached": 10, "thoughts": 5,
                   "tool": 0, "total": 155},
    })


home = Path(tempfile.mkdtemp(prefix="exp11b-"))
data = Path(tempfile.mkdtemp(prefix="exp11bd-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = "1"
import pathlib
pathlib.Path.home = classmethod(lambda cls: home)

chats = home / ".gemini" / "tmp" / "hash" / "chats"
chats.mkdir(parents=True)
t0 = 1_770_000_000_000
f = chats / "session-abc.jsonl"
f.write_text("\n".join(gemini_line(i, t0) for i in range(10)), encoding="utf-8")

from tokdash.pricing import PricingDatabase
from tokdash.sources.coding_tools import GeminiCLIParser
from tokdash.usage_store import UsageEntryStore
from tokdash.compute import _collect_parser_tail, _complete_jsonl_tail

pdb = PricingDatabase()
parser = GeminiCLIParser(pdb)
parser_sig = {"object": "GeminiCLIParser", "version": 1}


def sigs():
    s = f.stat()
    return ((str(f), s.st_mtime_ns, s.st_size),)


def dump_state(label):
    conn = sqlite3.connect(data / "usage.sqlite3")
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT path, size, safe_offset, entry_count FROM file_state").fetchall()
    keys = [r[0] for r in conn.execute(
        "SELECT entry_key FROM usage_entries WHERE source='gemini_cli' ORDER BY timestamp").fetchall()]
    conn.close()
    st = f.stat()
    print(f"{label}: file size={st.st_size}")
    for r in rows:
        print(f"   file_state: size={r['size']} safe_offset={r['safe_offset']} entries={r['entry_count']}")
    print(f"   stored keys: {[k[:20] for k in keys]}")


store = UsageEntryStore(db_path=data / "usage.sqlite3")
store.sync_files("gemini_cli", sigs(), parser=parser_sig,
                 parse_file_entries=lambda s: parser._parse_all(),
                 parse_file_tail_entries=lambda s, o: _collect_parser_tail(parser, s, o))
dump_state("after full replace (no trailing newline)")

# What does the tail reader think at old offset?
s = f.stat()
text, off = _complete_jsonl_tail(str(f), 0)
print(f"tail(0) on current file: len(text)={len(text)} -> safe_offset={off} "
      f"(last line has no \\n: file ends with '}}' = {f.read_bytes()[-1:]})")

# append 5 lines, each properly newline-terminated EXCEPT the join adds none at end
with f.open("a", encoding="utf-8") as h:
    h.write("\n" + "\n".join(gemini_line(i, t0) for i in range(10, 15)))

s = f.stat()
text, off = _complete_jsonl_tail(str(f), 0)
print(f"after append: size={s.st_size}; tail(0) safe_offset={off} "
      f"({len(text.splitlines())} complete lines)")
store.sync_files("gemini_cli", sigs(), parser=parser_sig,
                 parse_file_entries=lambda s: parser._parse_all(),
                 parse_file_tail_entries=lambda s, o: _collect_parser_tail(parser, s, o))
dump_state("after tail sync")
