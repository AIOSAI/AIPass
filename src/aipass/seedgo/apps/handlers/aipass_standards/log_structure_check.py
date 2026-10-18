# =================== AIPass ====================
# Name: log_structure_check.py
# Description: Log Structure Standards Checker Handler
# Version: 1.2.0
# Created: 2026-03-06
# Modified: 2026-10-17
# =============================================

"""
Log Structure Standards Checker Handler

Reference: log_structure.md
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: message format is a product decision.
APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"


def _find_branch_root(file_path: Path) -> Path:
    """Walk up from file to find branch root (directory containing apps/).

    Falls back to the file's parent when no ``apps/`` directory is found within 10 levels.
    """
    current = file_path.resolve().parent
    for _ in range(10):  # Safety limit
        if (current / "apps").is_dir():
            return current
        if current == current.parent:
            break
        current = current.parent
    return file_path.parent


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check module logging structure against the two-tier model."""
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

    # logs/ is gitignored (created on first log write): absence in a clean checkout or CI is not a violation.
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

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        checks.append({"name": "File readable", "passed": False, "message": f"Error reading file: {e}"})
        passed = all(c["passed"] for c in checks)
        score = int(sum(1 for c in checks if c["passed"]) / len(checks) * 100)
        return {"passed": passed, "checks": checks, "score": score, "standard": "LOG_STRUCTURE"}

    lines = content.split("\n")

    abs_log_issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
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

    home_log_issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
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


# Written into every dispatched branch's logs/ by @ai_mail's dispatch machinery, not by the branch;
# counting them would make the audit's own delivery mechanism manufacture the observation.
_MAIL_LANE_LOG_PREFIX = "dispatch_"


def _is_mail_lane_artifact(log_file: Path) -> bool:
    """Return True if *log_file* belongs to @ai_mail's lane rather than the branch."""
    return log_file.name.startswith(_MAIL_LANE_LOG_PREFIX)


def _system_log_dir(branch_path: Path) -> Path | None:
    """The repo's system_logs/ directory, or None when there is nothing to read.

    Outside a repo (no AIPASS_REGISTRY.json above, or no system_logs/) there is no second tier to compare.
    """
    repo = next(
        (p for p in [branch_path] + list(branch_path.parents) if (p / "AIPASS_REGISTRY.json").is_file()),
        None,
    )
    if repo is None:
        return None
    sd = repo / "system_logs"
    return sd if sd.is_dir() else None


def check_branch_observe(branch_path: str, bypass_rules: list | None = None) -> list[dict]:
    """Observe-only system-log reading. Gathers the data, moves no score.

    Reported on a channel branch_audit keeps out of scores[] and the average. It accepts ``bypass_rules``
    because the pipeline calls branch-level hooks as ``hook(path, bypass_rules=...)``. Every record carries
    ``observed_at`` (live .log files rotate with no code change) and a reading is emitted on every audit, so
    "never fired" can be told from "never ran". A bypassing branch is recorded as bypassed, with no score.
    """
    bp = Path(branch_path)
    record: dict = {
        "standard": "log_structure",
        "branch": bp.name,
        "observed_at": datetime.now().isoformat(timespec="seconds"),
        "bypassed": False,
        "observable": False,
        "local_logs": 0,
        "system_logs": 0,
        "would_be_score": None,
    }

    if is_bypassed(str(bp), "log_structure", bypass_rules=bypass_rules):
        record["bypassed"] = True
        return [record]

    local_logs = [f for f in bp.rglob("*.log") if f.parent.name == "logs" and not _is_mail_lane_artifact(f)]
    record["local_logs"] = len(local_logs)

    sd = _system_log_dir(bp)
    if sd is None:
        # A reading with nothing to read is not a 100.
        return [record]

    record["observable"] = True
    record["system_logs"] = len(list(sd.glob(f"{bp.name}_*.log")))
    record["would_be_score"] = 50 if (local_logs and record["system_logs"] == 0) else 100
    return [record]


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored signpost lines for the log structure standard.

    Local logs with no system logs is info, not a violation: it is not always a defect (@cli cannot import
    prax, so a healthy @cli emits zero system logs) and it reads live log files, so it moves with no edit.
    Plain strings on the info channel, so it can never reach a score.
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
