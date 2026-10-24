# =================== AIPass ====================
# Name: check_support.py
# Description: Source reading, parsing, result shape and platform-guard helpers shared by this pack's checkers
# Version: 1.0.1
# Created: 2026-10-23
# Modified: 2026-10-24
# =============================================

"""Helpers more than one checker in this pack needs, kept once so the copies cannot drift."""

import ast
import re
from pathlib import Path
from typing import Dict, List

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: Modules whose attributes differ by platform, so ``hasattr`` on them is a platform question.
_PROBED_MODULES = frozenset({"os", "signal", "sys", "socket", "select", "time", "errno", "subprocess", "shutil"})

#: Module-level platform flags the fleet spells: IS_WIN, ON_WINDOWS, IS_POSIX, _IS_LINUX.
_PLATFORM_FLAG = re.compile(r"_?(IS|ON)_(WIN|WINDOWS|LINUX|POSIX|MAC|MACOS|DARWIN|NT)", re.IGNORECASE)

#: Except types that make a platform-specific import or OS call a handled fact.
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


def _is_platform_attr(node: ast.expr) -> bool:
    """``sys.platform`` or ``os.name``."""
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and (node.value.id, node.attr) in (("sys", "platform"), ("os", "name"))
    )


def is_platform_guard(node: ast.expr) -> bool:
    """Whether a test expression asks which platform this is.

    A comparison or method call on ``sys.platform`` / ``os.name``, ``hasattr`` on a
    stdlib module, a platform flag such as ``IS_WIN``, and ``not``/``and``/``or`` of those.
    """
    if isinstance(node, ast.Compare):
        return _is_platform_attr(node.left)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _is_platform_attr(node.func.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "hasattr":
        return bool(node.args) and isinstance(node.args[0], ast.Name) and node.args[0].id in _PROBED_MODULES
    if isinstance(node, ast.Name):
        # shortcut: a flag is known by its name, not its binding; read the assignment if a flag name ever lies.
        return _PLATFORM_FLAG.fullmatch(node.id) is not None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return is_platform_guard(node.operand)
    if isinstance(node, ast.BoolOp):
        return any(is_platform_guard(v) for v in node.values)
    return False


def references_platform(node: ast.expr) -> bool:
    """Whether the expression reads sys.platform or os.name anywhere inside it."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            if (child.value.id == "sys" and child.attr == "platform") or (
                child.value.id == "os" and child.attr == "name"
            ):
                return True
    return False


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
    """Collect line numbers inside platform guard blocks or try/except ImportError."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and is_platform_guard(node.test):
            guarded.update(collect_child_linenos(node))
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
