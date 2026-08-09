# =================== AIPass ====================
# Name: test_event_queue.py
# Description: Unit tests for MonitoringEvent and MonitoringQueue
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-08-08
# =============================================

"""Tests for the thread-safe event queue used by the monitoring system."""

import importlib
import threading
from datetime import datetime, timedelta

import pytest


# =============================================
# MODULE LOADING
# =============================================


@pytest.fixture
def event_queue_module(mock_prax_infrastructure):
    """Force-reload event_queue after sys.modules mocks are in place."""
    import aipass.prax.apps.handlers.monitoring.event_queue as mod

    mod = importlib.reload(mod)
    return mod


@pytest.fixture
def MonitoringEvent(event_queue_module):
    return event_queue_module.MonitoringEvent


@pytest.fixture
def MonitoringQueue(event_queue_module):
    return event_queue_module.MonitoringQueue


# =============================================
# MonitoringEvent DATACLASS TESTS
# =============================================


class TestMonitoringEvent:
    """Tests for the MonitoringEvent dataclass."""

    def test_create_with_all_fields(self, MonitoringEvent):
        """All fields can be set explicitly at construction time."""
        ts = datetime(2026, 3, 24, 12, 0, 0)
        event = MonitoringEvent(
            priority=1,
            timestamp=ts,
            event_type="file",
            branch="PRAX",
            action="created",
            message="new config",
            level="error",
            caller="DRONE",
            pid=12345,
        )
        assert event.priority == 1
        assert event.timestamp == ts
        assert event.event_type == "file"
        assert event.branch == "PRAX"
        assert event.action == "created"
        assert event.message == "new config"
        assert event.level == "error"
        assert event.caller == "DRONE"
        assert event.pid == 12345

    def test_default_values(self, MonitoringEvent):
        """Defaults produce an info-level event with empty strings and None optionals."""
        event = MonitoringEvent(priority=3)
        assert event.event_type == ""
        assert event.branch == ""
        assert event.action == ""
        assert event.message == ""
        assert event.level == "info"
        assert event.caller is None
        assert event.pid is None

    def test_auto_priority_from_error_level(self, MonitoringEvent):
        """Priority 0 is auto-mapped to 1 for error level."""
        event = MonitoringEvent(priority=0, level="error")
        assert event.priority == 1

    def test_auto_priority_from_warning_level(self, MonitoringEvent):
        """Priority 0 is auto-mapped to 2 for warning level."""
        event = MonitoringEvent(priority=0, level="warning")
        assert event.priority == 2

    def test_auto_priority_from_info_level(self, MonitoringEvent):
        """Priority 0 is auto-mapped to 3 for info level."""
        event = MonitoringEvent(priority=0, level="info")
        assert event.priority == 3

    def test_auto_priority_from_debug_level(self, MonitoringEvent):
        """Priority 0 is auto-mapped to 4 for debug level."""
        event = MonitoringEvent(priority=0, level="debug")
        assert event.priority == 4

    def test_auto_priority_unknown_level_defaults_to_info(self, MonitoringEvent):
        """Unknown level with priority 0 falls back to info priority (3)."""
        event = MonitoringEvent(priority=0, level="trace")
        assert event.priority == 3

    def test_explicit_priority_not_overridden(self, MonitoringEvent):
        """When priority is non-zero, __post_init__ leaves it alone."""
        event = MonitoringEvent(priority=5, level="error")
        assert event.priority == 5

    def test_ordering_lower_priority_comes_first(self, MonitoringEvent):
        """Lower priority number sorts before higher (error < warning < info)."""
        error_event = MonitoringEvent(priority=1, event_type="file")
        info_event = MonitoringEvent(priority=3, event_type="file")
        assert error_event < info_event

    def test_ordering_equal_priority(self, MonitoringEvent):
        """Events with equal priority compare as equal."""
        a = MonitoringEvent(priority=2, message="a")
        b = MonitoringEvent(priority=2, message="b")
        assert not (a < b)
        assert not (b < a)
        assert a == b  # Comparison only uses priority

    def test_sorting_multiple_events(self, MonitoringEvent):
        """A list of events sorts by ascending priority number."""
        events = [
            MonitoringEvent(priority=3, event_type="info_event"),
            MonitoringEvent(priority=1, event_type="error_event"),
            MonitoringEvent(priority=4, event_type="debug_event"),
            MonitoringEvent(priority=2, event_type="warning_event"),
        ]
        sorted_events = sorted(events)
        assert [e.priority for e in sorted_events] == [1, 2, 3, 4]
        assert [e.event_type for e in sorted_events] == ["error_event", "warning_event", "info_event", "debug_event"]

    def test_timestamp_default_is_close_to_now(self, MonitoringEvent):
        """Default timestamp is approximately datetime.now()."""
        before = datetime.now()
        event = MonitoringEvent(priority=3)
        after = datetime.now()
        assert before <= event.timestamp <= after


# =============================================
# MonitoringQueue TESTS
# =============================================


class TestMonitoringQueue:
    """Tests for the MonitoringQueue class."""

    def test_enqueue_returns_true(self, MonitoringQueue, MonitoringEvent):
        """Enqueuing an event to a running queue returns True."""
        q = MonitoringQueue()
        event = MonitoringEvent(priority=1, event_type="file", branch="PRAX", action="created")
        result = q.enqueue(event)
        assert result is True

    def test_enqueue_increments_size(self, MonitoringQueue, MonitoringEvent):
        """Each successful enqueue increases queue size by one."""
        q = MonitoringQueue()
        assert q.size() == 0
        q.enqueue(MonitoringEvent(priority=1, event_type="file", branch="A", action="x", message="m1"))
        assert q.size() == 1
        q.enqueue(MonitoringEvent(priority=2, event_type="log", branch="B", action="y", message="m2"))
        assert q.size() == 2

    def test_dequeue_returns_event(self, MonitoringQueue, MonitoringEvent):
        """Dequeue returns the enqueued event."""
        q = MonitoringQueue()
        event = MonitoringEvent(priority=1, event_type="module", branch="DRONE", action="loaded")
        q.enqueue(event)
        result = q.dequeue(timeout=1.0)
        assert result is not None
        assert result.event_type == "module"
        assert result.branch == "DRONE"
        assert result.action == "loaded"

    def test_dequeue_decrements_size(self, MonitoringQueue, MonitoringEvent):
        """Dequeue reduces queue size by one."""
        q = MonitoringQueue()
        q.enqueue(MonitoringEvent(priority=1, event_type="file", branch="A", action="x", message="u1"))
        q.enqueue(MonitoringEvent(priority=2, event_type="log", branch="B", action="y", message="u2"))
        assert q.size() == 2
        q.dequeue(timeout=1.0)
        assert q.size() == 1

    def test_enqueue_dequeue_roundtrip_preserves_data(self, MonitoringQueue, MonitoringEvent):
        """An event survives enqueue/dequeue with all fields intact."""
        q = MonitoringQueue()
        ts = datetime(2026, 3, 24, 10, 0, 0)
        original = MonitoringEvent(
            priority=2,
            timestamp=ts,
            event_type="command",
            branch="FLOW",
            action="executed",
            message="plan step done",
            level="info",
            caller="SEEDGO",
            pid=9999,
        )
        q.enqueue(original)
        retrieved = q.dequeue(timeout=1.0)
        assert retrieved.priority == 2
        assert retrieved.timestamp == ts
        assert retrieved.event_type == "command"
        assert retrieved.branch == "FLOW"
        assert retrieved.action == "executed"
        assert retrieved.message == "plan step done"
        assert retrieved.level == "info"
        assert retrieved.caller == "SEEDGO"
        assert retrieved.pid == 9999

    def test_priority_ordering_across_dequeues(self, MonitoringQueue, MonitoringEvent):
        """Events dequeue in priority order (lowest number first)."""
        q = MonitoringQueue()
        q.enqueue(MonitoringEvent(priority=3, event_type="info", branch="A", action="a", message="m_info"))
        q.enqueue(MonitoringEvent(priority=1, event_type="error", branch="B", action="b", message="m_error"))
        q.enqueue(MonitoringEvent(priority=2, event_type="warning", branch="C", action="c", message="m_warn"))

        first = q.dequeue(timeout=1.0)
        second = q.dequeue(timeout=1.0)
        third = q.dequeue(timeout=1.0)

        assert first.priority == 1
        assert first.event_type == "error"
        assert second.priority == 2
        assert second.event_type == "warning"
        assert third.priority == 3
        assert third.event_type == "info"

    def test_flush_clears_queue(self, MonitoringQueue, MonitoringEvent):
        """Flush empties the queue and returns nothing (size goes to 0)."""
        q = MonitoringQueue()
        for i in range(5):
            q.enqueue(MonitoringEvent(priority=i + 1, event_type="file", branch=f"B{i}", action="a", message=f"msg{i}"))
        assert q.size() == 5
        q.flush()
        assert q.size() == 0

    def test_flush_clears_recent_events(self, MonitoringQueue, MonitoringEvent):
        """Flush also clears the recent_events dedup list."""
        q = MonitoringQueue()
        q.enqueue(MonitoringEvent(priority=1, event_type="file", branch="X", action="a", message="flush_test"))
        assert len(q.recent_events) == 1
        q.flush()
        assert len(q.recent_events) == 0

    def test_size_accurate_after_mixed_operations(self, MonitoringQueue, MonitoringEvent):
        """Size stays accurate through a mix of enqueue, dequeue, and flush."""
        q = MonitoringQueue()
        q.enqueue(MonitoringEvent(priority=1, event_type="a", branch="A", action="x", message="s1"))
        q.enqueue(MonitoringEvent(priority=2, event_type="b", branch="B", action="y", message="s2"))
        q.enqueue(MonitoringEvent(priority=3, event_type="c", branch="C", action="z", message="s3"))
        assert q.size() == 3
        q.dequeue(timeout=1.0)
        assert q.size() == 2
        q.flush()
        assert q.size() == 0

    def test_stop_prevents_new_enqueues(self, MonitoringQueue, MonitoringEvent):
        """After stop(), enqueue returns False and does not add events."""
        q = MonitoringQueue()
        q.stop()
        result = q.enqueue(MonitoringEvent(priority=1, event_type="file", branch="X", action="a", message="blocked"))
        assert result is False
        assert q.size() == 0

    def test_stop_flushes_existing_events(self, MonitoringQueue, MonitoringEvent):
        """stop() flushes events that were already in the queue."""
        q = MonitoringQueue()
        q.enqueue(MonitoringEvent(priority=1, event_type="file", branch="Y", action="b", message="will_flush"))
        assert q.size() == 1
        q.stop()
        assert q.size() == 0

    def test_dequeue_empty_queue_returns_none(self, MonitoringQueue):
        """Dequeue on an empty queue waits for timeout then returns None."""
        q = MonitoringQueue()
        result = q.dequeue(timeout=0.05)
        assert result is None

    def test_duplicate_detection_same_event_within_one_second(self, MonitoringQueue, MonitoringEvent):
        """An identical event within 1 second is detected as duplicate and rejected."""
        q = MonitoringQueue()
        ts = datetime.now()
        event1 = MonitoringEvent(
            priority=1, timestamp=ts, event_type="file", branch="PRAX", action="modified", message="config changed"
        )
        event2 = MonitoringEvent(
            priority=1,
            timestamp=ts + timedelta(milliseconds=500),
            event_type="file",
            branch="PRAX",
            action="modified",
            message="config changed",
        )
        assert q.enqueue(event1) is True
        assert q.enqueue(event2) is False
        assert q.size() == 1

    def test_duplicate_detection_different_message_is_not_duplicate(self, MonitoringQueue, MonitoringEvent):
        """Events with different messages are not duplicates even if otherwise identical."""
        q = MonitoringQueue()
        ts = datetime.now()
        event1 = MonitoringEvent(
            priority=1, timestamp=ts, event_type="file", branch="PRAX", action="modified", message="first change"
        )
        event2 = MonitoringEvent(
            priority=1,
            timestamp=ts + timedelta(milliseconds=100),
            event_type="file",
            branch="PRAX",
            action="modified",
            message="second change",
        )
        assert q.enqueue(event1) is True
        assert q.enqueue(event2) is True
        assert q.size() == 2

    def test_duplicate_detection_same_event_after_one_second(self, MonitoringQueue, MonitoringEvent):
        """An identical event more than 1 second later is not a duplicate."""
        q = MonitoringQueue()
        ts = datetime.now()
        event1 = MonitoringEvent(
            priority=1, timestamp=ts, event_type="log", branch="DRONE", action="created", message="log entry"
        )
        event2 = MonitoringEvent(
            priority=1,
            timestamp=ts + timedelta(seconds=2),
            event_type="log",
            branch="DRONE",
            action="created",
            message="log entry",
        )
        assert q.enqueue(event1) is True
        assert q.enqueue(event2) is True
        assert q.size() == 2

    def test_recent_events_list_caps_at_100(self, MonitoringQueue, MonitoringEvent):
        """The recent_events dedup buffer never exceeds 100 entries."""
        q = MonitoringQueue()
        base_ts = datetime.now()
        for i in range(120):
            event = MonitoringEvent(
                priority=3,
                timestamp=base_ts + timedelta(seconds=i * 2),
                event_type="file",
                branch=f"B{i}",
                action="modified",
                message=f"unique_msg_{i}",
            )
            q.enqueue(event)
        assert len(q.recent_events) <= 100

    def test_maxsize_prevents_overflow(self, MonitoringQueue, MonitoringEvent):
        """A queue with maxsize=2 rejects the third enqueue."""
        q = MonitoringQueue(maxsize=2)
        base_ts = datetime.now()
        r1 = q.enqueue(
            MonitoringEvent(priority=1, timestamp=base_ts, event_type="a", branch="A", action="x", message="o1")
        )
        r2 = q.enqueue(
            MonitoringEvent(
                priority=2,
                timestamp=base_ts + timedelta(seconds=2),
                event_type="b",
                branch="B",
                action="y",
                message="o2",
            )
        )
        r3 = q.enqueue(
            MonitoringEvent(
                priority=3,
                timestamp=base_ts + timedelta(seconds=4),
                event_type="c",
                branch="C",
                action="z",
                message="o3",
            )
        )
        assert r1 is True
        assert r2 is True
        assert r3 is False
        assert q.size() == 2

    def test_thread_safety_concurrent_enqueues(self, MonitoringQueue, MonitoringEvent):
        """Multiple threads can enqueue concurrently without data loss."""
        q = MonitoringQueue(maxsize=500)
        base_ts = datetime.now()
        errors = []

        def enqueue_batch(start: int):
            for i in range(50):
                idx = start + i
                event = MonitoringEvent(
                    priority=3,
                    timestamp=base_ts + timedelta(seconds=idx * 2),
                    event_type="file",
                    branch=f"T{idx}",
                    action="modified",
                    message=f"thread_msg_{idx}",
                )
                try:
                    q.enqueue(event)
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=enqueue_batch, args=(i * 50,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert q.size() == 200

    def test_json_handler_called_on_enqueue(self, MonitoringQueue, MonitoringEvent, mock_prax_infrastructure):
        """json_handler.log_operation is called when an event is enqueued."""
        q = MonitoringQueue()
        event = MonitoringEvent(priority=1, event_type="module", branch="SEEDGO", action="loaded", message="jh_test")
        q.enqueue(event)
        mock_prax_infrastructure.json_handler.log_operation.assert_called()
        call_args = mock_prax_infrastructure.json_handler.log_operation.call_args
        assert call_args[0][0] == "event_queued"
        assert call_args[0][1]["event_type"] == "module"
        assert call_args[0][1]["branch"] == "SEEDGO"

    def test_dequeue_from_stopped_queue(self, MonitoringQueue, MonitoringEvent):
        """Dequeue on a stopped (and flushed) queue returns None."""
        q = MonitoringQueue()
        q.enqueue(MonitoringEvent(priority=1, event_type="file", branch="X", action="a", message="pre_stop"))
        q.stop()
        # Queue is stopped and flushed — dequeue returns None after short timeout
        result = q.dequeue(timeout=0.05)
        assert result is None
        assert q.size() == 0

    def test_flush_on_empty_queue(self, MonitoringQueue):
        """Flushing an empty queue returns without error and size stays 0."""
        q = MonitoringQueue()
        assert q.size() == 0
        q.flush()  # Should not raise
        assert q.size() == 0
        assert len(q.recent_events) == 0

    def test_enqueue_after_flush(self, MonitoringQueue, MonitoringEvent):
        """After a flush, the queue still accepts new events normally."""
        q = MonitoringQueue()
        q.enqueue(MonitoringEvent(priority=1, event_type="file", branch="A", action="x", message="before_flush"))
        assert q.size() == 1
        q.flush()
        assert q.size() == 0

        # Enqueue after flush should still work (queue not stopped, just cleared)
        base_ts = datetime.now() + timedelta(seconds=5)
        result = q.enqueue(
            MonitoringEvent(
                priority=2, timestamp=base_ts, event_type="log", branch="B", action="y", message="after_flush"
            )
        )
        assert result is True
        assert q.size() == 1

    def test_double_stop(self, MonitoringQueue):
        """Calling stop() twice does not raise an exception."""
        q = MonitoringQueue()
        q.stop()
        q.stop()  # Should not raise
        assert q._stopped.is_set()
        assert q.size() == 0


# =============================================
# OPERATOR-FACING DROP REPORT
# =============================================


class TestDropReportWording:
    """The drop report is read by the operator on screen, not by a developer.

    Patrick's ruling (2026-08-08): monitor lines name their subsystem in plain words
    and say WHAT happened, the IMPACT, and whether data is safe — never a bare
    exception repr. These pin the wording so it cannot regress to the old
    'Dropping events (...): Full()' line.
    """

    def _fill_and_overflow(self, MonitoringQueue, MonitoringEvent):
        """Return a size-1 queue that has just rejected an event, plus that event."""
        q = MonitoringQueue(maxsize=1)
        q.enqueue(MonitoringEvent(priority=1, event_type="log", branch="FIRST", message="in"))
        overflow = MonitoringEvent(priority=2, event_type="log", branch="DAEMON", message="dropped")
        assert q.enqueue(overflow) is False
        return q, overflow

    def test_overflow_report_is_plain_language(self, event_queue_module, MonitoringQueue, MonitoringEvent):
        """Full queue reports cause, count, data safety and latest branch — no repr."""
        q, _ = self._fill_and_overflow(MonitoringQueue, MonitoringEvent)

        reported = [str(c) for c in event_queue_module.logger.warning.call_args_list]
        assert len(reported) == 1
        line = reported[0]

        assert "Full()" not in line, "raw exception repr must never reach the operator"
        assert "queue is full" in line
        assert "1 events" in line
        assert "on-disk logs are complete" in line
        assert "DAEMON" in line

    def test_overflow_report_names_the_subsystem(self, event_queue_module, MonitoringQueue, MonitoringEvent):
        """The operator must know WHICH pipeline lost events, not just 'the queue'."""
        self._fill_and_overflow(MonitoringQueue, MonitoringEvent)

        line = str(event_queue_module.logger.warning.call_args_list[0])
        assert "live monitor display" in line
        assert "terminal monitor view" in line

    def test_overflow_does_not_use_error_level(self, event_queue_module, MonitoringQueue, MonitoringEvent):
        """A normal overflow is a warning, not an error — it is expected under load."""
        self._fill_and_overflow(MonitoringQueue, MonitoringEvent)
        assert event_queue_module.logger.error.call_count == 0

    def test_unexpected_failure_is_not_reported_as_overflow(self, event_queue_module, MonitoringQueue, MonitoringEvent):
        """A non-Full failure says it is a bug rather than claiming the queue filled up."""
        q = MonitoringQueue(maxsize=10)

        def boom(*_args, **_kwargs):
            raise TypeError("unorderable event")

        q.queue.put = boom
        event = MonitoringEvent(priority=1, event_type="log", branch="DAEMON", message="x")
        assert q.enqueue(event) is False

        assert event_queue_module.logger.warning.call_count == 0
        reported = [str(c) for c in event_queue_module.logger.error.call_args_list]
        assert len(reported) == 1
        line = reported[0]

        assert "TypeError" in line
        assert "not a normal full queue" in line
        assert "live monitor display" in line
        assert "on-disk logs are complete" in line
        assert "queue is full" not in line, "an unrelated bug must not be dressed up as overflow"

    def test_report_is_rate_limited_to_one_per_30s(self, event_queue_module, MonitoringQueue, MonitoringEvent):
        """Repeat overflows stay silent for 30s — this log is one prax itself watches."""
        q = MonitoringQueue(maxsize=1)
        q.enqueue(MonitoringEvent(priority=1, event_type="log", branch="FIRST", message="in"))
        for i in range(10):
            q.enqueue(MonitoringEvent(priority=2, event_type="log", branch="DAEMON", message=f"drop{i}"))

        assert event_queue_module.logger.warning.call_count == 1
        assert q._dropped == 9, "events after the report still counted for the next one"
