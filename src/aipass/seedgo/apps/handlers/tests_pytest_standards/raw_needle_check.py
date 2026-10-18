# =================== AIPass ====================
# Name: raw_needle_check.py
# Description: nominator - a raw needle matched against output the same test normalises (WIDTH-FRAGILE-ASSERT)
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-10-17
# =============================================

"""A raw substring matched against captured console output, in a test that
ELSEWHERE normalises the SAME output for exactly this reason.

Reference: raw_needle.md
"""

import ast
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_raw_needle"

#: pytest's capture fixtures. A haystack is only "console output" when it came
#: from one of these - a needle matched against file bytes does not wrap.
CAPTURE_FIXTURES: frozenset = frozenset({"capsys", "capfd", "capsysbinary", "capfdbinary"})

CAPTURE_READER = "readouterr"

CAPTURE_STREAMS: frozenset = frozenset({"out", "err"})

#: They return a number or a type, so ``len(out) > 0`` is not the author normalising ``out``.
NON_NORMALISING_CALLS: frozenset = frozenset(
    {"len", "bool", "int", "float", "id", "type", "hash", "isinstance", "print", "getattr", "hasattr"}
)

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 9 - a needle matched against output the same test normalises",
    "species": ["WIDTH-FRAGILE-ASSERT"],
    "flags": [
        "a string literal matched with `in`/`not in` against captured console output that is "
        "NOT normalised, in a test that normalises that same output in another comparison",
    ],
    "exempts": [
        "a test that never normalises anything - matching raw console output is ordinary and correct",
        "a haystack that is not a pytest capture read; file bytes and return values do not wrap",
        "the normalising comparison itself, whose two sides are both put through the same call",
        "a wrapper that returns a number rather than text: len, bool, int, float, type, id",
    ],
    "fix": (
        "put BOTH sides of the raw assertion through the same normalising call the test "
        "already uses, or state the width the suite requires and pin it - a test whose "
        "colour depends on an unstated column count is measuring the terminal, not the code."
    ),
    "limits": [
        "a needle with no spaces may be genuinely wrap-proof and is still nominated; that is "
        "why this tier nominates and the execution tier convicts (Law M1)",
        "the normalising call is matched by SHAPE, not by reading what it does - a helper that "
        "takes the haystack and returns something unrelated would read as normalisation here",
        "a haystack laundered through more than one intermediate name is invisible to a static "
        "reader, which biases this rule toward FEWER nominations",
    ],
    "evidence": (
        "on the canary fixture, COLUMNS=40-41 produces 18 failures and COLUMNS=42 produces nine, "
        "while COLUMNS>=43 passes all 34 - and the suite names no column count anywhere"
    ),
}


def _key(node: ast.AST) -> str:
    """A stable source-text key for an expression, or "" when it has none.

    An expression that will not unparse is reported, never skipped (Law S1).
    """
    try:
        return ast.unparse(node)
    except (ValueError, AttributeError, RecursionError) as exc:
        logger.warning(f"[AUDIT-TESTS] raw_needle could not read an expression, so it cleared nothing there: {exc}")
        return ""


def _is_capture_read(node: ast.AST) -> bool:
    """True for `<capture>.readouterr().out` / `.err` and nothing else."""
    if not isinstance(node, ast.Attribute) or node.attr not in CAPTURE_STREAMS:
        return False
    return _is_capture_drain(node.value)


def _is_capture_drain(node: ast.AST) -> bool:
    """True for the `<capture>.readouterr()` call itself."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != CAPTURE_READER:
        return False
    return isinstance(func.value, ast.Name) and func.value.id in CAPTURE_FIXTURES


def _capture_keys(unit: corpus.TestUnit) -> Set[str]:
    """Every expression in a unit that holds captured console output.

    One hop, deliberately: a name bound from a name is not followed (toward fewer nominations).
    """
    keys: Set[str] = set()

    for node in ast.walk(unit.node):
        if _is_capture_read(node) and (key := _key(node)):
            keys.add(key)
        if isinstance(node, ast.Assign):
            keys.update(_bound_capture_names(node))

    return keys


def _bound_capture_names(node: ast.Assign) -> Set[str]:
    """Local names one assignment binds to captured console output."""
    if _is_capture_read(node.value):
        return {target.id for target in node.targets if isinstance(target, ast.Name)}
    if not _is_capture_drain(node.value):
        return set()
    names: Set[str] = set()
    for target in node.targets:
        if isinstance(target, (ast.Tuple, ast.List)):
            names.update(element.id for element in target.elts if isinstance(element, ast.Name))
    return names


def _comparisons_in(unit: corpus.TestUnit) -> List[ast.Compare]:
    """Every comparison inside a unit, assertion or not."""
    return [node for node in ast.walk(unit.node) if isinstance(node, ast.Compare)]


def _raw_needles(unit: corpus.TestUnit, capture: Set[str]) -> List[Tuple[str, str, int, ast.Compare]]:
    """Literal-in-captured-output tests, un-normalised."""
    found: List[Tuple[str, str, int, ast.Compare]] = []

    for node in _comparisons_in(unit):
        if not isinstance(node.left, ast.Constant) or not isinstance(node.left.value, str):
            continue
        for operator, comparator in zip(node.ops, node.comparators):
            if not isinstance(operator, (ast.In, ast.NotIn)):
                continue
            key = _key(comparator)
            if key in capture:
                found.append((node.left.value, key, node.lineno, node))

    return found


def _normalisers(unit: corpus.TestUnit, capture: Set[str]) -> Dict[str, List[Tuple[str, int, int]]]:
    """Every comparison that puts a captured haystack THROUGH a call."""
    found: Dict[str, List[Tuple[str, int, int]]] = {}

    for comparison in _comparisons_in(unit):
        for call in [node for node in ast.walk(comparison) if isinstance(node, ast.Call)]:
            name = corpus.dotted_name(call.func)
            if not name or name.rsplit(".", 1)[-1] in NON_NORMALISING_CALLS:
                continue
            for argument in call.args:
                key = _key(argument)
                if key in capture:
                    found.setdefault(key, []).append((name, call.lineno, id(comparison)))

    return found


def _nominate_unit(unit: corpus.TestUnit) -> List[dict]:
    """The nominations one unit's assertions produce."""
    capture = _capture_keys(unit)
    if not capture:
        return []

    normalisers = _normalisers(unit, capture)
    if not normalisers:
        return []

    rows: List[dict] = []
    for needle, haystack, lineno, comparison in _raw_needles(unit, capture):
        elsewhere = [entry for entry in normalisers.get(haystack, []) if entry[2] != id(comparison)]
        if not elsewhere:
            continue
        call_name, call_line, _ = elsewhere[0]
        rows.append(_row(unit, needle, haystack, lineno, call_name, call_line))

    return rows


def _row(unit: corpus.TestUnit, needle: str, haystack: str, lineno: int, call_name: str, call_line: int) -> dict:
    """One WIDTH-FRAGILE-ASSERT nomination, carrying both halves of the pair."""
    return corpus.nomination(
        "WIDTH-FRAGILE-ASSERT",
        unit,
        f"line {lineno} matches the raw literal {needle!r} against un-normalised captured output "
        f"'{haystack}', while line {call_line} of the same test compares that same output through "
        f"{call_name}() - console output wraps at the terminal width, so the raw match is green only "
        f"above some column count and the test names no column count",
        verdict=corpus.VERDICT_IMPROVE,
        line=lineno,
        evidence={
            "needle": needle,
            "haystack": haystack,
            "raw_assert_line": lineno,
            "normalised_by": call_name,
            "normalised_line": call_line,
        },
    )


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every raw needle matched against output its own test normalises."""
    rows: List[dict] = []

    for parsed in scanned.files:
        for unit in parsed.units:
            rows.extend(_nominate_unit(unit))

    return rows
