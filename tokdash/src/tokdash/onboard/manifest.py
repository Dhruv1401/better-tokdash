"""The revert manifest (``<data_dir>/install.json``).

setup *writes* it, ``doctor``/``update``/``uninstall`` *read* it, and ``/api/version``
peeks at ``install_method``. It is the single record of exactly what setup created, so
``uninstall`` reverts only setup-owned items and never guesses (plan §13, §21).

Reads are best-effort and never raise: a missing or corrupt manifest must not break
version reporting or a conservative uninstall fallback.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import paths

SCHEMA = 1


def new_marker_id() -> str:
    """A random id stamped into both the unit (comment) and the manifest.

    Lets uninstall confirm "this exact unit is the one setup wrote" rather than
    trusting the filename alone (the repo documents *manual* tokdash.service installs).
    """
    return secrets.token_hex(8)


def marker_token(marker_id: str) -> str:
    """The ``X-Tokdash-Managed`` token recorded in the manifest and emitted in the unit."""
    return f"X-Tokdash-Managed id={marker_id}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_manifest(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return the manifest dict, or ``None`` if absent/unreadable/not an object."""
    p = path or paths.manifest_path()
    try:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        return None
    return None


def write_manifest(data: Dict[str, Any], path: Optional[Path] = None) -> Path:
    """Atomically write the manifest, creating the data dir if needed."""
    p = path or paths.manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        # Don't leave a half-written ``install.json.tmp`` sidecar behind on failure.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return p


def remove_manifest(path: Optional[Path] = None) -> bool:
    """Delete the manifest; return whether a file was removed. Idempotent."""
    p = path or paths.manifest_path()
    try:
        if p.is_file():
            p.unlink()
            return True
    except OSError:
        pass
    return False


def build_manifest(
    *,
    install_method: str,
    runtime_kind: str,
    runtime_command: list[str],
    runtime_owned_by_setup: bool,
    python_path: str,
    python_version: str,
    service: Optional[Dict[str, Any]],
    runtime_marker: Optional[str],
    data_dir: str,
    bind: str,
    port: int,
) -> Dict[str, Any]:
    """Assemble the manifest payload in the documented shape (plan §13)."""
    return {
        "schema": SCHEMA,
        "install_method": install_method,
        "runtime_kind": runtime_kind,
        "runtime_command": list(runtime_command),
        "runtime_owned_by_setup": bool(runtime_owned_by_setup),
        "python_path": python_path,
        "python_version": python_version,
        "service": service,
        "runtime_marker": runtime_marker,
        # Phase 1 never configures Tailscale; the block is always the false/null shape
        # so a future Phase-3 wizard can populate it and uninstall already knows the key.
        "tailscale_serve": {"configured_by_setup": False, "target": None, "teardown_command": None},
        "data_dir": data_dir,
        "bind": bind,
        "port": port,
        "created_at": utc_now_iso(),
    }
