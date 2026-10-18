# =================== AIPass ====================
# Name: verdicts.py
# Description: Which checkers judge a file in the per-file checklist, and how a failure reads
# Version: 1.1.0
# Created: 2026-10-03
# Modified: 2026-10-17
# =============================================

"""Which checkers judge a file in the per-file checklist, and how a failure reads.

checklist.py binds each function under its old private name; returns values, never prints.
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


def reads_text_file(checker, file_path: str) -> bool:
    """Whether a ``TEXT_FILES = True`` checker judges this non-.py file; no ``is_text_target`` means no."""
    # Literally True: a stand-in object whose every attribute is truthy declares nothing.
    if getattr(checker, "TEXT_FILES", False) is not True:
        return False
    is_text_target = getattr(checker, "is_text_target", None)
    return bool(is_text_target and is_text_target(file_path))


def is_applicable(checker, file_path: str) -> bool:
    """Determine if a checker applies to the given file.

    APPLIES_TO goes through applicability.py so this lane and the audit lane agree on scope.
    """
    if not applicability.applies_to_file(checker, file_path):
        return False

    scope = getattr(checker, "AUDIT_SCOPE", "entry_point")

    if scope == "branch_level":
        return hasattr(checker, "check_module") and file_path.endswith(".py")

    if not hasattr(checker, "check_module"):
        return False

    if scope == "all_files":
        return file_path.endswith(".py") or reads_text_file(checker, file_path)

    return is_entry_point(file_path)


def format_failure(result: Dict) -> str:
    """Extract a concise one-line failure description from checker result."""
    checks = result.get("checks", [])
    failed = [c for c in checks if not c.get("passed", False)]

    if not failed:
        return "Failed (no details)"

    msg = failed[0].get("message", "Unknown issue")

    if len(failed) > 1:
        msg = f"{msg} (+{len(failed) - 1} more)"

    return msg


def is_skip_or_error(results: List[Dict]) -> bool:
    """Whether the checklist declined the file (skip/error) or judged nothing."""
    if not results:
        return True
    return any(r.get("standard") in ("(skip)", "(error)") for r in results)
