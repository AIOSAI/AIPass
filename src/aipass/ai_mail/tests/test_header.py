# =================== AIPass ====================
# Name: test_header.py
# Description: Tests for email header handler
# Version: 1.0.1
# Created: 2026-04-25
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/email/header.py -- get_dispatch_header, prepend_dispatch_header."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — DISPATCH_HEADER and NO_MEMORY_SAVE_HEADER's exact wording

import ast

import pytest
from unittest.mock import MagicMock

from pathlib import Path

import aipass.ai_mail.apps.handlers.email.header as mod

# Written here, not imported: seedgo's handlers guard refuses a caller from another branch.
_SWEEP_SKIP_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    mock_jh = MagicMock()
    monkeypatch.setattr(mod, "json_handler", mock_jh)
    return mock_jh


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


@pytest.mark.parametrize("flag", [False, True])
def test_prepend_dispatch_header_logs_the_no_memory_save_flag(
    _suppress_log_operation: MagicMock,
    flag: bool,
):
    """The audit payload carries whichever no_memory_save it was called with.

    Keep both rows: dropping either leaves the payload free to hardcode the other.
    """
    mod.prepend_dispatch_header("test", no_memory_save=flag)
    _suppress_log_operation.log_operation.assert_called_once_with("prepend_dispatch_header", {"no_memory_save": flag})


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
    """Standard header tells agents to run sub-agents synchronously (headless sessions are never re-invoked)."""
    assert "SYNCHRONOUSLY" in mod.DISPATCH_HEADER
    assert "run_in_background: false" in mod.DISPATCH_HEADER
    assert "BEFORE ending your turn" in mod.DISPATCH_HEADER


def test_no_memory_save_header_instructs_synchronous_subagents():
    """No-memory-save variant carries the same sync sub-agents warning."""
    assert "SYNCHRONOUSLY" in mod.NO_MEMORY_SAVE_HEADER
    assert "run_in_background: false" in mod.NO_MEMORY_SAVE_HEADER


def test_dispatch_header_carries_culture_fence():
    """Standard header states the fence: unexplained work is reported, never given an invented author."""
    assert "never invent an author" in mod.DISPATCH_HEADER
    assert "REPORT it" in mod.DISPATCH_HEADER
    assert "attribute it to no one" in mod.DISPATCH_HEADER


def test_no_memory_save_header_carries_culture_fence():
    """The fence is not a memory-save concern — the private variant carries it too."""
    assert "never invent an author" in mod.NO_MEMORY_SAVE_HEADER
    assert "attribute it to no one" in mod.NO_MEMORY_SAVE_HEADER


def test_culture_fence_reaches_the_recipient():
    """The fence survives prepend, on the surface a recipient actually reads."""
    result = mod.prepend_dispatch_header("Task body.")
    assert "never invent an author" in result


# A docstring after an import is evaluated and discarded: __doc__ stays None for help() and seedgo.


def test_header_module_has_a_real_docstring():
    """The defect itself: __doc__ is populated, not silently discarded."""
    assert "Email Header Handler" in (mod.__doc__ or "")


def test_header_docstring_opens_the_module_body():
    """The MECHANISM, separately from the outcome: the string is statement zero.

    Pinned apart so a future red names which one moved.
    """
    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    first = tree.body[0]
    assert isinstance(first, ast.Expr), f"module opens with {type(first).__name__}"
    assert isinstance(first.value, ast.Constant)
    assert isinstance(first.value.value, str)
    # Any opening literal passes the shape checks; tying it to __doc__ makes mechanism and outcome one string.
    assert first.value.value == mod.__doc__, "the opening literal IS the docstring, not a string beside it"


def _discarded_module_strings(source: str) -> list:
    """Line numbers of module-level strings Python evaluates and throws away, when there is no real docstring."""
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
    # An opening f-string reads as a docstring but is a JoinedStr: __doc__ stays None.
    if tree.body:
        first = tree.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.JoinedStr):
            discarded.append(first.lineno)
    return sorted(discarded)


_DEFECT_SHAPE = '"""Not the docstring."""'
_CURED_SHAPE = '"""The docstring."""'


def test_the_sweep_convicts_the_defect_shape():
    """Negative control. A matcher that convicts nothing reports any tree clean."""
    guilty = f"import os\n\n{_DEFECT_SHAPE}\n"
    assert _discarded_module_strings(guilty) == [3]


def test_the_sweep_acquits_a_real_docstring():
    """Positive control. The cured shape — string first, import after — is clean."""
    cured = f"{_CURED_SHAPE}\n\nimport os\n"
    assert _discarded_module_strings(cured) == []


def test_the_sweep_convicts_an_fstring_opener():
    """An f-string reads as the docstring and is not one."""
    guilty = 'f"""Module {1}."""\n\nimport os\n'
    assert _discarded_module_strings(guilty) == [1]


def _branch_sources(root):
    """Every .py under root, never inside a dropbox, .archive or __pycache__.

    Names are judged relative to root: a checkout under a directory named dropbox is still walked.
    """
    for source in root.rglob("*.py"):
        if not _SWEEP_SKIP_DIRS.intersection(source.relative_to(root).parts[:-1]):
            yield source


def test_the_tree_walk_never_enters_a_dropbox_or_an_archive(tmp_path):
    """A file placed in a dropbox or .archive under the walked root is not visited.

    The root sits inside a dropbox, so a filter on the whole path would drop kept.py too.
    """
    root = tmp_path / "dropbox" / "root"
    (root / "live").mkdir(parents=True)
    (root / "live" / "kept.py").write_text("", encoding="utf-8")
    for skipped in ("dropbox", ".archive"):
        (root / "live" / skipped).mkdir()
        (root / "live" / skipped / "planted.py").write_text("", encoding="utf-8")

    visited = [source.relative_to(root).as_posix() for source in _branch_sources(root)]

    assert visited == ["live/kept.py"]


def test_no_module_in_the_tree_documents_itself_into_the_void():
    """Tree-wide: the species dies everywhere in this branch, not just here."""
    apps = Path(__file__).resolve().parents[1] / "apps"
    scanned, offenders = 0, []
    for source in _branch_sources(apps):
        scanned += 1
        lines = _discarded_module_strings(source.read_text(encoding="utf-8"))
        if lines:
            offenders.append(f"{source.name}:{lines}")

    # Arming probe: a wrong root or renamed apps/ would otherwise read as a clean tree.
    assert scanned > 30, f"sweep only visited {scanned} files — wrong root?"
    assert offenders == [], f"module strings Python discards: {offenders}"
