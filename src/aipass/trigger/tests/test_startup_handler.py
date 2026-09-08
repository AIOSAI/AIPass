# =================== AIPass ====================
# Name: test_startup_handler.py
# Description: Tests for startup event handler
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for startup event handler."""

import pytest
from unittest.mock import MagicMock
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

        assert ok is True
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

        assert ok is False, "the limit must still stop the scan"
        assert len(errors) == limit
