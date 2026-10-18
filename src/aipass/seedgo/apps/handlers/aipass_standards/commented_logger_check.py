# =================== AIPass ====================
# Name: commented_logger_check.py
# Description: Commented Logger Standards Checker Handler
# Version: 1.1.0
# Created: 2026-03-22
# Modified: 2026-10-18
# =============================================

"""
Commented Logger Standards Checker Handler

Reference: commented_logger.md
"""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify

# APPLIES_TO: a commented-out logger call is dead weight in any file.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

_COMMENTED_LOGGER_RE = re.compile(r"#\s*logger\.(error|warning|warn|info|exception|critical|debug)\s*\(")


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for commented-out logger calls."""
    path = Path(module_path)

    if is_bypassed(module_path, "commented_logger", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "COMMENTED_LOGGER",
        }

    if path.suffix != ".py" or path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Commented logger calls",
                    "passed": True,
                    "message": "File skipped (non-target)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "COMMENTED_LOGGER",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "COMMENTED_LOGGER",
        }

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

    violation_lines: list[int] = []
    # Comments are this checker's target, so only docstrings and string bodies are skipped.
    try:
        kinds = classify(source)
        skipped = kinds.docstrings | kinds.string_bodies
    except UnparseableSource as exc:
        logger.info("commented_logger: unparseable, every line read: %s", exc)
        skipped = frozenset()

    for lineno, line in enumerate(source.splitlines(), start=1):
        if lineno in skipped:
            continue

        if _COMMENTED_LOGGER_RE.search(line):
            violation_lines.append(lineno)

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

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "commented_logger"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "COMMENTED_LOGGER"}
