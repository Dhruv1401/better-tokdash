"""EXP-15: content-hash entry_key collisions — the hash: fallback in
_entry_key identifies a row by (source, model, provider, timestamp, input,
output, cacheRead, cacheWrite, reasoning). Two DIFFERENT real events in two
different files (or the same file) that share all of those are silently
merged by the store (INSERT OR REPLACE + unique index) while the live path
counts both. Look for parsers that (a) emit no explicit entry id, and (b)
stamp seconds-granularity timestamps -> collisions become plausible.

Candidate: Gemini (id present usually), Grok, WorkBuddy, Qoder CLI segment
rows, MiniMax (message ids present)... Which parser truly emits no id?
Try WorkBuddy and Grok first.
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


def try_parser(name, files, parse_fn, sigs_fn):
    """files: dict path->content. parse_fn(parser, sig)->entries via injected sigs."""
    home = Path(tempfile.mkdtemp(prefix=f"exp15-{name}-"))
    data = Path(tempfile.mkdtemp(prefix=f"exp15d-{name}-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data)
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)
    for rel, content in files.items():
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    from tokdash.pricing import PricingDatabase
    from tokdash import coding_tools_mod if False else None
    from tokdash.sources.coding_tools import CodingToolsUsageTracker
    tracker = CodingToolsUsageTracker()
    parser = tracker.parsers.get(name)
    if parser is None:
        return f"({name}: parser not found)"
    parser._file_signatures = sigs_fn
    live = parser._parse_all()

    from tokdash.usage_store import UsageEntryStore
    store = UsageEntryStore(db_path=data / "u.sqlite3")
    parser_sig = parser.persistent_parser_signature()
    store.sync_files(name, sigs_fn(), parser=parser_sig,
                     parse_file_entries=lambda s: parser._parse_all())
    rows = store.query_entries(sources=[name])
    live_in = sum(e.get("input", 0) or 0 for e in live) + sum(e.get("cacheRead", 0) or 0 for e in live)
    store_in = sum(r.get("input", 0) or 0 for r in rows) + sum(r.get("cacheRead", 0) or 0 for r in rows)
    return (f"live n={len(live)} in+cr={live_in} | store n={len(rows)} in+cr={store_in} "
            f"{'DIVERGES' if (len(live), live_in) != (len(rows), store_in) else 'match'}")


def main():
    t0 = 1_770_000_000_000

    # ---- Grok: check schema ----
    from tokdash.sources.coding_tools import GrokParser
    import inspect
    src = inspect.getsource(GrokParser)
    print("Grok has entry_id:", "entry_id" in src)

    # ---- WorkBuddy ----
    from tokdash.sources.coding_tools import WorkBuddyParser
    src = inspect.getsource(WorkBuddyParser)
    print("WorkBuddy has entry_id:", "entry_id" in src)

    # Craft a WorkBuddy fixture: two assistant rows, same second, same tokens, two files
    ts = datetime.fromtimestamp(t0 / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = [json.dumps({"role": "assistant", "model": "gpt-5.5", "prompt_tokens": 100,
                        "completion_tokens": 50, "timestamp": ts}),
            json.dumps({"role": "assistant", "model": "gpt-5.5", "prompt_tokens": 100,
                        "completion_tokens": 50, "timestamp": ts})]
    content = "\n".join(rows) + "\n"
    files = {
        ".workbuddy-ai/projects/p1/t1.jsonl": content,
        ".workbuddy-ai/projects/p2/t2.jsonl": content,
    }
    sigs = tuple((str(home / rel), 1, len(content)) for rel in content_files) if False else None
    # simpler: compute sigs from written files
    def sigs_fn():
        return tuple(sorted((str(home / rel), 1, (home / rel).stat().st_size) for rel in files))
    print("workbuddy:", try_parser("workbuddy", files, None, sigs_fn))


if __name__ == "__main__":
    main()
