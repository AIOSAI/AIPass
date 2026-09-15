# =================== AIPass ====================
# Name: module_eviction_check.py
# Description: v5 - a test that evicts a cached module and does not put it back
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""Does this test leave the import cache the way it found it?

    def _import_rollover(monkeypatch):
        mocks = _prepare_rollover_mocks(monkeypatch)       # the cli is a MagicMock now
        sys.modules.pop("aipass.memory.apps.modules.rollover", None)
        delattr(parent, "rollover")
        from aipass.memory.apps.modules import rollover    # re-executed against the mock
        return rollover, mocks

Teardown put the cli back. Nothing put the MODULE back. The re-import minted a
rollover bound to a mock `error()`, and it stayed cached in `sys.modules` and on
its parent package after the test that made it had finished. The next in-process
`memory.main()` on the same xdist worker found that module, routed
`rollover <bogus>` through the mock error, and exited 0 where the contract says 2.
Which worker inherited it was loadscope's ordering, so CI on PR #769 went red on
some platforms and Pythons and not others: a flicker, and the flicker was a leak.

THE SAME RULING AS `host_state`, ONE LAYER IN. Touching the real thing is allowed;
leaving it changed is the defect. A test may evict a module to force a fresh
import - that is often the only way to execute import-time code under a mock. It
may not walk away leaving the cache holding a different object from the one it
found. This rule is about the restore, never about the eviction.

WHY A RULE AND NOT A `host_state` SPECIES. `host_state` judges test units and
fixtures. The incident's site was neither: it was a module-level HELPER that
units call, and that is where this shape lives across the fleet (prax keeps
dozens of bare pops inside `_fresh_import()`-style helpers). Teaching host_state
to read helpers would change what every one of its six species reads, and its
denominator with it. A separate rule reads every function and scores against
every function, and host_state stays exactly what it was measured to be.

WHAT IS READ: every function defined in a test file - test functions, fixtures,
and module-level, class-level or nested helpers - each one on its own scope. No
call is followed and no other file is opened, so the site is judged by what is
written in the function that evicts.

WHAT COUNTS AS AN EVICTION:

  - `sys.modules.pop(K, ...)` and `del sys.modules[K]`.
  - `delattr(M, "attr")` where M is PROVABLY a module: a name bound in the same
    function from `importlib.import_module(...)`, `__import__(...)`,
    `sys.modules[...]` or `sys.modules.get(...)`, a name bound by an `import`
    statement at module level or in the function, or one of those expressions
    written in place. The `.get` spelling is here because it is how memory's
    half-cured helpers bind the parent package: they moved the `sys.modules`
    half onto monkeypatch and kept a bare `delattr(parent, ...)` on a `parent`
    read with `.get`, which is the other half of the same leak.

  `monkeypatch.delitem(sys.modules, ...)` and `monkeypatch.delattr(...)` are
  never evictions here. They are the cure.

WHAT ACQUITS A SITE:

  - MONKEYPATCH RECORDED IT FIRST. `setitem`/`delitem` on `sys.modules` with the
    same key expression, or `setattr`/`delattr` with the same object and
    attribute, earlier in the same function. Recorded first, pytest puts back
    whatever stood there - the real module, or nothing. Recorded AFTER the
    eviction, it records the eviction and restores that, which is no restore.
  - `patch.dict(sys.modules ...)` as a `with` around the eviction, or as a
    decorator on the function. It snapshots the whole dict and restores it on
    exit. It acquits `sys.modules` evictions only: it never touches a package
    attribute, so a `delattr` inside it is still read.
  - AN EXPLICIT RESTORE after the eviction, or in any `finally` of the same
    function: `sys.modules[K] = ...` or `sys.modules.update(...)` for the cache,
    `setattr(M, "attr", ...)` or `M.attr = ...` for the attribute. A re-import
    is NOT a restore - `importlib.import_module(K)` after the eviction is the
    pollution, not the cure.
  - A FIXTURE WITH ANY STATEMENT AFTER ITS LAST YIELD. The teardown is where a
    fixture puts things back, and it runs for a failing test too. That is
    `host_state`'s convention, adopted after demanding a try/finally convicted
    thirty correct fixtures.
  - AN AUTOUSE FIXTURE IN THE SAME FILE RECORDED THE KEY. `setitem`/`delitem` on
    `sys.modules` inside an `autouse=True` fixture runs around every test in the
    file, so the key it records is put back after each of them, whatever a
    helper did to it in between. Both sides have to resolve to the same literal
    name - a string, a module-level string constant, or a `for` over a literal
    collection written in place or held in a module-level constant - one hop,
    same file. Cache evictions only: the fixture never recorded
    a package attribute. ADDED BECAUSE THE FLEET RUN DEMANDED IT: memory's
    test_symbolic_extras records five symbolic modules in `_mock_handler_deps`
    and pops the same five bare in five `_import_*` helpers, and a runtime probe
    found every one of those module objects unchanged after teardown.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM, all of it in the direction of FEWER
flags:

  - it does not follow calls. A restore performed by a helper the function calls,
    a fixture it requests, or a conftest two directories up is invisible - and so
    is an eviction performed by one. `conftest.py` is not a test file and is not
    read at all, so an autouse conftest fixture that records the same key - the
    one measured false positive left, prax's `modules.logger` - is invisible.
  - an autouse record whose key is assembled at runtime resolves to nothing, and
    nothing acquits nothing.
  - `delattr` on a name that is not provably a module is not read. A
    `from x import y` name may be a function; so may a parameter.
  - a name bound to a module AND rebound to anything else in the same function
    is not provably a module, and is not read.
  - code in a string is not code. A harness script handed to a child interpreter
    evicts modules in a process that dies with it, and is never read.
  - statements at module level, outside any function, are not read.
  - `sys.modules.clear()`, `popitem()`, `del M.attr` and a manually started
    `patch.dict(...).start()` are not read as evictions or restores.
  - `sys.modules.update(...)` acquits every cache eviction in its function
    without comparing keys. Generous on purpose.
  - A flagged site may be harmless - a module with no state, re-imported to an
    identical copy. The identity still changed. It nominates. A human decides.

STDLIB ONLY - `ast`, `dataclasses`, `pathlib`, `typing`, and the pack's own corpus
reader, like the rest of the pack. `_is_fixture` is a second copy of the reader in
`host_state_check` and `fresh_clone_check`: no rule in this pack imports another,
so a rule lifts out alone, and the copy is on the record rather than hidden.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "module_eviction"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: The import cache, by its dotted spelling.
SYS_MODULES: str = "sys.modules"

#: The two species. A cache entry and a package attribute are two homes of one
#: module, and a finding says which one was left changed.
SPECIES_CACHE: str = "SYS_MODULES_EVICTION"
SPECIES_ATTRIBUTE: str = "PACKAGE_ATTRIBUTE_EVICTION"

#: Calls whose result can only be a module (or None), so a name bound from one
#: is provably a module.
MODULE_BINDERS: frozenset = frozenset({"importlib.import_module", "__import__", "sys.modules.get"})

#: The monkeypatch methods that record a dict key or an attribute before they
#: change it. Read on any receiver: `monkeypatch`, `mp` and `self.monkeypatch`
#: are the same MonkeyPatch.
RECORDING_ITEM_METHODS: frozenset = frozenset({"setitem", "delitem"})
RECORDING_ATTR_METHODS: frozenset = frozenset({"setattr", "delattr"})

#: `patch.dict`, and the qualified spellings that end in it.
PATCH_DICT: str = "patch.dict"

#: Scopes read on their own. A nested def is a function of its own, and a
#: lambda's body may never run, so neither is read as part of its parent.
SEPARATE_SCOPES: tuple = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

#: The longest target spelling a finding quotes before it truncates.
MAX_TARGET_TEXT: int = 60

#: How many flagged functions to name in the result. The full list lives in the
#: report artifact; a check message printing hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# DATA
# =============================================================================


@dataclass
class Eviction:
    """One eviction site, with what a restore has to name to undo it."""

    species: str
    node: ast.AST
    line: int
    column: int
    #: The `sys.modules` key expression, or the object `delattr` was handed.
    target: ast.expr
    #: The attribute expression for a `delattr`; None for a cache eviction.
    attr: Optional[ast.expr] = None
    spelling: str = ""


@dataclass
class FileFacts:
    """What one test file declares at module level, read once per file."""

    #: Names a top-level `import` binds - modules, file-wide.
    imports: Set[str] = field(default_factory=set)
    #: Module-level names bound to a string literal.
    strings: Dict[str, str] = field(default_factory=dict)
    #: Module-level names bound to a literal list, tuple or set of strings.
    collections: Dict[str, List[str]] = field(default_factory=dict)
    #: Literal sys.modules keys an autouse fixture in this file records.
    autouse_keys: Set[str] = field(default_factory=set)


# =============================================================================
# READING A FUNCTION'S OWN SCOPE
# =============================================================================


def functions_in(tree: ast.Module) -> List[Tuple[str, Union[ast.FunctionDef, ast.AsyncFunctionDef]]]:
    """Every def in a parsed file with its `::`-joined qualified name, nested ones too.

    Classes contribute their name to the path and are not subjects themselves.
    A def inside an `if`, `try` or `with` is still a def, so every statement
    child is walked, not only bodies of classes and functions.
    """
    found: List[Tuple[str, Union[ast.FunctionDef, ast.AsyncFunctionDef]]] = []
    stack: List[Tuple[ast.AST, Tuple[str, ...]]] = [(node, ()) for node in reversed(tree.body)]
    while stack:
        node, prefix = stack.pop()
        path = prefix
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            path = prefix + (node.name,)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(("::".join(path), node))
        children = [c for c in ast.iter_child_nodes(node) if isinstance(c, (ast.stmt, ast.excepthandler))]
        stack.extend((child, path) for child in reversed(children))
    return sorted(found, key=lambda pair: (pair[1].lineno, pair[1].col_offset))


def own_nodes(function: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> List[ast.AST]:
    """Every node in a function's own body, nested defs, classes and lambdas excluded.

    ONE SCOPE, ONE OWNER. `ast.walk` over the function would hand a nested
    helper's eviction to its parent as well, reporting one site twice and
    letting the parent's restore acquit the child's eviction. Decorators are
    not the body either; the one decorator this rule reads is read by name.
    """
    found: List[ast.AST] = []
    stack: List[ast.AST] = [s for s in reversed(function.body) if not isinstance(s, SEPARATE_SCOPES)]
    while stack:
        node = stack.pop()
        found.append(node)
        stack.extend(c for c in reversed(list(ast.iter_child_nodes(node))) if not isinstance(c, SEPARATE_SCOPES))
    return found


def _same(left: Optional[ast.AST], right: Optional[ast.AST]) -> bool:
    """True when two expressions are spelled identically, positions ignored."""
    if left is None or right is None:
        return False
    return ast.dump(left) == ast.dump(right)


def _text(node: ast.AST) -> str:
    """An expression as source, cut short enough to sit inside a sentence."""
    spelled = ast.unparse(node)
    return spelled if len(spelled) <= MAX_TARGET_TEXT else spelled[: MAX_TARGET_TEXT - 3] + "..."


# =============================================================================
# WHAT IS PROVABLY A MODULE
# =============================================================================


def is_module_expression(node: Optional[ast.AST]) -> bool:
    """True for an expression whose value can only be a module (or None).

    `importlib.import_module(...)`, `__import__(...)`, `sys.modules.get(...)`
    and `sys.modules[...]`. Anything else - a `from x import y` name, a
    parameter, an attribute of something - may be a function, and `delattr` on
    a function is not an eviction.
    """
    if isinstance(node, ast.Call):
        return corpus.dotted_name(node.func) in MODULE_BINDERS
    if isinstance(node, ast.Subscript):
        return corpus.dotted_name(node.value) == SYS_MODULES
    return False


def _import_names(nodes: List[ast.AST]) -> Set[str]:
    """Names an `import a.b` / `import a.b as c` statement binds, which are modules."""
    names: Set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
    return names


def _argument_names(function: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> Set[str]:
    """Every parameter name of a function - none of them is provably anything."""
    arguments = function.args
    names = {a.arg for a in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}
    names.update(a.arg for a in (arguments.vararg, arguments.kwarg) if a is not None)
    return names


def provable_modules(
    function: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    nodes: List[ast.AST],
    module_imports: Set[str],
) -> Set[str]:
    """Names in this function that can only hold a module.

    A name is proven by an `import`, or by an assignment from a module
    expression. It is DISPROVEN by any other binding in the same function - a
    parameter, a `for` target, a second assignment from something else - because
    the reader cannot tell which binding is live at the `delattr`, and the
    doubt goes to the no-flag side.
    """
    proving_targets: Set[int] = set()
    proven = _import_names(nodes)
    for node in nodes:
        if isinstance(node, ast.Assign) and is_module_expression(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    proven.add(target.id)
                    proving_targets.add(id(target))
    disproven = _argument_names(function)
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and id(node) not in proving_targets:
            disproven.add(node.id)
    return (module_imports | proven) - disproven


# =============================================================================
# EVICTIONS
# =============================================================================


def evictions_in(nodes: List[ast.AST], modules: Set[str]) -> List[Eviction]:
    """Every eviction site in one scope, in source order."""
    found: List[Eviction] = []
    for node in nodes:
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and corpus.dotted_name(target.value) == SYS_MODULES:
                    found.append(
                        Eviction(
                            SPECIES_CACHE, node, node.lineno, node.col_offset, target.slice, None, "del sys.modules"
                        )
                    )
        if not isinstance(node, ast.Call):
            continue
        dotted = corpus.dotted_name(node.func)
        if dotted == "sys.modules.pop" and node.args:
            found.append(
                Eviction(SPECIES_CACHE, node, node.lineno, node.col_offset, node.args[0], None, "sys.modules.pop")
            )
        elif dotted == "delattr" and len(node.args) >= 2 and _is_module(node.args[0], modules):
            found.append(
                Eviction(SPECIES_ATTRIBUTE, node, node.lineno, node.col_offset, node.args[0], node.args[1], "delattr")
            )
    return sorted(found, key=lambda e: (e.line, e.column))


def _is_module(node: ast.expr, modules: Set[str]) -> bool:
    """True when `delattr`'s first argument is provably a module."""
    if isinstance(node, ast.Name):
        return node.id in modules
    return is_module_expression(node)


# =============================================================================
# ACQUITTALS
# =============================================================================


def _recorded_first(eviction: Eviction, nodes: List[ast.AST]) -> bool:
    """True when monkeypatch recorded the same target before the eviction ran.

    EARLIER, NOT MERELY PRESENT. monkeypatch restores the value it saw when it
    was called. Called before the eviction, that is the real module; called
    after it, that is the eviction, and teardown faithfully restores the hole.
    """
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or len(node.args) < 2:
            continue
        if (node.lineno, node.col_offset) >= (eviction.line, eviction.column):
            continue
        method = node.func.attr
        first, second = node.args[0], node.args[1]
        if eviction.species == SPECIES_CACHE and method in RECORDING_ITEM_METHODS:
            if corpus.dotted_name(first) == SYS_MODULES and _same(second, eviction.target):
                return True
        if eviction.species == SPECIES_ATTRIBUTE and method in RECORDING_ATTR_METHODS:
            if _same(first, eviction.target) and _same(second, eviction.attr):
                return True
    return False


def _is_patch_dict_of_sys_modules(node: ast.AST) -> bool:
    """True for `patch.dict(sys.modules, ...)` or `patch.dict("sys.modules", ...)`, any qualifier."""
    if not isinstance(node, ast.Call) or not node.args:
        return False
    dotted = corpus.dotted_name(node.func)
    if dotted != PATCH_DICT and not dotted.endswith("." + PATCH_DICT):
        return False
    first = node.args[0]
    return corpus.dotted_name(first) == SYS_MODULES or (isinstance(first, ast.Constant) and first.value == SYS_MODULES)


def _patch_dict_guarded(function: Union[ast.FunctionDef, ast.AsyncFunctionDef], nodes: List[ast.AST]) -> Set[int]:
    """Ids of every node a `patch.dict(sys.modules)` will put back on exit.

    A decorator guards the whole function; a `with` guards its own body.
    """
    if any(_is_patch_dict_of_sys_modules(decorator) for decorator in function.decorator_list):
        return {id(node) for node in nodes}
    guarded: Set[int] = set()
    for node in nodes:
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        if any(_is_patch_dict_of_sys_modules(item.context_expr) for item in node.items):
            guarded.update(id(child) for statement in node.body for child in ast.walk(statement))
    return guarded


def _in_a_finally(nodes: List[ast.AST]) -> Set[int]:
    """Ids of every node inside any `finally` of this scope."""
    inside: Set[int] = set()
    for node in nodes:
        if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            inside.update(id(child) for statement in getattr(node, "finalbody", []) for child in ast.walk(statement))
    return inside


def _restores_cache(node: ast.AST, eviction: Eviction) -> bool:
    """True for `sys.modules[K] = ...` naming the evicted key, or `sys.modules.update(...)`."""
    if isinstance(node, ast.Assign):
        return any(
            isinstance(t, ast.Subscript)
            and corpus.dotted_name(t.value) == SYS_MODULES
            and _same(t.slice, eviction.target)
            for t in node.targets
        )
    return isinstance(node, ast.Call) and corpus.dotted_name(node.func) == "sys.modules.update"


def _restores_attribute(node: ast.AST, eviction: Eviction) -> bool:
    """True for `setattr(M, "attr", ...)` or `M.attr = ...` naming the evicted attribute."""
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) == "setattr" and len(node.args) >= 2:
        return _same(node.args[0], eviction.target) and _same(node.args[1], eviction.attr)
    if not isinstance(node, ast.Assign) or not isinstance(eviction.attr, ast.Constant):
        return False
    return any(
        isinstance(t, ast.Attribute) and t.attr == eviction.attr.value and _same(t.value, eviction.target)
        for t in node.targets
    )


def _restored_explicitly(eviction: Eviction, nodes: List[ast.AST], finally_ids: Set[int]) -> bool:
    """True when the same scope puts the evicted target back, after it or in a finally.

    A RE-IMPORT IS NOT A RESTORE. `importlib.import_module(K)` after the
    eviction mints a new module object and caches THAT - which is the pollution
    this rule exists to find, so it acquits nothing.
    """
    restores = _restores_cache if eviction.species == SPECIES_CACHE else _restores_attribute
    for node in nodes:
        if getattr(node, "lineno", -1) <= eviction.line and id(node) not in finally_ids:
            continue
        if restores(node, eviction):
            return True
    return False


def _is_fixture(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True when a function carries a pytest fixture decorator."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if corpus.dotted_name(target).rsplit(".", 1)[-1] == "fixture":
            return True
    return False


def teardown_after_yield(function: Union[ast.FunctionDef, ast.AsyncFunctionDef], nodes: List[ast.AST]) -> bool:
    """True when a fixture runs any statement after handing its value over.

    ANY STATEMENT, NOT A TRY/FINALLY. pytest runs a yield fixture's teardown when
    the test fails as well as when it passes; demanding a `finally` convicted
    thirty correct fixtures on host_state's first fleet run.
    """
    if not _is_fixture(function):
        return False
    yields = [getattr(n, "lineno", -1) for n in nodes if isinstance(n, (ast.Yield, ast.YieldFrom))]
    if not yields:
        return False
    last_yield = max(yields)
    return any(isinstance(n, ast.stmt) and n.lineno > last_yield for n in nodes)


# =============================================================================
# WHAT THE FILE RECORDS AROUND EVERY TEST - AUTOUSE FIXTURES
# =============================================================================


def _literal_strings(node: ast.AST) -> List[str]:
    """The strings of a literal list, tuple or set made only of strings, else []."""
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)) or not node.elts:
        return []
    strings = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return strings if len(strings) == len(node.elts) else []


def _module_constants(tree: ast.Module) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Module-level names bound to a string, and to a literal collection of strings."""
    strings: Dict[str, str] = {}
    collections: Dict[str, List[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            strings.update((name, node.value.value) for name in names)
        elif _literal_strings(node.value):
            collections.update((name, _literal_strings(node.value)) for name in names)
    return strings, collections


def key_strings(key: ast.expr, nodes: List[ast.AST], facts: FileFacts) -> Set[str]:
    """The literal module names a key expression stands for, one hop, or an empty set.

    A string literal is itself. A name is a module-level string constant, or the
    target of a `for` in the same scope over a literal collection - written in
    place or held in a module-level constant. Anything else resolves to nothing.
    """
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return {key.value}
    if not isinstance(key, ast.Name):
        return set()
    if key.id in facts.strings:
        return {facts.strings[key.id]}
    for node in nodes:
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name) or node.target.id != key.id:
            continue
        if isinstance(node.iter, ast.Name):
            return set(facts.collections.get(node.iter.id, []))
        return set(_literal_strings(node.iter))
    return set()


def _is_autouse_fixture(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True for a fixture decorator called with `autouse=True`, in any spelling."""
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or corpus.dotted_name(decorator.func).rsplit(".", 1)[-1] != "fixture":
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "autouse" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                return True
    return False


def _cache_keys_recorded(function: Union[ast.FunctionDef, ast.AsyncFunctionDef], facts: FileFacts) -> Set[str]:
    """Literal sys.modules keys one function records through monkeypatch setitem/delitem."""
    nodes = own_nodes(function)
    keys: Set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or len(node.args) < 2:
            continue
        if node.func.attr in RECORDING_ITEM_METHODS and corpus.dotted_name(node.args[0]) == SYS_MODULES:
            keys |= key_strings(node.args[1], nodes, facts)
    return keys


def file_facts(tree: ast.Module) -> FileFacts:
    """A test file's module-level imports, constants and autouse records, read once."""
    strings, collections = _module_constants(tree)
    facts = FileFacts(imports=_import_names(list(tree.body)), strings=strings, collections=collections)
    for _, function in functions_in(tree):
        if _is_autouse_fixture(function):
            facts.autouse_keys |= _cache_keys_recorded(function, facts)
    return facts


def _recorded_by_autouse(eviction: Eviction, nodes: List[ast.AST], facts: FileFacts) -> bool:
    """True when every name a cache eviction's key stands for is recorded by a same-file autouse fixture.

    An autouse fixture runs around every test in its file, so its monkeypatch
    record is restored after each of them, whatever a helper did to that key in
    between. A key that resolves to nothing acquits nothing.
    """
    names = key_strings(eviction.target, nodes, facts)
    return bool(names) and names <= facts.autouse_keys


# =============================================================================
# ANALYSIS
# =============================================================================


def _describe(eviction: Eviction) -> str:
    """One site, as the clause a finding quotes."""
    if eviction.species == SPECIES_ATTRIBUTE and eviction.attr is not None:
        return f"line {eviction.line} delattr({_text(eviction.target)}, {_text(eviction.attr)})"
    if eviction.spelling == "del sys.modules":
        return f"line {eviction.line} del sys.modules[{_text(eviction.target)}]"
    return f"line {eviction.line} sys.modules.pop({_text(eviction.target)})"


def unrestored_in(
    function: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    facts: Optional[FileFacts] = None,
) -> List[Eviction]:
    """Every eviction in one function that nothing in it, or in its file's autouse fixtures, undoes.

    `facts` defaults to none deliberately: a function handed over without its
    file has no module-level import and no autouse fixture to lean on, which is
    the pre-acquittal reading rather than a silently generous one.
    """
    known = facts or FileFacts()
    nodes = own_nodes(function)
    candidates = evictions_in(nodes, provable_modules(function, nodes, known.imports))
    if not candidates or teardown_after_yield(function, nodes):
        return []
    guarded = _patch_dict_guarded(function, nodes)
    finally_ids = _in_a_finally(nodes)
    left: List[Eviction] = []
    for eviction in candidates:
        if _recorded_first(eviction, nodes):
            continue
        cache = eviction.species == SPECIES_CACHE
        if cache and (id(eviction.node) in guarded or _recorded_by_autouse(eviction, nodes, known)):
            continue
        if _restored_explicitly(eviction, nodes, finally_ids):
            continue
        left.append(eviction)
    return left


def function_count(scanned: corpus.Corpus) -> int:
    """How many functions the rule reads. The denominator.

    EVERY SUBJECT THE RULE JUDGES IS IN IT. Rows come from helpers as well as
    units, so scoring them against units alone would let one file of helpers
    drive a project below zero.
    """
    return sum(len(functions_in(parsed.tree)) for parsed in scanned.files)


def find_unrestored(scanned: corpus.Corpus) -> List[Dict]:
    """One row per function that leaves an evicted module unrestored.

    ONE ROW PER FUNCTION, EVERY LINE NAMED. A helper that pops five modules is
    one function a reader has to go and fix, not five; the row's detail lists
    each line so nothing is hidden by the dedupe.
    """
    rows: List[Dict] = []
    for parsed in scanned.files:
        facts = file_facts(parsed.tree)
        for qualname, function in functions_in(parsed.tree):
            left = unrestored_in(function, facts)
            if not left:
                continue
            rows.append(
                {
                    "nodeid": f"{parsed.relpath}::{qualname}",
                    "line": left[0].line,
                    "species": left[0].species,
                    "detail": (
                        "; ".join(_describe(e) for e in left)
                        + " - evicted with nothing recording it first and nothing putting it back, so the "
                        "import cache keeps whatever the next import mints, in every later test on this "
                        "worker. monkeypatch.delitem(sys.modules, ...) and monkeypatch.delattr are restored for you"
                    ),
                }
            )
    return rows


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests put evicted modules back.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to be
            excused from. Wiring a bypass before the standard can fail would be
            granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory, violations. A project with no tests reports not_applicable
        rather than a number, because zero tests measured is not zero quality
        found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. A project whose only test file has a syntax error must never report
    # what a project with no tests at all reports.
    unreadable: List[Dict] = []
    if scanned.unparseable:
        unreadable.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )

    if total == 0:
        measured = (
            "no test files found - nothing measured, so nothing scored"
            if not scanned.unparseable
            else (
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present but "
                f"unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Module evictions restored", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unrestored(scanned)
    population = function_count(scanned)
    score = int(((population - len(flagged)) / population) * 100)
    checks: List[Dict] = [
        {
            "name": "Module evictions restored",
            "passed": not flagged,
            "message": (
                f"{population}/{population} test functions, fixtures and helpers leave the import cache as they "
                "found it"
                if not flagged
                else (
                    f"{len(flagged)}/{population} test functions, fixtures and helpers evict a cached module "
                    "with no visible restore: "
                    + ", ".join(f"{r['nodeid']} ({r['species']})" for r in flagged[:MAX_REPORTED])
                    + (f" (+{len(flagged) - MAX_REPORTED} more)" if len(flagged) > MAX_REPORTED else "")
                )
            ),
        }
    ]
    checks.extend(unreadable)

    return {
        "passed": True,
        "score": score,
        "checks": checks,
        "standard": STANDARD_NAME.upper(),
        "advisory": True,
        "violations": flagged,
    }
