"""EXP-10b: quantify Windows replace crash in concurrent config writes."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

data = Path(tempfile.mkdtemp(prefix="exp10b-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)

from tokdash.sources.quota import config as qc

errors: list[str] = []
N_THREADS = 4
N_WRITES = 20
barrier = threading.Barrier(N_THREADS)


def writer(kind: int):
    barrier.wait()
    for i in range(N_WRITES):
        try:
            if kind % 2 == 0:
                qc.set_quota_consent({"claude_api": (i % 2 == 0)})
            else:
                qc.set_poll_interval_minutes(15 if i % 2 == 0 else 30)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")


threads = [threading.Thread(target=writer, args=(k,)) for k in range(N_THREADS)]
t0 = time.perf_counter()
for t in threads:
    t.start()
for t in threads:
    t.join()
dt = time.perf_counter() - t0

total = N_THREADS * N_WRITES
print(f"threads={N_THREADS} writes_each={N_WRITES} total={total} in {dt:.2f}s")
print(f"errors: {len(errors)} ({100*len(errors)/total:.1f}%)")
for e in errors[:5]:
    print("  ", e)
print("final keys:", sorted(qc._raw_quota().keys()) == sorted(
    ["antigravity_api", "claude_api", "codex_api", "commandcode_api", "credential_scan",
     "grok_api", "kimi_api", "minimax_api", "opencode_go_api", "poll_interval_minutes", "zai_api"]))
