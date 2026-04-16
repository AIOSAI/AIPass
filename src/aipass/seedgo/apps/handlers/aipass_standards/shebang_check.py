# =================== AIPass ====================
# Name: shebang_check.py
# Description: Shebang Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-06
# Modified: 2026-03-06
# =============================================

"""
Shebang Standards Checker Handler

Validates that Python files do not contain shebang lines (#!/...).
AIPass is a pip-installable package -- all execution goes through
pyproject.toml entry points or python3 -m.  Shebangs are unnecessary
and should be removed.
"""

from pathlib import Path
from typing import Dict
from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Audit scope: scan every .py file, not just entry point
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
    Check if a Python file contains a shebang line.

    Shebangs (#!/...) are not needed in pip packages -- all execution
    goes through pyproject.toml entry points or python3 -m.

    Args:
        module_path: Path to Python module to check
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': str
        }
    """
    path = Path(module_path)

    if is_bypassed(module_path, "shebang", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "SHEBANG",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "SHEBANG",
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline()
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "SHEBANG",
        }

    # Check line 1 for shebang
    if first_line.startswith("#!"):
        return {
            "passed": False,
            "checks": [
                {
                    "name": "No shebang line",
                    "passed": False,
                    "message": "Shebang lines are not needed in pip packages -- remove #!/... from line 1",
                }
            ],
            "score": 0,
            "standard": "SHEBANG",
        }

    score = 100
    json_handler.log_operation("check_completed", {"file": str(module_path), "score": score, "standard": "shebang"})
    return {
        "passed": True,
        "checks": [{"name": "No shebang line", "passed": True, "message": "No shebang line found"}],
        "score": score,
        "standard": "SHEBANG",
    }
