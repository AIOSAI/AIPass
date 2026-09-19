# =================== AIPass ====================
# Name: test_lock_ops.py
# Description: Tests for lock_ops handler — atomic lock file management
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-09-18
# =============================================

"""Tests for lock_ops handler — atomic lock file management."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.handlers.runner.lock_ops"

# Captured before any test patches os.open: the stand-in below delegates here.
_REAL_OS_OPEN = os.open


def _import_lock_ops():
    """Import lock_ops module and return it."""
    import aipass.flow.apps.handlers.runner.lock_ops as mod

    return mod


def _deny_exclusive_creates(lock_path: Path, denials: int | None, after: int = 0):
    """An os.open stand-in that answers the way Windows does mid-release.

    On Windows an exclusive create against a lock file another writer is still
    removing (delete-pending) raises PermissionError, not FileExistsError. Linux
    unlinks the name at once and can never show that, so it is manufactured
    here: exclusive creates of ``lock_path`` pass through for the first
    ``after`` calls, are then denied ``denials`` times (None = never clears),
    then delegate to the real os.open. Every other open is untouched.

    Returns:
        (side_effect, attempts, raised): attempts counts every exclusive create
        of lock_path; raised holds each PermissionError handed out.
    """
    attempts: list[int] = []
    raised: list[PermissionError] = []

    def fake_open(path, flags, *args, **kwargs):
        if flags & os.O_EXCL and str(path) == str(lock_path):
            attempts.append(len(attempts) + 1)
            index = len(attempts) - after
            if index > 0 and (denials is None or index <= denials):
                denial = PermissionError(13, "Access is denied")
                raised.append(denial)
                raise denial
        return _REAL_OS_OPEN(path, flags, *args, **kwargs)

    return fake_open, attempts, raised


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

    def test_delete_pending_denial_is_retried_and_lock_lands(self, tmp_path):
        """A Windows delete-pending PermissionError is a held lock: wait, retry, win.

        It used to escape try_create_lock on the first denial and crash the
        detached post-close runner, leaving the just-closed plan unprocessed.
        """
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=1)

        with patch(f"{_MOD}.os.open", side_effect=fake_open), patch("time.sleep") as sleep:
            result = mod.try_create_lock(lock)

        assert result is True
        assert len(attempts) == 2
        sleep.assert_called_once()
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_denial_that_never_clears_raises_at_the_budget(self, tmp_path):
        """A denial past the budget is a real permissions problem: raise it, chained.

        Not False: acquire_lock's callers read False as "another instance is
        already running", which would be a lie. Not forever: exactly the
        budget of attempts, then the last denial surfaces as the cause.
        """
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        fake_open, attempts, raised = _deny_exclusive_creates(lock, denials=None)

        with (
            patch(f"{_MOD}.os.open", side_effect=fake_open),
            patch("time.sleep"),
            pytest.raises(PermissionError) as excinfo,
        ):
            mod.try_create_lock(lock)

        assert str(lock) in str(excinfo.value)
        assert excinfo.value.__cause__ is raised[-1]
        assert len(attempts) == mod._CREATE_RETRIES
        assert mod._CREATE_RETRIES > 1
        assert f"{mod._CREATE_RETRIES} attempts" in str(excinfo.value)
        assert not lock.exists()

    def test_file_exists_still_returns_false_at_once(self, tmp_path):
        """FileExistsError is NOT retried: acquire_lock's stale check reads the holder next."""
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("12345", encoding="utf-8")
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=0)

        with patch(f"{_MOD}.os.open", side_effect=fake_open), patch("time.sleep") as sleep:
            result = mod.try_create_lock(lock)

        assert result is False
        assert len(attempts) == 1
        sleep.assert_not_called()


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

    def test_delete_pending_after_stale_unlink_still_acquires(self, tmp_path):
        """The re-create right after unlinking a stale lock is where Windows says
        delete-pending. It used to escape acquire_lock raw; now it waits and wins.
        """
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        # First create meets the stale file (real FileExistsError); the second,
        # just after the unlink, is denied once as Windows would.
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=1, after=1)

        with (
            patch(f"{_MOD}._pid_alive", return_value=False),
            patch(f"{_MOD}.os.open", side_effect=fake_open),
            patch("time.sleep"),
        ):
            result = mod.acquire_lock(lock)

        assert result is True
        assert len(attempts) == 3
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_denial_that_never_clears_raises_instead_of_returning_false(self, tmp_path):
        """False means "another instance is running" to every caller. A lock that
        can never be created is not that, so acquire_lock lets the chained
        PermissionError through after the budget.
        """
        mod = _import_lock_ops()
        lock = tmp_path / ".test.lock"
        fake_open, attempts, raised = _deny_exclusive_creates(lock, denials=None)

        with (
            patch(f"{_MOD}.os.open", side_effect=fake_open),
            patch("time.sleep"),
            pytest.raises(PermissionError) as excinfo,
        ):
            mod.acquire_lock(lock)

        assert str(lock) in str(excinfo.value)
        assert excinfo.value.__cause__ is raised[-1]
        assert len(attempts) == mod._CREATE_RETRIES


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
