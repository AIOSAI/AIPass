# =================== AIPass ====================
# Name: verdicts.py
# Description: Which checkers judge a file in the per-file checklist, and how a failure reads
# Version: 1.0.0
# Created: 2026-10-03
# Modified: 2026-10-03
# =============================================

"""Which checkers judge a file in the per-file checklist, and how a failure reads.

Moved out of apps/modules/checklist.py when it passed the 600-line cap (seedgo
fleet green leg 15). The checklist binds each function under its old private
name, so ``checklist._format_failure`` and the rest still answer from there.
Returns values, NEVER prints: the printing stays in the module.
"""

from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.aipass_standards import applicability


def is_entry_point(file_path: str) -> bool:
    """Check if file is an entry point: apps/{name}.py (directly in apps/, not subdirectory)."""
    p = Path(file_path)
    if not p.name.endswith(".py"):
        return False
    if "apps/" not in file_path.replace("\\", "/"):
        return False
    return p.parent.name == "apps"


def is_applicable(checker, file_path: str) -> bool:
    """Determine if a checker applies to the given file.

    First gate is APPLIES_TO — whether the standard is meaningful for this
    KIND of file (production / tests / everywhere), shared with the audit lane
    via applicability.py so the two can never disagree about scope again.
    Structural standards used to fail on nearly every test file in the fleet
    here while the audit lane never even looked at tests/; that gap is what
    branches were absorbing with bypass rules.

    Then AUDIT_SCOPE — where a result is reported:
      - "entry_point" (default) -> only apps/{name}.py files
      - "all_files"             -> any .py file
      - "branch_level"          -> normally skipped, but eligible if checker
                                   also implements check_module() for per-file use
    """
    if not applicability.applies_to_file(checker, file_path):
        return False

    scope = getattr(checker, "AUDIT_SCOPE", "entry_point")

    # Branch-level checkers skip per-file runs UNLESS they also implement
    # check_module() for targeted single-file validation (e.g., ruff_check)
    if scope == "branch_level":
        return hasattr(checker, "check_module") and file_path.endswith(".py")

    # Only check_module() capable checkers
    if not hasattr(checker, "check_module"):
        return False

    if scope == "all_files":
        return file_path.endswith(".py")

    # Default: entry_point scope
    return is_entry_point(file_path)


def format_failure(result: Dict) -> str:
    """Extract a concise one-line failure description from checker result."""
    checks = result.get("checks", [])
    failed = [c for c in checks if not c.get("passed", False)]

    if not failed:
        return "Failed (no details)"

    # Use first failure's message, trimmed
    msg = failed[0].get("message", "Unknown issue")

    # If multiple failures, indicate count
    if len(failed) > 1:
        msg = f"{msg} (+{len(failed) - 1} more)"

    return msg


def is_skip_or_error(results: List[Dict]) -> bool:
    """Whether the checklist declined the file (skip/error) or judged nothing.

    A skipped file (throwaway, retired, prototype, ignored, not Python) was
    judged by nothing, so naming the few rows it was not judged by would
    mislead in the other direction.
    """
    if not results:
        return True
    return any(r.get("standard") in ("(skip)", "(error)") for r in results)
