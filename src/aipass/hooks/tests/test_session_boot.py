# =================== AIPass ====================
# Name: test_session_boot.py
# Version: 1.1.1
# Description: Tests for session boot wrapper (menu-based attach/start/close)
# Branch: hooks
# Created: 2026-07-01
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/lifecycle/session_boot.py."""

# Menu-based attach/start/close.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/lifecycle/session_boot.py parses and imports
# seedgo: no-test-needed(documentation) — the module docstring's menu transcript, illustrative text only
# seedgo: no-test-needed(stdlib) — shutil.which and subprocess.run's own process-launch mechanics, stubbed at the edge
# seedgo: no-test-needed(log_level) — logger.info, logger.warning and logger.error prose; that row judges them

import json
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.handlers.lifecycle import session_boot
from aipass.hooks.tests.support_session_boot import _MOD, _kept_redirect, make_transcript

# conftest's tmux-lookup stub, for every test here (it skips the lookup's own classes).
pytestmark = pytest.mark.usefixtures("_no_real_tmux_lookup")

_CLAUDE = "/usr/local/bin/claude"


def _boot(tmp_path, live, choice, extra_args=None, quiet=True):
    """boot() at a menu: `choice` is one answer or a list of successive answers; quiet mutes the drift probe."""
    answers = iter(choice) if isinstance(choice, list) else None
    with (
        patch.dict("os.environ", _kept_redirect(), clear=True),
        patch.object(session_boot, "_resolve_claude_binary", return_value=_CLAUDE),
        patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
        patch.object(session_boot, "_find_live_sessions", return_value=live),
        patch.object(session_boot, "_read_choice", side_effect=lambda *_: next(answers) if answers else choice),
    ):
        if quiet:
            with patch.object(session_boot, "_warn_on_version_drift", return_value=""):
                return session_boot.boot(cwd=str(tmp_path), extra_args=extra_args)
        return session_boot.boot(cwd=str(tmp_path), extra_args=extra_args)


class TestBoot:
    def test_already_in_tmux_execs_directly(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": f"{tmp_path / 'tmux-1000' / 'default'},123,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "/usr/local/bin/claude"
        assert "--permission-mode" in args[1]
        assert "bypassPermissions" in args[1]

    def test_already_in_tmux_passes_extra_args(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": f"{tmp_path / 'tmux-1000' / 'default'},123,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--resume"])
        args = mock_exec.call_args[0][1]
        assert "--resume" in args

    def test_no_tmux_errors(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value=None),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 1
        assert "tmux not found" in result["error"]

    def test_live_session_resume_via_tmux(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value="hooks"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_exec.assert_called_once_with("tmux", ["tmux", "attach-session", "-t", "hooks"])

    def test_live_session_resume_continues_dead_window(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0][1]
        assert "--continue" in args

    def test_live_session_resume_bg_does_takeover(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_takeover_bg", return_value={"exit_code": 0, "action": "takeover"}
            ) as mock_take,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        mock_take.assert_called_once()
        assert result["action"] == "takeover"

    def test_live_session_new_stops_old(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_stop_session") as mock_stop,
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp"),
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_stop.assert_called_once_with(live[0], "/usr/local/bin/claude")

    def test_live_session_close_stops_and_exits(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="c"),
            patch.object(session_boot, "_stop_session") as mock_stop,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        mock_stop.assert_called_once()
        assert result["action"] == "closed"

    def test_no_live_continue_last(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0][1]
        assert "--continue" in args

    def test_no_live_new_starts_fresh(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0]
        assert args[0] == "tmux"
        assert "new-session" in args[1]
        assert "/usr/local/bin/claude" in args[1]

    def test_a_fresh_start_never_kills_a_tmux_session(self, tmp_path):
        """'n' used to kill the tmux session named <branch>, which a live chat can hold; its name is new now."""
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=True),
            patch(f"{_MOD}.subprocess.run") as mock_run,
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        assert not [c for c in mock_run.call_args_list if "kill-session" in str(c)]
        argv = mock_exec.call_args[0][1]
        assert argv[argv.index("-s") + 1] == f"{tmp_path.name}-{argv[argv.index('--session-id') + 1][:8]}"

    def test_extra_args_passed_on_fresh_start(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--resume"])
        args = mock_exec.call_args[0][1]
        assert "--resume" in args


class TestStopSession:
    def test_bg_returns_honest_no_stop(self):
        session = {"pid": 1234, "kind": "bg"}
        result = session_boot._stop_session(session, "/usr/local/bin/claude")
        assert "no per-job stop" in result

    def test_bg_background_kind_also_honest(self):
        session = {"pid": 1234, "kind": "background"}
        result = session_boot._stop_session(session, "/usr/local/bin/claude")
        assert "no per-job stop" in result

    def test_bg_never_sigterms(self):
        session = {"pid": 1234, "kind": "bg"}
        with patch(f"{_MOD}._kill") as mock_kill:
            session_boot._stop_session(session, "/usr/local/bin/claude")
        mock_kill.assert_not_called()

    def test_tmux_session_killed(self, tmp_path, capsys):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value="hooks"),
            patch(f"{_MOD}.subprocess.run") as mock_run,
            patch(f"{_MOD}._kill") as mock_kill,
        ):
            result = _boot(tmp_path, live, "c")
        kill_calls = [c for c in mock_run.call_args_list if c.args[0] == ["tmux", "kill-session", "-t", "hooks"]]
        assert len(kill_calls) == 1
        mock_kill.assert_not_called()
        assert "PID 1234: killed tmux session 'hooks'" in capsys.readouterr().err
        assert result["action"] == "closed"

    def test_plain_session_sigterm(self, tmp_path, capsys):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with patch(f"{_MOD}._kill") as mock_kill:
            _boot(tmp_path, live, "c")
        mock_kill.assert_called_once_with(1234, signal.SIGTERM)
        assert "PID 1234: sent SIGTERM" in capsys.readouterr().err

    def test_plain_session_already_dead(self, tmp_path, capsys):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with patch(f"{_MOD}._kill", side_effect=ProcessLookupError):
            result = _boot(tmp_path, live, "c")
        assert "PID 1234: already dead" in capsys.readouterr().err
        assert result["action"] == "closed"


class TestMain:
    def test_success(self, capsys):
        """A successful boot exits silently - main() calls boot once and returns.

        Had no oracle: main() was called and nothing was checked, so a main()
        that never reached boot at all, or that wrote to stderr on the happy
        path, passed. The sibling below pins the failure leg; this pins the one
        it has to be different from.
        """
        with patch.object(session_boot, "boot", return_value={"exit_code": 0, "action": "started"}) as mock_boot:
            assert session_boot.main() is None

        assert mock_boot.call_count == 1
        assert capsys.readouterr().err == ""

    def test_failure_exits(self):
        import pytest

        with (
            patch.object(session_boot, "boot", return_value={"exit_code": 1, "error": "tmux not found"}),
            pytest.raises(SystemExit, match="1"),
        ):
            session_boot.main()

    def test_passes_sys_argv(self):
        with (
            patch.object(session_boot, "boot", return_value={"exit_code": 0}) as mock_boot,
            patch(f"{_MOD}.sys.argv", ["session_boot", "--resume", "--verbose"]),
        ):
            session_boot.main()
        mock_boot.assert_called_once_with(extra_args=["--resume", "--verbose"])

    def test_no_extra_args_when_no_argv(self):
        with (
            patch.object(session_boot, "boot", return_value={"exit_code": 0}) as mock_boot,
            patch(f"{_MOD}.sys.argv", ["session_boot"]),
        ):
            session_boot.main()
        mock_boot.assert_called_once_with(extra_args=None)


class TestHeadlessBypass:
    def test_p_flag_skips_tmux_and_runs_directly(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "do something"])
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0][1]
        assert args[0] == "/usr/local/bin/claude"
        assert "-p" in args
        assert "do something" in args

    def test_p_flag_does_not_look_for_live_sessions(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_live_sessions") as mock_live,
            patch(f"{_MOD}._execvp"),
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query"])
        mock_live.assert_not_called()

    def test_p_flag_does_not_require_tmux(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value=None),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query"])
        assert result["action"] == "direct"
        assert result["reason"] == "headless -p mode"
        mock_exec.assert_called_once()

    def test_p_flag_still_gets_permission_mode_default(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query"])
        cmd = mock_exec.call_args[0][1]
        assert "--permission-mode" in cmd
        assert "bypassPermissions" in cmd

    def test_p_flag_respects_custom_permission_mode(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query", "--permission-mode", "default"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "default" in cmd


class TestPermissionModeDedupe:
    def test_no_extra_args_includes_default(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": f"{tmp_path / 'tmux-1000' / 'default'},1,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "bypassPermissions" in cmd

    def test_extra_args_with_permission_mode_no_double(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": f"{tmp_path / 'tmux-1000' / 'default'},1,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "default"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "default" in cmd
        assert "bypassPermissions" not in cmd

    def test_extra_args_without_permission_mode_gets_default(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": f"{tmp_path / 'tmux-1000' / 'default'},1,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--resume"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "bypassPermissions" in cmd
        assert "--resume" in cmd

    def test_fresh_start_dedupes_too(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "acceptEdits"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "acceptEdits" in cmd


class TestMultipleLiveSessions:
    def test_close_all(self, tmp_path):
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="c"),
            patch.object(session_boot, "_stop_session", return_value="stopped") as mock_stop,
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["action"] == "closed_all"
        mock_stop.assert_called_once()

    def test_pick_a_chat_held_by_a_seat_attaches(self, tmp_path, fake_projects):
        """Numbers address CHATS now. Picking one a live seat holds must ATTACH —
        spawning --resume against a held sessionId is what put two PIDs on one
        sessionId on 2026-08-18."""
        make_transcript(fake_projects, tmp_path, "abc", "Held chat", 4)
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "interactive"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="1"),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value="hooks"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_exec.assert_called_once_with("tmux", ["tmux", "attach-session", "-t", "hooks"])

    def test_pick_a_chat_held_by_bg_triggers_takeover(self, tmp_path, fake_projects):
        make_transcript(fake_projects, tmp_path, "def", "Bg chat", 3)
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="1"),
            patch.object(
                session_boot, "_takeover_bg", return_value={"exit_code": 0, "action": "takeover"}
            ) as mock_take,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        mock_take.assert_called_once()
        assert result["action"] == "takeover"

    def test_enter_continues_last_chat(self, tmp_path, fake_projects):
        """DEFECT A2, inverted. This test used to assert Enter was REJECTED — it
        pinned the missing continue-last path as if it were the contract. Single
        and no-live menus both offered it; only the >=2 menu had no way back to
        the conversation."""
        make_transcript(fake_projects, tmp_path, "newest", "Newest chat", 9)
        live = [
            {"pid": 1234, "sessionId": "held", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "other", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        cmd = mock_exec.call_args[0][2]
        assert "--resume" in cmd and "newest" in cmd

    def test_n_stops_stoppable_then_starts(self, tmp_path):
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_stop_session", return_value="stopped") as mock_stop,
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_stop.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "tmux"
        assert "new-session" in args[1]


class TestTakeover:
    def test_takeover_bg_runs_daemon_stop(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc12345-full-uuid", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}) as mock_daemon,
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "")
        mock_daemon.assert_called_once_with(_CLAUDE, tmp_path.name, 1234)
        args = mock_exec.call_args[0][1]
        assert "--resume" in args
        assert "abc12345-full-uuid" in args
        assert "new-session" in args

    def test_takeover_bg_no_session_id_continues(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "")
        args = mock_exec.call_args[0][1]
        assert "--continue" in args
        assert "--resume" not in args

    def test_takeover_daemon_stop_failure(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(f"{_MOD}.subprocess.run", side_effect=OSError("no claude")),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            result = _boot(tmp_path, live, "")
        assert result["exit_code"] == 1
        assert "daemon stop failed" in result["error"]
        mock_exec.assert_not_called()

    def test_takeover_nonzero_returncode_aborts(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=1, stderr="something failed")),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            result = _boot(tmp_path, live, "")
        assert result["exit_code"] == 1
        assert "daemon stop exit 1: something failed" in result["error"]
        mock_exec.assert_not_called()

    def test_single_bg_enter_is_takeover(self, tmp_path):
        """Enter on the one bg chat hands THAT session, this branch and the resolved binary to the takeover.

        Wider than test_live_session_resume_bg_does_takeover, which pins only that a takeover
        ran; proven by mutants that swap the branch and drop the defaults.
        """
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_takeover_bg", return_value={"exit_code": 0, "action": "takeover"}
            ) as mock_take,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        mock_take.assert_called_once_with(
            live[0], tmp_path.name, "/usr/local/bin/claude", ["--permission-mode", "bypassPermissions"], None
        )
        assert result["action"] == "takeover"

    def test_single_bg_n_stops_then_fresh(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0]
        assert args[0] == "tmux"
        assert "new-session" in args[1]

    def test_single_bg_c_stops(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="c"),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["action"] == "closed"


class TestBgResume:
    def test_bg_resume_routes_to_takeover(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}) as mock_daemon,
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            result = _boot(tmp_path, live, "")
        mock_daemon.assert_called_once()
        args = mock_exec.call_args[0][1]
        assert args[args.index("--resume") + 1] == "abc"
        assert result["action"] == "started"

    def test_bg_resume_never_opens_agents_view(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "")
        args = mock_exec.call_args[0][1]
        assert "--resume" in args
        assert "agents" not in args


def _label_line(err: str) -> str:
    """The single-session menu's header line, where the session label is printed."""
    return next(line for line in err.splitlines() if "live chat:" in line)


class TestSessionLabelAutoName:
    def test_bg_label_includes_auto_name(self, tmp_path, capsys):
        live = [{"pid": 1234, "sessionId": "abc12345", "kind": "bg", "name": "chroma review"}]
        _boot(tmp_path, live, "q")
        label = _label_line(capsys.readouterr().err)
        assert '"chroma review"' in label
        assert "abc12345" in label

    def test_interactive_label_no_name(self, tmp_path, capsys):
        live = [{"pid": 1234, "sessionId": "abc12345", "kind": "interactive"}]
        _boot(tmp_path, live, "q")
        label = _label_line(capsys.readouterr().err)
        assert label.endswith("PID 1234 · abc12345 · interactive")

    def test_bg_label_no_name_field(self, tmp_path, capsys):
        live = [{"pid": 1234, "sessionId": "abc12345", "kind": "bg"}]
        _boot(tmp_path, live, "q")
        label = _label_line(capsys.readouterr().err)
        assert '"' not in label
        assert label.endswith("PID 1234 · abc12345 · bg")


class TestDaemonStop:
    """Reached through the single-bg menu's [c]: close it and exit."""

    _live = [{"pid": 1234, "sessionId": "abc", "kind": "bg"}]

    def test_success_no_collateral(self, tmp_path, capsys):
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch.object(session_boot, "_is_session_file_present", return_value=False),
        ):
            result = _boot(tmp_path, self._live, "c")
        assert mock_run.call_args[0][0] == [_CLAUDE, "daemon", "stop", "--any"]
        assert result["action"] == "closed"
        assert "Stopped bg session PID 1234." in capsys.readouterr().err

    def test_nonzero_returncode_fails(self, tmp_path):
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=1, stderr="something broke")),
        ):
            result = _boot(tmp_path, self._live, "c")
        assert result["exit_code"] == 1
        assert "exit 1" in result["error"]

    def test_oserror_fails(self, tmp_path):
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(f"{_MOD}.subprocess.run", side_effect=OSError("no binary")),
        ):
            result = _boot(tmp_path, self._live, "c")
        assert result["exit_code"] == 1
        assert "daemon stop failed: no binary" in result["error"]

    def test_collateral_confirmed_proceeds(self, tmp_path, capsys):
        collateral = [{"pid": 9999, "cwd": str(tmp_path / "other"), "sessionId": "xyz"}]
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=collateral),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch.object(session_boot, "_is_session_file_present", return_value=False),
        ):
            result = _boot(tmp_path, self._live, ["c", "y"])
        mock_run.assert_called_once()
        assert result["action"] == "closed"
        assert "PID 9999 · other · xyz" in capsys.readouterr().err

    def test_collateral_denied_cancels(self, tmp_path):
        collateral = [{"pid": 9999, "cwd": str(tmp_path / "other"), "sessionId": "xyz"}]
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=collateral),
            patch(f"{_MOD}.subprocess.run") as mock_run,
        ):
            result = _boot(tmp_path, self._live, ["c", "n"])
        mock_run.assert_not_called()
        assert result["exit_code"] == 1
        assert "cancelled" in result["error"]


class TestExtraArgsThreading:
    """R6: extra_args must reach every launch path, not just _start_fresh."""

    def test_resume_dead_window_threads_extra_args(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "", extra_args=["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--continue" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_takeover_bg_threads_extra_args(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc-uuid", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "", extra_args=["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--resume" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_takeover_bg_continue_threads_extra_args(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "", extra_args=["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--continue" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_no_live_continue_threads_extra_args(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--continue" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_live_bg_enter_threads_extra_args(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--resume" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_multi_session_pick_threads_extra_args(self, tmp_path, fake_projects):
        make_transcript(fake_projects, tmp_path, "abc", "Orphaned window chat", 5)
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "interactive"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="1"),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--continue" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd


class TestNewOverAllAbort:
    def test_aborts_on_daemon_stop_failure(self, tmp_path):
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_stop_session", return_value="stopped"),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": False, "error": "failed"}),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 1
        assert "one-brain" in result["error"]
        mock_exec.assert_not_called()


class TestMenuQuit:
    def test_single_session_q_quits(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="q"),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        assert result["action"] == "quit"

    def test_single_session_exit_quits(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="exit"),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["action"] == "quit"

    def test_multi_session_quit_quits(self, tmp_path):
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "interactive"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="quit"),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["action"] == "quit"

    def test_no_live_q_quits(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="q"),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["action"] == "quit"


class TestAutoNamer:
    """R7: --name flag stamped on every launch for self-identifying sessions."""

    def test_fresh_start_gets_name(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd
        # Since FPLAN-0448 a fresh start MINTS its session id, so its name
        # carries the short id like every resumed seat's does — this used to
        # pin the bare branch name, which was just "no id known yet".
        branch = tmp_path.name
        minted = cmd[cmd.index("--session-id") + 1]
        idx = cmd.index("--name")
        assert cmd[idx + 1] == f"{branch}-{minted[:8]}"

    def test_takeover_gets_name_with_session_id(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc12345-full-uuid", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "")
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd
        idx = cmd.index("--name")
        assert cmd[idx + 1] == f"{tmp_path.name}-abc12345"

    def test_in_tmux_gets_name(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": f"{tmp_path / 'tmux-1000' / 'default'},123,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd

    def test_no_live_continue_gets_name(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd

    def test_user_name_not_overridden(self, tmp_path):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--name", "myname"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--name") == 1
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "myname"

    def test_dead_window_resume_gets_name_with_session_id(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc12345-uuid", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}._execvp") as mock_exec,
        ):
            _boot(tmp_path, live, "")
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd
        idx = cmd.index("--name")
        assert cmd[idx + 1] == f"{tmp_path.name}-abc12345"


class TestPickerOffersChatsNotProcesses:
    """The 2026-08-18 loss: Ctrl+C removes the dead chat's session file, so the
    conversation the owner wanted was the one thing a PID list could not show —
    while three bg leftovers were offered as if they were his chats."""

    def _boot(self, tmp_path, live, choice, projects_root=None):
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_warn_on_version_drift", return_value=""),
            patch.object(session_boot, "_read_choice", return_value=choice),
            patch.object(session_boot, "_exec_in_tmux", return_value={"exit_code": 0}) as mock_exec,
            patch.object(session_boot, "_stop_session", return_value="stopped"),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        return result, mock_exec

    def test_menu_lists_chats_from_transcripts(self, tmp_path, fake_projects, capsys):
        make_transcript(fake_projects, tmp_path, "aaaaaaaa-1", "Context weight", 109)
        live = [
            {"pid": 1, "sessionId": "live-1", "cwd": str(tmp_path), "kind": "bg"},
            {"pid": 2, "sessionId": "live-2", "cwd": str(tmp_path), "kind": "bg"},
        ]
        self._boot(tmp_path, live, "q")
        out = capsys.readouterr().err
        assert "Context weight" in out
        assert "109 msgs" in out

    def test_a_dead_chat_is_still_offered(self, tmp_path, fake_projects, capsys):
        """The whole point: no live process holds it, and it must still be pickable."""
        make_transcript(fake_projects, tmp_path, "dead-chat", "The one he wanted", 61)
        live = [
            {"pid": 1, "sessionId": "bg-a", "cwd": str(tmp_path), "kind": "bg"},
            {"pid": 2, "sessionId": "bg-b", "cwd": str(tmp_path), "kind": "bg"},
        ]
        result, mock_exec = self._boot(tmp_path, live, "1")

        # OFFERED is half the claim and the capture was already being asked for
        # to prove it - then never read. The picker printing nothing while the
        # resume still worked would have passed, and "no live process holds it,
        # and it must still be pickable" is a statement about the MENU.
        menu = capsys.readouterr().err
        assert "The one he wanted" in menu
        assert "61 msgs" in menu

        cmd = mock_exec.call_args[0][2]
        assert "--resume" in cmd and "dead-chat" in cmd

    def test_bg_leftovers_are_named_leftovers_not_chats(self, tmp_path, fake_projects, capsys):
        make_transcript(fake_projects, tmp_path, "real-chat", "A real chat", 5)
        live = [
            {"pid": 773292, "sessionId": "bg-a", "cwd": str(tmp_path), "kind": "bg"},
            {"pid": 773293, "sessionId": "bg-b", "cwd": str(tmp_path), "kind": "bg"},
        ]
        self._boot(tmp_path, live, "q")
        out = capsys.readouterr().err
        assert "bg leftover" in out
        assert "not chats" in out

    def test_enter_continues_the_newest_chat(self, tmp_path, fake_projects):
        make_transcript(fake_projects, tmp_path, "older", "Older", 3, age_seconds=9000)
        make_transcript(fake_projects, tmp_path, "newest", "Newest", 4)
        live = [
            {"pid": 1, "sessionId": "bg-a", "cwd": str(tmp_path), "kind": "bg"},
            {"pid": 2, "sessionId": "bg-b", "cwd": str(tmp_path), "kind": "bg"},
        ]
        result, mock_exec = self._boot(tmp_path, live, "")
        cmd = mock_exec.call_args[0][2]
        assert "newest" in cmd

    def test_a_held_chat_attaches_it_does_not_spawn_a_second_brain(self, tmp_path, fake_projects):
        """One-brain at the one place a hand can break it: --resume against a
        held sessionId is exactly what put two PIDs on e4cd682a."""
        make_transcript(fake_projects, tmp_path, "held-chat", "Held", 12)
        live = [
            {"pid": 4242, "sessionId": "held-chat", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 4243, "sessionId": "bg-b", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with patch.object(session_boot, "_resume_session", return_value={"exit_code": 0}) as mock_resume:
            result, mock_exec = self._boot(tmp_path, live, "1")
        mock_resume.assert_called_once()
        assert mock_resume.call_args[0][0]["pid"] == 4242
        mock_exec.assert_not_called()

    def test_a_live_seats_chat_outside_the_window_is_still_reachable(self, tmp_path, fake_projects, capsys):
        """Showing the process while hiding the only door into it would repeat
        the defect in miniature."""
        make_transcript(fake_projects, fake_projects.parent, "x", "unrelated", 1)
        make_transcript(fake_projects, tmp_path, "ancient-held", "Ancient held chat", 8, age_seconds=999999)
        for i in range(5):
            make_transcript(fake_projects, tmp_path, f"recent-{i}", f"Recent {i}", 2, age_seconds=i)
        live = [
            {"pid": 9, "sessionId": "ancient-held", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 10, "sessionId": "bg-b", "cwd": str(tmp_path), "kind": "bg"},
        ]
        self._boot(tmp_path, live, "q")
        assert "Ancient held chat" in capsys.readouterr().err

    def test_no_transcripts_still_offers_continue_last(self, tmp_path, fake_projects):
        """--continue is the fallback, never a dead end."""
        live = [
            {"pid": 1, "sessionId": "bg-a", "cwd": str(tmp_path), "kind": "bg"},
            {"pid": 2, "sessionId": "bg-b", "cwd": str(tmp_path), "kind": "bg"},
        ]
        result, mock_exec = self._boot(tmp_path, live, "")
        assert "--continue" in mock_exec.call_args[0][2]


class TestChatLine:
    """Chat lines as the multi-session menu prints them."""

    _live = [{"pid": 1, "sessionId": "bg-a", "kind": "bg"}, {"pid": 2, "sessionId": "bg-b", "kind": "bg"}]

    def _menu(self, tmp_path, fake_projects, capsys, title, age_seconds):
        make_transcript(fake_projects, tmp_path, "chat-1", title, 3, age_seconds=age_seconds)
        _boot(tmp_path, self._live, "q")
        return next(line for line in capsys.readouterr().err.splitlines() if "[1]" in line)

    def test_untitled_chat_says_so(self, tmp_path, fake_projects, capsys):
        assert "(untitled) · 3 msgs" in self._menu(tmp_path, fake_projects, capsys, "", 0)

    def test_minutes_under_an_hour(self, tmp_path, fake_projects, capsys):
        assert self._menu(tmp_path, fake_projects, capsys, "T", 300).endswith("· 5m ago")

    def test_hours_and_minutes(self, tmp_path, fake_projects, capsys):
        assert self._menu(tmp_path, fake_projects, capsys, "T", 7500).endswith("· 2h05m ago")

    def test_days(self, tmp_path, fake_projects, capsys):
        assert self._menu(tmp_path, fake_projects, capsys, "T", 350000).endswith("· 4d ago")


def _drift_err(tmp_path, capsys):
    """boot() to the no-live menu with the drift probe live; returns stderr."""
    result = _boot(tmp_path, [], "q", quiet=False)
    assert result["action"] == "quit"
    return capsys.readouterr().err


class TestVersionDrift:
    """The auto-updater self-ran from a process that started before
    DISABLE_AUTOUPDATER was set and moved 234 -> 235 under us. Drift is silent
    by nature; this is the line that makes it not."""

    def test_warns_when_running_differs_from_pinned(self, tmp_path, capsys):
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value="2.1.235"),
        ):
            err = _drift_err(tmp_path, capsys)
        assert "running 2.1.235, pinned 2.1.228" in err
        assert "DRIFT" in err.upper()

    def test_names_the_repin_command(self, tmp_path, capsys):
        """A warning that does not say how to fix it gets ignored twice."""
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value="2.1.235"),
        ):
            err = _drift_err(tmp_path, capsys)
        assert "ln -sfn ~/.local/share/claude/versions/2.1.228" in err

    def test_silent_when_versions_match(self, tmp_path, capsys):
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value="2.1.228"),
        ):
            assert "DRIFT" not in _drift_err(tmp_path, capsys)

    def test_no_pin_means_no_opinion(self, tmp_path, capsys):
        """An unpinned repo must not nag — and must not call the binary."""
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value=""),
            patch.object(session_boot, "_running_cli_version") as mock_run,
        ):
            assert "DRIFT" not in _drift_err(tmp_path, capsys)
        mock_run.assert_not_called()

    def test_unreadable_binary_is_silence_not_a_false_alarm(self, tmp_path, capsys):
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value=""),
        ):
            assert "DRIFT" not in _drift_err(tmp_path, capsys)

    def test_running_version_strips_the_trailing_words(self, tmp_path, capsys):
        """`claude --version` answers '2.1.228 (Claude Code)'."""
        completed = MagicMock(stdout="2.1.235 (Claude Code)\n")
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot.subprocess, "run", return_value=completed) as mock_run,
        ):
            err = _drift_err(tmp_path, capsys)
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == [_CLAUDE, "--version"]
        assert "running 2.1.235, pinned 2.1.228" in err

    def test_missing_binary_is_empty_not_an_exception(self, tmp_path, capsys):
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot.subprocess, "run", side_effect=OSError("no such file")),
        ):
            assert "DRIFT" not in _drift_err(tmp_path, capsys)

    def test_pin_lives_in_the_tracked_manifest(self, tmp_path, capsys):
        """The pin must ship with a clone — a personal settings file could not
        be reviewed and would not travel."""
        here = Path(session_boot.__file__).resolve()
        candidates = [p / ".claude" / "provider_manifest.json" for p in here.parents]
        manifest = next(c for c in candidates if c.is_file())
        pinned = json.loads(manifest.read_text(encoding="utf-8"))["cli"]["claude"]["pinned_version"]
        with patch.object(session_boot, "_running_cli_version", return_value="0.0.0-drift"):
            err = _drift_err(tmp_path, capsys)
        assert f"running 0.0.0-drift, pinned {pinned}" in err

    def test_broken_manifest_is_no_pin_not_a_crash(self, tmp_path, monkeypatch, capsys):
        broken = tmp_path / "provider_manifest.json"
        broken.write_text("{ not json", encoding="utf-8")
        monkeypatch.setattr(session_boot, "_find_manifest", lambda: broken)
        with patch.object(session_boot, "_running_cli_version", return_value="9.9.9") as mock_run:
            assert "DRIFT" not in _drift_err(tmp_path, capsys)
        mock_run.assert_not_called()

    def test_boot_warns_before_the_menu(self, tmp_path):
        """The line must land where a human is already looking."""
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_warn_on_version_drift", return_value="2.1.235") as mock_warn,
            patch.object(session_boot, "_read_choice", return_value="q"),
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_warn.assert_called_once_with("/usr/local/bin/claude")
