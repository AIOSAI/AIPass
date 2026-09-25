# =================== AIPass ====================
# Name: logged_fallback_check.py
# Description: Logged Fallback Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Logged Fallback Standards Checker Handler

``silent_catch``'s sibling. ``silent_catch`` acquits any ``except`` that calls
the logger; this rule reads what the handler RETURNS. A handler that logs and
then returns a value the success path can also return hands its caller a
failure dressed as an answer: the caller cannot tell "it failed" from "it
worked and found nothing".

  ``backup/apps/handlers/drive/client.py:128``: ``_api_call`` returns ``None``
  when a Drive request fails, and ``None`` is also what a search that found
  nothing returns. ``get_or_create_backup_folder`` reads the failure as "no
  folder", creates a duplicate root and wipes the tracker.

THE SHAPE. An ``except`` handler that

  * does not raise anywhere in its body (bare ``raise``, ``raise X``,
    ``raise X from Y``), and
  * ENDS in ``return`` of a literal default: a constant (``None``, ``False``,
    ``0``, ``""`` ...), an empty container (``{}``, ``[]``, ``()``, ``set()``,
    ``dict()``, ``list()``, ``tuple()``), or a string built from the exception
    (an f-string naming it, or ``str(exc)``), and
  * sits in a function whose SUCCESS PATH can return that same value.

"Can return that same value" is mechanical: some ``return`` outside every
handler of the function returns (a) a literal equal to the default -- same
type, same value, so ``False`` is not ``0`` -- or (b) a name whose FIRST
binding in the function is that literal (``results = []`` ... ``return
results``). A string built from the exception matches any string literal, or
a name first bound to one. Logging never acquits. The hit is reported on the
handler's ``return`` line.

NOT CONVICTED, each for its reason (the page names every one):
  * A SENTINEL: the default is a value no success return produces --
    ``return None`` where every success return is a dict, ``return -1`` where
    the success path returns a count. The caller can tell them apart.
  * A handler that raises, anywhere in its body.
  * A handler whose last statement is not a ``return``: it assigns the
    default and falls through, or falls through to a ``return`` after the
    ``try``. That shape is real (@backup's ``state/backup_timestamps.py`` and
    ``drive/share.py``) and this rule does not read it.
  * A generator: ``yield`` functions have no return value to compare.
  * A ``return`` inside ``finally``: it runs on both paths, so it is not the
    success path.
  * A success ``return`` of a call, an attribute, or a name first bound to
    anything but a literal (a parameter, a call, a loop target): what it
    returns cannot be read from the statement.
  * Nested functions are judged on their own returns, never their parent's.

CHECK FIRST (2026-09-25, before the rule landed). See the page's check-first
section for the fleet, per-branch and sample numbers.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

STANDARD = "LOGGED_FALLBACK"
STANDARD_KEY = "logged_fallback"

#: Scopes a function's own statements stop at.
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

#: Zero-argument constructors that build an empty container.
EMPTY_CALLS = frozenset({"dict", "list", "tuple", "set"})

#: Statements that bind names to something other than one readable expression.
BINDERS = (ast.AugAssign, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.NamedExpr)

#: The key every string built from an exception compares under.
EXCEPTION_TEXT = ("str", "*")

CURE = "re-raise, or return a value the success path cannot return and name it in the docstring"
WHY = "the success path can return the same value, so the caller cannot tell failure from an answer"


def own_nodes(function: ast.AST) -> List[ast.AST]:
    """Every node of a function's body, never descending into a nested scope."""
    body = getattr(function, "body", [])
    stack = [node for node in body if not isinstance(node, SCOPES)]
    nodes: List[ast.AST] = []
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, SCOPES))
    return nodes


def _inside(nodes: List[ast.AST], owners: List[ast.AST]) -> Set[int]:
    """The ids of every node that sits under one of ``owners``, within ``nodes``."""
    wanted = {id(node) for node in nodes}
    found: Set[int] = set()
    stack = list(owners)
    while stack:
        node = stack.pop()
        if id(node) in wanted:
            found.add(id(node))
        stack.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, SCOPES))
    return found


def literal_key(value: Optional[ast.AST], exception: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """A comparable key for a literal default, or None when the value is not one."""
    if isinstance(value, ast.Constant):
        return (type(value.value).__name__, repr(value.value))
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts:
        return ("empty", type(value).__name__.lower())
    if isinstance(value, ast.Dict) and not value.keys:
        return ("empty", "dict")
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and not value.args and not value.keywords:
        if value.func.id in EMPTY_CALLS:
            return ("empty", value.func.id)
    if exception and _names_exception(value, exception):
        return EXCEPTION_TEXT
    return None


def _names_exception(value: Optional[ast.AST], exception: str) -> bool:
    """An f-string that interpolates the exception, or ``str(exception)``."""
    if isinstance(value, ast.JoinedStr):
        return any(isinstance(node, ast.Name) and node.id == exception for node in ast.walk(value))
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "str":
        return len(value.args) == 1 and isinstance(value.args[0], ast.Name) and value.args[0].id == exception
    return False


def _binding_targets(node: ast.AST) -> List[Tuple[str, Optional[ast.AST]]]:
    """(name, the value it is bound to, or None when that is not one expression)."""
    bound: List[Tuple[str, Optional[ast.AST]]] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                bound.append((target.id, node.value))
            else:
                bound.extend((name.id, None) for name in ast.walk(target) if isinstance(name, ast.Name))
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        bound.append((node.target.id, node.value))
    elif isinstance(node, BINDERS):
        bound.extend(
            (name.id, None) for name in ast.walk(node) if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store)
        )
    return bound


def first_bindings(function: ast.AST, nodes: List[ast.AST]) -> Dict[str, Optional[ast.AST]]:
    """Name -> the value of its FIRST binding in the function; parameters bind first, to nothing."""
    first: Dict[str, Optional[ast.AST]] = {}
    arguments = getattr(function, "args", None)
    if isinstance(arguments, ast.arguments):
        for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs:
            first[arg.arg] = None
        for arg in (arguments.vararg, arguments.kwarg):
            if arg is not None:
                first[arg.arg] = None
    ordered = sorted(nodes, key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))
    for node in ordered:
        for name, value in _binding_targets(node):
            first.setdefault(name, value)
    return first


def _success_keys(function: ast.AST, nodes: List[ast.AST], excluded: Set[int]) -> Set[Tuple[str, str]]:
    """The literal keys the success path can return."""
    first = first_bindings(function, nodes)
    keys: Set[Tuple[str, str]] = set()
    for node in nodes:
        if not isinstance(node, ast.Return) or id(node) in excluded or node.value is None:
            continue
        value = node.value
        if isinstance(value, ast.Name):
            value = first.get(value.id)
        key = literal_key(value)
        if key is not None:
            keys.add(key)
            if key[0] == "str":
                keys.add(EXCEPTION_TEXT)
    return keys


def _judge_function(function: ast.AST) -> List[Tuple[int, str]]:
    """(line, the default's source) for every convicted handler in one function."""
    nodes = own_nodes(function)
    if any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in nodes):
        return []
    handlers = [node for node in nodes if isinstance(node, ast.ExceptHandler)]
    if not handlers:
        return []
    owners: List[ast.AST] = list(handlers)
    owners.extend(stmt for node in nodes if isinstance(node, ast.Try) for stmt in node.finalbody)
    excluded = _inside(nodes, owners)
    success = _success_keys(function, nodes, excluded)
    hits: List[Tuple[int, str]] = []
    for handler in handlers:
        last = handler.body[-1] if handler.body else None
        if not isinstance(last, ast.Return) or last.value is None:
            continue
        if any(isinstance(node, ast.Raise) for node in own_nodes(handler)):
            continue
        key = literal_key(last.value, handler.name)
        if key is not None and key in success:
            hits.append((last.lineno, ast.unparse(last.value)))
    return hits


def scan(tree: ast.AST) -> List[Tuple[int, str]]:
    """(line of the handler's return, the default) for every logged fallback in a file."""
    hits: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hits.extend(_judge_function(node))
    return sorted(hits)


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[logged_fallback] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Logged fallback", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a product file for a handler that returns a default the success path also returns.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard and per line.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
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
        logger.info("[logged_fallback] Unparseable %s: %s", module_path, exc)
        return _result(True, _one_check(True, "Not judged: the file does not parse (ruff convicts that)"), 100)

    hits = [hit for hit in scan(tree) if not is_bypassed(module_path, STANDARD_KEY, hit[0], bypass_rules)]
    if not hits:
        return _result(True, _one_check(True, "No handler returns a default the success path can also return"), 100)

    # Every hit on ONE check: checklist._format_failure prints the first failed
    # check and appends "(+N more)", so one check per hit would hide the rest.
    detail = "\n".join(f"{path.name}:{line} except returns {default} - {WHY}; {CURE}" for line, default in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
