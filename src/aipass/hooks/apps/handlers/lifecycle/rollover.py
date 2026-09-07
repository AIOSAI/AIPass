# =================== AIPass ====================
# Name: rollover.py
# Version: 2.1.0
# Description: Triggers memory rollover via @memory when files are overdue (PreCompact)
# Branch: hooks
# Layer: apps/handlers/lifecycle
# Created: 2026-05-22
# Modified: 2026-09-06
# =============================================

"""Delegates rollover detection to @memory and triggers rollover if overdue."""

import os
import subprocess
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


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


def _run_check(repo_root: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["drone", "@memory", "rollover", "check"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo_root),
        )
        stdout = result.stdout.strip()
        has_overdue = "ready for rollover" in stdout.lower()
        return has_overdue, stdout
    except subprocess.TimeoutExpired:
        logger.warning("[HOOKS] rollover: check timed out (30s)")
        return False, "check timed out"
    except Exception as exc:
        logger.warning("[HOOKS] rollover: check failed: %s", exc)
        return False, str(exc)


def _run_rollover(repo_root: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["drone", "@memory", "rollover", "run"],
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


def handle(hook_data: dict) -> dict:  # noqa: ARG001
    """Check memory files for overflow and trigger rollover if needed."""
    repo_root = _find_repo_root()
    if not repo_root:
        logger.warning("[HOOKS] rollover: no repo root found — cannot check")
        return {"stdout": "", "exit_code": 0}

    has_overdue, check_output = _run_check(repo_root)
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

    success, output = _run_rollover(repo_root)
    if success:
        logger.info("[HOOKS] rollover: complete")
    else:
        logger.warning("[HOOKS] rollover: FAILED — %s", output[:300])

    return {"stdout": "", "exit_code": 0, "sound": "pre compact rollover"}
