# =================== AIPass ====================
# Name: verdicts.py
# Description: Which checkers judge a file in the per-file checklist, and how a failure reads
# Version: 1.1.1
# Created: 2026-10-03
# Modified: 2026-10-24
# =============================================

"""Which checkers judge a file in the per-file checklist, and how a failure reads.

checklist.py binds each function under its old private name; returns values, never prints.
"""

from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.aipass_standards import applicability


def is_entry_point(file_path: str) -> bool:
    """Whether the file is its branch's entry file by the audit's rule; the branch is the directory above apps/."""
    p = Path(file_path)
    if p.parent.name != "apps":
        return False
    preferred, fallback = applicability.entry_file_names(p.parent.parent.name)
    if p.name == preferred:
        return True
    return p.name == fallback and not (p.parent / preferred).exists()


def failed_checks(result: Dict) -> List[Dict]:
    """The checks a result failed: what both lanes report, whatever the checker's own ``passed`` says."""
    return [c for c in result.get("checks", []) if not c.get("passed", False)]


def judged_passed(result: Dict) -> bool:
    """A row passes when no check failed; a result with no checks answers with its own ``passed``."""
    if result.get("checks"):
        return not failed_checks(result)
    return bool(result.get("passed", True))


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
    failed = failed_checks(result)

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
