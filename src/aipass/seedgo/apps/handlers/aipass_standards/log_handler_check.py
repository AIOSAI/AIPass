# =================== AIPass ====================
# Name: log_handler_check.py
# Description: Log Handler Standards Checker Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-10-18
# =============================================

"""
Log Handler Standards Checker Handler

Reference: log_handler.md
"""

import re
from pathlib import Path
from typing import AbstractSet, Dict, List
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify, hash_lines

# APPLIES_TO: a test importing stdlib logging to assert on it is legitimate.
APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module follows log handler standards"""
    checks = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "log_handler", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "LOG_HANDLER",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "LOG_HANDLER",
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
            "standard": "LOG_HANDLER",
        }

    has_handler_setup = re.search(
        r"logging\.(FileHandler|StreamHandler)\s*\(|"
        r"\.addHandler\s*\(",
        content,
    )
    if not has_handler_setup:
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Log handler check",
                    "passed": True,
                    "message": "No log handler setup found (skipped)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "LOG_HANDLER",
        }

    # Exempt prax logging infrastructure (it IS the RotatingFileHandler implementation)
    if "prax" in module_path and ("logging" in module_path or "setup.py" in module_path or "terminal" in module_path):
        return {
            "passed": True,
            "checks": [
                {"name": "Log handler check", "passed": True, "message": "Prax logging infrastructure (exempt)"}
            ],
            "score": 100,
            "standard": "LOG_HANDLER",
        }

    file_handler_check = check_no_raw_file_handler(lines, module_path, bypass_rules=bypass_rules)
    checks.append(file_handler_check)

    stream_handler_check = check_no_raw_stream_handler(lines, module_path, content, bypass_rules=bypass_rules)
    checks.append(stream_handler_check)

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "log_handler"})
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "LOG_HANDLER"}


def _prose(lines: List[str]) -> AbstractSet[int]:
    """Prose and string-body lines; a source that does not parse keeps every line but ``#`` ones."""
    source = "\n".join(lines)
    try:
        return classify(source).text_only
    except UnparseableSource as exc:
        logger.info("log_handler: unparseable, only # lines are prose: %s", exc)
        return hash_lines(source)


def check_no_raw_file_handler(lines: List[str], file_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that no raw logging.FileHandler is used. Must use RotatingFileHandler instead."""
    violations = []
    prose = _prose(lines)

    for i, line in enumerate(lines, 1):
        if i in prose:
            continue

        if re.search(r"logging\.FileHandler\s*\(", line):
            if not is_bypassed(file_path, "log_handler", i, bypass_rules):
                violations.append(i)

    if violations:
        return {
            "name": "No raw FileHandler",
            "passed": False,
            "message": f"Raw logging.FileHandler on lines {violations[:5]} - use RotatingFileHandler via prax system_logger",
        }

    return {"name": "No raw FileHandler", "passed": True, "message": "No raw logging.FileHandler found"}


def check_no_raw_stream_handler(
    lines: List[str], file_path: str, content: str, bypass_rules: list | None = None
) -> Dict:
    """Check that logging.StreamHandler is not used for log file output."""
    # Only flag StreamHandler if the file also sets up file-based logging
    has_file_logging = bool(
        re.search(
            r"logging\.(FileHandler|RotatingFileHandler)\s*\(|"
            r'system_logs|\.log["\']',
            content,
        )
    )
    if not has_file_logging:
        return {
            "name": "No raw StreamHandler with file logging",
            "passed": True,
            "message": "No file-based logging setup found (check not applicable)",
            "declined": True,
        }

    violations = []
    prose = _prose(lines)

    for i, line in enumerate(lines, 1):
        if i in prose:
            continue

        if re.search(r"logging\.StreamHandler\s*\(", line):
            if not is_bypassed(file_path, "log_handler", i, bypass_rules):
                violations.append(i)

    if violations:
        return {
            "name": "No raw StreamHandler with file logging",
            "passed": False,
            "message": f"Raw logging.StreamHandler with file logging on lines {violations[:5]} - use prax system_logger instead",
        }

    return {
        "name": "No raw StreamHandler with file logging",
        "passed": True,
        "message": "No raw StreamHandler with file logging found",
    }
