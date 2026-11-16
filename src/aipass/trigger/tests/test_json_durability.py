# =================== AIPass ====================
# Name: test_json_durability.py
# Description: Durability pins for config.py's write + lock helpers
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-11-16
# =============================================

"""Tests for apps/config.py's durability helpers: json_file_lock and atomic_write_json."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — medic state's read-modify-writes over json_file_lock, test_medic_state.py

import os
import threading
import pytest

from aipass.trigger.apps import config


class TestThePosixLockIsReal:
    """fcntl.flock on separate open file descriptions serialises threads."""

    def test_four_threads_never_hold_it_at_once(self, tmp_path):
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


class TestATornWriteCleansUp:
    """A failed atomic write leaves no tmp file, and a failed cleanup is never hidden."""

    def test_a_failed_write_leaves_no_tmp_file(self, tmp_path):
        home = tmp_path / "home"

        with pytest.raises(TypeError):
            config.atomic_write_json(home / "doc.json", {"x": object()})

        assert list(home.iterdir()) == []

    def test_a_cleanup_that_fails_raises_with_the_write_error_chained(self, tmp_path):
        """Pins the default: an unremovable tmp file was swallowed, left on disk with nobody told."""
        home = tmp_path / "home"
        home.mkdir()

        class LocksTheDirectoryMidWrite(dict):
            def items(self):
                home.chmod(0o500)
                raise TypeError("unserialisable")

        try:
            with pytest.raises(PermissionError) as caught:
                config.atomic_write_json(home / "doc.json", LocksTheDirectoryMidWrite(x=1))
            assert isinstance(caught.value.__context__, TypeError)
            assert [p.suffix for p in home.iterdir()] == [".tmp"]
        finally:
            home.chmod(0o700)
