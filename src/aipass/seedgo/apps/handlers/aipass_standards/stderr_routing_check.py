# =================== AIPass ====================
# Name: stderr_routing_check.py
# Description: Stderr Routing Standards Checker
# Version: 1.0.0
# Created: 2026-03-13
# Modified: 2026-03-13
# =============================================

"""
Stderr Routing Standards Checker

Validates that error/warning output uses CLI display functions (error(), warning(),
fatal()) which route to stderr, instead of raw console.print() with red/yellow markup
that stays on stdout.

CORRECT:
    from aipass.cli.apps.modules import error, warning, fatal
    error('Branch not found', suggestion='Check spelling')
    warning('Template mismatch', details='Expected v2')

WRONG:
    console.print('[red]Error: Branch not found[/red]')
    console.print('[yellow]Warning: mismatch[/yellow]')
"""

import re
from pathlib import Path
from typing import Dict, List
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler


AUDIT_SCOPE = "all_files"


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed."""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        rule_lines = rule.get("lines", [])
        if rule_lines and line is not None and line not in rule_lines:
            continue
        return True
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check if module routes error/warning output to stderr via CLI display functions.

    Returns:
        dict: {passed, checks, score, standard}
    """
    checks: List[Dict] = []
    path = Path(module_path)

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

    # Check 1: console.print() with error-like red markup
    error_prints = _find_error_prints(lines, module_path, bypass_rules)
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

    # Check 2: console.print() with warning-like yellow markup
    warning_prints = _find_warning_prints(lines, module_path, bypass_rules)
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

    # Check 3: Custom Console(stderr=True) — should import err_console
    custom_stderr = _find_custom_stderr_console(lines, module_path, bypass_rules)
    if custom_stderr:
        checks.append(
            {
                "name": "Stderr console creation",
                "passed": False,
                "message": f"{filename}: Custom Console(stderr=True) on lines {custom_stderr[:3]} — import err_console from aipass.cli.apps.modules",
            }
        )

    # No checks applied = no output patterns = skip
    if not checks:
        return {
            "passed": True,
            "checks": [
                {"name": "Stderr routing", "passed": True, "message": "No error/warning output patterns (skipped)"}
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

    Detects section headers, term highlights, and short formatting labels that use
    colored markup for emphasis — not for signaling warnings or errors.

    Label patterns:
    - Short highlight/term (<=max_short_words): 'off', 'Muted', 'Missing branch name'
    - Colon-terminated: 'COMMANDS:', 'Options:', 'Discovered Modules:'
    - ALL CAPS headers: 'ACTIONABLE ITEMS', 'ESCALATIONS NEEDED'

    max_short_words controls the threshold for short-phrase detection:
    - Yellow (warnings): 2 — real warnings like 'Template version mismatch' are 3+ words
    - Red (errors): 5 — red is commonly used for CLI feedback phrases
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
        # Label ending with colon (e.g., 'COMMANDS:', 'Discovered Modules:')
        if text.endswith(":") and word_count <= 3:
            return True
        # ALL CAPS section header (e.g., 'ACTIONABLE ITEMS')
        if text.isupper() and word_count <= 3:
            return True
    return False


def _has_any_output(content: str) -> bool:
    """Check if file has any console output at all."""
    return "console.print(" in content or "err_console.print(" in content


def _in_skip_context(line: str, in_docstring: bool, in_main_block: bool) -> bool:
    """Check if we should skip this line."""
    stripped = line.strip()
    if in_docstring or in_main_block:
        return True
    if stripped.startswith("#"):
        return True
    return False


def _find_error_prints(lines: List[str], module_path: str, bypass_rules: list | None) -> List[int]:
    """Find console.print() calls with red markup containing error-like content."""
    violations = []
    in_docstring = False
    in_main_block = False
    main_block_indent = 0

    # Patterns: [red], [bold red], [red bold] in console.print()
    red_pattern = re.compile(r"console\.print\(.*\[(?:bold\s+)?red(?:\s+bold)?\]", re.IGNORECASE)
    # Also catch: console.print("Error: ...") or console.print("Failed to ...")
    # Only match when keyword appears at the START of the string content (not buried in help text)
    # "error" requires a colon (to distinguish "Error: ..." from "Error Registry ...")
    error_msg_pattern = re.compile(
        r"""console\.print\(\s*f?["']\s*(?:error\s*:|(?:failed|fatal|cannot|unable|invalid)\b)""", re.IGNORECASE
    )

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip()) if stripped else 0

        # Track __main__ blocks
        if "if __name__ ==" in stripped and "__main__" in stripped:
            in_main_block = True
            main_block_indent = current_indent
            continue
        if in_main_block and stripped and current_indent <= main_block_indent:
            in_main_block = False

        # Track docstrings
        for quote in ('"""', "'''"):
            if line.count(quote) % 2 == 1:
                in_docstring = not in_docstring

        if _in_skip_context(line, in_docstring, in_main_block):
            continue

        # Skip if in a string context (the console.print itself is in a string)
        if "console.print(" not in stripped:
            continue

        # Check it's not inside a string literal
        before = line.split("console.print(")[0]
        if before.count("'") % 2 == 1 or before.count('"') % 2 == 1:
            continue

        # Skip bypassed lines
        if is_bypassed(module_path, "stderr_routing", line=i, bypass_rules=bypass_rules):
            continue

        # Match red markup patterns (skip CLI feedback — short red phrases are UI styling)
        if red_pattern.search(stripped):
            if not _is_markup_label(stripped, "red", max_short_words=5):
                violations.append(i)
        elif error_msg_pattern.search(stripped):
            violations.append(i)

    return violations


def _find_warning_prints(lines: List[str], module_path: str, bypass_rules: list | None) -> List[int]:
    """Find console.print() calls with yellow markup containing warning-like content."""
    violations = []
    in_docstring = False
    in_main_block = False
    main_block_indent = 0

    # Patterns: [yellow] in console.print() that look like warnings
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

        for quote in ('"""', "'''"):
            if line.count(quote) % 2 == 1:
                in_docstring = not in_docstring

        if _in_skip_context(line, in_docstring, in_main_block):
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


def _find_custom_stderr_console(lines: List[str], module_path: str, bypass_rules: list | None) -> List[int]:
    """Find custom Console(stderr=True) creation — should use err_console import."""
    violations = []
    in_docstring = False

    stderr_pattern = re.compile(r"Console\s*\(.*stderr\s*=\s*True", re.IGNORECASE)

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        for quote in ('"""', "'''"):
            if line.count(quote) % 2 == 1:
                in_docstring = not in_docstring

        if in_docstring or stripped.startswith("#"):
            continue

        if is_bypassed(module_path, "stderr_routing", line=i, bypass_rules=bypass_rules):
            continue

        if stderr_pattern.search(stripped):
            violations.append(i)

    return violations
