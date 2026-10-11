# =================== AIPass ====================
# Name: support_engine.py
# Description: Helpers shared by test_engine.py and test_engine_safeguards.py: a fail-closed gate and a one-hook config
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers for the engine tests (no test_ prefix: never collected)."""

# Shared by test_engine.py (TestRunEvent) and test_engine_safeguards.py
# (TestGatesFailClosed), both of apps/modules/engine.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

_GATE = "aipass.hooks.apps.handlers.security.rm_gate.handle"


def _one(handler: str, event: str = "PreToolUse") -> dict:
    return {"hooks_enabled": True, event: {"the_hook": {"enabled": True, "handler": handler, "matcher": ""}}}
