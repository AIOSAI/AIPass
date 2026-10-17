# =================== AIPass ====================
# Name: exception_handling.py
# Description: Shared discriminators for handlers that report rather than swallow
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""What separates a handler that SWALLOWS from one that reports.

``silent_catch`` and ``error_handling`` ask overlapping questions about ``except`` blocks,
so the discriminators live here once rather than drifting apart in two files.
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.json import json_handler

#: Attribute names that ARE a report; ``write`` reports only to a standard stream.
_REPORT_ATTRS = frozenset({"debug", "info", "warning", "error", "critical", "exception", "log_operation"})

#: Container mutations that may sit beside a report: deduping, a bounded list.
_BOOKKEEPING_ATTRS = frozenset({"add", "append", "discard", "remove", "extend"})


def _statement_calls(nodes: List[ast.stmt]) -> List[ast.Call]:
    """Calls made as STATEMENTS, not calls nested inside another call's arguments.

    A report composes its message with ``type(exc).__name__`` or ``str(exc)``, so counting
    those as effects would make every real report look impure.
    """
    calls = []
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Expr) and isinstance(sub.value, ast.Call):
                calls.append(sub.value)
    return calls


def _is_report_call(call: ast.Call) -> bool:
    """True for a call whose whole purpose is to tell someone what happened."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "write":
        stream = func.value
        return isinstance(stream, ast.Attribute) and stream.attr in ("stdout", "stderr")
    return func.attr in _REPORT_ATTRS


def _is_bookkeeping_call(call: ast.Call) -> bool:
    """True for a container mutation that supports a report without being one."""
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr in _BOOKKEEPING_ATTRS


def _record_grant(clause: str, module_path: str, line: int) -> None:
    """Log every exemption this module hands out.

    A silent exemption leaves a 100 that cannot tell "clean" from "excused".
    """
    json_handler.log_operation(
        "exception_handling_exemption_granted",
        {"clause": clause, "file": module_path or "unknown", "line": line},
    )


def guards_a_diagnostic(try_node: ast.Try, module_path: str = "", line: int = 0) -> bool:
    """True when this ``try`` block does nothing but REPORT.

    The handler catches the failure OF THE REPORT; demanding a log there asks for a second
    diagnostic, forever. At least one genuine report is required.
    """
    calls = _statement_calls(try_node.body)
    if not any(_is_report_call(call) for call in calls):
        return False
    if not all(_is_report_call(call) or _is_bookkeeping_call(call) for call in calls):
        return False
    _record_grant("guards_a_diagnostic", module_path, line or try_node.lineno)
    return True


def hands_the_exception_on(handler: ast.ExceptHandler, module_path: str = "") -> bool:
    """True when the caught exception LEAVES the handler as a value.

    ``except OSError as exc: _record_unresolved(path, exc)`` hands the exception to a named
    reporter. The clause is on the EXCEPTION NAME, so a handler that never binds ``as``, or
    binds it and ignores it, stays red.
    """
    if not handler.name:
        return False
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        for argument in arguments:
            for sub in ast.walk(argument):
                if isinstance(sub, ast.Name) and sub.id == handler.name:
                    _record_grant("hands_the_exception_on", module_path, handler.lineno)
                    return True
    return False
