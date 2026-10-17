# =================== AIPass ====================
# Name: shape.py
# Description: what each test function checks - the assertion-shape column
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""THE ASSERTION SHAPE: NONE, MOCK_ONLY, or REAL.

The mock set is the closed list `unittest.mock` defines, not an `assert_`
prefix: a prefix reads a project's own `assert_row_shape(...)` helper as a mock.
NONE over-reports tests that check through a helper, so every row also carries
`delegated_oracle`.
"""

import ast
import hashlib
from dataclasses import dataclass
from typing import List, Tuple

#: pytest's own oracle callables. A test using one checks something real.
PYTEST_ORACLES: frozenset = frozenset({"raises", "fail", "warns", "deprecated_call", "approx", "xfail"})

#: Every assertion method `unittest.mock` defines; closed on purpose (module docstring).
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
    """The dotted name a Call node names, or nothing."""
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

    blake2b, not `hash()`: the builtin is salted per process (PEP 456).
    """
    kinds = [type(child).__name__ for child in ast.walk(node) if isinstance(child, (ast.stmt, ast.excepthandler))]
    digest = hashlib.blake2b("|".join(kinds).encode("utf-8"), digest_size=4).hexdigest()
    return f"{len(kinds)}:{digest}"
