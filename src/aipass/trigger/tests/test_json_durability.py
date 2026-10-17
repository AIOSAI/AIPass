# =================== AIPass ====================
# Name: test_json_durability.py
# Description: Cross-platform durability pins for config.py's write + lock helpers
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-10-17
# =============================================

"""Tests for apps/config.py's durability helpers: atomic_write_json, json_file_lock and the retry reads."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — _acquire_lock_win32 against a real Windows host; driven here by injection
# seedgo: no-test-needed(covered_elsewhere) — medic state's read-modify-writes over json_file_lock, test_medic_state.py

import os
import sys
import threading
from pathlib import Path

import pytest

from aipass.trigger.apps import config

# Written here, not read off config's private constants: a test that reads the
# constant moves with it, so a changed bound passes unseen.
REPLACE_ATTEMPTS = 40
REPLACE_BACKOFF_SECONDS = 0.005
LOCK_ATTEMPTS = 100
LOCK_BACKOFF_SECONDS = 0.05


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
def win32():
    """A fake msvcrt, handed to the lock through its seam with platform "win32"."""
    return _FakeMsvcrt()


class TestWindowsLockIsRealNotSkipped:
    """A lock one platform walks past is not a lock. The old code read
    `if sys.platform == "win32": yield`, and every caller believed it was serialised."""

    def test_win32_acquires_and_releases_a_real_lock(self, win32, tmp_path):
        """The win32 path calls the OS primitive, both ways."""
        with config.json_file_lock(tmp_path / "doc.json", platform="win32", msvcrt_module=win32):
            assert (win32.LK_NBLCK, 1) in win32.calls, "no lock taken on win32"
        assert win32.calls[-1] == (win32.LK_UNLCK, 1), "lock never released"

    def test_win32_retries_a_contended_lock_then_succeeds(self, tmp_path):
        """A lock held by someone else is waited for, not walked past."""
        fake = _FakeMsvcrt(fail_times=3)
        sleeps: list = []

        with config.json_file_lock(tmp_path / "doc.json", platform="win32", msvcrt_module=fake, sleep_fn=sleeps.append):
            pass

        assert sleeps == [LOCK_BACKOFF_SECONDS] * 3
        assert fake.calls.count((fake.LK_NBLCK, 1)) == 4

    def test_win32_refuses_rather_than_running_unlocked(self, tmp_path):
        """Exhausting the retries RAISES after a bounded wait. Silent data loss is the one forbidden outcome."""
        fake = _FakeMsvcrt(fail_times=LOCK_ATTEMPTS + 5)
        sleeps: list = []

        entered = False
        with pytest.raises(OSError):
            with config.json_file_lock(
                tmp_path / "doc.json", platform="win32", msvcrt_module=fake, sleep_fn=sleeps.append
            ):
                entered = True
        assert entered is False, "body ran without the lock"
        assert sleeps == [LOCK_BACKOFF_SECONDS] * (LOCK_ATTEMPTS - 1)

    def test_no_platform_yields_without_locking(self):
        """No branch of the lock may reach `yield` without taking a lock.

        Pinned on the source: no Linux assertion can see a win32 branch that skips the call."""
        import inspect

        source = inspect.getsource(config.json_file_lock)
        assert "single-user typical" not in source, "the silent win32 skip is back"


class TestReplaceSurvivesWindowsSharingViolations:
    """os.replace raises PermissionError under AV/indexer locks on Windows;
    bounded retry, PermissionError only, exhaustion raises. Mirrors the fleet helper."""

    def test_success_after_transient_permission_errors(self, monkeypatch, tmp_path):
        """A replace blocked twice still lands, waiting once per refusal (mutant: a wait after success)."""
        attempts = {"n": 0}

        def flaky(src, dst):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise PermissionError("sharing violation")

        sleeps: list = []

        config.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"), replace_fn=flaky, sleep_fn=sleeps.append)
        assert attempts["n"] == 3
        assert sleeps == [REPLACE_BACKOFF_SECONDS] * 2

    def test_exhaustion_raises_at_exactly_the_declared_attempts(self, monkeypatch, tmp_path):
        """Bounded, and the bound is the declared constant."""
        attempts = {"n": 0}

        def always_blocked(src, dst):
            attempts["n"] += 1
            raise PermissionError("sharing violation")

        with pytest.raises(PermissionError):
            config.replace_with_retry(
                str(tmp_path / "a"), str(tmp_path / "b"), replace_fn=always_blocked, sleep_fn=lambda s: None
            )
        assert attempts["n"] == REPLACE_ATTEMPTS

    def test_foreign_oserror_propagates_on_the_first_attempt(self, monkeypatch, tmp_path):
        """Only sharing violations are retried — a real failure is not hidden."""
        attempts = {"n": 0}

        def wrong_disk(src, dst):
            attempts["n"] += 1
            raise OSError(18, "Invalid cross-device link")

        with pytest.raises(OSError):
            config.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"), replace_fn=wrong_disk)
        assert attempts["n"] == 1

    def test_the_backoff_is_a_wait_not_a_busy_spin(self, monkeypatch, tmp_path):
        """Deleting the sleep leaves a spin that passes every other pin here.

        Counting the sleeps pins the wait with no wall clock, so a loaded runner cannot flake it."""

        def refused(src, dst):
            raise PermissionError()

        sleeps: list = []

        with pytest.raises(PermissionError):
            config.replace_with_retry(
                str(tmp_path / "a"), str(tmp_path / "b"), replace_fn=refused, sleep_fn=sleeps.append
            )

        assert sleeps == [REPLACE_BACKOFF_SECONDS] * (REPLACE_ATTEMPTS - 1)

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


class TestReadTextWithRetry:
    """The mirror of replace_with_retry, and the half that was missing until
    reads retried too: a refused open regenerated the document from a template."""

    def _flaky(self, tmp_path, refusals):
        path = tmp_path / "doc.json"
        path.write_text("payload", encoding="utf-8")
        state = {"left": refusals, "seen": 0}
        real = Path.read_text

        def read_text(self_path, *args, **kwargs):
            if str(self_path) == str(path) and state["left"]:
                state["left"] -= 1
                state["seen"] += 1
                raise PermissionError(13, "used by another process")
            return real(self_path, *args, **kwargs)

        return path, state, read_text

    def test_a_refusal_that_clears_is_waited_out(self, monkeypatch, tmp_path):
        """Three sharing violations, then the real contents."""
        path, state, read_text = self._flaky(tmp_path, 3)
        assert config.read_text_with_retry(path, read_fn=read_text, sleep_fn=lambda s: None) == "payload"
        assert state["seen"] == 3

    def test_it_actually_waits_between_attempts(self, monkeypatch, tmp_path):
        """A busy spin retries, bounds and returns perfectly while never
        outlasting the handle the retry exists to wait out. Count the waits, not the clock."""
        path, _state, read_text = self._flaky(tmp_path, 3)
        sleeps: list = []
        config.read_text_with_retry(path, read_fn=read_text, sleep_fn=sleeps.append)
        assert sleeps == [REPLACE_BACKOFF_SECONDS] * 3

    def test_a_refusal_that_never_clears_raises(self, monkeypatch, tmp_path):
        """Exhaustion raises. Returning a blank document is the one outcome
        this function must never have."""
        path, state, read_text = self._flaky(tmp_path, 10_000)
        with pytest.raises(PermissionError):
            config.read_text_with_retry(path, read_fn=read_text, sleep_fn=lambda s: None)
        assert state["seen"] == REPLACE_ATTEMPTS

    def test_a_foreign_oserror_propagates_on_the_first_attempt(self, monkeypatch, tmp_path):
        """Only the sharing violation is transient. A missing file is not."""
        path = tmp_path / "gone.json"
        seen = []

        def read_text(self_path, *args, **kwargs):
            seen.append(1)
            raise FileNotFoundError(2, "No such file")

        with pytest.raises(FileNotFoundError):
            config.read_text_with_retry(path, read_fn=read_text)
        assert len(seen) == 1, "retried something that was never going to clear"


class _PositionalFakeMsvcrt:
    """A fake that models what real msvcrt.locking does: lock nbytes starting
    at the descriptor's CURRENT position, conflicting only where the ranges overlap."""

    LK_NBLCK = 1
    LK_UNLCK = 0

    def __init__(self):
        self.held: set = set()
        self.grants: list = []

    def locking(self, fileno, mode, nbytes):
        start = os.lseek(fileno, 0, os.SEEK_CUR)
        span = set(range(start, start + nbytes))
        if mode == self.LK_UNLCK:
            self.held -= span
            return
        if span & self.held:
            raise OSError(36, "Resource deadlock avoided")
        self.held |= span
        self.grants.append((start, nbytes))


class TestWindowsLockIsPositionAware:
    """msvcrt locks bytes at the descriptor's CURRENT position. The sidecar is
    opened "a+", which lands a fresh handle at EOF, so the seek(0) before every
    lock is the only thing keeping two handles on the same byte."""

    def test_a_sidecar_that_grew_still_collides(self, tmp_path):
        """The drift case, constructed: the file grows between the two opens.

        Without the seek the two handles lock different bytes and BOTH proceed."""
        fake = _PositionalFakeMsvcrt()
        sleeps: list = []
        doc = tmp_path / "doc.json"
        lock_path = doc.with_suffix(".lock")
        lock_path.write_text("", encoding="utf-8")

        with config.json_file_lock(doc, platform="win32", msvcrt_module=fake, sleep_fn=sleeps.append):
            lock_path.write_text("x" * 64, encoding="utf-8")
            with pytest.raises(OSError):
                with config.json_file_lock(doc, platform="win32", msvcrt_module=fake, sleep_fn=sleeps.append):
                    pass

        assert fake.grants[0] == (0, 1), f"outer lock landed at {fake.grants[0]}, not byte 0"
        assert len(fake.grants) == 1, "a second lock was granted while the first was held"
        assert len(sleeps) == LOCK_ATTEMPTS - 1, "the inner lock did not wait out its bound before refusing"

    def test_the_model_can_see_position_drift(self, monkeypatch, tmp_path):
        """Vacuity floor: prove the model WOULD grant two unsought locks.

        Without it, the test above could pass because the fake never conflicts."""
        fake = _PositionalFakeMsvcrt()
        lock_path = tmp_path / "drift.lock"
        lock_path.write_text("", encoding="utf-8")

        with open(lock_path, "a+", encoding="utf-8") as a:
            fake.locking(a.fileno(), fake.LK_NBLCK, 1)
            lock_path.write_text("x" * 64, encoding="utf-8")
            with open(lock_path, "a+", encoding="utf-8") as b:
                fake.locking(b.fileno(), fake.LK_NBLCK, 1)

        assert fake.grants == [(0, 1), (64, 1)], f"model did not show drift: {fake.grants}"


class TestThePosixLockArmIsRealToo:
    """The win32 arm is pinned by injection; the POSIX arm was only pinned
    through its callers. fcntl.flock on separate open file descriptions serialises threads."""

    def test_four_threads_never_hold_it_at_once(self, tmp_path):
        # sys, not config.sys: the subject under test must not decide its own collection.
        if sys.platform == "win32":  # pragma: no cover - POSIX arm only
            pytest.skip("POSIX arm; the win32 arm is pinned by injection above")

        doc = tmp_path / "doc.json"
        state = {"inside": 0, "peak": 0, "overlaps": 0}
        guard = threading.Lock()

        def worker():
            for _ in range(60):
                with config.json_file_lock(doc):
                    with guard:
                        state["inside"] += 1
                        state["peak"] = max(state["peak"], state["inside"])
                        if state["inside"] > 1:
                            state["overlaps"] += 1
                    # Yield while holding it: a no-op lock lets another worker in right here.
                    os.sched_yield()
                    with guard:
                        state["inside"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert state["peak"] == 1, f"{state['peak']} threads held the lock at once"
        assert state["overlaps"] == 0
