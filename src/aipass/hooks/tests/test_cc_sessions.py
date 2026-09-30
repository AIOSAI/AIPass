# =================== AIPass ====================
# Name: test_cc_sessions.py
# Version: 1.0.1
# Description: Tests for the CC-native session file reader
# Branch: hooks
# Created: 2026-07-01
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/cc_sessions.py, the CC-native session file reader."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — HELP_COMMANDS' help rows
# seedgo: no-test-needed(stdlib) — os.getpid and os.kill, patched at the edge wherever a live pid is needed

import json
import os
import sys
from unittest.mock import patch

import pytest

from aipass.hooks.apps.modules import cc_sessions


class TestResolveSessionPid:
    """The ppid walk that answers "which PID is my seat" (moved from presence.py)."""

    def test_finds_session_file_ancestor(self):
        ppid_map = {100: 90, 90: 80}
        with (
            patch("os.getpid", return_value=100),
            patch.object(cc_sessions, "_has_session_file", side_effect=lambda p: p == 80),
            patch.object(cc_sessions, "_get_ppid_portable", side_effect=lambda p: ppid_map.get(p)),
        ):
            assert cc_sessions.resolve_session_pid() == 80

    def test_no_session_file_ancestor_returns_none(self):
        ppid_map = {100: 90, 90: 80, 80: 1}
        with (
            patch("os.getpid", return_value=100),
            patch.object(cc_sessions, "_has_session_file", return_value=False),
            patch.object(cc_sessions, "_get_ppid_portable", side_effect=lambda p: ppid_map.get(p)),
        ):
            assert cc_sessions.resolve_session_pid() is None

    def test_ppid_failure_returns_none(self):
        with (
            patch("os.getpid", return_value=100),
            patch.object(cc_sessions, "_has_session_file", return_value=False),
            patch.object(cc_sessions, "_get_ppid_portable", return_value=None),
        ):
            assert cc_sessions.resolve_session_pid() is None

    def test_direct_session_process(self):
        with (
            patch("os.getpid", return_value=100),
            patch.object(cc_sessions, "_has_session_file", side_effect=lambda p: p == 100),
        ):
            assert cc_sessions.resolve_session_pid() == 100


class TestHasSessionFile:
    """Reads through CC_SESSIONS_DIR, so an unresolvable home answers instead of raising.

    Read through resolve_session_pid (fleet_green leg 4): our own pid is the
    walk's first step, and the ppid step answers None so no `ps` is started.
    Proof: a mutant of the file check.
    """

    def test_true_when_the_file_is_there(self, tmp_path):
        (tmp_path / f"{os.getpid()}.json").write_text("{}", encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.resolve_session_pid() == os.getpid()

    def test_false_when_it_is_not(self, tmp_path):
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_get_ppid_portable", return_value=None),
        ):
            assert cc_sessions.resolve_session_pid() is None

    def test_unresolvable_home_answers_false_not_raises(self):
        # _claude_home() degrades to a path that cannot exist. The old presence.py
        # built this path from Path.home() directly, so the same machine raised
        # RuntimeError into presence_gate's except-and-allow — the gate went dark
        # rather than reporting "no session files here".
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", cc_sessions.Path("<no-home>") / ".claude" / "sessions"),
            patch.object(cc_sessions, "_get_ppid_portable", return_value=None),
        ):
            assert cc_sessions.resolve_session_pid() is None


class TestGetPpidPortable:
    # The helper shells out to `ps` and is documented "Linux + macOS. Returns None
    # on failure". Windows has no `ps`, so None IS the contract there, not a
    # miss; pinned per platform after the Windows matrix went red on 2c8271a7
    # (assert None == 5516).
    @pytest.mark.skipif(sys.platform == "win32", reason="ps-based; Linux + macOS only by contract")
    def test_reports_our_real_parent(self):
        assert cc_sessions._get_ppid_portable(os.getpid()) == os.getppid()

    @pytest.mark.skipif(sys.platform != "win32", reason="the documented Windows answer")
    def test_windows_answers_none_by_contract(self):
        assert cc_sessions._get_ppid_portable(os.getpid()) is None

    def test_dead_pid_returns_none(self):
        assert cc_sessions._get_ppid_portable(999999999) is None


class TestIsPidAlive:
    """Liveness as `drone @hooks sessions` reports it: each listing line ends live or stale.

    The first four read the answer through the command (fleet_green leg 4);
    their proof is a mutant of the pid guard and of the probe.
    """

    @staticmethod
    def _status(tmp_path, capsys, pid: int) -> str:
        (tmp_path / f"{pid}.json").write_text(json.dumps({"pid": pid, "kind": "interactive"}), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("sessions", []) is True
        lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith(f"  PID {pid} · ")]
        assert len(lines) == 1
        return lines[0].rsplit(" ", 1)[1]

    def test_alive(self, tmp_path, capsys):
        assert self._status(tmp_path, capsys, os.getpid()) == "live"

    def test_dead(self, tmp_path, capsys):
        assert self._status(tmp_path, capsys, 999999999) == "stale"

    def test_pid_zero(self, tmp_path, capsys):
        assert self._status(tmp_path, capsys, 0) == "stale"

    def test_pid_one(self, tmp_path, capsys):
        assert self._status(tmp_path, capsys, 1) == "stale"

    def test_permission_error_treated_as_alive(self):
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=PermissionError("denied")):
            assert cc_sessions._is_pid_alive(42) is True

    def test_oserror_treated_as_dead(self):
        with patch("os.kill", side_effect=OSError("unknown")):
            assert cc_sessions._is_pid_alive(42) is False


class TestProcStartTicks:
    """The first two read the live start through find_live_for_cwd (fleet_green leg 4):
    our own session file carries a recorded procStart, and the listing keeps it
    only when the value read back from /proc agrees. Proof: mutants of the read."""

    @staticmethod
    def _kept(tmp_path, recorded: str) -> bool:
        s = {"pid": os.getpid(), "sessionId": "own", "cwd": str(tmp_path / "hooks"), "procStart": recorded}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            return [r["sessionId"] for r in cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))] == ["own"]

    @pytest.mark.skipif(sys.platform != "linux", reason="reads the real /proc filesystem")
    def test_current_process_returns_value_on_linux(self, tmp_path):
        # A value was read: an unreadable start would fall back to keeping it.
        assert self._kept(tmp_path, "not-a-tick") is False

    @pytest.mark.skipif(sys.platform != "linux", reason="reads the real /proc filesystem")
    def test_matches_raw_proc_stat_field(self, tmp_path):
        raw = (cc_sessions.Path("/proc") / str(os.getpid()) / "stat").read_text(encoding="utf-8")
        expected = raw.rsplit(")", 1)[1].split()[19]
        assert self._kept(tmp_path, expected) is True

    def test_non_linux_returns_none(self):
        with patch("sys.platform", "win32"):
            assert cc_sessions._proc_start_ticks(os.getpid()) is None

    def test_missing_pid_returns_none(self):
        with patch("sys.platform", "linux"):
            assert cc_sessions._proc_start_ticks(999999999) is None


class TestSessionPidMatches:
    """Four units moved 2026-09-28: their answers are read through find_live_for_cwd
    (TestFindLiveForCwd), the units archived in tests/.archive. The non-int guard
    stays: find_live_for_cwd hands the pid to the liveness check first, so no
    public route reaches it."""

    def test_non_int_pid_passes(self):
        assert cc_sessions._session_pid_matches({"pid": "not-an-int", "procStart": "123"}) is True


class TestReadAllSessions:
    def test_reads_pid_files(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc", "cwd": str(tmp_path / "branch"), "kind": "interactive"}
        (tmp_path / "1234.json").write_text(json.dumps(session), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert len(result) == 1
        assert result[0]["pid"] == 1234

    def test_skips_non_pid_files(self, tmp_path):
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        (tmp_path / "abc.json").write_text("{}", encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert result == []

    def test_skips_corrupt_json(self, tmp_path):
        (tmp_path / "999.json").write_text("not json{{{", encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert result == []

    def test_empty_dir(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert result == []

    def test_missing_dir(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path / "nonexistent"):
            result = cc_sessions.read_all_sessions()
        assert result == []

    def test_multiple_sessions(self, tmp_path):
        for pid in (100, 200, 300):
            s = {"pid": pid, "sessionId": f"s-{pid}", "cwd": str(tmp_path), "kind": "interactive"}
            (tmp_path / f"{pid}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert len(result) == 3


class TestFindLiveForCwd:
    def test_filters_by_cwd(self, tmp_path):
        s1 = {"pid": os.getpid(), "sessionId": "a", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        s2 = {"pid": os.getpid(), "sessionId": "b", "cwd": str(tmp_path / "devpulse"), "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s1), encoding="utf-8")
        (tmp_path / "99999.json").write_text(json.dumps(s2), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))
        assert len(result) == 1
        assert result[0]["sessionId"] == "a"

    def test_excludes_dead_pids(self, tmp_path):
        s = {"pid": 999999999, "sessionId": "dead", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        (tmp_path / "999999999.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))
        assert result == []

    def test_resolves_paths(self, tmp_path):
        target = str(tmp_path / "hooks")
        s = {"pid": os.getpid(), "sessionId": "a", "cwd": target, "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd(target + "/")
        assert len(result) == 1

    def test_empty_cwd_skipped(self, tmp_path):
        s = {"pid": os.getpid(), "sessionId": "a", "cwd": "", "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))
        assert result == []

    def test_excludes_reused_pid_with_mismatched_procstart(self, tmp_path):
        s = {
            "pid": os.getpid(),
            "sessionId": "reused",
            "cwd": str(tmp_path / "hooks"),
            "kind": "interactive",
            "procStart": "1",
        }
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s), encoding="utf-8")
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_proc_start_ticks", return_value="999999999"),
        ):
            result = cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))
        assert result == []

    def test_includes_session_with_matching_procstart(self, tmp_path):
        s = {
            "pid": os.getpid(),
            "sessionId": "genuine",
            "cwd": str(tmp_path / "hooks"),
            "kind": "interactive",
            "procStart": "42",
        }
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s), encoding="utf-8")
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_proc_start_ticks", return_value="42"),
        ):
            result = cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))
        assert len(result) == 1
        assert result[0]["sessionId"] == "genuine"

    def test_includes_session_without_procstart_field(self, tmp_path):
        s = {"pid": os.getpid(), "sessionId": "no-procstart", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))
        assert len(result) == 1
        assert result[0]["sessionId"] == "no-procstart"

    def test_unreadable_live_start_falls_back_to_liveness(self, tmp_path):
        """A recorded procStart the host cannot read back is not a mismatch.

        Moved here from the _session_pid_matches unit (fleet_green leg 4) so the
        fallback is read through find_live_for_cwd. Proof: the mutant that
        answers False on an unreadable start.
        """
        s = {
            "pid": os.getpid(),
            "sessionId": "unreadable",
            "cwd": str(tmp_path / "hooks"),
            "kind": "interactive",
            "procStart": "11277752",
        }
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s), encoding="utf-8")
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_proc_start_ticks", return_value=None),
        ):
            result = cc_sessions.find_live_for_cwd(str(tmp_path / "hooks"))
        assert [r["sessionId"] for r in result] == ["unreadable"]


class TestFindOccupant:
    def test_no_occupant_when_free(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant(str(tmp_path / "hooks"))
        assert result is None

    def test_excludes_own_pid(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "mine", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant(str(tmp_path / "hooks"), exclude_pid=my_pid)
        assert result is None

    def test_finds_other_occupant(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "other", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant(str(tmp_path / "hooks"), exclude_pid=99999)
        assert result is not None
        assert result["sessionId"] == "other"

    def test_no_exclude_returns_any_live(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "any", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant(str(tmp_path / "hooks"))
        assert result is not None
        assert result["sessionId"] == "any"

    def test_reused_pid_never_reported_as_occupant(self, tmp_path):
        my_pid = os.getpid()
        s = {
            "pid": my_pid,
            "sessionId": "stale-claim",
            "cwd": str(tmp_path / "hooks"),
            "kind": "interactive",
            "procStart": "1",
        }
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s), encoding="utf-8")
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_proc_start_ticks", return_value="999999999"),
        ):
            result = cc_sessions.find_occupant(str(tmp_path / "hooks"), exclude_pid=99999)
        assert result is None


class TestReclaim:
    def test_reclaim_stops_live_sessions(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "a", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s), encoding="utf-8")
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_stop_session", return_value="stopped") as mock_stop,
        ):
            actions = cc_sessions.reclaim()
        assert actions == ["stopped"]
        mock_stop.assert_called_once()
        assert mock_stop.call_args.args[0]["sessionId"] == "a"

    def test_reclaim_filters_by_branch(self, tmp_path):
        my_pid = os.getpid()
        s1 = {"pid": my_pid, "sessionId": "a", "cwd": str(tmp_path / "hooks"), "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s1), encoding="utf-8")
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_stop_session", return_value="stopped") as mock_stop,
        ):
            actions = cc_sessions.reclaim("devpulse")
        assert actions == []
        mock_stop.assert_not_called()

    def test_reclaim_empty_no_actions(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            actions = cc_sessions.reclaim()
        assert actions == []


class TestSessionHelpers:
    """Branch and short id, read where a caller outside the module meets them: the listing line.

    `drone @hooks sessions` prints one line per session file as
    PID · branch · short-id · kind · age, so each helper's answer is pinned
    between its two separators. Green from their first run; their proof is a
    mutant of each helper (fleet_green leg 4).
    """

    @staticmethod
    def _listing(tmp_path, capsys, session: dict) -> str:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "999999999.json").write_text(json.dumps(session), encoding="utf-8")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", sessions_dir):
            assert cc_sessions.handle_command("sessions", []) is True
        return capsys.readouterr().err

    def test_session_branch(self, tmp_path, capsys):
        cwd = tmp_path / "project" / "src" / "aipass" / "hooks"
        err = self._listing(tmp_path, capsys, {"pid": 999999999, "cwd": str(cwd), "kind": "interactive"})
        assert "PID 999999999 · hooks · " in err

    def test_session_branch_empty_cwd(self, tmp_path, capsys):
        err = self._listing(tmp_path, capsys, {"pid": 999999999, "cwd": "", "kind": "interactive"})
        assert "PID 999999999 · ? · " in err

    def test_session_short_id(self, tmp_path, capsys):
        session = {"pid": 999999999, "cwd": "", "sessionId": "abcdef1234567890", "kind": "interactive"}
        err = self._listing(tmp_path, capsys, session)
        assert " · abcdef12 · interactive · " in err

    def test_session_short_id_short(self, tmp_path, capsys):
        session = {"pid": 999999999, "cwd": "", "sessionId": "abc", "kind": "interactive"}
        err = self._listing(tmp_path, capsys, session)
        assert " · abc · interactive · " in err

    def test_session_short_id_missing(self, tmp_path, capsys):
        err = self._listing(tmp_path, capsys, {"pid": 999999999, "cwd": "", "kind": "interactive"})
        assert "PID 999999999 · ? ·  · interactive · " in err


class TestIntrospection:
    def test_print_introspection_no_sessions(self, tmp_path, capsys):
        """With no session files, introspection still names itself and the dir.

        Had no oracle: an introspection that printed nothing passed, which is
        exactly the failure this unit is positioned to catch - the empty-dir
        path is the one where a reader has nothing else to check against.
        """
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            cc_sessions.print_introspection()

        # stderr, not stdout: this module prints through the cli's err_console,
        # which is the seam that lets drone pipe a command's real output while
        # narration still reaches the terminal.
        err = capsys.readouterr().err
        assert err.startswith("sessions — CC session listing & reclaim")
        assert "No CC session files found" in err

    def test_handle_command_sessions(self, tmp_path, capsys):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("sessions", []) is True
        assert "No CC session files found" in capsys.readouterr().err

    def test_handle_command_cc_sessions_legacy(self, tmp_path, capsys):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("cc_sessions", []) is True
        assert "No CC session files found" in capsys.readouterr().err

    def test_handle_command_sessions_reclaim(self, tmp_path, capsys):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("sessions", ["reclaim"]) is True
        err = capsys.readouterr().err
        assert err.startswith("sessions reclaim\n")
        assert "No live sessions to reclaim" in err

    def test_handle_command_sessions_reclaim_branch(self, tmp_path, capsys):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("sessions", ["reclaim", "@hooks"]) is True
        err = capsys.readouterr().err
        assert err.startswith("sessions reclaim @hooks\n")
        assert "No live sessions to reclaim" in err

    def test_handle_command_help(self, capsys):
        assert cc_sessions.handle_command("--help", []) is True
        assert "drone @hooks sessions reclaim @branch  Stop sessions for a branch" in capsys.readouterr().err

    def test_handle_command_unknown(self):
        assert cc_sessions.handle_command("unknown", []) is False


class TestOccupantSelectionIsKindAware:
    """The seam named by @devpulse when the gate was flipped on 2026-08-18:
    find_occupant returned the FIRST non-self match, so a bg occupant could
    shadow a live interactive seat behind it — and a caller that skips bg
    (ruling a) would then ALLOW what it should have blocked."""

    @staticmethod
    def _live(*sessions):
        return patch.object(cc_sessions, "find_live_for_cwd", return_value=list(sessions))

    @staticmethod
    def _s(pid, kind, started_ms):
        return {"pid": pid, "kind": kind, "startedAt": started_ms, "cwd": "/tmp/branch"}

    @staticmethod
    def _occupant_pid(cwd, **kwargs):
        """The occupant's pid, having first proved there IS an occupant.

        Every row below used to index find_occupant's result inline. It returns
        dict | None - None is a real answer, pinned by test_free_branch_is_none
        - so pyright read eight subscripts of None, and a regression that
        answered None would have surfaced as a TypeError inside the assert
        rather than as the ranking claim that actually broke.
        """
        occupant = cc_sessions.find_occupant(cwd, **kwargs)
        assert occupant is not None
        return occupant["pid"]

    def test_a_seat_behind_a_job_is_not_shadowed(self, tmp_path):
        job = self._s(1, "bg", 1_000_000_000_000)
        seat = self._s(2, "interactive", 1_000_000_500_000)
        with self._live(job, seat):
            assert self._occupant_pid(str(tmp_path / "branch")) == 2

    def test_order_on_disk_does_not_decide(self, tmp_path):
        """Session files are read in directory order — the answer must not be."""
        job = self._s(1, "bg", 1_000_000_000_000)
        seat = self._s(2, "interactive", 1_000_000_500_000)
        for ordering in ((job, seat), (seat, job)):
            with self._live(*ordering):
                assert self._occupant_pid(str(tmp_path / "branch")) == 2

    def test_a_job_is_still_returned_when_it_is_the_only_occupant(self, tmp_path):
        """Ranking, not filtering — a bg-only branch stays answerable."""
        with self._live(self._s(1, "bg", 1_000_000_000_000)):
            assert self._occupant_pid(str(tmp_path / "branch")) == 1

    def test_background_spelling_ranks_as_a_job_too(self, tmp_path):
        job = self._s(1, "background", 1_000_000_000_000)
        seat = self._s(2, "interactive", 1_000_000_500_000)
        with self._live(job, seat):
            assert self._occupant_pid(str(tmp_path / "branch")) == 2

    def test_the_oldest_seat_is_the_incumbent(self, tmp_path):
        """Callers rank themselves against 'the occupant' — that must be the
        incumbent, or the newest arrival could pass as one."""
        older = self._s(1, "interactive", 1_000_000_000_000)
        newer = self._s(2, "interactive", 1_000_000_900_000)
        with self._live(newer, older):
            assert self._occupant_pid(str(tmp_path / "branch")) == 1

    def test_three_sessions_job_first_still_names_the_oldest_seat(self, tmp_path):
        job = self._s(1, "bg", 999_000_000_000)
        newer_seat = self._s(2, "interactive", 1_000_000_900_000)
        older_seat = self._s(3, "interactive", 1_000_000_000_000)
        with self._live(job, newer_seat, older_seat):
            assert self._occupant_pid(str(tmp_path / "branch")) == 3

    def test_unknown_start_never_displaces_a_seat_whose_age_is_known(self, tmp_path):
        undated = {"pid": 1, "kind": "interactive", "cwd": "/tmp/branch"}
        dated = self._s(2, "interactive", 1_000_000_900_000)
        with self._live(undated, dated):
            assert self._occupant_pid(str(tmp_path / "branch")) == 2

    def test_our_own_pid_is_still_excluded(self, tmp_path):
        seat = self._s(2, "interactive", 1_000_000_500_000)
        with self._live(self._s(1, "bg", 1_000_000_000_000), seat):
            assert self._occupant_pid(str(tmp_path / "branch"), exclude_pid=2) == 1

    def test_free_branch_is_none(self, tmp_path):
        with self._live():
            assert cc_sessions.find_occupant(str(tmp_path / "branch")) is None


class TestSessionStart:
    def test_epoch_milliseconds(self):
        assert cc_sessions.session_start({"startedAt": 1_000_000_000_000}) == 1_000_000_000.0

    def test_iso_string(self):
        # 2026-08-18T12:00:00Z in epoch seconds, measured once with a UTC datetime.
        assert cc_sessions.session_start({"startedAt": "2026-08-18T12:00:00Z"}) == 1_787_054_400.0

    def test_missing_is_none_not_zero(self):
        assert cc_sessions.session_start({}) is None

    def test_garbage_is_none(self):
        assert cc_sessions.session_start({"startedAt": "not a time"}) is None
