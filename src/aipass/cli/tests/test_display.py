"""Unit tests for CLI display module -- Rich-formatted terminal output."""

import importlib
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from aipass.cli.apps.modules import display


# =============================================================================
# Helpers
# =============================================================================


def _make_capture_console():
    """Return (console, get_output) for capturing Rich output.

    Uses no_color=True so assertions can match plain text without ANSI escapes.
    """
    buf = StringIO()
    cons = Console(file=buf, no_color=True, width=120, highlight=False)

    def get_output() -> str:
        return buf.getvalue()

    return cons, get_output


# =============================================================================
# handle_command routing tests
# =============================================================================


class TestHandleCommandRouting:
    """Verify handle_command dispatches to the correct function and returns the right bool."""

    @patch.object(display, "run_demo")
    def test_demo_command_calls_run_demo(self, mock_run_demo):
        result = display.handle_command("demo", [])
        mock_run_demo.assert_called_once()
        assert result is True

    @patch.object(display, "print_introspection")
    def test_display_no_args_calls_introspection(self, mock_introspection):
        result = display.handle_command("display", [])
        mock_introspection.assert_called_once()
        assert result is True

    @patch.object(display, "print_introspection")
    def test_show_no_args_calls_introspection(self, mock_introspection):
        result = display.handle_command("show", [])
        mock_introspection.assert_called_once()
        assert result is True

    @patch.object(display, "print_help")
    def test_display_help_flag(self, mock_help):
        result = display.handle_command("display", ["--help"])
        mock_help.assert_called_once()
        assert result is True

    @patch.object(display, "print_help")
    def test_display_dash_h_flag(self, mock_help):
        result = display.handle_command("display", ["-h"])
        mock_help.assert_called_once()
        assert result is True

    @patch.object(display, "print_help")
    def test_show_help_word(self, mock_help):
        result = display.handle_command("show", ["help"])
        mock_help.assert_called_once()
        assert result is True

    @patch.object(display, "run_demo")
    def test_display_demo_subcommand(self, mock_run_demo):
        result = display.handle_command("display", ["demo"])
        mock_run_demo.assert_called_once()
        assert result is True

    @patch.object(display, "run_demo")
    def test_show_demo_subcommand(self, mock_run_demo):
        result = display.handle_command("show", ["demo"])
        mock_run_demo.assert_called_once()
        assert result is True

    def test_unknown_command_returns_false(self):
        result = display.handle_command("foobar", [])
        assert result is False

    # help_flag_safety — a help flag ANYWHERE means explain, never execute.
    # run_demo is patched out in every case: a question must not reach a doing path.

    @patch.object(display, "run_demo")
    @patch.object(display, "print_help")
    def test_help_flag_after_demo_prints_help(self, mock_help, mock_run_demo):
        """`display demo --help` — flag at args[1] must still be read."""
        result = display.handle_command("display", ["demo", "--help"])
        mock_help.assert_called_once()
        mock_run_demo.assert_not_called()
        assert result is True

    @patch.object(display, "run_demo")
    @patch.object(display, "print_help")
    def test_dash_h_after_demo_prints_help(self, mock_help, mock_run_demo):
        result = display.handle_command("show", ["demo", "-h"])
        mock_help.assert_called_once()
        mock_run_demo.assert_not_called()
        assert result is True

    @patch.object(display, "run_demo")
    @patch.object(display, "print_help")
    def test_demo_as_command_with_help_flag_prints_help(self, mock_help, mock_run_demo):
        """`drone @cli demo --help` — verb arrives in command, flag in args."""
        result = display.handle_command("demo", ["--help"])
        mock_help.assert_called_once()
        mock_run_demo.assert_not_called()
        assert result is True

    @patch.object(display, "run_demo")
    @patch.object(display, "print_help")
    def test_help_flag_at_any_later_position_prints_help(self, mock_help, mock_run_demo):
        result = display.handle_command("display", ["demo", "extra", "--help"])
        mock_help.assert_called_once()
        mock_run_demo.assert_not_called()
        assert result is True

    def test_display_unknown_subcommand_returns_false(self):
        result = display.handle_command("display", ["unknown_sub"])
        assert result is False

    def test_handle_command_returns_bool(self):
        """handle_command always returns a bool — return type contract."""
        result = display.handle_command("nonexistent", [])
        assert isinstance(result, bool)


# =============================================================================
# header() output tests
# =============================================================================


class TestHeader:
    """Verify header() renders title and optional details."""

    def test_header_contains_title(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.header("My Title")
        output = get_output()
        assert "My Title" in output

    def test_header_renders_details(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.header("Build", details={"Branch": "main", "Status": "ok"})
        output = get_output()
        assert "Branch:" in output
        assert "main" in output
        assert "Status:" in output
        assert "ok" in output

    def test_header_without_details_omits_kv(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.header("Solo Title")
        output = get_output()
        # Should have the title but not a key-value separator pattern
        assert "Solo Title" in output

    def test_header_fires_trigger_when_available(self):
        cons, _get_output = _make_capture_console()
        mock_trigger = MagicMock()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", mock_trigger),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.header("Triggered Title")
        mock_trigger.fire.assert_called_once_with("cli_header_displayed", title="Triggered Title")


# =============================================================================
# success() output tests
# =============================================================================


class TestSuccess:
    """Verify success() renders message and kwargs."""

    def test_success_contains_message(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.success("All good")
        output = get_output()
        assert "All good" in output

    def test_success_contains_kwargs(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.success("Done", items=5, time="1.2s")
        output = get_output()
        assert "items: 5" in output
        assert "time: 1.2s" in output


# =============================================================================
# error() output tests
# =============================================================================


class TestError:
    """Verify error() renders to stderr console with optional suggestion."""

    def test_error_contains_message(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            display.error("Something broke")
        output = get_output()
        assert "Something broke" in output

    def test_error_contains_suggestion(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            display.error("Not found", suggestion="Check spelling")
        output = get_output()
        assert "Check spelling" in output
        assert "Try:" in output

    def test_error_without_suggestion_omits_try(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            display.error("Oops")
        output = get_output()
        assert "Try:" not in output


# =============================================================================
# warning() output tests
# =============================================================================


class TestWarning:
    """Verify warning() renders to stderr console with optional details."""

    def test_warning_contains_message(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            display.warning("Heads up")
        output = get_output()
        assert "Heads up" in output

    def test_warning_contains_details(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            display.warning("Version mismatch", details="Expected v2, got v1")
        output = get_output()
        assert "Expected v2, got v1" in output


# =============================================================================
# section() output tests
# =============================================================================


class TestSection:
    """Verify section() renders title and separator."""

    def test_section_contains_title(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.section("Results")
        output = get_output()
        assert "Results" in output

    def test_section_contains_separator_line(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.section("Results")
        output = get_output()
        assert "\u2500" * 50 in output


# =============================================================================
# run_demo() integration test
# =============================================================================


class TestRunDemo:
    """Verify run_demo logs operation and produces output."""

    @patch("aipass.cli.apps.handlers.json.json_handler.log_operation")
    def test_run_demo_logs_operation(self, mock_log):
        cons, _ = _make_capture_console()
        err_cons, _ = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.run_demo()
        mock_log.assert_called_once_with("display_demo")

    @patch("aipass.cli.apps.handlers.json.json_handler.log_operation")
    def test_run_demo_renders_expected_content(self, mock_log):
        cons, get_output = _make_capture_console()
        err_cons, get_err_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "err_console", err_cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.run_demo()
        output = get_output()
        assert "Demo" in output
        assert "successfully" in output
        assert "Rich library" in output


# =============================================================================
# fatal() output tests
# =============================================================================


class TestFatal:
    """Verify fatal() renders error to stderr console and exits with code 1."""

    def test_fatal_contains_message(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            with pytest.raises(SystemExit) as exc_info:
                display.fatal("Critical failure")
        output = get_output()
        assert "Critical failure" in output
        assert exc_info.value.code == 1

    def test_fatal_with_suggestion(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            with pytest.raises(SystemExit) as exc_info:
                display.fatal("Config missing", suggestion="Run aipass init")
        output = get_output()
        assert "Config missing" in output
        assert "Try:" in output
        assert "Run aipass init" in output
        assert exc_info.value.code == 1

    def test_fatal_without_suggestion_omits_try(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "err_console", cons):
            with pytest.raises(SystemExit):
                display.fatal("Crash")
        output = get_output()
        assert "Try:" not in output


# =============================================================================
# Infrastructure mocking tests
# =============================================================================


class TestPrintIntrospectionOutput:
    """Verify print_introspection() body produces expected Rich output."""

    def test_print_introspection_contains_module_name(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.print_introspection()
        output = get_output()
        assert "CLI Display Module" in output

    def test_print_introspection_lists_all_functions(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.print_introspection()
        output = get_output()
        for fn in ("header()", "success()", "error()", "warning()", "fatal()", "section()", "console"):
            assert fn in output

    def test_print_introspection_shows_help_hint(self):
        cons, get_output = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.print_introspection()
        output = get_output()
        assert "drone @cli display --help" in output


class TestPrintHelpOutput:
    """Verify print_help() body produces expected Rich output."""

    def test_print_help_contains_header(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "CLI Display Module" in output

    def test_print_help_contains_what_is_section(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "WHAT IS DISPLAY?" in output

    def test_print_help_contains_public_api_table(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "PUBLIC API FUNCTIONS" in output
        for fn in ("header()", "success()", "error()", "warning()", "fatal()", "section()"):
            assert fn in output

    def test_print_help_contains_usage_section(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "USAGE:" in output
        assert "drone @cli display" in output

    def test_print_help_contains_code_examples(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "CODE EXAMPLES:" in output
        assert "from aipass.cli" in output

    def test_print_help_contains_integration_section(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "INTEGRATION:" in output

    def test_print_help_contains_reference_section(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "REFERENCE:" in output
        assert "Module:" in output

    def test_print_help_contains_tip(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "TIP:" in output
        assert "drone @cli display demo" in output

    def test_print_help_contains_commands_line(self):
        cons, get_output = _make_capture_console()
        with (
            patch.object(display, "CONSOLE", cons),
            patch.object(display, "_TRIGGER", None),
            patch.object(display, "_TRIGGER_LOADED", True),
        ):
            display.print_help()
        output = get_output()
        assert "Commands:" in output


class TestHeaderTriggerLoading:
    """Verify header() lazy-loads trigger module."""

    def test_header_loads_trigger_on_first_call(self):
        cons, _get_output = _make_capture_console()
        original_loaded = display._TRIGGER_LOADED
        original_trigger = display._TRIGGER
        try:
            display._TRIGGER_LOADED = False
            display._TRIGGER = None
            with patch.object(display, "CONSOLE", cons):
                display.header("Test")
            assert display._TRIGGER_LOADED is True
        finally:
            display._TRIGGER_LOADED = original_loaded
            display._TRIGGER = original_trigger

    def test_header_handles_import_error_for_trigger(self):
        cons, _get_output = _make_capture_console()
        display._TRIGGER_LOADED = False
        display._TRIGGER = None
        with (
            patch.object(display, "CONSOLE", cons),
            patch.dict("sys.modules", {"aipass.trigger.apps.modules.core": None}),
        ):
            display._TRIGGER_LOADED = False
            display.header("Trigger Fail Test")
        assert display._TRIGGER_LOADED is True
        assert display._TRIGGER is None


class TestInfrastructureMocking:
    """Verify display module can be safely reloaded after sys.modules mocking."""

    def test_reimport_after_mock(self):
        """Module remains functional after importlib.reload."""
        importlib.reload(display)

        assert hasattr(display, "handle_command")
        assert callable(display.handle_command)

        result = display.handle_command("nonexistent", [])
        assert result is False

    def test_sys_modules_contains_display(self):
        """Display module is properly registered in sys.modules."""
        module_key = "aipass.cli.apps.modules.display"
        assert module_key in sys.modules
        assert sys.modules[module_key] is display


# =============================================================================
# Exit-code failure-flag tests
# =============================================================================


class TestCommandState:
    """Verify the process-level failure flag and resolve_exit truth table."""

    def setup_method(self):
        display.reset_command_state()

    def teardown_method(self):
        display.reset_command_state()

    def test_initial_state_is_not_failed(self):
        assert display.command_failed() is False

    def test_mark_command_failed_sets_flag(self):
        display.mark_command_failed()
        assert display.command_failed() is True

    def test_reset_command_state_clears_flag(self):
        display.mark_command_failed()
        display.reset_command_state()
        assert display.command_failed() is False

    def test_resolve_exit_not_handled(self):
        assert display.resolve_exit(handled=False) == 1

    def test_resolve_exit_handled_ok(self):
        assert display.resolve_exit(handled=True) == 0

    def test_resolve_exit_handled_failed(self):
        display.mark_command_failed()
        assert display.resolve_exit(handled=True) == 2

    def test_resolve_exit_not_handled_ignores_flag(self):
        display.mark_command_failed()
        assert display.resolve_exit(handled=False) == 1

    def test_error_trips_failure_flag(self):
        cons, _ = _make_capture_console()
        with patch.object(display, "err_console", cons):
            display.error("something broke")
        assert display.command_failed() is True

    def test_warning_does_not_trip_flag(self):
        cons, _ = _make_capture_console()
        with patch.object(display, "err_console", cons):
            display.warning("just a warning")
        assert display.command_failed() is False

    def test_success_does_not_trip_flag(self):
        cons, _ = _make_capture_console()
        with patch.object(display, "CONSOLE", cons):
            display.success("all good")
        assert display.command_failed() is False
