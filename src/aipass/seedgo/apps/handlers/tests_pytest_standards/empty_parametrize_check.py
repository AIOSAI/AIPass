# =================== AIPass ====================
# Name: empty_parametrize_check.py
# Description: nominator - a parametrize table computed at collection time (VANISHING-TABLE)
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""
A parametrized test over an EMPTY collection reports as passing.

    @pytest.mark.parametrize("item", collect())
    def test_every_found_item_is_valid(item):
        assert item["ok"]

If ``collect()`` returns ``[]``, pytest generates no cases, marks the test
SKIPPED, and the run prints ``1 passed, 1 skipped`` with exit code 0.
Reproduced verbatim before this rule was written. The instrument checked
nothing and reported the same green a clean tree reports.

WHY THIS IS ITS OWN RULE AND NOT PART OF `self_skip`. That rule asks where a
skip's CONDITION gets its answer, and finds skips written in the source. Here
there is no skip in the source at all — pytest manufactures it from an empty
argvalues sequence. A reader grepping for ``skip`` finds nothing, which is
what makes this the quieter species of the two.

WHERE IT CAME FROM. @drone hit it building the content-anchored bypass rule
(2026-08-31): their first version of ``test_bypass_anchors.py`` SURVIVED a
mutant that blinded the collector to ``return []``, because the anchor checks
were parametrized over the collector's output and the whole file came back
"1 passed, 2 skipped". Their arming probe asserted the raw bypass list was
non-empty, which is a different question from whether the collector found
anything. They reported it unprompted with the cure: recount the entries
INDEPENDENTLY, walking the raw data rather than calling the function under
judgement.

THE ACQUITTALS MATTER MORE THAN THE FLAGS HERE. A literal table cannot be
empty, and neither can a module constant bound to a non-empty literal, and a
file that already carries an independent non-empty guard has done the thing
this rule exists to ask for. Measured across the fleet before landing: 312
parametrize sites, 217 of them plain literals that this rule never looks at.

NOMINATION, NEVER CONVICTION (Law M1). A table that is legitimately empty on
some machines — a platform sweep with no rows on this OS — is the honest case,
and the execution tier rules on it.
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

#: The adapter group this nominator fills. Namespaced by the core.
GROUP = "static_empty_parametrize"

#: Builtins that cannot invent emptiness on their own: given a non-empty
#: literal they return something non-empty. ``range`` is here because
#: ``range(24)`` is a table written in shorthand, not a query.
SAFE_BUILTINS: frozenset = frozenset({"range", "sorted", "list", "tuple", "reversed", "enumerate", "set"})

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 3a - a table computed at collection time",
    "species": ["VANISHING-TABLE", "SHORT-TABLE"],
    "flags": [
        "parametrize argvalues drawn from a function call, whose empty return "
        "pytest reports as SKIPPED while the suite summary reads green",
        "the same table where the file's only guard asserts NON-EMPTINESS - a "
        "collector that drops one entry still satisfies it (SHORT-TABLE)",
    ],
    "exempts": [
        "a literal list/tuple/set with elements - it cannot be empty",
        "a module-level name bound to a non-empty literal",
        "a safe builtin over a literal: range(24), sorted(LITERAL)",
        "a file whose guard pins an expected COUNT, not merely non-emptiness",
    ],
    "fix": (
        "assert the collection is non-empty in a test of its own, and derive that "
        "assertion from the raw data rather than from the function being judged - "
        "a probe that calls the collector cannot detect a blinded collector."
    ),
    "limits": [
        "a table legitimately empty on some machines is nominated; that is why this "
        "tier nominates and the execution tier convicts (Law M1)",
        "the guard clause matches an assertion anywhere in the FILE, not one proven "
        "to cover this particular table - it errs toward acquitting",
    ],
    "evidence": (
        "@drone's test_bypass_anchors.py survived a collector-blinding mutant and "
        "reported '1 passed, 2 skipped' (2026-08-31, reported unprompted with the cure)"
    ),
}


def _module_literal_names(parsed: corpus.TestFile) -> set:
    """Module-level names bound to a non-empty literal container.

    Args:
        parsed: The test module.

    Returns:
        Names that cannot be empty at collection time.
    """
    safe = set()
    for node in parsed.tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        value = getattr(node, "value", None)
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)) and value.elts:
            safe.update(t.id for t in targets if isinstance(t, ast.Name))
        elif isinstance(value, ast.Dict) and value.keys:
            safe.update(t.id for t in targets if isinstance(t, ast.Name))
    return safe


def _cannot_be_empty(value: ast.expr, safe_names: set) -> bool:
    """True when this argvalues expression is non-empty by construction.

    Unwraps one layer of a safe builtin, so ``sorted(WORLDS)`` is judged on
    ``WORLDS``. One layer, deliberately: following an arbitrary chain would
    make this an interpreter, and Law M10 forbids running the subject.

    Args:
        value: The second positional argument to ``parametrize``.
        safe_names: Module names bound to non-empty literals.

    Returns:
        True if the table cannot vanish.
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


def _guard_pins_a_count(parsed: corpus.TestFile) -> bool:
    """True when some assertion compares a length against a derived EXPECTED value.

    @trigger's round-9 find, and the species is a notch smaller than the one
    this file was built for: a collector that silently drops ONE entry leaves a
    non-empty table, every surviving case still passes, and the run is two cases
    lighter than it should be. An empty run at least looks odd; a short one
    looks like a normal run.

    A guard asserting ``len(x)`` is truthy answers "did it find anything". A
    guard asserting ``len(x) == expected`` answers "did it find them all", and
    only the second notices a short table.

    Measured before this split shipped: of 10 files the guard clause acquits
    fleet-wide, 7 already pin a count and 3 assert only non-emptiness - so the
    new species nominates three sites, not a tree.

    Args:
        parsed: The test module.

    Returns:
        True if a count-pinning assertion exists anywhere in the file.
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
                # `len(x) == 0` is an emptiness assertion, not a count.
                if isinstance(comparator, ast.Constant) and comparator.value == 0:
                    continue
                return True
    return False


def _has_independent_nonempty_guard(parsed: corpus.TestFile) -> bool:
    """True when some test in this file asserts a collection is non-empty.

    The cure @drone built, detected in the shape it is usually written: an
    assertion comparing a length against zero, or asserting a collection
    truthy. Matched anywhere in the file rather than proven to cover the table
    in question — this rule errs toward acquitting, because a false flag on a
    file that already did the work teaches nothing.

    Args:
        parsed: The test module.

    Returns:
        True if an arming probe of that shape exists.
    """
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Call) and corpus.dotted_name(sub.func).rsplit(".", 1)[-1] == "len":
                return True
    return False


def _parametrize_tables(unit: corpus.TestUnit) -> List[tuple]:
    """Every ``parametrize`` decorator on a unit as ``(argvalues, lineno)``.

    Args:
        unit: The test function or class.

    Returns:
        One entry per parametrize decorator carrying argvalues.
    """
    tables = []
    for decorator in unit.decorators:
        if not isinstance(decorator, ast.Call):
            continue
        if corpus.dotted_name(decorator.func).rsplit(".", 1)[-1] != "parametrize":
            continue
        if len(decorator.args) < 2:
            continue
        tables.append((decorator.args[1], decorator.lineno))
    return tables


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every parametrize table that could vanish without the suite noticing.

    Args:
        scanned: The parsed corpus.

    Returns:
        Nomination rows, one per unguarded computed table.
    """
    rows: List[dict] = []

    for parsed in scanned.files:
        guarded = _has_independent_nonempty_guard(parsed)
        counted = _guard_pins_a_count(parsed)
        if guarded and counted:
            continue
        safe_names = _module_literal_names(parsed)
        for unit in parsed.units:
            for argvalues, lineno in _parametrize_tables(unit):
                if _cannot_be_empty(argvalues, safe_names):
                    continue
                if guarded:
                    rows.append(
                        corpus.nomination(
                            "SHORT-TABLE",
                            unit,
                            f"parametrize table computed at collection time ({ast.unparse(argvalues)[:60]}) "
                            "- the file's guard asserts the collection is NON-EMPTY, which a collector that "
                            "drops one entry still satisfies; pin the expected COUNT from raw data",
                            line=lineno,
                            evidence={"argvalues": ast.unparse(argvalues)[:120], "guard": "non-empty only"},
                        )
                    )
                    continue
                rows.append(
                    corpus.nomination(
                        "VANISHING-TABLE",
                        unit,
                        f"parametrize table computed at collection time ({ast.unparse(argvalues)[:60]}) "
                        "- an empty result is reported as SKIPPED and the suite summary reads green",
                        line=lineno,
                        evidence={"argvalues": ast.unparse(argvalues)[:120]},
                    )
                )

    return rows
