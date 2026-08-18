# =================== AIPass ====================
# Name: test_json_durability.py
# Description: Cross-platform durability pins for config.py's write + lock helpers
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Durability pins for atomic_write_json and json_file_lock.

Windows CI ran this tree to completion for the first time on 2026-08-18 and
found what a POSIX-only green run cannot: `json_file_lock` yielded WITHOUT a
lock on win32, so the read-modify-write serialisation proven here every day
did not exist there at all. Reported by devpulse (70a10016) with the measured
shape — increment_counter reached 26 of 100 on Windows.

These pins exercise the win32 branch FROM LINUX by injecting a fake msvcrt, so
the platform this branch cannot run on is still covered by construction.
"""

import sys
import pytest

from aipass.trigger.apps import config


class _FakeMsvcrt:
    """Stand-in for the win32 locking primitive, recording every call."""

    LK_NBLCK = 1
    LK_UNLCK = 0

    def __init__(self, fail_times: int = 0):
        self.calls: list = []
        self._fail_times = fail_times

    def locking(self, fileno, mode, nbytes):
        self.calls.append((mode, nbytes))
        if mode == self.LK_NBLCK and self._fail_times > 0:
            self._fail_times -= 1
            raise OSError(36, "Resource deadlock avoided")


@pytest.fixture
def win32(monkeypatch):
    """Make config believe it is running on Windows, with a fake msvcrt."""
    fake = _FakeMsvcrt()
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    return fake


class TestWindowsLockIsRealNotSkipped:
    """A lock one platform walks past is not a lock. The old code read
    `if sys.platform == "win32": yield` — every caller believed it was
    serialised and none of them were.
    """

    def test_win32_acquires_and_releases_a_real_lock(self, win32, tmp_path):
        """The win32 path calls the OS primitive, both ways."""
        with config.json_file_lock(tmp_path / "doc.json"):
            assert (win32.LK_NBLCK, 1) in win32.calls, "no lock taken on win32"
        assert win32.calls[-1] == (win32.LK_UNLCK, 1), "lock never released"

    def test_win32_retries_a_contended_lock_then_succeeds(self, monkeypatch, tmp_path):
        """A lock held by someone else is waited for, not walked past."""
        fake = _FakeMsvcrt(fail_times=3)
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        sleeps: list = []
        monkeypatch.setattr(config.time, "sleep", lambda s: sleeps.append(s))

        with config.json_file_lock(tmp_path / "doc.json"):
            pass

        assert sleeps == [config._LOCK_BACKOFF_SECONDS] * 3
        assert fake.calls.count((fake.LK_NBLCK, 1)) == 4

    def test_win32_refuses_rather_than_running_unlocked(self, monkeypatch, tmp_path):
        """Exhausting the retries RAISES. Silent data loss is the one forbidden outcome."""
        fake = _FakeMsvcrt(fail_times=config._LOCK_ATTEMPTS + 5)
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        monkeypatch.setattr(config.time, "sleep", lambda _s: None)

        entered = False
        with pytest.raises(OSError):
            with config.json_file_lock(tmp_path / "doc.json"):
                entered = True
        assert entered is False, "body ran without the lock"

    def test_no_platform_yields_without_locking(self):
        """No branch of the lock may reach `yield` without taking a lock.

        Pinned on the source because the defect was a MISSING call, and no
        behavioural assertion on Linux can see a win32 branch that skips one.
        """
        import inspect

        source = inspect.getsource(config.json_file_lock)
        assert "single-user typical" not in source, "the silent win32 skip is back"


class TestReplaceSurvivesWindowsSharingViolations:
    """os.replace raises PermissionError under AV/indexer locks on Windows;
    one stuck replace ate the whole CI lane at the 45-minute wall. Bounded
    retry, PermissionError only, exhaustion raises. Mirrors the fleet helper.
    """

    def test_success_after_transient_permission_errors(self, monkeypatch, tmp_path):
        """A replace blocked twice still lands."""
        attempts = {"n": 0}

        def flaky(src, dst):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise PermissionError("sharing violation")

        monkeypatch.setattr(config.os, "replace", flaky)
        monkeypatch.setattr(config.time, "sleep", lambda _s: None)

        config.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"))
        assert attempts["n"] == 3

    def test_exhaustion_raises_at_exactly_the_declared_attempts(self, monkeypatch, tmp_path):
        """Bounded, and the bound is the declared constant."""
        attempts = {"n": 0}

        def always_blocked(src, dst):
            attempts["n"] += 1
            raise PermissionError("sharing violation")

        monkeypatch.setattr(config.os, "replace", always_blocked)
        monkeypatch.setattr(config.time, "sleep", lambda _s: None)

        with pytest.raises(PermissionError):
            config.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"))
        assert attempts["n"] == config._REPLACE_ATTEMPTS

    def test_foreign_oserror_propagates_on_the_first_attempt(self, monkeypatch, tmp_path):
        """Only sharing violations are retried — a real failure is not hidden."""
        attempts = {"n": 0}

        def wrong_disk(src, dst):
            attempts["n"] += 1
            raise OSError(18, "Invalid cross-device link")

        monkeypatch.setattr(config.os, "replace", wrong_disk)

        with pytest.raises(OSError):
            config.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"))
        assert attempts["n"] == 1

    def test_the_backoff_is_a_wait_not_a_busy_spin(self, monkeypatch, tmp_path):
        """Deleting the sleep leaves a spin that passes every other pin here.

        Counting the sleeps pins the wait without asserting on wall-clock time,
        so it cannot flake on a loaded runner.
        """
        monkeypatch.setattr(config.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError()))
        sleeps: list = []
        monkeypatch.setattr(config.time, "sleep", lambda s: sleeps.append(s))

        with pytest.raises(PermissionError):
            config.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"))

        assert sleeps == [config._REPLACE_BACKOFF_SECONDS] * (config._REPLACE_ATTEMPTS - 1)

    def test_atomic_write_routes_through_the_retry(self, monkeypatch, tmp_path):
        """The public writer uses the guarded move, not a bare os.replace."""
        seen = {"used": False}
        real = config.replace_with_retry

        def spy(src, dst):
            seen["used"] = True
            real(src, dst)

        monkeypatch.setattr(config, "replace_with_retry", spy)
        config.atomic_write_json(tmp_path / "doc.json", {"ok": True})

        assert seen["used"] is True
