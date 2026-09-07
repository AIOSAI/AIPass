# =================== AIPass ====================
# Name: shape.py
# Description: what each test function checks - the assertion-shape column
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
THE ASSERTION SHAPE: NONE, MOCK_ONLY, or REAL.

This is the one column with published support behind it. Zhang & Mesbah
(ESEC/FSE 2015) found assertion presence correlates with fault-detection
strength where coverage does not, and Thoughtworks Radar vol. 34 named the
failure mode this column detects - "perpetually green" tests that pass
regardless of logic changes - as an AI-generated-test problem specifically.

  REAL       an `assert` statement, a pytest oracle (`raises`, `warns`, `fail`,
             `approx`, `deprecated_call`), or a unittest `assertX` call.
  MOCK_ONLY  nothing but `mock.assert_*` calls. The test asserts that the test's
             own doubles were called. arXiv:2606.18168 calls this W4 and finds
             it across 86,156 agent-authored test patches.
  NONE       no check of any kind.

WHY THE MOCK SET IS CLOSED AND NOT A PREFIX. The obvious rule - "the call name
starts with `assert_`" - reads a project's own helper `assert_row_shape(...)` as
a mock assertion and files a genuinely-checking test under MOCK_ONLY. The names
`unittest.mock` actually defines are a finite list, so this uses the list.

WHAT THIS OVER-REPORTS, stated because it decides whether the NONE count means
anything: a test whose checking lives in a HELPER it calls looks assertion-free
from here. So every row also carries `delegated_oracle`, which is true when the
function calls something named like a check - and a NONE row with a delegated
oracle is a different, weaker finding than a NONE row without one. Both counts
are published; the reader is not asked to take one number on trust.
"""

import ast
import hashlib
from dataclasses import dataclass
from typing import List, Tuple

#: pytest's own oracle callables. A test using one checks something real.
PYTEST_ORACLES: frozenset = frozenset({"raises", "fail", "warns", "deprecated_call", "approx", "xfail"})

#: Every assertion method `unittest.mock` defines. A closed set on purpose -
#: see the module docstring for the helper this stops us from misreading.
MOCK_ASSERTS: frozenset = frozenset(
    {
        "assert_any_await",
        "assert_any_call",
        "assert_awaited",
        "assert_awaited_once",
        "assert_awaited_once_with",
        "assert_awaited_with",
        "assert_called",
        "assert_called_once",
        "assert_called_once_with",
        "assert_called_with",
        "assert_has_awaits",
        "assert_has_calls",
        "assert_not_awaited",
        "assert_not_called",
    }
)

#: Prefixes that make a call LOOK like a delegated check.
DELEGATE_PREFIXES: tuple = ("assert", "check", "verify", "expect", "ensure")

#: The three shapes, most suspicious first.
SHAPE_NONE = "NONE"
SHAPE_MOCK_ONLY = "MOCK_ONLY"
SHAPE_REAL = "REAL"


@dataclass
class Shape:
    """What one test function checks, and what it was read as checking."""

    shape: str
    evidence: List[str]
    delegated_oracle: bool
    statements: int
    fingerprint: str


def classify(node: ast.AST) -> Shape:
    """The assertion shape of one test function."""
    real, mock, delegated = _oracles_in(node)

    if real:
        found = SHAPE_REAL
    elif mock:
        found = SHAPE_MOCK_ONLY
    else:
        found = SHAPE_NONE

    return Shape(
        shape=found,
        evidence=sorted(set(real or mock))[:5],
        delegated_oracle=bool(delegated),
        statements=sum(1 for child in ast.walk(node) if isinstance(child, ast.stmt)),
        fingerprint=fingerprint(node),
    )


def _oracles_in(node: ast.AST) -> Tuple[List[str], List[str], List[str]]:
    """The real oracles, mock assertions, and delegated-check calls in a body."""
    real: List[str] = []
    mock: List[str] = []
    delegated: List[str] = []

    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            real.append("assert")
            continue
        for name in _called_names(child):
            _file_name(name, real, mock, delegated)

    return real, mock, delegated


def _file_name(name: str, real: List[str], mock: List[str], delegated: List[str]) -> None:
    """Put one called name in whichever of the three buckets it belongs to."""
    tail = name.rsplit(".", 1)[-1]

    if tail in PYTEST_ORACLES or _is_unittest_assert(tail):
        real.append(name)
    elif tail in MOCK_ASSERTS:
        mock.append(name)
    elif tail.lstrip("_").startswith(DELEGATE_PREFIXES):
        delegated.append(name)


def _called_names(node: ast.AST) -> List[str]:
    """The dotted name a Call node names, or nothing.

    `with pytest.raises(...)` needs no special case and once had one: a
    mutation sweep deleted the `ast.With` arm and every test still passed,
    because `ast.walk` descends into `withitem.context_expr` and hands the
    same Call node here anyway. The arm was unreachable belt over a working
    brace, and an unreachable arm survives every mutant that touches it - so
    it is gone rather than pinned.
    """
    if isinstance(node, ast.Call):
        return [name] if (name := _dotted(node.func)) else []
    return []


def _dotted(node: ast.AST) -> str:
    """`a.b.c` for an attribute/name chain, or "" for anything else."""
    parts: List[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _is_unittest_assert(tail: str) -> bool:
    """`assertEqual`, `assertTrue`, ... - camelCase, never `assert_called`."""
    return len(tail) > 6 and tail.startswith("assert") and tail[6].isupper()


def fingerprint(node: ast.AST) -> str:
    """A shape signature for the function body, names and literals dropped.

    Two tests minted from one template differ in their literals and agree in
    their statement shape, so this is what makes a generated batch visible.
    It is a WEAK signal by construction - a genuine parametrised family looks
    identical too - and the column that uses it says so.

    Hashed with blake2b rather than `hash()`: the builtin is salted per process
    (PEP 456), so two runs over an unchanged tree would publish two different
    fingerprints and every diff of the artifact would be noise.
    """
    kinds = [type(child).__name__ for child in ast.walk(node) if isinstance(child, (ast.stmt, ast.excepthandler))]
    digest = hashlib.blake2b("|".join(kinds).encode("utf-8"), digest_size=4).hexdigest()
    return f"{len(kinds)}:{digest}"
