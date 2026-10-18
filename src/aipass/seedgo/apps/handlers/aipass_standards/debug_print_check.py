# =================== AIPass ====================
# Name: debug_print_check.py
# Description: Debug Print Standards Checker Handler
# Version: 1.0.1
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""
Debug Print Standards Checker Handler

Reference: debug_print.md
"""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

# Not preceded by a word char, dot or #, so console.print( and logger.print( pass.
_PRINT_RE = re.compile(r"(?<![.#\w])print\(")

_DOCTEST_RE = re.compile(r"^\s*(\.\.\.|>>>)\s")

_TEST_FILE_RE = re.compile(r"^(test_.+|.+_test|conftest)\.py$")

# String literals — strip content before regex to avoid false positives on print( inside strings
_STRING_LITERAL_RE = re.compile(r'""".*?"""|\'\'\'.*?\'\'\'|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')


def _is_in_main_block(lines: list[str], lineno: int) -> bool:
    """Return True if the line at *lineno* (1-based) is inside an ``if __name__ == "__main__":`` block."""
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
    """Scan a single .py file for bare print() calls.
    Returns (line_numbers, error_message); error_message is None on success.
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

        for tq in ('"""', "'''"):
            count = line.count(tq)
            if count == 0:
                continue
            if not in_docstring:
                in_docstring = True
                docstring_char = tq
                if count >= 2:
                    in_docstring = False
                    docstring_char = None
            elif docstring_char == tq:
                in_docstring = False
                docstring_char = None

        if in_docstring:
            continue

        if stripped.startswith("#"):
            continue

        if _DOCTEST_RE.match(line):
            continue

        code_part = line.split("#")[0]
        code_part = _STRING_LITERAL_RE.sub('""', code_part)

        if not _PRINT_RE.search(code_part):
            continue

        if _is_in_main_block(lines, lineno):
            continue

        hit_lines.append(lineno)

    return hit_lines, None


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for bare debug print() calls."""
    path = Path(module_path)

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

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Debug print calls",
                    "passed": True,
                    "message": "__init__.py skipped",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "DEBUG_PRINT",
        }

    if _TEST_FILE_RE.match(path.name):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Debug print calls",
                    "passed": True,
                    "message": "Test file skipped",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "DEBUG_PRINT",
        }

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

    non_bypassed = [ln for ln in hit_lines if not is_bypassed(module_path, "debug_print", ln, bypass_rules)]

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
