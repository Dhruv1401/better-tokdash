"""Shared harness for Tokdash adversarial experiments.

Every experiment gets an isolated data dir (TOKDASH_DATA_DIR) and isolated
source roots via the parsers' clientpaths module, so nothing touches real
~/.codex / ~/.claude etc.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "tokdash"
sys.path.insert(0, str(REPO / "src"))


class IsoEnv:
    """Isolated environment: own data dir, own client data roots."""

    def __init__(self, name: str):
        self.name = name
        self.root = Path(tempfile.mkdtemp(prefix=f"tokdash-audit-{name}-"))
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._old_env = {}
        self._setenv("TOKDASH_DATA_DIR", str(self.data_dir))
        # Speed: skip file-content hashes on unchanged files (audit-only).
        self._setenv("TOKDASH_USAGE_DB", os.environ.get("AUDIT_DB", "0"))

    def _setenv(self, key: str, value: str):
        self._old_env[key] = os.environ.get(key)
        os.environ[key] = value

    def cleanup(self):
        for key, old in self._old_env.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        shutil.rmtree(self.root, ignore_errors=True)

    def path(self, *parts) -> Path:
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def reload_clientpaths(env: IsoEnv):
    """(Re)load clientpaths after env overrides are set; returns module."""
    import tokdash.clientpaths as cp

    importlib.reload(cp)
    return cp


def fresh_modules():
    """Reload modules that cache class-level state between experiments."""
    import tokdash.sources.coding_tools as ct

    importlib.reload(ct)
    import tokdash.pricing as pricing_mod

    importlib.reload(pricing_mod)
    return ct


def iso(ts_ms: int) -> str:
    """Epoch ms -> Codex-style ISO timestamp."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def codex_event(session_id: str, ts_ms: int, input_tokens: int, cached: int = 0,
                output: int = 0, reasoning: int = 0, info_id: str | None = None) -> str:
    """A Codex token_count event_msg line."""
    info: dict = {"total_token_usage": {"input_tokens": input_tokens, "cached_input_tokens": cached,
                                        "output_tokens": output, "reasoning_output_tokens": reasoning},
                  "last_token_usage": {"input_tokens": input_tokens, "cached_input_tokens": cached,
                                       "output_tokens": output, "reasoning_output_tokens": reasoning}}
    if info_id:
        info["id"] = info_id
    return json.dumps({
        "timestamp": iso(ts_ms),
        "type": "event_msg",
        "payload": {"type": "token_count", "info": info},
    })


def claude_line(msg_id: str, ts_ms: int, inp: int, out: int, cache_r: int = 0, cache_w: int = 0,
                model: str = "claude-sonnet-4-6") -> str:
    return json.dumps({
        "type": "assistant",
        "timestamp": iso(ts_ms),
        "message": {"id": msg_id, "role": "assistant", "model": model,
                    "usage": {"input_tokens": inp, "output_tokens": out,
                              "cache_read_input_tokens": cache_r,
                              "cache_creation_input_tokens": cache_w}},
    })
