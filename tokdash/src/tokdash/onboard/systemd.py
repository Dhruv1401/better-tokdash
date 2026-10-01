"""systemd *user* service generation and lifecycle (plan §10.1, §12).

The unit always carries a machine-readable ownership marker so ``uninstall`` can prove
setup wrote it before removing it — the repo also documents *manual* tokdash.service
installs, and the filename alone is not proof (§12.3). All lifecycle calls use
``systemctl --user`` only; setup never runs ``sudo`` and never writes a system unit.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import manifest, paths

SERVICE_NAME = "tokdash"
MARKER_COMMENT = "# Managed-by: tokdash-setup"
LIFECYCLE_TIMEOUT = 120

_NEEDS_QUOTING = set(' \t\n"\\\'')


def _quote_exec_arg(arg: str) -> str:
    """Quote an ``ExecStart`` argument for systemd.

    systemd splits ``ExecStart`` on whitespace unless an argument is double-quoted, so
    a runtime/data path containing spaces would otherwise produce a broken unit. Wrap
    such args in double quotes with C-style escaping of ``\\`` and ``"``.
    """
    if arg and not (_NEEDS_QUOTING & set(arg)):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _environment_line(name: str, value: str) -> str:
    """Render an ``Environment=`` line, double-quoting the assignment if needed."""
    assignment = f"{name}={value}"
    if _NEEDS_QUOTING & set(value):
        assignment = '"' + assignment.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"Environment={assignment}"


def render_unit(
    runtime_command: List[str],
    bind: str,
    port: int,
    *,
    marker_id: str,
    env_data_dir: Optional[str] = None,
) -> str:
    """Render the ``tokdash.service`` text.

    ``ExecStart`` is ``<runtime_command> serve --bind <bind> --port <port> --no-open``;
    for a managed venv the interpreter path already lives under ``<data_dir>``. When the
    data dir is non-default, ``env_data_dir`` adds ``Environment=TOKDASH_DATA_DIR=`` so
    the service reads the same state the manifest recorded (§10.1).
    """
    exec_args = list(runtime_command) + ["serve", "--bind", bind, "--port", str(port), "--no-open"]
    exec_start = " ".join(_quote_exec_arg(a) for a in exec_args)
    lines = [
        "[Unit]",
        "Description=Tokdash local token dashboard",
        MARKER_COMMENT,
        f"# {manifest.marker_token(marker_id)}",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart={exec_start}",
        "Restart=on-failure",
        "RestartSec=3",
    ]
    if env_data_dir:
        lines.append(_environment_line("TOKDASH_DATA_DIR", env_data_dir))
    lines += ["", "[Install]", "WantedBy=default.target", ""]
    return "\n".join(lines)


def unit_is_managed(unit_path: Path, marker_id: Optional[str] = None) -> bool:
    """Does this unit carry setup's ownership marker (optionally a specific id)?

    Used as the safety gate before removing a unit when the manifest is missing.
    """
    try:
        text = unit_path.read_text(encoding="utf-8")
    except OSError:
        return False
    if "X-Tokdash-Managed" not in text:
        return False
    if marker_id is not None:
        return f"id={marker_id}" in text
    return True


def write_unit(text: str, name: str = SERVICE_NAME) -> Path:
    path = paths.systemd_unit_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(args: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout)


def daemon_reload() -> None:
    _run(["daemon-reload"])


def enable_now(name: str = SERVICE_NAME) -> subprocess.CompletedProcess:
    return _run(["enable", "--now", name], timeout=LIFECYCLE_TIMEOUT)


def disable_now(name: str = SERVICE_NAME) -> subprocess.CompletedProcess:
    return _run(["disable", "--now", name], timeout=LIFECYCLE_TIMEOUT)


def restart(name: str = SERVICE_NAME) -> subprocess.CompletedProcess:
    return _run(["restart", name], timeout=LIFECYCLE_TIMEOUT)


def fragment_path(name: str = SERVICE_NAME) -> Optional[str]:
    """Return the unit file path systemd has loaded for ``name``, if known."""
    try:
        proc = _run(["show", name, "-p", "FragmentPath", "--value"], timeout=10)
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except Exception:
        return None
    return None


def is_active(name: str = SERVICE_NAME) -> bool:
    try:
        return _run(["is-active", name], timeout=10).stdout.strip() == "active"
    except Exception:
        return False


def is_active_strict(name: str = SERVICE_NAME) -> bool:
    """Like :func:`is_active` but does NOT swallow errors/timeouts.

    ``is_active()`` returns False both for "confirmed inactive" and "could not determine" (it
    wraps the probe in ``except Exception``). The uninstall teardown must tell those apart so it
    can fail CLOSED when it cannot confirm a unit stopped — it calls this variant and treats a
    raised error (e.g. a hung ``systemctl``) as "state unknown → assume still active".
    """
    return _run(["is-active", name], timeout=10).stdout.strip() == "active"


def is_enabled(name: str = SERVICE_NAME) -> bool:
    try:
        return _run(["is-enabled", name], timeout=10).stdout.strip() == "enabled"
    except Exception:
        return False


def status(name: str = SERVICE_NAME) -> Dict[str, Any]:
    return {
        "type": "systemd-user",
        "name": name,
        "enabled": is_enabled(name),
        "active": is_active(name),
        "fragment_path": fragment_path(name),
    }
