# =================== AIPass ====================
# Name: support_pytest_quality_pack.py
# Description: Shared helpers for the pytest_quality pack test files (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Shared helpers for the tests of apps/handlers/pytest_quality_standards/ (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import ast
import textwrap
from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus


def _write(root: Path, relpath: str, source: str) -> Path:
    """One file, dedented, with its parents made."""
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


def _unit(source: str, relpath: str = "tests/test_x.py", class_name: str = "") -> corpus.TestUnit:
    """One written-out test function as the TestUnit the readers are handed."""
    node = ast.parse(textwrap.dedent(source).strip()).body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)), "the snippet must be one test function"
    return corpus.TestUnit(
        name=node.name,
        node=node,
        relpath=relpath,
        class_name=class_name,
        line=node.lineno,
    )


def _line_of(path: Path, prefix: str) -> int:
    """The 1-based line number of the first line starting with `prefix`."""
    return next(
        number
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if text.startswith(prefix)
    )
