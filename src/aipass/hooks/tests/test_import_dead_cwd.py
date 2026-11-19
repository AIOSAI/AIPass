# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins the handlers fence against regrowing inspect.stack()
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-15
# =============================================

"""Tests for apps/handlers/__init__.py: the fence walks frames with sys._getframe, never inspect.stack()."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that every hooks module parses; this file pins only the fence's source shape

import ast
from pathlib import Path

BRANCH_ROOT = Path(__file__).resolve().parents[1]
GUARD_SOURCE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"


class TestTheCureCannotBeSilentlyReverted:
    """An import probe cannot reach the guard's caller-is-None branch, so the inspect.stack() ban is structural."""

    def test_the_guard_source_is_actually_read(self):
        """Positive control: a wrong path would let every check below pass while reading nothing."""
        text = GUARD_SOURCE.read_text(encoding="utf-8")
        assert 'MY_BRANCH = "hooks"' in text

    @staticmethod
    def _inspect_stack_calls(source: str) -> list[int]:
        """Lines calling ``inspect.stack()``, by shape."""
        tree = ast.parse(source)
        return [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "stack"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "inspect"
        ]

    def test_inspect_stack_is_gone_from_the_guard(self):
        lines = self._inspect_stack_calls(GUARD_SOURCE.read_text(encoding="utf-8"))
        assert lines == [], (
            "inspect.stack() reaches os.path.realpath, which needs a readable cwd "
            f"- walk frames with sys._getframe instead (line {lines})"
        )

    def test_that_ban_would_convict_a_real_call(self):
        """Negative control: a matcher that matches nothing passes a reverted file too."""
        assert self._inspect_stack_calls("import inspect\ndef f():\n    return inspect.stack()\n") == [3]

    def test_that_ban_acquits_the_docstring_that_names_it(self):
        """The ban is AST, not a grep: prose naming the call is acquitted."""
        assert self._inspect_stack_calls('"""We do not call inspect.stack() here."""\n') == []

    def test_the_frame_walk_is_what_replaced_it(self):
        """Names the cure, so breaking the guard is not a way to pass the ban."""
        text = GUARD_SOURCE.read_text(encoding="utf-8")
        assert "sys._getframe" in text
        assert "linecache" in text, "code_context needs a replacement, not deletion"
