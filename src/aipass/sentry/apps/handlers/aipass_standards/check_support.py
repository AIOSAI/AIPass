# =================== AIPass ====================
# Name: check_support.py
# Description: Source reading, parsing, result shape and guard helpers shared by this pack's checkers
# Version: 1.1.0
# Created: 2026-10-23
# Modified: 2026-11-14
# =============================================

"""Helpers more than one checker in this pack needs, kept once so the copies cannot drift."""

import ast
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.sentry.apps.handlers.json import json_handler

#: Except types that make an optional import or OS call a handled fact.
_GUARDED_EXCEPT_TYPES = frozenset(
    {"ImportError", "ModuleNotFoundError", "OSError", "PermissionError", "ProcessLookupError"}
)


def read_text(path: Path, *, tag: str, errors: str = "strict") -> str | None:
    """A file's UTF-8 text, or None when it cannot be read or decoded."""
    try:
        return path.read_text(encoding="utf-8", errors=errors)
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[%s] Cannot read %s: %s", tag, path, exc)
        return None


def parse(source: str, filename: str = "<unknown>", *, tag: str) -> ast.Module | None:
    """The source's tree, or None when Python cannot parse it.

    ruff already convicts a syntax error; a verdict invented for an unparseable file misleads.
    Python 3.10/3.11 raise ValueError, not SyntaxError, on a NUL byte.
    """
    try:
        return ast.parse(source, filename=filename)
    except (SyntaxError, ValueError) as exc:
        logger.info("[%s] Unparseable, nothing scanned: %s", tag, exc)
        json_handler.log_operation("source_unparseable", {"checker": tag, "error": str(exc)})
        return None


def result(passed: bool, checks: List[Dict], score: int, standard: str) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": standard}


def tail_name(func: ast.AST) -> str:
    """The name a call is made under: ``f`` for ``a.b.f(...)`` and ``f(...)``, else ""."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def collect_child_linenos(node: ast.AST) -> set[int]:
    """Walk all descendants and return line numbers where present."""
    lines: set[int] = set()
    for child in ast.walk(node):
        lineno = getattr(child, "lineno", None)
        if lineno is not None:
            lines.add(lineno)
    return lines


def _handler_catches_guarded_type(handler: ast.ExceptHandler) -> bool:
    """Return True if the except handler catches an import/OS error type."""
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in _GUARDED_EXCEPT_TYPES
    if isinstance(handler.type, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id in _GUARDED_EXCEPT_TYPES for elt in handler.type.elts)
    return False


def lines_in_guarded_blocks(tree: ast.Module) -> set[int]:
    """Collect line numbers inside try/except ImportError or OSError."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            if any(_handler_catches_guarded_type(h) for h in node.handlers):
                guarded.update(collect_child_linenos(node))
    return guarded


def find_enclosing_function(tree: ast.Module, target_lineno: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The innermost def whose body holds the line, or None at module level."""
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if target_lineno in collect_child_linenos(node):
            if best is None or node.lineno > best.lineno:
                best = node
    return best
