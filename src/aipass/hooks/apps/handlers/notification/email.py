# =================== AIPass ====================
# Name: email.py
# Version: 1.4.1
# Description: Checks inbox for unread emails on UserPromptSubmit
# Branch: hooks
# Layer: apps/handlers/notification
# Created: 2026-05-21
# Modified: 2026-11-22
# =============================================

"""Checks branch inbox for unread emails and returns notification text."""

import json
from collections import Counter
from pathlib import Path

from aipass.ai_mail import mail_kind
from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax import logger


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
        if (search / "pyproject.toml").exists() or (
            (git := search / ".git").is_file() or (git.is_dir() and any(git.iterdir()))
        ):
            return search
        search = search.parent
    return None


def _count_new_emails(branch_root: Path) -> Counter:
    """Unread emails in the branch's inbox by kind, notices left out; empty with no inbox, an unreadable one raises."""
    inbox_path = branch_root / ".ai_mail.local" / "inbox.json"
    if not inbox_path.exists():
        inbox_path = branch_root / "ai_mail.local" / "inbox.json"

    if not inbox_path.exists():
        return Counter()

    data = json.loads(inbox_path.read_text(encoding="utf-8"))
    messages = data if isinstance(data, list) else data.get("messages", [])
    kinds = Counter()
    for msg in messages:
        status = msg.get("status")
        if status == "new" or (status is None and not msg.get("read", False)):
            # A stored kind is named as it is; only a row with none goes to ai_mail's reader (docs/mail_kinds.md).
            kinds[msg.get("kind") or mail_kind(msg)] += 1
    del kinds["notice"]
    return kinds


def _cadence_allows(new_count: int, hook_data: dict) -> bool:
    """Ask the shared cadence module whether the banner fires this turn.

    Fails open: a broken counter must not hide mail. Zero goes to cadence too: it clears the loop state.
    """
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        return cadence.should_fire_mail(new_count, hook_data)
    except Exception as exc:
        logger.warning("[hooks] email: cadence check failed, announcing anyway: %s", exc)
        return new_count > 0


def handle(hook_data: dict) -> dict:
    """Notify of unread mail; each call leaves one json trail entry."""
    result = _handle(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle(hook_data: dict) -> dict:
    """Check inbox and return email notification if unread messages exist."""
    branch_root = _find_branch_root()
    if not branch_root:
        logger.info("[hooks] email: no branch root found")
        return {"stdout": "", "exit_code": 0}

    kinds = _count_new_emails(branch_root)
    new_count = sum(kinds.values())
    if not _cadence_allows(new_count, hook_data):
        return {"stdout": "", "exit_code": 0}

    plural = "s" if new_count != 1 else ""
    named = ", ".join(f"{n} {kind}" for kind, n in kinds.items())
    msg = (
        f"You have {new_count} new email{plural}: {named} - check with: drone @ai_mail inbox"
        " | then: drone @ai_mail view <id> | close with: drone @ai_mail close <id>"
    )
    logger.info("[hooks] email: %d new email%s: %s", new_count, plural, named)
    return {
        "stdout": msg,
        "exit_code": 0,
        "sound": f"email notification: {new_count} new email{plural}",
    }
