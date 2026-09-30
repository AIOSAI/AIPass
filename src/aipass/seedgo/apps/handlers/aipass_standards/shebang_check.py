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
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: scan every .py file, not just entry point
# APPLIES_TO: a test file is library code - nothing executes it directly.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"


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
