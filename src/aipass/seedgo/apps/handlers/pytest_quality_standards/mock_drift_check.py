# =================== AIPass ====================
# Name: mock_drift_check.py
# Description: v5 - does a patch's replacement match its target (whole module; function over a class)
# Version: 1.1.0
# Created: 2026-09-01
# Modified: 2026-10-10
# =============================================

"""Does this patch replace a function, or a whole module?

`patch("a.b.c")` where `c` is a function swaps that one function out. Where `c`
is a MODULE, the whole module becomes a `MagicMock`, and a `MagicMock` answers
every attribute access that will ever be made of it - including attributes the
production code no longer has. Delete the function the test was named for and
the mock supplies it anyway, silently, forever.

That is measured, not hypothetical. Deleting `auth.validate_credentials` from one
branch left 46 of 46 tests green. The suite had no opinion about whether the
function existed, because none of those tests was ever talking to it.

HOW A TARGET IS RESOLVED, AND WHY THE WEAK WAY IS THE RIGHT WAY. This check never
imports the project it measures - a checker that imported a stranger's test tree
would execute it, which is the failure this whole pack refuses. So it does not ask
Python whether `a.b.c` is a module; it asks the corpus, which has already read the
tree as text. A dotted target is a module when it matches the path of a `.py` file
the corpus parsed, or when the file named by its parent segment binds that last
segment to a module by import. That is strictly weaker than an import, and the
weakness is deliberate: a module conjured at runtime is invisible here, and being
blind to it costs nothing a reader relies on.

WHY THE IMPORT-BINDING ARM EXISTS AT ALL. `patch(f"{_MOD}.console")` and
`patch(f"{_MOD}.json_handler")` are the same shape to a last-segment match, but
only one of them names a module: `console` is an object imported from a library
and `json_handler` is a file. Matching on the name alone would flag the first,
which is ordinary correct code. Reading what the parent file actually imports is
what makes this rule precise rather than a name collision.

F-STRING TARGETS RESOLVE, AND THAT IS NOT A CONVENIENCE. `patch(f"{_MOD}.thing")`
is the dominant real spelling - the whole 46-test block above is written that way -
and a first version of this rule demanded an `ast.Constant`, so it scored a branch
holding 25 known module patches as completely clean. A detector that only reads the
spelling nobody uses measures nothing. Only interpolations of module-level string
constants resolve; anything computed is unreadable and is never flagged.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM.

`spec=`, `spec_set=`, `autospec=True` and `new_callable=` acquit outright. A
specced mock raises on an attribute the real object does not have, which is
precisely the property whose absence this rule is about. It does not claim the
acquittal is complete - a `spec` pointed at the wrong object is still a lie, and
nothing static can see that.

A target that resolves to no file in the tree is NOT flagged. The rule reports
what it can resolve and stays quiet about the rest, rather than guessing from a
name. That bias runs toward FEWER findings, and it is the direction to be wrong
in for an advisory number.

Class-level decorators are not read. `@patch(...)` on a `class Test...:` reaches
every method in it, and this check only reads each method's own decorators and
body, so a class-level module patch is missed. Stated rather than hidden, because
a reader who knows the shape exists will otherwise assume it was measured.

It reads PRODUCTION, so it can be reading less than the tree holds: a production
file that will not parse contributes no module path and no import binding, which
again biases toward clean. Every result therefore carries `production_limits()`
as its own check line when anything was unreadable. A hole and an unread file look
identical from outside, and only the check itself can tell them apart.

TWO ARMS OF THE ORIGINAL RULE ARE GONE BECAUSE THEY COULD NEVER FIRE, and they are
named here rather than carried as decoration. The first iterated a unit's
decorators before walking its body: `ast.walk` on a `FunctionDef` already descends
into `decorator_list`, so every decorator patch was found twice and the dedupe set
threw the copy away - measured, not assumed. The second listed `patch.object` among
the watched call names; `patch.object(module, "name")` takes an OBJECT as its first
argument, never a dotted string, so the target reader returns None for it every
time. Leaving either in place would tell a future reader that a shape is covered
when it is not.

SECOND SPECIES, CLASS-STANDIN (1.1.0, PR #774 CI round four). The same family:
a patch whose replacement does not match its target. `monkeypatch.setattr(mod,
"Path", lambda *a: ...)` where `mod`'s own source uses `Path` AS A CLASS - an
attribute read off it (`Path.cwd()`), the second argument of isinstance/issubclass,
a base in a class statement. The stand-in has no such surface, so that use dies with
`'function' object has no attribute 'cwd'` - and only on the path that reaches it.
seedgo's own batch7 test at 1.3.1 did exactly this: `_find_registry` falls back to
`Path.cwd()` only when the git-ignored registry marker is absent, so every dev seat
was green and every clean checkout red.
- `mod` must be a bare name the TEST FILE binds by import, resolved to exactly one
  production file through the corpus (longest dotted suffix, at least two segments
  when the import has two). Never by importing. `mod.subprocess` is unreadable - the
  target is not in the corpus - and is skipped.
- The stand-in convicted: a lambda, a name the test file binds only to a `def`, or
  `functools.partial(...)` (a partial has no `.cwd` and isinstance against it
  raises - same species). Acquitted: a class (`class _FakePath`), `type(...)`, a
  MagicMock/Mock (every attribute), anything else.
- A constructor-only use (`Path(x)`) acquits: a function answers a call. A name the
  module binds by plain `import` is a module, not a class, and acquits.
- Helpers are read, not only units: the incident's patch lived in `_windows_spelled`.
  The row names the def holding the call; the score is floored at 0 because a helper
  is a place to look that is not a unit.
- Not claimed: `setattr("pkg.mod.Name", ...)` string targets, local shadowing of
  the name inside the product module, `except Name` uses.

STDLIB ONLY, like the rest of the pack: `ast`, `pathlib`, `typing`, and the pack's
own corpus reader. That constraint is the reason the pack exists.
"""

import ast
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "mock_drift"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Keyword arguments that make a mock refuse unknown attributes. Any one of them
#: acquits the patch outright, because refusing unknown attributes is the exact
#: property whose absence this rule is about.
ACQUITTING_KEYWORDS: frozenset = frozenset({"spec", "spec_set", "autospec", "new_callable"})

#: The call names this rule watches. `patch.object` is deliberately ABSENT: its
#: first argument is an object rather than a dotted string, so it can never
#: produce a readable target and listing it would only promise coverage.
PATCH_NAMES: frozenset = frozenset({"patch", "mock.patch", "unittest.mock.patch"})

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def _module_paths(scanned: corpus.Corpus) -> Set[str]:
    """Every dotted module path the corpus read, plus every suffix of each.

    EVERY SUFFIX, because a test patches `mypkg.apps.thing`, not the path
    relative to the project root. Both `a/b/c.py` and `a/b/c/__init__.py` count.

    Derived from what the corpus already parsed rather than from a second walk of
    the disk. That keeps the resolvable set and the import-binding map describing
    the same files, and it inherits the corpus's vendor pruning - which prunes
    relative to the walk root, so a project that merely LIVES under a directory
    called `build` still resolves.
    """
    found: Set[str] = set()
    relpaths = list(scanned.production_trees) + [parsed.relpath for parsed in scanned.files]

    for relpath in relpaths:
        pure = PurePosixPath(relpath)
        parts = list(pure.parts[:-1]) + [pure.stem]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        for start in range(len(parts)):
            found.add(".".join(parts[start:]))

    return found


def _module_constants(parsed: corpus.TestFile) -> Dict[str, str]:
    """Module-level `NAME = "string"` bindings, for resolving f-string targets."""
    constants: Dict[str, str] = {}
    for node in parsed.tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _patch_target(node: ast.Call, constants: Dict[str, str]) -> Optional[str]:
    """The dotted string a patch call targets, or None when it cannot be read.

    Only interpolations of module-level string constants resolve. Anything
    computed returns None, and an unreadable target is never flagged.
    """
    if not node.args:
        return None

    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value

    if not isinstance(first, ast.JoinedStr):
        return None

    parts: List[str] = []
    for piece in first.values:
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
            parts.append(piece.value)
        elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name):
            resolved = constants.get(piece.value.id)
            if resolved is None:
                return None
            parts.append(resolved)
        else:
            return None

    return "".join(parts)


def _acquitting_keyword(node: ast.Call) -> str:
    """The acquitting keyword this patch carries, or "" when it carries none."""
    for keyword in node.keywords:
        if keyword.arg and keyword.arg in ACQUITTING_KEYWORDS:
            return keyword.arg
    return ""


def _patch_calls(unit: corpus.TestUnit) -> List[ast.Call]:
    """Every `patch(...)` call reaching this unit, decorator or context manager.

    ONE WALK, NOT TWO. `ast.walk` on a `FunctionDef` descends into its
    `decorator_list`, so a separate decorator pass would return every decorator
    patch a second time - see the module docstring.
    """
    return [
        node
        for node in ast.walk(unit.node)
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in PATCH_NAMES
    ]


def _imported_module_names(tree: ast.Module, modules: Set[str]) -> Set[str]:
    """The local names ONE module binds to another module by import."""
    names: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(_plain_import_names(node, modules))
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name in modules)

    return names


def _plain_import_names(node: ast.Import, modules: Set[str]) -> Set[str]:
    """The local names a plain `import x.y` statement binds to a module."""
    names: Set[str] = set()
    for alias in node.names:
        if alias.name in modules or alias.name.split(".")[-1] in modules:
            names.add(alias.asname or alias.name.split(".")[0])
    return names


def _module_bound_names(scanned: corpus.Corpus, modules: Set[str]) -> Dict[str, Set[str]]:
    """Per production file stem, the names it binds to another MODULE by import.

    Keyed by STEM, which is what a patch target's parent segment gives. UNIONED
    rather than assigned: two files can share a stem, and the second overwriting
    the first would drop bindings silently - a hole that makes the rule report
    fewer findings, toward clean.
    """
    bound: Dict[str, Set[str]] = {}

    for relpath, tree in scanned.production_trees.items():
        stem = PurePosixPath(relpath).stem
        bound.setdefault(stem, set()).update(_imported_module_names(tree, modules))

    return bound


def _drift_reason(target: str, modules: Set[str], bound: Dict[str, Set[str]]) -> str:
    """Why this patch target is a module patch, or "" when it is not one."""
    if target in modules:
        return (
            f"patches '{target}', which resolves to a module file in this project - the module "
            f"becomes a MagicMock that answers every attribute, so deleting the production "
            f"function this test is about would not fail it"
        )

    if "." not in target:
        return ""

    parent, attribute = target.rsplit(".", 1)
    owner = parent.rsplit(".", 1)[-1]
    if attribute in bound.get(owner, set()):
        return (
            f"patches '{target}', where '{owner}' binds '{attribute}' to a MODULE by import - "
            f"the patch replaces that module with a MagicMock that answers every attribute, so "
            f"deleting the production function this test is about would not fail it"
        )

    return ""


def unit_flags(
    unit: corpus.TestUnit,
    constants: Dict[str, str],
    modules: Set[str],
    bound: Dict[str, Set[str]],
) -> List[Dict]:
    """Every module-patch finding in one unit, with the evidence for each.

    The public entry point for this rule - the report lane and the tests both ask
    the question here rather than re-deriving it.
    """
    rows: List[Dict] = []
    seen: Set[tuple] = set()

    for call in _patch_calls(unit):
        target = _patch_target(call, constants)
        if not target or _acquitting_keyword(call):
            continue

        reason = _drift_reason(target, modules, bound)
        if not reason:
            continue

        key = (target, call.lineno)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "nodeid": unit.nodeid,
                "line": call.lineno,
                "species": "MOCK-DRIFT",
                "target": target,
                "reason": reason,
            }
        )

    return rows


def find_module_patches(scanned: corpus.Corpus) -> List[Dict]:
    """Every unspecced patch whose target names a MODULE, not an attribute."""
    modules = _module_paths(scanned)
    bound = _module_bound_names(scanned, modules)
    rows: List[Dict] = []

    for parsed in scanned.files:
        constants = _module_constants(parsed)
        for unit in parsed.units:
            rows.extend(unit_flags(unit, constants, modules, bound))

    return rows


# =============================================================================
# SECOND SPECIES - A FUNCTION STANDING IN FOR A CLASS
# =============================================================================


def _module_files(scanned: corpus.Corpus) -> Dict[str, Set[str]]:
    """Dotted module path (every suffix) -> the production relpaths it can name."""
    files: Dict[str, Set[str]] = {}
    for relpath in scanned.production_trees:
        pure = PurePosixPath(relpath)
        parts = list(pure.parts[:-1]) + [pure.stem]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for start in range(len(parts)):
            files.setdefault(".".join(parts[start:]), set()).add(relpath)
    return files


def _resolve_module(dotted: str, files: Dict[str, Set[str]]) -> str:
    """The ONE production file a dotted import names, or "" when none or ambiguous.

    The longest suffix of `dotted` the corpus holds wins, and it must keep the last
    two segments when there are two: `from thirdparty import worker` must not land
    on a project file that merely shares the stem `worker`.
    """
    parts = dotted.split(".")
    shortest = min(2, len(parts))
    for start in range(len(parts) - shortest + 1):
        found = files.get(".".join(parts[start:]), set())
        if found:
            return next(iter(found)) if len(found) == 1 else ""
    return ""


def _imported_modules(tree: ast.Module) -> Dict[str, str]:
    """Local name -> dotted path, for every name a test file binds by import."""
    names: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _file_functions(tree: ast.Module) -> Set[str]:
    """Names the test file binds ONLY to a def - a plain function, never a class."""
    defs = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    return defs - classes


def _is_function_standin(value: ast.expr, functions: Set[str]) -> bool:
    """A lambda, a plain function from this file, or a functools.partial - none has a class surface.

    A partial of the original class is convicted too: `partial(Path).cwd` does not
    exist and `isinstance(x, partial(Path))` raises, so it is the same species.
    """
    if isinstance(value, ast.Lambda):
        return True
    if isinstance(value, ast.Name):
        return value.id in functions
    return isinstance(value, ast.Call) and corpus.dotted_name(value.func) in ("partial", "functools.partial")


def _class_names_in(node: ast.expr) -> List[ast.Name]:
    """The bare names in an isinstance/issubclass second argument, tuple or single."""
    items = node.elts if isinstance(node, ast.Tuple) else [node]
    return [item for item in items if isinstance(item, ast.Name)]


def _class_use(node: ast.AST, name: str) -> str:
    """`line:how` when this one node uses `name` as a class, else ""."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == name:
        return f"{node.lineno}:{name}.{node.attr}"
    if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in ("isinstance", "issubclass"):
        if len(node.args) == 2 and any(item.id == name for item in _class_names_in(node.args[1])):
            return f"{node.lineno}:{corpus.dotted_name(node.func)} second argument"
    if isinstance(node, ast.ClassDef) and any(isinstance(base, ast.Name) and base.id == name for base in node.bases):
        return f"{node.lineno}:used as a base of {node.name}"
    return ""


def _class_uses(tree: ast.Module, name: str) -> List[str]:
    """Where a module's own source uses `name` AS A CLASS: `line:how`, in line order.

    Three uses, and only these: an attribute read off it (`Path.cwd`), the second
    argument of isinstance/issubclass, a base in a class statement. A bare call
    `Name(...)` is a constructor and a function answers it, so it is not here.
    A name the module binds by plain `import` is a module, never a class.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any((a.asname or a.name.split(".")[0]) == name for a in node.names):
            return []

    uses = {use for use in (_class_use(node, name) for node in ast.walk(tree)) if use}
    return sorted(uses, key=lambda use: int(use.split(":", 1)[0]))


def _owned_defs(parsed: corpus.TestFile) -> List[tuple]:
    """(nodeid, def) for every module-level def and every method, helpers included.

    HELPERS INCLUDED, because the real incident lived in one: `_windows_spelled`
    patched Path, and no unit body held the call.
    """
    owned: List[tuple] = []
    for node in parsed.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owned.append((f"{parsed.relpath}::{node.name}", node))
        elif isinstance(node, ast.ClassDef):
            owned.extend(
                (f"{parsed.relpath}::{node.name}::{sub.name}", sub)
                for sub in node.body
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    return owned


def _standin_row(call: ast.Call, nodeid: str, context: Dict) -> Optional[Dict]:
    """One finding for a `.setattr(module, "Name", stand-in)` call, or None."""
    if len(call.args) != 3 or not isinstance(call.args[0], ast.Name):
        return None
    name_arg = call.args[1]
    if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
        return None
    if not _is_function_standin(call.args[2], context["functions"]):
        return None
    dotted = context["imports"].get(call.args[0].id, "")
    relpath = _resolve_module(dotted, context["files"]) if dotted else ""
    if not relpath:
        return None
    uses = _class_uses(context["trees"][relpath], name_arg.value)
    if not uses:
        return None
    first_line, first_how = uses[0].split(":", 1)
    more = f", +{len(uses) - 1} more" if len(uses) > 1 else ""
    return {
        "nodeid": nodeid,
        "line": call.lineno,
        "species": "CLASS-STANDIN",
        "target": f"{dotted}.{name_arg.value}",
        "reason": (
            f"replaces '{name_arg.value}' in {relpath} with a function, but that module uses it as a "
            f"class ({first_how} at {relpath}:{first_line}{more}) - the stand-in has no such surface, "
            f"so that path dies with 'function' object has no attribute, and only on a host that reaches it"
        ),
    }


def _setattr_calls(owner: ast.AST) -> List[ast.Call]:
    """Every `<anything>.setattr(...)` call under one def - monkeypatch's spelling."""
    return [
        node
        for node in ast.walk(owner)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setattr"
    ]


def find_class_standins(scanned: corpus.Corpus) -> List[Dict]:
    """Every `.setattr(module, "Name", lambda/function)` where the module reads Name as a class."""
    files = _module_files(scanned)
    rows: List[Dict] = []

    for parsed in scanned.files:
        context = {
            "files": files,
            "trees": scanned.production_trees,
            "imports": _imported_modules(parsed.tree),
            "functions": _file_functions(parsed.tree),
        }
        for nodeid, owner in _owned_defs(parsed):
            rows.extend(row for row in (_standin_row(c, nodeid, context) for c in _setattr_calls(owner)) if row)

    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    THE SCORE IS PER UNIT, NOT PER FINDING. A unit carrying four module patches
    is one unit a reader has to go and look at; counting the findings would let a
    single sloppy test drive a project's score below zero, and a score that can go
    negative is one nobody believes twice.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its patches replace functions or modules.

    Args:
        branch_path: Path to the project root.
        bypass_rules: Accepted for the scoring-API contract; this pack does not
            read them yet - shadow mode gates nothing, so there is nothing to
            be excused from. Wiring a bypass before the standard can fail would
            be granting exceptions to a rule with no teeth.

    Returns:
        dict with passed (always True in shadow mode), score, checks, standard,
        advisory. A project with no tests reports not_applicable rather than a
        number, because zero tests measured is not zero quality found.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS, with_production=True)
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. An earlier version of the reference check returned "no test files
    # found" before this ran, so a project whose ONLY test file had a syntax
    # error reported exactly what a project with no tests at all reports. A
    # broken file must never read as an absent one - that is the whole contract
    # `unparseable` exists to keep, and it was defeated on the one path where
    # nothing else could catch it. The ordering here is the fix, inherited.
    unreadable: List[Dict] = _limit_checks(scanned)

    if total == 0:
        measured = (
            "no test files found - nothing measured, so nothing scored"
            if not scanned.unparseable
            else (
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present "
                f"but unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Patch target", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    module_rows = find_module_patches(scanned)
    standin_rows = find_class_standins(scanned)
    flagged = module_rows + standin_rows
    units = flagged_nodeids(module_rows)
    standins = flagged_nodeids(standin_rows)
    # A stand-in found in a helper names the helper, which is not a unit, so the
    # places to look can outnumber the units: floored at 0, never negative.
    score = max(0, int(((total - len(flagged_nodeids(flagged))) / total) * 100))
    checks: List[Dict] = [
        {
            "name": "Patch target",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units patch attributes rather than whole modules"
                if not units
                else (
                    f"{len(units)}/{total} test units patch a whole module: "
                    + ", ".join(units[:MAX_REPORTED])
                    + (f" (+{len(units) - MAX_REPORTED} more)" if len(units) > MAX_REPORTED else "")
                )
            ),
        },
        {
            "name": "Class stand-in",
            "passed": not standins,
            "message": (
                "no lambda or plain function is patched over a class its module reads as a class"
                if not standins
                else (
                    f"{len(standins)} place(s) patch a function over a class its module reads as a class: "
                    + ", ".join(standins[:MAX_REPORTED])
                    + (f" (+{len(standins) - MAX_REPORTED} more)" if len(standins) > MAX_REPORTED else "")
                )
            ),
        },
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


def _limit_checks(scanned: corpus.Corpus) -> List[Dict]:
    """The lines saying what could NOT be read, test side and production side.

    THIS RULE READS PRODUCTION, so it can resolve fewer module paths than the
    tree holds, and every unresolved path is a finding that never happens. That
    bias runs toward clean, which is the direction nobody notices. So the
    production limit is published beside the score rather than left implicit -
    a hole and an unread file look identical from outside.
    """
    checks: List[Dict] = []

    if scanned.unparseable:
        checks.append(
            {
                "name": "Corpus readable",
                "passed": True,
                "message": (
                    f"{len(scanned.unparseable)} test file(s) could not be parsed and were NOT "
                    f"measured: {', '.join(scanned.unparseable[:MAX_REPORTED])}"
                ),
            }
        )

    production_limit = scanned.production_limits()
    if production_limit:
        checks.append(
            {
                "name": "Production readable",
                "passed": True,
                "message": (
                    f"{production_limit} - a patch target inside one of them cannot be resolved, "
                    f"so this score is biased toward FEWER findings"
                ),
            }
        )

    return checks
