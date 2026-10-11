# =================== AIPass ====================
# Name: test_session_boot_lookups.py
# Version: 1.0.0
# Description: Tests for session boot's lookups: claude binary, tmux, process tree, labels, home resolution
# Branch: hooks
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/lifecycle/session_boot.py: the lookups the menu stands on."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/lifecycle/session_boot.py parses and imports
# seedgo: no-test-needed(stdlib) — shutil.which and subprocess.run's own process-launch mechanics, stubbed at the edge
# seedgo: no-test-needed(log_level) — logger.info, logger.warning and logger.error prose; that row judges them

import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.ai_mail.apps.modules import door_session_pointer as sp
from aipass.hooks.apps.handlers.lifecycle import session_boot
from aipass.hooks.apps.modules import cc_sessions, cc_transcripts
from aipass.hooks.tests.support_session_boot import (
    _MOD,
    _kept_redirect,
    home_env,
    make_transcript,
    plant_pointer,
    set_home,
)

# conftest's tmux-lookup stub, for every test here (it skips the lookup's own classes).
pytestmark = pytest.mark.usefixtures("_no_real_tmux_lookup")


class TestResolveClaudeBinary:
    def test_found_on_path(self, tmp_path, monkeypatch):
        bin_dir = _on_path(tmp_path, monkeypatch, "claude")
        assert Path(session_boot._resolve_claude_binary()).parent == bin_dir

    def test_not_found_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))
        assert session_boot._resolve_claude_binary() == "claude"


class TestFindTmux:
    def test_found(self, tmp_path, monkeypatch):
        """PATH is a real world under tmp_path holding a tmux, not a patched shutil.which.

        Both a bare `tmux` (POSIX) and `tmux.exe` (Windows, via PATHEXT) are laid down.
        """
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name in ("tmux", "tmux.exe"):
            exe = bin_dir / name
            exe.write_text("", encoding="utf-8")
            exe.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        monkeypatch.setenv("PATHEXT", ".EXE")
        found = session_boot._find_tmux()
        assert found is not None
        assert Path(found).parent == bin_dir
        assert Path(found).stem == "tmux"

    def test_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))
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
        label = session_boot._session_label(session)
        assert "1234" in label
        assert "abcdef12" in label
        assert "interactive" in label


class TestExecInTmux:
    def test_wraps_in_tmux_session(self):
        with (
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot._exec_in_tmux("hooks", "abc12345", ["/usr/local/bin/claude", "--continue"])
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
            session_boot._exec_in_tmux("hooks", "", ["/usr/local/bin/claude"])
        kill_calls = [c for c in mock_run.call_args_list if "kill-session" in str(c)]
        assert len(kill_calls) == 1


class TestIsSessionFilePresent:
    def test_present(self, tmp_path, monkeypatch):
        """Home is a real world under tmp_path (env redirect), not a patched Path.home."""
        sessions_dir = tmp_path / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "1234.json").write_text("{}", encoding="utf-8")
        set_home(monkeypatch, tmp_path)
        assert session_boot._is_session_file_present(1234) is True

    def test_absent(self, tmp_path, monkeypatch):
        set_home(monkeypatch, tmp_path)
        assert session_boot._is_session_file_present(1234) is False

    def test_none_pid(self):
        assert session_boot._is_session_file_present(None) is False


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

    def test_kill_session_answers_false_when_tmux_is_absent(self):
        """check=False ignores an exit code; a missing binary never reaches one.

        seedgo host_portability arm B, FPLAN-0554: the three kill-session calls
        ran tmux with no probe and no handler, so FileNotFoundError came out of
        exec and took the caller with it.
        """
        with patch.object(session_boot.subprocess, "run", side_effect=FileNotFoundError(2, "No such file")):
            assert session_boot._tmux_kill_session("hooks") is False

    def test_kill_session_answers_true_when_the_kill_was_delivered(self):
        with patch.object(session_boot.subprocess, "run", return_value=MagicMock(returncode=0)) as mock_run:
            assert session_boot._tmux_kill_session("hooks") is True
        assert "kill-session" in str(mock_run.call_args)

    def test_a_hung_tmux_does_not_hang_the_kill(self):
        with patch.object(
            session_boot.subprocess, "run", side_effect=session_boot.subprocess.TimeoutExpired("tmux", 5)
        ):
            assert session_boot._tmux_kill_session("hooks") is False

    def test_stop_session_falls_back_to_sigterm_when_tmux_cannot_kill(self):
        """The old line claimed "killed tmux session" for a kill it never made."""
        with (
            patch.object(session_boot, "_find_tmux_session_for_pid", return_value="hooks"),
            patch.object(session_boot.subprocess, "run", side_effect=FileNotFoundError(2, "No such file")),
            patch.object(session_boot.os, "kill") as mock_kill,
        ):
            result = session_boot._stop_session({"pid": 4242, "kind": "interactive"}, "/usr/local/bin/claude")
        assert "SIGTERM" in result
        assert "killed tmux session" not in result
        mock_kill.assert_called_once_with(4242, signal.SIGTERM)

    def test_exec_in_tmux_still_launches_when_the_stale_kill_cannot_run(self):
        with (
            patch.object(session_boot, "_tmux_session_exists", return_value=True),
            patch.object(session_boot.subprocess, "run", side_effect=FileNotFoundError(2, "No such file")),
            patch.object(session_boot.os, "execvp") as mock_exec,
        ):
            result = session_boot._exec_in_tmux("hooks", "", ["/usr/local/bin/claude"])
        assert result["action"] == "started"
        mock_exec.assert_called_once()

    def test_start_fresh_still_launches_when_the_stale_kill_cannot_run(self, tmp_path):
        pointer = MagicMock()
        pointer.mint_session_id.return_value = "sid-1"
        with (
            patch.object(session_boot, "_tmux_session_exists", return_value=True),
            patch.object(session_boot, "_session_pointer", return_value=pointer),
            patch.object(session_boot.subprocess, "run", side_effect=FileNotFoundError(2, "No such file")),
            patch.object(session_boot.os, "execvp") as mock_exec,
        ):
            result = session_boot._start_fresh("hooks", "/usr/local/bin/claude", [], None, cwd=str(tmp_path))
        assert result["action"] == "started"
        mock_exec.assert_called_once()

    def test_the_menu_still_renders_without_tmux(self, tmp_path, fake_projects, capsys):
        """The failure that mattered: the whole menu, not one label."""
        make_transcript(fake_projects, tmp_path, "chat-1", "A chat", 4)
        live = [
            {"pid": 1, "sessionId": "s1", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 2, "sessionId": "s2", "cwd": str(tmp_path), "kind": "interactive"},
        ]
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
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


class TestHomeResolutionIsPortable:
    """PR 739 / windows-setup: home resolution must not be POSIX-only.

    Four pointer-door tests died on the Windows runner with
    RuntimeError("Could not determine home directory."), while their siblings
    passed — the split was not in the pointer logic at all. Every failing test
    planted a pointer and then ran boot() under
    `patch.dict(..., {"HOME": ...}, clear=True)`; every passing one returned
    before the first home lookup. Clearing the environ strips %USERPROFILE%,
    and Windows expanduser reads that, not $HOME.

    These pin both halves of the fix so the platform gap cannot come back
    quietly on a machine where nobody can run the failing platform.
    """

    def test_home_env_sets_both_platform_keys(self, tmp_path):
        """HOME alone is a Linux-only redirect. The Windows key must ride too."""
        env = home_env(tmp_path / "home")
        assert env["HOME"] == str(tmp_path / "home")
        assert env["USERPROFILE"] == str(tmp_path / "home")

    def test_set_home_redirects_home_with_the_environ_cleared(self, tmp_path, monkeypatch):
        """The whole point: resolution must survive a cleared environ, which is
        what every one of the four failing tests did to itself."""
        home = tmp_path / "home"
        set_home(monkeypatch, home)
        with patch.dict("os.environ", home_env(home), clear=True):
            assert Path.home() == home

    def test_pointer_doors_resolve_under_a_cleared_environ(self, tmp_path, monkeypatch):
        """The CI failure itself, reduced: plant a pointer, clear the environ to
        exactly what the fixture provides, and resolve. This is the call that
        raised on the runner (session_pointer.transcript_dir -> Path.home())."""
        home = plant_pointer(tmp_path, monkeypatch, "portable-sid")
        with patch.dict("os.environ", home_env(home), clear=True):
            sid, reason = sp.resolve_resume_target(Path(tmp_path))
        assert sid == "portable-sid", reason

    def test_claude_home_degrades_instead_of_raising(self):
        """An unresolvable home must not crash at import. The constants are
        module-level, so `Path.home()` raising there kills the whole module
        rather than the one lookup that wanted a path."""
        for mod in (cc_sessions, cc_transcripts):
            with patch.object(Path, "home", side_effect=RuntimeError("Could not determine home directory.")):
                fallback = mod._claude_home()
            assert not (fallback / ".claude").exists()

    def test_session_file_presence_survives_an_unresolvable_home(self, monkeypatch):
        """A presence check answers True or False — never takes the menu down."""
        monkeypatch.setattr(cc_sessions, "CC_SESSIONS_DIR", Path("<no-home>") / ".claude" / "sessions")
        assert session_boot._is_session_file_present(4321) is False


def _on_path(tmp_path: Path, monkeypatch, name: str) -> Path:
    """PATH set to a directory under tmp_path holding name, so the product's own shutil.which answers for real.

    Both a bare name (POSIX, mode bit set) and name.exe (Windows, found through PATHEXT) are laid down; the platform
    picks its own. The stubs are empty and never run. Returns the directory.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for spelling in (name, f"{name}.exe"):
        stub = bin_dir / spelling
        stub.write_text("", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PATHEXT", ".EXE")
    return bin_dir
