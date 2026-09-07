# =================== AIPass ====================
# Name: self_skip_check.py
# Description: v5 - where does a skip condition get its answer from
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Where does this test's skip condition get its answer from?

A test that skips itself when the thing it tests changes name has stopped being a
test. The cost is measured, not theoretical: renaming one constant in one branch
made 75 tests silently vanish, and the run stayed green. Nothing failed, because
nothing ran, and nothing said so.

THREE PROVENANCES, AND ONLY ONE OF THEM IS A DEFECT.

The MACHINE. `sys.platform`, `os.environ`, `shutil.which`, an optional extra
probed with `find_spec`. A Linux-only test that skips on Windows is correct code,
and a rule that flagged it would teach projects to delete their own portability.
A machine probe anywhere in the condition - or anywhere in a helper the condition
calls - acquits the whole site outright.

The SUBJECT. The condition asks whether a production symbol still EXISTS, with
`hasattr` or `getattr`, or reads a name imported from the code under test. That is
the defect: the test's answer to "should I run?" is derived from the very thing
whose disappearance it was written to catch. Rename the symbol and the test does
not fail - it evaporates.

NOTHING. An unconditional skip. A test that never runs proves nothing, whatever
it asserts, and the assertions inside it are a decoration on a green board.

THE MODULE SCOPE IS MEASURED, AND IT IS THE EXPENSIVE ONE. A module-level
`pytest.skip(..., allow_module_level=True)` removes an entire FILE, and it belongs
to no test function, so a reader that walked only test functions would miss the
single most costly skip in the catalog - which is exactly the shape that took the
75 tests. Every file therefore carries a `<module>` scope of its own alongside its
units, and that scope is scored like any other.

ONE HOP INTO A LOCAL HELPER, AND NO FURTHER. A skip condition is often written as
`if not _default_factory_raises_on_unknown():` - the provenance is real and it is
one function away. The same is true of a module-level name the condition reads:
the reasoning lives in the statement that computes it, which may be a `for` loop
around a `hasattr`, not a bare assignment, so the enclosing top-level statement is
what gets followed. It stops at one hop because a rule that chased an arbitrary
call graph would be an interpreter, and an interpreter that runs the subject is
the thing this pack refuses to be.

WHAT THIS FILE DELIBERATELY DOES NOT CLAIM.

It does not claim a flagged skip is wrong. A suite testing an optional plugin
legitimately asks whether the plugin is there, and that shape is indistinguishable
from the defect at this distance. The rule names the provenance; a human decides.

It does not see a condition built at runtime from a variable it cannot follow, or
a skip called through an alias it does not recognise, or a `skipif` written with
`condition=` as a keyword instead of a positional argument - `pytest` accepts that
spelling and this reader takes the first positional argument only. Each of those
is a finding that never happens, which biases the score toward clean.

It does not read class-level decorators. `@pytest.mark.skipif(...)` on a
`class Test...:` reaches every method in it; this check reads each method's own
decorators and body, and the file's module scope, and nothing between them.

ONE ARM OF THE ORIGINAL RULE IS CHANGED RATHER THAN COPIED. The original reported
the helper it hopped through by remembering the LAST name it followed, so a
finding proved by a module-level binding could be attributed to an unrelated
helper the same condition happened to call. Provenance now travels with each
source, so the message names the thing that actually carried the answer. And a
`@skip()` decorator - a `Call` whose dotted name is exactly `skip` - was found
twice, once as a decorator and once by the body walk that also descends into
decorators, producing two identical rows for one skip; findings are now deduped
per (unit, line, species).

STDLIB ONLY, like the rest of the pack: `ast`, `pathlib`, `typing`, and the pack's
own corpus reader. That constraint is the reason the pack exists.
"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "self_skip"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = ("tests", "test")

#: Dotted names whose presence in a condition makes it a MACHINE probe. These
#: acquit outright: a platform or environment gate is correct code, and a rule
#: that flagged them would teach branches to delete their own portability. Both
#: the dotted spelling and the bare tail are accepted, because a test that did
#: `from shutil import which` writes the same probe with a shorter name.
MACHINE_PROBES: frozenset = frozenset(
    {
        "sys.platform",
        "sys.version_info",
        "os.name",
        "os.environ",
        "os.getenv",
        "shutil.which",
        "platform.system",
        "platform.machine",
        "importlib.util.find_spec",
        "find_spec",
    }
)

#: Calls that ask whether a symbol still exists. The defining shape of the
#: defect: the test vanishes the moment the symbol is renamed.
EXISTENCE_PROBES: frozenset = frozenset({"hasattr", "getattr"})

#: The dotted spellings of a bare `skip` call this rule recognises in a body or
#: at module level. Decorators are matched by suffix instead, because
#: `pytest.mark.skip` and `pytest.mark.skipif` are the marker spellings.
SKIP_CALL_NAMES: tuple = ("pytest.skip", "skip")

#: How many flagged scopes to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12

#: Parsed once per file to stand in for the module scope - see
#: `_module_level_unit`. A source string rather than a hand-built `ast` node so
#: that no field of `FunctionDef` has to be spelled out and kept correct across
#: interpreter versions that add one.
_STAND_IN_SOURCE: str = "def _module_scope():\n    pass"


# =============================================================================
# ANALYSIS
# =============================================================================


def _imported_names(parsed: corpus.TestFile) -> Set[str]:
    """Every name this test module binds through an import statement."""
    names: Set[str] = set()
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _is_machine_probe(condition: ast.AST) -> bool:
    """True when the condition asks the machine rather than the subject."""
    for node in ast.walk(condition):
        name = corpus.dotted_name(node)
        if name and (name in MACHINE_PROBES or name.rsplit(".", 1)[-1] in MACHINE_PROBES):
            return True
    return False


def _existence_probe(condition: ast.AST) -> str:
    """The existence-probe call in a condition, or "" if there is none."""
    for node in ast.walk(condition):
        if isinstance(node, ast.Call):
            tail = corpus.dotted_name(node.func).rsplit(".", 1)[-1]
            if tail in EXISTENCE_PROBES:
                return tail
    return ""


def _reads_subject(condition: ast.AST, imported: Set[str]) -> str:
    """An imported name the condition reads, or "" if it reads none."""
    for node in ast.walk(condition):
        if isinstance(node, ast.Name) and node.id in imported:
            return node.id
        dotted = corpus.dotted_name(node)
        if dotted and dotted.split(".")[0] in imported:
            return dotted
    return ""


def _local_helpers(parsed: corpus.TestFile) -> Dict[str, ast.AST]:
    """Module-level helper functions by name, for one-hop condition following."""
    return {
        node.name: node
        for node in parsed.tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("test")
    }


def _called_helpers(condition: ast.AST, helpers: Dict[str, ast.AST]) -> List[str]:
    """Module-local helper names this condition calls."""
    names: List[str] = []
    for node in ast.walk(condition):
        if isinstance(node, ast.Call):
            name = corpus.dotted_name(node.func)
            if name in helpers:
                names.append(name)
    return names


def _module_bindings(parsed: corpus.TestFile) -> Dict[str, List[ast.stmt]]:
    """Module-level name -> the top-level statements that compute it.

    THE STATEMENT, NOT THE ASSIGNMENT. A flag is often set inside a `for` loop
    whose `if hasattr(module, candidate):` is where the provenance actually
    lives, so binding to the assignment node alone finds nothing. The enclosing
    top-level statement is the smallest unit that contains the reasoning.
    """
    bindings: Dict[str, List[ast.stmt]] = {}

    for statement in parsed.tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(statement):
            targets: List[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append(statement)

    return bindings


def _read_module_names(condition: ast.AST, bindings: Dict[str, List[ast.stmt]]) -> List[str]:
    """Module-level names this condition reads that are computed elsewhere."""
    return sorted({node.id for node in ast.walk(condition) if isinstance(node, ast.Name) and node.id in bindings})


# =============================================================================
# WHERE THE SKIPS ARE
# =============================================================================


def _decorator_skip_sites(unit: corpus.TestUnit) -> List[Tuple[Optional[ast.AST], int, str]]:
    """Every `@skip` / `@skipif` on the unit, as (condition_or_None, line, how)."""
    sites: List[Tuple[Optional[ast.AST], int, str]] = []

    for decorator in unit.node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = corpus.dotted_name(target)
        if not name.endswith("skipif") and not name.endswith(".skip") and name != "skip":
            continue
        if name.endswith("skipif"):
            if isinstance(decorator, ast.Call) and decorator.args:
                sites.append((decorator.args[0], decorator.lineno, "@skipif"))
        else:
            sites.append((None, decorator.lineno, "@skip"))

    return sites


def _body_skip_sites(unit: corpus.TestUnit) -> List[Tuple[Optional[ast.AST], int, str]]:
    """`pytest.skip(...)` calls in the body, paired with their guarding `if`."""
    return _guarded_skip_calls(unit.node, "pytest.skip()", set())


def _guarded_skip_calls(scope: ast.AST, how: str, skipped: Set[int]) -> List[Tuple[Optional[ast.AST], int, str]]:
    """Every recognised skip call under `scope`, paired with its guarding `if`.

    A skip with no enclosing `if` gets a None condition, which is what separates
    an unconditional skip from the other two provenances. `skipped` holds node
    ids to leave alone - the module scope uses it to drop the calls that live
    inside a function, which belong to that function's own row.
    """
    guards: Dict[int, ast.AST] = {}
    for node in ast.walk(scope):
        if isinstance(node, ast.If):
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and corpus.dotted_name(child.func).endswith("skip"):
                    guards.setdefault(id(child), node.test)

    sites: List[Tuple[Optional[ast.AST], int, str]] = []
    for node in ast.walk(scope):
        if id(node) in skipped:
            continue
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in SKIP_CALL_NAMES:
            sites.append((guards.get(id(node)), node.lineno, how))
    return sites


def _module_skip_sites(parsed: corpus.TestFile) -> List[Tuple[Optional[ast.AST], int, str]]:
    """`pytest.skip(...)` calls at module level, with their guarding `if`.

    THIS IS THE MOST EXPENSIVE SKIP IN THE CATALOG. A module-level skip removes
    the WHOLE FILE, and it was missing from the first version of the rule this
    ports, which walked test functions only.
    """
    inside_functions: Set[int] = set()
    for node in ast.walk(parsed.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                inside_functions.add(id(child))

    return _guarded_skip_calls(parsed.tree, "module-level pytest.skip()", inside_functions)


def _module_level_unit(parsed: corpus.TestFile) -> corpus.TestUnit:
    """A synthetic unit standing for the FILE, so a module-level skip has a row."""
    node = ast.parse(_STAND_IN_SOURCE).body[0]
    return corpus.TestUnit(name="<module>", node=node, relpath=parsed.relpath, line=1)  # type: ignore[arg-type]


# =============================================================================
# CLASSIFICATION
# =============================================================================


def _sources_for(
    condition: ast.AST,
    helpers: Dict[str, ast.AST],
    bindings: Dict[str, List[ast.stmt]],
) -> List[Tuple[ast.AST, str]]:
    """The condition and the one-hop places its answer can come from.

    Each source carries WHERE IT CAME FROM, so a finding proved by a module-level
    binding cannot be reported as coming from an unrelated helper the same
    condition happened to call.
    """
    sources: List[Tuple[ast.AST, str]] = [(condition, "")]
    for name in _called_helpers(condition, helpers):
        sources.append((helpers[name], f"the local helper {name}()"))
    for name in _read_module_names(condition, bindings):
        sources.extend((statement, f"the module-level name {name}") for statement in bindings[name])
    return sources


def _finding(unit: corpus.TestUnit, species: str, line: int, how: str, reason: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "how": how, "reason": reason}


def classify_site(
    unit: corpus.TestUnit,
    condition: Optional[ast.AST],
    line: int,
    how: str,
    imported: Set[str],
    helpers: Dict[str, ast.AST],
    bindings: Dict[str, List[ast.stmt]],
) -> List[Dict]:
    """Classify one skip site by where its condition gets its answer.

    The public entry point for this rule - the report lane and the tests both ask
    the question here rather than re-deriving it.
    """
    if condition is None:
        return [
            _finding(
                unit,
                "PERMA-SKIP",
                line,
                how,
                f"{how} with no condition - this test never runs, so it proves nothing",
            )
        ]

    sources = _sources_for(condition, helpers, bindings)

    if any(_is_machine_probe(source) for source, _ in sources):
        return []

    for source, via in sources:
        probe = _existence_probe(source)
        if probe:
            through = f" (through {via})" if via else ""
            return [
                _finding(
                    unit,
                    "SKIP-ON-DRIFT",
                    line,
                    how,
                    f"{how} decides whether to run by asking {probe}(){through} whether a symbol "
                    f"still exists - renaming that symbol makes this test vanish instead of fail",
                )
            ]

    for source, via in sources:
        read = _reads_subject(source, imported)
        if read:
            through = f" (through {via})" if via else ""
            return [
                _finding(
                    unit,
                    "SELF-SKIP",
                    line,
                    how,
                    f"{how} reads '{read}' from the subject under test{through} to decide whether "
                    f"to run - the test's answer to 'should I run?' comes from the thing it tests",
                )
            ]

    return []


def unit_flags(
    unit: corpus.TestUnit,
    imported: Set[str],
    helpers: Dict[str, ast.AST],
    bindings: Dict[str, List[ast.stmt]],
) -> List[Dict]:
    """Every skip-provenance finding on one unit, decorators and body."""
    rows: List[Dict] = []
    for condition, line, how in _decorator_skip_sites(unit) + _body_skip_sites(unit):
        rows.extend(classify_site(unit, condition, line, how, imported, helpers, bindings))
    return _deduped(rows)


def find_self_skips(scanned: corpus.Corpus) -> List[Dict]:
    """Every skip whose provenance is the subject rather than the machine."""
    rows: List[Dict] = []

    for parsed in scanned.files:
        imported = _imported_names(parsed)
        helpers = _local_helpers(parsed)
        bindings = _module_bindings(parsed)

        module_unit = _module_level_unit(parsed)
        for condition, line, how in _module_skip_sites(parsed):
            rows.extend(classify_site(module_unit, condition, line, how, imported, helpers, bindings))

        for unit in parsed.units:
            rows.extend(unit_flags(unit, imported, helpers, bindings))

    return _deduped(rows)


def _deduped(rows: List[Dict]) -> List[Dict]:
    """Findings with the same (unit, line, species) collapsed to one."""
    seen: Set[tuple] = set()
    kept: List[Dict] = []
    for row in rows:
        key = (row["nodeid"], row["line"], row["species"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct scopes named by a list of findings, first-seen order.

    THE SCORE IS PER SCOPE, NOT PER FINDING. A unit carrying three self-skips is
    one place a reader has to go and look at; counting the findings would let a
    single test drive a project's score below zero, and a score that can go
    negative is one nobody believes twice.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def scope_count(scanned: corpus.Corpus) -> int:
    """How many places a skip can live: every test unit, plus every file.

    THE DENOMINATOR HAS TO INCLUDE THE FILES, and getting that wrong makes the
    score meaningless rather than merely coarse. A module-level skip belongs to
    no test function, so its finding names a scope that is not among the units;
    dividing by units alone lets the flagged count exceed the total and the
    score go NEGATIVE on a small project. Counting each file's module scope as
    a scope of its own is also the honest reading: a file-wide skip is a
    separate place where the same defect lives, and it is the expensive one.
    """
    return scanned.unit_count() + len(scanned.files)


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on where its skip conditions get their answers.

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
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scope_count(scanned)

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. An earlier version of the reference check returned "no test files
    # found" before this ran, so a project whose ONLY test file had a syntax
    # error reported exactly what a project with no tests at all reports. A
    # broken file must never read as an absent one - that is the whole contract
    # `unparseable` exists to keep, and it was defeated on the one path where
    # nothing else could catch it. The ordering here is the fix, inherited.
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
                f"no test unit could be read: {len(scanned.unparseable)} test file(s) are present "
                f"but unparseable, so nothing was measured - this is NOT a project without tests"
            )
        )
        return {
            "passed": True,
            "not_applicable": True,
            "score": 0,
            "checks": [{"name": "Skip provenance", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_self_skips(scanned)
    scopes = flagged_nodeids(flagged)
    score = int(((total - len(scopes)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Skip provenance",
            "passed": not scopes,
            "message": (
                f"{total - len(scopes)}/{total} test scopes skip on the machine or not at all"
                if not scopes
                else (
                    f"{len(scopes)}/{total} test scopes decide whether to run from the subject "
                    f"under test, or never run at all: "
                    + ", ".join(scopes[:MAX_REPORTED])
                    + (f" (+{len(scopes) - MAX_REPORTED} more)" if len(scopes) > MAX_REPORTED else "")
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
