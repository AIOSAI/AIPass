# =================== AIPass ====================
# Name: test_rate_tracker.py
# Description: Tests for the rate tracker runaway-log detector
# Version: 1.2.1
# Created: 2026-07-14
# Modified: 2026-08-02
# =============================================

"""Tests for apps/handlers/monitoring/rate_tracker.py

Covers:
- Rate calculation from byte offset changes
- Sustained threshold detection (WARNING and CRITICAL)
- Burst detection via rolling-window average
- Subsidence reset when rate drops
- Per-file suppression
- Event firing via callback
- File disappearance handling
- get_snapshot() and configure()
- Disk persistence
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

_HANDLER_MOCKS = {
    "aipass.prax.apps.handlers.json": MagicMock(),
    "aipass.prax.apps.handlers.json.json_handler": MagicMock(),
}


def _import_tracker(monkeypatch, logs_dir=None):
    """Import (or reload) rate_tracker with handler mocks."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    fresh = {k: MagicMock() for k in _HANDLER_MOCKS}
    with patch.dict(sys.modules, fresh):
        import importlib

        if "aipass.prax.apps.handlers.monitoring.rate_tracker" in sys.modules:
            mod = importlib.reload(sys.modules["aipass.prax.apps.handlers.monitoring.rate_tracker"])
        else:
            mod = importlib.import_module("aipass.prax.apps.handlers.monitoring.rate_tracker")

        event_mock = MagicMock()
        mod._tracked.clear()
        mod._suppressed_files.clear()
        setattr(mod, "_state_loaded", False)
        setattr(mod, "_logs_dir", None)
        setattr(mod, "_EVENT_CALLBACK", None)
        mod.configure(logs_dir=logs_dir, event_callback=event_mock)
        return mod, event_mock


class TestRateCalculation:
    """Rate is calculated from byte offset changes over elapsed time."""

    def test_first_scan_initializes_no_rate(self, tmp_path, monkeypatch):
        """First scan seeds offsets — no rate calculated yet."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        (logs_dir / "test_module.log").write_text("line1\n" * 10)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        results = mod.scan_rates()

        assert results == []

    def test_second_scan_calculates_rate(self, tmp_path, monkeypatch):
        """Second scan with growth produces a rate."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        log_file.write_text("x" * 1300)

        with patch.object(mod.time, "time", return_value=time.time() + 10.0):
            results = mod.scan_rates()

        assert len(results) == 1
        assert results[0]["rate_lines_per_min"] > 0

    def test_no_growth_produces_zero_rate(self, tmp_path, monkeypatch):
        """File that hasn't grown has rate 0."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        (logs_dir / "test_module.log").write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        with patch.object(mod.time, "time", return_value=time.time() + 10.0):
            results = mod.scan_rates()

        assert len(results) == 1
        assert results[0]["rate_lines_per_min"] == 0.0

    def test_truncated_file_tracked_from_new_content(self, tmp_path, monkeypatch):
        """A file that shrinks (rotation) is rated on the new file's content.

        The bytes written before the roll are unobservable, so the new file's
        size is the interval floor. A quiet file after truncation must stay
        below threshold and not false-fire.
        """
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 10000)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        log_file.write_text("x" * 100)

        with patch.object(mod.time, "time", return_value=time.time() + 10.0):
            results = mod.scan_rates()

        assert len(results) == 1
        # 100 bytes / 120 bytes-per-line over 10s == 5 lines/min, well under WARNING
        assert results[0]["rate_lines_per_min"] < mod.WARNING_LINES_PER_MIN
        assert results[0]["severity"] is None
        event_mock.assert_not_called()


class TestSustainedThresholds:
    """Events fire only after sustained intervals above threshold."""

    def _grow_file(self, log_file, bytes_per_interval, mod, intervals):
        """Simulate N intervals of growth at a given rate."""
        base_time = time.time()
        results = []
        for i in range(intervals):
            log_file.write_bytes(b"x" * bytes_per_interval + log_file.read_bytes())

            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                results = mod.scan_rates()
        return results

    def test_warning_fires_after_sustained_intervals(self, tmp_path, monkeypatch):
        """WARNING fires after WARNING_SUSTAINED_INTERVALS above WARNING_LINES_PER_MIN."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        bytes_per_interval = int(mod.WARNING_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        self._grow_file(log_file, bytes_per_interval, mod, mod.WARNING_SUSTAINED_INTERVALS)

        event_mock.assert_called_once()
        call_args = event_mock.call_args
        assert call_args[0][0] == "runaway_log_detected"
        assert call_args[1]["severity"] == "warning"

    def test_warning_does_not_fire_before_sustained(self, tmp_path, monkeypatch):
        """WARNING does not fire before reaching sustained count."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        bytes_per_interval = int(mod.WARNING_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        self._grow_file(log_file, bytes_per_interval, mod, mod.WARNING_SUSTAINED_INTERVALS - 1)

        event_mock.assert_not_called()

    def test_critical_fires_after_sustained_intervals(self, tmp_path, monkeypatch):
        """CRITICAL fires after CRITICAL_SUSTAINED_INTERVALS above CRITICAL_LINES_PER_MIN."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        bytes_per_interval = int(mod.CRITICAL_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        self._grow_file(log_file, bytes_per_interval, mod, mod.CRITICAL_SUSTAINED_INTERVALS)

        assert event_mock.call_count == 1
        call_args = event_mock.call_args
        assert call_args[1]["severity"] == "critical"

    def test_fires_only_once_until_subsides(self, tmp_path, monkeypatch):
        """Event fires once — not again on continued high rate."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        bytes_per_interval = int(mod.WARNING_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        self._grow_file(log_file, bytes_per_interval, mod, mod.WARNING_SUSTAINED_INTERVALS + 5)

        assert event_mock.call_count == 1


class TestSubsidence:
    """Rate dropping below threshold resets sustained counters."""

    def test_subsidence_resets_and_allows_refire(self, tmp_path, monkeypatch):
        """After rate drops and rises again, event can fire again."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)

        base_time = time.time()
        mod.scan_rates()

        bytes_per_interval = int(mod.WARNING_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        for i in range(mod.WARNING_SUSTAINED_INTERVALS):
            log_file.write_bytes(b"x" * bytes_per_interval + log_file.read_bytes())
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        assert event_mock.call_count == 1

        for j in range(mod._WINDOW_INTERVALS):
            idle_offset = mod.WARNING_SUSTAINED_INTERVALS + j + 1
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + idle_offset * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        gap = mod.WARNING_SUSTAINED_INTERVALS + mod._WINDOW_INTERVALS
        for i in range(mod.WARNING_SUSTAINED_INTERVALS):
            log_file.write_bytes(b"x" * bytes_per_interval + log_file.read_bytes())
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (gap + i + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        assert event_mock.call_count == 2


class TestRotationDuringRunaway:
    """Regression: log rotation must not mask a sustained runaway.

    The 2026-07-31 prax event-queue firehose (~4090 lines/min, 6.8x the
    CRITICAL threshold) never fired an alert. At that rate the log hit its
    200KB RotatingFileHandler limit every ~24s, and every rotation zeroed
    the sustained counters, so the counter never reached the 6 consecutive
    intervals CRITICAL requires. The faster the runaway, the more often it
    rotated, the less likely detection became - a strict inversion.
    """

    def _run_rotating_flood(self, mod, log_file, bytes_per_interval, intervals):
        """Flood the file, rotating (shrinking to a fresh file) every 2nd interval."""
        base_time = time.time()
        for i in range(intervals):
            if i % 2 == 1:
                # RotatingFileHandler rolls .log -> .log.1 and opens a fresh
                # file, so the tracked path suddenly shrinks mid-flood.
                log_file.write_bytes(b"x" * bytes_per_interval)
            else:
                log_file.write_bytes(b"x" * bytes_per_interval + log_file.read_bytes())

            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

    def test_runaway_still_fires_when_log_rotates(self, tmp_path, monkeypatch):
        """A critical-rate flood that rotates its own log must still fire."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        bytes_per_interval = int(mod.CRITICAL_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        self._run_rotating_flood(mod, log_file, bytes_per_interval, mod.CRITICAL_SUSTAINED_INTERVALS * 2)

        assert event_mock.called, "runaway that rotates its own log must still fire an event"

    def test_rotation_preserves_sustained_counter(self, tmp_path, monkeypatch):
        """Rotation must not zero the sustained counters mid-flood."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        bytes_per_interval = int(mod.CRITICAL_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        # Three intervals, the last one a rotation - the counter must keep climbing.
        self._run_rotating_flood(mod, log_file, bytes_per_interval, 3)

        state = mod._tracked[str(log_file)]
        assert state.critical_sustained >= 3


class TestBurstDetection:
    """Window average catches bursty writers that evade per-interval checks."""

    def test_bursty_writer_fires_warning(self, tmp_path, monkeypatch):
        """Alternating high/zero intervals averaging above threshold fires WARNING."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        base_time = time.time()
        mod.scan_rates()

        bytes_burst = int(mod.WARNING_LINES_PER_MIN * 3 * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60)

        for i in range(mod.WARNING_SUSTAINED_INTERVALS):
            if i % 2 == 0:
                log_file.write_bytes(b"x" * bytes_burst + log_file.read_bytes())
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        event_mock.assert_called_once()
        assert event_mock.call_args[1]["severity"] == "warning"

    def test_single_burst_does_not_fire(self, tmp_path, monkeypatch):
        """One burst followed by silence clears before reaching sustained threshold."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        base_time = time.time()
        mod.scan_rates()

        bytes_burst = int(mod.WARNING_LINES_PER_MIN * 3 * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60)

        log_file.write_bytes(b"x" * bytes_burst + log_file.read_bytes())
        with patch.object(
            mod.time,
            "time",
            return_value=base_time + mod.SCAN_INTERVAL,
        ):
            mod.scan_rates()

        for i in range(mod.WARNING_SUSTAINED_INTERVALS):
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 2) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        event_mock.assert_not_called()

    def test_bursty_critical_fires(self, tmp_path, monkeypatch):
        """Alternating very-high/zero intervals averaging above critical threshold fires CRITICAL."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        base_time = time.time()
        mod.scan_rates()

        bytes_burst = int(mod.CRITICAL_LINES_PER_MIN * 3 * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60)

        for i in range(mod.CRITICAL_SUSTAINED_INTERVALS):
            if i % 2 == 0:
                log_file.write_bytes(b"x" * bytes_burst + log_file.read_bytes())
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        assert event_mock.call_count == 1
        assert event_mock.call_args[1]["severity"] == "critical"

    def test_window_average_subsides_after_storm(self, tmp_path, monkeypatch):
        """Window average drops below threshold after burst stops — no false latch."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)
        base_time = time.time()
        mod.scan_rates()

        bytes_burst = int(mod.WARNING_LINES_PER_MIN * 3 * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60)

        for i in range(mod.WARNING_SUSTAINED_INTERVALS):
            if i % 2 == 0:
                log_file.write_bytes(b"x" * bytes_burst + log_file.read_bytes())
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        assert event_mock.call_count == 1

        offset = mod.WARNING_SUSTAINED_INTERVALS
        for j in range(mod._WINDOW_INTERVALS):
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (offset + j + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        file_key = str(log_file)
        state = mod._tracked[file_key]
        assert state.warning_sustained == 0
        assert state.fired_warning is False


class TestSuppression:
    """Per-file suppression skips configured files."""

    def test_suppressed_file_not_tracked(self, tmp_path, monkeypatch):
        """Suppressed files are skipped entirely."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        (logs_dir / "noisy_module.log").write_text("x" * 10000)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.configure(suppressed_files={"noisy_module.log"})

        mod.scan_rates()
        mod.scan_rates()

        assert "noisy_module.log" not in {Path(k).name for k in mod._tracked}

    def test_non_suppressed_file_tracked(self, tmp_path, monkeypatch):
        """Non-suppressed files are tracked normally."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        (logs_dir / "normal_module.log").write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.configure(suppressed_files={"other_module.log"})

        mod.scan_rates()

        assert any("normal_module.log" in k for k in mod._tracked)


class TestEventPayload:
    """Event payload carries correct fields."""

    def test_event_payload_fields(self, tmp_path, monkeypatch):
        """Fired event includes all required fields."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, event_mock = _import_tracker(monkeypatch, logs_dir=logs_dir)

        base_time = time.time()
        mod.scan_rates()

        bytes_per_interval = int(mod.WARNING_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        for i in range(mod.WARNING_SUSTAINED_INTERVALS):
            log_file.write_bytes(b"x" * bytes_per_interval + log_file.read_bytes())
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                mod.scan_rates()

        call_kwargs = event_mock.call_args[1]
        assert "file_path" in call_kwargs
        assert "rate_lines_per_min" in call_kwargs
        assert "sustained_duration_sec" in call_kwargs
        assert "severity" in call_kwargs
        assert "branch" in call_kwargs
        assert call_kwargs["sustained_duration_sec"] > 0


class TestFileDisappearance:
    """Deleted files are cleaned from tracking state."""

    def test_deleted_file_removed_from_tracking(self, tmp_path, monkeypatch):
        """File removed between scans is cleaned from _tracked."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "ephemeral.log"
        log_file.write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        assert any("ephemeral.log" in k for k in mod._tracked)

        log_file.unlink()

        mod.scan_rates()

        assert not any("ephemeral.log" in k for k in mod._tracked)


class TestSnapshot:
    """get_snapshot() returns current state without scanning."""

    def test_snapshot_returns_tracked_files(self, tmp_path, monkeypatch):
        """Snapshot includes files from a previous scan."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        (logs_dir / "test_module.log").write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        snapshot = mod.get_snapshot()
        assert len(snapshot) == 1
        assert snapshot[0]["file"] == "test_module.log"

    def test_snapshot_empty_before_any_scan(self, monkeypatch):
        """Snapshot is empty before any scan."""
        mod, _ = _import_tracker(monkeypatch)
        assert mod.get_snapshot() == []


class TestConfigure:
    """configure() sets module-level dependencies."""

    def test_configure_clears_tracked_on_reimport(self, tmp_path, monkeypatch):
        """Fresh import via _import_tracker starts with empty tracked dict."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        (logs_dir / "test_module.log").write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.scan_rates()

        assert len(mod._tracked) > 0

        mod._tracked.clear()
        assert len(mod._tracked) == 0


class TestNoTrigger:
    """When no event callback is set, detection still works — just no event fired."""

    def test_detection_without_callback(self, tmp_path, monkeypatch):
        """Rate tracking and threshold detection work without event callback."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)
        mod.configure(event_callback=None)

        base_time = time.time()
        mod.scan_rates()

        bytes_per_interval = int(mod.WARNING_LINES_PER_MIN * mod.AVG_LINE_BYTES * mod.SCAN_INTERVAL / 60 * 1.5)

        results = []
        for i in range(mod.WARNING_SUSTAINED_INTERVALS):
            log_file.write_bytes(b"x" * bytes_per_interval + log_file.read_bytes())
            with patch.object(
                mod.time,
                "time",
                return_value=base_time + (i + 1) * mod.SCAN_INTERVAL,
            ):
                results = mod.scan_rates()

        assert any(r.get("severity") == "warning" for r in results)


class TestPersistence:
    """State persists to disk so CLI invocations and restarts work."""

    def test_scan_saves_state_to_disk(self, tmp_path, monkeypatch):
        """scan_rates() calls save_json after scanning."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        (logs_dir / "test_module.log").write_text("x" * 100)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)

        json_handler_mock = mod.json_handler
        mod.scan_rates()

        json_handler_mock.save_json.assert_called()
        call_args = json_handler_mock.save_json.call_args
        assert call_args[0][0] == "rate_tracker"
        assert call_args[0][1] == "data"
        saved_data = call_args[0][2]
        assert "files" in saved_data
        assert any("test_module.log" in k for k in saved_data["files"])

    def test_load_restores_offsets_from_disk(self, tmp_path, monkeypatch):
        """Loading persisted state restores file offsets so second scan can compute rates."""
        logs_dir = tmp_path / "system"
        logs_dir.mkdir(parents=True)
        log_file = logs_dir / "test_module.log"
        log_file.write_text("x" * 1300)

        mod, _ = _import_tracker(monkeypatch, logs_dir=logs_dir)

        persisted = {
            "module_name": "rate_tracker",
            "files": {
                str(log_file): {
                    "last_offset": 100,
                    "last_check": time.time() - 15.0,
                    "warning_sustained": 0,
                    "critical_sustained": 0,
                    "fired_warning": False,
                    "fired_critical": False,
                }
            },
        }
        mod.json_handler.load_json.return_value = persisted

        results = mod.scan_rates()

        assert len(results) == 1
        assert results[0]["rate_lines_per_min"] > 0

    def test_load_handles_missing_data(self, monkeypatch):
        """Loading when no data file exists is a no-op."""
        mod, _ = _import_tracker(monkeypatch)
        mod.json_handler.load_json.return_value = None

        mod._load_state()
        assert len(mod._tracked) == 0

    def test_reimport_clears_state_loaded_flag(self, monkeypatch):
        """Fresh _import_tracker resets _state_loaded so next scan reloads from disk."""
        mod, _ = _import_tracker(monkeypatch)
        setattr(mod, "_state_loaded", True)
        assert mod._state_loaded is True

        mod, _ = _import_tracker(monkeypatch)
        assert mod._state_loaded is False
