# =================== AIPass ====================
# Name: email.py
# Version: 1.2.0
# Description: Checks inbox for unread emails on UserPromptSubmit
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-05-21
# Modified: 2026-08-07
# =============================================

"""Checks branch inbox for unread emails and returns notification text."""

import json
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


def _find_branch_root() -> Path | None:
    """Find the branch root by walking up from CWD looking for branch markers."""
    cwd = Path.cwd()
    repo_root = _find_repo_root()
    if not repo_root:
        return None

    search = cwd
    for _ in range(10):
        has_trinity = (search / ".trinity").is_dir()
        has_apps = (search / "apps").is_dir()
        has_mail = (search / ".ai_mail.local").is_dir() or (search / "ai_mail.local").is_dir()

        if (has_trinity or has_apps or has_mail) and search != repo_root:
            return search

        if search == repo_root:
            break

        parent = search.parent
        if parent == search:
            break
        search = parent

    return None


def _find_repo_root() -> Path | None:
    """Find the repo root (contains pyproject.toml or .git)."""
    search = Path.cwd()
    while search.parent != search:
        if (search / "pyproject.toml").exists() or (search / ".git").is_dir():
            return search
        search = search.parent
    return None


def _count_new_emails(branch_root: Path) -> int:
    """Count unread emails in the branch's inbox."""
    inbox_path = branch_root / ".ai_mail.local" / "inbox.json"
    if not inbox_path.exists():
        inbox_path = branch_root / "ai_mail.local" / "inbox.json"

    if not inbox_path.exists():
        return 0

    try:
        data = json.loads(inbox_path.read_text(encoding="utf-8"))
        messages = data if isinstance(data, list) else data.get("messages", [])
        count = 0
        for msg in messages:
            if msg.get("status") == "new":
                count += 1
            elif msg.get("status") is None and not msg.get("read", False):
                count += 1
        return count
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[HOOKS] email: inbox read error: %s", exc)
        return 0


def _cadence_allows(new_count: int, hook_data: dict) -> bool:
    """Ask the shared cadence module whether the banner fires this turn.

    Zero new mail is always silent. Otherwise the banner announces on the turn
    mail arrives and repeats every Nth turn while it stays new, instead of
    stacking on every single turn.

    Fails OPEN: if cadence is unavailable the banner still shows whenever mail
    exists. A broken counter must not be able to silently hide someone's mail.

    Note the zero case is handed to cadence rather than short-circuited here —
    an empty inbox is what CLEARS the loop state, so the next mail to arrive
    announces on its own turn instead of serving out the previous period.
    """
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        return cadence.should_fire_mail(new_count, hook_data)
    except Exception as exc:
        logger.info("[HOOKS] email: cadence check failed, announcing anyway: %s", exc)
        return new_count > 0


def handle(hook_data: dict) -> dict:
    """Check inbox and return email notification if unread messages exist.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (notification text or empty) and exit_code.
    """
    branch_root = _find_branch_root()
    if not branch_root:
        logger.info("[HOOKS] email: no branch root found")
        return {"stdout": "", "exit_code": 0}

    new_count = _count_new_emails(branch_root)
    if not _cadence_allows(new_count, hook_data):
        return {"stdout": "", "exit_code": 0}

    plural = "s" if new_count != 1 else ""
    msg = (
        f"You have {new_count} new email{plural} - check with: drone @ai_mail inbox"
        " | then: drone @ai_mail view <id> | close with: drone @ai_mail close <id>"
    )
    logger.info("[HOOKS] email: %d new email%s", new_count, plural)
    return {
        "stdout": msg,
        "exit_code": 0,
        "sound": f"email notification: {new_count} new email{plural}",
    }
