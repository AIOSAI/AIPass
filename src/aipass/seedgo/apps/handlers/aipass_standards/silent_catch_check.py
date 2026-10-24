# =================== AIPass ====================
# Name: silent_catch_check.py
# Description: Silent Catch Standards Checker Handler
# Version: 1.0.2
# Created: 2026-03-22
# Modified: 2026-10-24
# =============================================

"""
Silent Catch Standards Checker Handler

Reference: silent_catch.md
"""

import ast
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards import exception_handling
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

# APPLIES_TO: except/pass in a test is how a broken assertion goes green.
APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

_LOGGING_ATTRS = frozenset({"error", "warning", "warn", "info", "debug", "exception", "critical"})


def _has_logger_call(nodes: list[ast.stmt]) -> bool:
    """Return True if any node in *nodes* (or its descendants) contains a ``logger.<level>()`` call."""
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


#: Catching these says "something went wrong", which is not a classification. DOTTED names compare
#: whole: ``pytest.skip.Exception`` is a specific type whose last component reads "Exception".
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


#: Builtins whose ZERO-ARGUMENT call is an empty container: ``set()`` and ``frozenset()`` have no literal
#: spelling, so a function returning one cannot say "nothing" in a way ``ast.Constant`` sees.
_EMPTY_BUILTINS = frozenset({"set", "frozenset", "dict", "list", "tuple"})


def _is_the_empty_answer(value: ast.expr) -> bool:
    """True for a value that means "this function found nothing".

    EMPTY only: ``return [1, 2]`` or ``set(c)`` fabricates an answer and keeps its finding.
    """
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return not value.elts
    if isinstance(value, ast.Dict):
        return not value.keys
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id in _EMPTY_BUILTINS and not value.args and not value.keywords
    return False


def _converts_the_exception_to_a_value(handler: ast.ExceptHandler) -> bool:
    """True when the handler turns a NAMED exception into a returned constant.

    Reference: silent_catch.md, "What is not a silent catch".
    """
    names = _caught_type_names(handler)
    if not names or set(names) & _BROAD_EXCEPTIONS:
        return False
    if len(handler.body) != 1:
        return False
    only = handler.body[0]
    if not isinstance(only, ast.Return) or only.value is None:
        return False
    if isinstance(only.value, ast.Constant) or _is_the_empty_answer(only.value):
        return True
    # A return that uses the bound exception carries MORE than a constant does.
    if handler.name:
        return any(isinstance(node, ast.Name) and node.id == handler.name for node in ast.walk(only.value))
    return False


def _reports_to_a_stream(handler: ast.ExceptHandler) -> bool:
    """True when the handler writes the failure to stdout or stderr.

    "Silently" is the standard's own word; whether a stream is the right instrument is the CLI standard's question.
    """
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "write":
            continue
        stream = node.func.value
        if isinstance(stream, ast.Attribute) and stream.attr in ("stdout", "stderr"):
            return True
    return False


def _judge_handler(handler: ast.ExceptHandler, try_node: ast.Try, module_path: str) -> list[int]:
    """The line of ``handler`` if it swallows, or [] if it reports by some means.

    Every exemption is a separate named clause, so a removed finding traces to the report that removed it.
    """
    if not handler.body:
        return []

    if _has_logger_call(handler.body) or _has_raise(handler.body):
        return []

    if _converts_the_exception_to_a_value(handler):
        return []

    if _reports_to_a_stream(handler):
        return []

    if exception_handling.guards_a_diagnostic(try_node, module_path, handler.lineno):
        return []

    if exception_handling.hands_the_exception_on(handler, module_path):
        return []

    return [handler.lineno]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a Python file for silent exception catches."""
    path = Path(module_path)

    if is_bypassed(module_path, "silent_catch", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "SILENT_CATCH",
        }

    if path.suffix != ".py" or path.name == "__init__.py":
        return {
            "passed": True,
            "checks": [
                {
                    "name": "Silent catch blocks",
                    "passed": True,
                    "message": "File skipped (non-target)",
                    "declined": True,
                }
            ],
            "score": 100,
            "standard": "SILENT_CATCH",
        }

    if not path.exists():
        return {
            "passed": False,
            "checks": [{"name": "File exists", "passed": False, "message": f"File not found: {module_path}"}],
            "score": 0,
            "standard": "SILENT_CATCH",
        }

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

    try:
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError) as e:
        logger.info("Skipped %s: SyntaxError during parse", path)
        return {
            "passed": False,
            "checks": [{"name": "File parseable", "passed": False, "message": f"Syntax error: {e}"}],
            "score": 0,
            "standard": "SILENT_CATCH",
        }

    silent_lines: list[int] = []

    # Walked as Try nodes, not bare handlers: two of the clauses below judge a
    # handler by the BLOCK it protects, and an ExceptHandler node has no link
    # back to its own try.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            silent_lines.extend(_judge_handler(handler, node, module_path))

    silent_lines.sort()

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

    passed_checks = sum(1 for c in checks if c["passed"])
    total_checks = len(checks)
    score = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    overall_passed = score >= 75

    json_handler.log_operation(
        "check_completed", {"file": str(module_path), "score": score, "standard": "silent_catch"}
    )
    return {"passed": overall_passed, "checks": checks, "score": score, "standard": "SILENT_CATCH"}
