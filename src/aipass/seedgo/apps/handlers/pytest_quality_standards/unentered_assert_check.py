# =================== AIPass ====================
# Name: unentered_assert_check.py
# Description: v5 - assertions that may never execute (VACUOUS-GUARD, VACUOUS-LOOP)
# Version: 1.1.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Does this test's assertion ever actually run?

Reference: unentered_assert.md"""

import ast
from pathlib import Path
from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "unentered_assert"

#: Tried in order; a project matching none of them gets a whole-tree walk.
TEST_DIRS: tuple = corpus.TEST_DIRS

#: Inside an assert before a loop, these prove the loop body runs (`assert len(rows) == 3`).
FLOOR_CALLS: frozenset = frozenset({"len", "sorted", "list", "tuple", "set"})

#: The full list rides in `violations`.
MAX_REPORTED: int = 12


def _asserts_anywhere_in(statements: List[ast.stmt]) -> bool:
    """True when any statement in the list holds an assert at any depth."""
    return any(isinstance(child, ast.Assert) for statement in statements for child in ast.walk(statement))


def _unconditional_statements(body: List[ast.stmt]) -> List[ast.stmt]:
    """Every statement reached without taking a branch or entering a loop.

    `with` and `try` bodies count, since neither decides anything; `if` and `for` bodies do not."""
    reached: List[ast.stmt] = []
    for statement in body:
        reached.append(statement)
        if isinstance(statement, (ast.With, ast.AsyncWith, ast.Try)):
            reached.extend(_unconditional_statements(statement.body))
    return reached


def asserts_on_a_path_that_always_runs(unit: corpus.TestUnit) -> bool:
    """True when the unit asserts somewhere that cannot be skipped.

    The exemption's public entry point: a unit answering True is never flagged."""
    return any(isinstance(statement, ast.Assert) for statement in _unconditional_statements(unit.node.body))


def guarding_if(unit: corpus.TestUnit) -> Optional[ast.If]:
    """The first one-sided `if` holding an assertion, or None.

    A two-sided `if/else` is skipped here, not excused later, so no caller can drop the exemption."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.If):
            continue
        if not _asserts_anywhere_in([node]):
            continue
        if node.orelse and _asserts_anywhere_in(node.orelse):
            continue
        return node
    return None


def _non_empty_literal(node: Optional[ast.expr]) -> bool:
    """True for a list, tuple, set or dict literal holding at least one element."""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return bool(node.elts)
    if isinstance(node, ast.Dict):
        return bool(node.keys)
    return False


def _names_bound_by(statement: ast.stmt) -> List[tuple]:
    """(name, value) for each name one statement binds; value None for an import or def."""
    if isinstance(statement, ast.Assign):
        return [(target.id, statement.value) for target in statement.targets if isinstance(target, ast.Name)]
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return [(statement.target.id, statement.value)]
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return [((alias.asname or alias.name).split(".")[0], None) for alias in statement.names]
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [(statement.name, None)]
    return []


def _bound_once(statements: List[ast.stmt]) -> Dict[str, Optional[ast.expr]]:
    """Names bound exactly once among these statements, to the value assigned (None for an import or def)."""
    counts: Dict[str, int] = {}
    values: Dict[str, Optional[ast.expr]] = {}
    for statement in statements:
        for name, value in _names_bound_by(statement):
            counts[name] = counts.get(name, 0) + 1
            values[name] = value
    return {name: values[name] for name, count in counts.items() if count == 1}


def _local_literal(unit: corpus.TestUnit, name: str, loop: ast.For) -> Optional[bool]:
    """Whether a name the unit binds itself is a non-empty literal; None when the unit never binds it.

    The one binding must precede the loop in the unit's own body; a parameter or a second binding is not read."""
    arguments = unit.node.args
    parameters = {arg.arg for arg in arguments.posonlyargs + arguments.args + arguments.kwonlyargs}
    stores = [
        node
        for node in ast.walk(unit.node)
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store)
    ]
    if name in parameters:
        return False
    if not stores:
        return None
    if len(stores) != 1:
        return False
    before = [statement for statement in unit.node.body if statement.lineno < loop.lineno]
    return _non_empty_literal(_bound_once(before).get(name))


def _iterates_a_literal_table(unit: corpus.TestUnit, loop: ast.For, test_file: Optional[corpus.TestFile]) -> bool:
    """True when the loop iterates a name bound once to a non-empty literal.

    ``NAME`` is read in the unit's body then at module level, ``self.NAME`` in its class body."""
    target = loop.iter
    if isinstance(target, ast.Name):
        local = _local_literal(unit, target.id, loop)
        if local is not None:
            return local
        if test_file is None:
            return False
        return _non_empty_literal(_bound_once(test_file.tree.body).get(target.id))
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
        if test_file is None:
            return False
        for node in test_file.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == unit.class_name:
                return _non_empty_literal(_bound_once(node.body).get(target.attr))
    return False


def has_floor(unit: corpus.TestUnit, loop: ast.For, test_file: Optional[corpus.TestFile] = None) -> bool:
    """True when something proves this loop's iterable is non-empty.

    A literal (at the loop or behind a name bound once), or a prior assert on the iterable's size or truth."""
    if isinstance(loop.iter, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return True
    if _iterates_a_literal_table(unit, loop, test_file):
        return True

    for statement in _unconditional_statements(unit.node.body):
        if not isinstance(statement, ast.Assert) or statement.lineno >= loop.lineno:
            continue
        for node in ast.walk(statement.test):
            if isinstance(node, ast.Call) and corpus.dotted_name(node.func) in FLOOR_CALLS:
                return True
        if isinstance(statement.test, (ast.Name, ast.Attribute, ast.Compare)):
            return True

    return False


def vacuous_loop(unit: corpus.TestUnit, test_file: Optional[corpus.TestFile] = None) -> Optional[ast.For]:
    """The first floorless `for` holding an assertion, or None."""
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.For):
            continue
        if not _asserts_anywhere_in([node]):
            continue
        if has_floor(unit, node, test_file):
            continue
        return node
    return None


def find_unentered(scanned: corpus.Corpus) -> List[Dict]:
    """Every unit whose assertions all sit behind something that may not run.

    ONE ROW PER UNIT: counting both shapes would push flagged past total and the score below zero."""
    rows: List[Dict] = []

    for test_file in scanned.files:
        rows.extend(_unentered_in(test_file))

    return rows


def _unentered_in(test_file: corpus.TestFile) -> List[Dict]:
    """The rows of one file's units, the file handed on so a loop's table can be read."""
    rows: List[Dict] = []

    for unit in test_file.units:
        if not corpus.asserts_in(unit) or asserts_on_a_path_that_always_runs(unit):
            continue

        guard = guarding_if(unit)
        if guard is not None:
            rows.append(
                {
                    "nodeid": unit.nodeid,
                    "line": unit.line,
                    "species": "VACUOUS-GUARD",
                    "branch_line": guard.lineno,
                    "assert_count": len(corpus.asserts_in(unit)),
                    "detail": (
                        "every assertion in this unit sits under an `if` with no asserting `else` - "
                        "when the guard is false the test passes having checked nothing, and the run "
                        "says nothing about which happened"
                    ),
                }
            )
            continue

        loop = vacuous_loop(unit, test_file)
        if loop is not None:
            rows.append(
                {
                    "nodeid": unit.nodeid,
                    "line": unit.line,
                    "species": "VACUOUS-LOOP",
                    "branch_line": loop.lineno,
                    "assert_count": len(corpus.asserts_in(unit)),
                    "detail": (
                        "every assertion in this unit sits inside a `for` with nothing proving the "
                        "iterable is non-empty - an empty iterable makes this a silent pass"
                    ),
                }
            )

    return rows


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its assertions can be reached.

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
            "checks": [{"name": "Assertion reachability", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unentered(scanned)
    score = int(((total - len(flagged)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Assertion reachability",
            "passed": not flagged,
            "message": (
                f"{total - len(flagged)}/{total} test units assert on a path that always runs"
                if not flagged
                else (
                    f"{len(flagged)}/{total} test units assert only behind a branch that may never be "
                    "entered: "
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
