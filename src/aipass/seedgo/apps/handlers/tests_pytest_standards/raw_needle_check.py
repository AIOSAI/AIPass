# =================== AIPass ====================
# Name: raw_needle_check.py
# Description: nominator - a raw needle matched against output the same test normalises (WIDTH-FRAGILE-ASSERT)
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""
A raw substring matched against captured console output, in a test that
ELSEWHERE normalises the SAME output for exactly this reason.

THE DEFECT. Rich - and every other console renderer - wraps at the terminal
width. A literal needle matched against un-normalised captured output is
therefore green only above some column count, and red below it, with nothing
in the test naming the dependency. The suite passes on the author's terminal
and fails in a narrow CI pane, which reads as a flake rather than as the
measurement it actually is.

MEASURED, on the canary fixture this rule was calibrated against: at
``COLUMNS=40`` and ``41`` the suite reports **18 failures**, at ``42`` it
reports **nine**, and from ``43`` upward all **34** tests pass. Nothing in the
suite mentions a column count.

WHY THE AUTHOR'S OWN INCONSISTENCY IS THE WHOLE SIGNAL. Matching raw console
output is not a defect on its own - most suites do it, most of the time
correctly, and a rule that flagged every ``assert "Usage:" in out`` would
nominate the fleet and teach nobody anything. What this rule looks for is
narrower and far more damning: the SAME test that normalises a haystack in one
assertion matches a raw literal against that haystack in the next. The author
who wrote the normalising call already knew the output wraps. The raw assert
beside it is an oversight, not a style choice, and it is the one the author
would fix if shown it.

WHAT IT DELIBERATELY DOES NOT FLAG:

  - a test that never normalises anything. No inconsistency, no nomination -
    however raw its needles are.
  - a haystack that is not captured console output. A needle matched against a
    file's bytes or a return value does not wrap, so the species does not
    apply and this rule does not look there.
  - the normalising assertion itself. Both of its sides are normalised; it is
    the correct half of the pair and it is what proves the other half wrong.
  - a call that cannot be a normalised form of the text - ``len``, ``bool``,
    ``int`` and friends return a number, not a comparable rendering.

NOMINATION, NEVER CONVICTION (Law M1). A test can have a legitimate reason to
match one needle raw and normalise another - a needle with no spaces in it
cannot be broken by a word wrap, and an author may have reasoned exactly that.
This tier names the inconsistency and reports BOTH halves of it in evidence,
with line numbers, so a reader can settle it in one glance. The execution tier
convicts.
"""

import ast
from typing import Dict, List, Set, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

#: The adapter group this nominator fills. Namespaced by the core.
GROUP = "static_raw_needle"

#: pytest's capture fixtures. A haystack is only "console output" when it came
#: from one of these - a needle matched against file bytes does not wrap.
CAPTURE_FIXTURES: frozenset = frozenset({"capsys", "capfd", "capsysbinary", "capfdbinary"})

#: The method that drains a capture fixture.
CAPTURE_READER = "readouterr"

#: The two streams a drained capture exposes.
CAPTURE_STREAMS: frozenset = frozenset({"out", "err"})

#: Calls that CANNOT be a normalised rendering of the text, because what they
#: return is a number or a type rather than something a needle can live in.
#: Without this, ``assert len(out) > 0`` beside ``assert "x" in out`` would
#: read as an author normalising their own haystack, and it is neither.
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

    Two expressions are "the same haystack" when they spell the same thing, so
    the key is the source text rather than the node. An expression that will
    not unparse is REPORTED, never skipped quietly: a haystack this rule could
    not read is a haystack it never cleared, and Law S1 forbids that reading
    the same as clean.

    Args:
        node: Any expression node.

    Returns:
        The unparsed source text, or "" when it could not be produced.
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

    Two spellings, both of them common and both present in the calibration
    fixture: the capture read used inline (``capsys.readouterr().err``), and a
    local name bound from one (``err = capsys.readouterr().err``). A tuple
    unpack of the drained result binds both streams at once.

    ONE HOP, DELIBERATELY. A name bound from a name bound from a capture is
    not followed, which biases this rule toward FEWER nominations - the safe
    direction for a rule whose whole claim is an author's inconsistency.

    Args:
        unit: The test function.

    Returns:
        Source-text keys naming captured output.
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
    """Literal-in-captured-output tests, un-normalised.

    Args:
        unit: The test function.
        capture: Keys naming captured console output in this unit.

    Returns:
        `(needle, haystack_key, lineno, comparison)` per raw membership test.
    """
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
    """Every comparison that puts a captured haystack THROUGH a call.

    This is the other half of the pair, and the half that makes the rule
    precise: it is the author's own statement that this output must be
    normalised before it can be matched.

    Args:
        unit: The test function.
        capture: Keys naming captured console output in this unit.

    Returns:
        haystack key -> `(call name, lineno, id of the enclosing comparison)`.
    """
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
    """Every raw needle matched against output its own test normalises.

    Args:
        scanned: The parsed corpus.

    Returns:
        Nomination rows, one per raw membership test with a normalised twin.
    """
    rows: List[dict] = []

    for parsed in scanned.files:
        for unit in parsed.units:
            rows.extend(_nominate_unit(unit))

    return rows
