"""Tests for help-flag safety — a help flag anywhere means explain, never execute.

Red-first canaries for DPLAN-0291 rule E / help_flag_safety. Every module below
gated help at args[0] only, so a flag later on the line was discarded and the
subcommand ran. The damage was real per module:

    dismiss <alert-id> --help   -> removed the alert it was asked to describe
    test --verbose --help       -> fired every hook with mock data
    sessions reclaim --help     -> stopped live sessions, filtered on "-help"
    feedback on --help          -> flipped the toggle
    hooksound off --help        -> muted the fleet's hook audio
    log --help                  -> dumped the log instead of explaining itself

Each test mocks the damaging target and asserts it is NEVER called.
"""

from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.cli.help_flags import HELP_FLAGS, is_help_flag, wants_help
from aipass.hooks.apps.modules import (
    alert_dismiss,
    cc_sessions,
    engine,
    feedback,
    hook_test,
    hooksound,
    hookstatus,
    sandbox,
    wire_verify,
)


class TestWantsHelpPredicate:
    """The predicate itself — dashed anywhere, bare word only at position 0."""

    def test_empty_args_is_not_help(self):
        assert wants_help([]) is False

    @pytest.mark.parametrize("flag", ["--help", "-h", "help"])
    def test_flag_at_position_zero(self, flag):
        assert wants_help([flag]) is True

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_dashed_flag_anywhere(self, flag):
        assert wants_help(["reclaim", flag]) is True
        assert wants_help(["push", "--force", flag]) is True

    def test_bare_word_later_is_content_by_default(self):
        """`dismiss help` may be an alert literally named help — not a question."""
        assert wants_help(["dismiss", "help"]) is False

    def test_bare_word_later_when_opted_in(self):
        assert wants_help(["dismiss", "help"], allow_bare_word=True) is True

    def test_non_help_args(self):
        assert wants_help(["reclaim", "@hooks"]) is False

    @pytest.mark.parametrize("token", HELP_FLAGS)
    def test_is_help_flag(self, token):
        assert is_help_flag(token) is True

    def test_is_help_flag_rejects_lookalikes(self):
        for token in ("--helpme", "-help", "helper", "h", ""):
            assert is_help_flag(token) is False


class TestDismissNeverDismissesOnHelp:
    def test_help_after_alert_id_does_not_dismiss(self):
        with patch.object(alert_dismiss, "_dismiss_alert") as target:
            assert alert_dismiss.handle_command("dismiss", ["some-alert-id", "--help"]) is True
        target.assert_not_called()

    def test_short_flag_after_alert_id_does_not_dismiss(self):
        with patch.object(alert_dismiss, "_dismiss_alert") as target:
            assert alert_dismiss.handle_command("dismiss", ["some-alert-id", "-h"]) is True
        target.assert_not_called()

    def test_real_dismiss_still_runs(self):
        with patch.object(alert_dismiss, "_dismiss_alert") as target:
            assert alert_dismiss.handle_command("dismiss", ["some-alert-id"]) is True
        target.assert_called_once_with("some-alert-id")

    def test_bare_word_at_position_zero_is_help_not_an_alert_id(self):
        """`dismiss help` reads as the question — the contract puts bare help at slot 0."""
        with patch.object(alert_dismiss, "_dismiss_alert") as target:
            assert alert_dismiss.handle_command("dismiss", ["help"]) is True
        target.assert_not_called()

    def test_bare_word_later_is_content_not_a_question(self):
        """A trailing bare `help` is an operand — only the dashed forms carry anywhere."""
        with patch.object(alert_dismiss, "_dismiss_alert") as target:
            assert alert_dismiss.handle_command("dismiss", ["some-alert-id", "help"]) is True
        target.assert_called_once_with("some-alert-id")


class TestHookTestNeverFiresOnHelp:
    def test_help_after_verbose_does_not_fire_hooks(self):
        with patch.object(hook_test, "run_test") as target:
            assert hook_test.handle_command("test", ["--verbose", "--help"]) is True
        target.assert_not_called()

    def test_short_flag_after_verbose_does_not_fire_hooks(self):
        with patch.object(hook_test, "run_test") as target:
            assert hook_test.handle_command("test", ["-v", "-h"]) is True
        target.assert_not_called()

    def test_bare_help_word_does_not_fire_hooks(self):
        with patch.object(hook_test, "run_test") as target:
            assert hook_test.handle_command("test", ["help"]) is True
        target.assert_not_called()

    def test_real_run_still_fires(self):
        with patch.object(hook_test, "run_test", return_value={}) as target:
            with patch.object(hook_test, "print_results"):
                assert hook_test.handle_command("test", ["--verbose"]) is True
        target.assert_called_once()


class TestSessionsReclaimNeverStopsSessionsOnHelp:
    """The worst of the set: --help was consumed as the branch filter value."""

    def test_help_after_reclaim_does_not_reclaim(self):
        with patch.object(cc_sessions, "reclaim") as target:
            assert cc_sessions.handle_command("sessions", ["reclaim", "--help"]) is True
        target.assert_not_called()

    def test_short_flag_after_reclaim_does_not_reclaim(self):
        with patch.object(cc_sessions, "reclaim") as target:
            assert cc_sessions.handle_command("sessions", ["reclaim", "-h"]) is True
        target.assert_not_called()

    def test_legacy_alias_also_protected(self):
        with patch.object(cc_sessions, "reclaim") as target:
            assert cc_sessions.handle_command("cc_sessions", ["reclaim", "--help"]) is True
        target.assert_not_called()

    def test_real_reclaim_still_runs(self):
        with patch.object(cc_sessions, "reclaim", return_value=[]) as target:
            assert cc_sessions.handle_command("sessions", ["reclaim", "@hooks"]) is True
        target.assert_called_once_with("hooks")


class TestFeedbackNeverTogglesOnHelp:
    def test_help_after_on_does_not_enable(self, tmp_path):
        sentinel = tmp_path / "feedback_off"
        sentinel.touch()
        with patch.object(feedback, "_sentinel", return_value=sentinel):
            assert feedback.handle_command("feedback", ["on", "--help"]) is True
        assert sentinel.exists(), "help request removed the sentinel — it toggled"

    def test_help_after_off_does_not_disable(self, tmp_path):
        sentinel = tmp_path / "feedback_off"
        with patch.object(feedback, "_sentinel", return_value=sentinel):
            assert feedback.handle_command("feedback", ["off", "--help"]) is True
        assert not sentinel.exists(), "help request created the sentinel — it toggled"

    def test_real_toggle_still_runs(self, tmp_path):
        sentinel = tmp_path / "feedback_off"
        with patch.object(feedback, "_sentinel", return_value=sentinel):
            assert feedback.handle_command("feedback", ["off"]) is True
        assert sentinel.exists()


class TestHooksoundNeverTogglesOnHelp:
    def test_help_after_off_does_not_mute(self, tmp_path):
        flag = tmp_path / "mute"
        with patch.object(hooksound, "MUTE_FLAG", flag):
            assert hooksound.handle_command("hooksound", ["off", "--help"]) is True
        assert not flag.exists(), "help request muted the fleet"

    def test_help_after_on_does_not_unmute(self, tmp_path):
        flag = tmp_path / "mute"
        flag.touch()
        with patch.object(hooksound, "MUTE_FLAG", flag):
            assert hooksound.handle_command("hooksound", ["on", "--help"]) is True
        assert flag.exists(), "help request unmuted the fleet"

    def test_real_mute_still_runs(self, tmp_path):
        flag = tmp_path / "mute"
        with patch.object(hooksound, "MUTE_FLAG", flag):
            assert hooksound.handle_command("hooksound", ["off"]) is True
        assert flag.exists()


class TestEngineLogNeverDumpsOnHelp:
    def test_help_after_log_does_not_tail(self):
        with patch.object(engine, "tail_log") as target:
            assert engine.handle_command("log", ["--help"]) is True
        target.assert_not_called()

    def test_real_log_still_tails(self):
        with patch.object(engine, "tail_log", return_value=[]) as target:
            assert engine.handle_command("log", []) is True
        target.assert_called_once()


class TestReadOnlyModulesStillAnswerHelp:
    """No damage to prevent here, but the answer must be help, not silence."""

    def test_status_help_after_operand(self):
        assert hookstatus.handle_command("status", ["anything", "--help"]) is True

    def test_sandbox_help_after_operand(self):
        assert sandbox.handle_command("sandbox", ["anything", "--help"]) is True

    def test_verify_help_after_operand(self):
        assert wire_verify.handle_command("verify", ["anything", "--help"]) is True


class TestHelpGateDoesNotHijackOtherModules:
    """The gate sits AFTER the ownership check, so a module only answers for itself."""

    def test_dismiss_does_not_answer_for_another_command(self):
        assert alert_dismiss.handle_command("status", ["--help"]) is False

    def test_hook_test_does_not_answer_for_another_command(self):
        assert hook_test.handle_command("dismiss", ["--help"]) is False

    def test_sessions_does_not_answer_for_another_command(self):
        assert cc_sessions.handle_command("status", ["--help"]) is False

    def test_feedback_does_not_answer_for_another_command(self):
        assert feedback.handle_command("hooksound", ["--help"]) is False

    def test_hooksound_does_not_answer_for_another_command(self):
        assert hooksound.handle_command("feedback", ["--help"]) is False

    def test_verify_does_not_answer_for_another_command(self):
        assert wire_verify.handle_command("status", ["--help"]) is False
