# =================== AIPass ====================
# Name: stderr_routing_check.py
# Description: Stderr Routing Standards Checker
# Version: 1.1.0
# Created: 2026-03-13
# Modified: 2026-10-18
# =============================================

"""
Stderr Routing Standards Checker

Reference: stderr_routing.md
"""

import re
from pathlib import Path
from typing import AbstractSet, Dict, List
from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify, hash_lines


# APPLIES_TO: stream choice is a product decision.
APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check if module routes error/warning output to stderr via CLI display functions."""
    checks: List[Dict] = []
    path = Path(module_path)

    # Normalize to forward slashes so string matching works on Windows too
    module_path = Path(module_path).as_posix()

    if is_bypassed(module_path, "stderr_routing", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "STDERR_ROUTING",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "STDERR_ROUTING",
        }

    # CLI branch is exempt — it defines these functions
    if "/cli/apps/" in module_path:
        return {
            "passed": True,
            "checks": [
                {"name": "Stderr routing", "passed": True, "message": "CLI branch exempt (defines display functions)"}
            ],
            "score": 100,
            "standard": "STDERR_ROUTING",
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
            "standard": "STDERR_ROUTING",
        }

    filename = path.name
    try:
        prose = classify(content).text_only
    except UnparseableSource as exc:
        logger.info("stderr_routing: unparseable, comment lines only skipped: %s", exc)
        prose = hash_lines(content)

    error_prints = _find_error_prints(lines, prose, module_path, bypass_rules)
    if error_prints:
        checks.append(
            {
                "name": "Error output routing",
                "passed": False,
                "message": f"{filename}: {len(error_prints)} error print(s) on lines {error_prints[:5]} — use error() or fatal() instead",
            }
        )
    elif _has_any_output(content):
        checks.append(
            {"name": "Error output routing", "passed": True, "message": "No error-like console.print() with red markup"}
        )

    warning_prints = _find_warning_prints(lines, prose, module_path, bypass_rules)
    if warning_prints:
        checks.append(
            {
                "name": "Warning output routing",
                "passed": False,
                "message": f"{filename}: {len(warning_prints)} warning print(s) on lines {warning_prints[:5]} — use warning() instead",
            }
        )
    elif _has_any_output(content):
        checks.append(
            {
                "name": "Warning output routing",
                "passed": True,
                "message": "No warning-like console.print() with yellow markup",
            }
        )

    custom_stderr = _find_custom_stderr_console(lines, prose, module_path, bypass_rules)
    if custom_stderr:
        checks.append(
            {
                "name": "Stderr console creation",
                "passed": False,
                "message": f"{filename}: Custom Console(stderr=True) on lines {custom_stderr[:3]} — import err_console from aipass.cli.apps.modules",
            }
        )

    if not checks:
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Stderr routing",
                    "passed": True,
                    "message": "No error/warning output patterns (skipped)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "STDERR_ROUTING",
        }

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "stderr_routing"}
    )
    return {"passed": score >= 75, "checks": checks, "score": score, "standard": "STDERR_ROUTING"}


def _is_markup_label(line: str, color: str, max_short_words: int = 2) -> bool:
    """Check if colored markup in a console.print() is a label/highlight, not a warning/error.

    max_short_words: yellow 2 (real warnings are 3+ words), red 5 (red is common for short CLI feedback).
    """
    pattern = re.compile(r"\[(?:bold\s+)?" + re.escape(color) + r"(?:\s+bold)?\](.*?)\[/", re.IGNORECASE)
    match = pattern.search(line)
    if match:
        text = match.group(1).strip()
        words = text.split()
        word_count = len(words)
        # Short highlight/term — too brief to be a real error/warning sentence
        if word_count <= max_short_words:
            return True
        if text.endswith(":") and word_count <= 3:
            return True
        if text.isupper() and word_count <= 3:
            return True
    return False


def _has_any_output(content: str) -> bool:
    """Check if file has any console output at all."""
    return "console.print(" in content or "err_console.print(" in content


def _find_error_prints(
    lines: List[str], prose: AbstractSet[int], module_path: str, bypass_rules: list | None
) -> List[int]:
    """Find console.print() calls with red markup containing error-like content."""
    violations = []
    in_main_block = False
    main_block_indent = 0

    red_pattern = re.compile(r"console\.print\(.*\[(?:bold\s+)?red(?:\s+bold)?\]", re.IGNORECASE)
    # Only match when keyword appears at the START of the string content (not buried in help text)
    # "error" requires a colon (to distinguish "Error: ..." from "Error Registry ...")
    error_msg_pattern = re.compile(
        r"""console\.print\(\s*f?["']\s*(?:error\s*:|(?:failed|fatal|cannot|unable|invalid)\b)""", re.IGNORECASE
    )

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if stripped else 0

        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue
        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        if i in prose or in_main_block:
            continue

        if "console.print(" not in stripped:
            continue

        before = line.split("console.print(")[0]
        if before.count("'") % 2 == 1 or before.count('"') % 2 == 1:
            continue

        if is_bypassed(module_path, "stderr_routing", line=i, bypass_rules=bypass_rules):
            continue

        # Match red markup patterns (skip CLI feedback — short red phrases are UI styling)
        if red_pattern.search(stripped):
            if not _is_markup_label(stripped, "red", max_short_words=5):
                violations.append(i)
        elif error_msg_pattern.search(stripped):
            violations.append(i)

    return violations


def _find_warning_prints(
    lines: List[str], prose: AbstractSet[int], module_path: str, bypass_rules: list | None
) -> List[int]:
    """Find console.print() calls with yellow markup containing warning-like content."""
    violations = []
    in_main_block = False
    main_block_indent = 0

    yellow_pattern = re.compile(r"console\.print\(.*\[(?:bold\s+)?yellow(?:\s+bold)?\]", re.IGNORECASE)
    # Only match when keyword appears at the START of the string content (not buried in help text)
    warning_msg_pattern = re.compile(r"""console\.print\(\s*f?["']\s*(?:⚠\s*)?warning\b""", re.IGNORECASE)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if stripped else 0

        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue
        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        if i in prose or in_main_block:
            continue

        if "console.print(" not in stripped:
            continue

        before = line.split("console.print(")[0]
        if before.count("'") % 2 == 1 or before.count('"') % 2 == 1:
            continue

        if is_bypassed(module_path, "stderr_routing", line=i, bypass_rules=bypass_rules):
            continue

        if yellow_pattern.search(stripped):
            if not _is_markup_label(stripped, "yellow"):
                violations.append(i)
        elif warning_msg_pattern.search(stripped):
            violations.append(i)

    return violations


def _find_custom_stderr_console(
    lines: List[str], prose: AbstractSet[int], module_path: str, bypass_rules: list | None
) -> List[int]:
    """Find custom Console(stderr=True) creation — should use err_console import."""
    violations = []

    stderr_pattern = re.compile(r"Console\s*\(.*stderr\s*=\s*True", re.IGNORECASE)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if i in prose:
            continue

        if is_bypassed(module_path, "stderr_routing", line=i, bypass_rules=bypass_rules):
            continue

        if stderr_pattern.search(stripped):
            violations.append(i)

    return violations
