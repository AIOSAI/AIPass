# =================== AIPass ====================
# Name: state_leak_check.py
# Description: State Leak Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
State Leak Standards Checker Handler

Test template v1, item 18: no test leaks state into the next. Every patch through
``monkeypatch``, every file under ``tmp_path``, nothing left in ``sys.modules``.

WHY THIS ONE IS DIFFERENT FROM THE OTHER SEVEN. A leaking test does not fail. It
makes an UNRELATED test lie, in a file its author never opened, and alphabetical
order decides whether anyone ever sees it. seedgo carried exactly one for months
(todo 139): twenty-five files here share a fixture that stubs
``sys.modules["...handlers.bypass"]`` with a MagicMock and re-imports a checker
against it. ``monkeypatch`` restores the sys.modules ENTRY, but it cannot undo a
name another module already bound -- ``trigger_check`` does
``from ...bypass.utils import matching_rule`` at import time -- and the poisoned
module then answers ``test_bypass.py`` with ``mock.utils.matching_rule()``.
``test_bypass`` runs FIRST in a forward run, which is the only reason the suite
was ever green.

THE RULE IS: A WRITE TO SHARED STATE, AT TEST TIME, WITH NOTHING TO PUT IT BACK.
Three shapes, measured 2026-09-22 over the fleet's 582 test files:

  (a) A DIRECT WRITE to state the process shares --
      ``os.environ[k] = v``, ``sys.path.insert(...)``, ``sys.modules[k] = v``,
      ``mod.attr = value`` / ``setattr(mod, name, value)`` on an imported
      product module.
  (b) A PATCHER STARTED AND NEVER STOPPED -- ``p = patch(...)`` then
      ``p.start()`` with no ``.stop()``, ``addCleanup`` or teardown in the same
      function. ``with patch(...)`` and ``@patch`` restore on exit and are never
      convicted; only the manual form can be left running.
  (c) ``os.chdir(...)`` with no restore. ``monkeypatch.chdir`` is the cure and
      the fleet already uses it 257 times.

NEVER CONVICTED, each for a measured reason:

  * EVERY ``monkeypatch`` VERB -- setattr (3,320), setitem (608), setenv (415),
    chdir (257), delenv (178), delitem (104), delattr (5), undo (2). 4,889 uses
    fleet-wide. They are the cure, not the offence.
  * A RESTORING FIXTURE IN SCOPE. @ai_mail's ``clean_env`` pops fourteen keys,
    yields, and puts them back; every raw ``os.environ[k] = v`` in a test that
    REQUESTS it is covered. An ``autouse=True`` one covers the whole file.
    Matching the fixture by request, not just by presence, is the difference
    between 39 acquittals and a rule that trusts a fixture nobody asked for.
  * A ``try`` WITH A ``finally`` in the same function -- @drone's
    ``test_registry.py`` saves ``sys.modules[...]``, swaps in None, and restores
    it in ``finally``. That is item 18 done by hand, and it works.
  * A ``sys.modules`` STUB NAMING AN AIPASS MODULE. Item 8, ``import_site``,
    already convicts it and this rule does not charge it twice -- which is why
    the checker does NOT convict ``test_checkers_batch9.py``, the very file
    whose leak this dispatch cured. The leak was real and import_site names it
    at lines 43, 48 and 51. Said plainly in mock_console.md's sibling, and in
    the reply.
  * A WRITE AT IMPORT TIME. Item 18 says "no test leaks into the NEXT"; a
    module-level write happens once, before any test, and every test in the file
    sees the same thing. 22 fleet sites, counted in the passing message.
  * A WRITE TO SOMETHING THE TEST BUILT -- a local, a Mock, a ``tmp_path``
    file. The base of an attribute write has to be a name bound by an ``aipass``
    import for this rule to see it at all.

TWO STATED LIMITS.

  * A FIXTURE IN THE FILE'S CONFTEST is invisible here. One pass reads one file,
    so a restoring fixture next door cannot be credited. Nothing in the fleet
    currently relies on one for these families, but a future one would be a
    false positive, and it would be an obvious one.
  * ``monkeypatch.delitem(sys.modules, name, raising=False)`` RECORDS NOTHING
    when the key is absent -- the cold-run case -- so it is a restore that
    restores nothing. It is the exact mechanism of todo 139 and it is NOT
    convicted here, because the write it pairs with is import_site's. Counted
    and reported instead: 104 sites in 68 files.
"""

import ast
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


def _patcher_names(body: List[ast.AST]) -> Set[str]:
    """Names bound to a ``patch(...)`` object inside this function."""
    names: Set[str] = set()
    for node in body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Call) and _tail_name(value.func) in _PATCH_CALLS:
            names.add(node.targets[0].id)
    return names


def _unstopped_patchers(body: List[ast.AST]) -> List[Tuple[int, str]]:
    """(line, name) for every patcher started here and never stopped here."""
    started: List[Tuple[int, str]] = []
    stopped: Set[str] = set()
    everything_stopped = False
    patchers = _patcher_names(body)
    for node in body:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        base = _base_name(node.func)
        if name in _STOPPERS and base not in patchers:
            everything_stopped = True
        elif name == "start" and base in patchers:
            started.append((node.lineno, base))
        elif name == "stop" and base in patchers:
            stopped.add(base)
    if everything_stopped:
        return []
    return [(line, name) for line, name in started if name not in stopped]


def _functions(tree: ast.Module) -> Tuple[Dict[int, ast.AST], Dict[int, List[ast.AST]]]:
    """(node -> the OUTERMOST function holding it, function -> its own nodes).

    One descent that carries the enclosing function down and collects each
    function's body on the way, rather than a fresh ``ast.walk`` per function
    per pass. The walk-per-function form spent 14.1s of the checker's 19.3s
    over the fleet re-walking every node once for each function above it.
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


def _parse(source: str, what: str) -> ast.Module | None:
    """The file's tree, or None when Python cannot read it.

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
    # Depth ONE only. ``mod.FLAG = False`` rebinds the module's own name and the
    # next test reads it; ``mod.helper.return_value = x`` configures an object the
    # module holds, which is ordinarily a Mock and nobody's shared state. 45 of
    # prax's and trigger's nominations are the second kind.
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
        for line, name in _unstopped_patchers(body):
            findings.append((line, f"{name}.start() with no stop()"))

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
    """Lines writing shared state at MODULE scope, before any test runs.

    Counted, never convicted. Item 18 is about one test leaking into the NEXT;
    a write at import time happens once and every test in the file sees the same
    thing. 22 fleet sites.
    """
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

    hits = [h for h in scan(source) if not is_bypassed(module_path, STANDARD_KEY, h[0], bypass_rules)]

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
