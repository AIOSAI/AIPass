"""Tests for email header handler -- get_dispatch_header, prepend_dispatch_header."""

import pytest
from unittest.mock import MagicMock

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
