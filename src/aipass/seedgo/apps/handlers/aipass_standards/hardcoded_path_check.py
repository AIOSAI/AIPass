# =================== AIPass ====================
# Name: hardcoded_path_check.py
# Description: Hardcoded Absolute Path Standards Checker Handler
# Version: 1.0.0
# Created: 2026-06-18
# Modified: 2026-06-18
# =============================================

"""Hardcoded Absolute Path Standards Checker Handler."""

import re
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

# APPLIES_TO: Windows CI runs the suite, so /home/... in a test breaks the build.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

_POSIX_HOME = re.compile(r"/home/[a-zA-Z][a-zA-Z0-9_.-]+/")
_MACOS_HOME = re.compile(r"/Users/[a-zA-Z][a-zA-Z0-9_.-]+/")
_WINDOWS_HOME = re.compile(r"[A-Z]:\\\\?Users\\\\?[a-zA-Z]")
_DASH_POSIX = re.compile(r"-home-[a-zA-Z][a-zA-Z0-9_.]+-")
_DASH_MACOS = re.compile(r"-Users-[a-zA-Z][a-zA-Z0-9_.]+-")

_ALL_PATTERNS = [
    (_POSIX_HOME, "POSIX home path"),
    (_MACOS_HOME, "macOS home path"),
    (_WINDOWS_HOME, "Windows home path"),
    (_DASH_POSIX, "dash-encoded POSIX home"),
    (_DASH_MACOS, "dash-encoded macOS home"),
]

_COMMENT_RE = re.compile(r"^\s*#")
_DOCSTRING_DELIMITERS = ('"""', "'''")


def _in_docstring(lines: list[str], line_idx: int) -> bool:
    """Return True if line_idx falls inside a docstring."""
    in_ds = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        for delim in _DOCSTRING_DELIMITERS:
            count = stripped.count(delim)
            if count >= 2:
                continue
            if count == 1:
                in_ds = not in_ds
        if i == line_idx:
            return in_ds
    return False


def _scan_file(content: str) -> list[tuple[int, str, str]]:
    """Scan content for hardcoded home paths.

    Returns list of (line_number, description, matched_text).
    """
    violations: list[tuple[int, str, str]] = []
    lines = content.split("\n")

    for idx, line in enumerate(lines):
        lineno = idx + 1
        if _COMMENT_RE.match(line):
            continue
        if _in_docstring(lines, idx):
            continue
        for pattern, desc in _ALL_PATTERNS:
            match = pattern.search(line)
            if match:
                violations.append((lineno, desc, match.group()))
                break
    return violations


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for hardcoded absolute home-directory paths."""
    path = Path(module_path)
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "hardcoded_path", bypass_rules=bypass_rules):
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
            "standard": "HARDCODED_PATH",
        }

    if path.suffix != ".py" or path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Hardcoded path",
                    "passed": True,
                    "message": "File skipped (non-target)",
                }
            ],
            "score": 100,
            "standard": "HARDCODED_PATH",
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
            "standard": "HARDCODED_PATH",
        }

    try:
        source = path.read_text(encoding="utf-8")
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
            "standard": "HARDCODED_PATH",
        }

    all_violations = _scan_file(source)

    non_bypassed = [
        (ln, desc, txt)
        for ln, desc, txt in all_violations
        if not is_bypassed(module_path, "hardcoded_path", ln, bypass_rules)
    ]
    non_bypassed.sort(key=lambda x: x[0])

    checks = []
    violation_count = len(non_bypassed)

    if violation_count == 0:
        checks.append(
            {
                "name": "Hardcoded path",
                "passed": True,
                "message": "No hardcoded absolute home paths found",
            }
        )
    else:
        previews = [f"L{ln}: {desc} ({txt})" for ln, desc, txt in non_bypassed[:3]]
        preview_str = "; ".join(previews)
        suffix = f" (and {violation_count - 3} more)" if violation_count > 3 else ""
        checks.append(
            {
                "name": "Hardcoded path",
                "passed": False,
                "message": f"{violation_count} hardcoded path(s): {preview_str}{suffix}",
            }
        )

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "hardcoded_path"},
    )
    return {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "HARDCODED_PATH",
    }
