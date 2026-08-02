# =================== AIPass ====================
# Name: test_instance_lock.py
# Description: Tests for the monitor single-instance lock
# Version: 1.1.0
# Created: 2026-07-10
# Modified: 2026-08-02
# =============================================

"""Tests for apps/handlers/monitoring/instance_lock.py

Covers:
- _is_pid_alive() cross-platform liveness check
- try_acquire() creates lock, returns False for live duplicate, reclaims stale
- _current_boot_id() + cross-boot reclaim (PID reuse after reboot)
- release() removes lock file on clean shutdown
- Concurrent viewer: relay lock scoped to TG sends, never blocks display
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_HANDLER_MOCKS = {
    "aipass.prax.apps.handlers.json": MagicMock(),
    "aipass.prax.apps.handlers.json.json_handler": MagicMock(),
}


def _import_lock():
    """Import (or reload) instance_lock with handler mocks."""
    fresh = {k: MagicMock() for k in _HANDLER_MOCKS}
    with patch.dict(sys.modules, fresh):
        import importlib

        if "aipass.prax.apps.handlers.monitoring.instance_lock" in sys.modules:
            mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.monitoring.instance_lock"])
        else:
            mod = importlib.import_module("aipass.prax.apps.handlers.monitoring.instance_lock")
        return mod


class TestIsPidAlive:
    """Test cross-platform PID liveness check."""

    def test_live_pid_returns_true_posix(self):
        """os.kill(pid, 0) success means alive on POSIX."""
        mod = _import_lock()
        with patch("sys.platform", "linux"), patch("os.kill"):
            assert mod._is_pid_alive(os.getpid()) is True

    def test_dead_pid_returns_false(self):
        """Non-existent PID returns False on POSIX."""
        mod = _import_lock()
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=ProcessLookupError):
            assert mod._is_pid_alive(99999999) is False

    def test_permission_error_means_alive(self):
        """PermissionError means the process exists but is owned by another user."""
        mod = _import_lock()
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=PermissionError):
            assert mod._is_pid_alive(1) is True

    def test_generic_oserror_returns_false(self):
        """Other OSError returns False."""
        mod = _import_lock()
        with patch("sys.platform", "linux"), patch("os.kill", side_effect=OSError(99, "Unknown")):
            assert mod._is_pid_alive(12345) is False

    def test_windows_delegates_to_pid_alive_windows(self):
        """On win32, _is_pid_alive delegates to _pid_alive_windows."""
        mod = _import_lock()
        with (
            patch("sys.platform", "win32"),
            patch.object(mod, "_pid_alive_windows", return_value=True) as mock_win,
        ):
            assert mod._is_pid_alive(1234) is True
            mock_win.assert_called_once_with(1234)

    def test_windows_dead_pid(self):
        """On win32, dead PID returns False via _pid_alive_windows."""
        mod = _import_lock()
        with (
            patch("sys.platform", "win32"),
            patch.object(mod, "_pid_alive_windows", return_value=False),
        ):
            assert mod._is_pid_alive(99999999) is False

    def test_windows_ctypes_failure_assumes_alive(self):
        """On win32, if ctypes fails, assume the process is alive (safe default)."""
        mod = _import_lock()
        with (
            patch("sys.platform", "win32"),
            patch.object(mod, "_pid_alive_windows", side_effect=OSError("ctypes failed")),
        ):
            assert mod._is_pid_alive(1234) is True


class TestTryAcquire:
    """Test relay lock acquisition."""

    def test_creates_lock_file(self, tmp_path):
        """try_acquire() creates a lock file with the current PID."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        assert mod.try_acquire() is True

        assert lock_path.exists()
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()

    def test_returns_false_when_live_holder(self, tmp_path):
        """try_acquire() returns False when another live process holds the lock."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

        assert mod.try_acquire() is False

    def test_reclaims_stale_lock(self, tmp_path):
        """try_acquire() reclaims the lock when the recorded PID is dead."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        lock_path.write_text(json.dumps({"pid": 99999999}), encoding="utf-8")

        with patch.object(mod, "_is_pid_alive", return_value=False):
            assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()

    def test_reclaims_corrupt_lock_file(self, tmp_path):
        """try_acquire() overwrites a corrupt lock file."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        lock_path.write_text("{corrupt json", encoding="utf-8")

        assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()

    def test_creates_parent_directories(self, tmp_path):
        """try_acquire() creates parent directories if they don't exist."""
        mod = _import_lock()
        lock_path = tmp_path / "nested" / "dir" / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        assert mod.try_acquire() is True
        assert lock_path.exists()


class TestBootIdentity:
    """Test cross-boot staleness detection (relay.pid outliving a reboot)."""

    def test_current_boot_id_returns_none_when_unreadable(self):
        """Platforms without /proc get None rather than an exception."""
        mod = _import_lock()
        with patch("pathlib.Path.read_text", side_effect=OSError("no /proc")):
            assert mod._current_boot_id() is None

    @pytest.mark.skipif(sys.platform == "win32", reason="/proc is Linux-only")
    def test_current_boot_id_reads_proc_on_linux(self):
        """Linux exposes a non-empty boot id that is stable within a boot."""
        mod = _import_lock()
        boot_id = mod._current_boot_id()
        assert boot_id
        assert boot_id == mod._current_boot_id()

    def test_lock_file_records_boot_id(self, tmp_path):
        """A freshly acquired lock carries the current boot id."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        with patch.object(mod, "_current_boot_id", return_value="boot-now"):
            assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["boot_id"] == "boot-now"

    def test_reclaims_lock_from_previous_boot(self, tmp_path):
        """A lock from an earlier boot is stale even if its PID is alive now.

        This is the 2026-07-31 failure: relay.pid survived a reboot holding
        PID 1567, which the new boot handed to an unrelated early process.
        Liveness said "held", so the relay ran viewer-only for 1h51m.
        """
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

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
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "boot_id": "boot-now"}),
            encoding="utf-8",
        )

        with patch.object(mod, "_current_boot_id", return_value="boot-now"):
            assert mod.try_acquire() is False

    def test_same_boot_dead_holder_is_reclaimed(self, tmp_path):
        """Matching boot ids with a dead PID still reclaim as before."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

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
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

        with patch.object(mod, "_current_boot_id", return_value="boot-now"):
            assert mod.try_acquire() is False

    def test_no_boot_id_available_uses_liveness_only(self, tmp_path):
        """Without a readable boot id the lock degrades to plain pid liveness."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "boot_id": "boot-before-reboot"}),
            encoding="utf-8",
        )

        with patch.object(mod, "_current_boot_id", return_value=None):
            assert mod.try_acquire() is False

    def test_lock_omits_boot_id_when_unavailable(self, tmp_path):
        """No boot id means no boot_id key — never a null that reads as a mismatch."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        with patch.object(mod, "_current_boot_id", return_value=None):
            assert mod.try_acquire() is True

        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert "boot_id" not in data


class TestRelease:
    """Test relay lock release."""

    def test_removes_lock_file(self, tmp_path):
        """release() removes the lock file."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        mod.try_acquire()
        assert lock_path.exists()

        mod.release()
        assert not lock_path.exists()

    def test_clears_held_lock_state(self, tmp_path):
        """release() clears the _held_lock global."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        mod.try_acquire()
        mod.release()
        assert mod._held_lock is None

    def test_release_without_acquire_is_safe(self):
        """release() is a no-op when no lock is held."""
        mod = _import_lock()
        setattr(mod, "_held_lock", None)
        mod.release()

    def test_release_handles_already_deleted_file(self, tmp_path):
        """release() handles the case where the lock file was already deleted."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        mod.try_acquire()
        lock_path.unlink()
        mod.release()
        assert mod._held_lock is None


class TestConcurrentViewers:
    """Concurrent monitor viewers: relay lock scoped, display never blocked."""

    def test_second_acquire_returns_false(self, tmp_path):
        """Second try_acquire() returns False when first holds the lock."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        assert mod.try_acquire() is True
        assert mod.try_acquire() is False

    def test_release_then_reacquire(self, tmp_path):
        """After release(), another process can acquire the relay lock."""
        mod = _import_lock()
        lock_path = tmp_path / "relay.pid"
        setattr(mod, "_lock_path_override", lock_path)

        assert mod.try_acquire() is True
        mod.release()
        assert mod.try_acquire() is True

    def test_lock_path_is_relay_pid(self):
        """Default lock file is relay.pid, not monitor.pid."""
        mod = _import_lock()
        setattr(mod, "_lock_path_override", None)
        assert mod.get_lock_path().name == "relay.pid"
