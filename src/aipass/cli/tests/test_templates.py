"""Tests for the CLI templates module — operation output templates."""

import pytest
from io import StringIO
from unittest.mock import patch

from rich.console import Console

from aipass.cli.apps.modules import templates
from aipass.cli.apps.modules import display


@pytest.fixture
def plain_console():
    """Rich Console that writes plain text (no ANSI codes) for assertions."""
    buf = StringIO()
    cons = Console(file=buf, no_color=True, width=120)

    def get_output() -> str:
        return buf.getvalue()

    return cons, get_output


# ============================================================================
# handle_command ROUTING TESTS
# ============================================================================


class TestHandleCommandRouting:
    """Tests for handle_command dispatch logic."""

    @patch.object(templates, "run_demo")
    def test_demo_command_calls_run_demo(self, mock_run_demo):
        result = templates.handle_command("demo", [])
        mock_run_demo.assert_called_once()
        assert result is True

    @patch.object(templates, "print_introspection")
    def test_templates_no_args_calls_introspection(self, mock_introspection):
        result = templates.handle_command("templates", [])
        mock_introspection.assert_called_once()
        assert result is True

    @patch.object(templates, "print_help")
    def test_templates_help_flag(self, mock_help):
        result = templates.handle_command("templates", ["--help"])
        mock_help.assert_called_once()
        assert result is True

    @patch.object(templates, "print_help")
    def test_templates_dash_h_flag(self, mock_help):
        result = templates.handle_command("templates", ["-h"])
        mock_help.assert_called_once()
        assert result is True

    @patch.object(templates, "print_help")
    def test_templates_help_word(self, mock_help):
        result = templates.handle_command("templates", ["help"])
        mock_help.assert_called_once()
        assert result is True

    @patch.object(templates, "run_demo")
    def test_templates_demo_subcommand(self, mock_run_demo):
        result = templates.handle_command("templates", ["demo"])
        mock_run_demo.assert_called_once()
        assert result is True

    def test_unknown_command_returns_false(self):
        result = templates.handle_command("unknown", [])
        assert result is False

    def test_templates_unknown_subcommand_returns_false(self):
        result = templates.handle_command("templates", ["bogus"])
        assert result is False


# ============================================================================
# operation_start OUTPUT TESTS
# ============================================================================


class TestOperationStart:
    """Tests for operation_start output formatting."""

    def test_operation_name_in_output(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_start("Building files")
        output = get_output()
        assert "Building files" in output

    def test_details_in_output(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_start("Deploying", target="/srv/app", mode="fast")
        output = get_output()
        assert "target: /srv/app" in output
        assert "mode: fast" in output

    def test_no_details_omits_detail_lines(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_start("Simple op")
        output = get_output()
        # Should contain the operation name but no key-value detail lines
        assert "Simple op" in output
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        # Only the operation line should have content; no "key: value" lines
        detail_lines = [line for line in lines if ": " in line and "Simple op" not in line]
        assert len(detail_lines) == 0


# ============================================================================
# operation_complete OUTPUT TESTS
# ============================================================================


class TestOperationComplete:
    """Tests for operation_complete output formatting."""

    def test_summary_header_present(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_complete(created=3)
        output = get_output()
        assert "Summary:" in output

    def test_summary_kwargs_in_output(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_complete(created=5, skipped=2)
        output = get_output()
        assert "created: 5" in output
        assert "skipped: 2" in output

    def test_time_kwarg_shows_completion_line(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_complete(files=10, time="2.5s")
        output = get_output()
        assert "Completed in 2.5s" in output

    def test_no_time_kwarg_omits_completion_line(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_complete(files=10)
        output = get_output()
        assert "Completed in" not in output

    def test_separator_line_present(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_complete(created=1)
        output = get_output()
        assert "─" * 50 in output

    def test_no_kwargs_shows_empty_summary(self, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.operation_complete()
        output = get_output()
        assert "Summary:" in output
        # No key-value summary lines should appear after "Summary:"
        lines = output.splitlines()
        summary_idx = next(i for i, line in enumerate(lines) if "Summary:" in line)
        after_summary = [
            line.strip() for line in lines[summary_idx + 1:] if line.strip()
        ]
        kv_lines = [line for line in after_summary if ": " in line]
        assert len(kv_lines) == 0


# ============================================================================
# run_demo TEST
# ============================================================================


class TestRunDemo:
    """Tests for run_demo execution."""

    @patch.object(templates, "json_handler")
    def test_run_demo_logs_operation(self, mock_json, plain_console):
        console, get_output = plain_console
        with patch.object(templates, "CONSOLE", console):
            templates.run_demo()
        mock_json.log_operation.assert_called_once_with("templates_demo")

    @patch.object(templates, "json_handler")
    def test_run_demo_renders_expected_content(self, mock_json, plain_console):
        console, get_output = plain_console
        with (
            patch.object(templates, "CONSOLE", console),
            patch.object(display, "CONSOLE", console),
        ):
            templates.run_demo()
        output = get_output()
        assert "Creating new branch" in output
        assert "Demo" in output
