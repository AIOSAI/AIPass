# =================== AIPass ====================
# META DATA HEADER
# Name: test_import_dead_cwd.py - cli imports without a readable cwd
# Description: No inspect.stack() call in the files that run at import
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-02
# Category: cli/tests
# =============================================

"""Tests for apps/handlers/__init__.py and every cli import-time site — no inspect.stack() at import."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(standard) — the fence with a healthy cwd; tests/test_handlers_fence.py covers it

import ast
from pathlib import Path


def _inspect_stack_call_lines(tree: ast.Module) -> list:
    """Line numbers of every inspect.stack() CALL in a parsed module."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "stack":
            if isinstance(func.value, ast.Name) and func.value.id == "inspect":
                lines.append(node.lineno)
    return lines


class TestStructuralSweep:
    """AST ban on inspect.stack() in the files that run at import; parsed, not grepped."""

    _IMPORT_TIME_FILES = (
        "apps/handlers/__init__.py",
        "apps/handlers/json/json_handler.py",
        "apps/modules/display.py",
    )

    def _branch_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_no_inspect_stack_call_in_import_time_files(self):
        offenders = []
        for rel in self._IMPORT_TIME_FILES:
            path = self._branch_root() / rel
            assert path.exists(), f"pin names a file that does not exist: {rel}"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders += [f"{rel}:{line}" for line in _inspect_stack_call_lines(tree)]

        assert not offenders, (
            "inspect.stack() is back in a file that runs at import time, and most "
            "of the fleet imports this branch. Use sys._getframe over "
            f"f_code.co_filename instead. Offenders: {offenders}"
        )

    def test_the_ast_pin_can_actually_fail(self):
        """Positive control: the matcher must convict the shape it bans."""
        tree = ast.parse("import inspect\nstack = inspect.stack()\n")
        assert _inspect_stack_call_lines(tree) == [2], (
            "the AST matcher cannot see inspect.stack() — the ban above is vacuous"
        )

    def test_the_ast_pin_does_not_convict_a_docstring(self):
        """A string ban would convict this very file's docstrings. Parsing does not."""
        tree = ast.parse('"""We used to call inspect.stack() here."""\nx = 1\n')
        assert _inspect_stack_call_lines(tree) == [], "prose mentioning inspect.stack() must not count as a call"
