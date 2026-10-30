# =================== AIPass ====================
# Name: test_engine.py
# Version: 2.3.0
# Description: Tests for hook engine dispatch logic: the dispatcher core; contracts and safeguards in two siblings
# Branch: hooks
# Layer: tests
# Created: 2026-05-18
# Modified: 2026-10-29
# =============================================

"""Tests for apps/modules/engine.py: the dispatcher core and the hook dispatch it drives."""

# Matching, the hook runner, dispatch, the log and its volume, block severity,
# the completion count, config lookup, the entry point and run_event. Contracts
# and resilience are test_engine_contracts.py; trust, timeouts, the ledger and
# the fail-closed gates are test_engine_safeguards.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess.run's process spawn and timeout mechanics; the tests stub it at the edge

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.hooks import handle_command, main, print_introspection
from aipass.hooks.apps.modules.engine import (
    dispatch,
    run_event,
    _run_hook,
    _log,
)
from aipass.hooks.apps.handlers.config.loader import find_project_config
from aipass.hooks.apps.handlers.config.trust_registry import enroll
from aipass.hooks.tests.support_engine import _GATE, _one

pytestmark = pytest.mark.usefixtures("_no_real_trust_banners")


def _fires(matcher: str, value: str) -> bool:
    """Whether dispatch() runs a handler hook with this matcher on an event whose tool_name is value."""
    module = MagicMock()
    module.handle.return_value = {"exit_code": 0, "stdout": ""}
    hook = {"enabled": True, "handler": "aipass.hooks.apps.handlers.probe.handle", "matcher": matcher}
    config = {"hooks_enabled": True, "Probe": {"probe": hook}}
    with patch("aipass.hooks.apps.modules.engine._import_handler_module", return_value=module):
        dispatch("Probe", json.dumps({"tool_name": value}) if value else "{}", config)
    return module.handle.called


class TestMatches:
    """Matcher logic, read as whether dispatch() runs the hook."""

    def test_empty_matcher_always_matches(self, mock_logger):
        assert _fires("", "Edit") is True

    def test_empty_matcher_matches_empty_value(self, mock_logger):
        assert _fires("", "") is True

    def test_single_match(self, mock_logger):
        assert _fires("Edit", "Edit") is True

    def test_single_no_match(self, mock_logger):
        assert _fires("Edit", "Bash") is False

    def test_pipe_delimited_match_first(self, mock_logger):
        assert _fires("Edit|Write|MultiEdit", "Edit") is True

    def test_pipe_delimited_match_middle(self, mock_logger):
        assert _fires("Edit|Write|MultiEdit", "Write") is True

    def test_pipe_delimited_match_last(self, mock_logger):
        assert _fires("Edit|Write|MultiEdit", "MultiEdit") is True

    def test_pipe_delimited_no_match(self, mock_logger):
        assert _fires("Edit|Write|MultiEdit", "Bash") is False

    def test_partial_name_does_not_match(self, mock_logger):
        assert _fires("Edit", "MultiEdit") is False
        assert _fires("MultiEdit", "Edit") is False

    def test_manual_auto_compact(self, mock_logger):
        assert _fires("manual|auto", "manual") is True
        assert _fires("manual|auto", "auto") is True


class TestRunHook:
    """Tests for _run_hook() subprocess execution."""

    def test_successful_hook(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="hello", stderr="")
        result = _run_hook("echo hello", "stdin_data")
        assert result["exit_code"] == 0
        assert result["stdout"] == "hello"
        assert result["elapsed_ms"] >= 0

    def test_hook_with_nonzero_exit(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = _run_hook("false", "")
        assert result["exit_code"] == 1
        assert result["stderr"] == "error"

    def test_hook_timeout(self, mock_subprocess, mock_logger):
        mock_subprocess.side_effect = subprocess.TimeoutExpired("cmd", 30)
        result = _run_hook("sleep 999", "", timeout_s=30)
        assert result["exit_code"] == -1
        assert result["stderr"] == "TIMEOUT"

    def test_hook_os_error(self, mock_subprocess, mock_logger, tmp_path):
        mock_subprocess.side_effect = OSError("No such file")
        result = _run_hook(str(tmp_path / "nonexistent"), "")
        assert result["exit_code"] == -1
        assert "No such file" in result["stderr"]

    def test_custom_timeout(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_hook("cmd", "", timeout_s=120)
        mock_subprocess.assert_called_once()
        assert mock_subprocess.call_args.kwargs["timeout"] == 120

    def test_default_timeout_is_30(self, mock_subprocess, mock_logger):
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_hook("cmd", "")
        assert mock_subprocess.call_args.kwargs["timeout"] == 30


class TestDispatch:
    """Tests for dispatch() core logic."""

    def test_hooks_disabled_returns_empty(self, mock_logger):
        config = {"hooks_enabled": False}
        result = dispatch("UserPromptSubmit", "{}", config)
        assert result[0] == ""
        assert result[1] == 0

    def test_no_hooks_for_event_returns_empty(self, mock_logger):
        config = {"hooks_enabled": True}
        result = dispatch("UnknownEvent", "{}", config)
        assert result[0] == ""
        assert result[1] == 0

    def test_disabled_hook_skipped(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "disabled_hook": {
                    "enabled": False,
                    "command": "echo fail",
                    "matcher": "",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        mock_run.assert_not_called()
        assert result[0] == ""
        assert result[1] == 0

    def test_matcher_filters_hooks(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "edit_only": {
                    "enabled": True,
                    "command": "echo matched",
                    "matcher": "Edit|Write",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {"exit_code": 0, "stdout": "matched", "stderr": "", "elapsed_ms": 10}
            dispatch("PreToolUse", '{"tool_name":"Bash"}', config)
        mock_run.assert_not_called()

    def test_matching_hook_fires(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "edit_hook": {
                    "enabled": True,
                    "command": "echo edit_output",
                    "matcher": "Edit|Write",
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {"exit_code": 0, "stdout": "edit_output", "stderr": "", "elapsed_ms": 10}
            result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        mock_run.assert_called_once()
        assert "edit_output" in result[0]
        assert result[1] == 0

    def test_multiple_hooks_concatenate_output(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hook_a": {"enabled": True, "command": "echo A", "matcher": ""},
                "hook_b": {"enabled": True, "command": "echo B", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.side_effect = [
                {"exit_code": 0, "stdout": "output_A", "stderr": "", "elapsed_ms": 10},
                {"exit_code": 0, "stdout": "output_B", "stderr": "", "elapsed_ms": 10},
            ]
            result = dispatch("UserPromptSubmit", '{"user_prompt":"test"}', config)
        assert mock_run.call_count == 2
        assert "output_A" in result[0]
        assert "output_B" in result[0]
        assert result[1] == 0

    def test_exit2_with_block_json_bails(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "blocker": {"enabled": True, "command": "block_cmd", "matcher": ""},
                "after_block": {"enabled": True, "command": "should_not_run", "matcher": ""},
            },
        }
        block_json = json.dumps({"decision": "block", "reason": "test block"})
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {"exit_code": 2, "stdout": block_json, "stderr": "", "elapsed_ms": 10}
            result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        assert mock_run.call_count == 1
        parsed = json.loads(result[0])
        assert parsed["decision"] == "block"
        assert result[1] == 2

    def test_exit2_without_json_is_crash_not_block(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "crashed": {"enabled": True, "command": "crash_cmd", "matcher": ""},
                "next_hook": {"enabled": True, "command": "echo survived", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.side_effect = [
                {"exit_code": 2, "stdout": "", "stderr": "file not found", "elapsed_ms": 10},
                {"exit_code": 0, "stdout": "survived", "stderr": "", "elapsed_ms": 10},
            ]
            result = dispatch("PreToolUse", '{"tool_name":"Edit"}', config)
        assert mock_run.call_count == 2
        assert "survived" in result[0]
        assert result[1] == 0

    def test_hook_with_custom_timeout(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "PreCompact": {
                "slow_hook": {
                    "enabled": True,
                    "command": "slow_cmd",
                    "matcher": "",
                    "timeout": 120,
                }
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 50}
            dispatch("PreCompact", '{"type":"manual"}', config)
        mock_run.assert_called_once_with("slow_cmd", '{"type":"manual"}', timeout_s=120)

    def test_empty_command_skipped(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "Stop": {
                "no_command": {"enabled": True, "command": "", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            dispatch("Stop", "{}", config)
        mock_run.assert_not_called()

    def test_malformed_stdin_does_not_crash(self, mock_logger):
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "hook": {"enabled": True, "command": "echo ok", "matcher": ""},
            },
        }
        with patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run:
            mock_run.return_value = {"exit_code": 0, "stdout": "ok", "stderr": "", "elapsed_ms": 5}
            result = dispatch("UserPromptSubmit", "not json at all{{{", config)
        assert "ok" in result[0]
        assert result[1] == 0

    def test_trust_break_banner_short_circuits_presence_gate_dispatch(self, mock_logger):
        """A hash-mismatch banner must reach the user even though presence_gate's own hook_def is empty."""
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch(
                "aipass.hooks.apps.handlers.config.loader.trust_break_banner",
                return_value="# TRUST BREAK — ALL AIPASS HOOKS DISABLED",
            ),
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_not_called()
        assert result == ("# TRUST BREAK — ALL AIPASS HOOKS DISABLED", 0)

    def test_no_trust_break_falls_through_to_normal_dispatch(self, mock_logger):
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        assert result == ("", 0)

    def test_never_enrolled_banner_short_circuits_dispatch(self, mock_logger):
        """A never-enrolled nudge must reach the user and skip normal hook dispatch."""
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
            patch(
                "aipass.hooks.apps.handlers.config.loader.never_enrolled_banner",
                return_value="# HOOKS ARE OFF — not yet enrolled",
            ),
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        mock_run.assert_not_called()
        assert result == ("# HOOKS ARE OFF — not yet enrolled", 0)

    def test_no_never_enrolled_nudge_falls_through_to_normal_dispatch(self, mock_logger):
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
            patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        assert result == ("", 0)

    def test_trust_break_takes_precedence_over_never_enrolled_nudge(self, mock_logger):
        """Both can't fire for the same project in practice, but trust_break must win if they did."""
        config = {"hooks_enabled": True, "UserPromptSubmit": {"presence_gate": {}}}
        with (
            patch(
                "aipass.hooks.apps.handlers.config.loader.trust_break_banner",
                return_value="# TRUST BREAK — ALL AIPASS HOOKS DISABLED",
            ) as mock_trust_banner,
            patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner") as mock_nudge,
        ):
            result = dispatch("UserPromptSubmit", "{}", config)
        mock_trust_banner.assert_called_once()
        mock_nudge.assert_not_called()
        assert result == ("# TRUST BREAK — ALL AIPASS HOOKS DISABLED", 0)

    def test_trust_break_check_runs_unconditionally_for_user_prompt_submit(self, mock_logger):
        """The check runs for every UserPromptSubmit dispatch, not just presence_gate-filtered calls."""
        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {"other_hook": {"enabled": True, "command": "echo hi", "matcher": ""}},
        }
        with (
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner") as mock_banner,
            patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_banner.return_value = None
            mock_run.return_value = {"exit_code": 0, "stdout": "hi", "stderr": "", "elapsed_ms": 5}
            dispatch("UserPromptSubmit", "{}", config)
        mock_banner.assert_called_once_with()  # the banner reads its own state: no argument filters it

    def test_trust_break_check_skipped_for_non_prompt_events(self, mock_logger):
        config = {"hooks_enabled": True, "PreToolUse": {"presence_gate": {}}}
        with (
            patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner") as mock_banner,
        ):
            dispatch("PreToolUse", "{}", config)
        mock_banner.assert_not_called()


class TestLogVolume:
    """Per-hook narration is suppressed in the prax stream by default.

    At ~3 lines per tool call it dominated system_logs/hooks_engine.log and
    tripped the runaway detector on ordinary multi-agent operation. engine.jsonl
    keeps the full record either way — these tests pin that split.
    """

    CONFIG = {
        "hooks_enabled": True,
        "PreToolUse": {
            "rm_gate": {"enabled": True, "command": "true", "matcher": ""},
            "off_hook": {"enabled": False, "command": "true", "matcher": ""},
        },
    }

    def _dispatch(self, mock_logger):
        with (
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1}
            dispatch("PreToolUse", '{"tool_name":"Bash"}', self.CONFIG)
        return mock_log

    def test_per_hook_lines_are_silent_by_default(self, mock_logger, monkeypatch):
        """No per-hook fire, no completion line, no skipped-disabled line."""
        monkeypatch.delenv("AIPASS_HOOKS_VERBOSE_LOG", raising=False)
        self._dispatch(mock_logger)

        emitted = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
        assert not [m for m in emitted if "agent=%s" in m]
        assert not [m for m in emitted if "complete:" in m]
        assert not [m for m in emitted if "skipped (disabled)" in m]

    def test_jsonl_still_records_everything(self, mock_logger, monkeypatch):
        """Suppression is stream-only — forensics must be untouched."""
        monkeypatch.delenv("AIPASS_HOOKS_VERBOSE_LOG", raising=False)
        mock_log = self._dispatch(mock_logger)

        entries = [c.args[0] for c in mock_log.call_args_list]
        skipped = [(e["event"], e["hook"]) for e in entries if e.get("action") == "skipped_disabled"]
        assert skipped == [("PreToolUse", "off_hook")]
        assert [e["event"] for e in entries if e.get("action") == "complete"] == ["PreToolUse"]
        ran = [(e["event"], e["hook"], e["exit_code"]) for e in entries if "exit_code" in e]
        assert ran == [("PreToolUse", "rm_gate", 0)]

    def test_each_hook_line_names_the_payload_session_so_parity_can_read_one_session(self, mock_logger):
        with (
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1}
            dispatch("PreToolUse", '{"tool_name":"Bash","session_id":"s-123"}', self.CONFIG)
        ran = [c.args[0] for c in mock_log.call_args_list if "exit_code" in c.args[0]]
        assert [e["session_id"] for e in ran] == ["s-123"]

    def test_verbose_env_restores_the_lines(self, mock_logger, monkeypatch):
        """AIPASS_HOOKS_VERBOSE_LOG=1 is the DEBUG-level stand-in."""
        monkeypatch.setenv("AIPASS_HOOKS_VERBOSE_LOG", "1")
        self._dispatch(mock_logger)

        emitted = [c.args[0] for c in mock_logger.info.call_args_list if c.args]
        assert [m for m in emitted if "agent=%s" in m]
        assert [m for m in emitted if "complete:" in m]

    def test_env_must_be_exactly_one(self, mock_logger, monkeypatch):
        """A stray truthy value must not accidentally reopen the firehose."""
        monkeypatch.setenv("AIPASS_HOOKS_VERBOSE_LOG", "0")
        self._dispatch(mock_logger)

        assert not [c for c in mock_logger.info.call_args_list if c.args and "complete:" in c.args[0]]

    def test_blocks_are_never_suppressed(self, mock_logger, monkeypatch):
        """Blocks stay RECORDED at default verbosity — that is the whole point.

        The level dropped to INFO (a gate that blocks is the gate working), but
        the record must still land. INFO here is a direct logger.info, NOT the
        _verbose helper, so the verbosity switch cannot swallow it.
        """
        monkeypatch.delenv("AIPASS_HOOKS_VERBOSE_LOG", raising=False)
        config = {
            "hooks_enabled": True,
            "PreToolUse": {"gate": {"enabled": True, "command": "block", "matcher": ""}},
        }
        with (
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.return_value = {
                "exit_code": 2,
                "stdout": json.dumps({"decision": "block"}),
                "stderr": "",
                "elapsed_ms": 1,
            }
            dispatch("PreToolUse", '{"tool_name":"Bash"}', config)

        assert [c for c in mock_logger.info.call_args_list if c.args and "blocked by" in c.args[0]]


class TestBlockSeverity:
    """A gate BLOCK is chosen, working behavior — it must not log at a level that
    escalates. Verified against the live log before reclassing, per compass #277:
    373 blocks spread over all 10 logged days, every working day, not one stuck
    session. The crash path beside it stays ERROR, which is the real signal."""

    CONFIG = {
        "hooks_enabled": True,
        "PreToolUse": {"gate": {"enabled": True, "command": "block", "matcher": ""}},
    }

    def _dispatch(self, stdout: str):
        with (
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 2, "stdout": stdout, "stderr": "", "elapsed_ms": 1}
            return dispatch("PreToolUse", '{"tool_name":"Edit"}', self.CONFIG)

    def test_intentional_block_does_not_log_at_warning(self, mock_logger):
        """The reclass itself: 390 lifetime WARNINGs and 6 digests for the gate working."""
        self._dispatch(json.dumps({"decision": "block", "reason": "nope"}))
        assert not [c for c in mock_logger.warning.call_args_list if c.args and "block" in c.args[0].lower()]

    def test_intentional_block_still_records_at_info(self, mock_logger):
        """Reclass must not delete the evidence — INFO is retained in the log file."""
        self._dispatch(json.dumps({"decision": "block", "reason": "nope"}))
        assert [c for c in mock_logger.info.call_args_list if c.args and "blocked by" in c.args[0]]

    def test_block_line_carries_the_reason(self, mock_logger):
        """Neither severity is diagnostic without knowing WHAT was blocked."""
        self._dispatch(json.dumps({"decision": "block", "reason": "Direct writes to inbox.json are blocked."}))
        calls = [c for c in mock_logger.info.call_args_list if c.args and "blocked by" in c.args[0]]
        assert any("inbox.json" in str(c.args[-1]) for c in calls)

    def test_block_line_uses_only_the_first_reason_line(self, mock_logger):
        """Gate reasons are multi-line; a log line is not a place to dump them."""
        self._dispatch(json.dumps({"decision": "block", "reason": "first line\nsecond line\nthird"}))
        calls = [c for c in mock_logger.info.call_args_list if c.args and "blocked by" in c.args[0]]
        assert calls and all("second line" not in str(c.args[-1]) for c in calls)

    def test_block_without_reason_does_not_crash(self, mock_logger):
        """A gate may block with no reason field — the engine still records it."""
        self._dispatch(json.dumps({"decision": "block"}))
        assert [c for c in mock_logger.info.call_args_list if c.args and "blocked by" in c.args[0]]

    def test_crash_at_exit_2_stays_error(self, mock_logger):
        """GUARD: the reclass must not soften a genuine crash. Non-block exit=2."""
        self._dispatch("not json at all")
        assert [c for c in mock_logger.error.call_args_list if c.args and "CRASHED" in c.args[0]]


class TestCompletionCount:
    """The 'complete: N hooks' line must count hooks that RAN, not hooks that
    wrote stdout. Silent gates (rm_gate, git_gate) pass with empty output, so
    counting outputs reported 'complete: 0 hooks' while gates had just run —
    a lie that reads as 'the engine did nothing'."""

    @pytest.fixture(autouse=True)
    def _verbose(self, monkeypatch):
        """These assert on the narration lines, so turn them back on."""
        monkeypatch.setenv("AIPASS_HOOKS_VERBOSE_LOG", "1")

    SILENT = {
        "hooks_enabled": True,
        "PreToolUse": {
            "rm_gate": {"enabled": True, "command": "true", "matcher": ""},
            "git_gate": {"enabled": True, "command": "true", "matcher": ""},
        },
    }

    def _complete_line(self, mock_logger):
        for call in mock_logger.info.call_args_list:
            if call.args and "complete:" in call.args[0]:
                return call.args
        raise AssertionError("no completion line logged")

    def test_silent_hooks_are_counted_as_run(self, mock_logger):
        """Two gates run and pass quietly — the log must say 2, not 0."""
        with (
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1}
            dispatch("PreToolUse", '{"tool_name":"Bash"}', self.SILENT)

        assert self._complete_line(mock_logger)[2] == 2

    def test_jsonl_hooks_run_counts_executions_not_outputs(self, mock_logger):
        """engine.jsonl carried the same misnomer — hooks_run was len(outputs)."""
        with (
            patch("aipass.hooks.apps.modules.engine._log") as mock_log,
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.return_value = {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1}
            dispatch("PreToolUse", '{"tool_name":"Bash"}', self.SILENT)

        complete = [c.args[0] for c in mock_log.call_args_list if c.args[0].get("action") == "complete"][0]
        assert complete["event"] == "PreToolUse"
        ran = [(e["event"], e["hook"]) for e in (c.args[0] for c in mock_log.call_args_list) if "exit_code" in e]
        assert ran == [("PreToolUse", "rm_gate"), ("PreToolUse", "git_gate")]
        assert complete["hooks_run"] == 2
        assert complete["hooks_with_output"] == 0

    def test_count_matches_the_per_hook_lines_above_it(self, mock_logger):
        """The invariant a log reader relies on: the completion count equals the
        number of per-hook lines printed for that dispatch."""
        config = {
            "hooks_enabled": True,
            "PreToolUse": {
                "quiet": {"enabled": True, "command": "true", "matcher": ""},
                "loud": {"enabled": True, "command": "echo hi", "matcher": ""},
                "off": {"enabled": False, "command": "true", "matcher": ""},
                "unmatched": {"enabled": True, "command": "true", "matcher": "Edit"},
            },
        }
        with (
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.side_effect = [
                {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1},
                {"exit_code": 0, "stdout": "hi", "stderr": "", "elapsed_ms": 1},
            ]
            dispatch("PreToolUse", '{"tool_name":"Bash"}', config)

        assert mock_run.call_count == 2
        per_hook = [c for c in mock_logger.info.call_args_list if c.args and "agent=%s" in c.args[0]]
        assert len(per_hook) == 2
        assert self._complete_line(mock_logger)[2] == len(per_hook)

    def test_timed_out_hook_is_not_counted_as_run(self, mock_logger):
        """A timeout gets its own loud line and no per-hook line, so it must not
        inflate the completion count."""
        with (
            patch("aipass.hooks.apps.modules.engine._run_hook") as mock_run,
        ):
            mock_run.side_effect = [
                {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "elapsed_ms": 30000},
                {"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1},
            ]
            dispatch("PreToolUse", '{"tool_name":"Bash"}', self.SILENT)

        assert mock_run.call_count == 2
        assert self._complete_line(mock_logger)[2] == 1


class TestFindProjectConfig:
    """Tests for find_project_config() CWD walk."""

    def test_finds_config_in_cwd(self, hooks_config_file, temp_test_dir, mock_logger):
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch(
                "aipass.hooks.apps.handlers.config.loader._search_bounds",
                return_value=(temp_test_dir, temp_test_dir.parent),
            ),
        ):
            config = find_project_config()
        assert config is not None
        assert config["hooks_enabled"] is True

    def test_returns_none_when_no_config(self, temp_test_dir, mock_logger):
        with patch(
            "aipass.hooks.apps.handlers.config.loader._search_bounds",
            return_value=(temp_test_dir, temp_test_dir.parent),
        ):
            config = find_project_config()
        assert config is None

    def test_expands_aipass_home(self, temp_test_dir, mock_logger):
        config_dir = temp_test_dir / ".aipass"
        config_dir.mkdir()
        config = {
            "hooks_enabled": True,
            "Stop": {"sound": {"enabled": True, "command": "python3 $AIPASS_HOME/hook.py", "matcher": ""}},
        }
        (config_dir / "hooks.json").write_text(json.dumps(config), encoding="utf-8")
        reg_path = temp_test_dir / "registry.json"
        with patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path):
            enroll(str(temp_test_dir))
        with (
            patch("aipass.hooks.apps.handlers.config.trust_registry.REGISTRY_PATH", reg_path),
            patch(
                "aipass.hooks.apps.handlers.config.loader._search_bounds",
                return_value=(temp_test_dir, temp_test_dir.parent),
            ),
            patch.dict("os.environ", {"AIPASS_HOME": "/test/path"}),
        ):
            result = find_project_config()
        assert (result or {}).get("Stop", {}).get("sound", {}).get("command") == "python3 /test/path/hook.py"


class TestLog:
    """Tests for _log() JSONL diagnostics."""

    def test_writes_jsonl_entry(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "Test", "action": "test_write"})
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "Test"
        assert entry["action"] == "test_write"

    def test_creates_parent_directory(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "subdir" / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "Test"})
        assert log_file.exists()

    def test_appends_multiple_entries(self, temp_test_dir, mock_logger):
        log_file = temp_test_dir / "test.jsonl"
        with patch("aipass.hooks.apps.handlers.config.diagnostics._get_log_file", return_value=log_file):
            _log({"event": "A"})
            _log({"event": "B"})
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2


class TestHooksEntryPoint:
    """Tests for hooks.py CLI routing."""

    def test_help_returns_zero(self):
        with patch("sys.argv", ["hooks", "--help"]):
            assert main() == 0

    def test_version_returns_zero(self):
        with patch("sys.argv", ["hooks", "--version"]):
            assert main() == 0

    def test_no_args_shows_help(self):
        with patch("sys.argv", ["hooks"]):
            assert main() == 0

    def test_unknown_command_returns_one(self):
        with patch("sys.argv", ["hooks", "nonexistent_command"]):
            assert main() == 1

    def test_print_introspection_prints_output(self, capsys):
        print_introspection()
        captured = capsys.readouterr()
        assert "HOOKS" in captured.out
        assert "Discovered Modules" in captured.out

    def test_handle_command_returns_bool(self):
        result = handle_command("nonexistent", [])
        assert result is False

    def test_status_with_no_config_exits_one_through_the_entry_point(self):
        """The routed `status` refusal reaches the shell as exit 1 (FPLAN-0507).

        This pin used to assert True with a patch on the LOADER's name, which
        hookstatus binds at import — so the patch bit only when hookstatus was
        first imported inside the patch window. In the full suite an earlier
        import had already bound the real function, the patch was inert, the
        real config was found and True came back; alone, or on a fresh xdist
        worker (the Linux CI on 8769a799), the patch bit and the test pinned
        the exit-0 defect FPLAN-0507 had just cured. Patch the name hookstatus
        actually calls, and pin the cured outcome.
        """
        with (
            patch("aipass.hooks.apps.modules.hookstatus.find_project_config", return_value=None),
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("status", [])
        assert exit_info.value.code == 1

    def test_log_command_prints_the_log_tail_to_stderr(self, tmp_path, capsys):
        """Green from its first run; its proof is a mutant on the printed line."""
        log_file = tmp_path / "engine.jsonl"
        log_file.write_text('{"event": "first"}\n{"event": "second"}\n', encoding="utf-8")
        with patch("aipass.hooks.apps.handlers.config.diagnostics.LOG_FILE", log_file):
            result = handle_command("log", [])
        out, err = capsys.readouterr()
        assert result is True
        assert '{"event": "first"}' in err
        assert '{"event": "second"}' in err
        assert "No engine log found" not in err

    def test_short_help_flag(self):
        with patch("sys.argv", ["hooks", "-h"]):
            assert main() == 0

    def test_help_word(self):
        with patch("sys.argv", ["hooks", "help"]):
            assert main() == 0


class TestRunEvent:
    """The bridges' logic, served from the promoted copy (DPLAN-0356 item 3)."""

    def test_it_dispatches_the_resolved_config_never_an_empty_one(self, mock_logger):
        with (
            patch("aipass.hooks.apps.handlers.config.loader.resolve_config", return_value=_one(_GATE)) as resolved,
            patch("aipass.hooks.apps.modules.engine.dispatch", return_value=("", 0)) as sent,
        ):
            run_event("PreToolUse", "{}")
        resolved.assert_called_once()
        assert sent.call_args[0][2]["PreToolUse"]["the_hook"]["handler"] == _GATE

    def test_a_named_hook_is_cut_out_of_the_config(self, mock_logger):
        with (
            patch("aipass.hooks.apps.handlers.config.loader.resolve_config", return_value=_one(_GATE)),
            patch("aipass.hooks.apps.modules.engine.dispatch", return_value=("", 0)) as sent,
        ):
            run_event("PreToolUse:the_hook", "{}")
        assert sent.call_args[0][2] == {
            "hooks_enabled": True,
            "PreToolUse": {"the_hook": _one(_GATE)["PreToolUse"]["the_hook"]},
        }

    def _project_row(self, config: dict) -> dict:
        """The config run_event hands dispatch for the generic UserPromptSubmit:project row."""
        with (
            patch("aipass.hooks.apps.handlers.config.loader.resolve_config", return_value=config),
            patch("aipass.hooks.apps.modules.engine.dispatch", return_value=("", 0)) as sent,
        ):
            run_event("UserPromptSubmit:project", "{}")
        return sent.call_args[0][2]

    _OWN = {"enabled": True, "handler": "hark.hark.apps.modules.hook_events.record", "matcher": ""}
    _HOUSE = {"enabled": True, "handler": "aipass.hooks.apps.handlers.prompt.temporal.handle", "matcher": ""}

    def test_the_project_row_runs_only_the_projects_own_handlers(self, mock_logger):
        group = {"temporal": self._HOUSE, "hark_events": self._OWN, "gauge": self._HOUSE}
        config = {"hooks_enabled": True, "_handler_namespace": "hark", "UserPromptSubmit": group}
        sent = self._project_row(config)
        assert sent["UserPromptSubmit"] == {"hark_events": self._OWN}
        assert sent["_handler_namespace"] == "hark"

    def test_the_project_row_runs_nothing_without_a_namespace(self, mock_logger):
        config = {"hooks_enabled": True, "UserPromptSubmit": {"temporal": self._HOUSE, "hark_events": self._OWN}}
        assert self._project_row(config)["UserPromptSubmit"] == {}

    def test_the_project_row_answers_nothing_in_aipass_own_tree(self, mock_logger):
        config = {"hooks_enabled": True, "UserPromptSubmit": {"temporal": self._HOUSE}}
        with patch("aipass.hooks.apps.handlers.config.loader.resolve_config", return_value=config):
            assert run_event("UserPromptSubmit:project", "{}") == ("", 0)
