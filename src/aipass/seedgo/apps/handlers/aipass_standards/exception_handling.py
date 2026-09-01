# =================== AIPass ====================
# Name: exception_handling.py
# Description: Shared discriminators for handlers that report rather than swallow
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""What separates a handler that SWALLOWS from one that reports.

Two checkers ask overlapping questions about ``except`` blocks — ``silent_catch``
("no logger call, no re-raise") and ``error_handling`` ("except: pass") — and
both convicted the same shape this morning, so the discriminators live here once
rather than drifting apart in two files.

WHERE THIS CAME FROM. The fleet spent this week adopting one guarded spelling for
module-level ``__file__`` resolution (the Windows dead-cwd cure). Every branch's
copy has the same two-layer shape, and BOTH layers looked silent to a checker
reading only for a logger call:

    try:
        return path.resolve()
    except OSError as exc:          # <- hands the exception to a named reporter
        _record_unresolved(path, exc)
        return path

    def _record_unresolved(path, exc):
        try:
            logger.debug(...)       # the diagnostic
        except Exception as inner:  # <- guards the diagnostic itself
            _retain("logger", inner)

@daemon reported it with the measurement that makes it undeniable: their first
cut logged from OUTSIDE the try, and their own pin caught it. The world that
reaches this code is a machine whose filesystem cannot answer a basic question,
and @prax's logger construction reads the working directory — so "the logger is
also down" is the SAME world, not a contrived one. A guard that dies in its own
diagnostic converts a survivable import into a crash while claiming to prevent
exactly that. The literal fix the checker demanded was to add a logger call to
the handler for a logger failure: the defect their pin had just caught,
reintroduced to satisfy a score.

@canary reported the same site from the other side, having MEASURED the
prescription rather than argued with it — applying it verbatim made their branch
unimportable — and @backup, @skills and @trigger carry the identical shape.
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.json import json_handler

#: Attribute names that ARE a report. ``write`` is qualified separately: only a
#: write to a standard stream reports, and a write to a file handle nobody is
#: watching does not.
_REPORT_ATTRS = frozenset({"debug", "info", "warning", "error", "critical", "exception", "log_operation"})

#: Container mutations that may sit beside a report without changing what the
#: block is FOR — deduping a repeated message, appending to a bounded list.
_BOOKKEEPING_ATTRS = frozenset({"add", "append", "discard", "remove", "extend"})


def _statement_calls(nodes: List[ast.stmt]) -> List[ast.Call]:
    """Calls made as STATEMENTS, not calls nested inside another call's arguments.

    The distinction is load-bearing and was found by measuring: a report almost
    always composes its message with ``type(exc).__name__`` or ``str(exc)``, and
    counting those as effects made every real report look impure. The first cut
    missed @canary's site for exactly that reason.

    Args:
        nodes: Statements to walk.

    Returns:
        Every ``ast.Call`` appearing as an expression statement.
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

    An exemption that fires silently is the thing I have spent this week arguing
    against: a reader seeing a 100 cannot tell "clean" from "excused". These are
    rare by construction — 16 handlers in the whole fleet — so the audit trail
    costs nothing and answers "why is this file green" without reading the
    checker.

    Args:
        clause: Which discriminator granted it.
        module_path: File the handler lives in, when the caller knows it.
        line: 1-indexed line of the handler.
    """
    json_handler.log_operation(
        "exception_handling_exemption_granted",
        {"clause": clause, "file": module_path or "unknown", "line": line},
    )


def guards_a_diagnostic(try_node: ast.Try, module_path: str = "", line: int = 0) -> bool:
    """True when this ``try`` block does nothing but REPORT.

    A handler attached to such a block is catching the failure OF THE REPORT.
    The original error was already dealt with by whatever produced the report,
    so nothing is being swallowed — and demanding a log call here asks the
    diagnostic to be protected by a second diagnostic, forever.

    Requires at least one genuine report: an empty ``try`` or one holding only
    bookkeeping is not a diagnostic and keeps its finding.

    MEASURED before landing, 2026-08-31: 6 handlers in the fleet match, in 6
    different branches, and every one is the dead-cwd cure's own diagnostic
    guard — @backup, @canary, @daemon (x2), @skills, @trigger. Exactly the
    reported class, nothing else.

    Args:
        try_node: The ``try`` statement whose handler is being judged.
        module_path: File being checked, recorded when an exemption is granted.
        line: Handler line, recorded with the grant; defaults to the try's own.

    Returns:
        True if every statement-level call in the block reports or is
        bookkeeping, and at least one reports.
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

    ``except OSError as exc: _record_unresolved(path, exc)`` does not drop
    anything — the exception is handed to a named function that owns reporting
    it. This is @spawn's classify-and-return one level out: there the
    information became a return value, here it becomes an argument. In both the
    caller decides, which is the opposite of swallowing.

    The clause is on the EXCEPTION NAME, so it cannot be borrowed by a handler
    that merely calls something: a handler that never binds ``as`` has no
    exception object to pass, and one that binds it and ignores it stays red.
    The checker cannot follow the callee, and does not claim to — what it
    verifies is that the object was not dropped on the floor.

    MEASURED before landing, 2026-08-31: 10 handlers match across the fleet and
    all 10 were read individually. Six are the dead-cwd cure delegating to a
    named reporter (@backup, @daemon x3, @skills, @trigger); the other four are
    a Rich console report before ``sys.exit`` (@cli), a subprocess protocol
    writing its error as JSON on stdout (@memory), a deliberately rate-limited
    queue warning (@prax), and a retained-unresolved list (@trigger). Zero
    looked like a swallow.

    Args:
        handler: The except handler being judged.
        module_path: File being checked, recorded when an exemption is granted.

    Returns:
        True if the bound exception name appears in a call's arguments.

    Note:
        The ``handler.name`` guard below is an EQUIVALENT MUTANT — removing it
        changes no answer, because an unbound handler has ``name is None`` and
        no ``ast.Name`` ever compares equal to it. It is kept for the reader and
        recorded here so nobody hunts for the pin that does not exist. Mutation
        run 2026-08-31: survived, and it should have.
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
