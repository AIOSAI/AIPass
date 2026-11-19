# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins that no daemon module calls inspect.stack()
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-15
# =============================================

"""Tests that apps/handlers/__init__.py, apps/handlers/json/json_handler.py and every daemon module stay free of inspect.stack()."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that each swept file parses; the sweep runs ast.parse on every one and would raise first

import ast
from pathlib import Path

# A dropbox, like .archive, is a sandbox nothing looks into or runs from; __pycache__ holds no source.
# Named here, not sentry's list: sentry's handlers refuse a caller from another branch.
SWEEP_SKIP_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})

_BRANCH = Path(__file__).resolve().parents[1]
APPS = _BRANCH / "apps"

# tools/ is swept: a tool that dies on its first line breaks exactly when someone diagnoses. It is gitignored,
# so it is named unconditionally and the sweep skips a root not on disk rather than failing CI.
SWEPT_ROOTS = (APPS, _BRANCH / "tools")


def _sweepable(root: Path):
    """Python files under *root*, or nothing if the root is not on this machine."""
    if not root.is_dir():
        return []
    return [f for f in sorted(root.rglob("*.py")) if not SWEEP_SKIP_DIRS.intersection(f.relative_to(root).parts[:-1])]


def _inspect_stack_calls(source: str) -> list:
    """Line numbers of every inspect.stack() call in *source*, by parse.

    Never a string scan: the guard's own docstring names inspect.stack() while explaining the defect.
    """
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


class TestTheGuardNeverCallsInspectStack:
    def test_the_guard_is_free_of_inspect_stack(self):
        guard = (APPS / "handlers" / "__init__.py").read_text(encoding="utf-8")

        assert _inspect_stack_calls(guard) == [], (
            "inspect.stack() is back in the guard - it needs a readable working "
            "directory before any of the guard's own code runs "
            "(getmodule's os.path.realpath sits outside any try)"
        )
        assert "import inspect" not in [line.strip() for line in guard.splitlines()], (
            "the guard imports inspect again - nothing in the cured shape needs it"
        )

    def test_the_json_handler_caller_walk_is_free_of_inspect_stack(self):
        """The runtime half. log_operation runs on essentially every tick."""
        handler = (APPS / "handlers" / "json" / "json_handler.py").read_text(encoding="utf-8")

        assert _inspect_stack_calls(handler) == [], (
            "inspect.stack() is back in _get_caller_module_name - the audit line "
            "would take its own caller down on a box with no working directory"
        )

    def test_no_daemon_module_calls_inspect_stack(self):
        """The sweep, so the next copy of the template line is caught at birth."""
        offenders = []
        for root in SWEPT_ROOTS:
            for source in _sweepable(root):
                for lineno in _inspect_stack_calls(source.read_text(encoding="utf-8")):
                    offenders.append(f"{source.relative_to(_BRANCH)}:{lineno}")

        assert offenders == [], "inspect.stack() calls in daemon: " + ", ".join(offenders)

    def test_the_matcher_convicts_a_real_call(self):
        """Positive control - a ban that convicts nothing reads green forever."""
        assert _inspect_stack_calls("import inspect\nframes = inspect.stack()\n") == [2]

    def test_the_matcher_clears_prose_that_names_the_defect(self):
        """Docstring negative control - the red that would rewrite the cure's own comments."""
        assert _inspect_stack_calls('"""inspect.stack() is banned here."""\n') == [], (
            "a docstring explaining the cure is not the defect; convicting it is how cures go unexplained"
        )

    def test_the_matcher_clears_an_unrelated_stack_attribute(self):
        """numpy.stack shape - the attribute name alone must not convict."""
        assert _inspect_stack_calls("import numpy\nnumpy.stack([])\n") == []

    def test_the_matcher_clears_inspect_signature(self):
        """rotation.py legitimately calls inspect.signature; only .stack is banned."""
        assert _inspect_stack_calls("import inspect\ninspect.signature(f)\n") == []
