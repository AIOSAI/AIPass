"""Tests for CC-native session file reader."""

import json
import os
import sys
from unittest.mock import patch

import pytest

from aipass.hooks.apps.modules import cc_sessions


class TestIsPidAlive:
    def test_alive(self):
        assert cc_sessions._is_pid_alive(os.getpid()) is True

    def test_dead(self):
        assert cc_sessions._is_pid_alive(999999999) is False

    def test_pid_zero(self):
        assert cc_sessions._is_pid_alive(0) is False

    def test_pid_one(self):
        assert cc_sessions._is_pid_alive(1) is False

    def test_permission_error_treated_as_alive(self):
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=PermissionError("denied")):
            assert cc_sessions._is_pid_alive(42) is True

    def test_oserror_treated_as_dead(self):
        with patch("os.kill", side_effect=OSError("unknown")):
            assert cc_sessions._is_pid_alive(42) is False


class TestProcStartTicks:
    @pytest.mark.skipif(sys.platform != "linux", reason="reads the real /proc filesystem")
    def test_current_process_returns_value_on_linux(self):
        result = cc_sessions._proc_start_ticks(os.getpid())
        assert result is not None
        assert result.isdigit()

    @pytest.mark.skipif(sys.platform != "linux", reason="reads the real /proc filesystem")
    def test_matches_raw_proc_stat_field(self):
        result = cc_sessions._proc_start_ticks(os.getpid())
        from pathlib import Path

        raw = Path(f"/proc/{os.getpid()}/stat").read_text(encoding="utf-8")
        expected = raw.rsplit(")", 1)[1].split()[19]
        assert result == expected

    def test_non_linux_returns_none(self):
        with patch("sys.platform", "win32"):
            assert cc_sessions._proc_start_ticks(os.getpid()) is None

    def test_missing_pid_returns_none(self):
        with patch("sys.platform", "linux"):
            assert cc_sessions._proc_start_ticks(999999999) is None


class TestSessionPidMatches:
    def test_no_procstart_recorded_passes(self):
        assert cc_sessions._session_pid_matches({"pid": os.getpid()}) is True

    def test_non_int_pid_passes(self):
        assert cc_sessions._session_pid_matches({"pid": "not-an-int", "procStart": "123"}) is True

    def test_matching_procstart_passes(self):
        with patch.object(cc_sessions, "_proc_start_ticks", return_value="11277752"):
            assert cc_sessions._session_pid_matches({"pid": 123, "procStart": "11277752"}) is True

    def test_mismatched_procstart_fails(self):
        with patch.object(cc_sessions, "_proc_start_ticks", return_value="99999999"):
            assert cc_sessions._session_pid_matches({"pid": 123, "procStart": "11277752"}) is False

    def test_unreadable_live_start_falls_back_to_pass(self):
        with patch.object(cc_sessions, "_proc_start_ticks", return_value=None):
            assert cc_sessions._session_pid_matches({"pid": 123, "procStart": "11277752"}) is True


class TestReadAllSessions:
    def test_reads_pid_files(self, tmp_path):
        session = {"pid": 1234, "sessionId": "abc", "cwd": "/tmp/branch", "kind": "interactive"}
        (tmp_path / "1234.json").write_text(json.dumps(session))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert len(result) == 1
        assert result[0]["pid"] == 1234

    def test_skips_non_pid_files(self, tmp_path):
        (tmp_path / "config.json").write_text("{}")
        (tmp_path / "abc.json").write_text("{}")
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert result == []

    def test_skips_corrupt_json(self, tmp_path):
        (tmp_path / "999.json").write_text("not json{{{")
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
            s = {"pid": pid, "sessionId": f"s-{pid}", "cwd": "/tmp", "kind": "interactive"}
            (tmp_path / f"{pid}.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.read_all_sessions()
        assert len(result) == 3


class TestFindLiveForCwd:
    def test_filters_by_cwd(self, tmp_path):
        s1 = {"pid": os.getpid(), "sessionId": "a", "cwd": "/tmp/hooks", "kind": "interactive"}
        s2 = {"pid": os.getpid(), "sessionId": "b", "cwd": "/tmp/devpulse", "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s1))
        (tmp_path / "99999.json").write_text(json.dumps(s2))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd("/tmp/hooks")
        assert len(result) == 1
        assert result[0]["sessionId"] == "a"

    def test_excludes_dead_pids(self, tmp_path):
        s = {"pid": 999999999, "sessionId": "dead", "cwd": "/tmp/hooks", "kind": "interactive"}
        (tmp_path / "999999999.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd("/tmp/hooks")
        assert result == []

    def test_resolves_paths(self, tmp_path):
        target = str(tmp_path / "hooks")
        s = {"pid": os.getpid(), "sessionId": "a", "cwd": target, "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd(target + "/")
        assert len(result) == 1

    def test_empty_cwd_skipped(self, tmp_path):
        s = {"pid": os.getpid(), "sessionId": "a", "cwd": "", "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd("/tmp/hooks")
        assert result == []

    def test_excludes_reused_pid_with_mismatched_procstart(self, tmp_path):
        s = {
            "pid": os.getpid(),
            "sessionId": "reused",
            "cwd": "/tmp/hooks",
            "kind": "interactive",
            "procStart": "1",
        }
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s))
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_proc_start_ticks", return_value="999999999"),
        ):
            result = cc_sessions.find_live_for_cwd("/tmp/hooks")
        assert result == []

    def test_includes_session_with_matching_procstart(self, tmp_path):
        s = {
            "pid": os.getpid(),
            "sessionId": "genuine",
            "cwd": "/tmp/hooks",
            "kind": "interactive",
            "procStart": "42",
        }
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s))
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_proc_start_ticks", return_value="42"),
        ):
            result = cc_sessions.find_live_for_cwd("/tmp/hooks")
        assert len(result) == 1
        assert result[0]["sessionId"] == "genuine"

    def test_includes_session_without_procstart_field(self, tmp_path):
        s = {"pid": os.getpid(), "sessionId": "no-procstart", "cwd": "/tmp/hooks", "kind": "interactive"}
        (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_live_for_cwd("/tmp/hooks")
        assert len(result) == 1
        assert result[0]["sessionId"] == "no-procstart"


class TestFindOccupant:
    def test_no_occupant_when_free(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant("/tmp/hooks")
        assert result is None

    def test_excludes_own_pid(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "mine", "cwd": "/tmp/hooks", "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant("/tmp/hooks", exclude_pid=my_pid)
        assert result is None

    def test_finds_other_occupant(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "other", "cwd": "/tmp/hooks", "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant("/tmp/hooks", exclude_pid=99999)
        assert result is not None
        assert result["sessionId"] == "other"

    def test_no_exclude_returns_any_live(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "any", "cwd": "/tmp/hooks", "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s))
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            result = cc_sessions.find_occupant("/tmp/hooks")
        assert result is not None

    def test_reused_pid_never_reported_as_occupant(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "stale-claim", "cwd": "/tmp/hooks", "kind": "interactive", "procStart": "1"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s))
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_proc_start_ticks", return_value="999999999"),
        ):
            result = cc_sessions.find_occupant("/tmp/hooks", exclude_pid=99999)
        assert result is None


class TestReclaim:
    def test_reclaim_stops_live_sessions(self, tmp_path):
        my_pid = os.getpid()
        s = {"pid": my_pid, "sessionId": "a", "cwd": "/tmp/hooks", "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s))
        with (
            patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path),
            patch.object(cc_sessions, "_stop_session", return_value="stopped") as mock_stop,
        ):
            actions = cc_sessions.reclaim()
        assert len(actions) == 1
        mock_stop.assert_called_once()

    def test_reclaim_filters_by_branch(self, tmp_path):
        my_pid = os.getpid()
        s1 = {"pid": my_pid, "sessionId": "a", "cwd": "/tmp/hooks", "kind": "interactive"}
        (tmp_path / f"{my_pid}.json").write_text(json.dumps(s1))
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
    def test_session_branch(self):
        assert cc_sessions._session_branch({"cwd": "/tmp/project/src/aipass/hooks"}) == "hooks"

    def test_session_branch_empty_cwd(self):
        assert cc_sessions._session_branch({"cwd": ""}) == "?"

    def test_session_short_id(self):
        assert cc_sessions._session_short_id({"sessionId": "abcdef1234567890"}) == "abcdef12"

    def test_session_short_id_short(self):
        assert cc_sessions._session_short_id({"sessionId": "abc"}) == "abc"

    def test_session_short_id_missing(self):
        assert cc_sessions._session_short_id({}) == ""


class TestIntrospection:
    def test_print_introspection_no_sessions(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            cc_sessions.print_introspection()

    def test_handle_command_sessions(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("sessions", []) is True

    def test_handle_command_cc_sessions_legacy(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("cc_sessions", []) is True

    def test_handle_command_sessions_reclaim(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("sessions", ["reclaim"]) is True

    def test_handle_command_sessions_reclaim_branch(self, tmp_path):
        with patch.object(cc_sessions, "CC_SESSIONS_DIR", tmp_path):
            assert cc_sessions.handle_command("sessions", ["reclaim", "@hooks"]) is True

    def test_handle_command_help(self):
        assert cc_sessions.handle_command("--help", []) is True

    def test_handle_command_unknown(self):
        assert cc_sessions.handle_command("unknown", []) is False
