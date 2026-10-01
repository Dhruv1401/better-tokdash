"""EXP-12: live API probes via TestClient.

- error detail leakage (500 detail=str(e) with paths)
- invalid/oversized params (period=…, session_id traversal, facets)
- cache behavior: same request twice, force_refresh
- /health and Host handling
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

home = Path(tempfile.mkdtemp(prefix="exp12-"))
data = Path(tempfile.mkdtemp(prefix="exp12d-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = "0"
import pathlib
pathlib.Path.home = classmethod(lambda cls: home)

# seed a couple of codex sessions so the sessions endpoints have material
from datetime import datetime, timezone
d = home / ".codex" / "sessions"
d.mkdir(parents=True)
t0 = 1_770_000_000_000


def iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


lines = [json.dumps({"timestamp": iso(t0 - 1), "type": "session_meta", "payload": {"id": "sess1"}}),
         json.dumps({"timestamp": iso(t0 - 1), "type": "turn_context", "payload": {"model": "gpt-5.3"}})]
for i in range(5):
    info = {"id": f"u{i}",
            "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 10,
                                  "output_tokens": 50, "reasoning_output_tokens": 3},
            "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 10,
                                 "output_tokens": 50, "reasoning_output_tokens": 3}}
    lines.append(json.dumps({"timestamp": iso(t0 + i * 1000), "type": "event_msg",
                             "payload": {"type": "token_count", "info": info}}))
(d / "rollout-x.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

from fastapi.testclient import TestClient
from tokdash.api import app

client = TestClient(app, raise_server_exceptions=False)

print("== /health ==")
r = client.get("/health")
print(r.status_code, r.json())

print("\n== /api/usage bad period ==")
r = client.get("/api/usage?period=zzz")
print(r.status_code, str(r.json())[:160])

print("\n== /api/usage inverted range ==")
r = client.get("/api/usage?date_from=2026-05-01&date_to=2026-04-01")
print(r.status_code, str(r.json())[:200])

print("\n== /api/session with traversal-ish id ==")
r = client.get("/api/session?tool=codex&session_id=..%2F..%2F..%2Fwindows")
print(r.status_code, str(r.json())[:300])

print("\n== /api/session nonexistent (404 detail) ==")
r = client.get("/api/session?tool=codex&session_id=nope")
print(r.status_code, str(r.json())[:300])

print("\n== /api/insights bad facets ==")
r = client.get("/api/insights?facets=hourly,bogus")
print(r.status_code, str(r.json())[:200])

print("\n== /api/insights huge period ==")
r = client.get("/api/insights?period=" + "9" * 8)
print(r.status_code, str(r.json())[:120])

print("\n== cache: /api/stats twice ==")
import time
r1 = client.get("/api/stats?period=week")
t = time.perf_counter(); r2 = client.get("/api/stats?period=week"); dt = (time.perf_counter() - t) * 1000
print("first:", r1.status_code, "second:", r2.status_code, f"{dt:.1f} ms")

print("\n== POST without token (write guard) ==")
r = client.post("/api/update-check/consent", headers={"Host": "127.0.0.1:55423"})
print(r.status_code, str(r.json())[:160])

print("\n== CSRF token fetch withSpoofed Host ==")
r = client.get("/api/csrf-token", headers={"Host": "evil.example:55423"})
print(r.status_code, str(r.json())[:80])
r = client.get("/api/csrf-token", headers={"Host": "127.0.0.1:55423"})
print(r.status_code, "token-issued" if r.status_code == 200 else r.json())
