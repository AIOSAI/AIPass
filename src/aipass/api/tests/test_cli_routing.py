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
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_help_flag(mock_jh, mock_header, mock_console):
    """handle_command with --help flag returns True."""
    result = api_key.handle_command("get-key", ["--help"])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_short_help(mock_jh, mock_header, mock_console):
    """handle_command with -h flag returns True."""
    result = api_key.handle_command("validate", ["-h"])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_help_word(mock_jh, mock_header, mock_console):
    """handle_command with 'help' as arg returns True."""
    result = api_key.handle_command("get-key", ["help"])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_no_args(mock_jh, mock_header, mock_console):
    """handle_command with no args triggers introspection, returns True."""
    result = api_key.handle_command("get-key", [])
    assert result is True


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_unknown(mock_jh, mock_header, mock_console):
    """handle_command with unknown command returns False."""
    result = api_key.handle_command("bogus_unknown", [])
    assert result is False


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
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
    """
    --help names every command the module actually routes.

    This asserted only that SOMETHING was printed until 2026-09-07, which is
    an assertion that cannot fail while the function prints anything at all —
    a help text that had lost half its commands passed it. Measured against
    the real output: the five verbs below are the ones this help lists, and
    the point of the test is that a command deleted from the help is a command
    an operator can no longer find.
    """
    api_key.print_help()

    printed = capsys.readouterr().out

    for command in ("get-key", "get-secret", "validate", "list-providers", "init"):
        assert command in printed, f"--help no longer names {command}"


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_print_help_produces_output(mock_jh, mock_header, mock_console):
    """
    print_help routes its text through console, not a bare print.

    `console.print.called or header.called` was true if either fired, so the
    test survived losing the entire body of the help as long as the header
    banner still ran. What is worth pinning here is the ROUTING — this branch
    prints through @cli, and a stray print() would bypass the formatting every
    other command obeys.
    """
    api_key.print_help()

    assert mock_console.print.called, "the help text no longer goes through the shared console"
    printed = " ".join(str(call) for call in mock_console.print.call_args_list)
    assert "get-key" in printed


@patch("aipass.api.apps.modules.api_key.console")
@patch("aipass.api.apps.modules.api_key.header")
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_print_introspection_produces_output(mock_jh, mock_header, mock_console):
    """
    The self-map names the handlers this module actually reaches.

    Same shape as the help test above and the same weakness: an `or` of two
    "was called" booleans. The introspection is what a bare `drone @api`
    prints, and its whole job is to be an accurate map — so it is pinned on
    naming a handler that really is wired in, not on having run.
    """
    api_key.print_introspection()

    assert mock_console.print.called, "the self-map no longer goes through the shared console"
    printed = " ".join(str(call) for call in mock_console.print.call_args_list)
    assert "handlers.auth.keys" in printed, "the self-map stopped naming the handler it reads keys through"
