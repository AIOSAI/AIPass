# =================== AIPass ====================
# Name: debug_print_check.py
# Description: Debug Print Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Debug Print Standards Checker Handler

Detects bare print() calls that should use structured logging (Prax/Rich).
Excludes lines inside docstrings, comments, doctests, and
``if __name__ == "__main__":`` blocks.
"""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"

# Matches a bare print( call: not preceded by a word char, dot, or #
# This excludes console.print(, logger.print(, etc.
_PRINT_RE = re.compile(r"(?<![.#\w])print\(")

# Doctest / interactive example lines to skip (>>> and ...)
_DOCTEST_RE = re.compile(r"^\s*(\.\.\.|>>>)\s")

# Test file name patterns
_TEST_FILE_RE = re.compile(r"^(test_.+|.+_test|conftest)\.py$")


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed."""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        # Must match standard
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        # Must match file (check if rule file path is in the full path)
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        # Check line-specific bypass
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def _is_in_main_block(lines: list[str], lineno: int) -> bool:
    """
    Return True if the line at *lineno* (1-based) is inside an
    ``if __name__ == "__main__":`` block.

    Uses indentation: the flagged line must have greater indentation than the
    ``if __name__`` header found by scanning backwards.
    """
    main_block_indent: int | None = None
    for i in range(lineno - 2, -1, -1):  # scan backwards (0-based)
        stripped = lines[i].strip()
        if re.match(r'if\s+__name__\s*==\s*["\']__main__["\']', stripped):
            main_block_indent = len(lines[i]) - len(lines[i].lstrip())
            break

    if main_block_indent is None:
        return False

    target_line = lines[lineno - 1]
    if not target_line.strip():
        return False
    target_indent = len(target_line) - len(target_line.lstrip())
    return target_indent > main_block_indent


def _scan_file(file_path: Path) -> tuple[list[int], str | None]:
    """
    Scan a single .py file for bare print() calls.

    Returns:
        (line_numbers, error_message) -- error_message is None on success.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("Cannot read %s: %s", file_path, exc)
        return [], f"cannot read: {exc}"

    lines = source.splitlines()
    hit_lines: list[int] = []
    in_docstring = False
    docstring_char: str | None = None  # '"""' or "'''"

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()

        # -- Docstring state machine --
        for tq in ('"""', "'''"):
            count = line.count(tq)
            if count == 0:
                continue
            if not in_docstring:
                in_docstring = True
                docstring_char = tq
                # Opening and closing on the same line (one-liner)
                if count >= 2:
                    in_docstring = False
                    docstring_char = None
            elif docstring_char == tq:
                in_docstring = False
                docstring_char = None

        if in_docstring:
            continue

        # Skip comment lines
        if stripped.startswith("#"):
            continue

        # Skip doctest / interactive example lines
        if _DOCTEST_RE.match(line):
            continue

        # Strip inline comments before checking for print(
        code_part = line.split("#")[0]

        if not _PRINT_RE.search(code_part):
            continue

        # Skip if inside `if __name__ == "__main__":` block
        if _is_in_main_block(lines, lineno):
            continue

        hit_lines.append(lineno)

    return hit_lines, None


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check a Python file for bare debug print() calls.

    Args:
        module_path: Path to the Python file to check.
        bypass_rules: Optional list of bypass rules to skip certain checks.

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': 'DEBUG_PRINT'
        }
    """
    path = Path(module_path)

    # -- Bypass entire standard for this file --
    if is_bypassed(module_path, "debug_print", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "DEBUG_PRINT",
        }

    # -- Skip __init__.py --
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Debug print calls",
                    "passed": True,
                    "message": "__init__.py skipped",
                }
            ],
            "score": 100,
            "standard": "DEBUG_PRINT",
        }

    # -- Skip test files --
    if _TEST_FILE_RE.match(path.name):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Debug print calls",
                    "passed": True,
                    "message": "Test file skipped",
                }
            ],
            "score": 100,
            "standard": "DEBUG_PRINT",
        }

    # -- Validate file exists --
    if not path.exists():
        return {
            "passed": False,
            "checks": [
                {
                    "name": "File exists",
                    "passed": False,
                    "message": f"File not found: {module_path}",
                }
            ],
            "score": 0,
            "standard": "DEBUG_PRINT",
        }

    # -- Scan --
    hit_lines, error = _scan_file(path)

    if error is not None:
        return {
            "passed": False,
            "checks": [
                {
                    "name": "File readable",
                    "passed": False,
                    "message": f"Error reading file: {error}",
                }
            ],
            "score": 0,
            "standard": "DEBUG_PRINT",
        }

    # -- Filter out bypassed lines --
    non_bypassed = [ln for ln in hit_lines if not is_bypassed(module_path, "debug_print", ln, bypass_rules)]

    # -- Build result --
    checks: list[Dict] = []

    if not non_bypassed:
        checks.append(
            {
                "name": "Debug print calls",
                "passed": True,
                "message": "No bare print() calls found",
            }
        )
    else:
        sample = ", ".join(str(ln) for ln in non_bypassed[:3])
        suffix = f" (and {len(non_bypassed) - 3} more)" if len(non_bypassed) > 3 else ""
        checks.append(
            {
                "name": "Debug print calls",
                "passed": False,
                "message": (f"{len(non_bypassed)} bare print() call(s) on lines {sample}{suffix}"),
            }
        )

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int(passed_checks / total_checks * 100) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "debug_print"},
    )

    return {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "DEBUG_PRINT",
    }
