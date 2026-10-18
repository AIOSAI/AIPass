# =================== AIPass ====================
# Name: test_instance_lock.py
# Description: Tests for the monitor single-instance lock
# Version: 1.4.0
# Created: 2026-07-10
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/monitoring/instance_lock.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_structure) — try_acquire's log_operation record, covered by that row
# seedgo: no-test-needed(log_level) — the info lines naming each liveness verdict, covered by that row

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from aipass.prax.apps.handlers.monitoring import instance_lock as mod


@pytest.fixture(autouse=True)
def lock_world(monkeypatch, tmp_path):
    """Every edge of instance_lock.py replaced where it binds it: recorders, lock file tmp_path / "relay.pid"."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(mod, "json_handler", MagicMock())
    monkeypatch.setattr(mod, "logger", MagicMock())
    monkeypatch.setattr(mod, "_lock_path_override", tmp_path / "relay.pid")
    monkeypatch.setattr(mod, "_held_lock", None)


def _held_by(tmp_path, pid: int) -> None:
    """A lock file from an earlier relay, with no boot id: try_acquire decides by liveness alone."""
    (tmp_path / "relay.pid").write_text(json.dumps({"pid": pid}), encoding="utf-8")


class TestIsPidAlive:
    """Cross-platform PID liveness, read through its one reader, try_acquire: live refuses, dead is reclaimed."""

    def test_live_pid_returns_true_posix(self, tmp_path):
        """os.kill(pid, 0) success means alive on POSIX."""
        _held_by(tmp_path, 4242)
        with patch("sys.platform", "linux"), patch("os.kill") as kill:
            assert mod.try_acquire() is False
        kill.assert_called_once_with(4242, 0)

    def test_dead_pid_returns_false(self, tmp_path):
        """Non-existent PID returns False on POSIX."""
        _held_by(tmp_path, 99999999)
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=ProcessLookupError):
            assert mod.try_acquire() is True

    def test_permission_error_means_alive(self, tmp_path):
        """PermissionError means the process exists but is owned by another user."""
        _held_by(tmp_path, 1)
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=PermissionError):
            assert mod.try_acquire() is False

    def test_generic_oserror_returns_false(self, tmp_path):
        """Other OSError returns False."""
        _held_by(tmp_path, 12345)
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=OSError(99, "Unknown")):
            assert mod.try_acquire() is True

    def test_windows_delegates_to_pid_alive_windows(self, tmp_path):
        """On win32, _is_pid_alive delegates to _pid_alive_windows."""
        _held_by(tmp_path, 1234)
        with (
            patch("sys.platform", "win32"),
            patch.object(mod, "_pid_alive_windows", return_value=True) as mock_win,
        ):
            assert mod.try_acquire() is False
            mock_win.assert_called_once_with(1234)

    def test_windows_dead_pid(self, tmp_path):
        """On win32, dead PID returns False via _pid_alive_windows."""
        _held_by(tmp_path, 99999999)
        with (
            patch("sys.platform", "win32"),
            patch.object(mod, "_pid_alive_windows", return_value=False),
        ):
            assert mod.try_acquire() is True

    def test_windows_ctypes_failure_assumes_alive(self, tmp_path):
        """On win32, if ctypes fails, assume the process is alive (safe default)."""
        _held_by(tmp_path, 1234)
        with (
            patch("sys.platform", "win32"),
            patch.object(mod, "_pid_alive_windows", side_effect=OSError("ctypes failed")),
        ):
            assert mod.try_acquire() is False


class TestTryAcquire:
    """Test relay lock acquisition."""

    def test_creates_lock_file(self, tmp_path):
        """try_acquire() creates a lock file with the current PID."""
        lock_path = tmp_path / "relay.pid"

        assert mod.try_acquire() is True

        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()

    def test_returns_false_when_live_holder(self, tmp_path):
        """try_acquire() returns False when another live process holds the lock."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

        assert mod.try_acquire() is False

    def test_reclaims_stale_lock(self, tmp_path):
        """try_acquire() reclaims the lock when the recorded PID is dead."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text(json.dumps({"pid": 99999999}), encoding="utf-8")

        with patch.object(mod, "_is_pid_alive", return_value=False):
            assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()

    def test_reclaims_corrupt_lock_file(self, tmp_path):
        """try_acquire() overwrites a corrupt lock file."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text("{corrupt json", encoding="utf-8")

        assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()

    def test_creates_parent_directories(self, monkeypatch, tmp_path):
        """try_acquire() creates parent directories if they don't exist."""
        lock_path = tmp_path / "nested" / "dir" / "relay.pid"
        monkeypatch.setattr(mod, "_lock_path_override", lock_path)

        assert mod.try_acquire() is True
        assert lock_path.exists()


class TestBootIdentity:
    """Test cross-boot staleness detection (relay.pid outliving a reboot)."""

    def test_current_boot_id_returns_none_when_unreadable(self, tmp_path):
        """Platforms without /proc get None rather than an exception: the lock is taken with no boot id."""
        with patch("pathlib.Path.read_text", side_effect=OSError("no /proc")):
            assert mod.try_acquire() is True

        data = json.loads((tmp_path / "relay.pid").read_text(encoding="utf-8"))
        assert "boot_id" not in data

    # Skip names the platform that HAS procfs (macOS lacks it too); the sibling above is the portable half.
    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="reads /proc/sys/kernel/random/boot_id - no procfs here; the recipe is unavailable, not the state",
    )
    def test_current_boot_id_reads_proc_on_linux(self, tmp_path):
        """Linux exposes a non-empty boot id, stable within a boot, read through the lock it is written into."""
        lock_path = tmp_path / "relay.pid"
        assert mod.try_acquire() is True
        first = json.loads(lock_path.read_text(encoding="utf-8")).get("boot_id")
        mod.release()
        assert mod.try_acquire() is True
        second = json.loads(lock_path.read_text(encoding="utf-8")).get("boot_id")

        assert first
        assert first == second

    def test_lock_file_records_boot_id(self, tmp_path):
        """A freshly acquired lock carries the current boot id."""
        lock_path = tmp_path / "relay.pid"

        with patch.object(mod, "_current_boot_id", return_value="boot-now"):
            assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["boot_id"] == "boot-now"

    def test_reclaims_lock_from_previous_boot(self, tmp_path):
        """A lock from an earlier boot is stale even if its PID is alive now (PIDs are reused after reboot)."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "boot_id": "boot-before-reboot"}),
            encoding="utf-8",
        )

        with (
            patch.object(mod, "_current_boot_id", return_value="boot-after-reboot"),
            patch.object(mod, "_is_pid_alive", return_value=True) as alive,
        ):
            assert mod.try_acquire() is True

        alive.assert_not_called()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
        assert data["boot_id"] == "boot-after-reboot"

    def test_same_boot_live_holder_still_blocks(self, tmp_path):
        """Matching boot ids fall through to the normal liveness check."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "boot_id": "boot-now"}),
            encoding="utf-8",
        )

        with patch.object(mod, "_current_boot_id", return_value="boot-now"):
            assert mod.try_acquire() is False

    def test_same_boot_dead_holder_is_reclaimed(self, tmp_path):
        """Matching boot ids with a dead PID still reclaim as before."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text(
            json.dumps({"pid": 99999999, "boot_id": "boot-now"}),
            encoding="utf-8",
        )

        with (
            patch.object(mod, "_current_boot_id", return_value="boot-now"),
            patch.object(mod, "_is_pid_alive", return_value=False),
        ):
            assert mod.try_acquire() is True

    def test_legacy_lock_without_boot_id_uses_liveness(self, tmp_path):
        """Pre-1.1.0 lock files have no boot_id — behaviour must not regress."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

        with patch.object(mod, "_current_boot_id", return_value="boot-now"):
            assert mod.try_acquire() is False

    def test_no_boot_id_available_uses_liveness_only(self, tmp_path):
        """Without a readable boot id the lock degrades to plain pid liveness."""
        lock_path = tmp_path / "relay.pid"

        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "boot_id": "boot-before-reboot"}),
            encoding="utf-8",
        )

        with patch.object(mod, "_current_boot_id", return_value=None):
            assert mod.try_acquire() is False

    def test_lock_omits_boot_id_when_unavailable(self, tmp_path):
        """No boot id means no boot_id key — never a null that reads as a mismatch."""
        lock_path = tmp_path / "relay.pid"

        with patch.object(mod, "_current_boot_id", return_value=None):
            assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert "boot_id" not in data


def _a_later_holder_survives_release(tmp_path) -> bool:
    """The hold is cleared when a lock written after the release outlives another release()."""
    lock_path = tmp_path / "relay.pid"
    lock_path.write_text("held by someone else", encoding="utf-8")
    mod.release()
    return lock_path.exists()


class TestRelease:
    """Test relay lock release."""

    def test_removes_lock_file(self, tmp_path):
        """release() removes the lock file."""
        lock_path = tmp_path / "relay.pid"

        mod.try_acquire()
        assert lock_path.exists()

        mod.release()
        assert not lock_path.exists()

    def test_clears_held_lock_state(self, tmp_path):
        """release() clears the hold: a second release leaves a lock someone else has since written."""
        mod.try_acquire()
        mod.release()
        assert _a_later_holder_survives_release(tmp_path)

    def test_release_without_acquire_is_safe(self, tmp_path):
        """release() is a no-op when no lock is held: a viewer never deletes the holder's lock file."""
        lock_path = tmp_path / "relay.pid"
        lock_path.write_text("held by someone else", encoding="utf-8")

        with patch.object(mod, "logger") as log:
            assert mod.release() is None

        log.info.assert_not_called()
        log.warning.assert_not_called()
        assert lock_path.exists()

    def test_release_handles_already_deleted_file(self, tmp_path):
        """release() handles the case where the lock file was already deleted."""
        lock_path = tmp_path / "relay.pid"

        mod.try_acquire()
        lock_path.unlink()
        mod.release()
        assert _a_later_holder_survives_release(tmp_path)


class TestConcurrentViewers:
    """Concurrent monitor viewers: relay lock scoped, display never blocked."""

    def test_second_acquire_returns_false(self, tmp_path):
        """Second try_acquire() returns False when first holds the lock."""
        assert mod.try_acquire() is True
        assert mod.try_acquire() is False

    def test_release_then_reacquire(self, tmp_path):
        """After release(), another process can acquire the relay lock."""
        assert mod.try_acquire() is True
        mod.release()
        assert mod.try_acquire() is True

    def test_lock_path_is_relay_pid(self, monkeypatch):
        """Default lock file is relay.pid, not monitor.pid."""
        monkeypatch.setattr(mod, "_lock_path_override", None)
        assert mod.get_lock_path().name == "relay.pid"
