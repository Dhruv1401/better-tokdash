"""EXP-10: concurrent config.json writers -> lost update.

set_quota_consent / set_poll_interval_minutes / set_quota_enabled each do
read-modify-write with no lock. Two writers racing (dashboard POST vs
background poller vs CLI) lose one update. tmp+replace makes the FILE
atomic, but the READ-MODIFY-WRITE is not.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

data = Path(tempfile.mkdtemp(prefix="exp10-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)

from tokdash.sources.quota import config as qc

results = {"consent_lost": 0, "interval_lost": 0}
N = 25

barrier = threading.Barrier(2)


def writer_consent():
    barrier.wait()
    for i in range(N):
        qc.set_quota_consent({"claude_api": (i % 2 == 0)})


def writer_interval():
    barrier.wait()
    for i in range(N):
        qc.set_poll_interval_minutes(15 if i % 2 == 0 else 30)


t1 = threading.Thread(target=writer_consent)
t2 = threading.Thread(target=writer_interval)
t1.start(); t2.start(); t1.join(); t2.join()

final = qc._raw_quota()
print("final quota block:", final)

# A correct serialized RMW ends with BOTH keys having deterministic values;
# a lost update shows an interval value that contradicts the last interval
# write or a consent that contradicts the last consent write. Since thread
# scheduling varies, we instead check for INTERLEAVING damage: the file must
# contain a poll_interval_minutes (written by t2) AND materialized consent
# keys (written by t1). If either writer's final state is missing, the RMW
# lost an update.
missing = []
if "poll_interval_minutes" not in final:
    missing.append("poll_interval_minutes (t2's last write lost)")
if "claude_api" not in final:
    missing.append("claude_api (t1's writes lost)")
print("lost-update evidence:", missing if missing else "none in this run (racy)")
# Statistical: count how often the final interval is not the last write by t2.
# Because both threads write N times, the final value should be one of the two
# legal choices; a missing key is the hard proof of loss.
sys.exit(1 if missing else 0)
