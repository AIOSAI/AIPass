# =================== AIPass ====================
# Name: test_session_boot_doors.py
# Version: 1.0.1
# Description: Tests for session boot's resume doors: the session pointer and the dispatched-job guard
# Branch: hooks
# Created: 2026-10-08
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/lifecycle/session_boot.py: the session-pointer doors and the dispatch guard."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/lifecycle/session_boot.py parses and imports
# seedgo: no-test-needed(constant) — _RECLAIM_WAIT_S and _RECLAIM_POLL_S defaults; tests patch both to short intervals
# seedgo: no-test-needed(log_level) — logger.info, logger.warning and logger.error prose; that row judges them

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.ai_mail.apps.modules import door_session_pointer as sp
from aipass.hooks.apps.handlers.lifecycle import session_boot
from aipass.hooks.apps.modules import cc_sessions
from aipass.hooks.tests.support_session_boot import (
    _MOD,
    _kept_redirect,
    home_env,
    make_transcript,
    plant_pointer,
    set_home,
)

# conftest's tmux-lookup stub, for every test here.
pytestmark = pytest.mark.usefixtures("_no_real_tmux_lookup")


class TestSessionPointerDoors:
    """FPLAN-0448: every human entry door resumes by the session pointer.

    `-c` REFUSES headless transcripts, so only the pointer can enter a dispatched agent's session.
    Chain, never hard-failing: pointer → today's behaviour → fresh.
    """

    def test_no_live_enter_resumes_the_pointer(self, tmp_path, monkeypatch):
        home = plant_pointer(tmp_path, monkeypatch, "ptr-sid-1")
        with (
            patch.dict("os.environ", home_env(home), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        cmd = mock_exec.call_args[0][2]
        assert "--resume" in cmd and "ptr-sid-1" in cmd
        assert "--continue" not in cmd

    def test_no_live_enter_without_pointer_still_continues(self, tmp_path):
        """No pointer → today's door, unchanged. A branch that predates the
        pointer must still open."""
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        assert "--continue" in mock_exec.call_args[0][2]

    def test_no_live_enter_with_stale_pointer_falls_back(self, tmp_path, monkeypatch):
        """A pointer whose transcript is gone must degrade to --continue —
        `--resume <missing id>` would fail the whole launch."""
        home = plant_pointer(tmp_path, monkeypatch, "ptr-gone")
        tdir = sp.transcript_dir(tmp_path)
        assert tdir is not None, "home redirect did not take: session_pointer cannot resolve a home"
        (tdir / "ptr-gone.jsonl").unlink()
        with (
            patch.dict("os.environ", home_env(home), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        cmd = mock_exec.call_args[0][2]
        assert "--continue" in cmd
        assert "ptr-gone" not in cmd

    def test_fresh_start_mints_and_records_the_seat(self, tmp_path, monkeypatch):
        """'n' mints the session id and writes the pointer BEFORE claude starts
        — a fresh seat the record never learned about is how the resume door
        drifts back to guessing."""
        home = tmp_path / "home"
        set_home(monkeypatch, home)
        with (
            patch.dict("os.environ", home_env(home), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        claude_cmd = mock_exec.call_args[0][1]
        assert "--session-id" in claude_cmd
        minted = claude_cmd[claude_cmd.index("--session-id") + 1]
        pointer = sp.read_pointer(Path(tmp_path))
        assert pointer is not None and pointer["session_id"] == minted
        assert pointer["set_by"] == "session_boot"

    def test_multi_enter_prefers_the_pointer_chat(self, tmp_path, monkeypatch, fake_projects):
        """Enter on the >=2 menu follows the pointer, not newest-by-mtime —
        mtime is the guess the pointer exists to retire."""
        make_transcript(fake_projects, tmp_path, "older-ptr", "Pointer chat", 3, age_seconds=600)
        make_transcript(fake_projects, tmp_path, "newest", "Newest chat", 9)
        home = plant_pointer(tmp_path, monkeypatch, "older-ptr")
        live = [
            {"pid": 1234, "sessionId": "held", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "other", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", home_env(home), clear=True),
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
        assert "--resume" in cmd and "older-ptr" in cmd
        assert "newest" not in cmd

    def test_picker_override_repoints_the_seat(self, tmp_path, monkeypatch, fake_projects):
        """A numbered pick IS the seat now — the pointer must follow it, or the
        next Enter (and the next dispatch) march back to the old session."""
        make_transcript(fake_projects, tmp_path, "chosen", "Chosen chat", 5, age_seconds=600)
        make_transcript(fake_projects, tmp_path, "newest", "Newest chat", 9)
        home = tmp_path / "home"
        set_home(monkeypatch, home)
        live = [
            {"pid": 1234, "sessionId": "held", "cwd": str(tmp_path), "kind": "interactive"},
            {"pid": 5678, "sessionId": "other", "cwd": str(tmp_path), "kind": "bg"},
        ]
        with (
            patch.dict("os.environ", home_env(home), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="2"),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        cmd = mock_exec.call_args[0][2]
        picked = cmd[cmd.index("--resume") + 1]
        pointer = sp.read_pointer(Path(tmp_path))
        assert pointer is not None and pointer["session_id"] == picked
        assert pointer["set_by"] == "session_boot"

    def test_fresh_never_writes_outside_the_boot_cwd(self, tmp_path, monkeypatch):
        """The defect that wrote a REAL pointer into the live hooks branch
        when a menu chain dropped boot's cwd: every chain carries it all the way to the write."""
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        target = tmp_path / "branch"
        target.mkdir()
        monkeypatch.chdir(decoy)
        home = tmp_path / "home"
        set_home(monkeypatch, home)
        live = [{"pid": 1234, "sessionId": "abc", "cwd": str(target), "kind": "interactive"}]
        with (
            patch.dict("os.environ", home_env(home), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=live),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_stop_session", return_value="stopped"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp"),
        ):
            session_boot.boot(cwd=str(target))
        assert sp.read_pointer(target) is not None
        assert not (decoy / ".ai_mail.local").exists()


def plant_dispatch_lock(tmp_path, pid=None):
    """A live dispatch lock, the exact shape ai_mail's wake writes.

    {pid, timestamp, branch} — see wake.py _acquire_lock. pid defaults to
    THIS process so the liveness check passes without patching.
    """
    import json
    import os

    lock = tmp_path / ".ai_mail.local" / ".dispatch.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps(
            {
                "pid": pid if pid is not None else os.getpid(),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "branch": str(tmp_path),
            }
        ),
        encoding="utf-8",
    )
    return lock


class TestDispatchedGuard:
    """FPLAN-0449: while an agent WORKS in the branch, resume steps aside.

    Resume onto a live dispatch is takeover: two claudes on one session id kill the job mid-run.
    Enter waits, 'n' stays safe (new session id), 'r' takes the seat with eyes open, a dead lock gates nothing.
    """

    def test_enter_leaves_the_job_working(self, tmp_path):
        plant_dispatch_lock(tmp_path)
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        assert result["action"] == "left_working"
        mock_exec.assert_not_called()

    def test_the_dispatch_process_is_never_offered_as_a_chat(self, tmp_path):
        """A dispatch claude writes a session file too, so without the guard
        the single-session menu calls the JOB a 'live chat' and Enter walks
        straight into the takeover. The lock check must outrank the live
        menu."""
        import os

        plant_dispatch_lock(tmp_path)
        live = [{"pid": os.getpid(), "sessionId": "job-sid", "cwd": str(tmp_path), "kind": "interactive"}]
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
        assert result["action"] == "left_working"
        mock_exec.assert_not_called()

    def test_fresh_stays_a_door(self, tmp_path, monkeypatch):
        """'n' mints a NEW session id — it steals nothing from the job."""
        plant_dispatch_lock(tmp_path)
        home = tmp_path / "home"
        set_home(monkeypatch, home)
        with (
            patch.dict("os.environ", home_env(home), clear=True),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="n"),
            patch.object(session_boot, "_tmux_session_exists", return_value=False),
            patch(f"{_MOD}.os.execvp") as mock_exec,
        ):
            session_boot.boot(cwd=str(tmp_path))
        claude_cmd = mock_exec.call_args[0][1]
        assert "--session-id" in claude_cmd
        assert "--resume" not in claude_cmd

    def test_dead_lock_gates_nothing_and_stays(self, tmp_path):
        """A lock whose PID is dead means the job is over — the door opens as
        usual. And the probe is READ-ONLY: cleanup belongs to ai_mail's own
        lifecycle, so the file must still be there afterwards."""
        lock = plant_dispatch_lock(tmp_path)
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(cc_sessions, "_is_pid_alive", return_value=False),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value=""),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        assert "--continue" in mock_exec.call_args[0][2]
        assert lock.exists()

    def test_reclaim_stops_the_job_then_resumes_its_chat(self, tmp_path, monkeypatch):
        """'r' is the deliberate takeover: stop the branch's claudes, wait for
        the monitor to surrender the lock, then resume by the pointer — the
        session comes over whole, task state and all."""
        lock = plant_dispatch_lock(tmp_path)
        home = plant_pointer(tmp_path, monkeypatch, "job-sid-9")
        monkeypatch.setattr(session_boot, "_RECLAIM_WAIT_S", 1.0)
        monkeypatch.setattr(session_boot, "_RECLAIM_POLL_S", 0.05)

        def fake_reclaim(branch_filter=None):
            assert branch_filter == str(tmp_path)
            lock.unlink()
            return ["PID 999: sent SIGTERM"]

        with (
            patch.dict("os.environ", home_env(home), clear=True),
            patch.object(cc_sessions, "reclaim", side_effect=fake_reclaim),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="r"),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 0
        cmd = mock_exec.call_args[0][2]
        assert "--resume" in cmd and "job-sid-9" in cmd

    def test_reclaim_refuses_when_the_lock_stays(self, tmp_path, monkeypatch):
        """If the lock never clears, resuming would race the monitor —
        refuse honestly instead."""
        plant_dispatch_lock(tmp_path)
        monkeypatch.setattr(session_boot, "_RECLAIM_WAIT_S", 0.15)
        monkeypatch.setattr(session_boot, "_RECLAIM_POLL_S", 0.05)
        with (
            patch.dict("os.environ", _kept_redirect(), clear=True),
            patch.object(cc_sessions, "reclaim", return_value=[]),
            patch.object(session_boot, "_resolve_claude_binary", return_value="/usr/local/bin/claude"),
            patch.object(session_boot, "_find_tmux", return_value="/usr/bin/tmux"),
            patch.object(session_boot, "_find_live_sessions", return_value=[]),
            patch.object(session_boot, "_read_choice", return_value="r"),
            patch.object(
                session_boot, "_exec_in_tmux", return_value={"exit_code": 0, "action": "started"}
            ) as mock_exec,
        ):
            result = session_boot.boot(cwd=str(tmp_path))
        assert result["exit_code"] == 1
        mock_exec.assert_not_called()
