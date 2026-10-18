# =================== AIPass ====================
# Name: test_lock_ops.py
# Description: Tests for lock_ops handler — atomic lock file management
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/runner/lock_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that lock_ops.py parses and imports

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.flow.apps.handlers.runner import lock_ops

_MOD = "aipass.flow.apps.handlers.runner.lock_ops"


def _unlink_answer(path: Path) -> OSError | None:
    """Unlink ``path`` with the test's own hands and keep what the platform answers."""
    try:
        path.unlink()
    except OSError as exc:
        return exc
    return None


def _deny_exclusive_creates(lock_path: Path, denials: int | None, after: int = 0):
    """A stand-in for lock_ops' _create_exclusive seam that answers the way
    Windows does mid-release.

    Windows delete-pending raises PermissionError, which Linux can never show. Creates of
    ``lock_path`` pass for ``after`` calls, are denied ``denials`` times (None = forever), then pass.
    """
    attempts: list[int] = []
    raised: list[PermissionError] = []

    def fake_create(path):
        if str(path) == str(lock_path):
            attempts.append(len(attempts) + 1)
            index = len(attempts) - after
            if index > 0 and (denials is None or index <= denials):
                denial = PermissionError(13, "Access is denied")
                raised.append(denial)
                raise denial
        return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    return fake_create, attempts, raised


def _age(lock: Path) -> None:
    """Set the lock's mtime an hour back, well past any unreadable-lock grace."""
    old = time.time() - 3600
    os.utime(lock, (old, old))


class TestTryCreateLock:
    """Tests for try_create_lock — atomic O_CREAT|O_EXCL lock creation."""

    def test_creates_lock_file_successfully(self, tmp_path):
        """Should create lock file with current PID and return True."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        result = mod.try_create_lock(lock)
        assert result is True
        assert lock.exists()
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_returns_false_if_lock_exists(self, tmp_path):
        """Should return False when lock file already exists."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("12345", encoding="utf-8")
        result = mod.try_create_lock(lock)
        assert result is False

    def test_does_not_overwrite_existing_lock(self, tmp_path):
        """Existing lock content should be preserved on failure."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("99999", encoding="utf-8")
        mod.try_create_lock(lock)
        assert lock.read_text(encoding="utf-8") == "99999"

    def test_delete_pending_denial_is_retried_and_lock_lands(self, tmp_path):
        """A Windows delete-pending PermissionError is a held lock: wait, retry, win."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=1)

        with patch(f"{_MOD}._create_exclusive", side_effect=fake_open), patch(f"{_MOD}._sleep") as sleep:
            try:
                result = mod.try_create_lock(lock)
            except PermissionError as exc:
                raise AssertionError(f"the lock did not land: {exc}") from exc

        assert result is True
        assert len(attempts) == 2
        sleep.assert_called_once()
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_denial_that_never_clears_raises_at_the_budget(self, tmp_path):
        """A denial past the budget is a real permissions problem: raise it, chained.

        Not False: callers read False as "another instance is already running".
        """
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        fake_open, attempts, raised = _deny_exclusive_creates(lock, denials=None)

        with (
            patch(f"{_MOD}._create_exclusive", side_effect=fake_open),
            patch(f"{_MOD}._sleep") as sleep,
            pytest.raises(PermissionError) as excinfo,
        ):
            mod.try_create_lock(lock)

        assert str(lock) in str(excinfo.value)
        assert excinfo.value.__cause__ is raised[-1]
        assert len(attempts) == mod._CREATE_RETRIES
        assert sleep.call_count == mod._CREATE_RETRIES
        assert mod._CREATE_RETRIES > 1
        assert f"{mod._CREATE_RETRIES} attempts" in str(excinfo.value)
        assert not lock.exists()
        # Positive first delay, doubling per denial, sum reported as the wait.
        delays = [c.args[0] for c in sleep.call_args_list]
        assert delays[0] > 0
        assert all(later == 2 * earlier for earlier, later in zip(delays, delays[1:]))
        assert f"({sum(delays):.2f}s waited)" in str(excinfo.value)

    def test_file_exists_still_returns_false_at_once(self, tmp_path):
        """FileExistsError is NOT retried: acquire_lock's stale check reads the holder next."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("12345", encoding="utf-8")

        with patch(f"{_MOD}._sleep") as sleep:
            try:
                result = mod.try_create_lock(lock)
            except PermissionError as exc:
                raise AssertionError(f"a held lock was retried to the budget: {exc}") from exc

        assert result is False
        sleep.assert_not_called()
        assert lock.read_text(encoding="utf-8") == "12345"


class TestIsLockStale:
    """Tests for is_lock_stale — dead process detection."""

    def test_lock_with_current_pid_is_not_stale(self, tmp_path):
        """Lock file holding current PID should not be considered stale."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        result = mod.is_lock_stale(lock)
        assert result is False

    def test_lock_with_dead_pid_is_stale(self, tmp_path):
        """Lock file holding a non-existent PID should be stale."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=False):
            result = mod.is_lock_stale(lock)
        assert result is True

    def test_lock_with_invalid_content_is_stale(self, tmp_path):
        """Lock file with non-integer content, older than the grace, should be stale."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("not-a-pid", encoding="utf-8")
        _age(lock)
        result = mod.is_lock_stale(lock)
        assert result is True

    def test_lock_with_empty_content_is_stale(self, tmp_path):
        """An empty lock older than the grace was left by a writer that died mid-create: stale."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("", encoding="utf-8")
        _age(lock)
        result = mod.is_lock_stale(lock)
        assert result is True

    def test_fresh_empty_lock_is_held(self, tmp_path):
        """The empty-lock race: a holder has done O_EXCL but not yet written its pid.

        Mutant: `if age < _UNREADABLE_LOCK_GRACE:` -> `if False:` reddens this.
        """
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("", encoding="utf-8")
        assert mod.is_lock_stale(lock) is False
        assert lock.exists()

    def test_fresh_garbage_lock_is_held(self, tmp_path):
        """Non-integer content that is still fresh is held, not taken over.

        Mutant: `if age < _UNREADABLE_LOCK_GRACE:` -> `if age < 0:` reddens this.
        """
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("not-a-pid", encoding="utf-8")
        assert mod.is_lock_stale(lock) is False

    def test_vanished_lock_is_stale(self, tmp_path):
        """A lock gone before it could be read was released: the caller may take over."""
        mod = lock_ops
        lock = tmp_path / ".gone.lock"
        assert mod.is_lock_stale(lock) is True

    def test_unreadable_lock_raises_instead_of_reading_stale(self, tmp_path):
        """A lock that exists but cannot be read is not proof its holder is dead.

        Which OSError is the platform's choice; only FileNotFoundError (meaning stale) must not come.
        """
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.mkdir()
        with pytest.raises(OSError) as excinfo:
            mod.is_lock_stale(lock)
        assert not isinstance(excinfo.value, FileNotFoundError)
        assert lock.is_dir()

    def test_permission_error_treated_as_alive(self, tmp_path):
        """When _pid_alive says process exists, lock is valid (not stale)."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("1", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=True):
            result = mod.is_lock_stale(lock)
        assert result is False


class TestAcquireLock:
    """Tests for acquire_lock — full lock acquisition with stale recovery."""

    def test_acquires_fresh_lock(self, tmp_path):
        """Should acquire lock when no lock file exists."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        result = mod.acquire_lock(lock)
        assert result is True
        assert lock.exists()

    def test_fails_when_another_process_holds_lock(self, tmp_path):
        """Should return False when lock held by a live process."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        result = mod.acquire_lock(lock)
        assert result is False

    def test_recovers_stale_lock(self, tmp_path):
        """Should recover a stale lock (dead PID) and acquire it."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=False):
            result = mod.acquire_lock(lock)
        assert result is True
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_raises_when_stale_lock_unlink_fails(self, tmp_path):
        """A stale lock that cannot be removed raises; it is not reported as held.

        Whether a read-only dir refuses an unlink is the platform's choice (not for Windows or root),
        so a probe unlink decides which answer the product owes.
        """
        mod = lock_ops
        home = tmp_path / "ro"
        home.mkdir()
        lock = home / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        probe = home / "probe"
        probe.write_text("", encoding="utf-8")
        home.chmod(0o555)
        try:
            refusal = _unlink_answer(probe)
            with patch(f"{_MOD}._pid_alive", return_value=False):
                if refusal is not None:
                    with pytest.raises(OSError) as excinfo:
                        mod.acquire_lock(lock)
                    assert type(excinfo.value) is type(refusal)
                    assert lock.read_text(encoding="utf-8") == "999999999"
                else:
                    assert mod.acquire_lock(lock) is True
                    assert lock.read_text(encoding="utf-8") == str(os.getpid())
        finally:
            home.chmod(0o755)

    def test_lock_released_between_the_read_and_the_unlink_is_taken(self, tmp_path):
        """The holder lets go after the stale check read its lock and before the unlink.

        Mutant: `lock_file.unlink(missing_ok=True)` -> `lock_file.unlink()` reddens this.
        """
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")

        def stale_then_released(path: Path) -> bool:
            path.unlink()
            return True

        with patch(f"{_MOD}.is_lock_stale", side_effect=stale_then_released) as stale_check:
            try:
                acquired = mod.acquire_lock(lock)
            except OSError as exc:
                pytest.fail(f"acquire_lock raised {exc!r} for a lock released before its unlink")

        stale_check.assert_called_once_with(lock)
        assert acquired is True
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_fresh_empty_lock_is_not_unlinked(self, tmp_path):
        """A holder between O_EXCL and its pid write keeps its lock: acquire says held."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("", encoding="utf-8")
        before = lock.stat().st_ino
        assert mod.acquire_lock(lock) is False
        assert lock.read_text(encoding="utf-8") == ""
        assert lock.stat().st_ino == before

    def test_logs_json_operation_on_fresh_acquire(self, tmp_path, mock_json_handler):
        """Should log lock_acquired via json_handler on fresh lock."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        mod.acquire_lock(lock)
        mock_json_handler.assert_called()
        call_args = mock_json_handler.call_args
        assert call_args[0][0] == "lock_acquired"
        assert call_args[0][1]["lock_file"] == str(lock)

    def test_logs_stale_recovery_on_stale_acquire(self, tmp_path, mock_json_handler):
        """Should log stale_recovery=True when recovering stale lock."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        with patch(f"{_MOD}._pid_alive", return_value=False):
            mod.acquire_lock(lock)
        call_args = mock_json_handler.call_args
        assert call_args[0][1]["stale_recovery"] is True

    def test_delete_pending_after_stale_unlink_still_acquires(self, tmp_path):
        """The re-create right after unlinking a stale lock is where Windows says
        delete-pending; it must wait and win.
        """
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text("999999999", encoding="utf-8")
        # First create meets the stale file; the second, after the unlink, is denied once.
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=1, after=1)

        with (
            patch(f"{_MOD}._pid_alive", return_value=False),
            patch(f"{_MOD}._create_exclusive", side_effect=fake_open),
            patch(f"{_MOD}._sleep") as sleep,
        ):
            try:
                result = mod.acquire_lock(lock)
            except PermissionError as exc:
                raise AssertionError(f"the lock did not land: {exc}") from exc

        assert result is True
        assert len(attempts) == 3
        sleep.assert_called_once()
        assert lock.read_text(encoding="utf-8") == str(os.getpid())

    def test_denial_that_never_clears_raises_instead_of_returning_false(self, tmp_path):
        """False means "another instance is running" to every caller. A lock that
        can never be created raises the chained PermissionError instead.
        """
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        fake_open, attempts, raised = _deny_exclusive_creates(lock, denials=None)

        with (
            patch(f"{_MOD}._create_exclusive", side_effect=fake_open),
            patch(f"{_MOD}._sleep") as sleep,
            pytest.raises(PermissionError) as excinfo,
        ):
            mod.acquire_lock(lock)

        assert str(lock) in str(excinfo.value)
        assert excinfo.value.__cause__ is raised[-1]
        assert len(attempts) == mod._CREATE_RETRIES
        assert sleep.call_count == mod._CREATE_RETRIES


class TestReleaseLock:
    """Tests for release_lock — lock file cleanup."""

    def test_removes_existing_lock(self, tmp_path):
        """Should remove the lock file."""
        mod = lock_ops
        lock = tmp_path / ".test.lock"
        lock.write_text(str(os.getpid()), encoding="utf-8")
        mod.release_lock(lock)
        assert not lock.exists()

    def test_no_error_when_lock_missing(self, tmp_path):
        """Should handle missing lock file gracefully (missing_ok=True)."""
        mod = lock_ops
        lock = tmp_path / ".nonexistent.lock"
        assert not lock.exists()

        assert mod.release_lock(lock) is None
        assert not lock.exists()

    def test_logs_warning_on_os_error(self, tmp_path, mock_logger):
        """Should log warning when lock removal fails."""
        mod = lock_ops
        # A directory at the lock path makes unlink raise a real OSError.
        lock = tmp_path / ".test.lock"
        lock.mkdir()
        assert mod.release_lock(lock) is None
        assert lock.is_dir()

        # The handler logs with lazy %s args, not an f-string.
        mock_logger.warning.assert_called_once()
        args = mock_logger.warning.call_args.args
        assert "Failed to release lock file" in args[0]
        assert lock in args
        assert any(isinstance(arg, OSError) for arg in args)
