# =================== AIPass ====================
# Name: test_help_flag_safety.py
# Description: A help flag anywhere in args must explain, never execute (DPLAN-0291 rule E)
# Version: 1.0.1
# Created: 2026-08-13
# Modified: 2026-09-27
# =============================================

"""Tests for a trailing --help in apps/modules/feedback.py, admin_grant.py, watchdog.py and compass.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(help_flag_safety) — that each handle_command calls _wants_help before acting

from unittest.mock import patch

import pytest

from aipass.devpulse.apps.modules import admin_grant as ag_mod
from aipass.devpulse.apps.modules import compass as compass_mod
from aipass.devpulse.apps.modules import feedback as fb_mod
from aipass.devpulse.apps.modules import watchdog as wd_mod


def _output(capsys) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_watchdog_trailing_help_never_executes(capsys):
    """watchdog status --help -> HELP_TEXT, _handle_status never called."""
    with (
        patch.object(wd_mod, "_guard_caller", return_value=True),
        patch.object(wd_mod, "_handle_status") as canary,
    ):
        result = wd_mod.handle_command("watchdog", ["status", "--help"])
    assert result is True
    canary.assert_not_called()
    assert "watchdog" in _output(capsys).lower()


def test_compass_trailing_help_never_executes(capsys):
    """compass query <term> --help -> HELP_TEXT, _handle_query never called."""
    with patch.object(compass_mod, "_handle_query") as canary:
        result = compass_mod.handle_command("compass", ["query", "trap", "--help"])
    assert result is True
    canary.assert_not_called()
    assert "compass" in _output(capsys).lower()


def test_admin_grant_trailing_help_never_executes(capsys):
    """admin_grant status --help -> HELP_TEXT, _cmd_status never called."""
    with patch.object(ag_mod, "_cmd_status") as canary:
        result = ag_mod.handle_command("admin_grant", ["status", "--help"])
    assert result is True
    canary.assert_not_called()
    assert "admin_grant" in _output(capsys).lower()


def test_feedback_trailing_help_never_executes(capsys):
    """feedback inbox --help -> HELP_TEXT, list_messages never called."""
    with (
        patch.object(fb_mod, "_guard_caller", return_value=True),
        patch.object(fb_mod, "list_messages") as canary,
    ):
        result = fb_mod.handle_command("feedback", ["inbox", "--help"])
    assert result is True
    canary.assert_not_called()
    assert "feedback" in _output(capsys).lower()


@pytest.mark.parametrize(
    ("mod", "cmd", "args", "handler"),
    [
        (wd_mod, "watchdog", ["agent", "@target", "-h"], "_handle_agent"),
        (compass_mod, "compass", ["add", "ctx", "decision", "-h"], "_handle_add"),
    ],
)
def test_short_help_flag_mid_args_never_executes(mod, cmd, args, handler, capsys):
    """-h anywhere is the same contract as --help anywhere.

    The handler the command would reach is the canary: help outranks the caller
    gate in watchdog and compass has no gate, so no guard is patched here (the
    old create=True patch made a _guard_caller on compass that nothing read).
    Mutant: `_wants_help` answering False in either module -> red.
    """
    with patch.object(mod, handler) as canary:
        result = mod.handle_command(cmd, args)
    assert result is True
    canary.assert_not_called()
    out = _output(capsys).lower()
    assert "usage:" in out


def test_compass_value_containing_help_word_still_executes():
    """A quoted VALUE that merely contains the word help is not a help flag.

    Bare word 'help' triggers only at position 0; later positions must be
    exact --help/-h. Guards the predicate against over-matching free text.
    """
    with patch.object(compass_mod, "_handle_query", return_value=True) as target:
        result = compass_mod.handle_command("compass", ["query", "how help works"])
    assert result is True
    target.assert_called_once()
