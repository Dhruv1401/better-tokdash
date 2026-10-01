"""EXP-11: tail-append semantics — partial last line, no trailing newline,
and duplicated-prefix safety for Gemini/Kimi (append_jsonl=True parsers).

Checks:
  A. file grows with a COMPLETE last line that has NO trailing newline:
     tail-read must return "" (rfind newline cut) -> then next sync reparses
     the file fully? Or is it stranded?
  B. incremental A-then-B == full A+B (property).
  C. appended line arrives while the previous last line lacked \n.
"""
from __future__ import annotations

import json
import os
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


def main():
    home = Path(tempfile.mkdtemp(prefix="exp11-"))
    data = Path(tempfile.mkdtemp(prefix="exp11d-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data)
    os.environ["TOKDASH_USAGE_DB"] = "1"
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)

    chats = home / ".gemini" / "tmp" / "hash" / "chats"
    chats.mkdir(parents=True)
    t0 = 1_770_000_000_000
    lines = [gemini_line(i, t0) for i in range(10)]

    from tokdash.pricing import PricingDatabase
    from tokdash.sources.coding_tools import GeminiCLIParser
    from tokdash.usage_store import UsageEntryStore

    pdb = PricingDatabase()
    parser = GeminiCLIParser(pdb)
    f = chats / "session-abc.jsonl"

    # Scenario A: write 10 lines, no trailing newline; then append more (still no \n)
    f.write_text("\n".join(lines), encoding="utf-8")
    store = UsageEntryStore(db_path=data / "usage.sqlite3")
    parser_sig = {"object": "GeminiCLIParser", "version": 1}

    def sigs():
        s = f.stat()
        return ((str(f), s.st_mtime_ns, s.st_size),)

    n1 = store.sync_files("gemini_cli", sigs(), parser=parser_sig,
                          parse_file_entries=lambda s: parser._parse_all(),
                          parse_file_tail_entries=lambda s, o: _tail(parser, s, o))
    rows1 = store.query_entries(sources=["gemini_cli"])
    print(f"A1 (10 lines, no trailing \\n): stored {len(rows1)} rows, in={sum(r['input'] for r in rows1)}")

    # append 5 more lines (file grows; previous content unchanged)
    with f.open("a", encoding="utf-8") as h:
        h.write("\n" + "\n".join(gemini_line(i, t0) for i in range(10, 15)))
    n2 = store.sync_files("gemini_cli", sigs(), parser=parser_sig,
                          parse_file_entries=lambda s: parser._parse_all(),
                          parse_file_tail_entries=lambda s, o: _tail(parser, s, o))
    rows2 = store.query_entries(sources=["gemini_cli"])
    print(f"A2 (appended 5 more): stored {len(rows2)} rows, in={sum(r['input'] for r in rows2)}")
    print("   expected: 15 rows, in=1500  | got:", len(rows2), sum(r['input'] for r in rows2))

    # B: fresh store, full file at once
    store2 = UsageEntryStore(db_path=data / "usage-b.sqlite3")
    store2.sync_files("gemini_cli", sigs(), parser=parser_sig,
                      parse_file_entries=lambda s: parser._parse_all(),
                      parse_file_tail_entries=lambda s, o: _tail(parser, s, o))
    rowsB = store2.query_entries(sources=["gemini_cli"])
    print(f"B (full file at once): {len(rowsB)} rows, in={sum(r['input'] for r in rowsB)}")
    print("incremental == full?", (len(rows2), sum(r['input'] for r in rows2)) ==
          (len(rowsB), sum(r['input'] for r in rowsB)))


def _tail(parser, file_sig, start_offset):
    from tokdash.compute import _collect_parser_tail
    return _collect_parser_tail(parser, file_sig, start_offset)


if __name__ == "__main__":
    main()
