# =================== AIPass ====================
# Name: test_json_durability.py
# Description: Cross-platform durability pins for config.py's write + lock helpers
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-09-29
# =============================================

"""Tests for apps/config.py's durability helpers: atomic_write_json, json_file_lock and the retry reads."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — _acquire_lock_win32 against a real Windows host; driven here by injection
# seedgo: no-test-needed(covered_elsewhere) — medic state's read-modify-writes over json_file_lock, test_medic_state.py

import json
import os
import sys
import threading
import time
from pathlib import Path

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
def win32():
    """A fake msvcrt, handed to the lock through its seam with platform "win32"."""
    return _FakeMsvcrt()


class TestWindowsLockIsRealNotSkipped:
    """A lock one platform walks past is not a lock. The old code read
    `if sys.platform == "win32": yield` — every caller believed it was
    serialised and none of them were.
    """

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

        assert sleeps == [config._LOCK_BACKOFF_SECONDS] * 3
        assert fake.calls.count((fake.LK_NBLCK, 1)) == 4

    def test_win32_refuses_rather_than_running_unlocked(self, tmp_path):
        """Exhausting the retries RAISES after a bounded wait. Silent data loss is the one forbidden outcome.

        Mutant run: the win32 backoff sleep deleted reddens this.
        """
        fake = _FakeMsvcrt(fail_times=config._LOCK_ATTEMPTS + 5)
        sleeps: list = []

        entered = False
        with pytest.raises(OSError):
            with config.json_file_lock(
                tmp_path / "doc.json", platform="win32", msvcrt_module=fake, sleep_fn=sleeps.append
            ):
                entered = True
        assert entered is False, "body ran without the lock"
        assert sleeps == [config._LOCK_BACKOFF_SECONDS] * (config._LOCK_ATTEMPTS - 1)

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
        """A replace blocked twice still lands, waiting once per refusal (mutant: a wait after success)."""
        attempts = {"n": 0}

        def flaky(src, dst):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise PermissionError("sharing violation")

        sleeps: list = []

        config.replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"), replace_fn=flaky, sleep_fn=sleeps.append)
        assert attempts["n"] == 3
        assert sleeps == [config._REPLACE_BACKOFF_SECONDS] * 2

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
        assert attempts["n"] == config._REPLACE_ATTEMPTS

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

        Counting the sleeps pins the wait without asserting on wall-clock time,
        so it cannot flake on a loaded runner.
        """

        def refused(src, dst):
            raise PermissionError()

        sleeps: list = []

        with pytest.raises(PermissionError):
            config.replace_with_retry(
                str(tmp_path / "a"), str(tmp_path / "b"), replace_fn=refused, sleep_fn=sleeps.append
            )

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


class TestReadTextWithRetry:
    """The mirror of replace_with_retry, and the half that was missing until
    Windows CI counted 98 of 100 appends (run 32167459635, 2026-08-18).

    Hardening only the write left every reader exposed to the same sharing
    window, and json_handler's readers answered a refused open by regenerating
    the document from a template — a transient laundered into data loss.
    """

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
        outlasting the handle the retry exists to wait out. Count the waits —
        no wall clock, so a loaded runner cannot flake this.
        """
        path, _state, read_text = self._flaky(tmp_path, 3)
        sleeps: list = []
        config.read_text_with_retry(path, read_fn=read_text, sleep_fn=sleeps.append)
        assert sleeps == [config._REPLACE_BACKOFF_SECONDS] * 3

    def test_a_refusal_that_never_clears_raises(self, monkeypatch, tmp_path):
        """Exhaustion raises. Returning a blank document is the one outcome
        this function must never have — that is the defect it was written for.
        """
        path, state, read_text = self._flaky(tmp_path, 10_000)
        with pytest.raises(PermissionError):
            config.read_text_with_retry(path, read_fn=read_text, sleep_fn=lambda s: None)
        assert state["seen"] == config._REPLACE_ATTEMPTS

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
    at the CURRENT file position of the descriptor, conflicting only where the
    ranges overlap.

    Asked for by devpulse (2564f815) as the way to make position drift
    constructible from Linux: the sidecar is opened "a+", so a fresh handle
    sits at EOF, and two handles at different offsets would each take their
    own byte and both proceed — a lock that never collides. The real fd is
    used, so the position this reads is the one msvcrt would see.
    """

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
    lock is the only thing keeping two handles on the same byte. Today the
    sidecar is always zero-length and the bug is invisible; the day anything
    writes to it, position drift would silently un-serialise every caller.
    """

    def test_a_sidecar_that_grew_still_collides(self, tmp_path):
        """The drift case, constructed: the file grows between the two opens.

        Handle A opens an empty sidecar and sits at byte 0. The sidecar then
        grows, so handle B opens at byte 64. Without the seek they lock
        different bytes and BOTH proceed — a lock that never collides. The
        seek is the only thing making them meet.
        Mutant for the wait assert: the win32 backoff sleep deleted.
        """
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
        assert len(sleeps) == config._LOCK_ATTEMPTS - 1, "the inner lock did not wait out its bound before refusing"

    def test_the_model_can_see_position_drift(self, monkeypatch, tmp_path):
        """Vacuity floor: prove the model WOULD grant two unsought locks.

        Without this, the test above could pass because the fake never
        conflicts with anything. Same growth, no seek — both handles lock
        where they land, both succeed, and that is exactly the defect.
        """
        fake = _PositionalFakeMsvcrt()
        lock_path = tmp_path / "drift.lock"
        lock_path.write_text("", encoding="utf-8")

        with open(lock_path, "a+", encoding="utf-8") as a:
            fake.locking(a.fileno(), fake.LK_NBLCK, 1)
            lock_path.write_text("x" * 64, encoding="utf-8")
            with open(lock_path, "a+", encoding="utf-8") as b:
                fake.locking(b.fileno(), fake.LK_NBLCK, 1)

        assert fake.grants == [(0, 1), (64, 1)], f"model did not show drift: {fake.grants}"


class TestAtomicCreateJsonNeverOverwrites:
    """ "Ensure this file exists" and "write this file" are different
    operations, and implementing the first as the second cost a concurrent
    append on Linux CI (32228159169, 99 of 100). Reproduced locally at 3 losing
    runs in 400 before the fix, 0 in 1500 after — with the same loop still
    losing when the replacing write is put back, so the loop has power.
    """

    def test_it_creates_when_nothing_is_there(self, tmp_path):
        path = tmp_path / "new.json"
        assert config.atomic_create_json(path, {"a": 1}) is True
        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}

    def test_it_refuses_and_changes_nothing_when_the_document_exists(self, tmp_path):
        """The whole point: the loser of a create race writes NOTHING."""
        path = tmp_path / "taken.json"
        path.write_text(json.dumps({"written": "by someone else"}), encoding="utf-8")

        assert config.atomic_create_json(path, {"a": 1}) is False
        assert json.loads(path.read_text(encoding="utf-8")) == {"written": "by someone else"}

    def test_a_filesystem_without_hard_links_refuses_rather_than_overwrites(self, tmp_path):
        """No link support is a refusal, never the replacing write the create exists to avoid.

        Red first 2026-09-29 (leg 5): the create fell back to replace_with_retry,
        returned True, and the other writer's document was gone.
        """
        path = tmp_path / "taken.json"
        path.write_text(json.dumps({"written": "by someone else"}), encoding="utf-8")

        def no_links(source: str, destination: str) -> None:
            raise OSError("no hard links on this filesystem")

        with pytest.raises(OSError, match="no hard links"):
            config.atomic_create_json(path, {"a": 1}, link_fn=no_links)
        assert json.loads(path.read_text(encoding="utf-8")) == {"written": "by someone else"}
        assert list(tmp_path.glob("*.tmp")) == []

    def test_it_leaves_no_staged_file_behind_either_way(self, tmp_path):
        """Both paths clean up their temp file — a create that loses the race
        still has one staged, and .tmp litter in the state dir is what the
        trio machinery would later try to interpret.
        """
        path = tmp_path / "clean.json"
        config.atomic_create_json(path, {"a": 1})
        config.atomic_create_json(path, {"a": 2})
        assert list(tmp_path.glob("*.tmp")) == []


class TestThePosixLockArmIsRealToo:
    """The win32 arm is pinned by injection; the POSIX arm was only pinned
    through its callers. devpulse asked outright whether the byte-lock is
    msvcrt-only with no fcntl twin (2564f815 follow-up, Linux CI 32228159169).

    It is not: fcntl.flock is taken on a fresh open file description per call,
    and separate descriptions conflict even inside ONE process — which is what
    makes threads serialise. Measured rather than asserted.
    """

    def test_four_threads_never_hold_it_at_once(self, tmp_path):
        # sys, not config.sys: the machine decides whether this runs, and the
        # subject under test does not get a vote. Reaching the same value
        # through config meant the module I am testing sat between me and the
        # platform fact — one attribute rename away from deciding my own
        # collection (seedgo self_skip, 2026-09-08).
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
                    time.sleep(0.0002)
                    with guard:
                        state["inside"] -= 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert state["peak"] == 1, f"{state['peak']} threads held the lock at once"
        assert state["overlaps"] == 0
