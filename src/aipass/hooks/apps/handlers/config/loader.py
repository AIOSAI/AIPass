# =================== AIPass ====================
# Name: loader.py
# Version: 1.0.0
# Description: Hook config loader — finds and parses .aipass/hooks.json
# Branch: hooks
# Layer: apps/handlers/config
# Created: 2026-05-19
# Modified: 2026-05-19
# =============================================

"""Loads per-project hook configuration from .aipass/hooks.json."""

import json
import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

AIPASS_HOME = os.environ.get("AIPASS_HOME", "")


def find_project_config() -> dict | None:
    """Walk up from CWD looking for .aipass/hooks.json, with trust verification."""
    from aipass.hooks.apps.handlers.config.trust_registry import (
        REGISTRY_PATH,
        bootstrap,
        is_trusted,
    )

    search = Path.cwd()
    home = Path.home()
    while search != home and search.parent != search:
        config_file = search / ".aipass" / "hooks.json"
        if config_file.exists():
            project_dir = str(search)

            if not REGISTRY_PATH.exists():
                bootstrap()

            if not is_trusted(project_dir):
                logger.warning(
                    "[HOOKS] project not enrolled in trust registry: %s (run: aipass init update)",
                    project_dir,
                )
                return None

            try:
                raw = config_file.read_text(encoding="utf-8")
                if AIPASS_HOME:
                    raw = raw.replace("$AIPASS_HOME", AIPASS_HOME)
                parsed = json.loads(raw)
                parsed["_source"] = "project"
                return parsed
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("[HOOKS] bad config %s: %s", config_file, exc)
                return None
        search = search.parent
    return None


def trust_break_banner() -> str | None:
    """Loud, config-independent check for a stale trust enrollment.

    find_project_config() goes silent on a hash mismatch (logs one WARNING,
    returns None) — the fallback config downstream then has no event_type
    keys at all, so every hook including this one's own dispatch path goes
    dark. This check does its own walk-up and hash comparison, never touches
    hooks.json content, and does not depend on the project being trusted —
    so it still works precisely when trust is broken. Returns None when
    nothing is broken, or when the project was simply never enrolled (normal
    first-run state, not a break).
    """
    from aipass.hooks.apps.handlers.config.trust_registry import is_hash_mismatch

    search = Path.cwd()
    home = Path.home()
    while search != home and search.parent != search:
        config_file = search / ".aipass" / "hooks.json"
        if config_file.exists():
            if is_hash_mismatch(str(search)):
                return (
                    "# TRUST BREAK — ALL AIPASS HOOKS DISABLED\n\n"
                    f"{search}/.aipass/hooks.json no longer matches its enrolled hash. "
                    "Every hook for this project (including this warning's own delivery "
                    "path) is silently skipped until a human re-enrolls.\n\n"
                    "Fix: drone @hooks trust enroll (or: aipass init update)\n"
                    "This does not auto-heal — re-enrollment is a deliberate human "
                    "checkpoint, not a bug."
                )
            return None
        search = search.parent
    return None
