# =================== AIPass ====================
# Name: todo_check.py
# Description: TODO/FIXME Standards Checker Handler
# Version: 1.0.2
# Created: 2026-03-22
# Modified: 2026-10-17
# =============================================

"""
TODO/FIXME Standards Checker Handler

Reference: todo.md
"""

import io
import re
import tokenize
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: a TODO in a test is as unfinished as one in a module.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

_TAGS = ("TODO", "FIXME", "HACK", "XXX")

_TAG_RE = re.compile(
    r"#\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)",
    re.IGNORECASE,
)


def _comments(content: str) -> list[str] | None:
    """
    Return the text of every comment token in the source, or None.

    None means Python cannot tokenize the source (an unclosed string, a
    bad dedent), so which text is a comment is unknown; the caller fails
    the file by name rather than reading it as clean.
    """
    try:
        return [
            token.string
            for token in tokenize.generate_tokens(io.StringIO(content).readline)
            if token.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, SyntaxError) as e:
        logger.info("Cannot tokenize source: %s", e)
        return None


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for TODO/FIXME/HACK/XXX comments."""
    path = Path(module_path)

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "TODO/FIXME comments",
                    "passed": True,
                    "message": "__init__.py skipped",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "TODO",
        }

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

    # Tokenizer, not a line scan: a tag inside a string or docstring is no COMMENT token.
    comments = _comments(content)
    if comments is None:
        return {
            "passed": False,
            "checks": [
                {
                    "name": "File tokenizable",
                    "passed": False,
                    "message": "Python cannot tokenize this file, so its comments are unknown",
                }
            ],
            "score": 0,
            "standard": "TODO",
        }

    tag_counts: dict[str, int] = {}
    total_found = 0
    for comment in comments:
        match = _TAG_RE.search(comment)
        if match:
            tag = match.group(1).upper()
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            total_found += 1

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
