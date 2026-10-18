# =================== AIPass ====================
# Name: permission_flags_check.py
# Description: Permission Flags Standards Checker Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-10-18
# =============================================

"""
Permission Flags Standards Checker Handler

Reference: permission_flags.md
"""

import re
from pathlib import Path
from typing import AbstractSet, Dict, List
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.prose_lines import UnparseableSource, hash_lines, prose_lines

# APPLIES_TO: a test that chmods 0o777 leaves the same hole.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"


def _get_non_code_lines(lines: List[str]) -> AbstractSet[int]:
    """Docstring and comment-only lines; a source that does not parse keeps every line but ``#`` ones."""
    source = "\n".join(lines)
    try:
        return prose_lines(source)
    except UnparseableSource as exc:
        logger.info("permission_flags: unparseable, only # lines are prose: %s", exc)
        return hash_lines(source)


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows permission flags standards"""
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, "permission_flags", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "PERMISSION_FLAGS",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "PERMISSION_FLAGS",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "PERMISSION_FLAGS",
        }

    has_permission_ref = re.search(
        r"skip.?permissions|dangerously.?skip|permission.?mode|bypass.?permission", content, re.IGNORECASE
    )
    if not has_permission_ref:
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Permission flags check",
                    "passed": True,
                    "message": "No permission flags found (skipped)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "PERMISSION_FLAGS",
        }

    dangerous_flags_check = check_no_dangerous_flags(lines, module_path, bypass_rules=bypass_rules)
    checks.append(dangerous_flags_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "permission_flags"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "PERMISSION_FLAGS"}


def check_no_dangerous_flags(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that no dangerous permission bypass flags are used."""
    dangerous_patterns = [
        r"dangerously.?skip.?permissions",
        r"--skip.?permissions",
        r"--no.?permissions",
        r"allow.?dangerously.?skip",
    ]

    violations = []
    skip_lines = _get_non_code_lines(lines)

    for i, line in enumerate(lines, 1):
        if i in skip_lines:
            continue

        for pattern in dangerous_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                if not is_bypassed(file_path, "permission_flags", i, bypass_rules):
                    violations.append(i)
                break

    if violations:
        return {
            "name": "No dangerous permission flags",
            "passed": False,
            "message": f"Dangerous permission bypass flags on lines {violations[:5]} - use --permission-mode bypassPermissions instead",
        }

    return {
        "name": "No dangerous permission flags",
        "passed": True,
        "message": "Only approved permission flags used (--permission-mode bypassPermissions)",
    }
