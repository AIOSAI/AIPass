# =================== AIPass ====================
# Name: test_startup_handler.py
# Description: Tests for startup event handler
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-09-12
# =============================================

"""Tests for startup event handler."""

import pytest
from unittest.mock import MagicMock
from datetime import datetime
from pathlib import Path


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock heavy infrastructure imports before importing the handler module."""
    import sys

    from aipass.trigger.apps.config import atomic_write_json, migrate_json_file

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
    mock_config.atomic_write_json = atomic_write_json
    mock_config.TRIGGER_JSON_DIR = tmp_path / "trigger_json"
    mock_config.migrate_json_file = migrate_json_file
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.json.json_handler",
        mock_json_handler,
    )

    monkeypatch.delitem(
        sys.modules,
        "aipass.trigger.apps.handlers.events.startup",
        raising=False,
    )


def _import_startup():
    """Import fresh after mocking."""
    import aipass.trigger.apps.handlers.events.startup as m

    return m


class TestHandleStartup:
    """Tests for handle_startup."""

    def test_calls_error_catchup_with_fire_event(self) -> None:
        """Passes fire_event kwarg to _run_error_catchup."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()

        fire_event = MagicMock()
        mod.handle_startup(fire_event=fire_event)

        mod._run_error_catchup.assert_called_once_with(fire_event)  # type: ignore[union-attr]

    def test_passes_none_when_no_fire_event(self) -> None:
        """Without fire_event kwarg, passes None to error catchup."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()

        mod.handle_startup()

        mod._run_error_catchup.assert_called_once_with(None)  # type: ignore[union-attr]

    def test_extra_kwargs_do_not_crash(self) -> None:
        """Arbitrary extra kwargs are silently ignored."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()

        mod.handle_startup(fire_event=MagicMock(), extra_arg="ignored", count=42)

        mod._run_error_catchup.assert_called_once()  # type: ignore[union-attr]


class TestCatchupStateMigration:
    """Catch-up state moves off the trio-owned trigger_data.json name."""

    def test_load_migrates_legacy_catchup_file(self) -> None:
        """Processed hashes survive the move — nothing is re-dispatched."""
        import json

        mod = _import_startup()
        legacy = mod.LEGACY_CATCHUP_STATE_FILE
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps(
                {"error_catchup": {"last_scan_timestamp": "2026-08-07T12:00:00", "processed_hashes": ["a1", "b2"]}}
            ),
            encoding="utf-8",
        )

        data = mod._load_trigger_data()

        assert data["error_catchup"]["processed_hashes"] == ["a1", "b2"]
        assert mod.CATCHUP_STATE_FILE.exists()
        assert not legacy.exists()

    def test_save_targets_new_file(self) -> None:
        """Saves go to error_catchup.json, never back to the legacy name."""
        mod = _import_startup()

        mod._save_trigger_data({"error_catchup": {"processed_hashes": []}})

        assert mod.CATCHUP_STATE_FILE.exists()
        assert not mod.LEGACY_CATCHUP_STATE_FILE.exists()


class TestCatchupOccurrenceCounting:
    """A burst must not read as one line (FPLAN-0492 wave 5)."""

    @staticmethod
    def _write_log(tmp_path: Path, lines: list) -> Path:
        log = tmp_path / "flow_ops.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log

    @staticmethod
    def _line(ts: str, message: str = "connection timed out") -> str:
        return f"{ts} | flow.runner | ERROR | {message}"

    def test_repeat_lines_are_counted_not_dropped(self, tmp_path: Path) -> None:
        """37 identical lines produce ONE entry carrying count 37.

        Measured live 2026-09-07: a 37-line burst reached the registry as
        count 2. The dedup key has no timestamp, so every line after the
        first was skipped outright and the payload said `count=1`.
        """
        mod = _import_startup()
        import time
        from datetime import datetime

        lines = [self._line(f"2026-09-07 10:{i // 60:02d}:{i % 60:02d}") for i in range(37)]
        log = self._write_log(tmp_path, lines)

        errors: list = []
        by_hash: dict = {}
        ok = mod._scan_single_log_file(
            log,
            datetime(2026, 9, 7, 0, 0, 0),
            set(),
            errors,
            time.monotonic(),
            by_hash,
        )

        assert ok is None, "no limit was hit, so nothing stopped the walk"
        assert len(errors) == 1, "one distinct error, not 37 events"
        assert errors[0]["count"] == 37

    def test_first_and_last_seen_span_the_burst(self, tmp_path: Path) -> None:
        """The stamps bracket the burst, so the notification can show its shape."""
        mod = _import_startup()
        import time
        from datetime import datetime

        log = self._write_log(
            tmp_path,
            [
                self._line("2026-09-07 10:00:00"),
                self._line("2026-09-07 10:00:30"),
                self._line("2026-09-07 10:05:00"),
            ],
        )

        errors: list = []
        mod._scan_single_log_file(log, datetime(2026, 9, 7, 0, 0, 0), set(), errors, time.monotonic(), {})

        assert errors[0]["count"] == 3
        assert errors[0]["first_seen"] == "2026-09-07T10:00:00"
        assert errors[0]["last_seen"] == "2026-09-07T10:05:00"

    def test_distinct_errors_keep_separate_counts(self, tmp_path: Path) -> None:
        """Counting a repeat must not merge two different errors."""
        mod = _import_startup()
        import time
        from datetime import datetime

        log = self._write_log(
            tmp_path,
            [
                self._line("2026-09-07 10:00:00", "connection timed out"),
                self._line("2026-09-07 10:00:01", "connection timed out"),
                self._line("2026-09-07 10:00:02", "disk full"),
            ],
        )

        errors: list = []
        mod._scan_single_log_file(log, datetime(2026, 9, 7, 0, 0, 0), set(), errors, time.monotonic(), {})

        assert len(errors) == 2
        by_message = {e["message"]: e["count"] for e in errors}
        assert by_message == {"connection timed out": 2, "disk full": 1}

    def test_a_hash_from_a_previous_run_stays_dropped(self, tmp_path: Path) -> None:
        """Repeats are counted against THIS scan only — old state still suppresses.

        Nothing collected this scan can be bumped for a hash carried over from
        persisted state, and re-emitting it would re-dispatch an error the
        previous run already handled.
        """
        mod = _import_startup()
        import time
        from datetime import datetime

        log = self._write_log(tmp_path, [self._line("2026-09-07 10:00:00")] * 5)
        old_hash = mod._generate_error_hash("flow.runner", "connection timed out")

        errors: list = []
        mod._scan_single_log_file(log, datetime(2026, 9, 7, 0, 0, 0), {old_hash}, errors, time.monotonic(), {})

        assert errors == []

    def test_the_storm_guard_still_measures_distinct_errors(self, tmp_path: Path) -> None:
        """MAX_ERRORS_PER_SCAN counts entries, so repeats cannot widen it."""
        mod = _import_startup()
        import time
        from datetime import datetime

        limit = mod.MAX_ERRORS_PER_SCAN
        lines = []
        for i in range(limit + 10):
            lines.append(self._line("2026-09-07 10:00:00", f"failure number {i}"))
            lines.append(self._line("2026-09-07 10:00:01", f"failure number {i}"))
        log = self._write_log(tmp_path, lines)

        errors: list = []
        ok = mod._scan_single_log_file(log, datetime(2026, 9, 7, 0, 0, 0), set(), errors, time.monotonic(), {})

        assert ok is not None, "the limit must still stop the scan"
        assert "MAX_ERRORS_PER_SCAN" in ok, "the reason has to name the limit that stopped it"
        assert len(errors) == limit


class TestRowTwelveTimestampGate:
    """last_scan_timestamp advances only after a scan that covered every file.

    Row 12 of DPLAN-0298, re-verified open 2026-09-11 and cured here. It used
    to advance unconditionally, so any DPLAN-037 limit threw away the window
    it aborted in: files the scan never reached fell behind the new cutoff and
    their errors were unrecoverable.
    """

    HELD = "2026-09-01T00:00:00"

    @staticmethod
    def _state(mod, last_scan, hashes=()):
        """Plant catch-up state and return the file it was written to."""
        import json

        mod.CATCHUP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        mod.CATCHUP_STATE_FILE.write_text(
            json.dumps({"error_catchup": {"last_scan_timestamp": last_scan, "processed_hashes": list(hashes)}}),
            encoding="utf-8",
        )
        return mod.CATCHUP_STATE_FILE

    @staticmethod
    def _read(mod):
        import json

        return json.loads(mod.CATCHUP_STATE_FILE.read_text(encoding="utf-8"))["error_catchup"]

    def test_completed_scan_advances_the_timestamp(self) -> None:
        """The normal path is unchanged — a clean scan still moves the cursor."""
        mod = _import_startup()
        self._state(mod, self.HELD)
        mod._scan_system_logs_for_errors = MagicMock(return_value=mod.ScanOutcome([], True, ""))

        mod._run_error_catchup(None)

        assert self._read(mod)["last_scan_timestamp"] != self.HELD

    def test_aborted_scan_holds_the_timestamp(self) -> None:
        """An incomplete scan leaves the cursor so the next run re-covers it."""
        mod = _import_startup()
        self._state(mod, self.HELD)
        mod._scan_system_logs_for_errors = MagicMock(
            return_value=mod.ScanOutcome([], False, "time budget exceeded between files (5.0s >= 5.0s)")
        )

        mod._run_error_catchup(None)

        assert self._read(mod)["last_scan_timestamp"] == self.HELD

    def test_held_timestamp_still_persists_processed_hashes(self) -> None:
        """Re-covering the window must not re-dispatch what was already found.

        The hashes are the only thing stopping that, so they are written on the
        aborted path too — holding the cursor back and dropping the hashes
        would turn one abort into a duplicate dispatch storm.
        """
        mod = _import_startup()
        self._state(mod, self.HELD)

        def _scan(since, processed_hashes):
            processed_hashes.add("deadbeef")
            return mod.ScanOutcome([], False, "MAX_ERRORS_PER_SCAN (50) reached")

        mod._scan_system_logs_for_errors = _scan

        mod._run_error_catchup(None)

        state = self._read(mod)
        assert state["last_scan_timestamp"] == self.HELD
        assert "deadbeef" in state["processed_hashes"]

    def test_size_skipped_file_holds_the_timestamp(self, tmp_path: Path) -> None:
        """A file too large to read is a hole in the window, so the cursor waits.

        @devpulse's wording for row 12 is "aborted OR skipped files". A file
        over MAX_FILE_SIZE_BYTES is never read at any window width, so
        advancing past it would lose its errors for good.
        """
        mod = _import_startup()
        monkey_dir = tmp_path / "system_logs"
        monkey_dir.mkdir()
        fat = monkey_dir / "flow_ops.log"
        fat.write_text("x" * (mod.MAX_FILE_SIZE_BYTES + 1), encoding="utf-8")
        mod.SYSTEM_LOGS_DIR = monkey_dir

        outcome = mod._scan_system_logs_for_errors(None, set())

        assert outcome.completed is False
        assert "MAX_FILE_SIZE_BYTES" in outcome.reason

    def test_missing_system_logs_dir_counts_as_completed(self, tmp_path: Path) -> None:
        """Nothing to read is not a failure to read — no window is left behind."""
        mod = _import_startup()
        mod.SYSTEM_LOGS_DIR = tmp_path / "does_not_exist"

        outcome = mod._scan_system_logs_for_errors(None, set())

        assert outcome == mod.ScanOutcome([], True, "")

    def test_clean_scan_of_a_real_dir_reports_completed(self, tmp_path: Path) -> None:
        """The completed verdict is measured off a real walk, not only mocked."""
        mod = _import_startup()
        logs = tmp_path / "system_logs"
        logs.mkdir()
        (logs / "flow_ops.log").write_text(
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | flow.runner | ERROR | disk full\n",
            encoding="utf-8",
        )
        mod.SYSTEM_LOGS_DIR = logs

        outcome = mod._scan_system_logs_for_errors(None, set())

        assert outcome.completed is True
        assert outcome.reason == ""
        assert len(outcome.errors) == 1

    def test_record_carries_the_completed_verdict(self) -> None:
        """The startup_catchup record says whether the cursor moved and why not.

        Without this the ring cannot distinguish "found nothing" from "never
        looked at half the tree" — the two readings that matter to an operator
        are identical at errors_found 0.
        """
        mod = _import_startup()
        self._state(mod, self.HELD)
        mod._scan_system_logs_for_errors = MagicMock(
            return_value=mod.ScanOutcome([], False, "MAX_ERRORS_PER_SCAN (50) reached")
        )

        mod._run_error_catchup(None)

        op, payload = mod.json_handler.log_operation.call_args[0]
        assert op == "startup_catchup"
        assert payload["completed"] is False
        assert payload["reason"] == "MAX_ERRORS_PER_SCAN (50) reached"


class TestRunStartupCatchupDoor:
    """The explicit door a long-lived process uses instead of the event bus."""

    def test_passes_fire_event_through(self) -> None:
        """A recovered error still reaches the registry and medic."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()
        fire_event = MagicMock()

        mod.run_startup_catchup(fire_event)

        mod._run_error_catchup.assert_called_once_with(fire_event)  # type: ignore[union-attr]

    def test_defaults_to_no_dispatch(self) -> None:
        """Called bare it scans and records without firing anything."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()

        mod.run_startup_catchup()

        mod._run_error_catchup.assert_called_once_with(None)  # type: ignore[union-attr]
