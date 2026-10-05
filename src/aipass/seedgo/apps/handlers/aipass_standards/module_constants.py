# =================== AIPass ====================
# Name: module_constants.py
# Description: A module's string constants bound once at module level, and the f-strings built from them
# Version: 1.0.0
# Created: 2026-10-05
# Modified: 2026-10-05
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
from typing import Dict, List

from aipass.seedgo.apps.handlers.json import json_handler

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


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
    rebound = sorted(name for name in values if counts.get(name) != 1)
    if rebound:
        # Rare, and the one case a reader may ask about: a string constant left unread on purpose.
        json_handler.log_operation("string_constant_rebound", {"names": rebound})
    return {name: text for name, text in values.items() if counts.get(name) == 1}


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
