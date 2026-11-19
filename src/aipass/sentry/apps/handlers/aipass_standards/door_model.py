# =================== AIPass ====================
# Name: door_model.py
# Description: The door model read from a package top file: uncached, unknown names raise, __all__ and __dir__
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""The door model, read statically from ``src/aipass/<branch>/__init__.py``.

A package top file that defines a module-level ``__getattr__`` is a door. Four facts are read:
it stores nothing it serves, an unknown name raises AttributeError, ``__all__`` is built from
the tables ``__getattr__`` reads, and ``__dir__`` exists. A shape this reader cannot follow is
left unjudged rather than guessed: a wrong conviction is worse than a stated gap.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from aipass.sentry.apps.handlers.json import json_handler

GETATTR = "__getattr__"
#: Calls that copy a table's names unchanged, as ``__all__ = sorted(_HOMES)`` does.
_COPIES = frozenset({"list", "sorted", "tuple", "set", "frozenset"})
#: Methods that write into the dict they are called on.
_WRITERS = frozenset({"update", "setdefault", "__setitem__"})
_LOOPS = (ast.Try, ast.For, ast.While, ast.With, ast.Match, ast.AsyncFor, ast.AsyncWith)
#: The unknown name's path ends in ``raise AttributeError``; a line number is where it is answered instead.
RAISES = "raises"
UNJUDGED = "unjudged"

CACHE_CURE = "Cure: return it, store nothing; a patch on the home must reach the next reader."
UNKNOWN_CURE = (
    "an unknown name must raise AttributeError (hasattr, getattr with a default and mock.patch rely on it). "
    "Cure: if name not in _HOMES: raise AttributeError(...) before any return; no default, no except that returns."
)
ALL_CURE = "Cure: __all__ = list(_HOMES)"
DIR_CURE = "Cure: def __dir__(): return sorted(set(globals()) | set(__all__))"


def is_package_top(path: Path) -> bool:
    """Whether the path is a branch's package top file, ``src/aipass/<branch>/__init__.py``."""
    package = path.parent.parent
    return path.name == "__init__.py" and package.name == "aipass" and package.parent.name == "src"


def findings(source: str) -> List[Tuple[int, str]]:
    """(line, message) for each broken fact; empty for a file with no ``__getattr__``, which is not a door."""
    tree = ast.parse(source)
    defs: Dict[str, ast.FunctionDef] = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    door = defs.get(GETATTR)
    if door is None:
        return []
    bound = _module_bindings(tree)
    found: Set[Tuple[int, str]] = set()
    for function in _reached(door, defs):
        found.update(_caches(function, bound))
    found.update(_answers_unknown(door))
    found.update(_all_findings(tree, door, _tables(bound)))
    if "__dir__" not in defs:
        found.add((door.lineno, f"the door has no __dir__: dir() misses every name not yet read. {DIR_CURE}"))
    if found:
        json_handler.log_operation("door_model_broken", {"facts": len(found)})
    return sorted(found)


def _module_bindings(tree: ast.Module) -> Dict[str, ast.expr]:
    """Each name a top-level assignment binds, with the value bound."""
    bound: Dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            bound.update({t.id: node.value for t in node.targets if isinstance(t, ast.Name)})
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            bound[node.target.id] = node.value
    return bound


def _tables(bound: Dict[str, ast.expr]) -> Set[str]:
    """Top-level names bound to a dict literal, ``dict(...)`` or ``dict.fromkeys(...)``: the door's tables."""
    return {
        name
        for name, value in bound.items()
        if isinstance(value, ast.Dict)
        or (isinstance(value, ast.Call) and ast.unparse(value.func) in ("dict", "dict.fromkeys"))
    }


def _reached(door: ast.FunctionDef, defs: Dict[str, ast.FunctionDef]) -> List[ast.FunctionDef]:
    """``__getattr__`` and every function of the file it calls, directly or through another."""
    seen: List[ast.FunctionDef] = [door]
    queue: List[ast.FunctionDef] = [door]
    while queue:
        calls = [n.func.id for n in ast.walk(queue.pop()) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        for callee in (defs[name] for name in calls if name in defs and name != "__dir__"):
            if callee not in seen:
                seen.append(callee)
                queue.append(callee)
    return seen


def _locals(function: ast.FunctionDef) -> Set[str]:
    """Names the function binds itself, which shadow a module-level name of the same spelling."""
    names = {a.arg for a in function.args.args}
    names.update(n.id for n in ast.walk(function) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
    return names


def _subscript_store(target: ast.expr, memo: Set[str]) -> Optional[str]:
    """What a subscript write stores into, when that is the package: ``globals()``, ``vars()`` or a memo dict."""
    if not isinstance(target, ast.Subscript):
        return None
    holder = target.value
    if isinstance(holder, ast.Call) and ast.unparse(holder.func) in ("globals", "vars"):
        return f"{ast.unparse(holder)}[...] ="
    if isinstance(holder, ast.Name) and holder.id in memo:
        return f"{holder.id}[...] = (a module-level memo)"
    return None


def _call_store(node: ast.Call, memo: Set[str]) -> Optional[str]:
    """``setattr`` on the package, or a writing method on ``globals()``, ``vars()`` or a memo dict."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "setattr" and node.args:
        owner = ast.unparse(node.args[0])
        return f"setattr({owner}, ...)" if owner.startswith(("sys.modules[", "globals()")) else None
    if isinstance(func, ast.Attribute) and func.attr in _WRITERS:
        holder = ast.unparse(func.value)
        return f"{holder}.{func.attr}(...)" if holder in ("globals()", "vars()") or holder in memo else None
    return None


def _store_at(node: ast.AST, memo: Set[str]) -> Optional[str]:
    """The package store this one node makes, if it makes one."""
    if isinstance(node, ast.Global):
        return f"global {', '.join(node.names)}"
    if isinstance(node, ast.Assign):
        return next((s for s in (_subscript_store(t, memo) for t in node.targets) if s), None)
    if isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        return _subscript_store(node.target, memo)
    if isinstance(node, ast.Call):
        return _call_store(node, memo)
    return None


def _caches(function: ast.FunctionDef, bound: Dict[str, ast.expr]) -> List[Tuple[int, str]]:
    """Each write, in a function ``__getattr__`` reaches, that keeps a served value on the package."""
    memo = {name for name in bound if name not in _locals(function)}
    stores = [(d.lineno, f"@{ast.unparse(d)}") for d in function.decorator_list if "cache" in ast.unparse(d)]
    for node in ast.walk(function):
        what = _store_at(node, memo)
        if what:
            stores.append((getattr(node, "lineno", function.lineno), what))
    return [
        (line, f"the door caches: {what} at line {line} keeps what __getattr__ serves on the package. {CACHE_CURE}")
        for line, what in stores
    ]


def _answers_unknown(door: ast.FunctionDef) -> List[Tuple[int, str]]:
    """Where ``__getattr__`` can hand back something for a name it does not serve."""
    lines: List[int] = []
    for node in ast.walk(door):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "getattr":
            if len(node.args) + len(node.keywords) > 2:
                lines.append(node.lineno)
        elif isinstance(node, ast.ExceptHandler) and not any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            returns = [n.lineno for n in ast.walk(node) if isinstance(n, ast.Return)]
            lines.append(returns[0] if returns else node.lineno)
    param = door.args.args[0].arg if door.args.args else ""
    end = _unknown_path(door.body, param)
    if end is None:
        end = door.lineno
    if isinstance(end, int):
        lines.append(end)
    return [(line, f"the door answers an unknown name at line {line}: {UNKNOWN_CURE}") for line in lines]


def _tests_name(test: ast.expr, param: str, ops: tuple) -> bool:
    """``<param> <op> <x>`` with op one of ``ops``."""
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == param
        and len(test.ops) == 1
        and isinstance(test.ops[0], ops)
    )


def _raises_attribute_error(node: ast.Raise) -> bool:
    called = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return isinstance(called, ast.Name) and called.id == "AttributeError"


def _branch_end(statement: ast.If, param: str) -> Union[str, int, None]:
    """Where an unknown name's path ends inside one ``if``; None when it carries on past it."""
    if _tests_name(statement.test, param, (ast.NotIn, ast.NotEq)):
        return _unknown_path(statement.body, param)
    if _tests_name(statement.test, param, (ast.In, ast.Eq)):
        return _unknown_path(statement.orelse, param)
    return UNJUDGED


def _unknown_path(body: List[ast.stmt], param: str) -> Union[str, int, None]:
    """Follow an unknown name through ``body``: RAISES, the line answering it, UNJUDGED, or None (falls through).

    A branch on ``name in``/``name ==`` serves a known name and is passed over; ``name not in`` guarding a raise
    ends the unknown path. A loop, try or with block, or an ``if`` on anything else, is not followed.
    """
    for statement in body:
        if isinstance(statement, ast.Raise):
            return RAISES if _raises_attribute_error(statement) else statement.lineno
        if isinstance(statement, ast.Return):
            return statement.lineno
        if isinstance(statement, _LOOPS):
            return UNJUDGED
        end = _branch_end(statement, param) if isinstance(statement, ast.If) else None
        if end is not None:
            return end
    return None


def _all_findings(tree: ast.Module, door: ast.FunctionDef, tables: Set[str]) -> List[Tuple[int, str]]:
    """``__all__`` missing, or a judged form that leaves out a table ``__getattr__`` serves from."""
    assigns = [
        n
        for n in tree.body
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))
        and "__all__" in {t.id for t in ast.walk(n) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
    ]
    if not assigns:
        return [(door.lineno, f"the door's __all__ is missing: star-imports and readers see no names. {ALL_CURE}")]
    node = assigns[0]
    if len(assigns) > 1 or isinstance(node, ast.AugAssign) or node.value is None or not _judged_all(node.value):
        return []
    served = _served_tables(door, tables)
    listed = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
    missing = sorted(served - listed)
    if not missing:
        return []
    return [
        (
            node.lineno,
            f"the door's __all__ is hand-written: it is not built from {', '.join(missing)}, the table "
            f"__getattr__ serves from, so the list and the served names can drift. "
            f"Cure: __all__ = list({missing[0]}), or [<own defs>, *{missing[0]}]",
        )
    ]


def _served_tables(door: ast.FunctionDef, tables: Set[str]) -> Set[str]:
    """Tables ``__getattr__`` reads a name from: ``name in TABLE`` or ``TABLE[...]`` loaded, never a memo it writes."""
    read: Set[str] = set()
    for node in ast.walk(door):
        if isinstance(node, ast.Compare):
            read.update(c.id for c in node.comparators if isinstance(c, ast.Name))
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name):
            read.add(node.value.id)
    return read & tables


def _judged_all(value: ast.expr) -> bool:
    """The ``__all__`` forms read: a literal list or tuple of names and ``*TABLE`` spreads, a copy call, a name."""
    if isinstance(value, ast.Name):
        return True
    if isinstance(value, ast.Call):
        return ast.unparse(value.func) in _COPIES and len(value.args) == 1 and isinstance(value.args[0], ast.Name)
    if isinstance(value, (ast.List, ast.Tuple)):
        return all(
            (isinstance(e, ast.Constant) and isinstance(e.value, str))
            or (isinstance(e, ast.Starred) and isinstance(e.value, ast.Name))
            for e in value.elts
        )
    return False
