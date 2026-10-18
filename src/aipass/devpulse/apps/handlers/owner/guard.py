# =================== AIPass ====================
# Name: guard.py
# Description: Owner-capability caller guard for devpulse owner-only tools
# Version: 1.3.0
# Created: 2026-07-10
# Modified: 2026-10-17
# =============================================

"""
Owner-capability guard for devpulse's owner-only tools.

drone runs a routed module with cwd set to the branch, so Path.cwd() never names the caller; AIPASS_CALLER_* does.
"""

import os
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.json import json_handler


def _resolve_caller() -> tuple[str, Path]:
    """Resolve ``(caller_email, caller_cwd)`` from the env drone sets; the email is @ + directory name, as ai_mail."""
    caller_cwd_env = os.environ.get("AIPASS_CALLER_CWD", "")
    caller_cwd = Path(caller_cwd_env) if caller_cwd_env else Path.cwd()

    branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    if not branch:
        for candidate in [caller_cwd, *caller_cwd.parents]:
            if (candidate / ".trinity" / "passport.json").exists():
                branch = candidate.name
                break

    email = f"@{branch.lstrip('@').lower()}" if branch else ""
    return email, caller_cwd


def _legacy_devpulse_heuristic(caller_cwd: Path) -> bool:
    """Pre-owner fail-safe for installs with no sealed owner: allow only a caller in the devpulse tree."""
    return caller_cwd.name == "devpulse" or any(p.name == "devpulse" for p in caller_cwd.parents)


def _owner_decision(email: str, caller_cwd: Path) -> bool:
    """Decide whether ``email`` owns the project at ``caller_cwd``, against the caller's own registry."""
    try:
        # Lazy: keeps cold start fast and lets an ImportError reach the fail-safe.
        from aipass.spawn.apps.modules.door_owner import (
            find_registry,
            get_owner,
            is_owner,
            registry_is_writable_document,
        )
    except ImportError as exc:
        logger.warning("[owner_guard] owner resolver unavailable (%s) — legacy heuristic", exc)
        return _legacy_devpulse_heuristic(caller_cwd)

    if get_owner(start_path=caller_cwd) is None:
        # None also means UNREADABLE; only the unsealed case may reach the heuristic, or any dir named devpulse passes.
        registry_path = find_registry(start_path=caller_cwd)
        if registry_path is not None and not registry_is_writable_document(registry_path):
            logger.warning("[owner_guard] registry %s exists but cannot be read — refusing", registry_path)
            return False
        logger.info("[owner_guard] no sealed owner at %s — legacy heuristic", caller_cwd)
        return _legacy_devpulse_heuristic(caller_cwd)

    return bool(email) and is_owner(email, start_path=caller_cwd)


def owner_address(start_path: Path | None = None) -> str | None:
    """The project owner's address — ``@devpulse`` here, ``@vera`` elsewhere.

    The single lookup for "who owns this project". None, never a raise: a message-builder must not break its refusal.
    """
    try:
        from aipass.spawn.apps.modules.door_owner import get_owner
    except ImportError as exc:  # pragma: no cover - resolver is a hard dependency
        logger.info("[owner_guard] owner resolver unavailable: %s", exc)
        return None

    try:
        entry = get_owner(start_path=start_path) if start_path is not None else get_owner()
    except Exception as exc:  # a registry read can fail any number of ways
        logger.info("[owner_guard] owner lookup failed: %s", exc)
        return None

    if not isinstance(entry, dict):
        return None
    email = str(entry.get("email") or "").strip()
    if not email:
        logger.info("[owner_guard] sealed owner entry carries no email: %s", sorted(entry))
        return None
    return f"@{email.lstrip('@').lower()}"


def guard_owner_caller(tool: str) -> bool:
    """Gate an owner-only tool; a denial is audit-logged and the calling module prints the refusal."""
    email, caller_cwd = _resolve_caller()
    if _owner_decision(email, caller_cwd):
        return True

    json_handler.log_operation("owner_guard_denied", {"tool": tool, "caller": email or "unknown"})
    logger.info("[owner_guard] %s denied non-owner caller=%s", tool, email or "unknown")
    return False
