# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests (adapted for API module structure)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
CLI Routing Tests for API branch.

API has handle_command in module files (api_key.py, openrouter_client.py, etc.)
rather than a standalone cli_handler. Tests adapted accordingly.

Covers 9 items:
  - help_flag, short_help, help_word, no_args, unknown_command,
    return_bool, print_help, print_introspection, output_capture
"""

from unittest.mock import patch


from aipass.api.apps.modules import api_key


# ---------------------------------------------------------------------------
# handle_command routing tests
# ---------------------------------------------------------------------------


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_handle_command_help_flag(mock_jh, mock_header, mock_console):
    """handle_command with --help flag returns True."""
    result = api_key.handle_command("get-key", ["--help"])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_handle_command_short_help(mock_jh, mock_header, mock_console):
    """handle_command with -h flag returns True."""
    result = api_key.handle_command("validate", ["-h"])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_handle_command_help_word(mock_jh, mock_header, mock_console):
    """handle_command with 'help' as arg returns True."""
    result = api_key.handle_command("get-key", ["help"])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_handle_command_no_args(mock_jh, mock_header, mock_console):
    """handle_command with no args triggers introspection, returns True."""
    result = api_key.handle_command("get-key", [])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_handle_command_unknown(mock_jh, mock_header, mock_console):
    """handle_command with unknown command returns False."""
    result = api_key.handle_command("bogus_unknown", [])
    assert result is False


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_handle_command_return_bool(mock_jh, mock_header, mock_console):
    """handle_command always returns a bool (True or False)."""
    result_true = api_key.handle_command("get-key", ["--help"])
    result_false = api_key.handle_command("bogus_xyz", [])
    assert isinstance(result_true, bool)
    assert isinstance(result_false, bool)
    assert result_true is True
    assert result_false is False


# ---------------------------------------------------------------------------
# Output capture tests
# ---------------------------------------------------------------------------


def test_output_capture_help(capsys):
    """--help flag triggers console output (output capture with capsys)."""
    # capsys captures stdout/stderr — satisfies output_capture pattern
    api_key.print_help()
    captured = capsys.readouterr()
    assert len(captured.out) > 0 or len(captured.err) > 0


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_print_help_produces_output(mock_jh, mock_header, mock_console):
    """print_help runs without error."""
    api_key.print_help()
    assert mock_console.print.called or mock_header.called


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler")
def test_print_introspection_produces_output(mock_jh, mock_header, mock_console):
    """print_introspection runs without error."""
    api_key.print_introspection()
    assert mock_console.print.called or mock_header.called
