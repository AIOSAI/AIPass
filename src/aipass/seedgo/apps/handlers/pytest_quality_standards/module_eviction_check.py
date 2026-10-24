# =================== AIPass ====================
# Name: module_eviction_check.py
# Description: v5 - a test that evicts a cached module and does not put it back
# Version: 1.1.1
# Created: 2026-09-15
# Modified: 2026-10-24
# =============================================

"""Does this test leave the import cache the way it found it?

Reference: module_eviction.md"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "module_eviction"

#: Tried in order; a project matching none of them gets a whole-tree walk.
TEST_DIRS: tuple = corpus.TEST_DIRS

SYS_MODULES: str = "sys.modules"

#: A cache entry and a package attribute are two homes of one module; a finding says which.
SPECIES_CACHE: str = "SYS_MODULES_EVICTION"
SPECIES_ATTRIBUTE: str = "PACKAGE_ATTRIBUTE_EVICTION"
#: A re-import sets the new module on the surviving parent, which a cache-only restore never undoes.
SPECIES_REBIND: str = "PARENT_ATTRIBUTE_REBIND"

#: Their result can only be a module (or None), so a name bound from one is provably a module.
MODULE_BINDERS: frozenset = frozenset({"importlib.import_module", "__import__", "sys.modules.get"})

#: Read on any receiver: `monkeypatch`, `mp` and `self.monkeypatch` are the same MonkeyPatch.
RECORDING_ITEM_METHODS: frozenset = frozenset({"setitem", "delitem"})
RECORDING_ATTR_METHODS: frozenset = frozenset({"setattr", "delattr"})

PATCH_DICT: str = "patch.dict"

#: A nested def is its own subject and a lambda's body may never run, so neither is read with its parent.
SEPARATE_SCOPES: tuple = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

MAX_TARGET_TEXT: int = 60

#: The full list lives in the report artifact.
MAX_REPORTED: int = 12


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

    imports: Set[str] = field(default_factory=set)
    strings: Dict[str, str] = field(default_factory=dict)
    collections: Dict[str, List[str]] = field(default_factory=dict)
    autouse_keys: Set[str] = field(default_factory=set)


def functions_in(tree: ast.Module) -> List[Tuple[str, Union[ast.FunctionDef, ast.AsyncFunctionDef]]]:
    """Every def in a parsed file with its `::`-joined qualified name, nested ones too.

    A def inside an `if`, `try` or `with` is still a def, so every statement child is walked."""
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

    ONE SCOPE, ONE OWNER: walking nested defs would report a site twice and let a parent's restore acquit a child."""
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


def is_module_expression(node: Optional[ast.AST]) -> bool:
    """True for an expression whose value can only be a module (or None).

    A `from x import y` name, a parameter or an attribute may be a function, and `delattr` on one is no eviction."""
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

    Proven by an `import` or an assignment from a module expression; DISPROVEN by any other binding in
    the function, because which binding is live at the `delattr` is unknowable and doubt goes to no-flag."""
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


def _recorded_first(eviction: Eviction, nodes: List[ast.AST]) -> bool:
    """True when monkeypatch recorded the same target before the eviction ran.

    EARLIER, NOT MERELY PRESENT: recorded after the eviction, teardown faithfully restores the hole."""
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

    A decorator guards the whole function; a `with` guards its own body."""
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
    """True for `sys.modules[K] = saved` naming the evicted key, or `sys.modules.update(...)`.

    A CALL IS NOT A RESTORE: `MagicMock()` or `import_module(K)` caches a new object, not the evicted module."""
    if isinstance(node, ast.Assign):
        return not isinstance(node.value, ast.Call) and any(
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

    A RE-IMPORT IS NOT A RESTORE: it mints and caches a new module, which is the pollution itself."""
    restores = _restores_cache if eviction.species == SPECIES_CACHE else _restores_attribute
    for node in nodes:
        if getattr(node, "lineno", -1) <= eviction.line and id(node) not in finally_ids:
            continue
        if restores(node, eviction):
            return True
    return False


def _is_fixture(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True when a function carries a pytest fixture decorator.

    A copy of the reader in host_state_check and fresh_clone_check: no rule imports another, so each lifts out alone."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if corpus.dotted_name(target).rsplit(".", 1)[-1] == "fixture":
            return True
    return False


def before_teardown(function: Union[ast.FunctionDef, ast.AsyncFunctionDef], nodes: List[ast.AST], line: int) -> bool:
    """False for a line in a fixture's teardown, after its last yield: an eviction there IS the cleanup.

    One before the yield still needs a restore, which may sit after it: pytest runs teardown for a failing test too."""
    yields = [getattr(n, "lineno", -1) for n in nodes if isinstance(n, (ast.Yield, ast.YieldFrom))]
    return not (yields and _is_fixture(function) and line > max(yields))


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

    A string is itself; a name is a module-level string constant or a same-scope `for` target over a literal collection."""
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

    An autouse record is restored after every test in its file; a key that resolves to nothing acquits nothing."""
    names = key_strings(eviction.target, nodes, facts)
    return bool(names) and names <= facts.autouse_keys


def _string_value(node: Optional[ast.AST], facts: FileFacts) -> str:
    """A string literal, or a module-level string constant by name, else ""."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return facts.strings.get(node.id, "")
    return ""


def _reads_sys_modules(node: ast.AST) -> bool:
    """True for `sys.modules`, `sys.modules.keys()`, or `list(...)` / `tuple(...)` of either."""
    if corpus.dotted_name(node) == SYS_MODULES:
        return True
    if not isinstance(node, ast.Call):
        return False
    dotted = corpus.dotted_name(node.func)
    if dotted == SYS_MODULES + ".keys":
        return True
    return dotted in ("list", "tuple", "sorted") and len(node.args) == 1 and _reads_sys_modules(node.args[0])


def _startswith_prefixes(test: ast.AST, variable: str, facts: FileFacts) -> Set[str]:
    """The literal prefixes of every `variable.startswith(P)` inside one filter expression."""
    prefixes: Set[str] = set()
    for node in ast.walk(test):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or not node.args:
            continue
        if node.func.attr != "startswith" or not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id != variable:
            continue
        argument = node.args[0]
        parts = argument.elts if isinstance(argument, ast.Tuple) else [argument]
        prefixes.update(value for value in (_string_value(part, facts) for part in parts) if value)
    return prefixes


def key_prefixes(key: ast.expr, nodes: List[ast.AST], facts: FileFacts) -> Set[str]:
    """The prefixes a loop key over `sys.modules` was filtered by, or an empty set.

    `for k in [n for n in sys.modules if n.startswith(P)]`, or `for k in list(sys.modules):` with an `if k.startswith(P):`."""
    if not isinstance(key, ast.Name):
        return set()
    prefixes: Set[str] = set()
    for node in nodes:
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name) or node.target.id != key.id:
            continue
        source = node.iter
        if isinstance(source, ast.Call) and corpus.dotted_name(source.func) in ("list", "tuple", "sorted"):
            source = source.args[0] if source.args else source
        if isinstance(source, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            prefixes |= _comprehension_prefixes(source, facts)
        elif _reads_sys_modules(source):
            guards = [statement.test for statement in node.body if isinstance(statement, ast.If)]
            prefixes.update(*(_startswith_prefixes(test, key.id, facts) for test in guards))
    return prefixes


def _comprehension_prefixes(source: Union[ast.ListComp, ast.GeneratorExp, ast.SetComp], facts: FileFacts) -> Set[str]:
    """The prefixes of `[n for n in sys.modules if n.startswith(P)]`, or an empty set for any other shape."""
    if len(source.generators) != 1:
        return set()
    generator = source.generators[0]
    element = source.elt
    if not _reads_sys_modules(generator.iter) or not isinstance(generator.target, ast.Name):
        return set()
    if not isinstance(element, ast.Name) or element.id != generator.target.id:
        return set()
    prefixes: Set[str] = set()
    for condition in generator.ifs:
        prefixes |= _startswith_prefixes(condition, element.id, facts)
    return prefixes


@dataclass
class CacheClear:
    """One `sys.modules` key removal, through monkeypatch or bare, with what its key stands for."""

    line: int
    column: int
    names: Set[str]
    prefixes: Set[str]

    def covers(self, dotted: str) -> bool:
        """True when this removal took the module named `dotted` out of the cache."""
        return dotted in self.names or any(dotted.startswith(prefix) for prefix in self.prefixes)


def cache_clears_in(nodes: List[ast.AST], facts: FileFacts) -> List[CacheClear]:
    """Every `sys.modules` key removal in one scope whose key resolves to literal names or prefixes.

    `monkeypatch.delitem` counts here: it restores the cache entry, never the parent attribute a re-import rebinds."""
    found: List[CacheClear] = []
    for node in nodes:
        if not isinstance(node, (ast.Delete, ast.Call)):
            continue
        for key in _cleared_keys(node):
            names = key_strings(key, nodes, facts)
            prefixes = key_prefixes(key, nodes, facts)
            if names or prefixes:
                found.append(CacheClear(node.lineno, node.col_offset, names, prefixes))
    return found


def _cleared_keys(node: Union[ast.Delete, ast.Call]) -> List[ast.expr]:
    """The key expressions one `del sys.modules[K]`, `sys.modules.pop(K)` or `<mp>.delitem(sys.modules, K)` removes."""
    if isinstance(node, ast.Delete):
        return [t.slice for t in node.targets if isinstance(t, ast.Subscript) and _is_sys_modules(t.value)]
    if not node.args:
        return []
    if corpus.dotted_name(node.func) == "sys.modules.pop":
        return [node.args[0]]
    is_delitem = isinstance(node.func, ast.Attribute) and node.func.attr == "delitem"
    if is_delitem and len(node.args) >= 2 and _is_sys_modules(node.args[0]):
        return [node.args[1]]
    return []


def _is_sys_modules(node: ast.AST) -> bool:
    """True for `sys.modules` itself."""
    return corpus.dotted_name(node) == SYS_MODULES


def _imported_names(node: ast.AST, facts: FileFacts) -> List[str]:
    """The dotted module names a statement or call imports fresh, when literal; else [].

    `importlib.reload` is not here: it re-executes the same object in place, and the parent attribute keeps it."""
    if isinstance(node, ast.Call) and node.args:
        if corpus.dotted_name(node.func) in ("importlib.import_module", "import_module", "__import__"):
            value = _string_value(node.args[0], facts)
            return [value] if value and not value.startswith(".") else []
        return []
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        return [node.module] + [f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"]
    return []


def _rebound_parent(dotted: str, clears: List[CacheClear]) -> Optional[Tuple[str, str, CacheClear]]:
    """The (parent, leaf, clear) a fresh import of `dotted` rebinds, or None.

    The first evicted package on the path whose own parent survived is set on that parent; a top-level name rebinds nothing."""
    parts = dotted.split(".")
    for depth in range(1, len(parts) + 1):
        candidate = ".".join(parts[:depth])
        for clear in clears:
            if clear.covers(candidate):
                return (".".join(parts[: depth - 1]), parts[depth - 1], clear) if depth > 1 else None
    return None


def _attribute_pinned(leaf: str, before: Tuple[int, int], nodes: List[ast.AST]) -> bool:
    """True when monkeypatch recorded an attribute named `leaf` before the given position."""
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or len(node.args) < 2:
            continue
        if node.func.attr not in RECORDING_ATTR_METHODS or (node.lineno, node.col_offset) >= before:
            continue
        second = node.args[1]
        if isinstance(second, ast.Constant) and second.value == leaf:
            return True
    return False


def _attribute_restored(leaf: str, after: int, nodes: List[ast.AST], finally_ids: Set[int]) -> bool:
    """True for `setattr(M, "leaf", ...)` or `M.leaf = ...` after the import or in a finally."""
    for node in nodes:
        if getattr(node, "lineno", -1) <= after and id(node) not in finally_ids:
            continue
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) == "setattr" and len(node.args) >= 2:
            if isinstance(node.args[1], ast.Constant) and node.args[1].value == leaf:
                return True
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == leaf for t in node.targets):
            return True
    return False


def _inside_pytest_raises(nodes: List[ast.AST]) -> Set[int]:
    """Ids of every node inside a `with pytest.raises(...)` body.

    An import expected to raise binds nothing: the parent attribute is set only after the child finishes executing."""
    inside: Set[int] = set()
    for node in nodes:
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            call = item.context_expr
            if isinstance(call, ast.Call) and corpus.dotted_name(call.func).rsplit(".", 1)[-1] == "raises":
                inside.update(id(child) for statement in node.body for child in ast.walk(statement))
    return inside


def rebinds_in(
    function: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    facts: Optional[FileFacts] = None,
) -> List[Eviction]:
    """Every fresh import after a cache eviction that rebinds a parent attribute nothing pinned.

    EXACT OR SILENT: key and imported name must resolve to literals, and the import must follow the eviction.
    `patch.dict(sys.modules)` acquits nothing here: it restores the dict only."""
    known = facts or FileFacts()
    nodes = own_nodes(function)
    clears = [c for c in cache_clears_in(nodes, known) if before_teardown(function, nodes, c.line)]
    if not clears:
        return []
    finally_ids = _in_a_finally(nodes)
    expected_to_fail = _inside_pytest_raises(nodes)
    found: List[Eviction] = []
    seen: Set[Tuple[int, str]] = set()
    for node in nodes:
        if id(node) in expected_to_fail:
            continue
        position = (getattr(node, "lineno", -1), getattr(node, "col_offset", -1))
        for dotted in _imported_names(node, known):
            earlier = [c for c in clears if (c.line, c.column) < position]
            rebound = _rebound_parent(dotted, earlier)
            if rebound is None:
                continue
            parent, leaf, clear = rebound
            if (position[0], leaf) in seen:
                continue
            if _attribute_pinned(leaf, position, nodes):
                continue
            if _attribute_restored(leaf, position[0], nodes, finally_ids):
                continue
            seen.add((position[0], leaf))
            found.append(
                Eviction(
                    SPECIES_REBIND,
                    node,
                    position[0],
                    position[1],
                    ast.Constant(parent),
                    ast.Constant(leaf),
                    f"{parent}.{leaf} rebound by importing {dotted} after line {clear.line}",
                )
            )
    return found


def _describe(eviction: Eviction) -> str:
    """One site, as the clause a finding quotes."""
    if eviction.species == SPECIES_REBIND and eviction.attr is not None:
        return (
            f"line {eviction.line} re-import leaves {eviction.spelling}: pin "
            f"monkeypatch.setattr(<{_text(eviction.target)}>, {_text(eviction.attr)}, ...) before the eviction"
        )
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

    `facts` defaults to none: a function handed over without its file gets the strict reading, never a generous one."""
    known = facts or FileFacts()
    nodes = own_nodes(function)
    candidates = [
        c
        for c in evictions_in(nodes, provable_modules(function, nodes, known.imports))
        if before_teardown(function, nodes, c.line)
    ]
    if not candidates:
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

    Rows come from helpers too, so scoring against units alone could drive a project below zero."""
    return sum(len(functions_in(parsed.tree)) for parsed in scanned.files)


def find_unrestored(scanned: corpus.Corpus) -> List[Dict]:
    """One row per function that leaves an evicted module unrestored.

    ONE ROW PER FUNCTION, EVERY LINE NAMED in its detail, so the dedupe hides nothing."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        facts = file_facts(parsed.tree)
        for qualname, function in functions_in(parsed.tree):
            left = unrestored_in(function, facts)
            rebound = rebinds_in(function, facts)
            if not left and not rebound:
                continue
            first = min(left + rebound, key=lambda e: (e.line, e.column))
            rows.append(
                {
                    "nodeid": f"{parsed.relpath}::{qualname}",
                    "line": first.line,
                    "species": first.species,
                    "detail": " | ".join(part for part in (_evicted_detail(left), _rebound_detail(rebound)) if part),
                }
            )
    return rows


def _evicted_detail(left: List[Eviction]) -> str:
    """The first two species' clause of a row, or "" when the function has none."""
    if not left:
        return ""
    return (
        "; ".join(_describe(e) for e in left)
        + " - evicted with nothing recording it first and nothing putting it back, so the "
        "import cache keeps whatever the next import mints, in every later test on this "
        "worker. monkeypatch.delitem(sys.modules, ...) and monkeypatch.delattr are restored for you"
    )


def _rebound_detail(rebound: List[Eviction]) -> str:
    """The third species' clause of a row, or "" when the function has none."""
    if not rebound:
        return ""
    return (
        "; ".join(_describe(e) for e in rebound)
        + " - the fresh import sets the NEW module on the surviving parent package, and a restore of "
        "sys.modules alone leaves that attribute pointing at it after teardown. On 3.10/3.11 a dotted "
        "mock.patch walks package attributes, so later string patches land on the new module while "
        "the product reads the old one"
    )


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests put evicted modules back.

    ``bypass_rules`` is accepted for the scoring-API contract and not read: shadow mode gates nothing.
    No tests reports not_applicable: zero tests measured is not zero quality found."""
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # Built before the empty path: a broken only-test-file must never read as no tests.
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
