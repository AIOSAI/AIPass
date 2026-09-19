# =================== AIPass ====================
# Name: exclusive_create_race.py
# Description: Windows compat - exclusive creates that lose the delete-pending race (advisory arm)
# Version: 1.0.0
# Created: 2026-09-17
# Modified: 2026-09-17
# =============================================

"""
Windows compat -- an exclusive create that treats "exists" as normal and
PermissionError as nothing.

The incident (CI 35192484222, Windows): api's token store lock took
``os.open(path, O_CREAT | O_EXCL)`` in a retry loop that caught
``FileExistsError`` only.  On Windows a create against a lock file another
thread is mid-removing (delete pending) answers ``PermissionError`` (errno
13), not ``FileExistsError``.  The exception left the loop, the thread died,
and the revoke never ran.  POSIX unlinks the name at once, so Linux and macOS
can never see it -- no suite run there can catch it either.

Two arms, both read from the try that owns the ``FileExistsError`` handler:

* ESCAPE -- no handler on that try (or on any try around it in the same
  function) takes a PermissionError: it leaves the function raw where
  "exists" would have returned or retried.
* GIVES UP -- the try sits in a loop, ``FileExistsError`` retries, and the
  handler that takes PermissionError (``except OSError``) unconditionally
  returns, raises or breaks: a transient state becomes a failed acquire.

Deliberately NOT flagged, each measured against the fleet on 2026-09-17:

* A single-shot create whose ``except OSError`` fails the same way "exists"
  does (ai_mail wake/daemon locks, memory intake, aipass install): Windows
  gets the outcome POSIX gets, with a different log line.
* A fresh name per attempt -- the path is a Name assigned inside the retry
  loop (prax json_service's pid+counter temp file).  Nothing deletes a name
  nobody has used yet.
* A create inside a ``sys.platform`` / ``os.name`` guard.

Known misses, named rather than hidden: flags held in a variable
(``os.open(p, flags)``), a create reached through a wrapper function, and a
PermissionError caught by a try OUTSIDE the retry loop (gives up, unflagged).
A single-shot create of a data file nothing ever deletes, with a
``FileExistsError``-only handler, IS flagged and is a false positive -- none
exists in the fleet today; a bypass rule is the answer when one appears.

Pure: takes a parsed tree, never touches the disk.
"""

import ast
from typing import Iterator

#: Exception names whose handler catches a PermissionError. Attribute forms
#: (``builtins.OSError``) are read by their last segment.
_PERMISSION_CATCHERS = frozenset(
    {"PermissionError", "OSError", "IOError", "EnvironmentError", "Exception", "BaseException"}
)

_EXISTS = "FileExistsError"

_SCOPE_BOUNDARIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef, ast.Module)

_LOOPS = (ast.For, ast.AsyncFor, ast.While)


def _walk(node: ast.AST, ancestry: list[tuple[ast.AST, str]]) -> Iterator[tuple[ast.AST, list[tuple[ast.AST, str]]]]:
    """Every descendant with its (ancestor, field) chain, outermost first."""
    for field, value in ast.iter_fields(node):
        children = value if isinstance(value, list) else [value]
        for child in children:
            if isinstance(child, ast.AST):
                chain = [*ancestry, (node, field)]
                yield child, chain
                yield from _walk(child, chain)


def _handler_names(handler: ast.ExceptHandler) -> set[str] | None:
    """Names a handler catches; None for a bare ``except:``."""
    if handler.type is None:
        return None
    elts = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names: set[str] = set()
    for elt in elts:
        if isinstance(elt, ast.Name):
            names.add(elt.id)
        elif isinstance(elt, ast.Attribute):
            names.add(elt.attr)
    return names


def _takes_permission_error(handler: ast.ExceptHandler) -> bool:
    names = _handler_names(handler)
    return names is None or bool(names & _PERMISSION_CATCHERS)


def _names_exists(handler: ast.ExceptHandler) -> bool:
    names = _handler_names(handler)
    return names is not None and _EXISTS in names


def _call_arg(node: ast.Call, index: int, keyword: str) -> ast.expr | None:
    if len(node.args) > index:
        return node.args[index]
    return next((kw.value for kw in node.keywords if kw.arg == keyword), None)


def is_exclusive_create(node: ast.AST) -> bool:
    """``os.open`` with O_EXCL in its flags, or builtin ``open`` in an "x" mode."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "open":
        if not (isinstance(func.value, ast.Name) and func.value.id == "os"):
            return False
        flags = _call_arg(node, 1, "flags")
        return flags is not None and any(
            (isinstance(n, ast.Attribute) and n.attr == "O_EXCL") or (isinstance(n, ast.Name) and n.id == "O_EXCL")
            for n in ast.walk(flags)
        )
    if isinstance(func, ast.Name) and func.id == "open":
        mode = _call_arg(node, 1, "mode")
        return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "x" in mode.value
    return False


def _exits_unconditionally(body: list[ast.stmt]) -> bool:
    """A top-level return/raise/break: the handler leaves the loop every time."""
    return any(isinstance(stmt, (ast.Return, ast.Raise, ast.Break)) for stmt in body)


def _assigned_names(loop: ast.AST) -> set[str]:
    """Names bound anywhere in a loop, its own target included."""
    names: set[str] = set()
    for child in ast.walk(loop):
        targets: list[ast.expr] = []
        if isinstance(child, ast.Assign):
            targets = list(child.targets)
        elif isinstance(child, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr, ast.For, ast.AsyncFor)):
            targets = [child.target]
        for target in targets:
            names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    return names


def _fresh_name_per_attempt(call: ast.Call, loop: ast.AST) -> bool:
    """The path is rebuilt from a name the loop rebinds: a new file each attempt, not a wait."""
    path = _call_arg(call, 0, "file") if isinstance(call.func, ast.Name) else _call_arg(call, 0, "path")
    if path is None:
        return False
    rebound = _assigned_names(loop)
    return any(isinstance(n, ast.Name) and n.id in rebound for n in ast.walk(path))


def _function_scope(ancestry: list[tuple[ast.AST, str]]) -> tuple[str, list[tuple[ast.AST, str]]]:
    """The enclosing function's name and the chain below it."""
    for index in range(len(ancestry) - 1, -1, -1):
        node = ancestry[index][0]
        if isinstance(node, _SCOPE_BOUNDARIES):
            name = getattr(node, "name", "<module>") if not isinstance(node, ast.Lambda) else "<lambda>"
            return name, ancestry[index + 1 :]
    return "<module>", ancestry


def _judge(call: ast.Call, ancestry: list[tuple[ast.AST, str]]) -> str | None:
    """The violation text for one exclusive create, or None when it is safe."""
    func_name, scope = _function_scope(ancestry)
    guarded_tries: list[tuple[int, ast.Try]] = [
        (i, node) for i, (node, field) in enumerate(scope) if isinstance(node, ast.Try) and field == "body"
    ]
    owner = next(((i, t) for i, t in reversed(guarded_tries) if any(_names_exists(h) for h in t.handlers)), None)
    if owner is None:
        return None
    owner_index, owner_try = owner
    loop = next(
        (node for node, field in reversed(scope[:owner_index]) if isinstance(node, _LOOPS) and field == "body"), None
    )
    if loop is not None and _fresh_name_per_attempt(call, loop):
        return None

    permission_handler = next((h for h in owner_try.handlers if _takes_permission_error(h)), None)
    if permission_handler is None:
        outer_catches = any(_takes_permission_error(h) for i, t in guarded_tries if i < owner_index for h in t.handlers)
        if outer_catches:
            return None
        return (
            f"exclusive create in {func_name}() catches FileExistsError only - a Windows delete-pending "
            "PermissionError escapes where 'exists' is handled"
        )

    exists_handler = next(h for h in owner_try.handlers if _names_exists(h))
    if (
        loop is not None
        and permission_handler is not exists_handler
        and not _exits_unconditionally(exists_handler.body)
        and _exits_unconditionally(permission_handler.body)
    ):
        return (
            f"exclusive create in {func_name}() retries FileExistsError but gives up on a Windows "
            f"delete-pending PermissionError (except at L{permission_handler.lineno})"
        )
    return None


def find_exclusive_create_races(tree: ast.Module, platform_guarded: set[int]) -> list[tuple[int, str]]:
    """Exclusive creates that lose the Windows delete-pending race.

    Args:
        tree: Parsed module.
        platform_guarded: Line numbers inside sys.platform / os.name guards.

    Returns:
        (line, description) per offending create, in source order.
    """
    found: list[tuple[int, str]] = []
    for node, ancestry in _walk(tree, []):
        if not isinstance(node, ast.Call) or not is_exclusive_create(node) or node.lineno in platform_guarded:
            continue
        verdict = _judge(node, ancestry)
        if verdict:
            found.append((node.lineno, verdict))
    return sorted(found)
