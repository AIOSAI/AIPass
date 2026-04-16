# =================== AIPass ====================
# Name: todo_check.py
# Description: TODO/FIXME Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
TODO/FIXME Standards Checker Handler

Detects TODO, FIXME, HACK, and XXX comments in Python source files.
These tags indicate incomplete work, known hacks, or code needing attention.
Each file is scored: passed if zero tags found, failed otherwise with
a count and tag breakdown in the message.
"""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "all_files"

# Tags to detect, case-insensitive
_TAGS = ("TODO", "FIXME", "HACK", "XXX")

# Regex: matches # TODO: text, # FIXME(user): text, inline # HACK ..., etc.
# Captures (tag, comment_text). Handles inline and standalone comments.
_TAG_RE = re.compile(
    r"#\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)",
    re.IGNORECASE,
)


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


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check a Python file for TODO/FIXME/HACK/XXX comments.

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
                    "name": "TODO/FIXME comments",
                    "passed": True,
                    "message": "__init__.py skipped",
                }
            ],
            "score": 100,
            "standard": "TODO",
        }

    # Check if entire standard is bypassed for this file
    if is_bypassed(module_path, "todo", bypass_rules=bypass_rules):
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
            "standard": "TODO",
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
            "standard": "TODO",
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
            "standard": "TODO",
        }

    # Scan for TODO/FIXME/HACK/XXX tags in comment lines
    tag_counts: dict[str, int] = {}
    total_found = 0
    in_docstring = False
    docstring_char: str | None = None

    for line in content.splitlines():
        stripped = line.strip()

        # Track docstring boundaries
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                docstring_char = stripped[:3]
                # Single-line docstring: opens and closes on the same line
                if stripped.count(docstring_char) >= 2:
                    continue
                in_docstring = True
                continue
        else:
            if docstring_char and docstring_char in stripped:
                in_docstring = False
            continue

        # Only match in comment portions (the regex already requires #)
        match = _TAG_RE.search(line)
        if match:
            tag = match.group(1).upper()
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            total_found += 1

    # Build the single check result
    if total_found == 0:
        check_result = {
            "name": "TODO/FIXME comments",
            "passed": True,
            "message": "No TODO/FIXME/HACK/XXX comments found",
        }
    else:
        breakdown = ", ".join(f"{tag}: {count}" for tag in _TAGS if (count := tag_counts.get(tag, 0)) > 0)
        check_result = {
            "name": "TODO/FIXME comments",
            "passed": False,
            "message": f"Found {total_found} TODO-type comment{'s' if total_found != 1 else ''} ({breakdown})",
        }

    checks = [check_result]

    # Score: one check, so 100 if passed, 0 if failed
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "todo"},
    )
    return {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "TODO",
    }
