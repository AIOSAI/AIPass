# =================== AIPass ====================
# Name: empty_parametrize_check.py
# Description: v5 - a parametrize table that can vanish at collection time
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""A parametrized test over an empty table reports as passing.

Reference: empty_parametrize.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus

AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "empty_parametrize"

TEST_DIRS: tuple = corpus.TEST_DIRS

#: Builtins that return something non-empty when handed something non-empty.
SAFE_BUILTINS: frozenset = frozenset({"range", "sorted", "list", "tuple", "reversed", "enumerate", "set"})

PARAMETRIZE_NAME: str = "parametrize"

EVIDENCE_CHARS: int = 120

#: The full list lives in the report artifact; the check message names only these.
MAX_REPORTED: int = 12


def _module_literal_names(parsed: corpus.TestFile) -> Set[str]:
    """Module-level names bound to a non-empty literal container.

    Class-body constants are not read: a measured false positive (see empty_parametrize.md).
    """
    safe: Set[str] = set()
    for node in parsed.tree.body:
        if isinstance(node, ast.Assign):
            targets: List[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and value.elts:
            safe.update(t.id for t in targets if isinstance(t, ast.Name))
        elif isinstance(value, ast.Dict) and value.keys:
            safe.update(t.id for t in targets if isinstance(t, ast.Name))
    return safe


def _cannot_be_empty(value: ast.expr, safe_names: Set[str]) -> bool:
    """True when this argvalues expression is non-empty by construction.

    Unwraps ONE safe-builtin layer only; following a chain would make this an interpreter.
    """
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        return bool(value.elts)
    if isinstance(value, ast.Dict):
        return bool(value.keys)
    if isinstance(value, ast.Constant):
        return bool(value.value)
    if isinstance(value, ast.Name):
        return value.id in safe_names
    if isinstance(value, ast.Call):
        name = corpus.dotted_name(value.func).rsplit(".", 1)[-1]
        if name not in SAFE_BUILTINS or not value.args:
            return False
        return _cannot_be_empty(value.args[0], safe_names)
    return False


def _has_independent_nonempty_guard(parsed: corpus.TestFile) -> bool:
    """True when some assertion in this file measures a length at all.

    Matched file-wide, not per table: a deliberate error toward acquitting.
    """
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Call) and corpus.dotted_name(sub.func).rsplit(".", 1)[-1] == "len":
                return True
    return False


def _guard_pins_a_count(parsed: corpus.TestFile) -> bool:
    """True when some assertion compares a length against an expected value.

    `len(x) == 0` is excluded: that is an emptiness assertion, not a count.
    """
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if not isinstance(sub, ast.Compare):
                continue
            if not (isinstance(sub.left, ast.Call) and corpus.dotted_name(sub.left.func).rsplit(".", 1)[-1] == "len"):
                continue
            for op, comparator in zip(sub.ops, sub.comparators):
                if not isinstance(op, ast.Eq):
                    continue
                if isinstance(comparator, ast.Constant) and comparator.value == 0:
                    continue
                return True
    return False


def _parametrize_tables(unit: corpus.TestUnit) -> List[Tuple[ast.expr, int]]:
    """Every `parametrize` decorator on a unit as (argvalues, lineno)."""
    tables: List[Tuple[ast.expr, int]] = []
    for decorator in unit.node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if corpus.dotted_name(decorator.func).rsplit(".", 1)[-1] != PARAMETRIZE_NAME:
            continue
        if len(decorator.args) < 2:
            continue
        tables.append((decorator.args[1], decorator.lineno))
    return tables


def _finding(species: str, unit: corpus.TestUnit, line: int, reason: str, argvalues: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {
        "nodeid": unit.nodeid,
        "line": line,
        "species": species,
        "reason": reason,
        "argvalues": argvalues[:EVIDENCE_CHARS],
    }


def file_flags(parsed: corpus.TestFile) -> List[Dict]:
    """Every vanishing-table finding in one file, with the evidence for each.

    Takes a FILE, not a unit: both acquittals (guard, module constants) are file-scoped.
    """
    guarded = _has_independent_nonempty_guard(parsed)
    counted = _guard_pins_a_count(parsed)
    if guarded and counted:
        return []

    safe_names = _module_literal_names(parsed)
    rows: List[Dict] = []
    for unit in parsed.units:
        for argvalues, lineno in _parametrize_tables(unit):
            if _cannot_be_empty(argvalues, safe_names):
                continue
            quoted = ast.unparse(argvalues)
            if guarded:
                rows.append(
                    _finding(
                        "SHORT-TABLE",
                        unit,
                        lineno,
                        f"parametrize table computed at collection time ({quoted[:60]}) - the file's guard "
                        f"asserts the collection is NON-EMPTY, which a collector that drops one entry still "
                        f"satisfies; pin the expected COUNT from raw data",
                        quoted,
                    )
                )
                continue
            rows.append(
                _finding(
                    "VANISHING-TABLE",
                    unit,
                    lineno,
                    f"parametrize table computed at collection time ({quoted[:60]}) - an empty result is "
                    f"reported as SKIPPED and the suite summary reads green",
                    quoted,
                )
            )
    return rows


def find_vanishing_tables(scanned: corpus.Corpus) -> List[Dict]:
    """Every parametrize table that could vanish without the suite noticing."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        rows.extend(file_flags(parsed))
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    The score is per unit: counting findings could push the score negative.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its parametrize tables can vanish.

    bypass_rules is accepted for the scoring-API contract and unread: advisory gates nothing.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # Built before the empty-path return: a project whose only test file is
    # unparseable must never read as a project with no tests.
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
            "checks": [{"name": "Parametrize table", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_vanishing_tables(scanned)
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Parametrize table",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units carry no parametrize table that could vanish"
                if not units
                else (
                    f"{len(units)}/{total} test units parametrize over a table computed at collection time: "
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
