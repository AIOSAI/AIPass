# =================== AIPass ====================
# Name: test_monitoring_handlers_display.py
# Description: Unit tests for the monitor's command parsing and stream display
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/monitoring/interactive_filter.py and unified_stream.py, the command and display."""

# Covers:
# - interactive_filter: parse_command, get_help_text
# - unified_stream: print_event, print_command_separator

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — print_hook_event(), covered by tests/test_display_resilience.py

import io
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from aipass.prax.apps.handlers.monitoring import interactive_filter, unified_stream

# =============================================
# INTERACTIVE FILTER TESTS
# =============================================


def _import_interactive_filter():
    """The interactive_filter module, bound at the top of this file; it holds no state."""
    return interactive_filter


class TestParseCommand:
    """Tests for parse_command()."""

    def test_simple_command(self):
        """Should parse single-word command."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("status")
        assert cmd == "status"
        assert args == []

    def test_command_with_args(self):
        """Should parse command with arguments."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("watch PRAX CLI")
        assert cmd == "watch"
        assert args == ["PRAX", "CLI"]

    def test_empty_string_returns_none(self):
        """Empty input should return (None, [])."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("")
        assert cmd is None
        assert args == []

    def test_whitespace_only_returns_none(self):
        """Whitespace-only input should return (None, [])."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("   ")
        assert cmd is None
        assert args == []

    def test_exit_normalized_to_quit(self):
        """'exit' should be normalized to 'quit'."""
        mod = _import_interactive_filter()
        cmd, _ = mod.parse_command("exit")
        assert cmd == "quit"

    def test_q_normalized_to_quit(self):
        """'q' should be normalized to 'quit'."""
        mod = _import_interactive_filter()
        cmd, _ = mod.parse_command("q")
        assert cmd == "quit"

    def test_uppercase_normalized(self):
        """Commands should be lowercased."""
        mod = _import_interactive_filter()
        cmd, _ = mod.parse_command("STATUS")
        assert cmd == "status"

    def test_leading_trailing_whitespace_stripped(self):
        """Leading and trailing whitespace should be stripped."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("  help  ")
        assert cmd == "help"
        assert args == []

    def test_logs_operation(self):
        """Should call json_handler.log_operation."""
        mod = _import_interactive_filter()
        with patch.object(mod, "json_handler") as recorder:
            mod.parse_command("status")
        recorder.log_operation.assert_called_once_with("filter_applied", {"command": "status", "args": []})


class TestGetHelpText:
    """Tests for get_help_text()."""

    def test_returns_string(self):
        """get_help_text() returns the exact three-command menu the loop prints."""
        mod = _import_interactive_filter()
        result = mod.get_help_text()
        assert isinstance(result, str)
        assert result == (
            "\n"
            "Available Commands:\n"
            "  status          - Show monitoring state\n"
            "  help            - Show this help\n"
            "  quit/exit       - Stop monitoring\n"
        )

    def test_contains_key_commands(self):
        """Help text should mention available commands."""
        mod = _import_interactive_filter()
        result = mod.get_help_text()
        assert "status" in result
        assert "help" in result
        assert "quit" in result

    def test_not_empty(self):
        """Help text should not be empty."""
        mod = _import_interactive_filter()
        result = mod.get_help_text()
        assert len(result.strip()) > 0


# =============================================
# UNIFIED STREAM TESTS
# =============================================


@pytest.fixture
def stream_log(monkeypatch) -> MagicMock:
    """unified_stream is imported once at the top and prints through the real
    console, read with capsys (prax, leg 11). Its logger is doubled where it
    binds it, so no test writes live state."""
    log = MagicMock()
    monkeypatch.setattr(unified_stream, "logger", log)
    return log


def _colour_console(monkeypatch) -> io.StringIO:
    """A real Console on a buffer with colour forced, for this test alone.

    The colour is the claim here and it exists only inside the console call
    (a dict lookup in print_event), and capsys strips it (prax, leg 11)."""
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="standard", width=200)
    monkeypatch.setattr(unified_stream, "console", console)
    return buffer


@pytest.mark.usefixtures("stream_log")
class TestPrintEvent:
    """Tests for print_event()."""

    def test_includes_branch_name(self, capsys):
        """One line reaches the console and it carries the branch name."""
        unified_stream.print_event("log", "SEEDGO", "audit complete")
        # The line carries a host clock, so the count and the label are the claim.
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 1
        assert "[SEEDGO" in lines[0]

    def test_includes_message(self, capsys):
        """Output should include the event message."""
        unified_stream.print_event("system", "CLI", "started successfully")
        assert capsys.readouterr().out.rstrip("\n").endswith(" started successfully")

    def test_with_pid(self, capsys):
        """Output should include PID when provided."""
        unified_stream.print_event("file", "PRAX", "changed", pid=12345)
        assert "[PRAX:12345" in capsys.readouterr().out

    def test_error_level_coloring(self, monkeypatch):
        """Error-level messages should use red color."""
        buffer = _colour_console(monkeypatch)
        unified_stream.print_event("log", "FLOW", "something broke", level="error")
        assert "\x1b[31msomething broke\x1b[0m" in buffer.getvalue()

    def test_branch_color_lookup(self, monkeypatch):
        """Should use branch-specific color from BRANCH_COLORS."""
        buffer = _colour_console(monkeypatch)
        unified_stream.print_event("file", "SEEDGO", "test")
        assert "\x1b[32mSEEDGO " in buffer.getvalue()  # SEEDGO -> green

    def test_unknown_branch_uses_white(self, monkeypatch):
        """Unknown branches should use white as default color."""
        buffer = _colour_console(monkeypatch)
        unified_stream.print_event("file", "XYZUNKNOWN", "test")
        assert "\x1b[37mXYZUNKNOWN " in buffer.getvalue()


@pytest.mark.usefixtures("stream_log")
class TestPrintCommandSeparator:
    """Tests for print_command_separator()."""

    def test_prints_separator(self, capsys):
        """A blank line, a rule, the command, a rule: no context line without caller or target."""
        unified_stream.print_command_separator("PRAX", "seedgo audit")
        assert capsys.readouterr().out.splitlines() == ["", "─" * 60, "▶ seedgo audit", "─" * 60]

    def test_includes_command(self, capsys):
        """Output should include the command text."""
        unified_stream.print_command_separator("CLI", "deploy --force")
        assert "▶ deploy --force" in capsys.readouterr().out.splitlines()

    def test_with_caller(self, capsys):
        """Output should include caller when provided."""
        unified_stream.print_command_separator("SEEDGO", "audit PRAX", caller="DRONE")
        assert "  DRONE" in capsys.readouterr().out.splitlines()

    def test_with_target(self, capsys):
        """Output should include target when provided."""
        unified_stream.print_command_separator("SEEDGO", "audit", target="FLOW")
        assert "  → FLOW" in capsys.readouterr().out.splitlines()

    def test_without_caller_or_target(self, capsys):
        """Should work without caller or target (no context line crash)."""
        unified_stream.print_command_separator("PRAX", "status")
        assert len(capsys.readouterr().out.splitlines()) == 4
