# =================== AIPass ====================
# Name: test_lock_ops.py
# Description: Tests for lock_ops handler — atomic lock file management
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

"""Tests for lock_ops handler — atomic lock file management."""

import os
from pathlib import Path
from unittest.mock import patch


# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.handlers.runner.lock_ops"


def _import_lock_ops():
    """Import lock_ops module and return it."""
    import aipass.flow.apps.handlers.runner.lock_ops as mod

    return mod


# ═══════════════════════════════════════════════════════════
# 1. try_create_lock
# ═══════════════════════════════════════════════════════════


class TestTryCreateLock:
    """Tests for try_create_lock — atomic O_CREAT|O_EXCL lock creation."""

    def test_creates_lock_file_successfully(self, tmp_path):
        """Should create lock file with current PID and return True."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        result = mod.try_create_lock(lock)
        assert result is True
        assert lock.exists()
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_returns_false_if_lock_exists(self, tmp_path):
        """Should return False when lock file already exists."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("12345", encoding="utf-8")
        result = mod.try_create_lock(lock)
        assert result is False

    def test_does_not_overwrite_existing_lock(self, tmp_path):
        """Existing lock content should be preserved on failure."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("99999", encoding="utf-8")
        mod.try_create_lock(lock)
        assert lock.read_text(encoding="utf-8") == "99999"


# ═══════════════════════════════════════════════════════════
# 2. is_lock_stale
# ═══════════════════════════════════════════════════════════


class TestIsLockStale:
    """Tests for is_lock_stale — dead process detection."""

    def test_lock_with_current_pid_is_not_stale(self, tmp_path):
        """Lock file holding current PID should not be considered stale."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        result = mod.is_lock_stale(lock)
        assert result is False

    def test_lock_with_dead_pid_is_stale(self, tmp_path):
        """Lock file holding a non-existent PID should be stale."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=False):
            result = mod.is_lock_stale(lock)
        assert result is True

    def test_lock_with_invalid_content_is_stale(self, tmp_path):
        """Lock file with non-integer content should be stale."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("not-a-pid", encoding="utf-8")
        result = mod.is_lock_stale(lock)
        assert result is True

    def test_lock_with_empty_content_is_stale(self, tmp_path):
        """Lock file with empty content should be stale."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("", encoding="utf-8")
        result = mod.is_lock_stale(lock)
        assert result is True

    def test_permission_error_treated_as_alive(self, tmp_path):
        """When _pid_alive says process exists, lock is valid (not stale)."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("1", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=True):
            result = mod.is_lock_stale(lock)
        assert result is False


# ═══════════════════════════════════════════════════════════
# 3. acquire_lock
# ═══════════════════════════════════════════════════════════


class TestAcquireLock:
    """Tests for acquire_lock — full lock acquisition with stale recovery."""

    def test_acquires_fresh_lock(self, tmp_path):
        """Should acquire lock when no lock file exists."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        result = mod.acquire_lock(lock)
        assert result is True
        assert lock.exists()

    def test_fails_when_another_process_holds_lock(self, tmp_path):
        """Should return False when lock held by a live process."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        result = mod.acquire_lock(lock)
        assert result is False

    def test_recovers_stale_lock(self, tmp_path):
        """Should recover a stale lock (dead PID) and acquire it."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=False):
            result = mod.acquire_lock(lock)
        assert result is True
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_fails_when_stale_lock_unlink_fails(self, tmp_path):
        """Should return False when stale lock can't be removed."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        with (
            patch(f"{_MOD}._pid_alive", return_value=False),
            patch.object(Path, "unlink", side_effect=OSError("permission denied")),
        ):
            result = mod.acquire_lock(lock)
        assert result is False

    def test_logs_json_operation_on_fresh_acquire(self, tmp_path, mock_json_handler):
        """Should log lock_acquired via json_handler on fresh lock."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        mod.acquire_lock(lock)
        mock_json_handler.assert_called()
        call_args = mock_json_handler.call_args
        assert call_args[0][0] == "lock_acquired"
        assert call_args[0][1]["lock_file"] == str(lock)

    def test_logs_stale_recovery_on_stale_acquire(self, tmp_path, mock_json_handler):
        """Should log stale_recovery=True when recovering stale lock."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=False):
            mod.acquire_lock(lock)
        call_args = mock_json_handler.call_args
        assert call_args[0][1]["stale_recovery"] is True


# ═══════════════════════════════════════════════════════════
# 4. release_lock
# ═══════════════════════════════════════════════════════════


class TestReleaseLock:
    """Tests for release_lock — lock file cleanup."""

    def test_removes_existing_lock(self, tmp_path):
        """Should remove the lock file."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        mod.release_lock(lock)
        assert not lock.exists()

    def test_no_error_when_lock_missing(self, tmp_path):
        """Should handle missing lock file gracefully (missing_ok=True).

        The graceful part is now READ: release_lock returns None and the file
        is still absent afterwards. A bare call asserted nothing - a
        release_lock that created the file, or returned an error object, passed
        this test unchanged.
        """
        mod = _import_lock_ops()
        lock = tmp_path / ".nonexistent.lock"
        assert not lock.exists()

        assert mod.release_lock(lock) is None
        assert not lock.exists()

    def test_logs_warning_on_os_error(self, tmp_path, mock_logger):
        """Should log warning when lock removal fails."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("12345", encoding="utf-8")
        with patch.object(Path, "unlink", side_effect=OSError("disk error")):
            assert mod.release_lock(lock) is None

        # THE WARNING IS THE SUBJECT, and it was never read. This unit takes
        # mock_logger, states "should log warning" in its docstring and then
        # checked neither - a release_lock that swallowed the OSError silently
        # passed it. The message is asserted through the real formatting the
        # handler uses: lazy %s args, not an f-string.
        mock_logger.warning.assert_called_once()
        args = mock_logger.warning.call_args.args
        assert "Failed to release lock file" in args[0]
        assert lock in args
        assert any("disk error" in str(arg) for arg in args)
