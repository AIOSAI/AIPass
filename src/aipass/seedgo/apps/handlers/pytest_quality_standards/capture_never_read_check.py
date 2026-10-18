# =================== AIPass ====================
# Name: capture_never_read_check.py
# Description: v5 - did the test read the output it arranged to capture
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Did this test look at the output it asked for?

Reference: capture_never_read.md
"""

import ast
from pathlib import Path
from typing import Dict, List, Set

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


AUDIT_SCOPE = "branch_level"

STANDARD_NAME = "capture_never_read"

TEST_DIRS: tuple = corpus.TEST_DIRS

CAPTURE_FIXTURES: frozenset = frozenset({"capsys", "capfd", "capsysbinary", "capfdbinary"})

READ_METHOD: str = "readouterr"

OUTPUT_PREFIXES: tuple = ("print_", "show_", "report_", "render_", "display_", "emit_")

#: `False` and `1` match these by equality, on purpose (see capture_never_read.md).
RECEIPT_CONSTANTS: tuple = (True, 0)

#: The full list lives in the report artifact; the check message stays readable.
MAX_REPORTED: int = 12


def _requested_fixtures(unit: corpus.TestUnit) -> List[str]:
    """The capture fixtures this unit's signature asks pytest for.

    Positional parameters only; no `self` filter, the intersection already excludes it.
    """
    return sorted({arg.arg for arg in unit.node.args.args} & CAPTURE_FIXTURES)


def _reads_capture(unit: corpus.TestUnit) -> bool:
    """True when the unit reads its capture anywhere in its body.

    The attribute arm decides (it also sees `read = capsys.readouterr` passed on);
    the call arm is kept so the rule does not rest on `ast.walk` ordering alone.
    """
    for node in ast.walk(unit.node):
        if isinstance(node, ast.Call) and corpus.dotted_name(node.func).endswith(READ_METHOD):
            return True
        if isinstance(node, ast.Attribute) and node.attr == READ_METHOD:
            return True
    return False


def capture_readers(tree: ast.Module) -> Dict[str, Set[int]]:
    """Which same-file helpers read a capture, and out of which parameter.

    Module-level defs of ONE file, to a fixed point; keyed by parameter position.
    Terminates: the candidate set is fixed and each pass only adds, so recursion is harmless.
    """
    defs = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    readers: Dict[str, Set[int]] = {}
    for name, node in defs.items():
        positions = {index for index, arg in enumerate(node.args.args) if _reads_name(node, arg.arg)}
        if positions:
            readers[name] = positions

    changed = True
    while changed:
        changed = False
        for name, node in defs.items():
            known = readers.get(name, set())
            forwarded = {
                index
                for index, arg in enumerate(node.args.args)
                if index not in known and _forwards_name(node, arg.arg, readers)
            }
            if forwarded:
                readers[name] = known | forwarded
                changed = True
    return readers


def _forwards_name(node: ast.AST, name: str, readers: Dict[str, Set[int]]) -> bool:
    """True when this body hands `name` to a helper that reads what it is given."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Name):
            continue
        for index in readers.get(child.func.id, set()):
            if index < len(child.args):
                argument = child.args[index]
                if isinstance(argument, ast.Name) and argument.id == name:
                    return True
    return False


def _reads_name(node: ast.AST, name: str) -> bool:
    """True when this body calls `<name>.readouterr()` somewhere inside it."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute) or child.attr != READ_METHOD:
            continue
        if isinstance(child.value, ast.Name) and child.value.id == name:
            return True
    return False


def _delegated_reader(unit: corpus.TestUnit, requested: List[str], readers: Dict[str, Set[int]]) -> str:
    """The same-file helper this unit handed its capture to, or ""."""
    wanted = set(requested)
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        positions = readers.get(node.func.id)
        if not positions:
            continue
        for index in positions:
            if index < len(node.args):
                argument = node.args[index]
                if isinstance(argument, ast.Name) and argument.id in wanted:
                    return node.func.id
    return ""


def _receipt_callee(node: ast.Assert) -> str:
    """The output function this assert takes a receipt from, or ""."""
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return ""
    if not isinstance(test.ops[0], (ast.Is, ast.Eq)):
        return ""

    comparator = test.comparators[0]
    if not isinstance(comparator, ast.Constant) or comparator.value not in RECEIPT_CONSTANTS:
        return ""

    if not isinstance(test.left, ast.Call):
        return ""

    name = corpus.dotted_name(test.left.func)
    tail = name.rsplit(".", 1)[-1]
    return name if tail.startswith(OUTPUT_PREFIXES) else ""


def _receipt_finding(unit: corpus.TestUnit) -> Dict:
    """A RECEIPT-ONLY finding for this unit, or {} when the receipt has company."""
    asserts = corpus.asserts_in(unit)
    if len(asserts) != 1:
        return {}
    if corpus.oracle_calls_in(unit):
        return {}

    callee = _receipt_callee(asserts[0])
    if not callee:
        return {}

    return _finding(
        "RECEIPT-ONLY",
        unit,
        asserts[0].lineno,
        f"the unit's only assertion takes a receipt from '{callee}', whose real work is what it emits - "
        f"the return value says the call happened, not that it printed anything right",
    )


def _finding(species: str, unit: corpus.TestUnit, line: int, reason: str) -> Dict:
    """One finding row. Flat and stringy so any reporter can render it."""
    return {"nodeid": unit.nodeid, "line": line, "species": species, "reason": reason}


def unit_flags(unit: corpus.TestUnit, readers: Dict[str, Set[int]] | None = None) -> List[Dict]:
    """Every capture-never-read finding in one unit, with its evidence.

    A unit that captured without reading is not also judged for a receipt.
    `readers` omitted means no same-file reader: it can only add findings, never acquit.
    """
    requested = _requested_fixtures(unit)
    if requested and not _reads_capture(unit) and not _delegated_reader(unit, requested, readers or {}):
        return [
            _finding(
                "CAPTURE-NEVER-READ",
                unit,
                unit.line,
                f"requests {', '.join(requested)} and never calls {READ_METHOD}() - the unit arranged "
                f"to see the output and then did not look at it",
            )
        ]

    receipt = _receipt_finding(unit)
    return [receipt] if receipt else []


def find_unread_captures(scanned: corpus.Corpus) -> List[Dict]:
    """Every capture-never-read finding in the corpus, unit order preserved."""
    rows: List[Dict] = []
    for parsed in scanned.files:
        readers = capture_readers(parsed.tree)
        for unit in parsed.units:
            rows.extend(unit_flags(unit, readers))
    return rows


def flagged_nodeids(rows: List[Dict]) -> List[str]:
    """The distinct units named by a list of findings, first-seen order.

    Per unit, not per row, so the flagged total can never exceed the unit total.
    """
    seen: List[str] = []
    for row in rows:
        if row["nodeid"] not in seen:
            seen.append(row["nodeid"])
    return seen


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Score a project on whether its tests read the output they capture.

    bypass_rules is accepted for the scoring-API contract and unread: shadow mode gates nothing.
    """
    root = Path(branch_path)
    scanned = corpus.build(root, test_dirs=TEST_DIRS)
    total = scanned.unit_count()

    # Built before the empty-corpus return: an unparseable-only project must not read as one without tests.
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
            "checks": [{"name": "Capture read", "passed": True, "message": measured}] + unreadable,
            "standard": STANDARD_NAME.upper(),
            "advisory": True,
        }

    flagged = find_unread_captures(scanned)
    units = flagged_nodeids(flagged)
    score = int(((total - len(units)) / total) * 100)
    checks: List[Dict] = [
        {
            "name": "Capture read",
            "passed": not units,
            "message": (
                f"{total - len(units)}/{total} test units read the output they asked for"
                if not units
                else (
                    f"{len(units)}/{total} test units never look at the output they asked for: "
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
