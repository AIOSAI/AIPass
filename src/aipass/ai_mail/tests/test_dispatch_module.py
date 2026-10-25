# =================== AIPass ====================
# Name: test_dispatch_module.py
# Description: Tests for dispatch.py orchestrator functions
# Version: 1.1.0
# Created: 2026-04-26
# Modified: 2026-10-25
# =============================================

"""Tests for apps/modules/dispatch.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the handler modules _orchestrate_dispatch_send reaches parse and import
# seedgo: no-test-needed(constant) — DISPATCH_ID_ENV and the other literal env-var names dispatch.py reads

import json
from contextlib import ExitStack

import pytest
from unittest.mock import MagicMock, patch

from aipass.ai_mail.apps.handlers.dispatch.wake import DispatchStatus
from aipass.ai_mail.apps.modules.dispatch import (
    handle_command,
    print_help,
    print_introspection,
)
import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod


# Each verb is reached the way `drone @ai_mail dispatch ...` reaches it: through
# handle_command.
def _send(args):
    """`dispatch <@target|/path> Subject Body ...`."""
    return handle_command("dispatch", args)


def _wake(args):
    """`dispatch wake ...`."""
    return handle_command("dispatch", ["wake", *args])


# ---------------------------------------------------------------------------
# Autouse fixture: suppress json_handler.log_operation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.modules.dispatch.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

MOD = "aipass.ai_mail.apps.modules.dispatch"

# Source modules for lazy imports inside _orchestrate_dispatch_send
_H_SEND = "aipass.ai_mail.apps.handlers.email.send"
_H_USERS = "aipass.ai_mail.apps.handlers.users.user"
_H_REG = "aipass.ai_mail.apps.handlers.registry.read"
_H_WAKE = "aipass.ai_mail.apps.handlers.dispatch.wake"
# The send half runs through email_send._send_direct, which binds these names at import.
_ES = "aipass.ai_mail.apps.modules.email_send"
_H_VERIFIED = "aipass.ai_mail.apps.handlers.users.verified_caller"


def _mock_console(printed: list[str]) -> MagicMock:
    """Create a mock console that appends all print calls to *printed*."""
    mc = MagicMock()
    mc.print = lambda msg="", **kw: printed.append(str(msg))
    return mc


# ===========================================================================
# print_help
# ===========================================================================


class TestPrintHelp:
    """Tests for dispatch.print_help."""

    def test_print_help_contains_keywords(self, monkeypatch):
        """Help text contains expected keywords."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        print_help()
        combined = " ".join(printed)
        assert "dispatch" in combined.lower()
        assert "wake" in combined.lower()


# ===========================================================================
# handle_command
# ===========================================================================


class TestHandleCommand:
    """Tests for the top-level handle_command router."""

    def test_non_dispatch_command_returns_false(self):
        """A command that is not 'dispatch' returns False."""
        result = handle_command("email", ["inbox"])
        assert result is False

    def test_dispatch_no_args_calls_introspection(self, monkeypatch):
        """'dispatch' with no args calls print_introspection."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = handle_command("dispatch", [])
        assert result is True
        combined = " ".join(printed)
        assert "dispatch Module" in combined

    def test_dispatch_help_flag(self, monkeypatch):
        """'dispatch --help' prints help and returns True."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = handle_command("dispatch", ["--help"])
        assert result is True
        combined = " ".join(printed)
        assert "COMMANDS" in combined

    def test_dispatch_h_flag(self, monkeypatch):
        """'dispatch -h' prints help and returns True."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = handle_command("dispatch", ["-h"])
        assert result is True
        assert "COMMANDS" in " ".join(printed)

    def test_dispatch_help_word(self, monkeypatch):
        """'dispatch help' prints help and returns True."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = handle_command("dispatch", ["help"])
        assert result is True
        assert "COMMANDS" in " ".join(printed)

    def test_dispatch_wake_subcommand(self, monkeypatch):
        """'dispatch wake @branch' delegates to _orchestrate_wake."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        # No further args -> shows help
        result = handle_command("dispatch", ["wake"])
        assert result is True
        assert "Usage: dispatch wake @branch" in " ".join(printed)

    def test_dispatch_at_target(self, monkeypatch):
        """'dispatch @target Subject Body' routes to _orchestrate_dispatch_send."""
        send = MagicMock(return_value=True)
        monkeypatch.setattr(f"{MOD}._orchestrate_dispatch_send", send)
        argv = ["@branch", "Subject", "Body"]

        result = handle_command("dispatch", argv)
        assert result is True
        send.assert_called_once_with(argv)

    def test_dispatch_path_target(self, monkeypatch):
        """'dispatch /path Subject Body' routes to _orchestrate_dispatch_send."""
        send = MagicMock(return_value=True)
        monkeypatch.setattr(f"{MOD}._orchestrate_dispatch_send", send)
        argv = ["/some/path", "Subject", "Body"]

        result = handle_command("dispatch", argv)
        assert result is True
        # The same list handed through, not a path parsed and compared.
        send.assert_called_once_with(argv)

    def test_dispatch_unknown_subcommand(self, monkeypatch):
        """Unknown subcommand prints its own error and returns True, so the router adds no second error."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = handle_command("dispatch", ["bogus"])
        assert result is True
        assert any("Unknown dispatch subcommand" in e for e in errors)

    def test_non_dispatch_command_is_declined(self):
        """A command this module does not own returns False, unhandled."""
        assert handle_command("email", ["@target", "Subject", "Body"]) is False


# ===========================================================================
# _orchestrate_wake
# ===========================================================================


class TestOrchestrateWake:
    """Tests for _orchestrate_wake."""

    def test_no_args_prints_help(self, monkeypatch):
        """No args prints wake help and returns True."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = _wake([])
        assert result is True
        combined = " ".join(printed)
        assert "Wake" in combined

    def test_wake_help_prints_the_wake_usage(self, monkeypatch):
        """`dispatch wake help` prints the wake usage and returns True."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = _wake(["help"])
        assert result is True
        combined = " ".join(printed)
        assert 'Usage: dispatch wake @branch ["custom message"]' in combined

    def test_h_flag_after_wake_is_answered_and_wakes_nothing(self, monkeypatch):
        """`dispatch wake -h` is help, never a wake: wants_help answers it before the verb."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))
        woken = []
        monkeypatch.setattr(f"{_H_WAKE}.wake_branch", lambda *a, **kw: woken.append(a))

        result = _wake(["-h"])
        assert result is True
        assert woken == []
        # The dispatch help answered, not the wake arm's own usage line.
        assert not any("Wake - Manual branch spawn" in line for line in printed)

    def test_help_word_prints_help(self, monkeypatch):
        """'help' prints wake help and returns True."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = _wake(["help"])
        assert result is True

    def test_missing_branch_after_flags_reports_and_stays_handled(self, monkeypatch):
        """Only flags (--fresh) without a branch errors but stays handled.

        error() marks the process failed (exit 2). Returning False here made
        the router add "Unknown command: dispatch" on top of "Missing branch
        argument" and exit 1 — unroutable — for a command it had routed.
        """
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = _wake(["--fresh"])
        assert result is True
        assert any("Missing" in e for e in errors)

    def test_blocked_branch_shows_error(self, monkeypatch):
        """A blocked branch shows error and returns True."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        with patch(
            "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked",
            return_value=True,
        ):
            result = _wake(["@protected"])
        assert result is True
        assert any("protected" in e for e in errors)

    def test_successful_wake(self, monkeypatch):
        """Successful wake prints status and returns True."""
        mock_status = MagicMock()
        mock_status.format.return_value = "WAKE OK: @branch woke up"

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked",
                return_value=False,
            ),
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                return_value=(mock_status, True),
            ),
        ):
            result = _wake(["@branch"])
        assert result is True
        combined = " ".join(printed)
        assert "WAKE OK" in combined

    def test_failed_wake_reports_error_and_stays_handled(self, monkeypatch):
        """A failed wake calls error() and still returns True.

        The step-status block alone never marked the command failed, so a dead
        wake exited 0 and any script reading the code was told it worked.
        """
        mock_status = MagicMock()
        mock_status.format.return_value = "WAKE FAILED: spawn error"

        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked",
                return_value=False,
            ),
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                return_value=(mock_status, False),
            ),
        ):
            result = _wake(["@branch"])
        assert result is True
        assert any("Wake failed for @branch" in e for e in errors)

    def test_fresh_flag(self, monkeypatch):
        """--fresh flag is passed through to wake_branch."""
        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Capture wake_branch call arguments."""
            wake_calls.append({"branch": branch, "fresh": fresh, "sender": sender, "model": model})
            return (mock_status, True)

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked",
                return_value=False,
            ),
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                side_effect=mock_wake,
            ),
        ):
            _wake(["--fresh", "@branch"])
        assert len(wake_calls) == 1
        assert wake_calls[0]["fresh"] is True

    def test_model_flag(self, monkeypatch):
        """--model flag is passed through to wake_branch."""
        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Track model argument passed to wake_branch."""
            wake_calls.append({"branch": branch, "model": model})
            return (mock_status, True)

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked",
                return_value=False,
            ),
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                side_effect=mock_wake,
            ),
        ):
            _wake(["--model", "opus", "@branch"])
        assert len(wake_calls) == 1
        assert wake_calls[0]["model"] == "opus"

    def test_provider_flag_reaches_wake_branch(self, monkeypatch):
        wake = MagicMock(return_value=(DispatchStatus(), True))
        monkeypatch.setattr(f"{MOD}.console", _mock_console([]))

        with patch(f"{_H_WAKE}.wake_branch", wake):
            _wake(["@canary", "--provider", "codex"])

        assert wake.call_args.kwargs["provider"] == "codex"

    def test_an_unknown_provider_refuses_the_wake(self, monkeypatch, capsys):
        wake = MagicMock(return_value=(DispatchStatus(), True))
        monkeypatch.setattr(f"{MOD}.console", _mock_console([]))

        with patch(f"{_H_WAKE}.wake_branch", wake):
            _wake(["@canary", "--provider", "gemini"])

        wake.assert_not_called()
        assert "unknown provider 'gemini'" in capsys.readouterr().err

    def _run_sender_flag(self, monkeypatch) -> list[dict]:
        """Run `wake @branch --sender @custom` and return the wake_branch calls."""
        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Track sender argument passed to wake_branch."""
            wake_calls.append({"branch": branch, "sender": sender})
            return (mock_status, True)

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked",
                return_value=False,
            ),
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                side_effect=mock_wake,
            ),
        ):
            _wake(["--sender", "@custom", "@branch"])
        return wake_calls

    def test_sender_flag_unverified_caller(self, monkeypatch):
        """No caller rail: --sender is passed through to wake_branch.

        States its lane explicitly — the rail reads ambient env, so a test that
        leaves AIPASS_CALLER_BRANCH to chance asserts a different contract
        depending on how the suite was launched.
        """
        monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        wake_calls = self._run_sender_flag(monkeypatch)
        assert len(wake_calls) == 1
        assert wake_calls[0]["sender"] == "@custom"

    def test_sender_flag_loses_to_the_verified_caller(self, monkeypatch):
        """With a rail, the wake is attributed to who actually ran it."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        wake_calls = self._run_sender_flag(monkeypatch)
        assert len(wake_calls) == 1
        assert wake_calls[0]["sender"] == "@seedgo"

    def test_custom_message(self, monkeypatch):
        """A custom message after the branch is passed to wake_branch."""
        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Track custom message argument passed to wake_branch."""
            wake_calls.append({"branch": branch, "msg": msg})
            return (mock_status, True)

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        with (
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked",
                return_value=False,
            ),
            patch(
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch",
                side_effect=mock_wake,
            ),
        ):
            _wake(["@branch", "Check your inbox now"])
        assert len(wake_calls) == 1
        assert wake_calls[0]["msg"] == "Check your inbox now"


# ===========================================================================
# _orchestrate_dispatch_send
# ===========================================================================


def _send_patches(overrides: dict | None = None) -> ExitStack:
    """Return an ExitStack applying all default patches for _orchestrate_dispatch_send.

    Call with overrides to replace specific mock values.
    The caller must use the returned stack as a context manager.
    """
    mock_status = MagicMock()
    mock_status.format.return_value = "WAKE OK"

    defaults = {
        f"{_H_SEND}.resolve_sender_info": MagicMock(return_value={"email_address": "@ai_mail"}),
        f"{_ES}.prepend_dispatch_header": MagicMock(return_value="[DISPATCH] Body"),
        f"{_ES}.send_to_single": MagicMock(return_value=(True, None)),
        f"{_ES}.on_email_delivered": MagicMock(),
        f"{_H_USERS}.get_current_user": MagicMock(return_value={"name": "test"}),
        f"{_H_REG}.get_branch_by_email": MagicMock(return_value={"email": "@target"}),
        f"{_ES}.update_central": MagicMock(),
        f"{_ES}.create_email_file": MagicMock(),
        f"{_ES}.load_email_file": MagicMock(),
        f"{_ES}.deliver_email_to_branch": MagicMock(),
        f"{_ES}.dispatch_send_error": MagicMock(),
        f"{_H_WAKE}.wake_branch": MagicMock(return_value=(mock_status, True)),
        f"{_ES}.trigger": MagicMock(),
    }
    if overrides:
        defaults.update(overrides)

    stack = ExitStack()
    for target, mock_obj in defaults.items():
        stack.enter_context(patch(target, mock_obj))
    return stack


class TestOrchestrateDispatchSend:
    """Tests for _orchestrate_dispatch_send."""

    def test_too_few_args_shows_usage(self, monkeypatch):
        """Fewer than 3 args prints usage error and returns True."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        result = _send(["@target", "Subject"])
        assert result is True
        assert any("Usage" in e for e in errors)

    def test_successful_send_and_wake(self, monkeypatch):
        """Successful send + wake returns True."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))
        monkeypatch.setattr(f"{_ES}.console", _mock_console(printed))

        patches = _send_patches()
        with patches:
            result = _send(["@target", "Subject", "Body"])

        assert result is True
        combined = " ".join(printed)
        assert "sent" in combined.lower()

    def test_send_failure_calls_dispatch_send_error(self, monkeypatch):
        """Send failure calls dispatch_send_error and stays handled.

        Returning False here is what made a refused cross-project dispatch run
        twice: the router moved on to the next module, which sent it again and
        then printed "Unknown command: dispatch".
        """
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        monkeypatch.setattr(f"{_ES}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))
        monkeypatch.setattr(f"{_ES}.console", _mock_console(printed))

        dispatch_error_calls: list[tuple] = []
        mock_dispatch_err = MagicMock(side_effect=lambda *a: dispatch_error_calls.append(a))
        patches = _send_patches(
            {
                f"{_ES}.send_to_single": MagicMock(return_value=(False, "Branch not found")),
                f"{_ES}.dispatch_send_error": mock_dispatch_err,
            }
        )
        with patches:
            result = _send(["@target", "Subject", "Body"])

        assert result is True
        assert any("Failed to deliver: Branch not found" in e for e in errors)
        assert len(dispatch_error_calls) == 1
        # The pre-send "Sending dispatch email to ..." announcement is gone.
        # drone replays stdout before stderr, so a progress line printed before
        # the send always landed BELOW the refusal — reading as "it failed,
        # and then it sent".
        assert not any("Sending dispatch email" in p for p in printed)

    def test_send_ok_but_wake_failure_shows_warning(self, monkeypatch):
        """Send succeeds but wake fails -- returns True but shows error."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        mock_status = MagicMock()
        mock_status.format.return_value = "WAKE FAILED"
        patches = _send_patches(
            {
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch": MagicMock(return_value=(mock_status, False)),
            }
        )
        with patches:
            result = _send(["@target", "Subject", "Body"])

        assert result is True
        assert any("wake failed" in e.lower() for e in errors)

    def test_fresh_flag_passed_through(self, monkeypatch):
        """--fresh flag is passed to wake_branch as fresh=True."""
        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Track fresh flag passed to wake_branch."""
            wake_calls.append({"branch": branch, "fresh": fresh})
            return (mock_status, True)

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches(
            {
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch": MagicMock(side_effect=mock_wake),
            }
        )
        with patches:
            _send(["@target", "Subject", "Body", "--fresh"])

        assert len(wake_calls) == 1
        assert wake_calls[0]["fresh"] is True

    def test_from_flag_passed_through(self, monkeypatch):
        """--from flag is passed to resolve_sender_info."""
        sender_calls: list[str | None] = []

        def tracking_resolve(from_branch, *args):
            """Track from_branch argument passed to resolve_sender_info."""
            sender_calls.append(from_branch)
            return {"email_address": "@custom"}

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches(
            {
                f"{_H_SEND}.resolve_sender_info": MagicMock(side_effect=tracking_resolve),
            }
        )
        with patches:
            _send(["@target", "Subject", "Body", "--from", "@custom_sender"])

        assert len(sender_calls) == 1
        assert sender_calls[0] == "@custom_sender"

    def test_model_flag(self, monkeypatch):
        """--model flag is passed to wake_branch."""
        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Track model argument passed to wake_branch in dispatch send."""
            wake_calls.append({"model": model})
            return (mock_status, True)

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches(
            {
                "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch": MagicMock(side_effect=mock_wake),
            }
        )
        with patches:
            _send(["@target", "Subject", "Body", "--model", "sonnet"])

        assert len(wake_calls) == 1
        assert wake_calls[0]["model"] == "sonnet"

    def test_provider_flag_reaches_wake_branch_beside_the_model(self, monkeypatch):
        wake = MagicMock(return_value=(DispatchStatus(), True))
        monkeypatch.setattr(f"{MOD}.console", _mock_console([]))

        with _send_patches({f"{_H_WAKE}.wake_branch": wake}):
            _send(["@canary", "Subject", "Body", "--provider", "codex", "--model", "gpt-6.1-sol"])

        assert wake.call_args.kwargs["provider"] == "codex"
        assert wake.call_args.kwargs["model"] == "gpt-6.1-sol"

    def test_an_unknown_provider_is_refused_before_any_mail_is_sent(self, monkeypatch, capsys):
        send = MagicMock(return_value=(True, None))
        wake = MagicMock(return_value=(DispatchStatus(), True))
        monkeypatch.setattr(f"{MOD}.console", _mock_console([]))

        with _send_patches({f"{_ES}.send_to_single": send, f"{_H_WAKE}.wake_branch": wake}):
            _send(["@canary", "Subject", "Body", "--provider", "gemini"])

        send.assert_not_called()
        wake.assert_not_called()
        err = capsys.readouterr().err
        assert "not sent" in err and "unknown provider 'gemini'" in err

    def test_no_memory_save_flag(self, monkeypatch):
        """--no-memory-save flag is passed to prepend_dispatch_header."""
        header_calls: list[dict] = []

        def tracking_header(body, no_memory_save=False):
            """Track no_memory_save flag passed to prepend_dispatch_header."""
            header_calls.append({"no_memory_save": no_memory_save})
            return f"[DISPATCH] {body}"

        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches(
            {
                f"{_ES}.prepend_dispatch_header": MagicMock(side_effect=tracking_header),
            }
        )
        with patches:
            _send(["@target", "Subject", "Body", "--no-memory-save"])

        assert len(header_calls) == 1
        assert header_calls[0]["no_memory_save"] is True

    def test_trigger_fire_failure_does_not_fail(self, monkeypatch):
        """If trigger.fire raises, the send still succeeds."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        mock_trigger = MagicMock()
        mock_trigger.fire.side_effect = RuntimeError("trigger broken")

        patches = _send_patches(
            {
                f"{_ES}.trigger": mock_trigger,
            }
        )
        with patches:
            result = _send(["@target", "Subject", "Body"])

        assert result is True

    def test_send_phase_exception_reports_and_stays_handled(self, monkeypatch):
        """An exception in the send phase errors out but stays handled."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches(
            {
                f"{_H_SEND}.resolve_sender_info": MagicMock(side_effect=RuntimeError("boom")),
            }
        )
        with patches:
            result = _send(["@target", "Subject", "Body"])

        assert result is True
        assert any("Dispatch to @target not sent: boom" in e for e in errors)


# ===========================================================================
# print_introspection
# ===========================================================================


class TestPrintIntrospection:
    """Tests for print_introspection."""

    def test_prints_module_info(self, monkeypatch):
        """print_introspection prints module info."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        print_introspection()
        combined = " ".join(printed)
        assert "dispatch Module" in combined
        assert "Connected Handlers" in combined
        assert "wake.py" in combined


# ===========================================================================
# Wake-back messaging (TDPLAN-0012 — retired _spawn_watchdog)
# ===========================================================================


class TestWakeBackMessaging:
    """Tests for honest wake-back messaging after watchdog retirement."""

    def test_wake_back_message_on_successful_wake(self, monkeypatch):
        """Successful send + wake prints wake-back enabled message."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches()
        with patches:
            result = _send(["@target", "Subject", "Body"])

        assert result is True
        combined = " ".join(printed)
        assert "Wake-back enabled" in combined
        assert "Watchdog armed" not in combined

    def test_no_wake_back_message_on_wake_failure(self, monkeypatch):
        """No wake-back message when wake fails."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        mock_status = MagicMock()
        mock_status.format.return_value = "WAKE FAILED"
        patches = _send_patches(
            {
                f"{_H_WAKE}.wake_branch": MagicMock(return_value=(mock_status, False)),
            }
        )
        with patches:
            _send(["@target", "Subject", "Body"])

        combined = " ".join(printed)
        assert "Wake-back enabled" not in combined

    def test_no_watchdog_flag_still_accepted(self, monkeypatch):
        """--no-watchdog flag is consumed without error (backward compat)."""
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches()
        with patches:
            result = _send(["@target", "Subject", "Body", "--no-watchdog"])

        assert result is True

    def test_no_watchdog_message_on_send_failure(self, monkeypatch):
        """No wake-back message when send fails."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        patches = _send_patches(
            {
                f"{_ES}.send_to_single": MagicMock(return_value=(False, "error")),
            }
        )
        with patches:
            _send(["@target", "Subject", "Body"])

        combined = " ".join(printed)
        assert "Wake-back enabled" not in combined


# ===========================================================================
# Verified-caller rail — spoofed sender refusal (FPLAN-0401 Phase 1)
# ===========================================================================


class TestSpoofedSenderRefusal:
    """CLI-suppliable identity must never gate a privilege.

    `--from` (dispatch send) and `--sender` (manual wake) both land on
    wake_branch's `sender`, and `sender == "@daemon"` unlocks the manager wake
    lane. These prove the claim is checked against the verified caller before
    it can reach that gate.
    """

    @pytest.fixture(autouse=True)
    def _clear_caller_env(self, monkeypatch):
        """State the caller env per test — an ambient one would decide for it."""
        monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

    def test_spoofed_daemon_from_flag_never_reaches_wake(self, monkeypatch):
        """THE canary: --from @daemon out of a non-daemon seat wakes nothing."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        wake = MagicMock()
        send = MagicMock(return_value=(True, None))
        patches = _send_patches({f"{_H_WAKE}.wake_branch": wake, f"{_ES}.send_to_single": send})
        with patches:
            result = _send(["@target", "Subject", "Body", "--from", "@daemon"])

        assert result is True
        wake.assert_not_called()
        send.assert_not_called()  # a refused dispatch must not send the email either
        assert errors, "refusal must be loud on stderr"
        assert "@daemon" in errors[0] and "@seedgo" in errors[0]

    def test_spoofed_daemon_sender_flag_never_reaches_wake(self, monkeypatch):
        """Same hole, second door: `dispatch wake @x --sender @daemon`."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        wake = MagicMock()
        with (
            patch(f"{_H_WAKE}.is_wake_blocked", return_value=False),
            patch(f"{_H_WAKE}.wake_branch", wake),
        ):
            result = _wake(["--sender", "@daemon", "@target"])

        assert result is True
        wake.assert_not_called()
        assert errors and "@daemon" in errors[0]

    def test_unverifiable_caller_cannot_claim_daemon(self, monkeypatch):
        """No caller rail at all — the claim is refused, not assumed."""
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        monkeypatch.setattr(f"{MOD}.console", _mock_console([]))

        wake = MagicMock()
        patches = _send_patches({f"{_H_WAKE}.wake_branch": wake})
        with patches:
            _send(["@target", "Subject", "Body", "--from", "@daemon"])

        wake.assert_not_called()
        assert errors and "unverified" in errors[0].lower()

    def test_real_daemon_seat_still_dispatches_as_daemon(self, monkeypatch):
        """The rail proves it: @daemon's own seat keeps its lane."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "daemon")
        monkeypatch.setattr(f"{MOD}.error", lambda msg: None)
        monkeypatch.setattr(f"{MOD}.console", _mock_console([]))

        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Track the sender that reached wake_branch."""
            wake_calls.append({"sender": sender})
            return (mock_status, True)

        patches = _send_patches({f"{_H_WAKE}.wake_branch": MagicMock(side_effect=mock_wake)})
        with patches:
            _send(["@target", "Subject", "Body", "--from", "@daemon"])

        assert len(wake_calls) == 1
        assert wake_calls[0]["sender"] == "@daemon"

    def test_wake_sender_comes_from_the_rail_not_the_from_flag(self, monkeypatch):
        """A legal --from still moves the mail identity, never the wake identity."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        monkeypatch.setattr(f"{MOD}.error", lambda msg: None)
        monkeypatch.setattr(f"{MOD}.console", _mock_console([]))

        wake_calls: list[dict] = []
        mock_status = MagicMock()
        mock_status.format.return_value = "OK"

        def mock_wake(branch, msg=None, fresh=False, sender="@devpulse", model=None, **kwargs):
            """Track the sender that reached wake_branch."""
            wake_calls.append({"sender": sender})
            return (mock_status, True)

        resolve = MagicMock(return_value={"email_address": "@spawn"})
        patches = _send_patches(
            {
                f"{_H_WAKE}.wake_branch": MagicMock(side_effect=mock_wake),
                f"{_H_SEND}.resolve_sender_info": resolve,
            }
        )
        with patches:
            _send(["@target", "Subject", "Body", "--from", "@spawn"])

        # The mail is still authored by @spawn...
        assert resolve.call_args[0][0] == "@spawn"
        # ...and the wake is attributed to whoever actually ran the command.
        assert wake_calls[0]["sender"] == "@seedgo"

    def test_non_privileged_from_flag_still_dispatches(self, monkeypatch):
        """No collateral damage: an ordinary --from send is untouched."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        errors: list[str] = []
        monkeypatch.setattr(f"{MOD}.error", lambda msg: errors.append(msg))
        printed: list[str] = []
        monkeypatch.setattr(f"{MOD}.console", _mock_console(printed))

        wake = MagicMock(return_value=(MagicMock(), True))
        send = MagicMock(return_value=(True, None))
        patches = _send_patches({f"{_H_WAKE}.wake_branch": wake, f"{_ES}.send_to_single": send})
        with patches:
            _send(["@target", "Subject", "Body", "--from", "@spawn"])

        send.assert_called_once()
        wake.assert_called_once()
        assert errors == []


class TestWakeBackPromiseMatchesDelivery:
    """The line printed after a successful dispatch must describe what will
    actually happen. A manager is never woken — it is mailed."""

    def _run(self, sender, sender_is_manager):
        """`dispatch @canary` under the shared send patch set, the wake-back going to `sender`.

        The wake and the manager verdict are stubbed; the real console prints to
        stdout. Reached through the command, not the helper.
        """
        status = DispatchStatus()
        status.ok("spawn", "agent started")
        overrides = {
            f"{_H_WAKE}.wake_branch": MagicMock(return_value=(status, True)),
            # Keyed on the address, so asking about the wrong one is seen.
            f"{_H_WAKE}.is_manager": MagicMock(side_effect=lambda addr: sender_is_manager and addr == sender),
            f"{_H_VERIFIED}.resolve_wake_sender": MagicMock(return_value=sender),
        }
        with _send_patches(overrides):
            assert _send(["@canary", "Subject", "Body"]) is True

    def test_manager_sender_is_promised_mail_not_a_wake(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """@devpulse was told 'sender will be woken' three times on 2026-08-21
        and was not woken any of them. Managers get mail; the promise must say mail.

        Read from stdout with the wrapped lines joined, so a promise Rich breaks
        across two lines is still seen whole.
        """
        self._run("@devpulse", sender_is_manager=True)
        line = " ".join(capsys.readouterr().out.split()).lower()
        assert "mailed" in line
        assert "will be woken" not in line

    def test_ordinary_sender_is_still_promised_a_wake(self, monkeypatch, capsys: pytest.CaptureFixture[str]):
        """A sender who is not a manager is still promised the wake, read from stdout."""
        self._run("@prax", sender_is_manager=False)
        line = " ".join(capsys.readouterr().out.split()).lower()
        assert "sender will be woken when @canary completes" in line


# ===========================================================================
# One seat, two verbs, one manager-gate verdict (#754's second owed pin)
# ===========================================================================


class TestBothVerbsAgreeAtTheManagerGate:
    """92d0e977: from the admin seat, `dispatch @vera` spawned while `dispatch
    wake @vera` answered "manager - wake skipped" - the wake verb never asked
    for the grant. The REAL wake_branch decides here. Only resolution and what
    sits past the gate are stubbed; the lock step is the stop, since an agent
    already holding the lock routes to inbox and spawns nothing.
    """

    @pytest.fixture(autouse=True)
    def manager(self, tmp_path, monkeypatch):
        """A manager-class citizen that every address resolves to."""
        branch = tmp_path / "mgr"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": "manager"}}), encoding="utf-8"
        )
        monkeypatch.setattr(f"{_H_WAKE}.resolve_branch", lambda email, admin=False: (branch, "@mgr"))
        monkeypatch.setattr(f"{_H_WAKE}.clean_zombies", lambda: 0)
        monkeypatch.setattr(f"{_H_WAKE}.check_lock", lambda path: {"pid": 4242, "timestamp": "held"})
        monkeypatch.setattr(f"{MOD}.error", lambda msg: None)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

    @staticmethod
    def _verdicts_from_both_verbs() -> list:
        """The manager step each verb's wake recorded: [wake verb, send+wake verb]."""
        real_wake = wake_mod.wake_branch
        verdicts: list = []

        def _spy(*args, **kwargs):
            """Run the real wake and keep its manager verdict."""
            status, ok = real_wake(*args, **kwargs)
            verdicts.append(status.find_step("manager"))
            return status, ok

        with patch(f"{_H_WAKE}.wake_branch", _spy):
            _wake(["@mgr"])
        with _send_patches({f"{_H_WAKE}.wake_branch": _spy}):
            _send(["@mgr", "Subject", "Body"])
        return verdicts

    def test_admin_seat_gets_one_verdict_from_both_verbs(self, monkeypatch):
        """Both verbs pass the gate on the verified grant."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
        with patch(f"{_H_VERIFIED}.verify_admin_caller", return_value=(True, "admin grant verified")):
            verdicts = self._verdicts_from_both_verbs()

        assert len(verdicts) == 2
        assert verdicts[0] == verdicts[1]
        assert verdicts[0][0] == "ok" and "verified admin dispatch" in verdicts[0][2]

    def test_ordinary_seat_gets_one_verdict_from_both_verbs(self, monkeypatch):
        """The control: the gate is seen to CLOSE, so agreement above is not two Nones."""
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "seedgo")
        verdicts = self._verdicts_from_both_verbs()

        assert len(verdicts) == 2
        assert verdicts[0] == verdicts[1]
        assert verdicts[0][0] == "info" and "wake skipped" in verdicts[0][2]
