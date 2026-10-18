# =================== AIPass ====================
# Name: empty_parametrize_check.py
# Description: nominator - a parametrize table computed at collection time (VANISHING-TABLE)
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""A parametrized test over an EMPTY collection reports as passing.

Reference: empty_parametrize.md
"""

import ast
from typing import List

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_empty_parametrize"

#: Given a non-empty literal these return something non-empty; ``range(24)`` is a table in shorthand.
SAFE_BUILTINS: frozenset = frozenset({"range", "sorted", "list", "tuple", "reversed", "enumerate", "set"})

#: Receiver must be a plain Name proven non-empty, never a chain, so this stays a
#: lookup and not the interpreter Law M10 forbids.
DICT_VIEW_METHODS: frozenset = frozenset({"values", "keys", "items"})

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
    """Module-level names bound to a non-empty literal container."""
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

    One layer of safe builtin is unwrapped, deliberately: following a chain is interpreting (M10).
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
        if _is_view_of_safe_name(value, safe_names):
            return True
        name = corpus.dotted_name(value.func).rsplit(".", 1)[-1]
        if name not in SAFE_BUILTINS or not value.args:
            return False
        return _cannot_be_empty(value.args[0], safe_names)
    return False


def _is_view_of_safe_name(value: ast.Call, safe_names: set) -> bool:
    """True when this call is ``NAME.values()`` on a proven non-empty mapping."""
    func = value.func
    if not isinstance(func, ast.Attribute) or func.attr not in DICT_VIEW_METHODS:
        return False
    return isinstance(func.value, ast.Name) and func.value.id in safe_names


def _guard_pins_a_count(parsed: corpus.TestFile) -> bool:
    """True when some assertion compares a length against a derived EXPECTED value.

    A truthy ``len(x)`` guard misses a collector that drops one entry; only a count notices.
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

    Matched anywhere in the file: the rule errs toward acquitting.
    """
    for node in ast.walk(parsed.tree):
        if not isinstance(node, ast.Assert):
            continue
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Call) and corpus.dotted_name(sub.func).rsplit(".", 1)[-1] == "len":
                return True
    return False


def _parametrize_tables(unit: corpus.TestUnit) -> List[tuple]:
    """Every ``parametrize`` decorator on a unit as ``(argvalues, lineno)``."""
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
    """Every parametrize table that could vanish without the suite noticing."""
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
