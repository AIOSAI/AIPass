# =================== AIPass ====================
# Name: rollover.py
# Version: 2.2.0
# Description: Triggers memory rollover via @memory when files are overdue (PreCompact), naming the compacting branch
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-05-22
# Modified: 2026-09-15
# =============================================

"""Delegates rollover detection to @memory and triggers rollover if overdue."""

import importlib
import os
import subprocess
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

# @memory prints this on the fleet line AND on the todos line of `rollover
# check` (todo_report.READY_PHRASE) - the one phrase this handler greps.
READY_PHRASE = "ready for rollover"


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
    logger.error(
        "[HOOKS] rollover: _find_repo_root failed — no AIPASS_REGISTRY.json found. AIPASS_HOME=%r, cwd=%s",
        aipass_home,
        cwd,
    )
    return None


def _compacting_branch(hook_data: dict) -> str | None:
    """The branch whose session is compacting, by directory name, or None.

    DPLAN-0345: @memory rolls ONE branch's todo pad per call, the branch named by
    --branch or the one drone's caller cwd sits in. drone runs here with cwd =
    repo root and re-stamps AIPASS_CALLER_CWD with it, so without the flag no
    branch resolves and no pad rolls. Same resolve as pre_compact_prep.
    """
    cwd = hook_data.get("cwd", "") or str(Path.cwd())
    context_window = importlib.import_module("aipass.hooks.apps.modules.context_window")
    branch_dir = context_window.find_branch_dir(cwd)
    if branch_dir is None:
        logger.info("[HOOKS] rollover: no branch resolved from cwd=%s — fleet rollover only, no todo pad", cwd)
        return None
    return branch_dir.name


def _branch_args(branch: str | None) -> list[str]:
    return ["--branch", f"@{branch}"] if branch else []


def _run_check(repo_root: Path, branch: str | None) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["drone", "@memory", "rollover", "check", *_branch_args(branch)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo_root),
        )
        stdout = result.stdout.strip()
        has_overdue = READY_PHRASE in stdout.lower()
        return has_overdue, stdout
    except subprocess.TimeoutExpired:
        logger.warning("[HOOKS] rollover: check timed out (30s)")
        return False, "check timed out"
    except Exception as exc:
        logger.warning("[HOOKS] rollover: check failed: %s", exc)
        return False, str(exc)


def _run_rollover(repo_root: Path, branch: str | None) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["drone", "@memory", "rollover", "run", *_branch_args(branch)],
            capture_output=True,
            text=True,
            timeout=110,
            cwd=str(repo_root),
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        logger.warning("[HOOKS] rollover: drone rollover timed out (110s)")
        return False, "Rollover timed out (110s)"
    except Exception as exc:
        logger.warning("[HOOKS] rollover: drone rollover failed: %s", exc)
        return False, str(exc)


def handle(hook_data: dict) -> dict:
    """Check memory files for overflow and trigger rollover if needed."""
    repo_root = _find_repo_root()
    if not repo_root:
        logger.warning("[HOOKS] rollover: no repo root found — cannot check")
        return {"stdout": "", "exit_code": 0}

    branch = _compacting_branch(hook_data)
    has_overdue, check_output = _run_check(repo_root, branch)
    if not has_overdue:
        return {"stdout": "", "exit_code": 0}

    logger.info("[HOOKS] rollover: overdue files detected — %s", check_output.replace("\n", " | "))

    # Everything above is read-only and runs for real under the probe. This is
    # the mutation: `rollover run` archives and TRIMS memory across the fleet,
    # and @memory resolves its own roots — neither cwd nor AIPASS_HOME reaches
    # it (measured 2026-09-06: the name appears nowhere in @memory's tree), so
    # the refusal has to live at the call. Info, not warning: under a probe this
    # is the designed path, not a fault.
    if os.environ.get("AIPASS_HOOK_PROBE") == "1":
        logger.info("[HOOKS] rollover: probe run — check ran, fleet rollover suppressed")
        return {"stdout": "", "exit_code": 0, "sound": "pre compact rollover"}

    success, output = _run_rollover(repo_root, branch)
    if success:
        logger.info("[HOOKS] rollover: complete (branch=%s)", branch)
    else:
        logger.warning("[HOOKS] rollover: FAILED — %s", output[:300])

    return {"stdout": "", "exit_code": 0, "sound": "pre compact rollover"}
