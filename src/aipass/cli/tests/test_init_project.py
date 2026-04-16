"""Tests for the CLI init_project module — aipass command routing and init orchestration."""

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from aipass.cli.apps.modules import init_project
from aipass.cli.apps.modules.init_project import handle_command, _handle_init


# =============================================================================
# Helpers
# =============================================================================

def _make_capture_console():
    """Return (console, get_output) for capturing Rich output."""
    buf = StringIO()
    cons = Console(file=buf, no_color=True, width=120, highlight=False)
    return cons, lambda: buf.getvalue()


# =============================================================================
# handle_command routing tests
# =============================================================================

class TestHandleCommandRouting:
    """Verify handle_command dispatches correctly and returns the right boolean."""

    def test_non_aipass_command_returns_false(self):
        """Commands other than 'aipass' should return False."""
        assert handle_command("other", []) is False
        assert handle_command("display", []) is False
        assert handle_command("", []) is False

    def test_aipass_no_args_calls_introspection(self):
        """'aipass' with no args shows introspection."""
        with patch.object(init_project, "print_introspection") as mock:
            result = handle_command("aipass", [])
        assert result is True
        mock.assert_called_once()

    def test_aipass_help_flag(self):
        """'aipass --help' shows full help."""
        with patch.object(init_project, "print_help") as mock:
            result = handle_command("aipass", ["--help"])
        assert result is True
        mock.assert_called_once()

    def test_aipass_dash_h_flag(self):
        """'aipass -h' shows full help."""
        with patch.object(init_project, "print_help") as mock:
            result = handle_command("aipass", ["-h"])
        assert result is True
        mock.assert_called_once()

    def test_aipass_help_word(self):
        """'aipass help' shows full help."""
        with patch.object(init_project, "print_help") as mock:
            result = handle_command("aipass", ["help"])
        assert result is True
        mock.assert_called_once()

    def test_aipass_init_routes_to_handle_init(self):
        """'aipass init' routes to _handle_init."""
        with patch.object(init_project, "_handle_init", return_value=True) as mock:
            result = handle_command("aipass", ["init"])
        assert result is True
        mock.assert_called_once_with([])

    def test_aipass_init_with_args_passes_through(self):
        """'aipass init /path Name' passes args to _handle_init."""
        with patch.object(init_project, "_handle_init", return_value=True) as mock:
            result = handle_command("aipass", ["init", "/path", "MyProj"])
        assert result is True
        mock.assert_called_once_with(["/path", "MyProj"])

    def test_unknown_subcommand_shows_error(self):
        """Unknown aipass subcommand shows error and returns True."""
        cons, get_output = _make_capture_console()
        err_cons, get_err = _make_capture_console()
        with patch.object(init_project, "console", cons), \
             patch.object(init_project, "error") as mock_error:
            result = handle_command("aipass", ["bogus"])
        assert result is True
        mock_error.assert_called_once()
        args = mock_error.call_args
        assert "bogus" in args[0][0]


# =============================================================================
# _handle_init tests
# =============================================================================

class TestHandleInit:
    """Tests for the init subcommand orchestration."""

    def test_init_help_flag(self):
        """'init --help' shows init help and returns True."""
        with patch.object(init_project, "_print_init_help") as mock:
            result = _handle_init(["--help"])
        assert result is True
        mock.assert_called_once()

    def test_init_success_displays_output(self, tmp_path):
        """Successful init displays results and logs the operation."""
        target = tmp_path / "my_project"
        cons, get_output = _make_capture_console()
        err_cons, get_err = _make_capture_console()

        from aipass.cli.apps.modules import display
        with patch.object(init_project, "console", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch.object(display, "err_console", err_cons), \
             patch.object(display, "_TRIGGER", None), \
             patch.object(display, "_TRIGGER_LOADED", True), \
             patch.object(init_project, "json_handler") as mock_json, \
             patch.object(init_project, "logger"):
            result = _handle_init([str(target)])

        assert result is True
        output = get_output()
        assert "Project Initialized" in output
        mock_json.log_operation.assert_called_once()
        call_args = mock_json.log_operation.call_args
        assert call_args[0][0] == "aipass_init"

    def test_init_value_error_exits(self, tmp_path):
        """ValueError from init_project causes error display and sys.exit(1)."""
        with patch.object(init_project, "init_project", side_effect=ValueError("bad name")), \
             patch.object(init_project, "error") as mock_error, \
             patch.object(init_project, "logger"), \
             pytest.raises(SystemExit) as exc_info:
            _handle_init([str(tmp_path)])
        assert exc_info.value.code == 1
        mock_error.assert_called_once()
        assert "bad name" in mock_error.call_args[0][0]

    def test_init_file_exists_error_exits(self, tmp_path):
        """FileExistsError from init_project causes error display and sys.exit(1)."""
        with patch.object(init_project, "init_project", side_effect=FileExistsError("already exists")), \
             patch.object(init_project, "error") as mock_error, \
             patch.object(init_project, "logger"), \
             pytest.raises(SystemExit) as exc_info:
            _handle_init([str(tmp_path)])
        assert exc_info.value.code == 1
        mock_error.assert_called_once()

    def test_init_os_error_exits(self, tmp_path):
        """OSError from init_project causes error display and sys.exit(1)."""
        with patch.object(init_project, "init_project", side_effect=OSError("disk full")), \
             patch.object(init_project, "error") as mock_error, \
             patch.object(init_project, "logger"), \
             pytest.raises(SystemExit) as exc_info:
            _handle_init([str(tmp_path)])
        assert exc_info.value.code == 1
        mock_error.assert_called_once()

    def test_init_uses_caller_cwd_env(self, tmp_path):
        """When no target arg, uses AIPASS_CALLER_CWD env var."""
        import os
        target = tmp_path / "env_project"
        target.mkdir()

        cons, get_output = _make_capture_console()
        err_cons, get_err = _make_capture_console()

        from aipass.cli.apps.modules import display
        with patch.dict(os.environ, {"AIPASS_CALLER_CWD": str(target)}), \
             patch.object(init_project, "console", cons), \
             patch.object(display, "CONSOLE", cons), \
             patch.object(display, "err_console", err_cons), \
             patch.object(display, "_TRIGGER", None), \
             patch.object(display, "_TRIGGER_LOADED", True), \
             patch.object(init_project, "json_handler"), \
             patch.object(init_project, "logger"):
            result = _handle_init([])

        assert result is True
        output = get_output()
        assert "Project Initialized" in output
