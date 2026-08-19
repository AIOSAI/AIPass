"""Tests for session boot wrapper (menu-based attach/start/close)."""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.hooks.apps.handlers.lifecycle import session_boot
from aipass.hooks.apps.modules import cc_transcripts

_MOD = "aipass.hooks.apps.handlers.lifecycle.session_boot"

# Classes that test the tmux lookups themselves — they must see the real thing.
_TMUX_OWN_TESTS = {
    "TestFindTmux",
    "TestTmuxSessionExists",
    "TestFindTmuxSessionForPid",
    "TestTmuxLookupsSurviveAMachineWithoutTmux",
}


@pytest.fixture(autouse=True)
def _no_real_tmux_lookup(request):
    """Keep the MENU tests off a real subprocess.

    Rendering the multi-session menu describes each live process, which asks
    tmux where that process lives. That is a real `tmux list-panes` call: it
    raises WinError 2 on the Windows runner (6 CI failures, 2026-08-18) and is
    slow everywhere else. Whether [Enter] continues the last chat is not a
    platform question, so the lookup is stubbed for every test except the ones
    whose subject IS the lookup.
    """
    if request.cls is not None and request.cls.__name__ in _TMUX_OWN_TESTS:
        yield
        return
    with patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None):
        yield


class TestResolveClaudeBinary:
    def test_found_on_path(self):
        with patch(f"{_MOD}.shutil.which", return_value="/usr/local/bin/claude"):
            assert session_boot._resolve_claude_binary() == "/usr/local/bin/claude"

    def test_not_found_fallback(self):
        with patch(f"{_MOD}.shutil.which", return_value=None):
            assert session_boot._resolve_claude_binary() == "claude"


class TestFindTmux:
    def test_found(self):
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            assert session_boot._find_tmux() == "/usr/bin/tmux"

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            assert session_boot._find_tmux() is None


class TestTmuxSessionExists:
    def test_exists(self):
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert session_boot._tmux_session_exists("hooks") is True

    def test_not_exists(self):
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert session_boot._tmux_session_exists("hooks") is False


class TestFindTmuxSessionForPid:
    def test_finds_session(self):
        output = "1234 hooks\n5678 devpulse\n"
        with (
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0, stdout=output)),
            patch.object(session_boot, "_is_descendant", side_effect=lambda t, a: t == 9999 and a == 1234),
        ):
            assert session_boot._find_tmux_session_for_pid(9999) == "hooks"

    def test_not_found(self):
        output = "1234 hooks\n"
        with (
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0, stdout=output)),
            patch.object(session_boot, "_is_descendant", return_value=False),
        ):
            assert session_boot._find_tmux_session_for_pid(9999) is None

    def test_tmux_not_running(self):
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert session_boot._find_tmux_session_for_pid(9999) is None


class TestGetPpid:
    def test_returns_parent_pid(self):
        mock_result = MagicMock(returncode=0, stdout="  1234\n")
        with patch(f"{_MOD}.subprocess.run", return_value=mock_result):
            assert session_boot._get_ppid(5678) == 1234

    def test_returns_none_on_failure(self):
        mock_result = MagicMock(returncode=1, stdout="")
        with patch(f"{_MOD}.subprocess.run", return_value=mock_result):
            assert session_boot._get_ppid(5678) is None

    def test_returns_none_on_oserror(self):
        with patch(f"{_MOD}.subprocess.run", side_effect=OSError("no ps")):
            assert session_boot._get_ppid(5678) is None

    def test_returns_none_on_timeout(self):
        import subprocess

        with patch(f"{_MOD}.subprocess.run", side_effect=subprocess.TimeoutExpired("ps", 5)):
            assert session_boot._get_ppid(5678) is None


class TestIsDescendant:
    def test_direct_match(self):
        assert session_boot._is_descendant(100, 100) is True

    def test_pid_one_not_descendant(self):
        assert session_boot._is_descendant(1, 999) is False

    def test_walks_via_ps(self):
        def mock_ppid(pid):
            return {200: 150, 150: 100}.get(pid)

        with patch.object(session_boot, "_get_ppid", side_effect=mock_ppid):
            assert session_boot._is_descendant(200, 100) is True

    def test_not_descendant(self):
        def mock_ppid(pid):
            return {200: 150, 150: 1}.get(pid)

        with patch.object(session_boot, "_get_ppid", side_effect=mock_ppid):
            assert session_boot._is_descendant(200, 100) is False

    def test_ppid_none_stops_walk(self):
        with patch.object(session_boot, "_get_ppid", return_value=None):
            assert session_boot._is_descendant(200, 100) is False


class TestMakeSessionName:
    def test_with_session_id(self):
        assert session_boot._make_session_name("hooks", "abcdef1234") == "hooks-abcdef12"

    def test_without_session_id(self):
        assert session_boot._make_session_name("hooks") == "hooks"

    def test_empty_session_id(self):
        assert session_boot._make_session_name("hooks", "") == "hooks"


class TestNameFlag:
    def test_branch_only(self):
        result = session_boot._name_flag("hooks")
        assert result == ["--name", "hooks"]

    def test_branch_with_session_id(self):
        result = session_boot._name_flag("hooks", "abcdef1234")
        assert result == ["--name", "hooks-abcdef12"]

    def test_skips_when_user_provides_name(self):
        result = session_boot._name_flag("hooks", "", ["--name", "myname"])
        assert result == []

    def test_skips_when_user_provides_n(self):
        result = session_boot._name_flag("hooks", "", ["-n", "myname"])
        assert result == []

    def test_adds_when_extra_args_no_name(self):
        result = session_boot._name_flag("hooks", "", ["--verbose"])
        assert result == ["--name", "hooks"]


class TestSessionLabel:
    def test_formats_label(self):
        session = {"pid": 1234, "sessionId": "abcdef1234", "kind": "interactive"}
        label = session_boot._session_label(session, "hooks")
        assert "1234" in label
        assert "abcdef12" in label
        assert "interactive" in label


class TestBoot:
    def test_already_in_tmux_execs_directly(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "/usr/local/bin/claude"
        assert "--permission-mode" in args[1]
        assert "bypassPermissions" in args[1]

    def test_already_in_tmux_passes_extra_args(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--resume"])
        args = mock_exec.call_args[0][1]
        assert "--resume" in args

    def test_no_tmux_errors(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value=None),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 1
        assert "tmux not found" in result["error"]

    def test_live_session_resume_via_tmux(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value="hooks"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_exec.assert_called_once_with("tmux", ["tmux", "attach-session", "-t", "hooks"])

    def test_live_session_resume_continues_dead_window(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0][1]
        assert "--continue" in args

    def test_live_session_resume_bg_does_takeover(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", {}, clear=True),
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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_stop_session") as mock_stop,
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp"),
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_stop.assert_called_once()

    def test_live_session_close_stops_and_exits(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", {}, clear=True),
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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0][1]
        assert "--continue" in args

    def test_no_live_new_starts_fresh(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0]
        assert args[0] == "tmux"
        assert "new-session" in args[1]
        assert "/usr/local/bin/claude" in args[1]

    def test_stale_tmux_session_killed_on_fresh_start(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=True),
            patch(f"{_MOD}.subprocess.run") as mock_run,
            patch(f"{_MOD}.os.execvp"),
        ):
            session_boot.boot(cwd=str(tmp_path))
        kill_calls = [c for c in mock_run.call_args_list if "kill-session" in str(c)]
        assert len(kill_calls) == 1

    def test_extra_args_passed_on_fresh_start(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
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
        with patch(f"{_MOD}.os.kill") as mock_kill:
            session_boot._stop_session(session, "/usr/local/bin/claude")
        mock_kill.assert_not_called()

    def test_tmux_session_killed(self):
        session = {"pid": 1234, "kind": "interactive"}
        with (
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value="hooks"),
            patch(f"{_MOD}.subprocess.run") as mock_run,
        ):
            result = session_boot._stop_session(session, "/usr/local/bin/claude")
        kill_calls = [c for c in mock_run.call_args_list if "kill-session" in str(c)]
        assert len(kill_calls) == 1
        assert "tmux" in result

    def test_plain_session_sigterm(self):
        session = {"pid": 1234, "kind": "interactive"}
        with (
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch(f"{_MOD}.os.kill") as mock_kill,
        ):
            result = session_boot._stop_session(session, "/usr/local/bin/claude")
        mock_kill.assert_called_once()
        assert "SIGTERM" in result

    def test_plain_session_already_dead(self):
        session = {"pid": 1234, "kind": "interactive"}
        with (
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch(f"{_MOD}.os.kill", side_effect=ProcessLookupError),
        ):
            result = session_boot._stop_session(session, "/usr/local/bin/claude")
        assert "already dead" in result


class TestMain:
    def test_success(self):
        with patch.object(session_boot, "boot", return_value={"exit_code": 0, "action": "started"}):
            session_boot.main()

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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "do something"])
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0][1]
        assert args[0] == "/usr/local/bin/claude"
        assert "-p" in args
        assert "do something" in args

    def test_p_flag_does_not_look_for_live_sessions(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_live_sessions") as mock_live,
            patch(f"{_MOD}.os.execvp"),
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query"])
        mock_live.assert_not_called()

    def test_p_flag_does_not_require_tmux(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value=None),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query"])
        assert result["action"] == "direct"
        assert result["reason"] == "headless -p mode"
        mock_exec.assert_called_once()

    def test_p_flag_still_gets_permission_mode_default(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query"])
        cmd = mock_exec.call_args[0][1]
        assert "--permission-mode" in cmd
        assert "bypassPermissions" in cmd

    def test_p_flag_respects_custom_permission_mode(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["-p", "query", "--permission-mode", "default"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "default" in cmd


class TestPermissionModeDedupe:
    def test_no_extra_args_includes_default(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,1,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "bypassPermissions" in cmd

    def test_extra_args_with_permission_mode_no_double(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,1,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "default"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "default" in cmd
        assert "bypassPermissions" not in cmd

    def test_extra_args_without_permission_mode_gets_default(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,1,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--resume"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "bypassPermissions" in cmd
        assert "--resume" in cmd

    def test_fresh_start_dedupes_too(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "acceptEdits"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--permission-mode") == 1
        assert "acceptEdits" in cmd


def make_transcript(projects_root, cwd, session_id, title, messages, age_seconds=0):
    """Write a CC-shaped transcript so the picker has a real chat to find."""
    import json as _json
    import os as _os
    import re as _re

    directory = projects_root / _re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    lines = [_json.dumps({"type": "ai-title", "aiTitle": title, "sessionId": session_id})]
    for i in range(messages):
        lines.append(_json.dumps({"type": "user", "message": {"content": f"turn {i}"}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if age_seconds:
        stamp = path.stat().st_mtime - age_seconds
        _os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def fake_projects(tmp_path, monkeypatch):
    """Point the transcript reader at a throwaway projects root."""
    root = tmp_path / "projects_root"
    root.mkdir()
    monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", root)
    return root


class TestMultipleLiveSessions:
    def test_close_all(self, tmp_path):
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", {}, clear=True),
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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="1"),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value="hooks"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
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
            patch.dict("os.environ", {}, clear=True),
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
            patch.dict("os.environ", {}, clear=True),
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
        cmd = mock_exec.call_args[0][3]
        assert "--resume" in cmd and "newest" in cmd

    def test_n_stops_stoppable_then_starts(self, tmp_path):
        live = [
            {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "def", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_stop_session", return_value="stopped") as mock_stop,
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_stop.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "tmux"
        assert "new-session" in args[1]


class TestTakeover:
    def test_takeover_bg_runs_daemon_stop(self, tmp_path):
        session = {
            "pid": 1234,
            "sessionId": "abc12345-full-uuid",
            "cwd": str(tmp_path),
            "kind": "bg",
        }
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}) as mock_daemon,
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._takeover_bg(
                session, "hooks", "/usr/local/bin/claude", ["--permission-mode", "bypassPermissions"]
            )
        mock_daemon.assert_called_once()
        args = mock_exec.call_args[0][1]
        assert "--resume" in args
        assert "abc12345-full-uuid" in args
        assert "new-session" in args

    def test_takeover_bg_no_session_id_continues(self, tmp_path):
        session = {"pid": 1234, "sessionId": "", "cwd": str(tmp_path), "kind": "bg"}
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._takeover_bg(
                session, "hooks", "/usr/local/bin/claude", ["--permission-mode", "bypassPermissions"]
            )
        args = mock_exec.call_args[0][1]
        assert "--continue" in args

    def test_takeover_daemon_stop_failure(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}
        with patch.object(
            session_boot, "_daemon_stop", return_value={"ok": False, "error": "daemon stop failed: no claude"}
        ):
            result = session_boot._takeover_bg(session, "hooks", "/usr/local/bin/claude", [])
        assert result["exit_code"] == 1
        assert "daemon stop failed" in result["error"]

    def test_takeover_nonzero_returncode_aborts(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}
        with patch.object(
            session_boot,
            "_daemon_stop",
            return_value={"ok": False, "error": "daemon stop exit 1: something failed"},
        ):
            result = session_boot._takeover_bg(session, "hooks", "/usr/local/bin/claude", [])
        assert result["exit_code"] == 1

    def test_single_bg_enter_is_takeover(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", {}, clear=True),
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

    def test_single_bg_n_stops_then_fresh(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        args = mock_exec.call_args[0]
        assert args[0] == "tmux"
        assert "new-session" in args[1]

    def test_single_bg_c_stops(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", {}, clear=True),
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
        session = {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}
        with patch.object(
            session_boot, "_takeover_bg", return_value={"exit_code": 0, "action": "takeover"}
        ) as mock_take:
            result = session_boot._resume_session(
                session, "hooks", "/usr/local/bin/claude", ["--permission-mode", "bypassPermissions"]
            )
        mock_take.assert_called_once()
        assert result["action"] == "takeover"

    def test_bg_resume_never_opens_agents_view(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._resume_session(
                session, "hooks", "/usr/local/bin/claude", ["--permission-mode", "bypassPermissions"]
            )
        args = mock_exec.call_args[0][1]
        assert "agents" not in args


class TestSessionLabelAutoName:
    def test_bg_label_includes_auto_name(self):
        session = {
            "pid": 1234,
            "sessionId": "abc12345",
            "kind": "bg",
            "name": "chroma review",
        }
        label = session_boot._session_label(session, "hooks")
        assert '"chroma review"' in label
        assert "abc12345" in label

    def test_interactive_label_no_name(self):
        session = {"pid": 1234, "sessionId": "abc12345", "kind": "interactive"}
        label = session_boot._session_label(session, "hooks")
        assert '"' not in label

    def test_bg_label_no_name_field(self):
        session = {"pid": 1234, "sessionId": "abc12345", "kind": "bg"}
        label = session_boot._session_label(session, "hooks")
        assert '"' not in label


class TestDaemonStop:
    def test_success_no_collateral(self):
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)),
            patch.object(session_boot, "_is_session_file_present", return_value=False),
        ):
            result = session_boot._daemon_stop("/usr/local/bin/claude", "hooks", 1234)
        assert result["ok"] is True

    def test_nonzero_returncode_fails(self):
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(
                f"{_MOD}.subprocess.run",
                return_value=MagicMock(returncode=1, stderr="something broke"),
            ),
        ):
            result = session_boot._daemon_stop("/usr/local/bin/claude", "hooks", 1234)
        assert result["ok"] is False
        assert "exit 1" in result["error"]

    def test_oserror_fails(self):
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=[]),
            patch(f"{_MOD}.subprocess.run", side_effect=OSError("no binary")),
        ):
            result = session_boot._daemon_stop("/usr/local/bin/claude", "hooks", 1234)
        assert result["ok"] is False

    def test_collateral_confirmed_proceeds(self):
        collateral = [{"pid": 9999, "cwd": "/tmp/other", "sessionId": "xyz"}]
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=collateral),
            patch.object(session_boot, "_read_choice", return_value="y"),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)),
            patch.object(session_boot, "_is_session_file_present", return_value=False),
        ):
            result = session_boot._daemon_stop("/usr/local/bin/claude", "hooks", 1234)
        assert result["ok"] is True

    def test_collateral_denied_cancels(self):
        collateral = [{"pid": 9999, "cwd": "/tmp/other", "sessionId": "xyz"}]
        with (
            patch.object(session_boot, "_get_collateral_bg", return_value=collateral),
            patch.object(session_boot, "_read_choice", return_value="n"),
        ):
            result = session_boot._daemon_stop("/usr/local/bin/claude", "hooks", 1234)
        assert result["ok"] is False
        assert "cancelled" in result["error"]


class TestExecInTmux:
    def test_wraps_in_tmux_session(self):
        with (
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._exec_in_tmux(
                "hooks", "abc12345", "/usr/local/bin/claude", ["/usr/local/bin/claude", "--continue"]
            )
        args = mock_exec.call_args[0]
        assert args[0] == "tmux"
        assert "new-session" in args[1]
        assert "-s" in args[1]
        assert "hooks-abc12345" in args[1]
        assert "/usr/local/bin/claude" in args[1]

    def test_kills_stale_tmux_first(self):
        with (
            patch.object(session_boot, "_tmux_session_exists", return_value=True),
            patch(f"{_MOD}.subprocess.run") as mock_run,
            patch(f"{_MOD}.os.execvp"),
        ):
            session_boot._exec_in_tmux("hooks", "", "/usr/local/bin/claude", ["/usr/local/bin/claude"])
        kill_calls = [c for c in mock_run.call_args_list if "kill-session" in str(c)]
        assert len(kill_calls) == 1


class TestIsSessionFilePresent:
    def test_present(self, tmp_path):
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "1234.json").write_text("{}")
        with patch.object(session_boot.Path, "home", return_value=tmp_path):
            assert session_boot._is_session_file_present(1234) is True

    def test_absent(self, tmp_path):
        with patch.object(session_boot.Path, "home", return_value=tmp_path):
            assert session_boot._is_session_file_present(1234) is False

    def test_none_pid(self):
        assert session_boot._is_session_file_present(None) is False


class TestExtraArgsThreading:
    """R6: extra_args must reach every launch path, not just _start_fresh."""

    def test_resume_dead_window_threads_extra_args(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}
        with (
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._resume_session(session, "hooks", "/usr/local/bin/claude", [], ["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--continue" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_takeover_bg_threads_extra_args(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc-uuid", "cwd": str(tmp_path), "kind": "bg"}
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._takeover_bg(session, "hooks", "/usr/local/bin/claude", [], ["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--resume" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_takeover_bg_continue_threads_extra_args(self, tmp_path):
        session = {"pid": 1234, "sessionId": "", "cwd": str(tmp_path), "kind": "bg"}
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._takeover_bg(session, "hooks", "/usr/local/bin/claude", [], ["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--continue" in cmd
        assert "--permission-mode" in cmd

    def test_no_live_continue_threads_extra_args(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--permission-mode", "plan"])
        cmd = mock_exec.call_args[0][1]
        assert "--continue" in cmd
        assert "--permission-mode" in cmd
        assert "plan" in cmd

    def test_live_bg_enter_threads_extra_args(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "bg"}]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="1"),
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_stop_session", return_value="stopped"),
            patch.object(session_boot, "_daemon_stop", return_value={"ok": False, "error": "failed"}),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 1
        assert "one-brain" in result["error"]
        mock_exec.assert_not_called()


class TestMenuQuit:
    def test_single_session_q_quits(self, tmp_path):
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path), "kind": "interactive"}]
        with (
            patch.dict("os.environ", {}, clear=True),
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
            patch.dict("os.environ", {}, clear=True),
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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="quit"),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["action"] == "quit"

    def test_no_live_q_quits(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
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
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd
        branch = tmp_path.name
        idx = cmd.index("--name")
        assert cmd[idx + 1] == branch

    def test_takeover_gets_name_with_session_id(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc12345-full-uuid", "cwd": str(tmp_path), "kind": "bg"}
        with (
            patch.object(session_boot, "_daemon_stop", return_value={"ok": True}),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._takeover_bg(session, "hooks", "/usr/local/bin/claude", [])
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "hooks-abc12345"

    def test_in_tmux_gets_name(self, tmp_path):
        with (
            patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd

    def test_no_live_continue_gets_name(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd

    def test_user_name_not_overridden(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path), extra_args=["--name", "myname"])
        cmd = mock_exec.call_args[0][1]
        assert cmd.count("--name") == 1
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "myname"

    def test_dead_window_resume_gets_name_with_session_id(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc12345-uuid", "cwd": str(tmp_path), "kind": "interactive"}
        with (
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._resume_session(session, "hooks", "/usr/local/bin/claude", [])
        cmd = mock_exec.call_args[0][1]
        assert "--name" in cmd
        idx = cmd.index("--name")
        assert cmd[idx + 1] == "hooks-abc12345"


class TestPickerOffersChatsNotProcesses:
    """The 2026-08-18 loss: Ctrl+C removes the dead chat's session file, so the
    conversation Patrick wanted was the one thing a PID list could not show —
    while three bg leftovers were offered as if they were his chats."""

    def _boot(self, tmp_path, live, choice, projects_root=None):
        with (
            patch.dict("os.environ", {}, clear=True),
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
        cmd = mock_exec.call_args[0][3]
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
        cmd = mock_exec.call_args[0][3]
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
        for i in range(session_boot._CHAT_LIMIT):
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
        assert "--continue" in mock_exec.call_args[0][3]


class TestChatLine:
    def test_untitled_chat_says_so(self):
        assert "(untitled)" in session_boot._chat_line({"title": "", "messages": 3, "modified": 0})

    def test_minutes_under_an_hour(self):
        assert session_boot._chat_age(time.time() - 300) == "5m ago"

    def test_hours_and_minutes(self):
        assert session_boot._chat_age(time.time() - 7500).startswith("2h")

    def test_days(self):
        assert session_boot._chat_age(time.time() - 200000) == "2d ago"


class TestVersionDrift:
    """The auto-updater self-ran from a process that started before
    DISABLE_AUTOUPDATER was set and moved 234 -> 235 under us. Drift is silent
    by nature; this is the line that makes it not."""

    def test_warns_when_running_differs_from_pinned(self, capsys):
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value="2.1.235"),
        ):
            got = session_boot._warn_on_version_drift("/usr/local/bin/claude")
        err = capsys.readouterr().err
        assert got == "2.1.235"
        assert "2.1.228" in err and "2.1.235" in err
        assert "DRIFT" in err.upper()

    def test_names_the_repin_command(self, capsys):
        """A warning that does not say how to fix it gets ignored twice."""
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value="2.1.235"),
        ):
            session_boot._warn_on_version_drift("/usr/local/bin/claude")
        assert "ln -sfn" in capsys.readouterr().err

    def test_silent_when_versions_match(self, capsys):
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value="2.1.228"),
        ):
            assert session_boot._warn_on_version_drift("/usr/local/bin/claude") == ""
        assert capsys.readouterr().err == ""

    def test_no_pin_means_no_opinion(self, capsys):
        """An unpinned repo must not nag — and must not call the binary."""
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value=""),
            patch.object(session_boot, "_running_cli_version") as mock_run,
        ):
            assert session_boot._warn_on_version_drift("/usr/local/bin/claude") == ""
        mock_run.assert_not_called()
        assert capsys.readouterr().err == ""

    def test_unreadable_binary_is_silence_not_a_false_alarm(self, capsys):
        with (
            patch.object(session_boot, "_pinned_cli_version", return_value="2.1.228"),
            patch.object(session_boot, "_running_cli_version", return_value=""),
        ):
            assert session_boot._warn_on_version_drift("/usr/local/bin/claude") == ""
        assert capsys.readouterr().err == ""

    def test_running_version_strips_the_trailing_words(self):
        """`claude --version` answers '2.1.228 (Claude Code)'."""
        completed = MagicMock(stdout="2.1.228 (Claude Code)\n")
        with patch.object(session_boot.subprocess, "run", return_value=completed):
            assert session_boot._running_cli_version("/usr/local/bin/claude") == "2.1.228"

    def test_missing_binary_is_empty_not_an_exception(self):
        with patch.object(session_boot.subprocess, "run", side_effect=OSError("no such file")):
            assert session_boot._running_cli_version("/nope/claude") == ""

    def test_pin_lives_in_the_tracked_manifest(self):
        """The pin must ship with a clone — a personal settings file could not
        be reviewed and would not travel."""
        manifest = session_boot._find_manifest()
        assert manifest is not None, "provider_manifest.json not found from this file"
        assert manifest.parts[-2:] == (".claude", "provider_manifest.json")
        assert session_boot._pinned_cli_version() != ""

    def test_broken_manifest_is_no_pin_not_a_crash(self, tmp_path, monkeypatch):
        broken = tmp_path / "provider_manifest.json"
        broken.write_text("{ not json", encoding="utf-8")
        monkeypatch.setattr(session_boot, "_find_manifest", lambda: broken)
        assert session_boot._pinned_cli_version() == ""

    def test_boot_warns_before_the_menu(self, tmp_path):
        """The line must land where a human is already looking."""
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_warn_on_version_drift", return_value="2.1.235") as mock_warn,
            patch.object(session_boot, "_read_choice", return_value="q"),
        ):
            session_boot.boot(cwd=str(tmp_path))
        mock_warn.assert_called_once()


class TestTmuxLookupsSurviveAMachineWithoutTmux:
    """A missing tmux is a fact about the world, not a crash. _describe_process
    put _find_tmux_session_for_pid on the menu render path, so an unguarded
    call took the whole menu down on every host without tmux."""

    def test_find_session_for_pid_answers_none_when_tmux_is_absent(self):
        with patch.object(session_boot.subprocess, "run", side_effect=FileNotFoundError(2, "No such file")):
            assert session_boot._find_tmux_session_for_pid(1234) is None

    def test_session_exists_answers_false_when_tmux_is_absent(self):
        with patch.object(session_boot.subprocess, "run", side_effect=FileNotFoundError(2, "No such file")):
            assert session_boot._tmux_session_exists("hooks") is False

    def test_a_hung_tmux_does_not_hang_the_menu(self):
        with patch.object(
            session_boot.subprocess, "run", side_effect=session_boot.subprocess.TimeoutExpired("tmux", 5)
        ):
            assert session_boot._find_tmux_session_for_pid(1234) is None
            assert session_boot._tmux_session_exists("hooks") is False

    def test_the_menu_still_renders_without_tmux(self, tmp_path, fake_projects, capsys):
        """The failure that mattered: the whole menu, not one label."""
        make_transcript(fake_projects, tmp_path, "chat-1", "A chat", 4)
        live = [
            {"pid": 1, "sessionId": "s1", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 2, "sessionId": "s2", "cwd": str(tmp_path), "kind": "interactive"},
        ]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            # tmux resolves (boot requires it) but every tmux CALL fails —
            # the shape of a host where the binary is stale or sandboxed away.
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_warn_on_version_drift", return_value=""),
            patch.object(session_boot.subprocess, "run", side_effect=FileNotFoundError(2, "No such file")),
            patch.object(session_boot, "_read_choice", return_value="q"),
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        out = capsys.readouterr().err
        assert result["action"] == "quit"
        assert "A chat" in out
        assert "no tmux" in out
