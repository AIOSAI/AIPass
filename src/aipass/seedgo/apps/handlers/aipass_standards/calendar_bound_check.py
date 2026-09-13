# =================== AIPass ====================
# Name: calendar_bound_check.py
# Description: Calendar Bound Standards Checker Handler
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""Calendar Bound Standards Checker Handler.

WHERE IT CAME FROM. main and PR #767 went red on every host on one test:

    def test_a_slotted_job_is_seeded_before_it_can_fire(self, capsys):
        results, _save = self._tick(interval_job_with_slot(), {"jobs": {}})
        assert runstate["jobs"][...]["last_run"] == "2026-09-06T03:00:00"

The seeder rolls a weekly slot forward to the latest occurrence at or before
``datetime.now()``, so the expected value is a fact about NOW. The test froze
nothing. It was green from 2026-09-06 to 2026-09-12, merged green, and turned
red by the calendar at 2026-09-13T03:00 - a time bomb that passed every gate
because every gate ran inside its one-week window. No rule read the clock:
pytest_quality asks what a test proves (a literal equality is a strong oracle),
host_portability and windows_compat ask which HOST a test runs on, and the
execution lane runs the suite on today's date, which is exactly the blind spot.

THE RULE HAS THREE LEGS AND ALL THREE MUST STAND.

    1. The unit ASSERTS A DATE LITERAL: an ISO string or ``datetime(...)`` /
       ``date(...)`` with integer literals, as an operand of an assert
       comparison or a unittest ``assert*`` method.
    2. The unit REACHES PRODUCTION THAT COMPUTES WITH THE CLOCK, within
       ``MAX_HOPS`` calls: a function that feeds ``datetime.now()`` /
       ``date.today()`` / ``time.time()`` (or a local name bound to one, or a
       one-level wrapper that returns one) into arithmetic, an ordering or
       equality, or another call. The incident is four hops deep: run_tick,
       _tick_body, _seed_interval_slots, seed_interval_slot.
    3. The unit DOES NOT OWN THE CLOCK.

LEG 2 IS WHERE THE NOISE DIED, AND WHY IT READS PRODUCTION. The shape as first
posed - a date literal in an assert, in a test whose imported module calls
``datetime.now()``, with no freeze - convicted 58 units fleet-wide. Reading
them: 57 were round trips. A date goes in through a helper, fixture or module
constant and comes out unchanged, while the module under test also STAMPS
``last_updated`` with now. Stamping is not deriving: ``now().isoformat()``
stored in a field cannot change what another field holds. So a clock value
counts only when something computes with it; a value turned into a string
(``isoformat``, ``strftime``), logged, formatted or stored is a stamp. A textual
narrowing ("the expected date appears nowhere else in the unit") was measured
too and rejected: the incident's date DOES appear as input (the slot default),
and inlining a helper would launder a real time bomb.

WHAT OWNS THE CLOCK (acquits, and is the cure this rule teaches):

  - a ``patch`` / ``patch.object`` / ``monkeypatch.setattr`` whose target names
    datetime, date, time, now, today, clock, freeze or frozen - in the unit, its
    class's helper methods, or a same-file function the unit calls;
  - an injected instant: a ``now=`` / ``clock=`` / ``today=`` / ``timestamp=``
    style keyword, or a ``datetime(...)`` literal handed positionally to a call;
  - a fixture parameter named for a clock (``frozen_now``, ``fixed_clock``);
  - a ``freeze_time`` / ``time_machine`` decorator on the unit or its class;
  - an autouse fixture in the file or a conftest.py above it that patches one.

A patch on ``sleep``, ``monotonic`` or ``perf_counter`` owns nothing: it stops
a wait or a stopwatch, never the calendar. ai_mail's wake helper patches
``wake.time.sleep`` and was acquitted by the word ``time`` until this was read.

A patched call is also CUT FROM THE WALK: a seam the unit stubbed is not a road
to the clock.

ALSO ACQUITTED: A DATE PRODUCTION SPELLS ITSELF. ``"2026-09-08" in step[2]``
(ai_mail test_wake) names the date of a ruling written into the refusal text;
it is a fact about the code, not the calendar, even though the same call path
ages a lock file against now. Read from production only - a string constant, by
substring, in a module on the trail that is not under a ``tests`` directory.
Docstrings do not count, and neither does the test's own spelling: the
incident's date sat in its own helper's default and first acquitted it.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM, all in the direction of FEWER flags:

  - an expected value held in a parametrize table or a variable is not read -
    only a literal operand is (the frozen-clock cure itself uses a table);
  - calls are followed by NAME: a function reached through an object that is
    not ``self``/``cls``, a module alias, or an import is invisible;
  - a clock read in another project's package is outside the walk;
  - a unit that owns the clock but freezes the WRONG module is acquitted.

Interface: AUDIT_SCOPE = "branch_level", entry point ``check_branch``. The
corpus is the branch's ``tests/`` and each ``lib/<skill>/tests/``; production
is read through the tests' own imports under the package root.
"""

import ast
import re
from collections import deque
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

from aipass.prax import logger
from aipass.seedgo.apps.handlers.aipass_standards.applicability import is_retired_path
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import SOURCE_SKIP_DIRS, is_disabled_file
from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored, load_ignore_entries
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "CALENDAR_BOUND"
_BYPASS_KEY = "calendar_bound"

#: tests/ is fingerprinted by the audit cache already; a skill's own tests/ under lib/ is not.
BRANCH_INPUTS = ("lib/*/tests/**/*.py",)

#: Below this the branch fails the standard, matching every other checker here.
PASS_THRESHOLD = 75

#: Calls from the unit to the clock read. The incident needed four.
MAX_HOPS = 6

_FUNC_NODE = Union[ast.FunctionDef, ast.AsyncFunctionDef]
_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?$")

_DATETIME_CLOCKS = frozenset({"now", "utcnow", "today"})
_TIME_CLOCKS = frozenset({"time", "time_ns", "localtime", "gmtime"})
_CONSTRUCTORS = frozenset({"datetime", "date"})

#: Methods that keep a clock value a clock value. isoformat/strftime end it: a string is a stamp.
_CARRY_ATTRS = frozenset({"astimezone", "replace", "date", "time", "timetz", "timestamp"})

#: Calls that report or store a value rather than compute with it.
_NON_DERIVING_CALLS = frozenset(
    {
        "str",
        "repr",
        "print",
        "format",
        "len",
        "bool",
        "isinstance",
        "type",
        "id",
        "hash",
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
        "critical",
        "dict",
        "update",
        "setdefault",
        "append",
        "extend",
        "add",
        "insert",
        "dump",
        "dumps",
        "write",
        "write_text",
    }
)

_ASSERT_METHODS = frozenset(
    {
        "assertEqual",
        "assertEquals",
        "assertNotEqual",
        "assertIn",
        "assertNotIn",
        "assertLess",
        "assertLessEqual",
        "assertGreater",
        "assertGreaterEqual",
    }
)

_PATCHERS = ("patch", "patch.object", "patch.dict", "setattr")

#: Patch targets that stop a wait or a stopwatch. Naming ``time`` is not owning the calendar.
_NOT_CLOCK_SEAMS = frozenset({"sleep", "monotonic", "perf_counter"})
_CLOCK_KWARGS = frozenset(
    {"now", "clock", "today", "at", "when", "current_time", "now_fn", "time_fn", "utcnow", "timestamp", "ts", "moment"}
)
_CLOCK_WORD = re.compile(r"datetime|\bdate\b|\btime\b|now|today|clock|freeze|frozen", re.IGNORECASE)
_CLOCK_FIXTURE = re.compile(r"clock|now|frozen|freeze|fixed_time|fake_time|today", re.IGNORECASE)
_FREEZE_DECORATOR = re.compile(r"freeze_time|time_machine|travel")


# =============================================
# PARSING AND MODULE RESOLUTION
# =============================================

_PARSE_CACHE: Dict[Tuple[str, int, int], Optional[ast.Module]] = {}


def _parse_uncached(path: Path) -> Optional[ast.Module]:
    """Parse one file, or None when it cannot be read or parsed."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        logger.info("[calendar_bound] skipped %s: %s", path, exc)
        return None


def _parse(path: Path) -> Optional[ast.Module]:
    """Parse a file once per content stamp; production modules are shared across units."""
    try:
        stat = path.stat()
    except OSError as exc:
        logger.info("[calendar_bound] cannot stat %s: %s", path, exc)
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _PARSE_CACHE:
        _PARSE_CACHE[key] = _parse_uncached(path)
    return _PARSE_CACHE[key]


def _module_file(root: Path, dotted: str) -> Optional[Path]:
    """The source file for a dotted module under the package root, or None."""
    parts = dotted.split(".")
    if len(parts) < 2 or parts[0] != root.name:
        return None
    base = root.joinpath(*parts[1:])
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


class _Module:
    """One parsed module: its functions, its methods by name, and its imports under the package root."""

    def __init__(self, path: Path, tree: ast.Module, root: Path):
        """Index the module once; resolution is by name only."""
        self.path = path
        self.tree = tree
        self.root = root
        self.functions: Dict[str, _FUNC_NODE] = {}
        self.methods: Dict[str, _FUNC_NODE] = {}
        self.imports: Dict[str, Tuple[str, Optional[str]]] = {}
        self._strings: Optional[Set[str]] = None
        for node in tree.body:
            self._index_definition(node)
        for node in ast.walk(tree):
            self._index_import(node)

    def _index_definition(self, node: ast.stmt) -> None:
        """Record a top-level function, or every method of a top-level class."""
        if isinstance(node, _FUNC_TYPES):
            self.functions[node.name] = node
            return
        if isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, _FUNC_TYPES):
                    self.methods.setdefault(member.name, member)

    def _index_import(self, node: ast.AST) -> None:
        """Record an import that lands under the package root."""
        prefix = self.root.name + "."
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(prefix):
            for alias in node.names:
                self.imports[alias.asname or alias.name] = (node.module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname and alias.name.startswith(prefix):
                    self.imports[alias.asname] = (alias.name, None)

    def _docstring_ids(self) -> Set[int]:
        """ids of every docstring constant: prose about a date is not the code spelling it."""
        found: Set[int] = set()
        for node in ast.walk(self.tree):
            body = getattr(node, "body", None)
            if not isinstance(node, (ast.Module, ast.ClassDef, *_FUNC_TYPES)) or not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
        return found

    def strings(self) -> Set[str]:
        """Every string constant this module spells, docstrings excepted."""
        if self._strings is None:
            docstrings = self._docstring_ids()
            self._strings = {
                node.value
                for node in ast.walk(self.tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
            }
        return self._strings

    def resolve(self, name: str, hops: int = 0) -> Tuple[Optional["_Module"], Optional[_FUNC_NODE]]:
        """What a bare name means here: (module, function), (module, None) for a module, or (None, None)."""
        if name in self.functions:
            return self, self.functions[name]
        if name not in self.imports or hops > 3:
            return None, None
        dotted, attr = self.imports[name]
        if attr is None:
            return _module_named(self.root, dotted), None
        submodule = _module_named(self.root, f"{dotted}.{attr}")
        if submodule is not None:
            return submodule, None
        owner = _module_named(self.root, dotted)
        if owner is None:
            return None, None
        return owner.resolve(attr, hops + 1)


_MODULE_CACHE: Dict[Tuple[str, int, int, str], _Module] = {}


def _module_at(path: Path, root: Path) -> Optional[_Module]:
    """The indexed module for a file, cached on its content stamp."""
    tree = _parse(path)
    if tree is None:
        return None
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size, str(root))
    if key not in _MODULE_CACHE:
        _MODULE_CACHE[key] = _Module(path, tree, root)
    return _MODULE_CACHE[key]


def _module_named(root: Path, dotted: str) -> Optional[_Module]:
    """The indexed module for a dotted name, or None when it is not under the root."""
    path = _module_file(root, dotted)
    return _module_at(path, root) if path else None


def _call_name(func: ast.expr) -> str:
    """The called name: ``f`` for ``f()``, ``m`` for ``x.y.m()``, '' otherwise."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _dotted(func: ast.expr) -> str:
    """``a.b.c`` for a Name/Attribute chain, '' for anything else."""
    parts: List[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if not isinstance(func, ast.Name):
        return ""
    parts.append(func.id)
    return ".".join(reversed(parts))


def _resolve_call(module: _Module, func: ast.expr, patched: Set[str]) -> Optional[Tuple[_Module, _FUNC_NODE]]:
    """One call's callee as (module, function), or None when unnamed, patched or not a function."""
    if isinstance(func, ast.Name):
        name, owner_name = func.id, ""
    elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        name, owner_name = func.attr, func.value.id
    else:
        return None
    if name in patched:
        return None
    if not owner_name:
        target_module, target = module.resolve(name)
    elif owner_name in ("self", "cls"):
        target_module, target = module, module.methods.get(name)
    else:
        owner, owner_func = module.resolve(owner_name)
        if owner is None or owner_func is not None:
            return None
        target_module, target = owner.resolve(name)
    if target_module is None or target is None:
        return None
    return target_module, target


# =============================================
# LEG 2 - PRODUCTION THAT COMPUTES WITH THE CLOCK
# =============================================


def _clock_call(node: ast.AST) -> bool:
    """datetime.now/utcnow/today, date.today, time.time/time_ns, a bare time.localtime/gmtime."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    base = node.func.value
    base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
    if node.func.attr in _DATETIME_CLOCKS:
        return base_name in _CONSTRUCTORS
    return base_name == "time" and node.func.attr in _TIME_CLOCKS and not node.args


def _is_clock_value(expr: ast.AST, names: Set[str], is_source: Callable[[ast.Call], bool]) -> bool:
    """True when the expression evaluates to the current instant (not a string made from it)."""
    if isinstance(expr, ast.Name):
        return expr.id in names
    if isinstance(expr, ast.BoolOp):
        return any(_is_clock_value(value, names, is_source) for value in expr.values)
    if isinstance(expr, ast.IfExp):
        return _is_clock_value(expr.body, names, is_source) or _is_clock_value(expr.orelse, names, is_source)
    if not isinstance(expr, ast.Call):
        return False
    if _clock_call(expr) or is_source(expr):
        return True
    func = expr.func
    return (
        isinstance(func, ast.Attribute) and func.attr in _CARRY_ATTRS and _is_clock_value(func.value, names, is_source)
    )


def _never(_call: ast.Call) -> bool:
    """A source predicate that knows no wrappers."""
    return False


def _clock_names(func: ast.AST, is_source: Callable[[ast.Call], bool]) -> Set[str]:
    """Local names bound to a clock value. Two passes, so ``b = a`` after ``a = now()`` binds too."""
    names: Set[str] = set()
    for _ in range(2):
        for node in ast.walk(func):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            if not _is_clock_value(node.value, names, is_source):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names


def _returns_clock(func: _FUNC_NODE) -> bool:
    """A one-level wrapper: the function hands back the current instant."""
    names = _clock_names(func, _never)
    return any(
        isinstance(node, ast.Return) and node.value is not None and _is_clock_value(node.value, names, _never)
        for node in ast.walk(func)
    )


def _source_predicate(module: _Module, patched: Set[str]) -> Callable[[ast.Call], bool]:
    """Is this call a clock wrapper this module can name (and the unit did not patch)?"""

    def is_source(call: ast.Call) -> bool:
        """True for a call to a resolvable, unpatched function that returns the current instant."""
        found = _resolve_call(module, call.func, patched)
        return found is not None and _returns_clock(found[1])

    return is_source


def _is_non_deriving(call: ast.Call) -> bool:
    """A call that reports or stores its argument."""
    name = _call_name(call.func)
    return name in _NON_DERIVING_CALLS or name.lstrip("_").startswith("log")


def _consumes(parent: Optional[ast.AST], current: ast.AST, parents: Dict[ast.AST, ast.AST]) -> bool:
    """True when the parent computes with the clock value rather than stamping it."""
    if isinstance(parent, ast.BinOp):
        return True
    if isinstance(parent, ast.Compare):
        return not all(isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops)
    if isinstance(parent, ast.keyword):
        call = parents.get(parent)
        return isinstance(call, ast.Call) and not _is_non_deriving(call)
    return isinstance(parent, ast.Call) and current is not parent.func and not _is_non_deriving(parent)


def _is_derivation(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> bool:
    """Climb through or/if-else and the carrying methods, then ask what consumes the value."""
    current = node
    while True:
        parent = parents.get(current)
        if isinstance(parent, (ast.BoolOp, ast.IfExp)):
            current = parent
            continue
        carried = parents.get(parent) if isinstance(parent, ast.Attribute) and parent.attr in _CARRY_ATTRS else None
        if isinstance(carried, ast.Call) and carried.func is parent:
            current = carried
            continue
        return _consumes(parent, current, parents)


def _derived_clock_line(func: ast.AST, is_source: Callable[[ast.Call], bool]) -> int:
    """Line of the first clock value this function computes with, or 0 when it only stamps or never reads."""
    names = _clock_names(func, is_source)
    parents = {child: node for node in ast.walk(func) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(func):
        is_value = (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in names) or (
            isinstance(node, ast.Call) and (_clock_call(node) or is_source(node))
        )
        if is_value and _is_derivation(node, parents):
            return getattr(node, "lineno", 0)
    return 0


def _relative_to_root(path: Path, root: Path) -> str:
    """Package-root-relative posix path, falling back to the file name."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        logger.info("[calendar_bound] %s not under %s: %s", path, root, exc)
        return path.name


def _call_targets(module: _Module, func: _FUNC_NODE, patched: Set[str]) -> List[Tuple[_Module, _FUNC_NODE]]:
    """Every function a scope calls that its module can name, minus the patched ones."""
    return [
        found
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        for found in [_resolve_call(module, node.func, patched)]
        if found is not None
    ]


def _clock_trail(test_module: _Module, unit: _FUNC_NODE, patched: Set[str]) -> List[Tuple[_Module, str]]:
    """Breadth-first from the unit to the nearest function that computes with the clock; [] when none."""
    queue = deque([(test_module, unit, 0, [])])
    seen: Set[Tuple[str, int]] = set()
    while queue:
        module, func, hops, trail = queue.popleft()
        key = (str(module.path), func.lineno)
        if key in seen:
            continue
        seen.add(key)
        line = _derived_clock_line(func, _source_predicate(module, patched))
        step = (module, f"{_relative_to_root(module.path, module.root)}:{line or func.lineno} {func.name}")
        if line:
            return trail + [step]
        if hops < MAX_HOPS:
            queue.extend((m, f, hops + 1, trail + [step]) for m, f in _call_targets(module, func, patched))
    return []


# =============================================
# LEG 1 AND LEG 3 - THE UNIT
# =============================================


def _is_constructor(node: ast.AST) -> bool:
    """``datetime(2026, 9, 6, ...)`` / ``date(...)`` with integer literals for year, month and day."""
    if not isinstance(node, ast.Call) or len(node.args) < 3 or _call_name(node.func) not in _CONSTRUCTORS:
        return False
    return all(isinstance(arg, ast.Constant) and type(arg.value) is int for arg in node.args[:3])


def _date_literal(node: ast.AST) -> str:
    """The literal's text when the node spells a calendar instant, else ''."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and _ISO_DATE.match(node.value):
        return node.value
    return ast.unparse(node) if _is_constructor(node) else ""


def _compared_operands(node: ast.AST) -> List[ast.expr]:
    """The operands an assert comparison or a unittest assert method compares."""
    if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
        return [node.test.left, *node.test.comparators]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _ASSERT_METHODS:
        return list(node.args[:2])
    return []


def _asserted_literals(unit: _FUNC_NODE) -> List[Tuple[int, str]]:
    """(line, text) for every date literal the unit asserts against."""
    return [
        (operand.lineno, text)
        for node in ast.walk(unit)
        for operand in _compared_operands(node)
        for text in [_date_literal(operand)]
        if text
    ]


def _test_units(tree: ast.Module) -> List[Tuple[_FUNC_NODE, Optional[ast.ClassDef]]]:
    """Each test function with the class that holds it, if any."""
    units: List[Tuple[_FUNC_NODE, Optional[ast.ClassDef]]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            units.extend((member, node) for member in node.body if isinstance(member, _FUNC_TYPES))
        elif isinstance(node, _FUNC_TYPES):
            units.append((node, None))
    return [(unit, cls) for unit, cls in units if unit.name.startswith("test")]


def _ownership_scopes(test_module: _Module, unit: _FUNC_NODE, cls: Optional[ast.ClassDef]) -> List[_FUNC_NODE]:
    """The unit, its class's helper methods, and the same-file functions it calls by name."""
    scopes: List[_FUNC_NODE] = [unit]
    if cls is not None:
        scopes.extend(m for m in cls.body if isinstance(m, _FUNC_TYPES) and not m.name.startswith("test"))
    called = {node.func.id for node in ast.walk(unit) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    scopes.extend(test_module.functions[name] for name in sorted(called) if name in test_module.functions)
    return scopes


def _is_patcher(call: ast.Call) -> bool:
    """patch / patch.object / patch.dict / monkeypatch.setattr, however imported."""
    return _dotted(call.func).endswith(_PATCHERS)


def _patched_names(scopes: Iterable[ast.AST]) -> Set[str]:
    """The last dotted segment of every string a patcher names - the seams the walk must not cross."""
    names: Set[str] = set()
    for scope in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call) or not _is_patcher(node):
                continue
            names.update(
                child.value.rsplit(".", 1)[-1]
                for arg in node.args[:2]
                for child in ast.walk(arg)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            )
    return names


def _is_clock_patch(call: ast.Call) -> bool:
    """A patcher whose target names the clock - and not only a wait or a stopwatch."""
    if not _is_patcher(call):
        return False
    named = [
        child.value.rsplit(".", 1)[-1]
        for arg in call.args[:2]
        for child in ast.walk(arg)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]
    if named and all(name in _NOT_CLOCK_SEAMS for name in named):
        return False
    return bool(_CLOCK_WORD.search(" ".join(ast.unparse(a) for a in call.args[:2])))


def _scope_owns_clock(scope: ast.AST) -> str:
    """Why this scope controls the instant its code sees, or ''."""
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        if _is_clock_patch(node):
            return "patches the clock"
        if any(keyword.arg in _CLOCK_KWARGS for keyword in node.keywords):
            return "injects the instant"
        if _call_name(node.func) in _ASSERT_METHODS or _is_constructor(node):
            continue
        if any(_is_constructor(arg) for arg in node.args):
            return "injects the instant"
    return ""


def _autouse_freezes(tree: ast.Module) -> bool:
    """An autouse fixture in this module that patches the clock."""
    return any(
        isinstance(node, _FUNC_TYPES)
        and any("autouse" in ast.unparse(decorator) for decorator in node.decorator_list)
        and bool(_scope_owns_clock(node))
        for node in ast.walk(tree)
    )


def _owns_clock(
    unit: _FUNC_NODE, cls: Optional[ast.ClassDef], scopes: List[_FUNC_NODE], trees: List[ast.Module]
) -> str:
    """Why this unit is not at the wall clock's mercy, or '' when nothing says it is."""
    if any(_CLOCK_FIXTURE.search(arg.arg) for arg in unit.args.args):
        return "takes a clock fixture"
    decorators = list(unit.decorator_list) + (list(cls.decorator_list) if cls else [])
    if any(_FREEZE_DECORATOR.search(ast.unparse(decorator)) for decorator in decorators):
        return "is frozen by a decorator"
    for scope in scopes:
        reason = _scope_owns_clock(scope)
        if reason:
            return reason
    return "has an autouse clock fixture" if any(_autouse_freezes(tree) for tree in trees) else ""


def _conftest_trees(path: Path, root: Path) -> List[ast.Module]:
    """conftest.py modules from the file's directory up to the package root."""
    trees: List[ast.Module] = []
    for directory in path.parents:
        if directory == root or root not in directory.parents:
            break
        tree = _parse(directory / "conftest.py") if (directory / "conftest.py").is_file() else None
        if tree is not None:
            trees.append(tree)
    return trees


def _judge_unit(
    test_module: _Module, unit: _FUNC_NODE, cls: Optional[ast.ClassDef], conftests: List[ast.Module]
) -> Tuple[str, str, int]:
    """(verdict, detail, line): verdict is 'convict', 'owned', 'spelled' or 'clear'."""
    literals = _asserted_literals(unit)
    if not literals:
        return "clear", "", 0
    scopes = _ownership_scopes(test_module, unit, cls)
    trail = _clock_trail(test_module, unit, _patched_names(scopes))
    if not trail:
        return "clear", "", 0
    if _owns_clock(unit, cls, scopes, [test_module.tree, *conftests]):
        return "owned", "", 0
    production = [module for module, _ in trail if _is_production(module)]
    unspelled = [(line, text) for line, text in literals if not _spelled_by(production, text)]
    if not unspelled:
        return "spelled", "", 0
    line, text = unspelled[0]
    detail = (
        f"{unit.name} asserts {text} against code that computes with the clock, nearest at {trail[-1][1]} "
        f"({len(trail) - 1} call(s) in) and does not own the clock - true only while the calendar agrees; "
        "freeze the clock that code reads (monkeypatch its datetime), inject now=, "
        "or build the expected value from the frozen instant"
    )
    return "convict", detail, line


def _is_production(module: _Module) -> bool:
    """Not test code: no ``tests`` directory between the package root and the file."""
    try:
        parts = module.path.relative_to(module.root).parts
    except ValueError as exc:
        logger.info("[calendar_bound] %s not under %s: %s", module.path, module.root, exc)
        return False
    return "tests" not in parts


def _spelled_by(modules: List[_Module], text: str) -> bool:
    """True when one of these modules writes the date into a string constant of its own."""
    return any(text in string for module in modules for string in module.strings())


def scan_file(file_path: str, package_root: str) -> Tuple[List[Tuple[int, str]], Dict[str, int]]:
    """Judge every test unit in one file. Returns (violations, {'owned': n, 'spelled': n}).

    A file that cannot be read or parsed reports NOTHING rather than a
    violation: an unparseable test is ruff's business, not the calendar's.
    """
    path = Path(file_path)
    root = Path(package_root)
    context = {"owned": 0, "spelled": 0}
    test_module = _module_at(path, root)
    if test_module is None:
        return [], context
    conftests = _conftest_trees(path, root)
    violations: List[Tuple[int, str]] = []
    for unit, cls in _test_units(test_module.tree):
        verdict, detail, line = _judge_unit(test_module, unit, cls, conftests)
        if verdict == "convict":
            violations.append((line, detail))
        elif verdict in context:
            context[verdict] += 1
    violations.sort(key=lambda row: row[0])
    return violations, context


# =============================================
# CORPUS
# =============================================


def _test_roots(branch_root: Path) -> List[Path]:
    """The branch's tests/ and every lib/<skill>/tests/."""
    roots = [branch_root / "tests"]
    lib = branch_root / "lib"
    if lib.is_dir():
        roots.extend(sorted(lib.glob("*/tests")))
    return [root for root in roots if root.is_dir()]


def _in_corpus(path: Path, branch_root: Path, ignore_entries: list) -> bool:
    """Skip caches, disabled and retired files, and anything .seedgoignore names."""
    if any(part in SOURCE_SKIP_DIRS for part in path.parts):
        return False
    if is_disabled_file(path.name) or is_retired_path(str(path)):
        return False
    return not is_seedgo_ignored(str(path), branch_root, ignore_entries)


def _corpus_files(branch_root: Path, ignore_entries: list) -> List[Path]:
    """Every auditable test-tree .py file."""
    return [
        path
        for root in _test_roots(branch_root)
        for path in sorted(root.rglob("*.py"))
        if _in_corpus(path, branch_root, ignore_entries)
    ]


def _relative(path: Path, branch_root: Path) -> str:
    """Branch-relative posix path, falling back to the absolute one."""
    try:
        return path.relative_to(branch_root).as_posix()
    except ValueError as exc:
        logger.info("[calendar_bound] %s not relative to %s: %s", path, branch_root, exc)
        return path.as_posix()


# =============================================
# BRANCH-LEVEL CHECK (audit pipeline entry)
# =============================================


def _result(score: int, checks: List[Dict], branch_path: str) -> Dict:
    """The pack's result shape, logged once."""
    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": _BYPASS_KEY},
    )
    return {
        "passed": score >= PASS_THRESHOLD,
        "checks": checks,
        "score": score,
        "standard": STANDARD_NAME,
    }


def _context_check(owned: int, spelled: int) -> Dict:
    """The acquittals, counted so a reader can see the rule looked - never scored."""
    return {
        "name": "Clock already owned",
        "passed": True,
        "message": (
            f"{owned} unit(s) assert a date against clock-derived code and already own the clock; "
            f"{spelled} assert a date the production code spells itself - context, not scored"
        ),
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a branch's tests for assertions that are only true on some dates.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo)
        bypass_rules: Optional list of bypass rules to skip certain violations

    Returns:
        dict: {
            'passed': bool,
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': 'CALENDAR_BOUND'
        }
    """
    branch_root = Path(branch_path)

    if is_bypassed(branch_path, _BYPASS_KEY, bypass_rules=bypass_rules):
        return _result(
            100,
            [{"name": "Bypassed", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            branch_path,
        )

    files = _corpus_files(branch_root, load_ignore_entries(branch_root))
    if not files:
        return _result(
            100,
            [{"name": "Calendar bound", "passed": True, "message": "No tests/ Python files to check"}],
            branch_path,
        )

    package_root = str(branch_root.resolve().parent)
    rows: List[Tuple[str, int, str]] = []
    owned = spelled = 0
    for path in files:
        rel = _relative(path, branch_root)
        violations, context = scan_file(str(path), package_root)
        owned += context["owned"]
        spelled += context["spelled"]
        rows.extend(
            (rel, lineno, detail)
            for lineno, detail in violations
            if not is_bypassed(rel, _BYPASS_KEY, lineno, bypass_rules)
        )

    dirty_files = {rel for rel, _, _ in rows}
    score = int((len(files) - len(dirty_files)) / len(files) * 100)
    if rows:
        preview = "; ".join(f"{rel}:{lineno} {detail.split(' against ')[0]}" for rel, lineno, detail in rows[:3])
        suffix = f" (and {len(rows) - 3} more)" if len(rows) > 3 else ""
        checks: List[Dict] = [
            {
                "name": "Calendar bound",
                "passed": False,
                "message": (
                    f"{len(rows)} calendar-bound assertion(s) in {len(dirty_files)}/{len(files)} "
                    f"test files: {preview}{suffix}"
                ),
                "violations": [{"file": rel, "line": lineno, "name": detail} for rel, lineno, detail in rows],
            }
        ]
    else:
        checks = [
            {
                "name": "Calendar bound",
                "passed": True,
                "message": f"No date literal asserted against an unfrozen clock in {len(files)} test files",
            }
        ]
    if owned or spelled:
        checks.append(_context_check(owned, spelled))

    return _result(score, checks, branch_path)
