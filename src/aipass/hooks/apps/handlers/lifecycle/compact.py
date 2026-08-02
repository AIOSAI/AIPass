# =================== AIPass ====================
# Name: compact.py
# Version: 1.0.0
# Description: Injects live state for post-compact recovery (PreCompact)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Reads branch state and injects recovery context before compaction."""

import json
import os
import subprocess
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


def _find_branch_dir(cwd: str) -> Path | None:
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "aipass" and i > 0 and parts[i - 1] == "src":
            branch_dir = Path(*parts[: i + 2])
            if branch_dir.is_dir():
                return branch_dir
    if (Path(cwd) / ".trinity").is_dir():
        return Path(cwd)
    return None


def _read_last_session(branch_dir: Path) -> str | None:
    local_path = branch_dir / ".trinity" / "local.json"
    if not local_path.is_file():
        return None
    try:
        data = json.loads(local_path.read_text(encoding="utf-8"))
        result: list[str] = []
        sessions = data.get("sessions", [])
        if sessions:
            last = sessions[0]
            sid = last.get("number", "?")
            sdate = last.get("date", "?")
            ssum = last.get("summary", "no summary")
            result.append(f"Last session (#{sid}, {sdate}): {ssum}")
        learnings = data.get("key_learnings", [])
        if isinstance(learnings, list) and learnings:
            # newest-first: [:10] is the ten most recent, not [-10:] (the ten oldest)
            keys = [entry.get("key", "?") for entry in learnings[:10] if isinstance(entry, dict)]
            if keys:
                result.append(f"Key learnings available: {', '.join(keys)}")
        return "\n".join(result) if result else None
    except Exception as exc:
        logger.info("[HOOKS] compact: read session failed: %s", exc)
        return None


def _get_git_info() -> str | None:
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        result: list[str] = []
        if branch.returncode == 0:
            result.append(f"Git branch: {branch.stdout.strip()}")
        if dirty.returncode == 0 and dirty.stdout.strip():
            lines = dirty.stdout.strip().split("\n")
            result.append(f"Uncommitted changes: {len(lines)} files")
        return "\n".join(result) if result else None
    except Exception as exc:
        logger.info("[HOOKS] compact: git info failed: %s", exc)
        return None


def handle(hook_data: dict) -> dict:
    """Inject live branch state for post-compact recovery."""
    try:
        import importlib

        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        cadence.reset_counter(hook_data=hook_data, caller="compact")
    except Exception as exc:
        logger.info("[HOOKS] compact: cadence reset failed: %s", exc)

    try:
        cwd = hook_data.get("cwd", "") or str(Path.cwd())
        branch_dir = _find_branch_dir(cwd)
        branch_name = branch_dir.name if branch_dir else "unknown"

        sections: list[str] = []
        sections.append(
            f"POST-COMPACT RECOVERY — @{branch_name}\n\n"
            "Context just compacted. Below is your live state. Use it to continue seamlessly."
        )

        git_info = _get_git_info()
        if git_info:
            sections.append(f"## Git\n{git_info}")

        if branch_dir:
            session_info = _read_last_session(branch_dir)
            if session_info:
                sections.append(f"## Last Session\n{session_info}")

        is_dispatched = os.environ.get("AIPASS_SESSION_TYPE") == "dispatched"
        if is_dispatched:
            sections.append(
                "## DISPATCHED AGENT — SAVE STATE NOW\n"
                "Before continuing work, you MUST update your memories:\n"
                "1. Update .trinity/local.json — add/update current session with work done so far\n"
                "2. Then continue your task from where the summary left off\n\n"
                "This is non-optional. Compaction just happened — if you don't save now, work history is lost."
            )
        else:
            sections.append(
                "## Recovery Protocol\n"
                "- Continue where the summary left off — don't restart or ask generic questions\n"
                "- .trinity/local.json has full session history and key_learnings — read it if you need more context\n"
                "- Save memories proactively — compaction just proved you need to\n"
                "- Match the conversation tone from before compaction"
            )

        return {"stdout": "\n\n".join(sections), "exit_code": 0, "sound": "pre compact"}

    except Exception as exc:
        logger.info("[HOOKS] compact: unexpected error: %s", exc)
        return {"stdout": "", "exit_code": 0}
