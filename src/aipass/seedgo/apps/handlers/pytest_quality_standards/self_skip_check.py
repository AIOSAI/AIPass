# =================== AIPass ====================
# Name: self_skip_check.py
# Description: v5 - where does a skip condition get its answer from
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Where does this test's skip condition get its answer from?

Reference: self_skip.md"""

import ast
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "self_skip"

#: Tried in order; a project matching none of them gets a whole-tree walk.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Dotted or bare tail both match: `from shutil import which` writes the same probe shorter.
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

EXISTENCE_PROBES: frozenset = frozenset({"hasattr", "getattr"})

#: Body and module-level calls only; decorators match by suffix (`pytest.mark.skip`, `skipif`).
SKIP_CALL_NAMES: tuple = ("pytest.skip", "skip")

#: The full list lives in the report artifact.
MAX_REPORTED: int = 12

#: Parsed, not hand-built, so no `FunctionDef` field has to track interpreter versions.
_STAND_IN_SOURCE: str = "def _module_scope():\n    pass"


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

    The enclosing top-level statement, not the assignment: the `hasattr` often sits in a `for` around it."""
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

    No enclosing `if` gives a None condition; `skipped` ids belong to a function's own row."""
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

    A module-level skip removes the WHOLE FILE, so the file gets a row of its own."""
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


def _sources_for(
    condition: ast.AST,
    helpers: Dict[str, ast.AST],
    bindings: Dict[str, List[ast.stmt]],
) -> List[Tuple[ast.AST, str]]:
    """The condition and the one-hop places its answer can come from.

    Each source carries where it came from, so the message names the one that carried the answer."""
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

    The rule's public entry point: the report lane and the tests ask here."""
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

    THE SCORE IS PER SCOPE, NOT PER FINDING, so one test cannot drive the score below zero."""
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def scope_count(scanned: corpus.Corpus) -> int:
    """How many places a skip can live: every test unit, plus every file.

    The files count: a module-level skip names no unit, and dividing by units alone can go negative."""
    return scanned.unit_count() + len(scanned.files)


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on where its skip conditions get their answers.

    ``bypass_rules`` is accepted for the scoring-API contract and not read: shadow mode gates nothing.
    No tests reports not_applicable: zero tests measured is not zero quality found."""
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scope_count(scanned)

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
