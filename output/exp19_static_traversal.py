"""EXP-19: Static mount + BasePathMiddleware traversal probe (raw ASGI scopes).

The mount comment says traversal is "still rejected via abspath" and
follow_symlink=True is deliberate (uv-cache symlinks). Empirical check of both,
plus BasePathMiddleware prefix-strip edge cases. Hand-built ASGI scopes avoid
httpx's client-side URL normalization, which is what a curl --path-as-is or a
raw socket request would reach the server as.

Run from tokdash/: PYTHONPATH=src python ../output/exp19_static_traversal.py
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))

home = Path(tempfile.mkdtemp(prefix="exp19-"))
data = Path(tempfile.mkdtemp(prefix="exp19d-"))
os.environ["TOKDASH_DATA_DIR"] = str(data)
os.environ["TOKDASH_USAGE_DB"] = "0"
import pathlib

pathlib.Path.home = classmethod(lambda cls: home)

from tokdash import api as api_mod

app = api_mod.app


async def raw_request(path: str, method: str = "GET", headers: list[tuple[bytes, bytes]] | None = None):
    """Drive the ASGI app directly with a hand-built scope."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("127.0.0.1", 80),
        "client": ("127.0.0.1", 12345),
        "headers": headers or [(b"host", b"127.0.0.1:8080")],
    }
    status_holder = {}
    body = io.BytesIO()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status_holder["status"] = message["status"]
        elif message["type"] == "http.response.body":
            body.write(message.get("body", b""))

    await app(scope, receive, send)
    return status_holder.get("status"), body.getvalue()


PROBES = [
    # (label, path)
    ("baseline index", "/static/index.html"),
    ("dotdot up one", "/static/../pyproject.toml"),
    ("dotdot up two", "/static/../../pyproject.toml"),
    ("dotdot up three", "/static/../../../pyproject.toml"),
    ("dotdot to compute.py", "/static/../../tokdash/compute.py"),
    ("backslash traversal (raw)", "/static/..\\..\\pyproject.toml"),
    ("double slash abs win", "/static//C:/Windows/win.ini"),
    ("UNC path", "/static//\\\\?\\C:\\Windows\\win.ini"),
    ("encoded dotdot %2e%2e", "/static/%2e%2e/%2e%2e/pyproject.toml"),
    ("null byte", "/static/index.html%00.txt"),
    ("trailing dots", "/static/.../pyproject.toml"),
    ("dot-segment inside name", "/static/./index.html"),
    ("symlink escape probe", "/static/__exp19_link__/../pyproject.toml"),
]

print("=" * 78)
print("PART A: StaticFiles traversal probes (raw ASGI scopes)")
asyncio.set_event_loop(asyncio.new_event_loop())
loop = asyncio.get_event_loop()
for label, path in PROBES:
    try:
        status, body = loop.run_until_complete(raw_request(path))
        leak = b"tokdash" in body.lower() or b"[project]" in body[:4000] or b"[build-system]" in body[:4000]
        print(f"  {label:28s} {path:45s} -> {status}  len={len(body)} leak-looking={leak}")
    except Exception as e:
        print(f"  {label:28s} {path:45s} -> EXCEPTION {type(e).__name__}: {e}")

print("=" * 78)
print("PART A2: real symlink inside the static dir pointing OUTSIDE (follow_symlink=True)")
static_dir = api_mod.STATIC_DIR
outside = data / "outside-secret.txt"
outside.write_text("TOPSECRET-OUTSIDE", encoding="utf-8")
link = static_dir / "__exp19_link__"
made = False
try:
    if hasattr(os, "symlink"):
        os.symlink(data, link, target_is_directory=True)
        made = True
except OSError as e:
    print("  (symlink unavailable on this platform/privilege:", e, ")")
if made:
    status, body = loop.run_until_complete(raw_request("/static/__exp19_link__/outside-secret.txt"))
    print(f"  read through symlink into data dir -> {status} body={body[:60]!r}")
    (static_dir / "__exp19_link__").unlink()
else:
    # Windows without privilege: junction via os functions not available -> note only
    print("  skipped (no symlink support in this environment)")

print("=" * 78)
print("PART B: BasePathMiddleware edge cases (write-guard interplay)")
# api/usage needs a synced compute; we only care about STATUS distinctness here.
BP = [
    ("plain", "/api/usage"),
    ("base path", "/tokdash/api/usage"),
    ("base path case-mismatch", "/TOKDASH/api/usage"),
    ("double slash prefix", "//tokdash/api/usage"),
    ("prefix without slash", "/tokdashapi/usage"),
    ("dotdot inside base", "/tokdash/../api/usage"),
    ("encoded dotdot in base", "/tokdash/%2e%2e/api/usage"),
    ("base path traversal out", "/tokdash/../../api/usage"),
    ("trailing only", "/tokdash/"),
    ("exact", "/tokdash"),
]
for label, path in BP:
    try:
        status, body = loop.run_until_complete(raw_request(path))
        print(f"  {label:26s} {path:38s} -> {status} len={len(body)}")
    except Exception as e:
        print(f"  {label:26s} {path:38s} -> EXCEPTION {type(e).__name__}: {e}")

print("=" * 78)
print("PART C: same dotdot probes against /api/session (documented 'no traversal found')")
for p in ["/api/session/..%2f..%2fpyproject.toml", "/api/session/%2e%2e%2fcompute.py",
          "/api/session/..\\..\\pyproject.toml", "/api/session/C:/Windows/win.ini"]:
    try:
        status, body = loop.run_until_complete(raw_request(p))
        print(f"  {p:55s} -> {status} len={len(body)} body[:80]={body[:80]!r}")
    except Exception as e:
        print(f"  {p:55s} -> EXCEPTION {type(e).__name__}: {e}")
loop.close()
print("done.")
