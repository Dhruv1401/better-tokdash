"""macOS launchd *user* LaunchAgent generation and lifecycle (plan §10.3).

The macOS analogue of :mod:`.systemd`. A LaunchAgent plist at
``~/Library/LaunchAgents/com.tokdash.tokdash.plist`` carries the same ownership marker so
``uninstall`` can prove setup wrote it before removing it (§12.3). All lifecycle calls use
per-user ``launchctl`` only — never ``sudo``, never a system (``/Library``) agent.

Unlike systemd's ``ExecStart`` (a single whitespace-split line), launchd's
``ProgramArguments`` is an array of separate strings, so paths with spaces need no special
quoting — only XML escaping.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from . import manifest, paths

LABEL = "com.tokdash.tokdash"
MARKER_COMMENT = "Managed-by: tokdash-setup"
LIFECYCLE_TIMEOUT = 120


def _uid() -> int:
    # getuid exists on macOS (and Linux). Guarded for the (unsupported) Windows case.
    return os.getuid() if hasattr(os, "getuid") else 0


def _domain_target() -> str:
    return f"gui/{_uid()}"


def _service_target() -> str:
    return f"gui/{_uid()}/{LABEL}"


def render_plist(
    runtime_command: List[str],
    bind: str,
    port: int,
    *,
    marker_id: str,
    env_data_dir: Optional[str] = None,
) -> str:
    """Render the LaunchAgent plist text.

    ``ProgramArguments`` = ``<runtime_command> serve --bind <bind> --port <port> --no-open``.
    ``RunAtLoad`` + ``KeepAlive`` make it a always-on background agent. When the data dir is
    non-default, ``EnvironmentVariables`` adds ``TOKDASH_DATA_DIR`` (mirror of §10.1).
    """
    args = list(runtime_command) + ["serve", "--bind", bind, "--port", str(port), "--no-open"]
    arg_xml = "\n".join(f"        <string>{escape(a)}</string>" for a in args)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        f"<!-- {MARKER_COMMENT} -->",
        f"<!-- {escape(manifest.marker_token(marker_id))} -->",
        '<plist version="1.0">',
        "<dict>",
        "    <key>Label</key>",
        f"    <string>{LABEL}</string>",
        "    <key>ProgramArguments</key>",
        "    <array>",
        arg_xml,
        "    </array>",
        "    <key>RunAtLoad</key>",
        "    <true/>",
        "    <key>KeepAlive</key>",
        "    <true/>",
    ]
    if env_data_dir:
        lines += [
            "    <key>EnvironmentVariables</key>",
            "    <dict>",
            "        <key>TOKDASH_DATA_DIR</key>",
            f"        <string>{escape(env_data_dir)}</string>",
            "    </dict>",
        ]
    lines += ["</dict>", "</plist>", ""]
    return "\n".join(lines)


def plist_is_managed(plist_path: Path, marker_id: Optional[str] = None) -> bool:
    """Does this plist carry setup's ownership marker (optionally a specific id)?"""
    try:
        text = plist_path.read_text(encoding="utf-8")
    except OSError:
        return False
    if "X-Tokdash-Managed" not in text:
        return False
    if marker_id is not None:
        return f"id={marker_id}" in text
    return True


def write_plist(text: str) -> Path:
    path = paths.launchd_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(args: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=timeout)


def bootstrap(plist_path: Path) -> subprocess.CompletedProcess:
    return _run(["bootstrap", _domain_target(), str(plist_path)], timeout=LIFECYCLE_TIMEOUT)


def bootout() -> subprocess.CompletedProcess:
    return _run(["bootout", _service_target()], timeout=LIFECYCLE_TIMEOUT)


def kickstart() -> subprocess.CompletedProcess:
    # `-k` kills the running instance first, so this is a true restart.
    return _run(["kickstart", "-k", _service_target()], timeout=LIFECYCLE_TIMEOUT)


def is_loaded() -> bool:
    try:
        return _run(["print", _service_target()], timeout=10).returncode == 0
    except Exception:
        return False


def is_loaded_strict() -> bool:
    """Like :func:`is_loaded` but does NOT swallow errors/timeouts.

    ``is_loaded()`` returns False both for "confirmed not loaded" and "could not determine"
    (it wraps the probe in ``except Exception``). The uninstall teardown must tell those apart
    so it can fail CLOSED when it cannot confirm the agent stopped — it calls this variant and
    treats a raised error (e.g. a hung ``launchctl``) as "state unknown → assume still loaded".
    """
    return _run(["print", _service_target()], timeout=10).returncode == 0


def status() -> Dict[str, Any]:
    loaded = is_loaded()
    return {"type": "launchd", "name": LABEL, "enabled": loaded, "active": loaded}
