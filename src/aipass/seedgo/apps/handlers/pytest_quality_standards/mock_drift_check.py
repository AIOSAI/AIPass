# =================== AIPass ====================
# Name: mock_drift_check.py
# Description: v5 - does a patch replace a function or a whole module
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
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
TEST_DIRS: tuple = ("tests", "test")

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

    flagged = find_module_patches(scanned)
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
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
