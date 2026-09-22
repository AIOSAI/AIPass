# =================== AIPass ====================
# Name: help_text_check.py
# Description: Help Text Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Help Text Standards Checker Handler

Detects user-facing string literals that reference ``python3`` or ``python``
as a command instruction (e.g. "python3 tools/scanner.py").  These should
tell the user to run commands via ``drone @branch`` instead.

Shebangs, import statements, and Python API references (like "python version")
are excluded.  Only instructional command invocations are flagged.

One check per file -- passed if zero references found, failed with a count
and the first three offending line numbers.
"""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: --help content; a test file has none.
APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

# ── Detection patterns (extracted from devpulse help_text_scanner_v1) ───

# Lines to always skip
_SHEBANG_RE = re.compile(r"^\s*#!")
_COMMENT_RE = re.compile(r"^\s*#")

# Single-line string literals (single or double quoted)
_STRING_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"|'  # double-quoted
    r"'(?:[^'\\]|\\.)*'",  # single-quoted
)

# Instructional python command references inside string content
_PYTHON3_CMD_RE = re.compile(r"\bpython3\s+\S")
_PYTHON_CMD_RE = re.compile(r"\bpython\s+(?:-[a-zA-Z]|\S+\.py)")

# Triple-quote delimiters
_TRIPLE_DOUBLE = '"""'
_TRIPLE_SINGLE = "'''"


def _has_python_instruction(text: str) -> bool:
    """Return True if *text* contains a python3/python command reference."""
    return bool(_PYTHON3_CMD_RE.search(text) or _PYTHON_CMD_RE.search(text))


def _strings_on_line(line: str) -> list[str]:
    """Return all single-line string literal tokens found on a source line."""
    return [m.group(0) for m in _STRING_RE.finditer(line)]


def _line_has_python_instruction(line: str) -> bool:
    """Check single-line string literals on *line* for python command refs."""
    return any(_has_python_instruction(s) for s in _strings_on_line(line))


# ── Bypass helper ───────────────────────────────────────────────────────


# ── Main checker entry point ────────────────────────────────────────────


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check a Python file for user-facing help text that references python3/python
    commands instead of ``drone @branch``.

    Args:
        module_path: Path to the Python file to check.
        bypass_rules: Optional list of bypass rules to skip certain checks.

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': str,
        }
    """
    path = Path(module_path)

    # Skip __init__.py files
    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Help text references",
                    "passed": True,
                    "message": "__init__.py skipped",
                }
            ],
            "score": 100,
            "standard": "HELP_TEXT",
        }

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "help_text", bypass_rules=bypass_rules):
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
            "standard": "HELP_TEXT",
        }

    # Validate file exists
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
            "standard": "HELP_TEXT",
        }

    # Read file
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [
                {
                    "name": "File readable",
                    "passed": False,
                    "message": f"Error reading file: {e}",
                }
            ],
            "score": 0,
            "standard": "HELP_TEXT",
        }

    lines = content.splitlines()
    violation_lines: list[int] = []

    # State machine for multiline strings (mirrors scanner logic)
    in_multiline: bool = False
    multiline_delim: str = ""

    for lineno, raw_line in enumerate(lines, start=1):
        # --- Inside a multiline string block ---
        if in_multiline:
            if multiline_delim in raw_line:
                in_multiline = False
                multiline_delim = ""
            # Check content inside multiline strings (skip comment-only lines)
            if not _COMMENT_RE.match(raw_line) and _has_python_instruction(raw_line):
                if not is_bypassed(module_path, "help_text", lineno, bypass_rules):
                    violation_lines.append(lineno)
            continue

        # --- Normal line handling ---

        # Skip shebangs and pure-comment lines
        if _SHEBANG_RE.match(raw_line) or _COMMENT_RE.match(raw_line):
            continue

        # Check for opening triple-quote that does NOT close on the same line
        for delim in (_TRIPLE_DOUBLE, _TRIPLE_SINGLE):
            if delim in raw_line:
                count = raw_line.count(delim)
                if count % 2 == 1:
                    in_multiline = True
                    multiline_delim = delim
                break

        # Check single-line string literals for python command references
        if _line_has_python_instruction(raw_line):
            if not is_bypassed(module_path, "help_text", lineno, bypass_rules):
                violation_lines.append(lineno)

    # Build the single check result
    total_found = len(violation_lines)

    if total_found == 0:
        check_result = {
            "name": "Help text references",
            "passed": True,
            "message": "No python3/python command references in help text",
        }
    else:
        first_three = ", ".join(str(ln) for ln in violation_lines[:3])
        suffix = f" (and {total_found - 3} more)" if total_found > 3 else ""
        check_result = {
            "name": "Help text references",
            "passed": False,
            "message": (
                f"Found {total_found} python3/python command "
                f"reference{'s' if total_found != 1 else ''} in help text "
                f"on line{'s' if total_found != 1 else ''} {first_three}{suffix} "
                f"-- should use drone @branch instead"
            ),
        }

    checks = [check_result]

    # Score: one check, so 100 if passed, 0 if failed
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "help_text"},
    )
    return {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "HELP_TEXT",
    }
