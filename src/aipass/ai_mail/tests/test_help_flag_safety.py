# =================== AIPass ====================
# Name: test_help_flag_safety.py
# Description: Tests for whole-sequence help-flag detection across the three CLI modules
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Tests for help-flag safety (seedgo ``help_flag_safety``, DPLAN-0291 rule E).

All three modules gated help at ``args[0]`` only, so a flag one position later
was discarded and the command ran instead. For a messaging branch that is not
cosmetic: ``dispatch @target "Subject" "Body" --help`` reached
``_orchestrate_dispatch_send`` and would have *sent the mail and woken the
branch* it was asked to describe. Same class as @drone's ``rm`` shape, where a
trailing ``--help`` deleted the real target first.

A question must never be executed as an instruction. Every test here mocks the
send and wake targets and asserts two things together — help was printed **and**
the side-effecting target was never called. Asserting only the first would pass
on code that explains itself after sending the mail.

Two token classes, deliberately different:

``--help`` / ``-h``
    Unambiguous anywhere in the sequence, matched exactly. Exact match is what
    keeps real mail safe: a body reading "run --help for usage" arrives as one
    quoted argument and is not that token.

``help``
    A legitimate operand — a subject line can be the word "help", and for this
    branch that is a plausible message, not a typo. It therefore only reads as
    a request in the subcommand slot, position 0. None of the three modules
    owns a genuine ``help`` verb, so position 0 is free.
"""

from unittest.mock import patch

from aipass.ai_mail.apps.handlers.cli.help_flags import wants_help
from aipass.ai_mail.apps.modules import dispatch as dispatch_module
from aipass.ai_mail.apps.modules import email as email_module
from aipass.ai_mail.apps.modules import email_send as email_send_module


# =============================================================================
# THE DETECTOR
# =============================================================================


class TestWantsHelp:
    """Pure argument inspection — no I/O, no side effects."""

    def test_empty_args_is_not_a_help_request(self):
        assert wants_help([]) is False

    def test_dashed_flag_at_position_zero(self):
        assert wants_help(["--help"]) is True
        assert wants_help(["-h"]) is True

    def test_dashed_flag_after_the_first_argument(self):
        """The whole point: a flag later in the line still counts."""
        assert wants_help(["@devpulse", "Subject", "Body", "--help"]) is True
        assert wants_help(["@devpulse", "-h"]) is True

    def test_bare_word_counts_only_at_position_zero(self):
        assert wants_help(["help"]) is True
        assert wants_help(["@devpulse", "help"]) is False

    def test_bare_word_can_be_opted_out(self):
        """For a module that owns a genuine `help` verb."""
        assert wants_help(["help"], allow_bare_word=False) is False
        assert wants_help(["help", "--help"], allow_bare_word=False) is True

    def test_match_is_exact_so_real_message_bodies_survive(self):
        """Quoted free text arrives as ONE argument and must stay content."""
        assert wants_help(["@devpulse", "Subject", "run --help for usage"]) is False
        assert wants_help(["@devpulse", "--help is broken", "body"]) is False
        assert wants_help(["@devpulse", "Subject", "helpful"]) is False

    def test_a_body_that_is_exactly_the_flag_explains_rather_than_sends(self):
        """Nonsense input, and explain-over-execute is the ruling."""
        assert wants_help(["@devpulse", "Subject", "--help"]) is True


# =============================================================================
# DISPATCH — THE DANGEROUS ONE (sends mail AND wakes a branch)
# =============================================================================


class TestDispatchHelpSafety:
    """A help probe must never send mail or wake a branch."""

    def test_trailing_help_never_reaches_the_send_and_wake_path(self):
        with (
            patch.object(dispatch_module, "_orchestrate_dispatch_send") as send,
            patch.object(dispatch_module, "print_help") as help_out,
        ):
            handled = dispatch_module.handle_command("dispatch", ["@devpulse", "Subject", "Body", "--help"])

        assert handled is True
        help_out.assert_called_once()
        send.assert_not_called()

    def test_trailing_help_never_reaches_the_wake_path(self):
        with (
            patch.object(dispatch_module, "_orchestrate_wake") as wake,
            patch.object(dispatch_module, "print_help") as help_out,
        ):
            handled = dispatch_module.handle_command("dispatch", ["wake", "@devpulse", "--help"])

        assert handled is True
        help_out.assert_called_once()
        wake.assert_not_called()

    def test_short_flag_is_equally_safe(self):
        with (
            patch.object(dispatch_module, "_orchestrate_dispatch_send") as send,
            patch.object(dispatch_module, "print_help") as help_out,
        ):
            handled = dispatch_module.handle_command("dispatch", ["@devpulse", "Subject", "-h"])

        assert handled is True
        help_out.assert_called_once()
        send.assert_not_called()

    def test_a_real_dispatch_still_dispatches(self):
        """The guard must not swallow ordinary commands."""
        with (
            patch.object(dispatch_module, "_orchestrate_dispatch_send", return_value=True) as send,
            patch.object(dispatch_module, "print_help") as help_out,
        ):
            handled = dispatch_module.handle_command("dispatch", ["@devpulse", "Subject", "run --help for usage"])

        assert handled is True
        send.assert_called_once()
        help_out.assert_not_called()

    def test_status_subcommand_still_runs(self):
        with (
            patch.object(dispatch_module, "_orchestrate_status", return_value=True) as status,
            patch.object(dispatch_module, "print_help") as help_out,
        ):
            handled = dispatch_module.handle_command("dispatch", ["status"])

        assert handled is True
        status.assert_called_once()
        help_out.assert_not_called()


# =============================================================================
# EMAIL MODULE
# =============================================================================


class TestEmailHelpSafety:
    """`email`/`send` reach a real delivery; the other verbs mutate the inbox."""

    def test_trailing_help_never_reaches_the_send_path(self):
        with (
            patch.object(email_module, "handle_send") as send,
            patch.object(email_module, "print_help") as help_out,
        ):
            handled = email_module.handle_command("email", ["@devpulse", "Subject", "Body", "--help"])

        assert handled is True
        help_out.assert_called_once()
        send.assert_not_called()

    def test_trailing_help_never_closes_a_message(self):
        with (
            patch.object(email_module, "handle_close") as close,
            patch.object(email_module, "print_help") as help_out,
        ):
            handled = email_module.handle_command("close", ["all", "--help"])

        assert handled is True
        help_out.assert_called_once()
        close.assert_not_called()

    def test_trailing_help_never_replies(self):
        with (
            patch.object(email_module, "handle_reply") as reply,
            patch.object(email_module, "print_help") as help_out,
        ):
            handled = email_module.handle_command("reply", ["abc123", "message", "-h"])

        assert handled is True
        help_out.assert_called_once()
        reply.assert_not_called()

    def test_a_real_reply_still_replies(self):
        with (
            patch.object(email_module, "handle_reply", return_value=True) as reply,
            patch.object(email_module, "print_help") as help_out,
        ):
            handled = email_module.handle_command("reply", ["abc123", "see --help for usage"])

        assert handled is True
        reply.assert_called_once()
        help_out.assert_not_called()

    def test_unknown_command_still_declines(self):
        """The guard must not turn a foreign command into a help print."""
        assert email_module.handle_command("nonsense", ["--help"]) is False


# =============================================================================
# EMAIL_SEND MODULE
# =============================================================================


class TestEmailSendHelpSafety:
    """The second module answering to `send`/`email`."""

    def test_trailing_help_never_reaches_the_send_path(self):
        with (
            patch.object(email_send_module, "handle_send") as send,
            patch.object(email_send_module, "print_introspection") as help_out,
        ):
            handled = email_send_module.handle_command("send", ["@devpulse", "Subject", "Body", "--help"])

        assert handled is True
        help_out.assert_called_once()
        send.assert_not_called()

    def test_short_flag_is_equally_safe(self):
        with (
            patch.object(email_send_module, "handle_send") as send,
            patch.object(email_send_module, "print_introspection") as help_out,
        ):
            handled = email_send_module.handle_command("email", ["@devpulse", "-h", "Body"])

        assert handled is True
        help_out.assert_called_once()
        send.assert_not_called()

    def test_a_real_send_still_sends(self):
        with (
            patch.object(email_send_module, "handle_send", return_value=True) as send,
            patch.object(email_send_module, "print_introspection") as help_out,
        ):
            handled = email_send_module.handle_command("email", ["@devpulse", "Subject", "please read --help first"])

        assert handled is True
        send.assert_called_once()
        help_out.assert_not_called()

    def test_foreign_command_still_declines(self):
        assert email_send_module.handle_command("inbox", ["--help"]) is False
