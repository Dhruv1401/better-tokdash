"""EXP-18: DSH (DeepSeek Harness) log decoder under corruption / duplicates.

Attack surface: sources/dsh_log.py decode_dsh_session_file (multi-frame zstd,
read_across_frames=True) and its two consumers (DSHParser for Overview/usage,
sessions._parse_dsh_session_file for the Sessions view).

Scenarios:
  S1  healthy 2-frame zstd -> baseline (sanity)
  S2  one corrupted byte in an INTERIOR frame -> raise, partial, or garbage?
      (maintainer tests only cover a torn FINAL frame)
  S3  properly torn final frame (their test) -> complete rows kept (confirm)
  S4  file truncated at an interior frame boundary -> graceful prefix?
  S5  same session id in TWO physical files with DIFFERENT usage for the same
      (turn, step): which copy does Overview bill, which does Sessions show?
  S6  non-adjacent duplicate (turn, step) in one file: fold appends twice ->
      entry_id collision. Overview keeps last; Sessions keeps first?
  S7  do skip_reason outcomes (unsupported version, corrupt frame) emit ANY
      diagnostic while the parser scans a whole source?
  S8  10**25 tokens (F-001 class) through the DSH path into the store.
  S9  file that HAD stored rows becomes corrupt -> do stored rows survive?
  S10 realistic mid-life version bump: 3 healthy files + 1 that flips to an
      unsupported version -> how much of the source silently vanishes?

Run from tokdash/: PYTHONPATH=src python ../output/exp18_dsh_corruption.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

home = Path(tempfile.mkdtemp(prefix="exp18-"))
data = Path(tempfile.mkdtemp(prefix="exp18d-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = "0"  # parser-only unless a scenario opts in
os.environ["TOKDASH_COMPUTE_CONCURRENCY"] = "1"
import pathlib

pathlib.Path.home = classmethod(lambda cls: home)

DSH_HOME = home / ".dsh"
os.environ["DSH_HOME"] = str(DSH_HOME)

from zstandard import ZstdCompressor

from tokdash.pricing import PricingDatabase
from tokdash.sources.coding_tools import BaseParser, DSHParser, _sig_cache
from tokdash.sources.dsh_log import decode_dsh_session_file, dsh_entry_id, fold_dsh_usage_samples

TS = 1786735098528


def header(session_id="session-abc", version=0):
    return {"type": "session", "version": version, "id": session_id, "createdAt": TS, "cwd": "/p"}


def event(seq, etype, data, time_ms=None):
    return {"type": etype, "seq": seq, "time": TS + 1000 * seq if time_ms is None else time_ms, "data": data}


def msg(seq, turn, step, inp, outp):
    return event(seq, "assistant/message", {
        "turn": turn, "step": step,
        "message": {"id": f"a{seq}", "role": "assistant",
                    "content": [{"type": "text", "text": "x"}],
                    "source": {"kind": "model", "provider": "deepseek", "model": "deepseek-v4-flash"}},
        "usage": {"inputTokens": inp, "outputTokens": outp},
    })


def write_zstd_frames(path: Path, frames: list[bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(frames))
    return path


def frame(rows) -> bytes:
    comp = ZstdCompressor()
    return comp.compress(b"".join((json.dumps(r) + "\n").encode("utf-8") for r in rows))


def fresh_parser():
    _sig_cache.clear()
    BaseParser._entry_cache.clear()
    return DSHParser(PricingDatabase())


def collect_entries(session_path: Path, session_id="session-abc"):
    sigs = ((str(session_path), 1, session_path.stat().st_size),)
    parser = fresh_parser()
    for sig in sigs:
        decoded = decode_dsh_session_file(Path(sig[0]))
        if decoded.skip_reason is not None or decoded.header is None:
            return decoded, []
        by_id = {}
        for s in fold_dsh_usage_samples(decoded.header, decoded.events):
            by_id[dsh_entry_id(session_id, s["turn"], s["step"])] = s
        return decoded, list(by_id.values())
    return None, []


SEP = "=" * 78

# --- S1: baseline -------------------------------------------------------------
print(SEP)
print("S1: healthy two-frame zstd file (baseline)")
p1 = DSH_HOME / "sessions" / "proj" / "s1" / "session.jsonl.zstd"
write_zstd_frames(p1, [frame([header()]), frame([msg(1, 0, 0, 100, 10), msg(2, 1, 0, 200, 20)])])
dec, entries = collect_entries(p1)
print("  skip_reason:", dec.skip_reason, "| entries:", [(e['turn'], e['step'], e['input'], e['output']) for e in entries])

# --- S2: corrupt interior frame -----------------------------------------------
print(SEP)
print("S2: corrupt ONE byte inside the INTERIOR of frame 1 (not the tail)")
raw = bytearray(p1.read_bytes())
raw[len(raw) // 4] ^= 0xFF
p2 = DSH_HOME / "sessions" / "proj" / "s2" / "session.jsonl.zstd"
p2.parent.mkdir(parents=True, exist_ok=True)
p2.write_bytes(bytes(raw))
dec, entries = collect_entries(p2)
if dec is not None:
    print("  decode outcome: skip_reason =", dec.skip_reason, "| events survived:", len(dec.events))
else:
    print("  decode outcome: EXCEPTION", entries)
print("  -> parser-visible entries:", len(entries))

print(SEP)
print("S2b: corrupt a byte INSIDE frame 2 (final frame interior)")
raw = bytearray(p1.read_bytes())
raw[int(len(raw) * 0.75)] ^= 0xFF
p2b = DSH_HOME / "sessions" / "proj" / "s2b" / "session.jsonl.zstd"
p2b.parent.mkdir(parents=True, exist_ok=True)
p2b.write_bytes(bytes(raw))
dec, entries = collect_entries(p2b)
if dec is not None:
    print("  decode outcome: skip_reason =", dec.skip_reason, "| events survived:", len(dec.events))
else:
    print("  decode outcome: EXCEPTION", entries)

# --- S3: torn final frame (maintainer-covered) ---------------------------------
print(SEP)
print("S3: torn FINAL frame (maintainer-covered; confirm)")
comp = ZstdCompressor()
f1 = frame([header(), msg(1, 0, 0, 100, 10)])
torn = comp.compress(b'{"type": "assistant/message", "seq": 2')[:12]
p3 = DSH_HOME / "sessions" / "proj" / "s3" / "session.jsonl.zstd"
p3.parent.mkdir(parents=True, exist_ok=True)
p3.write_bytes(f1 + torn)
dec, entries = collect_entries(p3)
print("  skip_reason:", dec.skip_reason, "| entries:", [(e['turn'], e['input'], e['output']) for e in entries])

# --- S4: truncated at frame boundary --------------------------------------------
print(SEP)
print("S4: file TRUNCATED exactly at an interior frame boundary (frame 2 gone mid-batch)")
p4 = DSH_HOME / "sessions" / "proj" / "s4" / "session.jsonl.zstd"
p4.parent.mkdir(parents=True, exist_ok=True)
p4.write_bytes(f1)  # only frame 1
dec, entries = collect_entries(p4)
print("  skip_reason:", dec.skip_reason, "| entries:", [(e['input'], e['output']) for e in entries])

# --- S5/S6: isolated home -------------------------------------------------------
print(SEP)
print("S5: SAME session id in two physical files, DIFFERENT usage for same (turn,step)")
DSH_HOME2 = home / ".dsh2"
os.environ["DSH_HOME"] = str(DSH_HOME2)
p5a = DSH_HOME2 / "sessions" / "projA" / "s5" / "session.jsonl"       # older partial copy
p5a.parent.mkdir(parents=True, exist_ok=True)
p5a.write_text("".join(json.dumps(r) + "\n" for r in [header("s5"), msg(1, 0, 0, 100, 10)]), encoding="utf-8")
p5b = DSH_HOME2 / "sessions" / "projB" / "s5" / "session.jsonl.zstd"  # newer copy, DIVERGENT (0,0) usage
p5b.parent.mkdir(parents=True, exist_ok=True)
write_zstd_frames(p5b, [frame([header("s5")]), frame([msg(1, 0, 0, 999, 99)])])

parser = fresh_parser()
all_entries = [e for e in parser.collect(None, None) if str(e['entry_id']).startswith('dsh:s5')]
print("  Overview/usage path: entries:", [(e['entry_id'], e['input'], e['output']) for e in all_entries])
from tokdash import sessions as sess_mod
sess = sess_mod._load_dsh_sessions(sess_mod._dsh_session_signatures(), ())
s = sess.get("s5", {})
turns = [(t.get("_event_key"), t.get("tokens_in"), t.get("tokens_out")) for t in s.get("turns", [])]
print("  Sessions path: s5 turns:", turns)

print(SEP)
print("S6: non-adjacent duplicate (turn,step) in ONE file")
p6 = DSH_HOME2 / "sessions" / "proj" / "s6" / "session.jsonl"
p6.parent.mkdir(parents=True, exist_ok=True)
rows = [header("s6"),
        msg(1, 0, 0, 100, 10),   # (0,0) attempt A
        msg(2, 1, 0, 300, 30),   # (1,0) different step
        msg(3, 0, 0, 111, 22)]   # (0,0) again, NON-adjacent -> fold appends, not replaces
p6.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
parser = fresh_parser()
entries6 = [e for e in parser.collect(None, None) if str(e['entry_id']).startswith('dsh:s6')]
print("  Overview/usage entries:", [(e['entry_id'], e['input'], e['output']) for e in entries6])
sess6 = sess_mod._load_dsh_sessions(sess_mod._dsh_session_signatures(), ())
s = sess6.get("s6", {})
turns = [(t.get("_event_key"), t.get("tokens_in"), t.get("tokens_out")) for t in s.get("turns", [])]
print("  Sessions turns:", turns)

# --- S7: diagnostics capture ----------------------------------------------------
print(SEP)
print("S7: diagnostics capture — skip_reason outcomes emit ANY log during a full scan?")
records = []


class Cap(logging.Handler):
    def emit(self, r):
        records.append((r.name, r.levelname, r.getMessage()))


root = logging.getLogger()
root.addHandler(Cap())
for name in ("tokdash", "tokdash.sources", "tokdash.sources.coding_tools", "tokdash.sources.dsh_log", "tokdash.sessions"):
    lg = logging.getLogger(name)
    lg.addHandler(Cap())
    lg.setLevel(logging.DEBUG)

pv = DSH_HOME2 / "sessions" / "proj" / "s7v" / "session.jsonl.zstd"
write_zstd_frames(pv, [frame([header("s7v", version=99)]), frame([msg(1, 0, 0, 100, 10)])])
pc = DSH_HOME2 / "sessions" / "proj" / "s7c" / "session.jsonl.zstd"
raw = bytearray(frame([header("s7c"), msg(1, 0, 0, 100, 10)]))
raw[len(raw) // 2] ^= 0xFF
pc.parent.mkdir(parents=True, exist_ok=True)
pc.write_bytes(bytes(raw))
records.clear()
parser = fresh_parser()
n = len(parser.collect(None, None))
print(f"  whole-source scan with 1 unsupported-version + 1 corrupt-frame file -> {n} usable entries")
print(f"  log records emitted anywhere in tokdash.*: {len(records)}")
for r in records[:10]:
    print("   ", r)

# --- S8: F-001 class through DSH -------------------------------------------------
print(SEP)
print("S8: 10**25 tokens through DSH into the persistent store (F-001 class)")
os.environ["TOKDASH_USAGE_DB"] = str(data / "usage8.db")
p8 = DSH_HOME2 / "sessions" / "proj" / "s8" / "session.jsonl"
p8.parent.mkdir(parents=True, exist_ok=True)
p8.write_text("".join(json.dumps(r) + "\n" for r in [header("s8"), msg(1, 0, 0, 10**25, 5)]), encoding="utf-8")
from tokdash.compute import _collect_parser_file
from tokdash.usage_store import UsageEntryStore
store = UsageEntryStore()
parser = fresh_parser()
try:
    files = tuple(f for f in parser._file_signatures() if f[0] == str(p8))
    sig = parser.persistent_parser_signature()
    store.sync_files("dsh", files, parser=sig, pricing_identity=(),
                     parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                     cross_file_stable_keys=False)
    print("  sync_files: NO ERROR raised?!")
except Exception as e:
    print(f"  sync_files raised: {type(e).__name__}: {e}")

# --- S9: corrupt file that had stored rows ---------------------------------------
print(SEP)
print("S9: corrupt file that HAD stored rows -> do stored rows survive the resync?")
os.environ["TOKDASH_USAGE_DB"] = str(data / "usage9.db")
DSH_HOME3 = home / ".dsh3"
os.environ["DSH_HOME"] = str(DSH_HOME3)
p9 = DSH_HOME3 / "sessions" / "proj" / "s9" / "session.jsonl.zstd"
write_zstd_frames(p9, [frame([header("s9")]), frame([msg(1, 0, 0, 500, 50)])])
store = UsageEntryStore()
parser = fresh_parser()
files = tuple(f for f in parser._file_signatures() if f[0] == str(p9))
sig = parser.persistent_parser_signature()
store.sync_files("dsh", files, parser=sig, pricing_identity=(),
                 parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                 cross_file_stable_keys=False)
rows_after_healthy = len(store.query_entries(sources=["dsh"]))
# corrupt the same file in place; bump mtime so the signature changes -> resync
raw = bytearray(p9.read_bytes())
raw[len(raw) // 2] ^= 0xFF
p9.write_bytes(bytes(raw))
os.utime(p9, ns=(int(2e9), int(2e9)))
parser = fresh_parser()
files = tuple(f for f in parser._file_signatures() if f[0] == str(p9))
store.sync_files("dsh", files, parser=sig, pricing_identity=(),
                 parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                 cross_file_stable_keys=False)
rows_after_corrupt = len(store.query_entries(sources=["dsh"]))
print(f"  rows stored while healthy: {rows_after_healthy}; after the file corrupts: {rows_after_corrupt}")

# --- S10: realistic mid-life version bump across a whole source -------------------
print(SEP)
print("S10: 4 healthy files (100 tok each), then ONE flips to unsupported version")
os.environ["TOKDASH_USAGE_DB"] = str(data / "usage10.db")
paths = []
for i in range(4):
    pi = DSH_HOME3 / "sessions" / "proj" / f"s10-{i}" / "session.jsonl.zstd"
    write_zstd_frames(pi, [frame([header(f"s10-{i}")]), frame([msg(1, 0, 0, 100, 10)])])
    paths.append(pi)
store = UsageEntryStore()
parser = fresh_parser()
files = parser._file_signatures()
sig = parser.persistent_parser_signature()
store.sync_files("dsh", files, parser=sig, pricing_identity=(),
                 parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                 cross_file_stable_keys=False)
before = len(store.query_entries(sources=["dsh"]))
# dsh "upgrades" one session to a hypothetical version 1 format
pflip = DSH_HOME3 / "sessions" / "proj" / "s10-2" / "session.jsonl.zstd"
write_zstd_frames(pflip, [frame([header("s10-2", version=1)]), frame([msg(1, 0, 0, 100, 10)])])
os.utime(pflip, ns=(int(3e9), int(3e9)))
parser = fresh_parser()
files = parser._file_signatures()
store.sync_files("dsh", files, parser=sig, pricing_identity=(),
                 parse_file_entries=lambda fs, context=None: _collect_parser_file(parser, fs),
                 cross_file_stable_keys=False)
after = len(store.query_entries(sources=["dsh"]))
print(f"  store rows before: {before}; after one file bumps version: {after}")
print(SEP)
print("done.")
