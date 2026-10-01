"""Python-native onboarding engine for Tokdash.

Behind the CLI lifecycle verbs (``setup`` / ``doctor`` / ``uninstall``) sits one
reversible engine: detect -> plan -> apply -> record (``install.json``) -> revert.
Setup is optional and creates only user-level state; ``tokdash serve`` needs no setup,
so the tool stays fully backward-compatible (plan §3, §6).

The public entry point is :func:`tokdash.onboard.engine.run_lifecycle`. It is imported
lazily (the CLI does ``from .onboard.engine import run_lifecycle``) so importing this
package never pulls in FastAPI or the rest of the runtime.
"""
from __future__ import annotations
