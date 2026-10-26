# =================== AIPass ====================
# Name: test_help_flags.py
# Version: 1.1.1
# Description: Help-flag safety — a help flag anywhere means explain, never execute
# Branch: hooks
# Created: 2026-08-13
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/cli/help_flags.py and the modules that route through it."""

# A help flag after args[0] must not run the subcommand: each test mocks the damaging target, asserts never called.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that help_flags.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — each module's help text wording, the documentation checker covers it
# seedgo: no-test-needed(constant) — HELP_FLAGS' spelling list beyond the members asserted here

from unittest.mock import patch

import pytest

from aipass.hooks.apps import hooks, sound
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

    def test_help_flags_table_is_the_three_spellings(self):
        """Arms the parametrized row below, which reads HELP_FLAGS at collection.

        An emptied HELP_FLAGS collects zero cases, which pytest reports as a green SKIPPED.
        """
        assert len(HELP_FLAGS) == 3
        assert set(HELP_FLAGS) == {"--help", "-h", "help"}

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

    def test_real_dismiss_still_runs_and_carries_the_outcome(self):
        """Both legs pinned: a real dismissal routes True, a refusal exits 1 (a bare MagicMock is truthy)."""
        with patch.object(alert_dismiss, "_dismiss_alert", return_value=True) as target:
            assert alert_dismiss.handle_command("dismiss", ["some-alert-id"]) is True
        target.assert_called_once_with("some-alert-id")

        with patch.object(alert_dismiss, "_dismiss_alert", return_value=False) as target:
            with pytest.raises(SystemExit) as exit_info:
                alert_dismiss.handle_command("dismiss", ["missing-id"])
        assert exit_info.value.code == 1
        target.assert_called_once_with("missing-id")

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
            with patch.object(hook_test, "print_results") as shown:
                assert hook_test.handle_command("test", ["--verbose"]) is True
        target.assert_called_once_with(verbose=True)
        shown.assert_called_once_with({}, verbose=True)


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
        target.assert_called_once_with(cc_sessions.registered_branch_dir("hooks"))


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
    """These patch the flag's real owner, sound, and run the true write path end to end."""

    def test_help_after_off_does_not_mute(self, tmp_path):
        flag = tmp_path / "mute"
        with patch.object(sound, "MUTE_FLAG", flag):
            assert hooksound.handle_command("hooksound", ["off", "--help"]) is True
        assert not flag.exists(), "help request muted the fleet"

    def test_help_after_on_does_not_unmute(self, tmp_path):
        flag = tmp_path / "mute"
        flag.touch()
        with patch.object(sound, "MUTE_FLAG", flag):
            assert hooksound.handle_command("hooksound", ["on", "--help"]) is True
        assert flag.exists(), "help request unmuted the fleet"

    def test_real_mute_still_runs(self, tmp_path):
        flag = tmp_path / "mute"
        with patch.object(sound, "MUTE_FLAG", flag):
            assert hooksound.handle_command("hooksound", ["off"]) is True
        assert flag.exists()

    def test_real_unmute_still_runs(self, tmp_path):
        flag = tmp_path / "mute"
        flag.touch()
        with patch.object(sound, "MUTE_FLAG", flag):
            assert hooksound.handle_command("hooksound", ["on"]) is True
        assert not flag.exists()


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

    def test_status_help_after_operand(self, capsys):
        assert hookstatus.handle_command("status", ["anything", "--help"]) is True
        assert "drone @hooks status --help    Show this help" in capsys.readouterr().err

    def test_sandbox_help_after_operand(self, capsys):
        assert sandbox.handle_command("sandbox", ["anything", "--help"]) is True
        assert "drone @hooks sandbox    Show sandbox module status" in capsys.readouterr().err

    def test_verify_help_after_operand(self, capsys):
        assert wire_verify.handle_command("verify", ["anything", "--help"]) is True
        assert "drone @hooks verify     Cross-check provider settings" in capsys.readouterr().err

    @pytest.mark.parametrize("verb", ["cadence", "context_window", "diagnostics_state", "engine"])
    def test_verb_help_answers_help_not_unknown_command(self, verb, capsys):
        assert hooks.handle_command(verb, ["--help"]) is True
        assert f"{verb} — " in capsys.readouterr().err


class TestHelpListsWhatRuns:
    def test_help_lists_closure_list_not_the_module_name(self, capsys):
        hooks.print_help()
        out, _ = capsys.readouterr()
        assert "closure list" in out
        assert "engine_closure" not in out

    def test_every_module_description_is_a_whole_sentence(self):
        for module in hooks.discover_modules():
            first = (module.__doc__ or "").strip().split("\n")[0]
            assert first.endswith((".", "?")), module.__name__


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


class TestUnknownCommandNamesWhatFailed:
    """An unknown sub-verb is named with its known parent, not reported as an unknown command."""

    def _main(self, argv):
        import sys
        from unittest.mock import patch

        # Both consoles: the refusal prints on err_console, and stdout alone would read as silence.
        printed = []
        with (
            patch.object(sys, "argv", ["hooks", *argv]),
            patch.object(hooks.console, "print", side_effect=lambda m="", **k: printed.append(str(m))),
            patch.object(hooks.err_console, "print", side_effect=lambda m="", **k: printed.append(str(m))),
        ):
            code = hooks.main()
        return code, "\n".join(printed)

    def test_unknown_subverb_exits_nonzero(self):
        code, _ = self._main(["hooksound", "sideways"])
        assert code == 1

    def test_unknown_subverb_names_the_subverb(self):
        _, out = self._main(["hooksound", "sideways"])
        assert "hooksound sideways" in out

    def test_unknown_top_level_command_still_named_alone(self):
        code, out = self._main(["banana"])
        assert code == 1
        assert "Unknown command: banana" in out

    def test_known_verbs_still_succeed(self, tmp_path):
        from unittest.mock import patch

        # An absent flag under tmp_path: the status line must read it as ACTIVE.
        with patch("aipass.hooks.apps.sound.MUTE_FLAG", tmp_path / "mute"):
            code, out = self._main(["hooksound"])
        assert code == 0
        assert "Hook sound control (ACTIVE)" in out
