# =================== AIPass ====================
# Name: test_reload_sentinel.py
# Description: Tests the handler-mtime reload sentinel that keeps the watcher on shipped code
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/reload_sentinel.py, the handler-mtime reload sentinel."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — main() exiting RELOAD_EXIT_CODE, in test_log_watcher_service.py
# seedgo: no-test-needed(external) — systemd restarting the unit on RELOAD_EXIT_CODE; AIPass tests only its own files

import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import aipass.trigger.apps.handlers.reload_sentinel as reload_sentinel
import pytest
from aipass.trigger.apps.config import trail_logger


def _join_sentinel_loops() -> None:
    """Wait for every reload-sentinel loop thread to observe its stop event and exit."""
    for thread in threading.enumerate():
        if thread.name == "reload-sentinel":
            thread.join(timeout=2.0)
            assert not thread.is_alive(), "a reload-sentinel loop outlived its stop event"


@pytest.fixture
def sentinel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The module under test, with its trail pinned inside tmp_path.

    evaluate() logs through a module-level trail logger. Left unpatched every
    test that detects a change appends to the branch's LIVE
    logs/reload_sentinel.jsonl — operational evidence manufactured by a test
    suite, which is exactly the trap that sent me hunting a reload warning no
    service had written.
    """
    monkeypatch.setattr(reload_sentinel, "logger", trail_logger(tmp_path / "reload_sentinel.jsonl"))
    # Same reasoning one layer down: log_operation() writes into the branch's
    # live trigger_json/ operational logs, so an unmocked test run files
    # invented reload events alongside real ones.
    monkeypatch.setattr(reload_sentinel, "json_handler", MagicMock())
    return reload_sentinel


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sentinel) -> Path:
    """A fake handler tree the sentinel watches, isolated from the real one."""
    root = tmp_path / "handlers"
    root.mkdir()
    (root / "escalation.py").write_text("# handler\n", encoding="utf-8")
    (root / "error_registry.py").write_text("# handler\n", encoding="utf-8")
    (root / "notes.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sentinel, "WATCHED_ROOTS", (root,))
    return root


@pytest.fixture
def stop_event():
    """A stop event that is ALWAYS set on teardown.

    start() spawns a daemon thread that loops until this is set. A test that
    leaves one running outlives its own monkeypatch: WATCHED_ROOTS reverts to
    the real handler tree while the thread still holds a baseline built from
    tmp_path, so every real module reads as changed and the loop writes a
    spurious reload warning into the live trail. That is not hypothetical —
    it happened on 2026-08-12 and cost a forensic detour to explain a log line
    no service had written.
    """
    event = threading.Event()
    yield event
    event.set()
    _join_sentinel_loops()  # the loop has exited before the patch lifts


def _age(path: Path, seconds: float) -> None:
    """Backdate a file's mtime so it reads as settled."""
    stamp = path.stat().st_mtime - seconds
    os.utime(path, (stamp, stamp))


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    """What the sentinel considers part of the loaded code."""

    def test_python_modules_are_tracked(self, sentinel, tree) -> None:
        snapshot = sentinel.snapshot()

        assert set(snapshot) == {tree / "escalation.py", tree / "error_registry.py"}

    def test_non_python_files_are_ignored(self, sentinel, tree) -> None:
        """A JSON state file changes constantly and is not loaded code."""
        assert tree / "notes.json" not in sentinel.snapshot()

    def test_a_missing_root_is_not_an_error(self, sentinel, monkeypatch, tmp_path) -> None:
        """A tree that does not exist yields nothing rather than raising."""
        monkeypatch.setattr(sentinel, "WATCHED_ROOTS", (tmp_path / "nope",))

        assert sentinel.snapshot() == {}

    def test_an_archive_a_dropbox_and_a_pycache_are_not_loaded_code(self, sentinel, tree) -> None:
        """A file moved into a sandbox is no change the watcher must restart for.

        Red first 2026-09-29: rglob took all three into the snapshot.
        """
        for sandbox in (tree / ".archive", tree / "x" / "dropbox", tree / "__pycache__"):
            sandbox.mkdir(parents=True)
            (sandbox / "retired.py").write_text("# retired\n", encoding="utf-8")
        (tree / "x" / "beside.py").write_text("# handler\n", encoding="utf-8")

        snapshot = sentinel.snapshot()

        assert set(snapshot) == {tree / "escalation.py", tree / "error_registry.py", tree / "x" / "beside.py"}

    def test_a_root_inside_a_directory_named_dropbox_still_shows_its_files(
        self, sentinel, monkeypatch, tmp_path
    ) -> None:
        """The skip compares the parts below the root, never the whole path."""
        root = tmp_path / "dropbox" / ".archive" / "handlers"
        root.mkdir(parents=True)
        (root / "escalation.py").write_text("# handler\n", encoding="utf-8")
        monkeypatch.setattr(sentinel, "WATCHED_ROOTS", (root,))

        assert set(sentinel.snapshot()) == {root / "escalation.py"}


# ---------------------------------------------------------------------------
# Change detection + the settle window
# ---------------------------------------------------------------------------


class TestChangeDetection:
    """A change counts only once it has stopped moving."""

    def test_an_unchanged_tree_reports_nothing(self, sentinel, tree) -> None:
        baseline = sentinel.snapshot()

        assert sentinel.changed_since(baseline) == []

    def test_a_settled_edit_is_detected(self, sentinel, tree) -> None:
        baseline = sentinel.snapshot()
        edited = tree / "escalation.py"
        edited.write_text("# fixed\n", encoding="utf-8")
        _age(edited, sentinel.SETTLE_SECONDS + 5)

        assert sentinel.changed_since(baseline) == [edited]

    def test_an_in_flight_edit_is_not_detected(self, sentinel, tree) -> None:
        """The debounce: a file written moments ago may still be being written."""
        baseline = sentinel.snapshot()
        (tree / "escalation.py").write_text("# half a fi", encoding="utf-8")

        assert sentinel.changed_since(baseline) == []

    def test_a_new_module_is_a_change(self, sentinel, tree) -> None:
        baseline = sentinel.snapshot()
        added = tree / "new_handler.py"
        added.write_text("# new\n", encoding="utf-8")
        _age(added, sentinel.SETTLE_SECONDS + 5)

        assert sentinel.changed_since(baseline) == [added]

    def test_a_removed_module_is_a_change(self, sentinel, tree) -> None:
        """A handler renamed to name(disabled).py is still a code change."""
        baseline = sentinel.snapshot()
        (tree / "error_registry.py").unlink()

        assert sentinel.changed_since(baseline) == [tree / "error_registry.py"]

    def test_a_touched_but_identical_file_counts(self, sentinel, tree) -> None:
        """mtime is the signal. Content hashing would cost IO on every check."""
        baseline = sentinel.snapshot()
        touched = tree / "escalation.py"
        _age(touched, -sentinel.SETTLE_SECONDS * 2)  # push mtime into the future
        _age(touched, sentinel.SETTLE_SECONDS * 3)  # then well into the past

        assert sentinel.changed_since(baseline) == [touched]


# ---------------------------------------------------------------------------
# The supervision guard — the half that prevents making things worse
# ---------------------------------------------------------------------------


class TestSupervisionGuard:
    """Never trade a stale watcher for no watcher."""

    def test_systemd_sets_invocation_id(self, sentinel, monkeypatch) -> None:
        monkeypatch.setenv("INVOCATION_ID", "abc123")

        assert sentinel.is_supervised() is True

    def test_a_hand_run_process_is_not_supervised(self, sentinel, monkeypatch) -> None:
        monkeypatch.delenv("INVOCATION_ID", raising=False)

        assert sentinel.is_supervised() is False

    def test_an_empty_invocation_id_is_not_supervision(self, sentinel, monkeypatch) -> None:
        monkeypatch.setenv("INVOCATION_ID", "")

        assert sentinel.is_supervised() is False


class TestReloadDecision:
    """What the sentinel actually does when it sees a settled change."""

    def test_supervised_change_requests_the_reload(self, sentinel, tree, monkeypatch) -> None:
        monkeypatch.setenv("INVOCATION_ID", "abc123")
        baseline = sentinel.snapshot()
        edited = tree / "escalation.py"
        edited.write_text("# fixed\n", encoding="utf-8")
        _age(edited, sentinel.SETTLE_SECONDS + 5)

        assert sentinel.evaluate(baseline) is True

    def test_unsupervised_change_never_requests_the_reload(self, sentinel, tree, monkeypatch) -> None:
        """The whole point of the guard: exiting here would stop log watching."""
        monkeypatch.delenv("INVOCATION_ID", raising=False)
        baseline = sentinel.snapshot()
        edited = tree / "escalation.py"
        edited.write_text("# fixed\n", encoding="utf-8")
        _age(edited, sentinel.SETTLE_SECONDS + 5)

        assert sentinel.evaluate(baseline) is False

    def test_no_change_does_not_request_the_reload(self, sentinel, tree, monkeypatch) -> None:
        monkeypatch.setenv("INVOCATION_ID", "abc123")

        assert sentinel.evaluate(sentinel.snapshot()) is False

    def test_the_exit_code_is_non_zero(self, sentinel) -> None:
        """The unit ships Restart=on-failure, so exit 0 would NOT bring us back.

        This is the one constant that must track the systemd unit. If the unit
        ever moves to Restart=always, a clean 0 becomes correct and this test is
        the reminder to change both together.
        """
        assert sentinel.RELOAD_EXIT_CODE != 0

    def test_shutdown_without_a_change_is_not_a_reload(self, sentinel, tree, monkeypatch, stop_event) -> None:
        """An ordinary SIGTERM must exit 0, not 75 — otherwise every stop looks failed."""
        monkeypatch.setattr(sentinel, "CHECK_INTERVAL_SECONDS", 0.01)
        reload_requested = sentinel.start(stop_event)
        stop_event.set()
        _join_sentinel_loops()

        assert reload_requested() is False

    def test_the_loop_requests_a_reload_and_wakes_the_service(self, sentinel, tree, monkeypatch, stop_event) -> None:
        """The loop sets the SAME stop_event the service already waits on."""
        monkeypatch.setenv("INVOCATION_ID", "abc123")
        monkeypatch.setattr(sentinel, "CHECK_INTERVAL_SECONDS", 0.01)
        reload_requested = sentinel.start(stop_event)
        edited = tree / "escalation.py"
        edited.write_text("# fixed\n", encoding="utf-8")
        _age(edited, sentinel.SETTLE_SECONDS + 5)

        assert stop_event.wait(timeout=3.0) is True, "the loop must wake the service's own wait()"
        assert reload_requested() is True

    def test_a_crashing_check_does_not_stop_log_watching(self, sentinel, tree, monkeypatch, stop_event) -> None:
        """A broken sentinel is an inconvenience; a dead watcher is an outage."""
        monkeypatch.setattr(sentinel, "CHECK_INTERVAL_SECONDS", 0.01)
        crashes: list[int] = []
        crashed_twice = threading.Event()

        def crash(_baseline: object) -> bool:
            """Fail every check; signal once the loop has survived one crash."""
            crashes.append(1)
            if len(crashes) >= 2:
                crashed_twice.set()
            raise OSError("disk gone")

        monkeypatch.setattr(sentinel, "evaluate", crash)
        reload_requested = sentinel.start(stop_event)

        assert crashed_twice.wait(timeout=3.0), "the loop must keep checking after a crash"
        assert stop_event.is_set() is False, "the watcher must still be running"
        assert reload_requested() is False

    def test_a_reload_is_recorded_before_the_process_goes(self, sentinel, tree, monkeypatch) -> None:
        """A restart nobody can explain later is indistinguishable from a crash."""
        logged: list[Any] = []
        monkeypatch.setenv("INVOCATION_ID", "abc123")
        monkeypatch.setattr(sentinel.logger, "warning", lambda msg, **kw: logged.append(msg))
        baseline = sentinel.snapshot()
        edited = tree / "escalation.py"
        edited.write_text("# fixed\n", encoding="utf-8")
        _age(edited, sentinel.SETTLE_SECONDS + 5)

        sentinel.evaluate(baseline)

        assert logged and "escalation.py" in str(logged[-1])
