# =================== AIPass ====================
# Name: error_handling_check.py
# Description: Error Handling Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Error Handling Standards Checker Handler

Validates error handling compliance — detects silent failures
(bare except: pass) in production code.
"""

from pathlib import Path
from typing import Dict, List, Optional
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: all Python files
AUDIT_SCOPE = "all_files"


def is_bypassed(file_path: str, standard: str, line: int | None = None, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed"""
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
    """Check if module follows error handling standards"""
    checks = []
    path = Path(module_path)

    if is_bypassed(module_path, "error_handling", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "ERROR_HANDLING",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "ERROR_HANDLING",
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
            "standard": "ERROR_HANDLING",
        }

    # Only check: Error handling (for all files, not just non-test files)
    error_handling_check = check_error_handling(content, lines, module_path)
    if error_handling_check:
        checks.append(error_handling_check)

    # If no checks were added (no try/except blocks), pass
    if not checks:
        return {
            "passed": True,
            "checks": [
                {"name": "Error handling", "passed": True, "message": "No try/except blocks detected (not applicable)"}
            ],
            "score": 100,
            "standard": "ERROR_HANDLING",
        }

    passed_checks = sum(1 for check in checks if check["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks * 100)) if total_checks > 0 else 0
    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "error_handling"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "ERROR_HANDLING"}


def _is_silent_except(lines: List[str], pass_index: int, pass_line: str) -> bool:
    pass_indent = len(pass_line) - len(pass_line.lstrip())
    for j in range(pass_index, min(pass_index + 3, len(lines))):
        next_line = lines[j].strip()
        is_pass_line = next_line == "pass" or next_line.startswith("pass ") or next_line.startswith("pass#")
        if next_line and not is_pass_line:
            if lines[j].startswith(" ") and len(lines[j]) - len(lines[j].lstrip()) > pass_indent:
                return False
            break
    return True


def check_error_handling(content: str, lines: List[str], module_path: str = "") -> Optional[Dict]:
    """Check for proper error handling patterns"""
    try_count = content.count("try:")

    if try_count == 0:
        return None

    silent_failures = []
    in_docstring = False
    in_except = False
    except_line = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = '"""' if stripped.startswith('"""') else "'''"
            if stripped.count(quote) == 2 and len(stripped) > len(quote) * 2:
                pass
            else:
                in_docstring = not in_docstring
        if in_docstring:
            continue
        if "except" in stripped and ":" in stripped:
            in_except = True
            except_line = i
            continue
        if in_except:
            if stripped == "pass" or stripped.startswith("pass ") or stripped.startswith("pass#"):
                if _is_silent_except(lines, i, line):
                    silent_failures.append(f"line {except_line}")
            if line.strip() and not line.startswith(" ") and not line.startswith("\t"):
                in_except = False

    if silent_failures:
        return {
            "name": "Error handling",
            "passed": False,
            "message": f"Silent failure detected (except: pass) in {Path(module_path).name if module_path else 'file'} at {silent_failures[0]} - errors should log/return",
        }

    return {
        "name": "Error handling",
        "passed": True,
        "message": f"Error handling present ({try_count} try/except blocks with proper handling)",
    }
