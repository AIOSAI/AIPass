# =================== AIPass ====================
# Name: commented_logger_check.py
# Description: Commented Logger Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Commented Logger Standards Checker Handler

Detects commented-out logger calls in Python files. Lines like:

    # logger.error(...)
    # logger.warning(...)
    # logger.info(...)
    # logger.debug(...)
    # logger.critical(...)
    # logger.exception(...)

These indicate intentionally disabled logging that should either be
restored or removed entirely -- dead logging is noise.
"""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: scan every .py file, not just entry point
AUDIT_SCOPE = "all_files"

# Regex extracted from devpulse commented_logger_scanner_v1.py
_COMMENTED_LOGGER_RE = re.compile(r"#\s*logger\.(error|warning|warn|info|exception|critical|debug)\s*\(")


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed."""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check a Python file for commented-out logger calls.

    Scans every non-docstring, non-__init__.py line for patterns like
    ``# logger.error(...)``.  One check is produced per file: passed if
    zero violations, failed if any found (message includes count and
    first three line numbers).

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': str
        }
    """
    path = Path(module_path)

    # --- bypass -----------------------------------------------------------
    if is_bypassed(module_path, "commented_logger", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "COMMENTED_LOGGER",
        }

    # --- skip non-.py and __init__.py -------------------------------------
    if path.suffix != ".py" or path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "Commented logger calls", "passed": True, "message": "File skipped (non-target)"}],
            "score": 100,
            "standard": "COMMENTED_LOGGER",
        }

    # --- file exists ------------------------------------------------------
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "COMMENTED_LOGGER",
        }

    # --- read file --------------------------------------------------------
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "COMMENTED_LOGGER",
        }

    # --- scan for commented-out logger calls, skipping docstrings ---------
    violation_lines: list[int] = []
    in_docstring = False

    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()

        # Track triple-quote docstring boundaries
        triple_count = stripped.count('"""') + stripped.count("'''")
        if triple_count == 1:
            in_docstring = not in_docstring
            continue
        if triple_count >= 2:
            # Opening and closing on same line -- not inside docstring
            continue
        if in_docstring:
            continue

        if _COMMENTED_LOGGER_RE.search(line):
            violation_lines.append(lineno)

    # --- build result -----------------------------------------------------
    checks = []
    violation_count = len(violation_lines)

    if violation_count == 0:
        checks.append(
            {"name": "Commented logger calls", "passed": True, "message": "No commented-out logger calls found"}
        )
    else:
        first_three = violation_lines[:3]
        line_preview = ", ".join(str(ln) for ln in first_three)
        suffix = f" (and {violation_count - 3} more)" if violation_count > 3 else ""
        checks.append(
            {
                "name": "Commented logger calls",
                "passed": False,
                "message": f"{violation_count} commented-out logger call(s) on lines {line_preview}{suffix} -- restore or remove",
            }
        )

    # --- score ------------------------------------------------------------
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "commented_logger"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "COMMENTED_LOGGER"}
