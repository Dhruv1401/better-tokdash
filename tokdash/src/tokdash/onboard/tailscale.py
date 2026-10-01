"""Wizard-run Tailscale Serve exposure (plan §8.3, §12.1).

This is the ONLY path that exposes Tokdash beyond loopback, and it is interactive and
explicitly confirmed — ``--auto`` never runs it (it only prints the command). The serve and
teardown commands are built from the same parameters so they are a guaranteed matched pair,
and teardown is the **exact targeted ``off``** — never ``tailscale serve reset`` (which would
wipe unrelated Serve config). setup records the teardown in the manifest so ``uninstall``
reverts exactly what was run.

Note: `tailscale serve` syntax has shifted across Tailscale versions. The commands here
target the modern (`--bg --https=443 <target>`) form; verify against your installed
Tailscale. The teardown is the matched inverse regardless of target shape.
"""
from __future__ import annotations

import getpass
import re
import subprocess
from typing import Any, Dict, List

HTTPS_PORT = 443
SERVE_PATH = "/tokdash"


def _normalize_path(path: str | None) -> str:
    raw = (path or "").strip()
    if not raw or raw == "/":
        return "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    return raw.rstrip("/")


def serve_command(local_port: int, https_port: int = HTTPS_PORT, path: str = SERVE_PATH) -> List[str]:
    serve_path = _normalize_path(path)
    return [
        "tailscale",
        "serve",
        "--bg",
        f"--https={https_port}",
        f"--set-path={serve_path}",
        f"http://127.0.0.1:{local_port}",
    ]


def teardown_command(https_port: int = HTTPS_PORT, path: str = SERVE_PATH) -> List[str]:
    # Targeted off for exactly this https handler — NEVER `tailscale serve reset`.
    return ["tailscale", "serve", f"--https={https_port}", f"--set-path={_normalize_path(path)}", "off"]


def operator_command(user: str | None = None) -> List[str]:
    """One-time command that lets the current user manage Tailscale Serve without sudo."""
    return ["sudo", "tailscale", "set", f"--operator={user or getpass.getuser()}"]


def manifest_block(
    local_port: int,
    https_port: int = HTTPS_PORT,
    url: str | None = None,
    path: str = SERVE_PATH,
) -> Dict[str, Any]:
    serve_path = _normalize_path(path)
    return {
        "configured_by_setup": True,
        "target": f"https={https_port}{serve_path} -> http://127.0.0.1:{local_port}",
        "path": serve_path,
        "url": url,
        "teardown_command": teardown_command(https_port, serve_path),
    }


def parse_serve_url(status_text: str, local_port: int, path: str = SERVE_PATH) -> str | None:
    """Extract the MagicDNS HTTPS URL for the Serve target from `tailscale serve status`."""
    target = f"http://127.0.0.1:{local_port}"
    serve_path = _normalize_path(path)

    def _scoped(url: str) -> str:
        # We configured ``serve_path``, so the public URL is always host + serve_path. Append
        # it unless the parsed URL already carries it — never advertise the bare tailnet host
        # root (that would imply other services are reachable at the root).
        base = url.rstrip("/")
        if serve_path != "/" and not base.endswith(serve_path):
            return base + serve_path
        return base

    current_url: str | None = None
    first_url: str | None = None
    for raw in status_text.splitlines():
        line = raw.strip()
        match = re.search(r"https://[^\s()]+", line)
        if match:
            current_url = match.group(0).rstrip("/")
            first_url = first_url or current_url
        # The target line is authoritative: attach our serve path to the host URL in scope
        # (this line's own URL, else the most recent parent line's URL).
        if target in line and current_url:
            return _scoped(current_url)
    # No target line resolved (unusual status layout); still scope the first host URL to our
    # serve path rather than returning the host root.
    return _scoped(first_url) if first_url else None


def serve_status() -> Dict[str, Any]:
    cmd = ["tailscale", "serve", "status"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"ok": False, "command": cmd, "output": "", "error": str(exc)}
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return {"ok": False, "command": cmd, "output": output, "error": output}
    return {"ok": True, "command": cmd, "output": output, "error": None}


def run_serve(local_port: int, https_port: int = HTTPS_PORT, path: str = SERVE_PATH) -> Dict[str, Any]:
    """Run `tailscale serve`; return ``{ok, command, block, error}``.

    On success ``block`` is the manifest ``tailscale_serve`` payload to record so uninstall
    can revert it. Never raises.
    """
    cmd = serve_command(local_port, https_port, path)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"ok": False, "command": cmd, "block": None, "error": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "command": cmd, "block": None, "error": (proc.stderr or proc.stdout or "").strip()}
    status = serve_status()
    combined_output = "\n".join(s for s in (proc.stdout, proc.stderr, status.get("output", "")) if s)
    url = parse_serve_url(combined_output, local_port, path) if status["ok"] else None
    return {
        "ok": True,
        "command": cmd,
        "block": manifest_block(local_port, https_port, url=url, path=path),
        "url": url,
        "status": status,
        "error": None,
    }


def needs_operator_permission(error: str | None) -> bool:
    """Whether a `tailscale serve` failure looks like a missing operator permission."""
    text = (error or "").lower()
    return "access denied" in text and ("serve config" in text or "operator" in text)


def grant_operator(user: str | None = None) -> Dict[str, Any]:
    """Run the one-time operator grant interactively; never raises."""
    cmd = operator_command(user)
    try:
        proc = subprocess.run(cmd, timeout=120)
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"ok": False, "command": cmd, "error": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "command": cmd, "error": f"exit {proc.returncode}"}
    return {"ok": True, "command": cmd, "error": None}
