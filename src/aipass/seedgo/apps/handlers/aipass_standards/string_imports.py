# =================== AIPass ====================
# Name: string_imports.py
# Description: Import targets written as string literals, read from the parse tree
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Import targets a file names as a STRING, for the cross-branch handler rule.

``importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")``
reaches another branch's handlers exactly like an import statement does, and
both the ``handlers`` and ``encapsulation`` standards used to be blind to it:
the first reads import nodes only, the second skips any line where
``apps.handlers`` sits inside quotes, by design, to acquit documentation
examples (DPLAN-0404, measured 10-06/07: 10 product sites, ~45 test files).

The cure keeps that acquittal. A string is an import only when it is an
ARGUMENT to a call that imports or patches by name; a string anywhere else is
prose. The parse tree answers that for free: docstrings and comments are never
call arguments.

The calls read, by the call's own name (any module, any alias):

- ``import_module("lit")`` - ``importlib.import_module``, a bare import, an
  ``as`` alias, and a seam whose name ends in ``import_module``
- ``resolve_name("lit")`` - ``pkgutil.resolve_name``
- ``patch("lit")`` - ``unittest.mock.patch``, ``mock.patch``; first positional
  only. ``patch.object`` takes an object and is not read.
- ``<x>.setattr("lit", ...)`` - ``monkeypatch.setattr``, the string form only

A literal counts when it starts with ``aipass.`` and contains
``.apps.handlers``. A bare name counts too when it resolves to a module-level
assignment of one string literal (hooks' ``_RAIL`` shape).
"""

import ast
from typing import Dict, Iterator, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: The marker a string must carry to be a handlers target.
HANDLERS_MARKER = ".apps.handlers"

#: The conviction note both standards append to a quoted line.
STRING_IMPORT_NOTE = "(string import)"


def _call_name(func: ast.expr, aliases: Dict[str, str]) -> str:
    """The last segment of a call's name, with an ``import ... as`` alias undone."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    return ""


def _aliases(tree: ast.AST) -> Dict[str, str]:
    """Every ``from x import name as alias`` in the file, alias -> name."""
    found: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname:
                    found[alias.asname] = alias.name
    return found


def _module_constants(tree: ast.Module) -> Dict[str, str]:
    """Module-level ``NAME = "literal"`` assignments, one target, one string."""
    found: Dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[node.targets[0].id] = node.value.value
    return found


def _reads_a_target(call: ast.Call, aliases: Dict[str, str]) -> bool:
    """Whether this call imports or patches by the name in its first argument."""
    name = _call_name(call.func, aliases)
    if name.endswith("import_module") or name in ("resolve_name", "patch"):
        return True
    return name == "setattr" and isinstance(call.func, ast.Attribute)


def _literal_of(arg: ast.expr, constants: Dict[str, str]) -> Optional[str]:
    """The string an argument carries: a literal, or a module constant's literal."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.Name):
        return constants.get(arg.id)
    return None


def iter_string_imports(content: str) -> Iterator[Tuple[int, str]]:
    """Yield (line, target) for every handlers target named as a call's string.

    Args:
        content: Source of the file.

    Returns:
        An iterator of (1-indexed line of the call, dotted target). An
        unparseable file yields nothing: the import-node readers beside this
        one already decline it the same way.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.info("string_imports: unparseable, no string targets read: %s", exc)
        json_handler.log_operation("string_imports_unparseable", {"error": str(exc)})
        return
    aliases = _aliases(tree)
    constants = _module_constants(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args or not _reads_a_target(node, aliases):
            continue
        target = _literal_of(node.args[0], constants)
        if target and target.startswith("aipass.") and HANDLERS_MARKER in target:
            yield node.lineno, target
