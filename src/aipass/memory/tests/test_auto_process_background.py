# =================== AIPass ====================
# Name: tests/test_auto_process_background.py
# Description: Tests for auto_process background spawn, single-flight lock and run_once
# Version: 1.1.1
# Created: 2026-08-14
# Modified: 2026-10-17
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/intake/auto_process.py."""

# auto_process runs detached, never on the prompt lane: its stdout is empty and it took 78-120s.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — run_pool_processing and auto_process() work, in tests/test_auto_process.py
# seedgo: no-test-needed(external) — what the detached child writes to _CHILD_LOG; that is the child's own run
# seedgo: no-test-needed(external) — the win32 branch of spawn_background(); only a Windows run takes it

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.memory.apps.handlers.intake import auto_process as ap


@pytest.fixture(autouse=True)
def isolated_lock(tmp_path, monkeypatch):
    """Point the lock and the child log at tmp_path — never touch the real ones during tests."""
    monkeypatch.setattr(ap, "_LOCK_PATH", tmp_path / "auto-process.lock")
    monkeypatch.setattr(ap, "_CHILD_LOG", tmp_path / "auto-process.log")
    yield tmp_path / "auto-process.lock"


@pytest.fixture(autouse=True)
def no_live_operation_log(monkeypatch):
    """Keep test runs out of the branch's real operation log: no fabricated entries in a production record."""
    monkeypatch.setattr(ap.json_handler, "log_operation", MagicMock(return_value=True))


class TestSpawnBackground:
    """The hook's call must return in milliseconds, having done no work."""

    def test_spawn_does_not_run_the_work_inline(self):
        with patch.object(ap, "auto_process") as worked:
            with patch("subprocess.Popen") as popen:
                popen.return_value = MagicMock(pid=4242)
                result = ap.spawn_background()

        worked.assert_not_called()
        assert result["success"] is True
        assert result["pid"] == 4242

    def test_child_is_detached_so_it_outlives_the_session(self):
        """A child in the session's process group dies with the session."""
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock(pid=1)
            ap.spawn_background()

        kwargs = popen.call_args.kwargs
        if sys.platform == "win32":
            assert kwargs.get("creationflags", 0) != 0
        else:
            assert kwargs.get("start_new_session") is True

    def test_child_never_inherits_the_hook_pipes(self, isolated_lock):
        """Inherited pipes can block the hook when the buffer fills: each stream pinned to what it is handed."""
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock(pid=1)
            ap.spawn_background()

        kwargs = popen.call_args.kwargs
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["stdout"].name == str(isolated_lock.parent / "auto-process.log")

    def test_spawn_failure_is_reported_not_raised(self):
        """Fail to errors: the hook gets a result, never an exception."""
        with patch("subprocess.Popen", side_effect=OSError("no fork for you")):
            result = ap.spawn_background()

        assert result["success"] is False
        assert "no fork for you" in result["error"]

    def test_spawn_target_is_this_handler_as_a_script(self):
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock(pid=1)
            ap.spawn_background()

        argv = popen.call_args.args[0]
        assert argv[0] == sys.executable
        assert argv[1].endswith("auto_process.py")


class TestSingleFlight:
    """Two sessions starting together must not run two rollovers at once."""

    def test_fresh_lock_skips_the_spawn_with_a_reason(self, isolated_lock):
        isolated_lock.write_text(json.dumps({"pid": 999, "started": time.time()}), encoding="utf-8")

        with patch("subprocess.Popen") as popen:
            result = ap.spawn_background()

        popen.assert_not_called()
        assert result["skipped"] is True
        assert "already running" in result["reason"]

    def test_stale_lock_does_not_wedge_the_lane_forever(self, isolated_lock):
        """A crashed child leaves a lock behind; it must not block for good."""
        old = time.time() - 30 * 24 * 3600  # a month old: stale under any threshold the lane could carry
        isolated_lock.write_text(json.dumps({"pid": 999, "started": old}), encoding="utf-8")

        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock(pid=7)
            result = ap.spawn_background()

        popen.assert_called_once()
        assert result["success"] is True

    def test_unreadable_lock_is_treated_as_stale(self, isolated_lock):
        """Guard the read, not just the parse — a corrupt lock is not a wedge."""
        isolated_lock.write_text("{not json", encoding="utf-8")

        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock(pid=8)
            result = ap.spawn_background()

        popen.assert_called_once()
        assert result["success"] is True


class TestRunOnce:
    """The child holds the lock for exactly as long as it works."""

    def test_runs_the_work_and_releases_the_lock(self, isolated_lock):
        with patch.object(ap, "auto_process", return_value={"success": True}) as worked:
            result = ap.run_once()

        worked.assert_called_once()
        assert result["success"] is True
        assert not isolated_lock.exists()

    def test_lock_is_released_even_when_the_work_raises(self, isolated_lock):
        with patch.object(ap, "auto_process", side_effect=RuntimeError("chroma exploded")):
            result = ap.run_once()

        assert result["success"] is False
        assert "chroma exploded" in result["error"]
        assert not isolated_lock.exists(), "a crashed run must not wedge the next one"

    def test_second_runner_declines_while_the_first_holds_the_lock(self, isolated_lock):
        isolated_lock.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}), encoding="utf-8")

        with patch.object(ap, "auto_process") as worked:
            result = ap.run_once()

        worked.assert_not_called()
        assert result["skipped"] is True

    def test_lock_records_who_holds_it(self, isolated_lock):
        seen = {}

        def _capture():
            seen["lock"] = json.loads(isolated_lock.read_text(encoding="utf-8"))
            return {"success": True}

        with patch.object(ap, "auto_process", side_effect=_capture):
            ap.run_once()

        assert seen["lock"]["pid"] == os.getpid()
        assert seen["lock"]["started"] > 0


class TestCompletionIsAnnounced:
    """The child announces its own completion, because nothing else can.

    The spawn site cannot: a PID is not a completion. Without the fire, @trigger's failure leg never reaches medic.
    """

    @staticmethod
    def _bus():
        """The exact bus object ``_fire_completion`` will reach, resolved NOW.

        A dotted patch() walks the package attributes on 3.10 and sys.modules on 3.11+; when the two
        split, the patch misses. Patching through the import route pins the object the code reaches.
        """
        import importlib

        return importlib.import_module("aipass.trigger.apps.modules.core").trigger

    @staticmethod
    def _fired(mock_fire):
        """The one memory_pool_auto_processed call, as (name, payload)."""
        calls = [c for c in mock_fire.call_args_list if c.args and c.args[0] == "memory_pool_auto_processed"]
        assert len(calls) == 1, f"expected exactly one completion fire, got {len(calls)}"
        return calls[0].kwargs

    def test_a_finished_run_announces_success_in_the_published_shape(self, isolated_lock):
        """@trigger's handler reads `status` on both sections — the internal dicts do not carry it."""
        done = {
            "success": True,
            "pool": {"success": True, "files_processed": 3, "total_chunks": 12},
            "rollover": {"success": True, "triggers": 1, "processed": 1},
        }
        with patch.object(self._bus(), "fire") as fire:
            with patch.object(ap, "auto_process", return_value=done):
                ap.run_once()

        payload = self._fired(fire)
        assert payload["success"] is True
        assert payload["error"] is None
        assert payload["pool"] == {"status": "ok", "files_processed": 3, "total_chunks": 12}
        assert payload["rollover"] == {"status": "ok", "triggers": 1, "processed": 1}

    def test_a_crashed_run_announces_the_failure_that_reaches_medic(self, isolated_lock):
        """The leg that was dead. `success: False` + `error` is what becomes error_detected."""
        with patch.object(self._bus(), "fire") as fire:
            with patch.object(ap, "auto_process", side_effect=RuntimeError("chroma exploded")):
                ap.run_once()

        payload = self._fired(fire)
        assert payload["success"] is False
        assert "chroma exploded" in payload["error"]
        assert payload["branch"] == "memory", "the citizen to wake for a fault here is this code's owner"
        assert payload["pool"]["status"] == "unknown", "a section that never reported is not a completion"
        assert payload["rollover"]["status"] == "unknown"

    def test_a_declined_run_announces_nothing(self, isolated_lock):
        """A run that never held the lock did not complete anything; the holder announces its own."""
        isolated_lock.write_text(json.dumps({"pid": os.getpid(), "started": time.time()}), encoding="utf-8")

        with patch.object(self._bus(), "fire") as fire:
            result = ap.run_once()

        assert result["skipped"] is True
        assert not [c for c in fire.call_args_list if c.args and c.args[0] == "memory_pool_auto_processed"]

    def test_a_broken_bus_does_not_break_the_run(self, isolated_lock):
        """Observability must not take down the work it observes."""
        with patch.object(self._bus(), "fire", side_effect=RuntimeError("bus down")):
            with patch.object(ap, "auto_process", return_value={"success": True}):
                result = ap.run_once()

        assert result["success"] is True
        assert not isolated_lock.exists(), "a failed fire must still release the lock"


class TestScriptContract:
    """The child is executed as a script by path — it must survive that."""

    def test_handler_has_a_main_block(self):
        source = Path(ap.__file__).read_text(encoding="utf-8")
        assert '__name__ == "__main__"' in source

    def test_handler_has_no_relative_imports(self):
        """A relative import here is invisible until the child runs (the `watch` defect).

        Mutant: a ``from . import nothing`` line added to ``spawn_background``'s docstring — killed.
        """
        source = Path(ap.__file__).read_text(encoding="utf-8")
        offenders = [ln for ln in source.splitlines() if ln.strip().startswith("from .")]
        assert offenders == [], f"relative imports in a script-executed handler: {offenders}"
