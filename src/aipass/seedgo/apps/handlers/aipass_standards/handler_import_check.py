# =================== AIPass ====================
# Name: handler_import_check.py
# Description: Handler Import Standards Checker
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

"""
Handler Import Standards Checker

Validates that every branch's apps/__init__.py contains
``from . import handlers`` to ensure Python 3.10 mock.patch
can resolve handler subpackages correctly.

Score: 100 (import present) or 0 (missing / file absent).
"""

from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: reads apps/__init__.py only.
APPLIES_TO = "production"
AUDIT_SCOPE = "branch_level"


# =============================================
# BYPASS HELPER
# =============================================


# =============================================
# BRANCH-LEVEL CHECK (audit pipeline entry)
# =============================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """
    Check that a branch's apps/__init__.py contains ``from . import handlers``.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo)
        bypass_rules: Optional list of bypass rules to skip certain checks

    Returns:
        dict: {
            'passed': bool,
            'score': int,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'standard': 'HANDLER_IMPORT'
        }
    """
    bp = Path(branch_path)

    # Check if entire standard is bypassed
    if is_bypassed(branch_path, "handler_import", bypass_rules=bypass_rules):
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Bypassed",
                    "passed": True,
                    "message": "Standard bypassed via .seedgo/bypass.json",
                }
            ],
            "score": 100,
            "standard": "HANDLER_IMPORT",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "handler_import"},
        )
        return result

    init_file = bp / "apps" / "__init__.py"

    if not init_file.exists():
        message = "apps/__init__.py not found"
        logger.info("handler_import check: %s in %s", message, branch_path)
        result = {
            "passed": False,
            "checks": [
                {
                    "name": "Handler import present",
                    "passed": False,
                    "message": message,
                }
            ],
            "score": 0,
            "standard": "HANDLER_IMPORT",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 0, "standard": "handler_import"},
        )
        return result

    # Read the file and check for the import line
    try:
        content = init_file.read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("handler_import check: cannot read %s: %s", init_file, exc)
        result = {
            "passed": False,
            "checks": [
                {
                    "name": "Handler import present",
                    "passed": False,
                    "message": f"Cannot read apps/__init__.py: {exc}",
                }
            ],
            "score": 0,
            "standard": "HANDLER_IMPORT",
        }
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 0, "standard": "handler_import"},
        )
        return result

    if "from . import handlers" in content:
        result = {
            "passed": True,
            "checks": [
                {
                    "name": "Handler import present",
                    "passed": True,
                    "message": ("apps/__init__.py contains 'from . import handlers'"),
                }
            ],
            "score": 100,
            "standard": "HANDLER_IMPORT",
        }
    else:
        result = {
            "passed": False,
            "checks": [
                {
                    "name": "Handler import present",
                    "passed": False,
                    "message": (
                        "apps/__init__.py is missing 'from . import handlers'"
                        " -- Python 3.10 mock.patch cannot resolve handler"
                        " subpackages without an explicit import in the"
                        " parent __init__.py"
                    ),
                }
            ],
            "score": 0,
            "standard": "HANDLER_IMPORT",
        }

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": result["score"],
            "standard": "handler_import",
        },
    )
    return result
