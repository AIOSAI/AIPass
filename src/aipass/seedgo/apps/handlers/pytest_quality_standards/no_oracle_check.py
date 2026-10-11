# =================== AIPass ====================
# Name: no_oracle_check.py
# Description: v5 - does a test verify anything at all
# Version: 1.1.0
# Created: 2026-09-01
# Modified: 2026-10-06
# =============================================

"""Does this test verify anything a reader can see?

THE FIRST V5 CHECK, AND THE PACK'S REFERENCE PORT. Ten more nominators follow
it in phase 2; this one establishes the shape they copy - scoring API, advisory
result, evidence attached to every flag, stdlib only.

WHAT IT REPLACES. v4 scored a branch by searching its test files for 99 pattern
substrings. The match was a bare `in` over raw source, so comments and docstrings
counted, and a file of pattern strings with no code at all scored 94 percent. It
also could not be opted out of: the raw percentage entered the branch average and
CI gates that average at 100, so every branch was pushed to 51 of 51 items. That
is why `importlib.reload` appears in eighteen of eighteen branches - not drift,
compliance. This check reads the AST instead, and asks the only question v4 never
asked: is there an oracle.

WHAT COUNTS AS AN ORACLE IS DELIBERATELY GENEROUS. An `assert`, a `pytest.raises`
or `warns` or `fail` or `approx`, any `assert_*` method (unittest and mock), or a
call to a locally named checking helper. Being generous is the right direction to
be wrong in: a false flag costs a reader thirty seconds, and this tier is advisory
either way.

IT NOMINATES, IT DOES NOT CONVICT. A bare trailing call CAN be a working oracle -
`parse(bad_input)` with no assert really does fail when `parse` starts accepting
bad input. That is a weak oracle, not an absent one, and static analysis cannot
tell them apart from the outside. So this file never says a test is worthless. It
says: no oracle is visible here, and here is what the test calls.
"""

import ast
from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

# =============================================================================
# CONFIGURATION
# =============================================================================

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "no_oracle"

#: Directories a project keeps tests in. Tried in order; a project matching
#: none of them gets a whole-tree walk, which is what an unknown target needs.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Helper-name prefixes that mean the unit delegates its checking. A unit calling
#: `_assert_document_is_lawful(...)` has an oracle one hop away, and flagging it
#: would teach projects to inline their helpers to please the checker - the exact
#: behaviour v4 produced.
DELEGATING_PREFIXES: tuple = ("assert", "_assert", "check", "_check", "verify", "_verify", "expect", "_expect")

#: How many flagged units to name in the result. The full list lives in the
#: report artifact; a check message that prints hundreds of lines is unreadable.
MAX_REPORTED: int = 12


# =============================================================================
# ANALYSIS
# =============================================================================


def _delegates(unit: corpus.TestUnit) -> str:
    """A checking-helper call this unit makes, or "" when it makes none."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call):
            continue
        name = corpus.dotted_name(node.func)
        if name and name.rsplit(".", 1)[-1].startswith(DELEGATING_PREFIXES):
            return name
    return ""


def _calls_made(unit: corpus.TestUnit) -> List[str]:
    """Every call the unit makes, so a nomination can show its work."""
    names = set()
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call):
            name = corpus.dotted_name(node.func)
            if name:
                names.add(name)
    return sorted(names)


def has_oracle(unit: corpus.TestUnit, oracle_helpers: frozenset = frozenset()) -> bool:
    """True when the unit verifies something a reader can see.

    The public entry point for this rule - the report lane and the tests both
    ask the question here rather than re-deriving it. ``oracle_helpers`` are
    the call spellings (``name`` or ``self.name``) of the unit's own module
    functions and class methods whose body holds an oracle; a call to one is
    the unit's oracle (seedgo, fleet green leg 20).
    """
    if corpus.asserts_in(unit) or corpus.oracle_calls_in(unit) or _delegates(unit):
        return True
    return any(
        isinstance(node, ast.Call) and corpus.dotted_name(node.func) in oracle_helpers for node in ast.walk(unit.node)
    )


def _helper_has_oracle(node: ast.FunctionDef | ast.AsyncFunctionDef, relpath: str) -> bool:
    """Whether a helper's own body holds an oracle: one level, never what it calls in turn."""
    return has_oracle(corpus.TestUnit(name=node.name, node=node, relpath=relpath, line=node.lineno))


def _oracle_helpers(test_file: corpus.TestFile) -> Dict[str, frozenset]:
    """Per class name ("" for module level), the helper call spellings that hold an oracle.

    A module function is called by its name, a method of the unit's own class
    through ``self``; both are read in the same file only.
    """
    module_level = frozenset(
        node.name
        for node in test_file.tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _helper_has_oracle(node, test_file.relpath)
    )
    helpers: Dict[str, frozenset] = {"": module_level}
    for node in test_file.tree.body:
        if isinstance(node, ast.ClassDef):
            methods = frozenset(
                f"self.{sub.name}"
                for sub in node.body
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _helper_has_oracle(sub, test_file.relpath)
            )
            helpers[node.name] = module_level | methods
    return helpers


def find_unoracled(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit with no visible oracle, with the evidence for each."""
    rows: List[Dict] = []
    for test_file in scanned.files:
        helpers = _oracle_helpers(test_file)
        rows.extend(_unoracled_in(test_file, helpers))
    return rows


def _unoracled_in(test_file: corpus.TestFile, helpers: Dict[str, frozenset]) -> List[Dict]:
    """The rows of one file's units that have no visible oracle."""
    rows: List[Dict] = []
    for unit in test_file.units:
        if has_oracle(unit, helpers.get(unit.class_name, helpers[""])):
            continue
        calls = _calls_made(unit)
        rows.append(
            {
                "nodeid": unit.nodeid,
                "line": unit.line,
                "calls": calls[:MAX_REPORTED],
                "call_count": len(calls),
            }
        )
    return rows


# =============================================================================
# BRANCH-LEVEL CHECK
# =============================================================================


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests verify anything.

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
    total = scanned.unit_count()

    # THE UNREADABLE-FILE LINE IS BUILT FIRST, BECAUSE THE EMPTY PATH NEEDS IT
    # MOST. An earlier version returned "no test files found" before this ran,
    # so a project whose ONLY test file had a syntax error reported exactly what
    # a project with no tests at all reports. A broken file must never read as an
    # absent one - that is the whole contract `unparseable` exists to keep, and
    # it was defeated on the one path where nothing else could catch it.
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
            "checks": [{"name": "Oracle presence", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unoracled(scanned)
    score = int(((total - len(flagged)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Oracle presence",
            "passed": not flagged,
            "message": (
                f"{total - len(flagged)}/{total} test units have a visible oracle"
                if not flagged
                else (
                    f"{len(flagged)}/{total} test units have no visible oracle: "
                    + ", ".join(r["nodeid"] for r in flagged[:MAX_REPORTED])
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
