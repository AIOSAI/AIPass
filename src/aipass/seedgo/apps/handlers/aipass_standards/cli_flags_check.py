# =================== AIPass ====================
# Name: cli_flags_check.py
# Description: CLI Flags Standards Checker Handler
# Version: 1.2.0
# Created: 2026-03-05
# Modified: 2026-10-18
# =============================================

"""
CLI Flags Standards Checker Handler

Validates that branch entry points support --version / -V; --help is cli_check's to judge.
"""

import re
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify

# APPLIES_TO: entry-point flags; a test file has no --help.
APPLIES_TO = "production"
AUDIT_SCOPE = "entry_point"

_EMPTY_MARKER = "Package marker with no code (skipped)"


def _is_empty_package_marker(path: Path, content: str) -> bool:
    """Whether this is an ``__init__.py`` whose every line is blank or a comment.

    A package marker with no code has no --version to ask for; one that carries code,
    even a docstring, is still read as an entry point.
    """
    lines = (line.strip() for line in content.splitlines())
    return path.name == "__init__.py" and all(not line or line.startswith("#") for line in lines)


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows CLI flags standards"""
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, "cli_flags", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "CLI_FLAGS",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "CLI_FLAGS",
        }

    if path.parent.name != "apps":
        return {
            "passed": True,
            "checks": [{"name": "Entry point check", "passed": True, "message": "Not an entry point (skipped)"}],
            "score": 100,
            "standard": "CLI_FLAGS",
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
            "standard": "CLI_FLAGS",
        }

    if _is_empty_package_marker(path, content):
        return {
            "passed": True,
            "checks": [{"name": "Entry point check", "passed": True, "message": _EMPTY_MARKER}],
            "score": 100,
            "standard": "CLI_FLAGS",
        }

    version_flag_check = check_version_flag(lines, module_path, bypass_rules)
    checks.append(version_flag_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "cli_flags"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "CLI_FLAGS"}


def check_version_flag(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that the entry point supports --version / -V flag."""
    if is_bypassed(file_path, "cli_flags", None, bypass_rules):
        return {"name": "--version flag support", "passed": True, "message": "Bypassed by bypass rules"}

    # A flag named in a docstring or inside help text's string body is not flag handling.
    try:
        kinds = classify("\n".join(lines))
    except UnparseableSource as exc:
        logger.info("cli_flags: --version unread, unparseable: %s", exc)
        return {"name": "--version flag support", "passed": False, "message": f"Source does not parse: {exc}"}
    skip_lines = kinds.prose | kinds.string_bodies

    version_patterns = [
        r"""['"]--version['"]""",
        r"""['"]-V['"]""",
    ]

    for i, line in enumerate(lines, 1):
        if i in skip_lines:
            continue

        for pattern in version_patterns:
            if re.search(pattern, line):
                return {
                    "name": "--version flag support",
                    "passed": True,
                    "message": f"Found version flag handling on line {i}",
                }

    return {
        "name": "--version flag support",
        "passed": False,
        "message": "Entry point missing --version / -V flag support",
    }
