# =================== AIPass ====================
# Name: no_oracle_check.py
# Description: v5 - does a test verify anything at all
# Version: 1.1.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Does this test verify anything a reader can see?

Reference: no_oracle.md"""

import ast
from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "no_oracle"

#: Tried in order; a project matching none of them gets a whole-tree walk.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Flagging a delegating helper call would teach projects to inline their helpers.
DELEGATING_PREFIXES: tuple = ("assert", "_assert", "check", "_check", "verify", "_verify", "expect", "_expect")

#: The full list lives in the report artifact.
MAX_REPORTED: int = 12


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

    The rule's public entry point: the report lane and the tests ask here.
    ``oracle_helpers`` are same-file helper spellings (``name``/``self.name``) whose body holds an oracle."""
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

    Module functions by name, own-class methods through ``self``; same file only."""
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


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests verify anything.

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
