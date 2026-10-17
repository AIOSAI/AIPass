# =================== AIPass ====================
# Name: fresh_clone_check.py
# Description: v5 - would this test pass on a machine that has only what the repo ships
# Version: 1.1.1
# Created: 2026-09-08
# Modified: 2026-10-17
# =============================================

"""Would this test pass on a machine that has only what the repo ships?

Reference: fresh_clone.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# Re-exported so callers keep importing these from fresh_clone_check.
from aipass.seedgo.apps.handlers.pytest_quality_standards.fresh_clone_extras import (  # noqa: F401
    IMPORT_ERRORS,
    OPTIONAL_EXTRA_MODULES,
)
from aipass.seedgo.apps.handlers.pytest_quality_standards.fresh_clone_extras import (
    _finding,
    _is_fixture,
    _tail,
    file_extra_controls,
    optional_extra,
    optional_extra_functions,
    product_aliases,
)


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "fresh_clone"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: Frozen from the AIPass root `.gitignore`; never read at audit time (the pack is portable).
IGNORED_SEGMENTS: frozenset = frozenset(
    {
        ".trinity",
        ".watchdog",
        ".ai_mail.local",
        "ai_mail.local",
        ".feedback.local",
        ".ai_central",
        ".archive",
        ".backup",
        ".backup_system",
        ".recovery",
        ".seed",
        ".spawn",
        ".chroma",
        "logs",
        "system_logs",
        "artifacts",
        "dropbox",
        "docs.local",
        "projects",
        "mutants",
        "backups",
        "backup_data",
        "branch_audits",
        "readme_history",
    }
)

#: A segment, not a filename: `trigger_json/` is runtime state, `trigger.json` may be source.
IGNORED_SEGMENT_SUFFIXES: tuple = ("_json",)

IGNORED_FILE_NAMES: frozenset = frozenset(
    {
        "DASHBOARD.local.json",
        "STATUS.local.md",
        "STATUS.md",
        "AIPASS_REGISTRY.json",
        "AIPASS_ROOTS.json",
        "CLOSED_PLANS.local.json",
        "notepad.md",
        "dev.local.md",
        ".devpulse_secret.md",
        # A FILE line: `.daemon/` itself is tracked, so `.daemon` is not a segment.
        "last_wake_prompt.txt",
    }
)

#: The `.gitignore` `!` lines re-admit `spawn/templates/*/.trinity/**`; a frozen list
#: cannot express a negation, so the negated region is spelled by its root's name.
NEGATED_ROOT_SPELLINGS: tuple = ("template",)

IGNORED_FILE_SUFFIXES: tuple = (".local.md",)
IGNORED_FILE_PREFIXES: tuple = ("FPLAN-", "DPLAN-", "RPLAN-", "TDPLAN-", "PPLAN-", "APLAN-")

SANDBOX_SEEDS: frozenset = frozenset(
    {
        "tmp_path",
        "tmp_path_factory",
        "tmpdir",
        "tmpdir_factory",
        "TemporaryDirectory",
        "NamedTemporaryFile",
        "mkdtemp",
        "mkstemp",
        "gettempdir",
        # Named exception, not a wildcard: the fleet's conftest template roots it at tmp_path.
        "temp_test_dir",
    }
)

#: Only path-shaped names are resolved one hop: `_run(cwd=Path(__file__).parent)` is not a path.
PATH_SHAPED_CALLS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PosixPath", "str", "resolve", "absolute", "expanduser", "joinpath"}
)

MACHINE_ROOT_CALLS: frozenset = frozenset(
    {"find_repo_root", "get_repo_root", "find_branch_root", "get_branch_root", "repo_root", "getcwd", "cwd"}
)

#: `__file__` alone is the shipped test file; only a climb to a directory reaches host state.
CLIMBING_ATTRIBUTES: frozenset = frozenset({"parent", "parents"})
CLIMBING_CALLS: frozenset = frozenset({"os.path.dirname", "dirname"})

#: These turn a machine path back into a platform constant: `/` is not this checkout.
PLATFORM_CONSTANT_ATTRIBUTES: frozenset = frozenset({"anchor", "root", "drive", "parts"})

EXISTENCE_METHODS: frozenset = frozenset({"exists", "is_dir", "is_file", "is_symlink", "isdir", "isfile"})

READING_METHODS: frozenset = frozenset(
    {
        "exists",
        "is_dir",
        "is_file",
        "is_symlink",
        "iterdir",
        "glob",
        "rglob",
        "read_text",
        "read_bytes",
        "open",
        "stat",
        "samefile",
    }
)

READING_FUNCTIONS: frozenset = frozenset(
    {
        "open",
        "os.listdir",
        "os.scandir",
        "os.walk",
        "os.stat",
        "os.path.exists",
        "os.path.isdir",
        "os.path.isfile",
        "os.path.getsize",
        "json.load",
    }
)

#: Their RECEIVER is the world, read the way the third arm reads a call argument.
LISTING_METHODS: frozenset = frozenset({"iterdir", "glob", "rglob", "scandir", "walk", "listdir"})

BUILDING_METHODS: frozenset = frozenset({"mkdir", "write_text", "write_bytes", "touch", "symlink_to", "hardlink_to"})
BUILDING_FUNCTIONS: frozenset = frozenset({"os.makedirs", "os.mkdir", "shutil.copytree", "shutil.copy", "shutil.copy2"})

#: A derived root reaching one of these is being located or compared, not described.
NOT_THE_WORLD: frozenset = frozenset(
    {
        "str",
        "Path",
        "PurePath",
        "fspath",
        "insert",
        "append",
        "chdir",
        "syspath_prepend",
        "spec_from_file_location",
        "module_from_spec",
        "SourceFileLoader",
        "exec_module",
        "print",
        "len",
        "repr",
        "format",
        "join",
        "relative_to",
        "resolve",
        "skip",
        "skipif",
        "fail",
        "patch",
        "object",
        "setattr",
        "setenv",
        "delenv",
        "monkeypatch",
        "startswith",
        "endswith",
        "split",
        "rsplit",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "lower",
        "upper",
        "encode",
        "decode",
        "count",
        "index",
        "find",
        "add",
        "get",
        "update",
        "extend",
        "sort",
        "sorted",
        "set",
        "list",
        "tuple",
        "dict",
        "int",
        "float",
        "bool",
    }
    | BUILDING_METHODS
    | EXISTENCE_METHODS
)

#: Paired with an existence probe these are a `self_skip` row, left to that rule.
SKIP_CALLS: frozenset = frozenset({"skip", "skipif"})

MAX_REPORTED: int = 12


def _names_under(node: ast.AST) -> Set[str]:
    """Every bare name and dotted call target under a node."""
    found: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Call):
            dotted = corpus.dotted_name(child.func)
            if dotted:
                found.add(dotted)
                found.add(_tail(dotted))
    return found


def _assign_targets(node: Union[ast.Assign, ast.AnnAssign]) -> Sequence[ast.expr]:
    """The target expressions of an assignment, in either spelling."""
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _bound_names(node: ast.AST) -> Dict[str, ast.expr]:
    """Every name assigned under a node, mapped to the expression it came from."""
    bound: Dict[str, ast.expr] = {}
    for child in ast.walk(node):
        if not isinstance(child, (ast.Assign, ast.AnnAssign)) or child.value is None:
            continue
        for target in _assign_targets(child):
            if isinstance(target, ast.Name):
                bound[target.id] = child.value
    return bound


def _nested_parameter_names(unit_node: ast.AST) -> Set[str]:
    """Every parameter of a function DEFINED INSIDE this unit."""
    names: Set[str] = set()
    for child in ast.walk(unit_node):
        if child is unit_node or not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        spec = child.args
        names |= {a.arg for a in [*spec.posonlyargs, *spec.args, *spec.kwonlyargs]}
    return names


def _sandbox_names(unit_node: ast.AST, seeds: Optional[Set[str]] = None) -> Set[str]:
    """Names that resolve to a directory pytest or tempfile creates and removes.

    Nested-def parameters join only in a unit that already names a sandbox: a gate, not a blanket.
    """
    bound: Set[str] = set(SANDBOX_SEEDS) | set(seeds or ())
    if _names_under(unit_node) & bound:
        bound |= _nested_parameter_names(unit_node)
    changed = True
    while changed:
        changed = False
        for child in ast.walk(unit_node):
            fresh = _names_bound_from(child, bound)
            if fresh:
                bound |= fresh
                changed = True
    return bound


def _binding_form(child: ast.AST) -> Tuple[Sequence[ast.expr], Optional[ast.expr]]:
    """The names a node binds and the value it binds them from, or ([], None)."""
    if isinstance(child, (ast.Assign, ast.AnnAssign)) and child.value is not None:
        return _assign_targets(child), child.value
    if isinstance(child, ast.withitem) and child.optional_vars is not None:
        return [child.optional_vars], child.context_expr
    if isinstance(child, (ast.For, ast.AsyncFor, ast.comprehension)):
        return [child.target], child.iter
    return [], None


def _names_bound_from(child: ast.AST, bound: Set[str]) -> Set[str]:
    """Names this binding adds to the sandbox set, given what is already in it."""
    targets, value = _binding_form(child)
    if value is None or not (_names_under(value) & bound):
        return set()
    return _target_names(targets) - bound


def _target_names(targets: Sequence[ast.expr]) -> Set[str]:
    """Every name an assignment binds, unpacking included (generous: one sandbox element acquits all)."""
    names: Set[str] = set()
    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name):
                names.add(child.id)
    return names


def _class_scopes(tree: ast.Module) -> Dict[str, Dict[str, ast.expr]]:
    """Class name -> the constants assigned directly in that class body (`self.BRANCH_ROOT`)."""
    return {node.name: _bound_names_in_body(node.body) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def _bound_names_in_body(body: Sequence[ast.stmt]) -> Dict[str, ast.expr]:
    """Names assigned directly in a statement list, one level deep."""
    bound: Dict[str, ast.expr] = {}
    for node in body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        for target in _assign_targets(node):
            if isinstance(target, ast.Name):
                bound[target.id] = node.value
    return bound


def unit_scope(unit: corpus.TestUnit, module_scope: Dict[str, ast.expr], classes: Dict[str, Dict]) -> Dict:
    """Every name this unit could resolve, one hop: module, class, then local (local wins)."""
    scope: Dict[str, ast.expr] = dict(module_scope)
    scope.update(classes.get(unit.class_name, {}))
    scope.update(_bound_names(unit.node))
    return scope


def _one_hop(expr: ast.expr, scope: Dict[str, ast.expr]) -> List[ast.expr]:
    """The expression, plus the expression behind each name it mentions: one hop, never a chain."""
    forms: List[ast.expr] = [expr]
    for child in ast.walk(expr):
        key = ""
        if isinstance(child, ast.Name):
            key = child.id
        elif isinstance(child, ast.Attribute):
            key = child.attr
        behind = scope.get(key)
        if behind is not None and behind is not expr:
            forms.append(behind)
    return forms


def parent_map(root: ast.AST) -> Dict[int, ast.AST]:
    """Child id -> parent node, for one unit."""
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(root):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _ancestors(node: ast.AST, parents: Dict[int, ast.AST]) -> List[ast.AST]:
    """Every node enclosing this one, innermost first."""
    chain: List[ast.AST] = []
    current = parents.get(id(node))
    while current is not None:
        chain.append(current)
        current = parents.get(id(current))
    return chain


def _call_role(call: ast.Call, child: ast.AST) -> str:
    """What one enclosing call does with the node under it: build, read, or "".

    `child` is the call's DIRECT child on the path up, so receiver-ness is `child is call.func`.
    """
    dotted = corpus.dotted_name(call.func)
    tail = _tail(dotted)
    on_receiver = child is call.func
    if on_receiver and tail in BUILDING_METHODS:
        return "build"
    if dotted in BUILDING_FUNCTIONS:
        return "build"
    if on_receiver and tail in READING_METHODS:
        return "read"
    if dotted in READING_FUNCTIONS:
        return "read"
    return ""


def _direct_role(node: ast.AST, parents: Dict[int, ast.AST]) -> str:
    """What the calls enclosing this node do with it: "build", "read", or "" ("build" outranks "read")."""
    role = ""
    child: ast.AST = node
    ancestor = parents.get(id(node))
    while ancestor is not None:
        if isinstance(ancestor, ast.Call):
            found = _call_role(ancestor, child)
            if found == "build":
                return "build"
            role = role or found
        child, ancestor = ancestor, parents.get(id(ancestor))
    return role


def _bound_to_name(node: ast.AST, parents: Dict[int, ast.AST]) -> str:
    """The name this node is assigned to, or ""."""
    for ancestor in _ancestors(node, parents):
        if not isinstance(ancestor, (ast.Assign, ast.AnnAssign)):
            continue
        names = [t.id for t in _assign_targets(ancestor) if isinstance(t, ast.Name)]
        if names:
            return names[0]
    return ""


def _name_uses(unit_node: ast.AST) -> Dict[str, List[ast.Name]]:
    """Name -> every load of that name inside the unit, walked once."""
    uses: Dict[str, List[ast.Name]] = {}
    for node in ast.walk(unit_node):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            uses.setdefault(node.id, []).append(node)
    return uses


def _role_of(node: ast.AST, parents: Dict[int, ast.AST], uses: Dict[str, List[ast.Name]]) -> str:
    """What the unit does with this node, following one assignment and no more."""
    role = _direct_role(node, parents)
    if role == "build":
        return "build"
    for use in uses.get(_bound_to_name(node, parents), ()):
        found = _direct_role(use, parents)
        if found == "build":
            return "build"
        role = role or found
    return role


def _is_written_down(node: ast.expr) -> bool:
    """True when an expression is a value the author TYPED rather than computed."""
    if isinstance(node, ast.Constant):
        return node.value is not None and not isinstance(node.value, bool)
    return isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict))


def pins_a_written_expectation(node: ast.Assert) -> bool:
    """True when this assert compares something against a value spelled in the file."""
    for child in ast.walk(node.test):
        if not isinstance(child, ast.Compare):
            continue
        if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in child.ops):
            continue
        if any(_is_written_down(side) for side in [child.left, *child.comparators]):
            return True
    return False


def _asserted_names(unit_node: ast.AST) -> Set[str]:
    """Names compared against a written-down value somewhere in this unit."""
    found: Set[str] = set()
    for node in ast.walk(unit_node):
        if not isinstance(node, ast.Assert) or not pins_a_written_expectation(node):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                found.add(child.id)
    return found


def _path_expression_around(node: ast.expr, parents: Dict[int, ast.AST]) -> ast.expr:
    """The widest path-shaped expression enclosing a node; its ROOT decides tmp_path or not."""
    widest: ast.expr = node
    for ancestor in _ancestors(node, parents):
        if not isinstance(ancestor, (ast.BinOp, ast.Attribute, ast.Subscript, ast.Call)):
            break
        widest = ancestor
    return widest


def is_ignored_segment(segment: str) -> bool:
    """True when one path segment matches a root `.gitignore` pattern (segment-wise, not substring)."""
    if not segment or segment in {".", "..", "*"}:
        return False
    if segment in IGNORED_SEGMENTS or segment in IGNORED_FILE_NAMES:
        return True
    if segment.endswith(IGNORED_SEGMENT_SUFFIXES) or segment.endswith(IGNORED_FILE_SUFFIXES):
        return True
    return segment.startswith(IGNORED_FILE_PREFIXES)


def _ignored_spelling(text: str) -> str:
    """The first ignored segment inside one string literal, or ""."""
    for segment in text.replace("\\", "/").split("/"):
        if is_ignored_segment(segment):
            return segment
    return ""


def _path_literals(unit_node: ast.AST) -> List[Tuple[ast.Constant, str]]:
    """String literals sitting in a position that builds a path.

    A literal in an expected-value list is data a producer returned, not a path this unit opened.
    """
    found: List[Tuple[ast.Constant, str]] = []
    for node in ast.walk(unit_node):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            found.extend(_string_constants((node.left, node.right)))
        elif isinstance(node, ast.Call):
            found.extend(_literal_arguments(node))
    return found


def _string_constants(nodes: Sequence[ast.expr]) -> List[Tuple[ast.Constant, str]]:
    """Every string-literal node in a sequence, paired with its text."""
    return [(n, n.value) for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _literal_arguments(node: ast.Call) -> List[Tuple[ast.Constant, str]]:
    """String literal arguments to a call that treats them as a path."""
    dotted = corpus.dotted_name(node.func)
    tail = _tail(dotted)
    path_shaped = tail in {"Path", "PurePath", "PurePosixPath", "glob", "rglob", "joinpath"}
    path_shaped = path_shaped or dotted in READING_FUNCTIONS or dotted in {"os.path.join", "os.path.exists"}
    if not path_shaped:
        return []
    return _string_constants(node.args)


def _built_spellings(unit_node: ast.AST) -> Set[str]:
    """Ignored segments this unit CREATES, which is the acquittal for reading them."""
    parents = parent_map(unit_node)
    uses = _name_uses(unit_node)
    built: Set[str] = set()
    for literal, text in _path_literals(unit_node):
        segment = _ignored_spelling(text)
        if segment and _role_of(literal, parents, uses) == "build":
            built.add(segment)
    return built


def _rooted_in_a_negated_region(expr: ast.expr, scope: Dict[str, ast.expr]) -> bool:
    """True when the path is reached through something the ignore file re-admits (a spelling test)."""
    for form in _one_hop(expr, scope):
        for name in _names_under(form):
            if any(spelling in name.lower() for spelling in NEGATED_ROOT_SPELLINGS):
                return True
    return False


def _ignored_path(
    unit: corpus.TestUnit, sandbox: Set[str], built_elsewhere: Set[str], scope: Dict[str, ast.expr]
) -> List[Dict]:
    """Findings for paths a fresh clone does not have."""
    parents = parent_map(unit.node)
    uses = _name_uses(unit.node)
    built = _built_spellings(unit.node) | built_elsewhere
    rows: List[Dict] = []
    for literal, text in _path_literals(unit.node):
        segment = _ignored_spelling(text)
        if not segment or segment in built:
            continue
        if _role_of(literal, parents, uses) != "read":
            continue
        spine = _path_expression_around(literal, parents)
        if _names_under(spine) & sandbox or _rooted_in_a_negated_region(spine, scope):
            continue
        rows.append(
            _finding(
                "IGNORED_PATH",
                unit,
                getattr(literal, "lineno", unit.line),
                f"reads '{text}' - the segment '{segment}' matches a root .gitignore pattern, so a "
                f"fresh clone has nothing there and this unit never builds it",
            )
        )
    return rows


def _existence_probe(node: ast.AST) -> str:
    """The existence question an expression asks the filesystem, or ""."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        dotted = corpus.dotted_name(child.func)
        if _tail(dotted) in EXISTENCE_METHODS:
            return dotted or _tail(dotted)
    return ""


def _asserts_in(statements: Sequence[ast.stmt]) -> bool:
    """True when a block of statements contains an assert anywhere."""
    return any(isinstance(child, ast.Assert) for stmt in statements for child in ast.walk(stmt))


def _both_worlds(unit: corpus.TestUnit, sandbox: Set[str]) -> List[Dict]:
    """Findings for a unit that asserts one thing here and another thing there."""
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.If) or not node.orelse:
            continue
        probe = _existence_probe(node.test)
        if not probe or _names_under(node.test) & sandbox:
            continue
        if not (_asserts_in(node.body) and _asserts_in(node.orelse)):
            continue
        rows.append(
            _finding(
                "BOTH_WORLDS",
                unit,
                node.lineno,
                f"branches on {probe}() and asserts in both arms - the oracle is a runtime question about "
                f"THIS machine, so whichever arm this host takes is the only arm anyone ever runs and the "
                f"other one is prose. A fresh clone takes the arm you did not write for it",
            )
        )
    return rows


def _climbs_to_a_directory(expr: ast.expr) -> bool:
    """True when an expression walks up from a file to the directory holding it."""
    for child in ast.walk(expr):
        if isinstance(child, ast.Attribute) and child.attr in CLIMBING_ATTRIBUTES:
            return True
        if isinstance(child, ast.Call) and corpus.dotted_name(child.func) in CLIMBING_CALLS:
            return True
    return False


def _machine_root_seed(expr: ast.expr) -> str:
    """How an expression asks the running machine where it is, or "" (`__file__` only once climbed)."""
    for child in ast.walk(expr):
        if isinstance(child, ast.Attribute) and child.attr in PLATFORM_CONSTANT_ATTRIBUTES:
            return ""
    for child in ast.walk(expr):
        if isinstance(child, ast.Call) and _tail(corpus.dotted_name(child.func)) in MACHINE_ROOT_CALLS:
            return corpus.dotted_name(child.func) or "cwd"
    if _climbs_to_a_directory(expr) and any(
        isinstance(child, ast.Name) and child.id == "__file__" for child in ast.walk(expr)
    ):
        return "Path(__file__).parents[...]"
    return ""


def _holds_a_literal(expr: ast.expr) -> bool:
    """True when an expression spells any string out loud."""
    return any(isinstance(c, ast.Constant) and isinstance(c.value, str) for c in ast.walk(expr))


def _is_path_shaped(expr: ast.expr) -> bool:
    """True when an expression is a path chain rather than some other value."""
    node: ast.AST = expr
    while True:
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
            continue
        if isinstance(node, ast.BinOp):
            node = node.left
            continue
        if not isinstance(node, ast.Call):
            return isinstance(node, ast.Name)
        called = _tail(corpus.dotted_name(node.func))
        if called in PATH_SHAPED_CALLS:
            node = node.func
            continue
        if called in MACHINE_ROOT_CALLS:
            return True
        return False


def bare_machine_root(expr: ast.expr, scope: Dict[str, ast.expr]) -> str:
    """The machine root this expression IS, with no literal segment on it, or ""."""
    forms = [expr] + [f for f in _one_hop(expr, scope)[1:] if _is_path_shaped(f)]
    seed = ""
    for form in forms:
        seed = seed or _machine_root_seed(form)
    if not seed or any(_holds_a_literal(form) for form in forms):
        return ""
    return seed


def _reaches_an_assert(node: ast.AST, parents: Dict[int, ast.AST], asserted: Set[str]) -> bool:
    """True when a call's answer is compared against a value spelled in the file."""
    for ancestor in _ancestors(node, parents):
        if isinstance(ancestor, ast.Assert):
            return pins_a_written_expectation(ancestor)
        if isinstance(ancestor, (ast.Assign, ast.AnnAssign)):
            names = {t.id for t in _assign_targets(ancestor) if isinstance(t, ast.Name)}
            if names & asserted:
                return True
    return False


def _world_arguments(call: ast.Call) -> List[ast.expr]:
    """The expressions this call is being handed as a world to describe."""
    dotted = corpus.dotted_name(call.func)
    tail = _tail(dotted)
    if tail in LISTING_METHODS and isinstance(call.func, ast.Attribute):
        return [call.func.value]
    if tail in NOT_THE_WORLD:
        return []
    return list(call.args)


def _derived_expected(unit: corpus.TestUnit, scope: Dict[str, ast.expr]) -> List[Dict]:
    """Findings for a value the machine, not the test, decided."""
    parents = parent_map(unit.node)
    asserted = _asserted_names(unit.node)
    rows: List[Dict] = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        seeds = [bare_machine_root(a, scope) for a in _world_arguments(node)]
        seed = next((s for s in seeds if s), "")
        if not seed or not _reaches_an_assert(node, parents, asserted):
            continue
        rows.append(
            _finding(
                "DERIVED_EXPECTED",
                unit,
                node.lineno,
                f"hands {seed} - this machine's own root, with no path segment on it - to "
                f"{corpus.dotted_name(node.func) or 'a call'}() and then asserts on the answer. The expected "
                f"value is whatever this checkout happens to contain; a fresh clone contains something else",
            )
        )
    return rows


def skip_guarded(unit: corpus.TestUnit) -> bool:
    """True when the unit steps aside on a machine that lacks what it reads (`self_skip`'s row, not ours)."""
    calls = {_tail(corpus.dotted_name(n.func)) for n in ast.walk(unit.node) if isinstance(n, ast.Call)}
    return bool(calls & SKIP_CALLS) and bool(_existence_probe(unit.node))


def sandbox_fixtures(tree: ast.Module) -> Set[str]:
    """Same-file fixtures that hand out a directory pytest creates and removes, to a fixed point."""
    fixtures = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(n)]
    found: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in fixtures:
            parameters = {argument.arg for argument in node.args.args}
            if node.name in found or not ((parameters | _names_under(node)) & (SANDBOX_SEEDS | found)):
                continue
            found.add(node.name)
            changed = True
    return found


def fixture_built_spellings(tree: ast.Module) -> Dict[str, Set[str]]:
    """Fixture name -> the ignored segments that fixture CREATES.

    Built once per file, not per unit: per-unit re-parsing is quadratic on large files.
    """
    return {
        node.name: _built_spellings(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(node)
    }


def unit_flags(
    unit: corpus.TestUnit,
    scope: Dict[str, ast.expr],
    handed_out: Optional[Set[str]] = None,
    fixture_built: Optional[Dict[str, Set[str]]] = None,
) -> List[Dict]:
    """Every fresh-clone finding in one unit, in species order.

    Fixture inputs default to none: a caller with no file gets the strict reading, not a generous one.
    """
    if skip_guarded(unit):
        return []
    requested = {argument.arg for argument in unit.node.args.args}
    sandbox = _sandbox_names(unit.node, requested & set(handed_out or ()))
    built: Set[str] = set()
    for name in requested:
        built |= (fixture_built or {}).get(name, set())
    return _ignored_path(unit, sandbox, built, scope) + _both_worlds(unit, sandbox) + _derived_expected(unit, scope)


def find_host_dependent(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit whose answer comes from this machine rather than the repo.

    One row per unit, always: counting findings would let one test drive the score below zero.
    """
    rows: List[Dict] = []
    seen: Set[str] = set()
    guarded = optional_extra_functions(scanned.production_trees)
    for parsed in scanned.files:
        module_scope = _bound_names_in_body(parsed.tree.body)
        classes = _class_scopes(parsed.tree)
        handed_out = sandbox_fixtures(parsed.tree)
        fixture_built = fixture_built_spellings(parsed.tree)
        aliases = product_aliases(parsed.tree, guarded) if guarded else {}
        controls = file_extra_controls(parsed.tree)
        for unit in parsed.units:
            scope = unit_scope(unit, module_scope, classes)
            extra_rows = optional_extra(unit, aliases, guarded, controls) if aliases else []
            for row in unit_flags(unit, scope, handed_out, fixture_built) + extra_rows:
                if row["nodeid"] not in seen:
                    seen.add(row["nodeid"])
                    rows.append(row)
    return rows


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests would pass on a fresh clone.

    `bypass_rules` is accepted for the scoring-API contract and not read: shadow mode gates nothing.
    """
    root = Path(branch_path)
    # Production is parsed for OPTIONAL_EXTRA only.
    scanned = corpus.build(root, test_dirs=TEST_DIRS, with_production=True)
    total = scanned.unit_count()

    # Built before the early return: an all-unparseable project must not read as "no tests".
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
            "checks": [{"name": "Fresh clone survivable", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_host_dependent(scanned)
    score = int(((total - len(flagged)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Fresh clone survivable",
            "passed": not flagged,
            "message": (
                f"{total - len(flagged)}/{total} test units read only what the repo ships"
                if not flagged
                else (
                    f"{len(flagged)}/{total} test units take their answer from state a fresh clone "
                    "does not have: "
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
