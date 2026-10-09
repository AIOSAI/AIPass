# =================== AIPass ====================
# Name: module_constants.py
# Description: A module's string constants bound once at module level, and the f-strings built from them
# Version: 1.1.0
# Created: 2026-10-05
# Modified: 2026-10-08
# =============================================

"""A module's string constants, read from its AST, for checkers that read a name as its value.

Two checkers met the same blind spot (seedgo, fleet green leg 17):
``stdlib_patch`` could not read ``patch(f"{_MOD}.shutil.which")`` and
``import_site`` could not read ``sys.modules[KEY] = stub``. Both only need to
know which string a module-level name holds, so the table lives here once.

A name enters the table only when it is bound EXACTLY ONCE at module level,
and that binding is ``NAME = "text"`` (or ``NAME: str = "text"``). Every other
binding of the name counts against it: a second assignment, an augmented one,
a loop or ``with`` target, an import, a ``def``/``class`` of that name, or a
``global NAME`` inside any function. A name bound twice has two possible
values, and a checker that guessed one would convict or acquit by luck.
Function and class bodies are a different scope and are not read.
"""

import ast
from pathlib import Path
from typing import Dict, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

_PRODUCT = "aipass"
_TESTS = "tests"
_SUPPORT_PREFIX = "support_"


def _is_text(node: ast.AST | None) -> bool:
    """True for a string literal."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _scope_bindings(node: ast.AST) -> List[str]:
    """Names a def/class binds in the module: its own name and every ``global`` inside it."""
    names = [getattr(node, "name", "")]
    for inner in ast.walk(node):
        if isinstance(inner, ast.Global):
            names.extend(inner.names)
    return names


def string_constants(tree: ast.Module) -> Dict[str, str]:
    """Module-level name -> the string it holds, for names bound exactly once to a string literal."""
    return _bound_once(*_bindings(tree))


def _bound_once(counts: Dict[str, int], values: Dict[str, str]) -> Dict[str, str]:
    """The values whose name is bound exactly once; a rebound string constant is logged and left unread."""
    rebound = sorted(name for name in values if counts.get(name) != 1)
    if rebound:
        # Rare, and the one case a reader may ask about: a string constant left unread on purpose.
        json_handler.log_operation("string_constant_rebound", {"names": rebound})
    return {name: text for name, text in values.items() if counts.get(name) == 1}


def file_constants(tree: ast.Module, path: Path | None) -> Dict[str, str]:
    """``string_constants`` plus the string constants this test file imports from its own support module.

    The fleet's split rule 4 moves a test file's ``_MOD`` into
    ``tests/support_<stem>.py``, after which ``patch(f"{_MOD}.os.kill")`` read
    nothing: the import counted as the name's one binding and carried no value
    (hooks' ``test_session_boot*.py``, 45 sites, fleet green split legs).
    ONE hop to a ``support_*.py`` beside the file, in the file's own branch
    (``from aipass.<branch>.tests.support_x import NAME`` or ``from
    .support_x import NAME``); no chains, no other module. The imported name
    must be bound nowhere else in the file, the same once-only rule a local
    constant meets.
    """
    counts, values = _bindings(tree)
    constants = _bound_once(counts, values)
    if path is None:
        return constants
    for node in tree.body:
        support = _support_file(node, path)
        if support is None or not isinstance(node, ast.ImportFrom):
            continue
        theirs = _support_constants(support)
        for alias in node.names:
            local = alias.asname or alias.name
            if alias.name in theirs and counts.get(local) == 1:
                constants[local] = theirs[alias.name]
    return constants


def _support_file(node: ast.AST, path: Path) -> Path | None:
    """The own-branch ``support_*.py`` this ``from`` import reads, or None for any other import."""
    if not isinstance(node, ast.ImportFrom) or not node.module:
        return None
    tests_dir = path.parent
    parts = node.module.split(".")
    if node.level == 1 and len(parts) == 1:
        stem = parts[0]
    elif node.level == 0 and parts[:-1] == [_PRODUCT, tests_dir.parent.name, _TESTS] and tests_dir.name == _TESTS:
        stem = parts[-1]
    else:
        return None
    if not stem.startswith(_SUPPORT_PREFIX):
        return None
    return tests_dir / f"{stem}.py"


def _support_constants(support: Path) -> Dict[str, str]:
    """A support module's own string constants; nothing it imports is followed (one hop)."""
    try:
        tree = ast.parse(support.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        logger.info("[module_constants] Support module unread, its names stay unresolved: %s", exc)
        return {}
    return string_constants(tree)


def _bindings(tree: ast.Module) -> Tuple[Dict[str, int], Dict[str, str]]:
    """(module-level name -> how many times it is bound, name -> the string literal it was bound to)."""
    counts: Dict[str, int] = {}
    values: Dict[str, str] = {}
    pending: List[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        bound: List[str] = []
        if isinstance(node, _SCOPES):
            for name in _scope_bindings(node):
                counts[name] = counts.get(name, 0) + 1
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bound = [(alias.asname or alias.name).split(".")[0] for alias in node.names]
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound = [node.id]
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound = [node.name]
        for name in bound:
            counts[name] = counts.get(name, 0) + 1
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if _is_text(node.value):
                values[node.targets[0].id] = node.value.value  # type: ignore[union-attr]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and _is_text(node.value):
            values[node.target.id] = node.value.value  # type: ignore[union-attr]
        pending.extend(ast.iter_child_nodes(node))
    return counts, values


def joined_text(node: ast.AST, constants: Dict[str, str]) -> str:
    """The f-string as one string when every field is a bare name in ``constants``, else "".

    A field with a conversion (``!r``), a format spec, or anything but a bare
    name (a call, an attribute, an expression) is not read: "" means unread,
    and the caller counts it rather than guessing.
    """
    if not isinstance(node, ast.JoinedStr):
        return ""
    parts: List[str] = []
    for value in node.values:
        if _is_text(value):
            parts.append(value.value)  # type: ignore[attr-defined]
        elif (
            isinstance(value, ast.FormattedValue)
            and value.conversion == -1
            and value.format_spec is None
            and isinstance(value.value, ast.Name)
            and value.value.id in constants
        ):
            parts.append(constants[value.value.id])
        else:
            return ""
    return "".join(parts)
