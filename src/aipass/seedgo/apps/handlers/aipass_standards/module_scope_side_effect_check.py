# =================== AIPass ====================
# Name: module_scope_side_effect_check.py
# Description: Module Scope Side Effect Standards Checker Handler
# Version: 1.1.1
# Created: 2026-09-25
# Modified: 2026-10-17
# =============================================

"""
Module Scope Side Effect Standards Checker Handler

Reference: module_scope_side_effect.md
"""

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.applicability import is_test_path
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "everywhere"
AUDIT_SCOPE = "all_files"

STANDARD = "MODULE_SCOPE_SIDE_EFFECT"
STANDARD_KEY = "module_scope_side_effect"

CURE = "move it into a fixture (monkeypatch / tmp_path) or into the test that needs it"

#: A cure that is not the test-file one, by shape.
CURES: Dict[str, str] = {
    "signal_disposition": 'set it where the process starts, under `if __name__ == "__main__":`',
}

#: The shapes judged in every file, not only in a collected test file.
EVERYWHERE_SHAPES: frozenset[str] = frozenset({"signal_disposition"})

#: The pass sentence for a file only EVERYWHERE_SHAPES are judged in.
ONLY_SIGNALS_PASS = "Not a collected test file: only signal_disposition is judged here, and nothing sets one"

#: Why each shape is a defect at collection time.
WHY: Dict[str, str] = {
    "audit_hook": "installed at collection for the whole session, and an audit hook can never be removed",
    "host_read": "reads the host at import; if it raises, every test in the file is lost before one runs",
    "environ_write": "changes the process environment for every test collected after it",
    "sys_modules_write": "swaps a module for every test collected after it",
    "sys_path_write": "changes import resolution for every test collected after it",
    "module_attr_write": "monkeypatches an imported object at collection, with nothing to undo it",
    "cwd_change": "moves the working directory for every test collected after it",
    "global_recorder": "module state that functions rebind via `global`, shared by every test in the session",
    "signal_disposition": (
        "changes how the process answers a signal for the rest of its life, and a module a test imports "
        "runs it in every pytest worker at collection"
    ),
}

#: Calls that read the host, by canonical dotted name.
HOST_READS: frozenset[str] = frozenset(
    {"pathlib.Path.home", "pathlib.Path.cwd", "os.path.expanduser", "os.getcwd", "os.getcwdb"}
)

#: Methods that mutate a mapping or list in place.
MUTATORS: frozenset[str] = frozenset({"setdefault", "update", "pop", "popitem", "clear"})
LIST_MUTATORS: frozenset[str] = frozenset({"insert", "append", "extend", "remove", "pop", "clear"})

#: Canonical name of a shared container -> the shape a write to it is.
CONTAINERS: Dict[str, str] = {
    "os.environ": "environ_write",
    "sys.modules": "sys_modules_write",
    "sys.path": "sys_path_write",
}

#: Plain calls that are a shape on their own.
CALLS: Dict[str, str] = {
    "sys.addaudithook": "audit_hook",
    "os.putenv": "environ_write",
    "os.unsetenv": "environ_write",
    "os.chdir": "cwd_change",
    "signal.signal": "signal_disposition",
    "signal.alarm": "signal_disposition",
    "signal.setitimer": "signal_disposition",
}

#: The file names pytest collects as tests.
EXEMPT = "conftest.py"


def is_collected_test(name: str) -> bool:
    """Whether pytest collects this file name as a test module."""
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _is_main_guard(test: ast.expr) -> bool:
    """Whether an ``if`` test is ``__name__ == "__main__"``, either way round."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    sides = [test.left, test.comparators[0]]
    has_name = any(isinstance(side, ast.Name) and side.id == "__name__" for side in sides)
    has_main = any(isinstance(side, ast.Constant) and side.value == "__main__" for side in sides)
    return has_name and has_main


def _defaults(args: ast.arguments) -> List[ast.expr]:
    """The default expressions of a signature, evaluated when the def runs."""
    return list(args.defaults) + [default for default in args.kw_defaults if default is not None]


def import_time(node: ast.AST) -> Iterator[ast.AST]:
    """Every node under ``node`` that executes when the module is imported."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for expr in list(node.decorator_list) + _defaults(node.args):
            yield from import_time(expr)
        return
    if isinstance(node, ast.Lambda):
        for expr in _defaults(node.args):
            yield from import_time(expr)
        return
    if isinstance(node, ast.If) and _is_main_guard(node.test):
        for stmt in node.orelse:
            yield from import_time(stmt)
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from import_time(child)


def _bindings(node: ast.AST) -> List[Tuple[str, str]]:
    """(local name, dotted name) pairs one import statement binds."""
    if isinstance(node, ast.Import):
        pairs: List[Tuple[str, str]] = []
        for alias in node.names:
            top = alias.name.split(".")[0]
            pairs.append((alias.asname, alias.name) if alias.asname else (top, top))
        return pairs
    if isinstance(node, ast.ImportFrom):
        base = "." * node.level + (node.module or "")
        return [(alias.asname or alias.name, f"{base}.{alias.name}") for alias in node.names if alias.name != "*"]
    return []


def aliases(nodes: List[ast.AST]) -> Dict[str, str]:
    """Local name -> the dotted name it was imported as, from import-time imports."""
    return {local: full for node in nodes for local, full in _bindings(node)}


def dotted(expr: ast.AST, bound: Dict[str, str]) -> str | None:
    """The canonical dotted name of a Name/Attribute chain, through the file's imports."""
    if isinstance(expr, ast.Name):
        return bound.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        head = dotted(expr.value, bound)
        return f"{head}.{expr.attr}" if head else None
    return None


def _root(expr: ast.AST) -> str | None:
    """The leftmost Name of an Attribute chain."""
    while isinstance(expr, ast.Attribute):
        expr = expr.value
    return expr.id if isinstance(expr, ast.Name) else None


def _call_shape(call: ast.Call, bound: Dict[str, str]) -> str | None:
    """The shape a call is, or None."""
    func = call.func
    name = dotted(func, bound)
    if name in CALLS:
        return CALLS[name]
    if name in HOST_READS:
        return "host_read"
    if isinstance(func, ast.Attribute):
        if func.attr == "expanduser" and isinstance(func.value, ast.Call):
            if dotted(func.value.func, bound) == "pathlib.Path":
                return "host_read"
        owner = dotted(func.value, bound)
        shape = CONTAINERS.get(owner or "")
        methods = LIST_MUTATORS if owner == "sys.path" else MUTATORS
        if shape and func.attr in methods:
            return shape
    if name == "setattr" and call.args and _root(call.args[0]) in bound:
        return "module_attr_write"
    return None


def _target_shape(target: ast.AST, bound: Dict[str, str]) -> str | None:
    """The shape an assignment or ``del`` target is, or None."""
    if isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            shape = _target_shape(element, bound)
            if shape:
                return shape
        return None
    if isinstance(target, ast.Subscript):
        return CONTAINERS.get(dotted(target.value, bound) or "")
    if isinstance(target, ast.Attribute):
        if dotted(target, bound) == "sys.path":
            return "sys_path_write"
        if _root(target) in bound:
            return "module_attr_write"
    return None


def _targets(node: ast.AST) -> List[ast.AST]:
    """What a statement writes to."""
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AugAssign, ast.AnnAssign)) and node.value is not None:
        return [node.target]
    if isinstance(node, ast.Delete):
        return list(node.targets)
    return []


def _own_scope(func: ast.AST) -> Iterator[ast.AST]:
    """A function's own nodes, not those of the functions and classes nested in it."""
    for child in ast.iter_child_nodes(func):
        yield child
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            yield from _own_scope(child)


def rebound_globals(tree: ast.Module) -> Dict[str, int]:
    """Name -> line of the first ``global`` statement for names a function rebinds."""
    found: Dict[str, int] = {}
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nodes = list(_own_scope(func))
        declared = {name: node.lineno for node in nodes if isinstance(node, ast.Global) for name in node.names}
        stored = {
            node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
        }
        for name, line in declared.items():
            if name in stored:
                found.setdefault(name, line)
    return found


def _module_level(body: List[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that bind module globals at import: not in a class, def or main guard."""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(stmt, ast.If) and _is_main_guard(stmt.test):
            yield from _module_level(stmt.orelse)
            continue
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            yield from _module_level(getattr(stmt, field, []) or [])
        for handler in getattr(stmt, "handlers", []) or []:
            yield from _module_level(handler.body)
        for case in getattr(stmt, "cases", []) or []:
            yield from _module_level(case.body)


def _binds(stmt: ast.stmt) -> List[ast.AST]:
    """The targets a module-level statement binds names through."""
    if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        return _targets(stmt)
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        return [stmt.target]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return [item.optional_vars for item in stmt.items if item.optional_vars is not None]
    return []


def _binding_line(tree: ast.Module, name: str) -> int | None:
    """The first line the module binds this name at import, or None."""
    for stmt in _module_level(tree.body):
        for target in _binds(stmt):
            if any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(target)):
                return stmt.lineno
    return None


def scan(tree: ast.Module) -> List[Tuple[int, str]]:
    """(line, shape) for every side effect this file runs at import."""
    nodes = list(import_time(tree))
    bound = aliases(nodes)
    found: Set[Tuple[int, str]] = set()
    for node in nodes:
        if isinstance(node, ast.Call):
            shape = _call_shape(node, bound)
            if shape:
                found.add((getattr(node, "lineno", 0), shape))
        for target in _targets(node):
            shape = _target_shape(target, bound)
            if shape:
                found.add((getattr(node, "lineno", 0), shape))
    for name, global_line in rebound_globals(tree).items():
        found.add((_binding_line(tree, name) or global_line, "global_recorder"))
    return sorted(found)


def _snippet(lines: List[str], line: int) -> str:
    """The source line a finding sits on, trimmed for one message line."""
    text = lines[line - 1].strip() if 0 < line <= len(lines) else ""
    return text if len(text) <= 80 else text[:77] + "..."


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[module_scope_side_effect] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Module scope side effect", "passed": passed, "message": message}]


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check that a file does nothing at import that outlives the tests that import it.

    A collected test file in a tests tree is judged for every shape; any other
    file, conftest.py and a test-named product module included, for
    EVERYWHERE_SHAPES alone.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    every_shape = path.name != EXEMPT and is_collected_test(path.name) and is_test_path(str(path))
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        logger.info("[module_scope_side_effect] Unparseable %s: %s", module_path, exc)
        return _result(True, _one_check(True, "Not judged: the file does not parse (ruff convicts that)"), 100)

    findings = [(line, shape) for line, shape in scan(tree) if every_shape or shape in EVERYWHERE_SHAPES]
    if not findings:
        message = "Nothing at module scope outlives the file's own tests" if every_shape else ONLY_SIGNALS_PASS
        return _result(True, _one_check(True, message), 100)

    # One check for every hit: checklist._format_failure prints only the first failed check plus "(+N more)".
    lines = source.splitlines()
    detail = "\n".join(
        f"{path.name}:{line} {shape}: {_snippet(lines, line)} - {WHY[shape]}; {CURES.get(shape, CURE)}"
        for line, shape in findings
    )

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(findings)},
    )
    return _result(False, _one_check(False, detail), 0)
