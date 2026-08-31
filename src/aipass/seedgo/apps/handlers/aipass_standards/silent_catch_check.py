# =================== AIPass ====================
# Name: silent_catch_check.py
# Description: Silent Catch Standards Checker Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Silent Catch Standards Checker Handler

Detects except blocks that silently swallow exceptions -- no logger call
and no re-raise.  A silent catch is an ExceptHandler whose body:

  1. Contains no logger.<level>() call  (error, warning, info, debug,
     exception, critical)
  2. Contains no ``raise`` statement

These blocks hide failures and make debugging impossible.  Detection
logic extracted from devpulse silent_catch_scanner_v2.
"""

import ast
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# Audit scope: scan every .py file, not just entry point
AUDIT_SCOPE = "all_files"

# Logger attribute names that count as "logging present"
_LOGGING_ATTRS = frozenset({"error", "warning", "warn", "info", "debug", "exception", "critical"})


# -- AST helpers (extracted from devpulse silent_catch_scanner_v2) ---------


def _has_logger_call(nodes: list[ast.stmt]) -> bool:
    """
    Return True if any node in *nodes* (or its descendants) contains a
    ``logger.<level>()`` call.
    """
    for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _LOGGING_ATTRS
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
        ):
            return True
    return False


def _has_raise(nodes: list[ast.stmt]) -> bool:
    """Return True if any node in *nodes* (or its descendants) is a Raise."""
    for node in ast.walk(ast.Module(body=nodes, type_ignores=[])):
        if isinstance(node, ast.Raise):
            return True
    return False


#: Catching these says "something went wrong", which is not a classification.
#: DOTTED names are compared whole: ``pytest.skip.Exception`` is a specific type
#: whose last component happens to read "Exception", and matching on the
#: attribute alone rejected it (found by its own pin, 2026-08-31).
_BROAD_EXCEPTIONS = frozenset({"Exception", "BaseException", "builtins.Exception", "builtins.BaseException"})


def _caught_type_names(handler: ast.ExceptHandler) -> list[str]:
    """The exception names this handler catches; empty for a bare ``except:``."""
    caught = handler.type
    if caught is None:
        return []
    nodes = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    names = []
    for node in nodes:
        dotted = _dotted_name(node)
        if dotted:
            names.append(dotted)
    return names


def _dotted_name(node: ast.expr) -> str:
    """``pytest.skip.Exception`` for an Attribute chain, ``ValueError`` for a Name."""
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ""
    parts.append(current.id)
    return ".".join(reversed(parts))


def _converts_the_exception_to_a_value(handler: ast.ExceptHandler) -> bool:
    """True when the handler turns a NAMED exception into a returned constant.

    ``except FileNotFoundError: return "absent"`` does not swallow anything —
    the exception's information becomes the return value and the caller decides
    (@spawn, 2026-08-31, whose final_state() and _verdict() helpers answer
    'absent' / 'unreadable' / 'FAILED' / 'SKIPPED'). A logger call there would
    route production logging out of a suite, which is what the hygiene lane
    exists to stop, so the two standards were pulling opposite ways.

    TWO CLAUSES, both measured here:
      1. the handler names a SPECIFIC exception type — a bare ``except:`` or
         ``except Exception`` catches everything, so "it failed" is all the
         caller learns and the type carries no meaning;
      2. the body is exactly one ``return <constant>`` — control leaves with a
         value. Anything else (a second statement, a computed return, a pass, a
         continue) is not this shape and keeps its finding.

    Measured across the fleet before landing: 17 handlers match (14 in tests,
    3 in production), out of 27 single-return-constant handlers — the other 10
    catch Exception or bare and stay flagged. A narrow shape, not an amnesty.
    """
    names = _caught_type_names(handler)
    if not names or set(names) & _BROAD_EXCEPTIONS:
        return False
    if len(handler.body) != 1:
        return False
    only = handler.body[0]
    if not isinstance(only, ast.Return) or only.value is None:
        return False
    if isinstance(only.value, ast.Constant):
        return True
    # `except AssertionError as exc: return ("FAILED", str(exc))` carries MORE
    # than a constant does. Keying on ast.Constant alone flagged the better
    # version of the same pattern (@spawn's _verdict, caught by running the
    # rule against their real file rather than against my own examples).
    if handler.name:
        return any(isinstance(node, ast.Name) and node.id == handler.name for node in ast.walk(only.value))
    return False


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """
    Check a Python file for silent exception catches.

    Parses the file with ``ast.parse()`` and walks every ExceptHandler
    node.  A handler is flagged when its body contains neither a logger
    call nor a raise statement.

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

    # --- bypass -----------------------------------------------------------
    if is_bypassed(module_path, "silent_catch", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "SILENT_CATCH",
        }

    # --- skip non-.py and __init__.py -------------------------------------
    if path.suffix != ".py" or path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [{"name": "Silent catch blocks", "passed": True, "message": "File skipped (non-target)"}],
            "score": 100,
            "standard": "SILENT_CATCH",
        }

    # --- file exists ------------------------------------------------------
    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "SILENT_CATCH",
        }

    # --- read file --------------------------------------------------------
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception as e:
        logger.info("Cannot read %s: %s", path, e)
        return {
            "passed": False,
            "checks": [{"name": "File readable", "passed": False, "message": f"Error reading file: {e}"}],
            "score": 0,
            "standard": "SILENT_CATCH",
        }

    # --- parse AST --------------------------------------------------------
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        logger.info("Skipped %s: SyntaxError during parse", path)
        return {
            "passed": False,
            "checks": [{"name": "File parseable", "passed": False, "message": f"Syntax error: {e}"}],
            "score": 0,
            "standard": "SILENT_CATCH",
        }

    # --- walk AST for silent ExceptHandler nodes --------------------------
    silent_lines: list[int] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue

        body = node.body
        if not body:
            continue

        # An except block is "silent" when it has neither a logger call
        # nor a raise -- it swallows the exception without reporting it
        if _has_logger_call(body) or _has_raise(body):
            continue

        # Classifying, not swallowing: a named exception becomes a returned value.
        if _converts_the_exception_to_a_value(node):
            continue

        silent_lines.append(node.lineno)

    silent_lines.sort()

    # --- build result -----------------------------------------------------
    checks = []
    violation_count = len(silent_lines)

    if violation_count == 0:
        checks.append({"name": "Silent catch blocks", "passed": True, "message": "No silent exception catches found"})
    else:
        first_three = silent_lines[:3]
        line_preview = ", ".join(str(ln) for ln in first_three)
        suffix = f" (and {violation_count - 3} more)" if violation_count > 3 else ""
        checks.append(
            {
                "name": "Silent catch blocks",
                "passed": False,
                "message": f"{violation_count} silent catch(es) on lines {line_preview}{suffix} -- add logger call or re-raise",
            }
        )

    # --- score ------------------------------------------------------------
    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "silent_catch"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "SILENT_CATCH"}
