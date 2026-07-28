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

import hashlib
import json
import os
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

AIPASS_HOME = os.environ.get("AIPASS_HOME", "")
_GUARD_DIR = Path(tempfile.gettempdir())


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


def _nudge_guard_path(session_id: str, project_path: str) -> Path | None:
    """Guard-file path for the one-time never-enrolled nudge, keyed by session + project."""
    if not session_id:
        return None
    slug = hashlib.sha256(project_path.encode()).hexdigest()[:16]
    return _GUARD_DIR / f"aipass-never-enrolled-{session_id}-{slug}"


def _already_nudged(session_id: str, project_path: str) -> bool:
    path = _nudge_guard_path(session_id, project_path)
    return path is not None and path.exists()


def _mark_nudged(session_id: str, project_path: str) -> None:
    path = _nudge_guard_path(session_id, project_path)
    if path is not None:
        try:
            path.touch()
        except OSError as exc:
            logger.info("[HOOKS] never_enrolled_banner: guard write failed: %s", exc)


def never_enrolled_banner(session_id: str = "") -> str | None:
    """One-time-per-session nudge for a project that was simply never enrolled.

    Distinct from trust_break_banner() — that fires on a genuine hash-mismatch
    break and nags every prompt by design. Never-enrolled is normal first-run
    state, not a break (#712), so the ask is a single nudge, not a persistent
    nag. Same independent CWD-to-home walk and config-independence as
    trust_break_banner() — this must work precisely when the project config
    is missing, so it never touches hooks.json content or depends on it.
    """
    from aipass.hooks.apps.handlers.config.trust_registry import is_unenrolled

    search = Path.cwd()
    home = Path.home()
    while search != home and search.parent != search:
        config_file = search / ".aipass" / "hooks.json"
        if config_file.exists():
            project_path = str(search)
            if not is_unenrolled(project_path):
                return None
            if _already_nudged(session_id, project_path):
                return None
            _mark_nudged(session_id, project_path)
            return (
                "# HOOKS ARE OFF — not yet enrolled\n\n"
                f"{project_path}/.aipass/hooks.json exists, but this project has never "
                "been enrolled in the trust registry, so no AIPass hooks run here "
                "(identity injection, edit/git/rm gates, pre-compact, and everything "
                "else are all silent).\n\n"
                "Fix: aipass init update\n"
                "One-time nudge for this session — enrollment stays a deliberate "
                "human action, not something that auto-heals."
            )
        search = search.parent
    return None
