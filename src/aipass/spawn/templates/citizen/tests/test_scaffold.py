# =================== META ====================
# Name: test_scaffold.py
# Description: The handler guard's structural pin a citizen is born with
# Version: 1.3.0
# Created: 2026-07-04
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/__init__.py, the guard pin a citizen is born with: no ``inspect.stack()``."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/__init__.py parses and imports

import ast
from pathlib import Path

import pytest


def _bound_names(node: ast.AST, module: str, name: str) -> set:
    """The local names one import statement binds to ``module`` (Import) or ``module.name`` (ImportFrom)."""
    if isinstance(node, ast.Import):
        return {alias.asname or alias.name for alias in node.names if alias.name == module}
    if isinstance(node, ast.ImportFrom) and node.module == module:
        return {alias.asname or alias.name for alias in node.names if alias.name == name}
    return set()


def _inspect_stack_calls(source: str) -> list:
    """Line numbers of every ``inspect.stack()`` CALL in ``source`` (AST: a docstring naming it is no call)."""
    tree = ast.parse(source)

    module_aliases = {"inspect"}
    direct_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_aliases |= _bound_names(node, "inspect", "")
        elif isinstance(node, ast.ImportFrom):
            direct_names |= _bound_names(node, "inspect", "stack")

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "stack"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        ):
            found.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id in direct_names:
            found.append(node.lineno)

    return sorted(found)


def test_the_handler_guard_never_walks_inspect_stack():
    """This branch's import guard must not call ``inspect.stack()``.

    On Windows it reads os.getcwd() per frame, so a dead cwd kills every handler import; only Windows shows it,
    so the pin reads the source.
    """
    guard = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py"

    if not guard.exists():
        pytest.skip(f"no handler guard at {guard} — nothing to pin")

    source = guard.read_text(encoding="utf-8")

    # Control: a matcher that parses nothing reports clean.
    assert "_guard_branch_access" in source, (
        f"{guard} does not look like a handler guard — this pin is measuring nothing"
    )

    assert _inspect_stack_calls(source) == [], (
        "inspect.stack() is back in this branch's handler guard. It reads the "
        "current working directory on Windows before any of the guard's own code "
        "runs, so a process with a dead cwd cannot import this branch at all. "
        "Walk frames with sys._getframe(1) and read frame.f_code.co_filename."
    )


def test_the_stack_matcher_can_convict():
    """Negative control for the pin above — it must be able to say yes."""
    assert _inspect_stack_calls("import inspect\nx = inspect.stack()\n") == [2]
    assert _inspect_stack_calls("import inspect\nx = inspect.currentframe()\n") == []
