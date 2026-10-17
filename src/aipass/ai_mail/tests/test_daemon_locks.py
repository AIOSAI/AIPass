# =================== AIPass ====================
# Name: test_daemon_locks.py
# Description: Tests for the dispatch daemon's dispatch lock, its own pid file and the occupied-branch check
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/dispatch/daemon.py -- the dispatch lock, the daemon pid file and is_branch_occupied."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — a real Windows delete-pending denial; os.open is scripted to answer it here

import json
import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import aipass.ai_mail.apps.handlers.dispatch.daemon as daemon_mod
import aipass.ai_mail.apps.handlers.dispatch.pid_lock as pid_lock_mod
from aipass.ai_mail.apps.handlers.dispatch.daemon import (
    check_lock,
    acquire_lock,
    is_branch_occupied,
    run_daemon,
)

pytestmark = pytest.mark.usefixtures("daemon_json_silenced", "daemon_paths_in_tmp", "daemon_signals_restored")


# ---- check_lock tests ------------------------------------------


def test_check_lock_no_file(tmp_path):
    """No lock file returns None."""
    result = check_lock(tmp_path)

    assert result is None


def test_check_lock_alive_pid(tmp_path, monkeypatch):
    """Lock with alive PID returns lock data."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": datetime.now().isoformat()}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=True)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is not None
    assert result["pid"] == 99999
    alive.assert_called_once_with(99999)


def test_check_lock_dead_pid(tmp_path, monkeypatch):
    """Lock with dead PID is cleaned up."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": datetime.now().isoformat()}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=False)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()
    alive.assert_called_once_with(99999)


def test_check_lock_stale_over_10min_removed(tmp_path, monkeypatch):
    """Stale lock older than 10 minutes with dead PID is removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    old_time = (datetime.now() - timedelta(minutes=15)).isoformat()
    lock_data = {"pid": 99999, "timestamp": old_time}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=False)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()
    alive.assert_called_once_with(99999)


def test_check_lock_stale_under_10min_dead_pid_removed(tmp_path, monkeypatch):
    """Stale lock under 10 minutes with dead PID is also removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    recent_time = (datetime.now() - timedelta(minutes=5)).isoformat()
    lock_data = {"pid": 99999, "timestamp": recent_time}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    alive = MagicMock(return_value=False)
    monkeypatch.setattr(pid_lock_mod, "check_pid_alive", alive)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()
    alive.assert_called_once_with(99999)


def test_check_lock_fresh_corrupt_json_is_held(tmp_path):
    """A corrupt lock younger than the grace is a writer mid-write: held, not removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json!!", encoding="utf-8")

    result = check_lock(tmp_path)

    assert result is not None
    assert lock_file.exists()


def test_check_lock_old_corrupt_json_removed(tmp_path):
    """A corrupt lock an hour old is a crashed writer's leftover: removed, None."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text("{bad json!!", encoding="utf-8")
    hour_ago = lock_file.stat().st_mtime - 3600
    os.utime(lock_file, (hour_ago, hour_ago))

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


def test_check_lock_zombie_holder_is_dead(tmp_path, monkeypatch):
    """A lock held by a linux zombie is reclaimed: the wake's liveness rule."""
    monkeypatch.setattr(sys, "platform", "linux")
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text(json.dumps({"pid": 4242}), encoding="utf-8")
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(pid_lock_mod, "_is_zombie_linux", lambda pid: pid == 4242)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


def test_check_lock_unparseable_timestamp(tmp_path, monkeypatch):
    """Lock with unparseable timestamp and dead PID is removed."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_data = {"pid": 99999, "timestamp": "not-a-timestamp"}
    lock_file.write_text(json.dumps(lock_data), encoding="utf-8")

    def _raise_process_lookup(pid, sig):
        raise ProcessLookupError("No such process")

    monkeypatch.setattr(os, "kill", _raise_process_lookup)

    result = check_lock(tmp_path)

    assert result is None
    assert not lock_file.exists()


# ---- acquire_lock tests -----------------------------------------


def test_acquire_lock_success(tmp_path):
    """New lock file is created atomically."""
    acquired, msg = acquire_lock(tmp_path, 12345)

    assert acquired is True
    assert msg == "Lock acquired"
    lock_file = tmp_path / ".ai_mail.local" / ".dispatch.lock"
    assert lock_file.exists()
    data = json.loads(lock_file.read_text(encoding="utf-8"))
    assert data["pid"] == 12345


def test_acquire_lock_file_exists_error(tmp_path):
    """FileExistsError when lock already present returns (False, message)."""
    lock_dir = tmp_path / ".ai_mail.local"
    lock_dir.mkdir(parents=True)
    lock_file = lock_dir / ".dispatch.lock"
    lock_file.write_text('{"pid": 111}', encoding="utf-8")

    acquired, msg = acquire_lock(tmp_path, 22222)

    assert acquired is False
    assert "already exists" in msg


def test_acquire_lock_oserror(tmp_path):
    """OSError during lock creation returns (False, message)."""
    with patch("os.open", side_effect=OSError("Permission denied")):
        acquired, msg = acquire_lock(tmp_path, 12345)

    assert acquired is False
    assert "Lock failed" in msg


# ---- _write_pid_file tests --------------------------------------


def _start_daemon(tmp_path, monkeypatch, pid_file, while_running=None):
    """Run run_daemon with SHUTDOWN set, so it stops right after start-up.

    Returns what the pid file held when config loaded; [] means the daemon
    never started. while_running stands in for whatever touches the pid file
    during the run.
    """
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", True)
    pid_at_start = []

    def config_after_pid():
        pid_at_start.append(pid_file.read_text(encoding="utf-8").strip())
        if while_running is not None:
            while_running()
        return {"poll_interval_seconds": 0, "kill_switch_path": str(tmp_path / "pause"), "autonomous_branches": []}

    monkeypatch.setattr(daemon_mod, "load_config", config_after_pid)
    run_daemon()
    return pid_at_start


def test_write_pid_file_no_existing(tmp_path, monkeypatch):
    """No existing PID file: the daemon writes its own PID and starts."""
    pid_file = tmp_path / "daemon.pid"

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]


def test_write_pid_file_existing_alive_pid(tmp_path, monkeypatch):
    """Existing PID file with alive process: the daemon does not start."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == []


def test_write_pid_file_existing_dead_pid(tmp_path, monkeypatch):
    """Existing PID file with dead process: the daemon takes over and starts."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")

    def _kill_stub(pid, sig):
        if pid == 999999:
            raise ProcessLookupError("No such process")

    monkeypatch.setattr(os, "kill", _kill_stub)

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]


def test_write_pid_file_existing_permission_error(tmp_path, monkeypatch):
    """Existing PID file with PermissionError on kill: the daemon does not start."""
    monkeypatch.setattr("sys.platform", "linux")
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("888888", encoding="utf-8")

    def _raise_permission(pid, sig):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(os, "kill", _raise_permission)

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == []


def test_write_pid_file_corrupt_pid_file(tmp_path, monkeypatch):
    """Corrupt PID file is overwritten and the daemon starts."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("not-a-number", encoding="utf-8")

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]


# ---- _write_pid_file: the Windows delete-pending denial -------------
#
# Windows answers an exclusive create against a pid file another process is
# still releasing (delete pending) with PermissionError, not FileExistsError.
# POSIX unlinks the name at once, so no Linux or macOS run can produce it:
# every case below MANUFACTURES the Windows answer by scripting os.open.

_REAL_OS_OPEN = os.open


@pytest.fixture
def fake_clock(monkeypatch):
    """time.monotonic that moves only when the code sleeps - no real waiting."""
    clock = {"now": 1000.0, "sleeps": 0}

    def fake_sleep(seconds):
        clock["now"] += seconds
        clock["sleeps"] += 1

    monkeypatch.setattr(daemon_mod.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(daemon_mod.time, "sleep", fake_sleep)
    return clock


def _denial(path):
    """The Windows delete-pending answer, as Python raises it (EACCES)."""
    return PermissionError(13, "Access is denied", str(path))


def _scripted_pid_open(pid_file, script, calls):
    """os.open that answers the pid file from *script*, then for real.

    A script step is an exception to raise, a callable run before the real
    create (it may raise), or None for the real create. Other paths open for real.
    """

    def fake_open(path, flags, mode=0o777, *args, **kwargs):
        if str(path) != str(pid_file):
            return _REAL_OS_OPEN(path, flags, mode, *args, **kwargs)
        calls.append(flags)
        step = script.pop(0) if script else None
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            step()
        return _REAL_OS_OPEN(path, flags, mode, *args, **kwargs)

    return fake_open


def test_write_pid_file_first_create_denied_once_then_lands(tmp_path, monkeypatch, fake_clock):
    """The first create, denied once (a previous daemon's file still releasing), is polled and lands."""
    pid_file = tmp_path / "daemon.pid"
    calls = []
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [_denial(pid_file)], calls))

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]
    assert len(calls) == 2
    assert fake_clock["sleeps"] == 1


def test_write_pid_file_retake_denied_once_then_lands(tmp_path, monkeypatch, fake_clock):
    """The create right after unlinking a stale pid file - our own delete still pending - is polled and lands."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    alive = MagicMock(return_value=False)
    monkeypatch.setattr(daemon_mod, "_pid_alive", alive)
    calls = []
    # real (exists) -> denied (the unlink we just made is still pending) -> real
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [None, _denial(pid_file)], calls))

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]
    assert len(calls) == 3
    alive.assert_called_once_with(999999)


def test_write_pid_file_stale_unlink_denied_create_waits_it_out(tmp_path, monkeypatch, fake_clock):
    """Unlinking a stale pid file someone else already deleted is denied too; the create waits the release out."""
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    alive = MagicMock(return_value=False)
    monkeypatch.setattr(daemon_mod, "_pid_alive", alive)
    real_unlink = daemon_mod.Path.unlink
    denied = []

    def unlink_denied(self, missing_ok=False):
        # Denied once: the stale file's release. The stop's own unlink lands.
        if self == pid_file and not denied:
            denied.append(self)
            raise _denial(self)
        return real_unlink(self, missing_ok=missing_ok)

    def pending_delete_completes():
        real_unlink(pid_file)
        raise _denial(pid_file)

    monkeypatch.setattr(daemon_mod.Path, "unlink", unlink_denied)
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [None, pending_delete_completes], []))

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == [str(os.getpid())]
    assert denied == [pid_file]
    alive.assert_called_once_with(999999)


def test_stale_unlink_failing_otherwise_than_denied_escapes(tmp_path, monkeypatch):
    """Only a DENIED unlink of the stale pid file is left to the create.

    Any other failure escapes run_daemon as itself: caught, the create would
    meet the stale file still standing and report "another daemon raced us",
    a race that never happened. The error is this stand-in's own. Green on the
    tree from its first run; its proof is the mutant that widens the catch to
    OSError.
    """
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "_pid_alive", MagicMock(return_value=False))
    stuck = OSError(30, "Read-only file system", str(pid_file))
    real_unlink = daemon_mod.Path.unlink

    def unlink_fails(self, missing_ok=False):
        if self == pid_file:
            raise stuck
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(daemon_mod.Path, "unlink", unlink_fails)

    with pytest.raises(OSError) as raised:
        _start_daemon(tmp_path, monkeypatch, pid_file)
    assert raised.value is stuck


def test_write_pid_file_denial_that_never_clears_raises_at_budget(tmp_path, monkeypatch, fake_clock):
    """A denial that outlasts the wait raises - naming the wait, the denial as cause - and never loops forever."""
    pid_file = tmp_path / "daemon.pid"
    denial = _denial(pid_file)
    attempts = []

    def always_denied(path, flags, mode=0o777, *args, **kwargs):
        if str(path) != str(pid_file):
            return _REAL_OS_OPEN(path, flags, mode, *args, **kwargs)
        attempts.append(path)
        if len(attempts) > 10_000:
            raise AssertionError("retried past any budget - the wait is not bounded")
        raise denial

    monkeypatch.setattr(daemon_mod.os, "open", always_denied)
    start = fake_clock["now"]

    with pytest.raises(PermissionError) as excinfo:
        _start_daemon(tmp_path, monkeypatch, pid_file)

    assert excinfo.value is not denial
    assert excinfo.value.__cause__ is denial
    assert f"{daemon_mod.PID_DENIED_WAIT_SECONDS}s" in str(excinfo.value)
    assert fake_clock["now"] - start >= daemon_mod.PID_DENIED_WAIT_SECONDS
    assert not pid_file.exists()


def test_run_daemon_starts_after_a_denied_pid_create(tmp_path, monkeypatch, fake_clock):
    """The daemon starts after one delete-pending denial: the pid file is on disk when config loads."""
    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(daemon_mod, "DAEMON_PID_FILE", pid_file)
    monkeypatch.setattr(daemon_mod, "SHUTDOWN", True)
    monkeypatch.setattr(daemon_mod.os, "open", _scripted_pid_open(pid_file, [_denial(pid_file)], []))
    pid_at_start = []

    def config_after_pid():
        pid_at_start.append(pid_file.read_text(encoding="utf-8").strip())
        return {"poll_interval_seconds": 0, "kill_switch_path": str(tmp_path / "pause"), "autonomous_branches": []}

    monkeypatch.setattr(daemon_mod, "load_config", config_after_pid)

    run_daemon()

    assert pid_at_start == [str(os.getpid())]
    assert not pid_file.exists()  # a clean stop removes its own pid file


# ---- _remove_pid_file tests ------------------------------------


def test_remove_pid_file_matching_pid(tmp_path, monkeypatch):
    """A clean stop removes the daemon's own PID file."""
    pid_file = tmp_path / "daemon.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file)

    assert not pid_file.exists()


def test_remove_pid_file_different_pid(tmp_path, monkeypatch):
    """A PID file another daemon took over during the run is left alone at stop."""
    pid_file = tmp_path / "daemon.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file, lambda: pid_file.write_text("999999", encoding="utf-8"))

    assert pid_file.read_text(encoding="utf-8").strip() == "999999"


def test_remove_pid_file_missing(tmp_path, monkeypatch):
    """A PID file gone during the run does not break the stop."""
    pid_file = tmp_path / "daemon.pid"
    moved = tmp_path / "moved.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file, lambda: pid_file.rename(moved))

    assert not pid_file.exists()
    assert moved.exists()


def test_remove_pid_file_corrupt(tmp_path, monkeypatch):
    """A PID file corrupted during the run is removed at stop."""
    pid_file = tmp_path / "daemon.pid"

    _start_daemon(tmp_path, monkeypatch, pid_file, lambda: pid_file.write_text("not-a-number", encoding="utf-8"))

    assert not pid_file.exists()


# ---- is_branch_occupied tests ------------------------------------
# The daemon uses pid_lock's is_branch_occupied and process readers; their own tests,
# the darwin lanes among them, live in test_wake.py.


def test_is_branch_occupied_no_claude_processes(tmp_path):
    """Returns False when pgrep finds no claude processes."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch(
        "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
        return_value=mock_result,
    ):
        result = is_branch_occupied(tmp_path)

    assert result is False


def test_is_branch_occupied_claude_in_different_dir(tmp_path, monkeypatch):
    """Returns False when claude runs in a different directory."""
    monkeypatch.setattr(sys, "platform", "linux")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "12345\n"

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
            return_value=mock_result,
        ),
        patch("os.readlink", return_value="/some/other/dir"),
    ):
        result = is_branch_occupied(tmp_path)

    assert result is False


def test_is_branch_occupied_claude_in_same_dir_interactive(tmp_path, monkeypatch):
    """Returns True when interactive claude session runs in same directory."""
    monkeypatch.setattr(sys, "platform", "linux")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "12345\n"

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
            return_value=mock_result,
        ),
        patch("os.readlink", return_value=str(tmp_path.resolve())),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.pid_lock._read_session_type",
            return_value="interactive",
        ),
    ):
        result = is_branch_occupied(tmp_path)

    assert result is True


def test_is_branch_occupied_claude_in_same_dir_daemon(tmp_path, monkeypatch):
    """Returns False when daemon claude session runs in same directory."""
    monkeypatch.setattr(sys, "platform", "linux")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "12345\n"

    with (
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
            return_value=mock_result,
        ),
        patch("os.readlink", return_value=str(tmp_path.resolve())),
        patch(
            "aipass.ai_mail.apps.handlers.dispatch.pid_lock._read_session_type",
            return_value="daemon",
        ),
    ):
        result = is_branch_occupied(tmp_path)

    assert result is False


def test_is_branch_occupied_pgrep_failure(tmp_path):
    """Returns False when pgrep cannot run.

    Since leg 12 this is wake's body, which catches what subprocess.run raises
    for a missing or failing tool (OSError, SubprocessError) and nothing wider;
    the daemon's copy caught every Exception (ai_mail, leg 12).
    """
    with patch(
        "aipass.ai_mail.apps.handlers.dispatch.daemon.subprocess.run",
        side_effect=OSError("pgrep unavailable"),
    ):
        result = is_branch_occupied(tmp_path)

    assert result is False


# ---- _write_pid_file atomic tests (DPLAN-0159 S5) ----------------


def test_write_pid_file_atomic_race_second_loses(tmp_path, monkeypatch):
    """Stale PID file, but another daemon re-creates it first: the retry's O_EXCL loses and returns False.

    Mutant: the retry's `return False` after "raced us" turned to `return True` - two daemons start.
    """
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(daemon_mod, "_pid_alive", lambda pid: pid != 999999)
    create_calls = []

    def _create_always_loses():
        create_calls.append(1)
        return False

    monkeypatch.setattr(daemon_mod, "_create_pid_file", _create_always_loses)

    assert _start_daemon(tmp_path, monkeypatch, pid_file) == []
    assert len(create_calls) == 2
