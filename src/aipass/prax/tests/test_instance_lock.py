# =================== AIPass ====================
# Name: test_instance_lock.py
# Description: Tests for the monitor single-instance lock
# Version: 2.0.0
# Created: 2026-07-10
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/monitoring/instance_lock.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_structure) — try_acquire's log_operation record, covered by that row
# seedgo: no-test-needed(log_level) — try_acquire's info lines, covered by that row

import os
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.monitoring import instance_lock as mod

needs_flock = pytest.mark.skipif(mod.fcntl is None, reason="no fcntl on this platform: the lock is a no-op")


@pytest.fixture(autouse=True)
def lock_world(monkeypatch, tmp_path):
    """Recorders doubled; lock file at tmp_path / "monitor.lock"; any hold dropped after each test."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(mod, "json_handler", MagicMock())
    monkeypatch.setattr(mod, "logger", MagicMock())
    monkeypatch.setattr(mod, "_lock_path_override", tmp_path / "monitor.lock")
    monkeypatch.setattr(mod, "_held_file", None)
    yield
    mod.release()


@needs_flock
class TestTryAcquire:
    """One holder at a time, decided by the kernel lock, not by the file's contents."""

    def test_creates_lock_file_with_pid(self, tmp_path):
        assert mod.try_acquire() is True
        assert (tmp_path / "monitor.lock").read_text(encoding="utf-8") == str(os.getpid())

    def test_second_acquire_returns_false(self):
        assert mod.try_acquire() is True
        assert mod.try_acquire() is False

    def test_release_then_reacquire(self):
        assert mod.try_acquire() is True
        mod.release()
        assert mod.try_acquire() is True

    def test_leftover_file_naming_a_live_pid_does_not_block(self, tmp_path):
        """A crashed holder leaves its file behind; with no lock held on it, the next monitor takes it."""
        (tmp_path / "monitor.lock").write_text(str(os.getppid()), encoding="utf-8")
        assert mod.try_acquire() is True

    def test_lock_held_by_another_process_blocks(self, tmp_path):
        lock_path = tmp_path / "monitor.lock"
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import fcntl,sys,time\n"
                "f=open(sys.argv[1],'a+',encoding='utf-8')\n"
                "fcntl.flock(f.fileno(),fcntl.LOCK_EX)\n"
                "print('held',flush=True)\n"
                "time.sleep(30)",
                str(lock_path),
            ],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            assert holder.stdout is not None
            assert holder.stdout.readline().strip() == "held"
            assert mod.try_acquire() is False
        finally:
            holder.kill()
            holder.wait()
        # The kernel drops a dead process's lock: no stale-lock judgement needed.
        assert mod.try_acquire() is True

    def test_creates_parent_directories(self, monkeypatch, tmp_path):
        lock_path = tmp_path / "nested" / "dir" / "monitor.lock"
        monkeypatch.setattr(mod, "_lock_path_override", lock_path)
        assert mod.try_acquire() is True
        assert lock_path.exists()


class TestRelease:
    def test_release_without_acquire_is_safe(self, monkeypatch, tmp_path):
        """A viewer that never held the lock leaves the holder's file alone."""
        lock_path = tmp_path / "monitor.lock"
        lock_path.write_text("held by someone else", encoding="utf-8")
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)
        assert mod.release() is None
        log.info.assert_not_called()
        assert lock_path.exists()


def test_default_lock_path_is_prax_json_monitor_lock(monkeypatch):
    """Under prax/prax_json/ (not apps/), and not named after the retired relay."""
    monkeypatch.setattr(mod, "_lock_path_override", None)
    path = mod.get_lock_path()
    assert path.name == "monitor.lock"
    assert path.parent.name == "prax_json"
    assert path.parent.parent.name == "prax"
