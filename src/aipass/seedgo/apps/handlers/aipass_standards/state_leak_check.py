# =================== AIPass ====================
# Name: state_leak_check.py
# Description: State Leak Standards Checker Handler
# Version: 1.2.0
# Created: 2026-09-22
# Modified: 2026-10-16
# =============================================

"""
State Leak Standards Checker Handler

Test template v1, item 18: no test leaks state into the next. A write to shared
state at test time with nothing to put it back, in four shapes: (a) a direct
write to ``os.environ``, ``sys.path``, ``sys.modules`` or an imported product
module's attribute; (b) a patcher started and never stopped, held or one-line;
(c) ``os.chdir`` with no restore; (d) a call to a product function that writes
a module-level container the product's own public ``reset*`` writes, with no
fixture in the file or any conftest.py calling that reset. Every monkeypatch
verb, ``with patch``, ``@patch``, a ``try``/``finally`` and a restoring fixture
the test requests are acquittals; an aipass ``sys.modules`` key is import_site's
and an import-time write is counted, never charged. state_leak.md carries the
measurements and the stated limits.
"""

import ast
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "STATE_LEAK"
STANDARD_KEY = "state_leak"

#: The fixture object whose every verb records an undo. A name bound to it is
#: the cure, so nothing reached through it is ever a finding.
_MONKEYPATCH_NAMES: frozenset[str] = frozenset({"monkeypatch", "mp"})

#: Which family each monkeypatch verb puts back, so a function that uses one is
#: credited for that family and no other.
_MONKEYPATCH_COVERS: Dict[str, Tuple[str, ...]] = {
    "setenv": ("os.environ",),
    "delenv": ("os.environ",),
    "setitem": ("os.environ", "sys.modules"),
    "delitem": ("os.environ", "sys.modules"),
    "syspath_prepend": ("sys.path",),
    "chdir": ("cwd",),
    "setattr": ("attr",),
    "delattr": ("attr",),
    "undo": ("os.environ", "sys.modules", "sys.path", "cwd", "attr"),
}

#: Methods that mutate a mapping or list in place.
_MUTATORS: frozenset[str] = frozenset({"pop", "update", "clear", "setdefault", "insert", "append", "remove", "extend"})

#: Stopping a patcher, by any of the three names that do it.
_STOPPERS: frozenset[str] = frozenset({"stop", "addCleanup", "stopall"})

#: The calls that build a patcher. Only the manual form can be left running.
_PATCH_CALLS: frozenset[str] = frozenset({"patch", "object", "dict", "multiple"})

CURES: Dict[str, str] = {
    "os.environ": "monkeypatch.setenv / monkeypatch.delenv",
    "sys.modules": "monkeypatch.setitem",
    "sys.path": "monkeypatch.syspath_prepend",
    "attr": "monkeypatch.setattr",
    "cwd": "monkeypatch.chdir",
    "patcher": "stop() in teardown, or addCleanup(p.stop)",
}


def _tail_name(func: ast.expr) -> str:
    """The name a call is made under -- ``f`` for ``a.b.f(...)`` and ``f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _base_name(node: ast.expr) -> str:
    """The leftmost name of a dotted expression -- ``os`` for ``os.environ.pop``."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _family(target: ast.expr | None) -> str | None:
    """Which shared-state family this target belongs to, or None."""
    if target is None:
        return None
    node = target.value if isinstance(target, ast.Subscript) else target
    if not isinstance(node, ast.Attribute):
        return None
    base = _base_name(node)
    if base == "os" and node.attr == "environ":
        return "os.environ"
    if base == "sys" and node.attr == "modules":
        return "sys.modules"
    if base == "sys" and node.attr == "path":
        return "sys.path"
    return None


def _imports_aipass(node: ast.AST) -> List[str]:
    """Names this one statement binds to an ``aipass`` import, if any."""
    if isinstance(node, ast.Import):
        return [a.asname or a.name.split(".")[0] for a in node.names if a.name.startswith("aipass")]
    if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("aipass"):
        return [a.asname or a.name for a in node.names]
    if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return []
    value = node.value
    named_aipass = (
        isinstance(value, ast.Call)
        and _tail_name(value.func) == "import_module"
        and bool(value.args)
        and isinstance(value.args[0], ast.Constant)
        and str(value.args[0].value).startswith("aipass")
    )
    return [node.targets[0].id] if named_aipass else []


def _product_names(nodes: List[ast.AST]) -> Set[str]:
    """Names bound to something imported from an ``aipass`` package."""
    found: Set[str] = set()
    for node in nodes:
        found.update(_imports_aipass(node))
    return found


def _is_aipass_key(target: ast.expr) -> bool:
    """Whether a ``sys.modules`` subscript names an aipass module -- item 8's ground."""
    if not isinstance(target, ast.Subscript):
        return False
    key = target.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value.startswith("aipass")
    return False


def _statement_families(node: ast.AST) -> Set[str]:
    """Which families this one statement writes to."""
    families: Set[str] = set()
    if isinstance(node, (ast.Assign, ast.Delete)):
        for target in node.targets:
            families.add(_family(target) or ("attr" if isinstance(target, ast.Attribute) else ""))
        return families - {""}
    if not isinstance(node, ast.Call):
        return families
    name = _tail_name(node.func)
    if name == "chdir":
        families.add("cwd")
    elif name == "setattr":
        families.add("attr")
    elif name in _MUTATORS and isinstance(node.func, ast.Attribute):
        families.add(_family(node.func.value) or "")
    return families - {""}


def _written_families(function: ast.AST) -> Set[str]:
    """Every family a function writes to -- used to read what a fixture restores."""
    families: Set[str] = set()
    for node in ast.walk(function):
        families.update(_statement_families(node))
    return families


def _restoring_fixtures(nodes: List[ast.AST]) -> Tuple[Set[str], Dict[str, Set[str]]]:
    """(families every test is covered for, families each named fixture covers).

    A fixture counts only when it can actually run teardown: a ``yield`` or a
    ``finally``. ``autouse=True`` covers the file; anything else covers only the
    tests that ask for it by name.
    """
    autouse: Set[str] = set()
    by_name: Dict[str, Set[str]] = {}
    for function in nodes:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [ast.unparse(d) for d in function.decorator_list]
        if not any("fixture" in d for d in decorators):
            continue
        teardown = any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(function)) or any(
            isinstance(n, ast.Try) and n.finalbody for n in ast.walk(function)
        )
        if not teardown:
            continue
        families = _written_families(function)
        if not families:
            continue
        if any("autouse=True" in d for d in decorators):
            autouse |= families
        else:
            by_name[function.name] = families
    return autouse, by_name


def _covered(function: ast.AST, body: List[ast.AST], autouse: Set[str], by_name: Dict[str, Set[str]]) -> Set[str]:
    """Every family this function is already protected for."""
    covered = set(autouse)
    if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        parameters = {arg.arg for arg in function.args.args}
        for fixture, families in by_name.items():
            if fixture in parameters:
                covered |= families
        # A restoring fixture is the cure. Charging it for the `os.environ.update(saved)`
        # that IS the restore would convict the one function in the file doing item 18's
        # job by hand. (An autouse one is already covered -- its families are the file's.)
        covered |= by_name.get(function.name, set())
    for node in body:
        if isinstance(node, ast.Try) and node.finalbody:
            # A hand-written restore. @drone's test_registry.py is the fleet's one.
            return {"os.environ", "sys.modules", "sys.path", "cwd", "attr", "patcher"}
        if isinstance(node, ast.Call) and _base_name(node.func) in _MONKEYPATCH_NAMES:
            covered.update(_MONKEYPATCH_COVERS.get(_tail_name(node.func), ()))
    return covered


#: What the one-line form leaves behind. It names the reason, not just the shape:
#: the author has to see that there is nothing left to call stop() ON.
_UNSTOPPABLE = "patch(...).start() holds no patcher, so nothing can stop it"


def _is_patch_call(node: ast.expr | None) -> bool:
    """Whether this expression IS a ``patch(...)`` call, not a name holding one."""
    return isinstance(node, ast.Call) and _tail_name(node.func) in _PATCH_CALLS


def _patcher_event(node: ast.AST, patchers: Set[str]) -> Tuple[str, str, int]:
    """(kind, patcher name, line) for one node in the patcher pass.

    ``("", "", 0)`` when the node is not part of this pass at all.
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return "", "", 0
    name, base, line = node.func.attr, _base_name(node.func), node.lineno
    if name == "start" and _is_patch_call(node.func.value):
        return "unstoppable", "", line
    if name in _STOPPERS and base not in patchers:
        return "stopall", "", line
    if name in ("start", "stop") and base in patchers:
        return name, base, line
    return "", "", 0


def _patcher_names(body: List[ast.AST]) -> Set[str]:
    """Names bound to a ``patch(...)`` object inside this function."""
    names: Set[str] = set()
    for node in body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if _is_patch_call(node.value):
            names.add(node.targets[0].id)
    return names


def _held_but_unstopped(started: List[Tuple[int, str]], stopped: Set[str]) -> List[Tuple[int, str]]:
    """The named form: a patcher started in this function with no stop() in it."""
    return [(line, f"{name}.start() with no stop()") for line, name in started if name not in stopped]


def _unstopped_patchers(body: List[ast.AST]) -> List[Tuple[int, str]]:
    """(line, what was left running) for every patcher started and never stopped.

    A held ``p.start()`` needs a ``stop()``; the one-line ``patch(...).start()``
    holds nothing, so only a _STOPPERS call on anything else stands it down.
    """
    started: List[Tuple[int, str]] = []
    unstoppable: List[Tuple[int, str]] = []
    stopped: Set[str] = set()
    everything_stopped = False
    patchers = _patcher_names(body)
    for node in body:
        kind, base, line = _patcher_event(node, patchers)
        everything_stopped = everything_stopped or kind == "stopall"
        if kind == "unstoppable":
            unstoppable.append((line, _UNSTOPPABLE))
        elif kind == "start":
            started.append((line, base))
        elif kind == "stop":
            stopped.add(base)
    if everything_stopped:
        return []
    return unstoppable + _held_but_unstopped(started, stopped)


def _functions(tree: ast.Module) -> Tuple[Dict[int, ast.AST], Dict[int, List[ast.AST]]]:
    """(node -> the OUTERMOST function holding it, function -> its own nodes), in one descent.

    One descent, not an ``ast.walk`` per function: that form cost 14.1s of 19.3s.
    """
    holder: Dict[int, ast.AST] = {}
    bodies: Dict[int, List[ast.AST]] = {}
    stack: List[Tuple[ast.AST, ast.AST | None]] = [(tree, None)]
    while stack:
        node, enclosing = stack.pop()
        if enclosing is None and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            enclosing = node
            bodies[id(node)] = []
        if enclosing is not None:
            holder[id(node)] = enclosing
            bodies[id(enclosing)].append(node)
        for child in ast.iter_child_nodes(node):
            stack.append((child, enclosing))
    return holder, bodies


@lru_cache(maxsize=64)
def _parse(source: str, what: str) -> ast.Module | None:
    """The file's tree, read-only and shared by every pass, or None when Python cannot read it.

    ruff already convicts a syntax error, and a line number invented for a
    statement Python cannot parse sends its author to the wrong place.
    """
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        logger.info("[state_leak] Unparseable, nothing %s: %s", what, exc)
        return None


def _target_finding(target: ast.expr, covered: Set[str], product: Set[str]) -> str | None:
    """What an assignment or delete target leaves behind, or None."""
    family = _family(target)
    if family == "sys.modules" and _is_aipass_key(target):
        return None  # item 8, import_site, already charges it
    if family:
        return None if family in covered else f"a write to {family} with nothing to put it back"
    # Depth ONE only: ``mod.FLAG = x`` rebinds the module's name, while
    # ``mod.helper.return_value = x`` configures a held object, ordinarily a Mock.
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        if target.value.id in product and "attr" not in covered:
            return f"a write to the product's {target.value.id}.{target.attr}"
    return None


def _call_finding(node: ast.Call, covered: Set[str], product: Set[str]) -> str | None:
    """What a call leaves behind, or None."""
    if _base_name(node.func) in _MONKEYPATCH_NAMES:
        return None
    name = _tail_name(node.func)
    if name == "chdir" and _base_name(node.func) == "os":
        return None if "cwd" in covered else "os.chdir with no restore"
    if name in _MUTATORS and isinstance(node.func, ast.Attribute):
        family = _family(node.func.value)
        if family and family not in covered:
            return f"{family}.{name}() with nothing to put it back"
        return None
    if name == "setattr" and node.args and isinstance(node.args[0], ast.Name):
        if node.args[0].id in product and "attr" not in covered:
            attribute = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "?"
            return f"setattr on the product's {node.args[0].id}.{attribute}"
    return None


def _write_findings(
    nodes: List[ast.AST], holder: Dict[int, ast.AST], product: Set[str], guard
) -> List[Tuple[int, str]]:
    """(line, what was left behind) for every unrestored write at test time."""
    found: List[Tuple[int, str]] = []
    for node in nodes:
        if holder.get(id(node)) is None:
            continue  # module scope: once, before any test. Counted, not charged.
        covered = guard(holder[id(node)])
        if isinstance(node, (ast.Assign, ast.Delete)):
            for target in node.targets:
                what = _target_finding(target, covered, product)
                if what:
                    found.append((node.lineno, what))
        elif isinstance(node, ast.Call):
            what = _call_finding(node, covered, product)
            if what:
                found.append((node.lineno, what))
    return found


def scan(source: str) -> List[Tuple[int, str, str]]:
    """(line, what was left behind, the cure) for every leak in a test file."""
    tree = _parse(source, "scanned")
    if tree is None:
        return []

    # One materialised walk, reused by all three passes. Walking the tree afresh
    # per pass is what `mock_console` measured at 10.8s against 6.0s.
    nodes = list(ast.walk(tree))
    holder, bodies = _functions(tree)
    product = _product_names(nodes)
    autouse, by_name = _restoring_fixtures(nodes)
    cache: Dict[int, Set[str]] = {}

    def guard(function: ast.AST) -> Set[str]:
        """Families this function is protected for, computed once per function."""
        if id(function) not in cache:
            cache[id(function)] = _covered(function, bodies.get(id(function), []), autouse, by_name)
        return cache[id(function)]

    findings = _write_findings(nodes, holder, product, guard)
    for body in bodies.values():
        # The descent appends the function to its own body first, so body[0] is it.
        if "patcher" in guard(body[0]):
            continue
        findings.extend(_unstopped_patchers(body))

    hits: List[Tuple[int, str, str]] = []
    seen: Set[Tuple[int, str]] = set()
    for line, what in findings:
        if (line, what) in seen:
            continue
        seen.add((line, what))
        hits.append((line, what, _cure_for(what)))
    return sorted(hits)


def _cure_for(what: str) -> str:
    """The verb that would have put this one back."""
    for family, cure in CURES.items():
        if family in what:
            return cure
    if "start()" in what:
        return CURES["patcher"]
    if "chdir" in what:
        return CURES["cwd"]
    return CURES["attr"]


def counted_import_time_writes(source: str) -> List[int]:
    """Lines writing shared state at MODULE scope, before any test runs: counted, never convicted."""
    tree = _parse(source, "counted")
    if tree is None:
        return []

    holder, _bodies = _functions(tree)
    lines = []
    for node in ast.walk(tree):
        if holder.get(id(node)) is not None or not isinstance(node, (ast.Assign, ast.Delete)):
            continue
        if any(_family(target) for target in node.targets):
            lines.append(node.lineno)
    return sorted(set(lines))


#: Calls that build a module-level container the product then writes in place.
_CONTAINER_CALLS: frozenset[str] = frozenset({"dict", "list", "set"})

#: In-place verbs on a dict, list or set.
_IN_PLACE: frozenset[str] = _MUTATORS | frozenset({"add", "discard", "popitem"})

_FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _module_containers(tree: ast.Module) -> Set[str]:
    """Names a product module binds at its top level to a dict, list or set."""
    names: Set[str] = set()
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        value = getattr(node, "value", None)
        built = isinstance(value, ast.Call) and _tail_name(value.func) in _CONTAINER_CALLS
        if isinstance(value, (ast.Dict, ast.List, ast.Set)) or built:
            names.update(t.id for t in targets if isinstance(t, ast.Name))
    return names


def _containers_written(function: ast.AST, containers: Set[str]) -> Set[str]:
    """Which module containers one product function writes: a subscript, an in-place verb, a ``global`` rebind."""
    rebindable = {name for node in ast.walk(function) if isinstance(node, ast.Global) for name in node.names}
    written: Set[str] = set()
    for node in ast.walk(function):
        targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
        for target in targets if isinstance(node, (ast.Assign, ast.Delete, ast.AugAssign, ast.AnnAssign)) else []:
            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                written.add(target.value.id)
            elif isinstance(target, ast.Name) and target.id in rebindable:
                written.add(target.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _IN_PLACE:
            written.add(_base_name(node.func.value) if isinstance(node.func.value, ast.Name) else "")
    return written & containers


@lru_cache(maxsize=512)
def product_resets(source: str) -> Tuple[frozenset[str], frozenset[str]]:
    """(public ``reset*`` functions, functions writing what they reset, directly or via a same-module call)."""
    tree = _parse(source, "read as a product") if "def reset" in source else None
    if tree is None:
        return frozenset(), frozenset()
    containers = _module_containers(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, _FUNCTION_TYPES)}
    writes = {name: _containers_written(node, containers) for name, node in functions.items()}
    resets = {name for name, written in writes.items() if name.startswith("reset") and written}
    reset_state = set().union(*(writes[name] for name in resets))
    writers = {name for name, written in writes.items() if written & reset_state} - resets
    grew = bool(writers)
    while grew:
        grew = False
        for name, node in functions.items():
            calls = {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            if name not in writers | resets and calls & writers:
                writers.add(name)
                grew = True
    return frozenset(resets), frozenset(writers)


def _resolve(roots: List[Path], dotted: str) -> Path | None:
    """The source file of an ``aipass`` module under one of the import roots."""
    for root in roots:
        base = root.joinpath(*dotted.split("."))
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                return candidate
    return None


_API = Tuple[frozenset[str], frozenset[str]]


def _product_bindings(tree: ast.Module, test_path: Path) -> Tuple[Dict[str, _API], Dict[str, frozenset[str]]]:
    """(module name -> (resets, writers), writer function name -> resets) for the file's top-level imports."""
    roots = [directory for directory in test_path.parents if (directory / "aipass").is_dir()]
    modules: Dict[str, _API] = {}
    functions: Dict[str, frozenset[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level or not (node.module or "").startswith("aipass"):
            continue
        for alias in node.names:
            submodule = _resolve(roots, f"{node.module}.{alias.name}")
            if submodule is not None:
                resets, writers = product_resets(_read(submodule) or "")
                if resets:
                    modules[alias.asname or alias.name] = (resets, writers)
                continue
            parent = _resolve(roots, node.module or "")
            resets, writers = product_resets(_read(parent) or "") if parent else (frozenset(), frozenset())
            if alias.name in writers:
                functions[alias.asname or alias.name] = resets
    return modules, functions


def _reset_fixtures(tree: ast.Module) -> Tuple[Set[str], Dict[str, Set[str]]]:
    """(names every autouse fixture calls, names each requested fixture calls)."""
    autouse: Set[str] = set()
    by_name: Dict[str, Set[str]] = {}
    for function in ast.walk(tree):
        if not isinstance(function, _FUNCTION_TYPES):
            continue
        decorators = [ast.unparse(d) for d in function.decorator_list]
        if not any("fixture" in d for d in decorators):
            continue
        calls = {_tail_name(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}
        if any("autouse=True" in d for d in decorators):
            autouse |= calls
        else:
            by_name[function.name] = calls
    return autouse, by_name


def _conftests(test_path: Path) -> List[Path]:
    """Every conftest.py pytest loads for this file, up to the project root."""
    found: List[Path] = []
    for directory in test_path.parents:
        conftest = directory / "conftest.py"
        if conftest.is_file() and conftest != test_path:
            found.append(conftest)
        if (directory / "pyproject.toml").is_file() or (directory / ".git").exists():
            break
    return found


def _reset_credit(
    test: ast.FunctionDef | ast.AsyncFunctionDef, autouse: Set[str], by_name: Dict[str, Set[str]]
) -> Set[str]:
    """Names a test is reset by: autouse fixtures, the fixtures it requests, its own ``finally``."""
    credit = set(autouse)
    requested = {arg.arg for arg in test.args.args}
    for decorator in test.decorator_list:
        if "usefixtures" in ast.unparse(decorator) and isinstance(decorator, ast.Call):
            requested.update(str(a.value) for a in decorator.args if isinstance(a, ast.Constant))
    for fixture in requested:
        credit |= by_name.get(fixture, set())
    for node in ast.walk(test):
        if isinstance(node, ast.Try) and node.finalbody:
            finals = [n for statement in node.finalbody for n in ast.walk(statement)]
            credit.update(_tail_name(n.func) for n in finals if isinstance(n, ast.Call))
    return credit


def _writer_call(
    node: ast.AST, modules: Dict[str, _API], functions: Dict[str, frozenset[str]]
) -> Tuple[str, frozenset[str]]:
    """(the call as written, the resets it owes) when a node calls a product writer, else ("", empty)."""
    if not isinstance(node, ast.Call):
        return "", frozenset()
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in modules:
        resets, writers = modules[func.value.id]
        return (f"{func.value.id}.{func.attr}", resets) if func.attr in writers else ("", frozenset())
    if isinstance(func, ast.Name) and func.id in functions:
        return func.id, functions[func.id]
    return "", frozenset()


def scan_product_resets(test_path: Path, source: str) -> List[Tuple[int, str, str]]:
    """(line, what was left behind, the cure) for shape (d): a product's own reset that no fixture calls."""
    tree = _parse(source, "scanned") if "aipass" in source else None
    if tree is None:
        return []
    modules, functions = _product_bindings(tree, test_path)
    if not modules and not functions:
        return []
    autouse, by_name = _reset_fixtures(tree)
    for conftest in _conftests(test_path):
        conftest_tree = _parse(_read(conftest) or "", "read as a conftest")
        more_autouse, more_named = _reset_fixtures(conftest_tree) if conftest_tree else (set(), {})
        autouse |= more_autouse
        for name, calls in more_named.items():
            by_name.setdefault(name, set()).update(calls)
    hits: List[Tuple[int, str, str]] = []
    for test in ast.walk(tree):
        if not isinstance(test, _FUNCTION_TYPES) or not test.name.startswith("test"):
            continue
        credit = _reset_credit(test, autouse, by_name)
        for node in ast.walk(test):
            call, resets = _writer_call(node, modules, functions)
            if isinstance(node, ast.Call) and call and not resets & credit:
                reset = sorted(resets)[0]
                what = f"{call}() writes the product's own state and nothing calls {reset}()"
                hits.append((node.lineno, what, f"an autouse fixture in conftest.py calling {reset}()"))
    return sorted(set(hits))


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[state_leak] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "State leak", "passed": passed, "message": message}]


def _clean_message(import_time: List[int]) -> str:
    """What a passing file says, carrying the import-time count."""
    if not import_time:
        return "Every change this file makes is put back"
    subject = "write is" if len(import_time) == 1 else "writes are"
    return (
        f"Every change this file makes is put back "
        f"({len(import_time)} import-time {subject} counted, which the rule allows)"
    )


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check one test file for state it leaves behind for the next test.

    Args:
        module_path: Path to the test file to check.
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

    found = sorted(scan(source) + scan_product_resets(path.resolve(), source))
    hits = [h for h in found if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

    if not hits:
        return _result(True, _one_check(True, _clean_message(counted_import_time_writes(source))), 100)

    # One line per hit, all inside ONE check rather than one check each --
    # checklist._format_failure prints the FIRST failed check and appends
    # "(+N more)", so N checks would show one hit and hide the rest.
    detail = "\n".join(f"{path.name}:{line} {what} - {cure}" for line, what, cure in hits)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "hits": len(hits)},
    )
    return _result(False, _one_check(False, detail), 0)
