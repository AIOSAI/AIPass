# =================== AIPass ====================
# Name: rollover.py
# Version: 2.6.1
# Description: Triggers memory rollover via @memory when files are overdue (PreCompact), naming the compacting branch
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-05-22
# Modified: 2026-11-22
# =============================================

"""Delegates rollover detection to @memory and triggers rollover if overdue.

A clean check is trusted for CHECK_FRESH_SECONDS: the check is a 7-15 s drone subprocess, and OpenCode
runs PreCompact inside its agent step, so an unthrottled check stalls the chat at every compaction.
A ready verdict, a failed check or a timeout leaves no stamp, so the next compaction checks again."""

import hashlib
import importlib
import os
import subprocess
import tempfile
import time
from pathlib import Path

from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax import logger

# Contract with @memory's todo_report.READY_PHRASE: the one phrase this handler greps.
READY_PHRASE = "ready for rollover"

CHECK_FRESH_SECONDS = 30 * 60

_GUARD_DIR = Path(tempfile.gettempdir())


def _probe_run() -> bool:
    """True under drone @hooks test: its sandbox has no registry by design, so a missing root is no fault."""
    return os.environ.get("AIPASS_HOOK_PROBE") == "1"


def _find_repo_root() -> Path | None:
    aipass_home = os.environ.get("AIPASS_HOME", "")
    if aipass_home:
        p = Path(aipass_home)
        if (p / "AIPASS_REGISTRY.json").exists():
            return p
    cwd = Path.cwd()
    for parent in [cwd, *list(cwd.parents)]:
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    if _probe_run():
        return None
    logger.error(
        "[hooks] rollover: _find_repo_root failed — no AIPASS_REGISTRY.json found. AIPASS_HOME=%r, cwd=%s",
        aipass_home,
        cwd,
    )
    return None


def _compacting_branch(hook_data: dict) -> Path | None:
    """The directory of the branch whose session is compacting, or None.

    drone runs in it, so the verified-caller rail reads that branch as the caller, not the project.
    """
    cwd = hook_data.get("cwd", "") or str(Path.cwd())
    context_window = importlib.import_module("aipass.hooks.apps.modules.context_window")
    branch_dir = context_window.find_branch_dir(cwd)
    if branch_dir is None:
        logger.info("[hooks] rollover: no branch resolved from cwd=%s — fleet rollover only, no todo pad", cwd)
        return None
    return branch_dir


def _branch_args(branch: str | None) -> list[str]:
    return ["--branch", f"@{branch}"] if branch else []


def _clean_stamp(repo_root: Path, branch: str | None) -> Path:
    """The file whose mtime is the last clean check for this project's branch (the fleet when None)."""
    project = hashlib.sha256(str(repo_root).encode()).hexdigest()[:12]
    return _GUARD_DIR / f"aipass-rollover-clean-{project}-{branch or 'fleet'}"


def _recently_clean(repo_root: Path, branch: str | None) -> bool:
    try:
        age = time.time() - _clean_stamp(repo_root, branch).stat().st_mtime
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.info("[hooks] rollover: clean stamp unreadable, checking: %s", exc)
        return False
    return 0 <= age < CHECK_FRESH_SECONDS


def _mark_clean(repo_root: Path, branch: str | None) -> None:
    try:
        _clean_stamp(repo_root, branch).touch()
    except OSError as exc:
        logger.info("[hooks] rollover: clean stamp not written, the next compaction checks again: %s", exc)


def _run_check(repo_root: Path, branch: str | None, seat: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["drone", "@memory", "rollover", "check", *_branch_args(branch)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(seat),
        )
        stdout = result.stdout.strip()
        has_overdue = READY_PHRASE in stdout.lower()
        if result.returncode == 0 and not has_overdue:
            _mark_clean(repo_root, branch)
        return has_overdue, stdout
    except subprocess.TimeoutExpired:
        logger.warning("[hooks] rollover: check timed out (30s)")
        return False, "check timed out"
    except Exception as exc:
        logger.warning("[hooks] rollover: check failed: %s", exc)
        return False, str(exc)


def _run_rollover(branch: str | None, seat: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["drone", "@memory", "rollover", "run", *_branch_args(branch)],
            capture_output=True,
            text=True,
            timeout=110,
            cwd=str(seat),
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        logger.warning("[hooks] rollover: drone rollover timed out (110s)")
        return False, "Rollover timed out (110s)"
    except Exception as exc:
        logger.warning("[hooks] rollover: drone rollover failed: %s", exc)
        return False, str(exc)


def handle(hook_data: dict) -> dict:
    """Check memory files for overflow, roll over if due; each call leaves one json trail entry."""
    result = _handle(hook_data)
    seat = hook_data.get("cwd", "") if isinstance(hook_data, dict) else ""
    json_handler.log_operation("handle", {"exit_code": result.get("exit_code"), "seat": seat})
    return result


def _handle(hook_data: dict) -> dict:
    """Check memory files for overflow and trigger rollover if needed."""
    repo_root = _find_repo_root()
    if not repo_root:
        if not _probe_run():
            logger.warning("[hooks] rollover: no repo root found — cannot check")
        return {"stdout": "", "exit_code": 0}

    branch_dir = _compacting_branch(hook_data)
    branch = branch_dir.name if branch_dir else None
    seat = branch_dir or repo_root
    if _recently_clean(repo_root, branch):
        logger.info(
            "[hooks] rollover: checked clean within %d min, skipped (branch=%s)", CHECK_FRESH_SECONDS // 60, branch
        )
        return {"stdout": "", "exit_code": 0}
    has_overdue, check_output = _run_check(repo_root, branch, seat)
    if not has_overdue:
        return {"stdout": "", "exit_code": 0}

    logger.info("[hooks] rollover: overdue files detected — %s", check_output.replace("\n", " | "))

    # `rollover run` trims fleet memory and ignores cwd and AIPASS_HOME, so the probe must stop it here.
    if _probe_run():
        logger.info("[hooks] rollover: probe run — check ran, fleet rollover suppressed")
        return {"stdout": "", "exit_code": 0, "sound": "pre compact rollover"}

    success, output = _run_rollover(branch, seat)
    if success:
        logger.info("[hooks] rollover: complete (branch=%s)", branch)
    else:
        logger.warning("[hooks] rollover: FAILED — %s", output[:300])

    return {"stdout": "", "exit_code": 0, "sound": "pre compact rollover"}
