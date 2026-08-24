# =================== AIPass ====================
# Name: guard.py
# Description: Owner-capability caller guard for devpulse owner-only tools
# Version: 1.1.0
# Created: 2026-07-10
# Modified: 2026-08-22
# =============================================

"""
Owner-capability guard for devpulse's owner-only tools.

watchdog and feedback's mailbox-management verbs are the project OWNER's
tools. The catch: drone runs a routed module with ``cwd=<branch_path>`` (see
drone router_handler), so the module's own ``Path.cwd()`` is ALWAYS the
devpulse tree and can't identify who called. The real caller lives in the env
drone sets — ``AIPASS_CALLER_BRANCH`` / ``AIPASS_CALLER_CWD``. This resolves
that caller and checks it against the sealed-registry owner via ``is_owner``.

Portable by construction: ``is_owner`` reads each project's OWN sealed
registry, so "owner" is devpulse in AIPass and whoever owns elsewhere (e.g.
@vera in Vera Studio) — no hardcoded name, no per-project scaffolding.

Fail-safe: if the owner resolver is unavailable (import fails, or a project
has no sealed owner yet — an old/partial install), it falls back to the legacy
devpulse-path heuristic so existing installs never hard-break. Concretely #681.

Returns a plain bool — the calling MODULE owns user-facing output (handlers
don't print). Denials are audit-logged here.
"""

import os
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.json import json_handler


def _resolve_caller() -> tuple[str, Path]:
    """Resolve ``(caller_email, caller_cwd)`` from the env drone sets.

    ``caller_email`` is ``@<branch>`` — a branch's address is ``@`` + its
    directory name (matches ai_mail's identity resolution). Prefers the
    ``AIPASS_CALLER_BRANCH`` env var; otherwise walks up ``AIPASS_CALLER_CWD``
    for a ``.trinity/passport.json`` and uses that directory's name. Falls back
    to the process cwd when no caller env is set (direct, non-drone invocation).

    Returns:
        tuple: (caller_email_or_empty, caller_cwd_path)
    """
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
    """Pre-owner behavior: allow only a caller standing in the devpulse tree.

    Used solely as the fail-safe when the owner resolver can't decide, so
    existing AIPass installs keep working before the sealed owner is present.
    """
    return caller_cwd.name == "devpulse" or any(p.name == "devpulse" for p in caller_cwd.parents)


def _owner_decision(email: str, caller_cwd: Path) -> bool:
    """Decide whether ``email`` is the owner of the project at ``caller_cwd``.

    Owner check runs against the caller's OWN project registry (start_path =
    caller_cwd), so cross-project calls resolve the caller's owner, not
    AIPass's. Falls back to the legacy heuristic when the resolver is
    unavailable or the project has no sealed owner yet.
    """
    try:
        # is_owner is the frozen shared owner-capability contract (spawn is its
        # sole home; no modules re-export). Lazy import keeps cold start fast and
        # enables the fail-safe fallback below.
        from aipass.spawn.apps.handlers.registry import get_owner, is_owner
    except ImportError as exc:
        logger.warning("[owner_guard] owner resolver unavailable (%s) — legacy heuristic", exc)
        return _legacy_devpulse_heuristic(caller_cwd)

    if get_owner(start_path=caller_cwd) is None:
        # No sealed owner in this project -> resolver can't decide -> legacy path check.
        logger.info("[owner_guard] no sealed owner at %s — legacy heuristic", caller_cwd)
        return _legacy_devpulse_heuristic(caller_cwd)

    return bool(email) and is_owner(email, start_path=caller_cwd)


def owner_address(start_path: Path | None = None) -> str | None:
    """The project owner's address — ``@devpulse`` here, ``@vera`` elsewhere.

    The single lookup for "who owns this project", so a refusal message and an
    arm-time check can never disagree about the answer. Returns None rather
    than raising: callers that must refuse hard convert it themselves, and a
    message-builder must never be able to break the refusal it is decorating.

    ``get_owner`` returns the owner's REGISTRY ENTRY DICT, not a name. Reading
    it as a string stringifies the whole dict into a plausible-looking address
    that matches nothing — the same class of mistake as answering "who am I"
    with a project directory name, which cost $1.41 on 2026-08-21.
    """
    try:
        from aipass.spawn.apps.handlers.registry import get_owner
    except ImportError as exc:  # pragma: no cover - resolver is a hard dependency
        logger.info("[owner_guard] owner resolver unavailable: %s", exc)
        return None

    try:
        entry = get_owner(start_path=start_path) if start_path is not None else get_owner()
    except Exception as exc:  # noqa: BLE001 - a registry read can fail any number of ways
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
    """Gate an owner-only tool.

    Args:
        tool: Name of the calling tool (e.g. 'watchdog', 'feedback') for the
            audit line. The caller is responsible for any user-facing message.

    Returns:
        bool: True to allow the call; False (after audit-logging the denial) to
        reject a non-owner caller.
    """
    email, caller_cwd = _resolve_caller()
    if _owner_decision(email, caller_cwd):
        return True

    json_handler.log_operation("owner_guard_denied", {"tool": tool, "caller": email or "unknown"})
    logger.info("[owner_guard] %s denied non-owner caller=%s", tool, email or "unknown")
    return False
