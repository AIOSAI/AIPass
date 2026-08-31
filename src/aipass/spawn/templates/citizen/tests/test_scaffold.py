# =================== META ====================
# Name: test_scaffold.py
# Description: Scaffold smoke test for template test infrastructure
# Version: 1.2.0
# Created: 2026-07-04
# Modified: 2026-08-31
# =============================================

"""Scaffold smoke test — proves pytest infrastructure works in this branch.

Also carries the one structural pin a citizen is BORN with: the handler
access guard must never walk ``inspect.stack()``. See the test below for why
that pin lives here rather than in a branch's own suite.
"""

import ast
from pathlib import Path

import pytest


def test_conftest_fixtures_available(request):
    """Verify template conftest fixtures are wired and return expected types.

    Established branches replace the template conftest with their own suite
    fixtures (spawn update never overwrites .py files) — there this smoke test
    has nothing left to prove, so it skips instead of erroring.
    """
    try:
        temp_test_dir = request.getfixturevalue("temp_test_dir")
        sample_test_data = request.getfixturevalue("sample_test_data")
    except pytest.FixtureLookupError:
        pytest.skip("branch conftest replaced the template scaffold fixtures — real suite covers this")
    assert temp_test_dir.exists()
    assert isinstance(sample_test_data, dict)


def _inspect_stack_calls(source: str) -> list:
    """Line numbers of every ``inspect.stack()`` CALL in ``source``.

    An AST matcher, not a string search: the guard's docstring names
    ``inspect.stack()`` while explaining what it replaced, and a spelling ban
    would convict the explanation.
    """
    tree = ast.parse(source)

    module_aliases = {"inspect"}
    direct_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "inspect":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "inspect":
            for alias in node.names:
                if alias.name == "stack":
                    direct_names.add(alias.asname or alias.name)

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

    WHY A NEWBORN IS BORN WITH THIS PIN. ``inspect.stack()`` builds a FrameInfo
    for every frame, which resolves that frame's source file
    (getsourcefile -> getmodule -> os.path.realpath), and ``ntpath.realpath``
    computes ``os.getcwd()`` unconditionally — before it even checks whether the
    path is absolute. So on Windows, in a process whose working directory is
    gone or unreadable, importing ANY handler in this branch dies inside the
    stdlib, one line above the guard's own first statement. Found on the Windows
    CI gate 2026-08-31; the cure is to walk frames with ``sys._getframe`` and
    read ``frame.f_code.co_filename``, which asks the filesystem nothing.

    WHY IT IS STRUCTURAL. The regression has no behavioural instrument. The
    guard's ``caller_file is None`` branch is unreachable from any import-shaped
    test, because ``apps/__init__.py`` always supplies a real-file frame —
    measured identically across nine branches, where restoring the walk left the
    whole suite green. A call that must not exist is pinned by reading the
    source; there is nothing else to watch.

    Unlike the fixture smoke test above, this does NOT skip when a branch grows
    its own suite: the guard is inherited code that a branch rarely edits, which
    is exactly why nobody would notice it changing.
    """
    guard = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py"

    if not guard.exists():
        pytest.skip(f"no handler guard at {guard} — nothing to pin")

    source = guard.read_text(encoding="utf-8")

    # Control: a matcher that parses nothing reports clean. Prove it read a real
    # guard before trusting its silence.
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
    """Negative control for the pin above — it must be able to say yes.

    A matcher that always returns an empty list passes the pin forever while
    detecting nothing.
    """
    assert _inspect_stack_calls("import inspect\nx = inspect.stack()\n") == [2]
    assert _inspect_stack_calls("import inspect\nx = inspect.currentframe()\n") == []
