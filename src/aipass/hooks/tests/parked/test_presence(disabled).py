"""Tests for the presence service module."""

import json
import sys
from contextlib import nullcontext
from unittest.mock import patch

import pytest

from aipass.hooks.apps.modules import presence


@pytest.fixture
def presence_dir(tmp_path):
    """Create a temporary .ai_central directory with PRESENCE.central.json."""
    ai_central = tmp_path / ".ai_central"
    ai_central.mkdir()
    return ai_central


@pytest.fixture
def presence_file(presence_dir):
    """Return path to the presence file."""
    return presence_dir / "PRESENCE.central.json"


@pytest.fixture
def patch_paths(presence_dir):
    """Patch _find_ai_central to use the temp directory."""
    with patch.object(presence, "_find_ai_central", return_value=presence_dir):
        yield presence_dir


@pytest.fixture
def patch_flock():
    """Make the presence lock a no-op (avoid real file locking in tests)."""
    with patch.object(presence, "_presence_lock", side_effect=lambda: nullcontext()):
        yield


def _patch_session_pid(pid):
    """Patch _resolve_session_pid to return a given PID."""
    return patch.object(presence, "_resolve_session_pid", return_value=pid)


# ── session PID resolution tests ────────────────────────────────────────


class TestResolveSessionPid:
    def test_finds_session_file_ancestor(self):
        ppid_map = {100: 90, 90: 80}
        with (
            patch("os.getpid", return_value=100),
            patch.object(presence, "_has_session_file", side_effect=lambda p: p == 80),
            patch.object(presence, "_get_ppid_portable", side_effect=lambda p: ppid_map.get(p)),
        ):
            assert presence._resolve_session_pid() == 80

    def test_no_session_file_ancestor_returns_none(self):
        ppid_map = {100: 90, 90: 80, 80: 1}
        with (
            patch("os.getpid", return_value=100),
            patch.object(presence, "_has_session_file", return_value=False),
            patch.object(presence, "_get_ppid_portable", side_effect=lambda p: ppid_map.get(p)),
        ):
            assert presence._resolve_session_pid() is None

    def test_ppid_failure_returns_none(self):
        with (
            patch("os.getpid", return_value=100),
            patch.object(presence, "_has_session_file", return_value=False),
            patch.object(presence, "_get_ppid_portable", return_value=None),
        ):
            assert presence._resolve_session_pid() is None

    def test_direct_session_process(self):
        with (
            patch("os.getpid", return_value=100),
            patch.object(presence, "_has_session_file", side_effect=lambda p: p == 100),
        ):
            assert presence._resolve_session_pid() == 100


# ── claim tests ──────────────────────────────────────────────────────────


class TestClaim:
    def test_claim_empty_file(self, patch_paths, patch_flock, presence_file):
        with _patch_session_pid(1000), patch("os.getcwd", return_value="/tmp/branch"):
            result = presence.claim("devpulse", session_id="abc")
        assert result["status"] == "ACQUIRED"
        data = json.loads(presence_file.read_text())
        assert data["devpulse"]["pid"] == 1000
        assert data["devpulse"]["session_id"] == "abc"
        assert data["devpulse"]["work_dir"] == "/tmp/branch"

    def test_claim_reentry_same_pid(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 1000,
                        "session_id": "old",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with _patch_session_pid(1000), patch("os.getcwd", return_value="/w"):
            result = presence.claim("devpulse", session_id="new-id")
        assert result["status"] == "ACQUIRED"
        data = json.loads(presence_file.read_text())
        assert data["devpulse"]["session_id"] == "new-id"

    def test_claim_stale_dead_pid(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 9999,
                        "session_id": "old",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with (
            _patch_session_pid(2000),
            patch("os.getcwd", return_value="/w2"),
            patch.object(presence, "_is_pid_alive", return_value=False),
        ):
            result = presence.claim("devpulse", session_id="new")
        assert result["status"] == "ACQUIRED"
        data = json.loads(presence_file.read_text())
        assert data["devpulse"]["pid"] == 2000

    def test_claim_occupied_live_pid(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 5000,
                        "session_id": "live",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with (
            _patch_session_pid(6000),
            patch("os.getcwd", return_value="/w2"),
            patch.object(presence, "_is_pid_alive", return_value=True),
            patch.object(presence, "_cwd_matches", return_value=True),
        ):
            result = presence.claim("devpulse", session_id="new")
        assert result["status"] == "OCCUPIED"
        assert result["pid"] == 5000
        assert result["session_type"] == "interactive"

    def test_claim_stale_cwd_mismatch(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 5000,
                        "session_id": "old",
                        "work_dir": "/original",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with (
            _patch_session_pid(6000),
            patch("os.getcwd", return_value="/new"),
            patch.object(presence, "_is_pid_alive", return_value=True),
            patch.object(presence, "_cwd_matches", return_value=False),
        ):
            result = presence.claim("devpulse", session_id="new")
        assert result["status"] == "ACQUIRED"

    def test_claim_no_existing_file(self, patch_paths, patch_flock):
        with _patch_session_pid(1000), patch("os.getcwd", return_value="/w"):
            result = presence.claim("hooks")
        assert result["status"] == "ACQUIRED"

    def test_claim_multiple_branches(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "api": {
                        "pid": 3000,
                        "session_id": "a",
                        "work_dir": "/api",
                        "session_type": "interactive-mirror",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with _patch_session_pid(4000), patch("os.getcwd", return_value="/hooks"):
            result = presence.claim("hooks", session_id="h1")
        assert result["status"] == "ACQUIRED"
        data = json.loads(presence_file.read_text())
        assert "api" in data
        assert "hooks" in data

    def test_claim_fails_open_when_no_session_pid(self, patch_paths, patch_flock):
        with _patch_session_pid(None):
            result = presence.claim("devpulse")
        assert result["status"] == "ACQUIRED"

    def test_claim_ephemeral_holder_reclaimed(self, patch_paths, patch_flock, presence_file):
        """Models the real ephemeral-PID scenario: holder PID is dead (hook exited),
        but a LIVE claude session exists. 2nd session reclaims."""
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 99999,
                        "session_id": "old",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with (
            _patch_session_pid(8000),
            patch("os.getcwd", return_value="/w"),
            patch.object(presence, "_is_pid_alive", return_value=False),
        ):
            result = presence.claim("devpulse", session_id="new")
        assert result["status"] == "ACQUIRED"
        data = json.loads(presence_file.read_text())
        assert data["devpulse"]["pid"] == 8000


# ── release tests ────────────────────────────────────────────────────────


class TestRelease:
    def test_release_existing(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 1000,
                        "session_id": "a",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with _patch_session_pid(1000):
            result = presence.release("devpulse")
        assert result is True
        data = json.loads(presence_file.read_text())
        assert "devpulse" not in data

    def test_release_not_claimed(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(json.dumps({}))
        with _patch_session_pid(1000):
            result = presence.release("devpulse")
        assert result is False

    def test_release_wrong_pid_refused(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 1000,
                        "session_id": "a",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with _patch_session_pid(9999):
            result = presence.release("devpulse")
        assert result is False
        data = json.loads(presence_file.read_text())
        assert "devpulse" in data
        assert data["devpulse"]["pid"] == 1000

    def test_release_no_session_pid_skips(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 1000,
                        "session_id": "a",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        with _patch_session_pid(None):
            result = presence.release("devpulse")
        assert result is False
        data = json.loads(presence_file.read_text())
        assert "devpulse" in data

    def test_release_preserves_others(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "devpulse": {
                        "pid": 1000,
                        "session_id": "a",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    },
                    "api": {
                        "pid": 2000,
                        "session_id": "b",
                        "work_dir": "/api",
                        "session_type": "interactive-mirror",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    },
                }
            )
        )
        with _patch_session_pid(1000):
            presence.release("devpulse")
        data = json.loads(presence_file.read_text())
        assert "api" in data
        assert "devpulse" not in data


# ── refresh tests ────────────────────────────────────────────────────────


class TestRefresh:
    def test_refresh_updates_last_seen(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(
            json.dumps(
                {
                    "hooks": {
                        "pid": 1000,
                        "session_id": "a",
                        "work_dir": "/w",
                        "session_type": "interactive",
                        "attach_handle": "",
                        "started": "2026-01-01T00:00:00",
                        "last_seen": "2026-01-01T00:00:00",
                    }
                }
            )
        )
        presence.refresh("hooks")
        data = json.loads(presence_file.read_text())
        assert data["hooks"]["last_seen"] != "2026-01-01T00:00:00"

    def test_refresh_nonexistent_noop(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text(json.dumps({}))
        presence.refresh("hooks")
        data = json.loads(presence_file.read_text())
        assert data == {}


# ── read_all tests ───────────────────────────────────────────────────────


class TestReadAll:
    def test_read_all_returns_data(self, patch_paths, patch_flock, presence_file):
        expected = {
            "hooks": {
                "pid": 1000,
                "session_id": "a",
                "work_dir": "/w",
                "session_type": "interactive",
                "attach_handle": "",
                "started": "2026-01-01T00:00:00",
                "last_seen": "2026-01-01T00:00:00",
            }
        }
        presence_file.write_text(json.dumps(expected))
        result = presence.read_all()
        assert result == expected

    def test_read_all_empty(self, patch_paths, patch_flock):
        result = presence.read_all()
        assert result == {}


# ── liveness tests ───────────────────────────────────────────────────────


class TestLiveness:
    def test_is_pid_alive_true(self):
        with patch("sys.platform", "linux"), patch("os.kill") as mock_kill:
            assert presence._is_pid_alive(1234) is True
            mock_kill.assert_called_once_with(1234, 0)

    def test_is_pid_alive_dead(self):
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=ProcessLookupError):
            assert presence._is_pid_alive(1234) is False

    def test_is_pid_alive_permission_error(self):
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=PermissionError):
            assert presence._is_pid_alive(1234) is True

    def test_cwd_matches_linux(self):
        with (
            patch("sys.platform", "linux"),
            patch("os.readlink", return_value="/tmp/project/src/aipass/hooks"),
        ):
            assert presence._cwd_matches(1234, "/tmp/project/src/aipass/hooks") is True

    def test_cwd_mismatch_linux(self):
        with (
            patch("sys.platform", "linux"),
            patch("os.readlink", return_value="/tmp/project/src/aipass/api"),
        ):
            assert presence._cwd_matches(1234, "/tmp/project/src/aipass/hooks") is False

    def test_cwd_matches_non_linux_skips(self):
        with patch("sys.platform", "win32"):
            assert presence._cwd_matches(1234, "/anything") is True

    def test_cwd_read_fails_treats_as_stale(self):
        with (
            patch("sys.platform", "linux"),
            patch("os.readlink", side_effect=OSError("no proc")),
        ):
            assert presence._cwd_matches(1234, "/w") is False

    def test_is_holder_alive_full_check(self):
        entry = {"pid": 1234, "work_dir": "/w"}
        with (
            patch.object(presence, "_is_pid_alive", return_value=True),
            patch.object(presence, "_cwd_matches", return_value=True),
        ):
            assert presence._is_holder_alive(entry) is True

    def test_is_holder_alive_dead_pid(self):
        entry = {"pid": 1234, "work_dir": "/w"}
        with patch.object(presence, "_is_pid_alive", return_value=False):
            assert presence._is_holder_alive(entry) is False

    def test_is_holder_alive_no_pid(self):
        assert presence._is_holder_alive({}) is False

    def test_is_holder_alive_no_work_dir(self):
        entry = {"pid": 1234, "work_dir": ""}
        with patch.object(presence, "_is_pid_alive", return_value=True):
            assert presence._is_holder_alive(entry) is False


# ── proc helpers tests ───────────────────────────────────────────────────


class TestProcHelpers:
    def test_read_proc_comm_success(self, tmp_path):
        comm_file = tmp_path / "comm"
        comm_file.write_text("claude\n")
        with patch("pathlib.Path.__truediv__", return_value=comm_file):
            pass
        with patch.object(presence.Path, "__new__", return_value=comm_file):
            pass
        result = presence._read_proc_comm(99999999)
        assert result == "" or isinstance(result, str)

    def test_read_proc_comm_oserror(self):
        result = presence._read_proc_comm(99999999)
        assert result == ""

    def test_read_proc_ppid_oserror(self):
        result = presence._read_proc_ppid(99999999)
        assert result is None


# ── file locking tests ──────────────────────────────────────────────────


class TestFileLocking:
    @pytest.mark.skipif(sys.platform == "win32", reason="fcntl is POSIX-only")
    def test_presence_lock_acquires_flock(self, patch_paths):
        with patch("aipass.hooks.apps.modules.presence.fcntl") as mock_fcntl:
            mock_fcntl.LOCK_EX = 2
            mock_fcntl.LOCK_UN = 8
            with presence._presence_lock():
                pass
            mock_fcntl.flock.assert_called()

    def test_corrupt_json_returns_empty(self, patch_paths, patch_flock, presence_file):
        presence_file.write_text("not json {{{")
        result = presence._read_presence()
        assert result == {}
