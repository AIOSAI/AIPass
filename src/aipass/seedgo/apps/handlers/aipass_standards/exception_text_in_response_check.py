# =================== AIPass ====================
# Name: exception_text_in_response_check.py
# Description: Exception Text In Response Standards Checker Handler
# Version: 1.0.0
# Created: 2026-10-10
# Modified: 2026-10-17
# =============================================

"""
Exception Text In Response Standards Checker Handler

Reference: exception_text_in_response.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Set

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

STANDARD = "EXCEPTION_TEXT_IN_RESPONSE"
STANDARD_KEY = "exception_text_in_response"

#: Top-level packages whose import puts a module in scope.
WEB_FRAMEWORKS = frozenset({"fastapi", "starlette"})

#: Decorator attributes that register a route, when handed a "/..." path.
ROUTE_VERBS = frozenset({"get", "post", "put", "delete", "patch", "head", "options", "route", "api_route", "websocket"})

#: Response classes whose content is the body (keyword ``content`` or first positional).
RESPONSE_CLASSES = frozenset({"JSONResponse", "PlainTextResponse", "HTMLResponse", "Response"})

#: Local helpers that build the response, compared with leading underscores stripped.
RESPONSE_HELPERS = frozenset({"deny", "refuse", "error_response", "respond"})

#: traceback functions that return the trace as text.
TRACE_TEXT = frozenset({"format_exc", "format_exception", "format_exception_only", "format_tb"})

#: Calls that read an exception without carrying its text.
TEXT_FREE = frozenset({"type", "isinstance", "issubclass", "id", "len", "bool", "hash", "callable"})

CURE = "log the detail with exc_info and return a fixed typed message (plus a correlation id that is also logged)"
WHY = "exception text reaches an HTTP response"


def _callee(call: ast.Call) -> str:
    """The last segment of a call's name (``HTTPException`` for ``fastapi.HTTPException``)."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_trace_text(call: ast.Call) -> bool:
    """``traceback.format_exc()`` and its siblings, imported either way."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id == "traceback" and func.attr in TRACE_TEXT
    return isinstance(func, ast.Name) and func.id in TRACE_TEXT


def tainted(expr: ast.AST | None, names: Set[str]) -> bool:
    """Whether an expression carries exception text, given the names that hold it."""
    if expr is None:
        return False
    if isinstance(expr, ast.Name):
        return expr.id in names
    if isinstance(expr, (ast.Attribute, ast.Subscript, ast.Starred, ast.FormattedValue)):
        return tainted(expr.value, names)
    if isinstance(expr, ast.Call):
        if _is_trace_text(expr):
            return True
        if isinstance(expr.func, ast.Name) and expr.func.id in TEXT_FREE:
            return False
        receiver = expr.func.value if isinstance(expr.func, ast.Attribute) else None
        parts = [receiver, *expr.args, *(keyword.value for keyword in expr.keywords)]
        return any(tainted(part, names) for part in parts)
    if isinstance(expr, ast.JoinedStr):
        return any(tainted(part, names) for part in expr.values)
    if isinstance(expr, ast.BinOp):
        return tainted(expr.left, names) or tainted(expr.right, names)
    if isinstance(expr, ast.IfExp):
        return tainted(expr.body, names) or tainted(expr.orelse, names)
    if isinstance(expr, ast.BoolOp):
        return any(tainted(value, names) for value in expr.values)
    return _holds(expr, names)


def _holds(expr: ast.AST, names: Set[str]) -> bool:
    """Whether a container literal holds exception text in any slot."""
    if isinstance(expr, ast.Dict):
        return any(tainted(value, names) for value in expr.values)
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return any(tainted(element, names) for element in expr.elts)
    return False


def _call_sink_reached(node: ast.Call, names: Set[str]) -> bool:
    """Whether one call builds a response out of exception text."""
    callee = _callee(node)
    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
    if callee == "HTTPException":
        return tainted(keywords.get("detail"), names) or (len(node.args) > 1 and tainted(node.args[1], names))
    if callee in RESPONSE_CLASSES:
        return tainted(keywords.get("content"), names) or bool(node.args and tainted(node.args[0], names))
    if callee.lstrip("_") in RESPONSE_HELPERS:
        return any(tainted(arg, names) for arg in [*node.args, *keywords.values()])
    return False


def _walk_clause(statements: List[ast.stmt]):
    """Every node of a clause in source order, nested defs and classes left out."""
    for statement in statements:
        yield from _walk_node(statement)


def _walk_node(node: ast.AST):
    """One node and its children, depth first, stopping at a nested def or class."""
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _walk_node(child)


def _clause_rows(handler: ast.ExceptHandler) -> Set[int]:
    """The sink lines one except clause feeds with exception text."""
    names: Set[str] = {handler.name} if handler.name else set()
    rows: Set[int] = set()
    for node in _walk_clause(handler.body):
        if isinstance(node, ast.Assign):
            carries = tainted(node.value, names)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    (names.add if carries else names.discard)(target.id)
        if isinstance(node, ast.Return) and tainted(node.value, names):
            rows.add(node.lineno)
        elif isinstance(node, ast.Call) and _call_sink_reached(node, names):
            rows.add(node.lineno)
    return rows


def _imports_web(tree: ast.AST) -> bool:
    """Whether the file imports fastapi or starlette, at any depth."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in WEB_FRAMEWORKS for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] in WEB_FRAMEWORKS:
                return True
    return False


def _is_route(decorator: ast.AST) -> bool:
    """``@<x>.get("/...")`` and its siblings."""
    if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)):
        return False
    if decorator.func.attr not in ROUTE_VERBS or not decorator.args:
        return False
    path = decorator.args[0]
    return isinstance(path, ast.Constant) and isinstance(path.value, str) and path.value.startswith("/")


def in_scope(tree: ast.AST) -> bool:
    """Whether the file builds HTTP responses: a web framework import, or a route."""
    if _imports_web(tree):
        return True
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(_is_route(d) for d in node.decorator_list)
        for node in ast.walk(tree)
    )


def scan(tree: ast.AST) -> List[int]:
    """Every sink line, in any except clause of the file, that receives exception text."""
    rows: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            rows |= _clause_rows(node)
    return sorted(rows)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[exception_text_in_response] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Exception text in response", "passed": passed, "message": message}]


def _declined(reason: str) -> Dict:
    """A result that measured nothing: out of the average, never a 100."""
    return {
        "passed": True,
        "score": 100,
        "not_applicable": True,
        "checks": [{**check, "declined": True} for check in _one_check(True, f"Not applicable: {reason}")],
        "standard": STANDARD,
    }


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a product file for exception text that reaches an HTTP response."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[exception_text_in_response] Unparseable %s: %s", module_path, exc)
        return _declined("the file does not parse (ruff convicts that)")

    if not in_scope(tree):
        return _declined("no fastapi/starlette import and no route, so no response is built here")

    hits = [line for line in scan(tree) if not is_bypassed(module_path, STANDARD_KEY, line, bypass_rules)]
    if not hits:
        return _result(True, _one_check(True, "No except clause hands exception text to a response"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per hit would hide the rest.
    detail = "\n".join(f"{path.name}:{line} {WHY} - {CURE}" for line in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
