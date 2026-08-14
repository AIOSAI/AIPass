# =================== AIPass ====================
# Name: log_structure_check.py
# Description: Log Structure Standards Checker Handler
# Version: 1.2.0
# Created: 2026-03-06
# Modified: 2026-03-17
# =============================================

"""
Log Structure Standards Checker Handler

Validates the two-tier logging model:
  - system_logs/ at repo root (system-wide)
  - logs/ at branch root only (per-branch)
No hierarchical logs/ at every nested directory.
No hardcoded absolute log paths.
"""

import re
from pathlib import Path
from typing import Dict
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"


def _find_branch_root(file_path: Path) -> Path:
    """Walk up from file to find branch root (directory containing apps/).

    The branch root is the directory that directly contains an ``apps/``
    subdirectory. For example::

        apps/seedgo.py          -> branch root is parent.parent (seedgo/)
        apps/modules/foo.py     -> branch root is parent.parent.parent
        apps/handlers/audit/bar -> branch root is parent x4

    Falls back to the file's parent when no ``apps/`` directory is found
    within 10 levels.
    """
    current = file_path.resolve().parent
    for _ in range(10):  # Safety limit
        if (current / "apps").is_dir():
            return current
        if current == current.parent:
            break
        current = current.parent
    # Fallback: assume parent of file
    return file_path.parent


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check module logging structure against the two-tier model.

    Checks:
    1. logs/ directory exists at branch root (entry file's parent)
    2. No hardcoded absolute log paths in source
    3. No /home/ references in logging configuration

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules

    Returns:
        Standard check result dict
    """
    path = Path(module_path)
    checks = []

    if is_bypassed(module_path, "log_structure", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "LOG_STRUCTURE",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "LOG_STRUCTURE",
        }

    # Check 1: Branch-root log placement — logs/ directory at the branch root
    # logs/ is gitignored (runtime artifact, created on first log write).
    # Only check when the directory actually exists; absence in a clean
    # checkout or CI environment is expected and not a violation.
    branch_root = _find_branch_root(path)
    logs_dir = branch_root / "logs"
    has_logs_dir = logs_dir.is_dir()
    if has_logs_dir:
        checks.append(
            {
                "name": "Branch-root logs/ directory",
                "passed": True,
                "message": f"logs/ directory exists at branch root {branch_root}/",
            }
        )

    # Check 2-3: Scan file for hardcoded log paths
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        checks.append({"name": "File readable", "passed": False, "message": f"Error reading file: {e}"})
        passed = all(c["passed"] for c in checks)
        score = int(sum(1 for c in checks if c["passed"]) / len(checks) * 100)
        return {"passed": passed, "checks": checks, "score": score, "standard": "LOG_STRUCTURE"}

    lines = content.split("\n")

    # Check 2: No hardcoded absolute log paths
    abs_log_issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments and docstrings
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # Look for absolute paths in log-related contexts
        if re.search(r'["\'][/\\](?:home|tmp|var|etc)[/\\].*\.log', stripped):
            abs_log_issues.append(i)

    checks.append(
        {
            "name": "No hardcoded log paths",
            "passed": len(abs_log_issues) == 0,
            "message": "No hardcoded absolute log paths found"
            if not abs_log_issues
            else f"Hardcoded log paths on lines: {abs_log_issues}",
        }
    )

    # Check 3: No /home/ references in logging setup
    home_log_issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # Look for /home/ in log file handler or path config
        if re.search(r"/home/\w+", stripped) and ("log" in stripped.lower() or "LOG" in stripped):
            home_log_issues.append(i)

    checks.append(
        {
            "name": "No /home/ in log config",
            "passed": len(home_log_issues) == 0,
            "message": "No /home/ references in logging configuration"
            if not home_log_issues
            else f"/home/ references in log config on lines: {home_log_issues}",
        }
    )

    passed = all(c["passed"] for c in checks)
    score = int(sum(1 for c in checks if c["passed"]) / len(checks) * 100) if checks else 0
    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "log_structure"}
    )
    return {"passed": passed, "checks": checks, "score": score, "standard": "LOG_STRUCTURE"}


# Written into every dispatched branch's logs/ by @ai_mail's dispatch machinery,
# not by the branch. Counting them made the audit's own delivery mechanism
# manufacture the observation: @cli was reported as having 3 local logs on the
# night it was dispatched, when it has none of its own.
_MAIL_LANE_LOG_PREFIX = "dispatch_"


def _is_mail_lane_artifact(log_file: Path) -> bool:
    """Return True if *log_file* belongs to @ai_mail's lane rather than the branch."""
    return log_file.name.startswith(_MAIL_LANE_LOG_PREFIX)


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored signpost lines for the log structure standard.

    Two-tier model:
      - system_logs/ at repo root is managed by prax (runtime dispatch).
      - logs/ at branch root holds local-only logs.

    "Local logs, no system logs" used to be a branch-level VIOLATION worth 50.
    It is reported here instead, and the reasons are two:

    1. It is not always a defect. @cli's modules cannot import prax at all
       (circular: prax depends on cli), so every prax call site lives in cli.py
       and every one of them is a failure path — logger.error on module-load
       failure, logger.warning on KeyboardInterrupt, logger.error on an
       unhandled exception. A HEALTHY @cli emits zero system logs BY
       CONSTRUCTION: the zero is the success case, not a symptom.

    2. It was not a function of the CODE. The count comes from live log files,
       so a branch's score moved when logs rotated or were cleared with nothing
       edited — @cli read 100% one morning and 50% the same evening with the
       structural facts about their code identical on both days. A score that
       moves on its own is worse than a wrong score, because nobody can act on
       it. Everything else this standard checks reads the source and stays
       scored.

    Returns plain strings on the audit's info channel (see
    architecture_check.check_branch_info for the pattern), so it can never
    reach a score by construction.

    Args:
        branch_path: Branch root to inspect.

    Returns:
        List of info lines, empty when there is nothing to signpost.
    """
    bp = Path(branch_path)
    local_logs = [f for f in bp.rglob("*.log") if f.parent.name == "logs" and not _is_mail_lane_artifact(f)]
    if not local_logs:
        return []

    repo = next(
        (p for p in [bp] + list(bp.parents) if (p / "AIPASS_REGISTRY.json").is_file()),
        None,
    )
    if repo is None or not (repo / "system_logs").is_dir():
        return []

    sd = repo / "system_logs"
    if list(sd.glob(f"{bp.name}_*.log")):
        return []
    return [
        f"{bp.name}: {len(local_logs)} local log(s) under logs/, 0 system log(s) in {sd}/ — "
        "prax writes a system log only when something calls it, so a branch whose prax call sites "
        "are all failure paths shows zero here by design. Runtime observation, not scored."
    ]
