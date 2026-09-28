# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests (adapted for API module structure)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/api_key.py's command routing, help and introspection."""

# CLI Routing Tests for API branch.
#
# API has handle_command in module files (api_key.py, openrouter_client.py, etc.)
# rather than a standalone cli_handler. Tests adapted accordingly.
#
# Covers 9 items:
#   - help_flag, short_help, help_word, no_args, unknown_command,
#     return_bool, print_help, print_introspection, output_capture

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — get_key(), validate_key() and get_secret_cmd() bodies, tests/test_api_key.py
# seedgo: no-test-needed(cli) — the console and header rendering itself, owned by @cli

from unittest.mock import patch


from aipass.api.apps.modules import api_key


# ---------------------------------------------------------------------------
# handle_command routing tests
# ---------------------------------------------------------------------------


# The key source is replaced in every routing test: a help gate that let the
# command through would otherwise read a real key.
KEYS = "aipass.api.apps.modules.api_key.keys"


def _assert_help_shown_and_nothing_run(capsys, mock_keys, mock_jh):
    """The help text reached stdout and no key was looked up or logged."""
    out = capsys.readouterr().out
    assert "API_KEY — Manage API keys and credentials" in out
    assert "COMMANDS:" in out
    mock_keys.get_api_key.assert_not_called()
    mock_jh.log_operation.assert_not_called()


@patch(KEYS, autospec=True)
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_help_flag(mock_jh, mock_keys, capsys):
    """handle_command with --help flag shows help and runs nothing."""
    result = api_key.handle_command("get-key", ["--help"])
    assert result is True
    _assert_help_shown_and_nothing_run(capsys, mock_keys, mock_jh)


@patch(KEYS, autospec=True)
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_short_help(mock_jh, mock_keys, capsys):
    """handle_command with -h flag shows help and runs nothing."""
    result = api_key.handle_command("validate", ["-h"])
    assert result is True
    _assert_help_shown_and_nothing_run(capsys, mock_keys, mock_jh)


@patch(KEYS, autospec=True)
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_help_word(mock_jh, mock_keys, capsys):
    """handle_command with 'help' as arg shows help and runs nothing."""
    result = api_key.handle_command("get-key", ["help"])
    assert result is True
    _assert_help_shown_and_nothing_run(capsys, mock_keys, mock_jh)


@patch(KEYS, autospec=True)
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_no_args(mock_jh, mock_keys, capsys):
    """get-key with no args runs get_key for the default provider (openrouter)."""
    mock_keys.get_api_key.return_value = None

    result = api_key.handle_command("get-key", [])

    assert result is True
    mock_keys.get_api_key.assert_called_once_with("openrouter")
    captured = capsys.readouterr()
    assert "Get API Key - openrouter" in captured.out
    assert "Failed to retrieve API key for openrouter" in captured.out + captured.err


@patch(KEYS, autospec=True)
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_unknown(mock_jh, mock_keys, capsys):
    """handle_command with unknown command returns False and does nothing."""
    result = api_key.handle_command("bogus_unknown", [])
    assert result is False
    assert capsys.readouterr().out == ""
    mock_keys.get_api_key.assert_not_called()


@patch(KEYS, autospec=True)
@patch("aipass.api.apps.modules.api_key.json_handler", autospec=True)
def test_handle_command_return_bool(mock_jh, mock_keys, capsys):
    """handle_command always returns a bool (True or False)."""
    result_true = api_key.handle_command("get-key", ["--help"])
    result_false = api_key.handle_command("bogus_xyz", [])
    assert isinstance(result_true, bool)
    assert isinstance(result_false, bool)
    assert result_true is True
    assert result_false is False
    assert "COMMANDS:" in capsys.readouterr().out


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


def test_print_help_produces_output(capsys):
    """
    print_help routes its text through console, not a bare print.

    `console.print.called or header.called` was true if either fired, so the
    test survived losing the entire body of the help as long as the header
    banner still ran. What is worth pinning here is the ROUTING — this branch
    prints through @cli, and a stray print() would bypass the formatting every
    other command obeys.
    """
    api_key.print_help()

    printed = capsys.readouterr().out
    assert "get-key" in printed
    # Rich consumed the markup: a bare print() would leave the tags in the text.
    assert "[cyan]" not in printed, "the help text no longer goes through the shared console"


def test_print_introspection_produces_output(capsys):
    """
    The self-map names the handlers this module actually reaches.

    Same shape as the help test above and the same weakness: an `or` of two
    "was called" booleans. The introspection is what a bare `drone @api`
    prints, and its whole job is to be an accurate map — so it is pinned on
    naming a handler that really is wired in, not on having run.
    """
    api_key.print_introspection()

    printed = capsys.readouterr().out
    assert "API Key Module Introspection" in printed
    assert "[cyan]" not in printed, "the self-map no longer goes through the shared console"
    assert "handlers.auth.keys" in printed, "the self-map stopped naming the handler it reads keys through"
