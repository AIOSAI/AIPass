# =================== AIPass ====================
# Name: output_routing_check.py
# Description: Output Routing Standards Checker Handler
# Version: 1.0.1
# Created: 2026-07-09
# Modified: 2026-09-25
# =============================================

"""
Output Routing Standards Checker Handler

Detects user-facing error/success/warning output that bypasses @cli's
semantic helpers (error(), success(), warning()) by using raw
console.print() with status markup or status emojis.
"""

import re
import sys
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

# APPLIES_TO: tests read stdout with capsys; raw print is their idiom.
APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

_TEST_FILE_RE = re.compile(r"^(test_.+|.+_test|conftest)\.py$")

# console.print( or err_console.print( at any indentation
_CONSOLE_PRINT_RE = re.compile(r"(?:console|err_console)\.print\(")

# Status color markup — error indicators
_RED_MARKUP_RE = re.compile(r"\[(?:bold\s+)?red(?:\s+bold)?\]")

# Status color markup — warning indicators
_YELLOW_STATUS_RE = re.compile(r"\[yellow\].*(?:⚠|[Ww]arning|WARN|FAIL)")

# Status emojis: ❌ ✅ ✓ ✗ ✘ ⚠ ✔
_STATUS_EMOJI_RE = re.compile(r"[❌✅✓✗✘⚠✔]")

# Green check pattern: [green] followed by check emoji
_GREEN_CHECK_RE = re.compile(r"\[green\].*[✓✔✅]")


def _is_status_console_print(code: str) -> bool:
    if not _CONSOLE_PRINT_RE.search(code):
        return False
    if _RED_MARKUP_RE.search(code):
        return True
    if _STATUS_EMOJI_RE.search(code):
        return True
    if _YELLOW_STATUS_RE.search(code):
        return True
    if _GREEN_CHECK_RE.search(code):
        return True
    return False


def _scan_file(file_path: Path) -> tuple[list[int], str | None]:
    try:
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("Cannot read %s: %s", file_path, exc)
        return [], f"cannot read: {exc}"

    lines = source.splitlines()
    hit_lines: list[int] = []
    in_docstring = False
    docstring_char: str | None = None

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

        code_part = line.split("#")[0]

        if _is_status_console_print(code_part):
            hit_lines.append(lineno)

    return hit_lines, None


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for user-facing output bypassing @cli helpers."""
    path = Path(module_path)

    if is_bypassed(module_path, "output_routing", bypass_rules=bypass_rules):
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
            "standard": "OUTPUT_ROUTING",
        }

    if path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Output routing",
                    "passed": True,
                    "message": "__init__.py skipped",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "OUTPUT_ROUTING",
        }

    if _TEST_FILE_RE.match(path.name):
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Output routing",
                    "passed": True,
                    "message": "Test file skipped",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "OUTPUT_ROUTING",
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
            "standard": "OUTPUT_ROUTING",
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
            "standard": "OUTPUT_ROUTING",
        }

    non_bypassed = [ln for ln in hit_lines if not is_bypassed(module_path, "output_routing", ln, bypass_rules)]

    checks: list[Dict] = []

    if not non_bypassed:
        checks.append(
            {
                "name": "Output routing",
                "passed": True,
                "message": "All user-facing status output uses @cli helpers",
            }
        )
    else:
        sample = ", ".join(str(ln) for ln in non_bypassed[:5])
        suffix = f" (and {len(non_bypassed) - 5} more)" if len(non_bypassed) > 5 else ""
        checks.append(
            {
                "name": "Output routing",
                "passed": False,
                "message": f"{len(non_bypassed)} raw status output(s) on lines {sample}{suffix}",
            }
        )

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int(passed_checks / total_checks * 100) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": score, "standard": "output_routing"},
    )

    return {
        "passed": overall_passed,
        "checks": checks,
        "score": score,
        "standard": "OUTPUT_ROUTING",
    }
