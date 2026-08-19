# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_auto_process_background.py
# Date: 2026-08-13
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Tests for moving auto_process off the prompt lane (DPLAN-0295 item 1).

auto_process ran SYNCHRONOUSLY on the first UserPromptSubmit of every session —
measured 78.5s to 120.5s with a backlog, and the cause of the 30s-timeout losses
Patrick hit live. Its stdout is always empty, so by Patrick's test (compass #272)
it never belonged on the prompt lane at all.

Covers:
  - spawn_background() returns immediately and does NOT do the work inline
  - a spawn failure is reported, never raised into the hook and never silent
  - single-flight: a fresh lock skips the spawn with a stated reason
  - a stale lock is reclaimed rather than deadlocking the lane forever
  - run_once() (the child) acquires, works, and always releases — even on error
  - the child is detached, so it outlives the session that kicked it
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.memory.apps.handlers.intake import auto_process as ap


@pytest.fixture(autouse=True)
def isolated_lock(tmp_path, monkeypatch):
    """Point the lock at tmp_path — never touch the real one during tests."""
    monkeypatch.setattr(ap, "_LOCK_PATH", tmp_path / "auto-process.lock")
    yield tmp_path / "auto-process.lock"


@pytest.fixture(autouse=True)
def no_live_operation_log(monkeypatch):
    """Keep test runs out of the branch's real operation log.

    Without this, spawn/run tests append fabricated entries ('chroma exploded',
    pid 8) to memory_json/auto_process_log.json — test fiction in a production
    record that a future reader would have to disprove.
    """
    monkeypatch.setattr(ap.json_handler, "log_operation", MagicMock(return_value=True))


# ---------------------------------------------------------------------------
# spawn_background
# ---------------------------------------------------------------------------


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

    def test_child_never_inherits_the_hook_pipes(self):
        """Inherited pipes can block the hook when the buffer fills."""
        with patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock(pid=1)
            ap.spawn_background()

        kwargs = popen.call_args.kwargs
        assert kwargs.get("stdout") is not None
        assert kwargs.get("stderr") is not None
        assert kwargs.get("stdin") is not None

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


# ---------------------------------------------------------------------------
# Single-flight
# ---------------------------------------------------------------------------


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
        old = time.time() - (ap._LOCK_STALE_SECONDS + 60)
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


# ---------------------------------------------------------------------------
# run_once — the child's entry point
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Script contract
# ---------------------------------------------------------------------------


class TestScriptContract:
    """The child is executed as a script by path — it must survive that."""

    def test_handler_has_a_main_block(self):
        source = Path(ap.__file__).read_text(encoding="utf-8")
        assert '__name__ == "__main__"' in source

    def test_handler_has_no_relative_imports(self):
        """A relative import here is invisible until the child runs (the `watch` defect)."""
        source = Path(ap.__file__).read_text(encoding="utf-8")
        offenders = [ln for ln in source.splitlines() if ln.strip().startswith("from .")]
        assert not offenders, f"relative imports in a script-executed handler: {offenders}"
