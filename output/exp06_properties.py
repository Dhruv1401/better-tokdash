"""EXP-06: property tests across parsers.

P1 idempotence: parse same corpus twice -> same output.
P2 order independence: shuffling file discovery order -> same totals.
P3 split equivalence: one file split into N files -> same totals (for parsers
   that key rows on content, splitting should not change identity).
P4 duplicate file copies (backup dirs): totals must not change for parsers
   whose ids are content-unique; must change (double) is a finding for parsers
   without cross-file identity.
P5 hash-key collision: two DIFFERENT rows without explicit ids that hash to
   the same key are silently merged (store) — count collisions.
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))


def iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def codex_lines(n, t0=1_770_000_000_000):
    lines = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta",
                         "payload": {"id": "sess1"}}),
             json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context",
                         "payload": {"model": "gpt-5.3"}})]
    for i in range(n):
        info = {"id": f"u{i}",
                "total_token_usage": {"input_tokens": 100 + i, "cached_input_tokens": 10,
                                      "output_tokens": 50, "reasoning_output_tokens": 3},
                "last_token_usage": {"input_tokens": 100 + i, "cached_input_tokens": 10,
                                     "output_tokens": 50, "reasoning_output_tokens": 3}}
        lines.append(json.dumps({"timestamp": iso(t0 + i * 1000), "type": "event_msg",
                                 "payload": {"type": "token_count", "info": info}}))
    return lines


def totals(entries):
    return dict(
        n=len(entries),
        inp=sum(e.get("input", 0) or 0 for e in entries),
        out=sum(e.get("output", 0) or 0 for e in entries),
        cr=sum(e.get("cacheRead", 0) or 0 for e in entries),
        cost=round(sum(e.get("cost", 0.0) or 0.0 for e in entries), 6),
    )


def fresh_env(tag):
    home = Path(tempfile.mkdtemp(prefix=f"p6-{tag}-"))
    data = Path(tempfile.mkdtemp(prefix=f"p6d-{tag}-"))
    os.environ["TOKDASH_DATA_DIR"] = str(data)
    os.environ["TOKDASH_USAGE_DB"] = "0"
    import pathlib
    pathlib.Path.home = classmethod(lambda cls: home)
    return home


def codex_totals(lines_by_file, shuffle_seed=None):
    home = fresh_env("codex")
    d = home / ".codex" / "sessions"
    d.mkdir(parents=True)
    for i, lines in enumerate(lines_by_file):
        (d / f"rollout-{i}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    from tokdash.pricing import PricingDatabase
    from tokdash.sources.coding_tools import CodexParser
    p = CodexParser(PricingDatabase())
    sigs = list(p._file_signatures())
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(sigs)
        p._file_signatures = lambda: tuple(sigs)
    return totals(p._parse_all())


def main():
    lines = codex_lines(200)

    base = codex_totals([lines])
    print("P1/P2 codex base:", base)
    for seed in (1, 2, 3):
        t = codex_totals([lines], shuffle_seed=seed)
        assert t == base, f"order dependence! seed={seed}: {t} != {base}"
    print("P2 order independence: OK (3 seeds)")

    # P1 idempotence: parse twice from same process/cache-busted instances
    home = fresh_env("idem")
    d = home / ".codex" / "sessions"
    d.mkdir(parents=True)
    (d / "r.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    from tokdash.pricing import PricingDatabase
    from tokdash.sources.coding_tools import CodexParser
    p1 = CodexParser(PricingDatabase())
    t1 = totals(p1._parse_all())
    p2 = CodexParser(PricingDatabase())
    t2 = totals(p2._parse_all())
    assert t1 == t2 == base, f"idempotence broken: {t1} vs {t2} vs {base}"
    print("P1 idempotence: OK")

    # P3 split: one file -> three files.  Codex keys are session-scoped stable
    # hashes, so split files must dedup to the same total ONLY if the stable
    # key survives the split (the session_meta/turn_context headers stay in
    # file 0; parts 1,2 lose the model signal -> placeholder model logic).
    third = len(lines) // 3
    split = codex_totals([lines[:third], lines[third:2 * third], lines[2 * third:]])
    print("P3 split-3 totals:", split)
    if split != base:
        print(f"  ^^ DIVERGENCE from base: delta_in={split['inp']-base['inp']}, "
              f"delta_n={split['n']-base['n']}, delta_cost={round(split['cost']-base['cost'],4)}")

    # P4 duplicate copy in second dir (archived_sessions overlap)
    home = fresh_env("dup")
    sessions_d = home / ".codex" / "sessions"
    archived_d = home / ".codex" / "archived_sessions"
    sessions_d.mkdir(parents=True)
    archived_d.mkdir(parents=True)
    (sessions_d / "r.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (archived_d / "r.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    p = CodexParser(PricingDatabase())
    dup = totals(p._parse_all())
    print("P4 duplicate in archived:", dup)
    print("  same as base?", dup == base)


if __name__ == "__main__":
    main()
