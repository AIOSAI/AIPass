# =================== AIPass ====================
# Name: caller_file_depth_check.py
# Description: Caller File Depth Standards Checker - __file__ handed to a depth function from a layout it does not fit
# Version: 1.1.0
# Created: 2026-11-17
# Modified: 2026-11-18
# =============================================

"""Caller File Depth Standards Checker

Reference: caller_file_depth.md. A depth function climbs a fixed number of levels (two or more) from a path it is
handed and treats the landing as the caller's branch root, for a file at ``<branch>/apps/...``. A call handing it
``__file__`` is convicted when the caller, from any place it runs, is not at that layout:

- the source file itself sits at another depth, or not under its branch's ``apps/``;
- a copy of it runs from a folder beside ``apps/`` (hooks promotes ``apps/`` to ``.live-<stamp>/``): the depth
  still lands on the branch by coincidence, and the next change to the function breaks every tool call.

A run location is seen only when the copy is on disk; a clean checkout, a wheel or a temp copy is not seen.
"""

import ast
from functools import lru_cache, partial
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.sentry.apps.handlers.aipass_standards.check_support import (
    find_enclosing_function,
    parse,
    read_text,
    result,
    tail_name,
)
from aipass.sentry.apps.handlers.aipass_standards.json_handler_check import BY_NAME_CLAIMS, by_name_line
from aipass.sentry.apps.handlers.bypass.utils import FILE_SCOPE, is_bypassed
from aipass.sentry.apps.handlers.json import json_handler

APPLIES_TO = "production"
AUDIT_SCOPE = "all_files"

STANDARD = "CALLER_FILE_DEPTH"
STANDARD_KEY = "caller_file_depth"

#: Wraps that keep the path they are given.
_KEEPS = frozenset({"Path", "PurePath", "abspath", "realpath", "normpath"})
#: Folders that are never a source of depth functions or a run location.
_SKIP = frozenset({"tests", "docs.local", "__pycache__", "artifacts"})

_parse = partial(parse, tag=STANDARD_KEY)
_read = partial(read_text, tag=STANDARD_KEY)
_result = partial(result, standard=STANDARD)


def _levels(node: ast.AST, params: frozenset) -> Optional[int]:
    """Levels climbed from one of ``params``, or None when the expression does not start at one."""
    if isinstance(node, ast.Name):
        return 0 if node.id in params else None
    if isinstance(node, ast.Call):
        name = tail_name(node.func)
        if name in _KEEPS and node.args:
            return _levels(node.args[0], params)
        if name in ("resolve", "absolute") and isinstance(node.func, ast.Attribute):
            return _levels(node.func.value, params)
        if name == "dirname" and node.args:
            inner = _levels(node.args[0], params)
            return None if inner is None else inner + 1
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        inner = _levels(node.value, params)
        return None if inner is None else inner + 1
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, int):
            inner = _levels(node.value.value, params)
            return None if inner is None else inner + node.slice.value + 1
    return None


def _skipped(parts: Tuple[str, ...]) -> bool:
    return any(part in _SKIP or part.startswith(".") for part in parts)


@lru_cache(maxsize=4)
def depth_functions(source_root: str) -> Dict[str, int]:
    """Every function under src/aipass that climbs two or more levels from a parameter, by name: its climb."""
    root = Path(source_root)
    found: Dict[str, int] = {}
    for path in root.glob("*/**/*.py"):
        if _skipped(path.relative_to(root).parts):
            continue
        source = _read(path)
        tree = _parse(source) if source is not None else None
        if tree is None:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = frozenset(a.arg for a in fn.args.args + fn.args.kwonlyargs) - {"self", "cls"}
            climb = max((lv for node in ast.walk(fn) if (lv := _levels(node, params))), default=0)
            # shortcut: matched by name fleet-wide; two depth functions sharing a name keep the deeper climb
            if climb >= 2:
                found[fn.name] = max(climb, found.get(fn.name, 0))
    return found


def _source_root(path: Path) -> Optional[Path]:
    parts = path.parts
    for index in range(len(parts) - 2, -1, -1):
        if parts[index : index + 2] == ("src", "aipass"):
            return Path(*parts[: index + 2])
    return None


def _run_locations(path: Path, branch: Path) -> List[Path]:
    """The file itself, plus each copy of it in a folder beside its branch's apps/ (a promoted snapshot)."""
    locations = [path]
    rel = path.relative_to(branch)
    if rel.parts[0] != "apps":
        return locations
    below = Path(*rel.parts[1:])
    for sibling in sorted(branch.iterdir()):
        if sibling.is_dir() and sibling.name not in ("apps", ".archive") and (sibling / below).is_file():
            locations.append(sibling / below)
    return locations


def _misfit(location: Path, branch: Path, climb: int) -> Optional[str]:
    """Why ``location`` is not the layout a ``climb``-level depth function assumes, or None when it is."""
    rel = location.relative_to(branch)
    if len(rel.parts) == climb and rel.parts[0] == "apps":
        return None
    if len(rel.parts) == climb:
        return f"from {branch.name}/{rel} the climb lands on the branch only by coincidence of depth"
    return f"from {branch.name}/{rel} the climb lands on {location.parents[climb - 1].name}/, not the branch"


def _hands_own_file(call: ast.Call) -> bool:
    """True when the first argument is this file's own ``__file__``, bare or wrapped."""
    return bool(call.args) and _levels(call.args[0], frozenset({"__file__"})) == 0


def _one_check(passed: bool, message: str) -> List[Dict]:
    return [{"name": "Caller file depth", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Convict each call handing __file__ to a depth function from a place whose layout it does not fit."""
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .sentry/bypass.json"), 100)
    path = Path(module_path).resolve()
    root = _source_root(path)
    if root is None or path == root or len(path.relative_to(root).parts) < 2:
        return _result(True, _one_check(True, "Not inside a branch under src/aipass, no caller layout to judge"), 100)
    source = _read(path)
    tree = _parse(source) if source is not None else None
    if tree is None:
        return _result(False, _one_check(False, "Cannot be read as Python, calls unjudged"), 0)
    functions = depth_functions(str(root))
    branch = root / path.relative_to(root).parts[0]
    checks = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and tail_name(call.func) in functions and _hands_own_file(call)):
            continue
        name, climb = tail_name(call.func), functions[tail_name(call.func)]
        misfits = [why for loc in _run_locations(path, branch) if (why := _misfit(loc, branch, climb))]
        holder = find_enclosing_function(tree, call.lineno)
        function = holder.name if holder else FILE_SCOPE
        if not misfits or is_bypassed(module_path, STANDARD_KEY, call.lineno, bypass_rules, function):
            continue
        cure = "pass the branch root explicitly, or find it by a marker, never by depth"
        if branch.name in BY_NAME_CLAIMS:
            cure = f"bind by name as the json_handler claim names it: {by_name_line(branch.name).strip()}"
        message = (
            f"{path.name}:{call.lineno} hands __file__ to {name}(), which climbs {climb} levels to find the branch: "
            f"{'; '.join(misfits)} - {cure}"
        )
        checks.append({"name": "Caller file depth", "passed": False, "line": call.lineno, "function": function})
        checks[-1]["message"] = message
    if not checks:
        return _result(True, _one_check(True, "No __file__ handed to a depth function from a layout it misfits"), 100)
    json_handler.log_operation("check_completed", {"file": module_path, "standard": STANDARD_KEY, "sites": len(checks)})
    return _result(False, checks, 0)
