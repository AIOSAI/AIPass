# =================== AIPass ====================
# Name: self_skip_check.py
# Description: nominator - skip-predicate provenance (SELF-SKIP, SKIP-ON-DRIFT)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
TAXONOMY rule 3 — where does a skip condition get its answer from?

A test that skips itself when the thing it tests changes name has stopped
being a test. The measured cost is not theoretical: renaming `JSON_DIR` in
@daemon made **75 tests silently vanish** and the run stayed green, and the
same shape ships fleet-wide through the seedgo branch template.

THREE PROVENANCES, AND ONLY ONE OF THEM IS A DEFECT:

  machine    `sys.platform`, `shutil.which`, `os.environ`, an optional extra
             probed with `find_spec` — legitimate, and this rule must never
             flag it. A Linux-only test skipping on Windows is correct code.
  subject    the condition asks whether a production symbol still EXISTS.
             That is SELF-SKIP: the test's answer to "should I run?" is
             derived from the very thing whose disappearance it should catch.
  nothing    an unconditional skip. PERMA-SKIP: a test that never runs is a
             test that proves nothing, whatever it asserts.

NOMINATION, NEVER CONVICTION (Law M1). A skip can be legitimately conditional
on a subject symbol — a suite that tests an optional plugin is the honest
case. The rule names the provenance and lets the execution tier decide.
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

#: The adapter group this nominator fills. Namespaced by the core.
GROUP = "static_self_skip"

#: Dotted names whose presence in a condition makes it a MACHINE probe. These
#: acquit outright: a platform or environment gate is correct code, and a rule
#: that flagged them would teach branches to delete their own portability.
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

#: Calls that ask whether a symbol still exists. The defining shape of
#: SKIP-ON-DRIFT: the test vanishes the moment the symbol is renamed.
EXISTENCE_PROBES: frozenset = frozenset({"hasattr", "getattr"})

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 3 - skip-predicate provenance",
    "species": ["SELF-SKIP", "SKIP-ON-DRIFT", "PERMA-SKIP"],
    "flags": [
        "a skip condition that asks whether a production symbol still exists (hasattr/getattr)",
        "a skip condition that reads a name imported from the subject under test",
        "an unconditional skip - the test never runs at all",
    ],
    "exempts": [
        "machine probes: sys.platform, sys.version_info, os.name, os.environ, shutil.which, find_spec",
        "a platform-divergent test that skips on the platform it cannot run on is correct code",
    ],
    "fix": (
        "make the skip condition read the MACHINE, never the SUBJECT. If the symbol's "
        "absence is the thing worth knowing, assert it instead of skipping on it."
    ),
    "limits": [
        "a suite legitimately testing an optional plugin will be nominated; that is why this "
        "tier nominates and the execution tier convicts (Law M1)",
        "a condition built at runtime from a variable is invisible to a static reader",
    ],
    "evidence": (
        "renaming JSON_DIR in @daemon made 75 tests silently vanish with the run still green "
        "(TAXONOMY corpus row 20); the SELF-SKIP shape ships fleet-wide via the branch template "
        "(corpus row 25)"
    ),
}


def _imported_names(parsed: corpus.TestFile) -> set:
    """Every name this test module binds through an import statement."""
    names = set()
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


def _reads_subject(condition: ast.AST, imported: set) -> str:
    """An imported name the condition reads, or "" if it reads none."""
    for node in ast.walk(condition):
        if isinstance(node, ast.Name) and node.id in imported:
            return node.id
        dotted = corpus.dotted_name(node)
        if dotted and dotted.split(".")[0] in imported:
            return dotted
    return ""


def _skip_sites(unit: corpus.TestUnit) -> List[tuple]:
    """Every skip in a unit as `(condition_or_None, lineno, how)`.

    A bare `pytest.skip()` reached unconditionally is recorded with a None
    condition, which is what separates PERMA-SKIP from the other two species.
    """
    sites: List[tuple] = []

    for decorator in unit.decorators:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = corpus.dotted_name(target)
        if not name.endswith("skipif") and not name.endswith(".skip") and name != "skip":
            continue
        if name.endswith("skipif") and isinstance(decorator, ast.Call) and decorator.args:
            sites.append((decorator.args[0], decorator.lineno, "@skipif"))
        elif not name.endswith("skipif"):
            sites.append((None, decorator.lineno, "@skip"))

    sites.extend(_body_skip_sites(unit))
    return sites


def _body_skip_sites(unit: corpus.TestUnit) -> List[tuple]:
    """`pytest.skip(...)` calls in the body, paired with their guarding `if`."""
    guards = {}
    for node in ast.walk(unit.node):
        if isinstance(node, ast.If):
            for statement in ast.walk(node.test):
                guards[id(statement)] = node.test
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and corpus.dotted_name(child.func).endswith("skip"):
                    guards[id(child)] = node.test

    sites: List[tuple] = []
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in ("pytest.skip", "skip"):
            sites.append((guards.get(id(node)), node.lineno, "pytest.skip()"))
    return sites


def _module_level_unit(parsed: corpus.TestFile) -> corpus.TestUnit:
    """A synthetic unit standing for the FILE, so a module-level skip has a row.

    A module-level skip belongs to no test function, and a rule that only
    walked test functions would miss the most expensive skip in the catalog.
    """
    return corpus.TestUnit(
        name="<module>",
        node=ast.FunctionDef(name="<module>", lineno=1, body=[], decorator_list=[]),  # type: ignore[call-arg]
        lineno=1,
        docstring="",
        params=[],
        decorators=[],
        class_name="",
        relpath=parsed.relpath,
    )


def _module_skip_sites(parsed: corpus.TestFile) -> List[tuple]:
    """`pytest.skip(...)` calls at module level, with their guarding `if`.

    THIS IS THE MOST EXPENSIVE SKIP IN THE CATALOG and it was missing from the
    first version of this rule, which walked test functions only. A module-level
    `pytest.skip(..., allow_module_level=True)` removes the WHOLE FILE: renaming
    `JSON_DIR` made 75 @daemon tests vanish through exactly this shape, and the
    run stayed green. Found by calibrating against TAXONOMY corpus row 20, which
    this rule had scored as clean.
    """
    guards = {}
    for node in ast.walk(parsed.tree):
        if isinstance(node, ast.If):
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and corpus.dotted_name(child.func).endswith("skip"):
                    guards.setdefault(id(child), node.test)

    inside_functions = set()
    for node in ast.walk(parsed.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                inside_functions.add(id(child))

    sites: List[tuple] = []
    for node in ast.walk(parsed.tree):
        if id(node) in inside_functions:
            continue
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in ("pytest.skip", "skip"):
            sites.append((guards.get(id(node)), node.lineno, "module-level pytest.skip()"))
    return sites


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every skip whose provenance is the subject rather than the machine."""
    rows: List[dict] = []

    for parsed in scanned.files:
        imported = _imported_names(parsed)
        helpers = _local_helpers(parsed)
        bindings = _module_bindings(parsed)
        module_unit = _module_level_unit(parsed)
        for condition, lineno, how in _module_skip_sites(parsed):
            rows.extend(_nominate_site(module_unit, condition, lineno, how, imported, helpers, bindings))
        for unit in parsed.units:
            rows.extend(_nominate_unit(unit, imported, helpers, bindings))

    return rows


def _local_helpers(parsed: corpus.TestFile) -> dict:
    """Module-level helper functions by name, for one-hop condition following."""
    return {
        node.name: node
        for node in parsed.tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("test")
    }


def _called_helpers(condition: ast.AST, helpers: dict) -> List[str]:
    """Module-local helper names this condition calls."""
    names = []
    for node in ast.walk(condition):
        if isinstance(node, ast.Call):
            name = corpus.dotted_name(node.func)
            if name in helpers:
                names.append(name)
    return names


def _module_bindings(parsed: corpus.TestFile) -> dict:
    """Module-level name -> the top-level statements that compute it.

    THE STATEMENT, NOT THE ASSIGNMENT. `_JSON_DIR_ATTR` in @daemon is set
    inside a `for` loop whose `if hasattr(_mod, _candidate):` is where the
    provenance actually lives, so binding to the assignment node alone finds
    nothing. The enclosing top-level statement is the smallest unit that
    contains the reasoning.
    """
    bindings: dict = {}

    for statement in parsed.tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(statement):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append(statement)

    return bindings


def _read_module_names(condition: ast.AST, bindings: dict) -> List[str]:
    """Module-level names this condition reads that are computed elsewhere."""
    return sorted({node.id for node in ast.walk(condition) if isinstance(node, ast.Name) and node.id in bindings})


def _nominate_unit(unit: corpus.TestUnit, imported: set, helpers: dict, bindings: dict) -> List[dict]:
    """The nominations one unit's skip sites produce."""
    rows: List[dict] = []
    for condition, lineno, how in _skip_sites(unit):
        rows.extend(_nominate_site(unit, condition, lineno, how, imported, helpers, bindings))
    return rows


def _nominate_site(
    unit: corpus.TestUnit,
    condition,
    lineno: int,
    how: str,
    imported: set,
    helpers: dict,
    bindings: dict,
) -> List[dict]:
    """Classify one skip site by where its condition gets its answer.

    ONE HOP INTO A MODULE-LOCAL HELPER, AND NO FURTHER. A skip condition is
    often written as `if not _default_factory_raises_on_unknown():` — the
    provenance is real and it is one function away. Calibration against
    TAXONOMY corpus row 25 found this rule scoring that shape as clean, which
    is why the hop exists; it stops at one because a rule that chased an
    arbitrary call graph would be an interpreter, and an interpreter that runs
    the subject is the thing Law M10 forbids.
    """
    if condition is None:
        return [
            corpus.nomination(
                "PERMA-SKIP",
                unit,
                f"{how} with no condition - this test never runs, so it proves nothing",
                line=lineno,
                evidence={"how": how},
            )
        ]

    sources = [condition]
    hopped = ""
    for name in _called_helpers(condition, helpers):
        sources.append(helpers[name])
        hopped = name
    for name in _read_module_names(condition, bindings):
        sources.extend(bindings[name])
        hopped = hopped or name

    if any(_is_machine_probe(source) for source in sources):
        return []

    for source in sources:
        probe = _existence_probe(source)
        if probe:
            through = f" (through the local helper {hopped}())" if source is not condition else ""
            return [
                corpus.nomination(
                    "SKIP-ON-DRIFT",
                    unit,
                    f"{how} decides whether to run by asking {probe}(){through} whether a symbol "
                    f"still exists - renaming that symbol makes this test vanish instead of fail",
                    verdict=corpus.VERDICT_IMPROVE,
                    line=lineno,
                    evidence={"how": how, "probe": probe, "via_helper": hopped},
                )
            ]

    for source in sources:
        read = _reads_subject(source, imported)
        if read:
            through = f" (through the local helper {hopped}())" if source is not condition else ""
            return [
                corpus.nomination(
                    "SELF-SKIP",
                    unit,
                    f"{how} reads '{read}' from the subject under test{through} to decide whether "
                    f"to run - the test's answer to 'should I run?' comes from the thing it tests",
                    verdict=corpus.VERDICT_IMPROVE,
                    line=lineno,
                    evidence={"how": how, "reads": read, "via_helper": hopped},
                )
            ]

    return []
