"""Tests for email header handler -- get_dispatch_header, prepend_dispatch_header."""

import ast

import pytest
from unittest.mock import MagicMock

from pathlib import Path

import aipass.ai_mail.apps.handlers.email.header as mod


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    mock_jh = MagicMock()
    monkeypatch.setattr(mod, "json_handler", mock_jh)
    return mock_jh


# --- get_dispatch_header tests ---------------------------------------


def test_get_dispatch_header_default_returns_standard():
    """Default call returns DISPATCH_HEADER."""
    result = mod.get_dispatch_header()
    assert result == mod.DISPATCH_HEADER


def test_get_dispatch_header_no_memory_save_returns_variant():
    """no_memory_save=True returns NO_MEMORY_SAVE_HEADER."""
    result = mod.get_dispatch_header(no_memory_save=True)
    assert result == mod.NO_MEMORY_SAVE_HEADER


def test_get_dispatch_header_false_returns_standard():
    """Explicit no_memory_save=False returns DISPATCH_HEADER."""
    result = mod.get_dispatch_header(no_memory_save=False)
    assert result == mod.DISPATCH_HEADER


def test_dispatch_header_contains_memory_reminder():
    """Standard header reminds agents to update memories."""
    result = mod.get_dispatch_header()
    assert "UPDATE YOUR MEMORIES" in result
    assert "NOT optional" in result


def test_no_memory_save_header_contains_optional_directive():
    """No-memory-save header marks memory update as OPTIONAL."""
    result = mod.get_dispatch_header(no_memory_save=True)
    assert "OPTIONAL" in result
    assert "Do NOT log this task" in result


def test_headers_are_distinct():
    """The two header variants are different strings."""
    standard = mod.get_dispatch_header(no_memory_save=False)
    no_save = mod.get_dispatch_header(no_memory_save=True)
    assert standard != no_save


# --- prepend_dispatch_header tests -----------------------------------


def test_prepend_dispatch_header_default():
    """Prepends standard dispatch header to message."""
    message = "Please complete task X."
    result = mod.prepend_dispatch_header(message)
    assert result.startswith(mod.DISPATCH_HEADER)
    assert result.endswith(message)


def test_prepend_dispatch_header_no_memory_save():
    """Prepends no-memory-save header when flag is set."""
    message = "Private task."
    result = mod.prepend_dispatch_header(message, no_memory_save=True)
    assert result.startswith(mod.NO_MEMORY_SAVE_HEADER)
    assert result.endswith(message)


def test_prepend_dispatch_header_preserves_message():
    """Original message text is fully preserved in result."""
    message = "Multi\nline\nmessage\nbody"
    result = mod.prepend_dispatch_header(message)
    assert message in result


def test_prepend_dispatch_header_logs_operation(
    _suppress_log_operation: MagicMock,
):
    """prepend_dispatch_header calls json_handler.log_operation."""
    mod.prepend_dispatch_header("test", no_memory_save=False)
    _suppress_log_operation.log_operation.assert_called_once_with("prepend_dispatch_header", {"no_memory_save": False})


def test_prepend_dispatch_header_logs_no_memory_save_flag(
    _suppress_log_operation: MagicMock,
):
    """Log call captures no_memory_save=True when set."""
    mod.prepend_dispatch_header("test", no_memory_save=True)
    _suppress_log_operation.log_operation.assert_called_once_with("prepend_dispatch_header", {"no_memory_save": True})


def test_prepend_dispatch_header_empty_message():
    """Works with an empty message string."""
    result = mod.prepend_dispatch_header("")
    assert result == mod.DISPATCH_HEADER


def test_prepend_dispatch_header_result_is_header_plus_message():
    """Result is exactly header concatenated with message."""
    message = "Exact concatenation test."
    result = mod.prepend_dispatch_header(message, no_memory_save=False)
    assert result == mod.DISPATCH_HEADER + message


def test_dispatch_header_instructs_synchronous_subagents():
    """Standard header tells agents to run sub-agents synchronously —
    headless sessions are never re-invoked when background tasks finish."""
    assert "SYNCHRONOUSLY" in mod.DISPATCH_HEADER
    assert "run_in_background: false" in mod.DISPATCH_HEADER
    assert "BEFORE ending your turn" in mod.DISPATCH_HEADER


def test_no_memory_save_header_instructs_synchronous_subagents():
    """No-memory-save variant carries the same sync sub-agents warning."""
    assert "SYNCHRONOUSLY" in mod.NO_MEMORY_SAVE_HEADER
    assert "run_in_background: false" in mod.NO_MEMORY_SAVE_HEADER


def test_dispatch_header_carries_culture_fence():
    """Standard header states the fence: unexplained work is reported, never
    given an invented author (DPLAN-0276)."""
    assert "never invent an author" in mod.DISPATCH_HEADER
    assert "REPORT it" in mod.DISPATCH_HEADER
    assert "attribute it to no one" in mod.DISPATCH_HEADER


def test_no_memory_save_header_carries_culture_fence():
    """The fence is not a memory-save concern — the private variant carries it too."""
    assert "never invent an author" in mod.NO_MEMORY_SAVE_HEADER
    assert "attribute it to no one" in mod.NO_MEMORY_SAVE_HEADER


def test_culture_fence_reaches_the_recipient():
    """The fence survives prepend — it is on the surface a recipient actually reads,
    not just a module constant."""
    result = mod.prepend_dispatch_header("Task body.")
    assert "never invent an author" in result


# --- The module docstring is where Python can see it -----------------
#
# Found by @seedgo (2026-08-31) when they rewrote check_module_docstring off a
# 30-line scan for a triple quote and onto ast.get_docstring. This file's
# docstring sat AFTER the json_handler import. Python evaluates such a string,
# discards it, and leaves __doc__ None — so the module read as documented to
# every human opening it and to nothing that reads __doc__: help(), pydoc, and
# seedgo's new checker. That is why the old line scan agreed with the reader
# instead of with the interpreter, and why the verdict was 100 for eight months.


def test_header_module_has_a_real_docstring():
    """The defect itself: __doc__ is populated, not silently discarded.

    Goes red on the pre-fix file — the string was there, ``__doc__`` was None.
    """
    assert mod.__doc__ is not None
    assert "Email Header Handler" in mod.__doc__


def test_header_docstring_opens_the_module_body():
    """The MECHANISM, separately from the outcome: the string is statement zero.

    ``__doc__`` being populated is the outcome; a string literal opening the
    body is the cause. Pinned apart so a future red names which one moved —
    a docstring assigned some other way would satisfy the pin above and still
    leave the shape seedgo measures wrong.
    """
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    first = tree.body[0]
    assert isinstance(first, ast.Expr), f"module opens with {type(first).__name__}"
    assert isinstance(first.value, ast.Constant)
    assert isinstance(first.value.value, str)


def _discarded_module_strings(source: str) -> list:
    """Line numbers of module-level strings Python evaluates and throws away.

    A bare string expression at the top of the body IS the docstring; anywhere
    below it, it is a no-op the interpreter discards. Reports lines only when
    the module has no real docstring, which is the shape that reads as
    documentation and is not.
    """
    tree = ast.parse(source)
    if ast.get_docstring(tree) is not None:
        return []
    discarded = [
        node.lineno
        for index, node in enumerate(tree.body)
        if index != 0
        and isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    # An f-string OPENING the body is the same defect one step along: it reads
    # as the docstring to a human, ``ast.get_docstring`` refuses it (JoinedStr,
    # not Constant), and Python leaves __doc__ None. Named by a mutant here,
    # measured at 0 live sites in apps/ on 2026-08-31 — reachable, not armed,
    # so the sweep watches for it rather than waiting to be surprised.
    if tree.body:
        first = tree.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.JoinedStr):
            discarded.append(first.lineno)
    return sorted(discarded)


_DEFECT_SHAPE = '"""Not the docstring."""'
_CURED_SHAPE = '"""The docstring."""'


def test_the_sweep_convicts_the_defect_shape():
    """Negative control. A matcher that convicts nothing reports any tree clean.

    Built from a synthetic source, never the live file, so it cannot pass for
    the sweep's own reason — the thing it measures is present here by
    construction whatever the tree below does.
    """
    guilty = f"import os\n\n{_DEFECT_SHAPE}\n"
    assert _discarded_module_strings(guilty) == [3]


def test_the_sweep_acquits_a_real_docstring():
    """Positive control. The cured shape — string first, import after — is clean.

    Without this, a matcher that convicts unconditionally would look identical
    to a working one from the tree sweep's green.
    """
    cured = f"{_CURED_SHAPE}\n\nimport os\n"
    assert _discarded_module_strings(cured) == []


def test_the_sweep_convicts_an_fstring_opener():
    """The species M4 named: an f-string reads as the docstring and is not one.

    Zero live sites in ``apps/`` when this was written, so the sweep's green on
    this shape says nothing on its own — this control is what makes the tree
    result mean something.
    """
    guilty = 'f"""Module {1}."""\n\nimport os\n'
    assert _discarded_module_strings(guilty) == [1]


def test_no_module_in_the_tree_documents_itself_into_the_void():
    """Tree-wide: the species dies everywhere in this branch, not just here.

    seedgo's sweep named one ai_mail file and my own sweep agreed on one — but
    a handed list is a starting point, never the scope, so this asks the tree
    directly and keeps asking on every run.
    """
    apps = Path(__file__).resolve().parents[1] / "apps"
    scanned, offenders = 0, []
    for source in apps.rglob("*.py"):
        scanned += 1
        lines = _discarded_module_strings(source.read_text(encoding="utf-8"))
        if lines:
            offenders.append(f"{source.name}:{lines}")

    # Arming probe: a sweep over an empty file list passes for free. A wrong
    # root or a renamed apps/ would otherwise read as a clean tree forever.
    assert scanned > 30, f"sweep only visited {scanned} files — wrong root?"
    assert not offenders, f"module strings Python discards: {offenders}"
