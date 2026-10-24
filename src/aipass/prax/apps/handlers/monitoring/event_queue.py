# =================== AIPass ====================
# Name: event_queue.py
# Description: Thread-Safe Event Queue
# Version: 0.2.0
# Created: 2025-11-23
# Modified: 2026-10-24
# =============================================

"""Thread-safe event coordination for monitoring system"""

from queue import Empty, Full, PriorityQueue
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import itertools
import threading
import time

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

_arrival = itertools.count()


@dataclass(order=True)
class MonitoringEvent:
    """Unified event structure for all monitoring sources"""

    priority: int = field(compare=True)
    # Second sort key: equal priorities leave the queue in arrival order.
    seq: int = field(compare=True, init=False, repr=False, default_factory=lambda: next(_arrival))
    timestamp: datetime = field(compare=False, default_factory=datetime.now)
    event_type: str = field(compare=False, default="")  # 'file', 'log', 'module', 'command'
    branch: str = field(compare=False, default="")
    action: str = field(compare=False, default="")  # 'created', 'modified', 'deleted', 'executed'
    message: str = field(compare=False, default="")
    level: str = field(compare=False, default="info")  # 'info', 'warning', 'error'
    caller: Optional[str] = field(compare=False, default=None)  # Branch that initiated command
    pid: Optional[int] = field(compare=False, default=None)  # Process ID of the agent

    def __post_init__(self):
        if self.priority == 0:  # Not set
            priority_map = {"error": 1, "warning": 2, "info": 3, "debug": 4}
            self.priority = priority_map.get(self.level, 3)


class MonitoringQueue:
    """Thread-safe event queue with deduplication"""

    def __init__(self, maxsize: int = 1000, scope=None):
        self.queue = PriorityQueue(maxsize=maxsize)
        self.recent_events = []  # For deduplication
        self.lock = threading.Lock()
        self._stopped = threading.Event()
        self._dropped = 0
        self._last_drop_warning = 0.0
        self._scope = scope  # BranchScope or None — set once at monitor start
        self._scope_suppressed = 0

    def set_scope(self, scope) -> None:
        """Restrict the queue to a branch scope (None clears it).

        Filtering at the queue, not the display, stops a noisy branch evicting wanted events.
        """
        self._scope = scope

    def suppressed_count(self) -> int:
        """Events kept off-screen by the branch scope (not lost data)."""
        return self._scope_suppressed

    def enqueue(self, event: MonitoringEvent, bypass_scope: bool = False) -> bool:
        """Add event to queue (thread-safe).

        bypass_scope is for the monitor's own health messages, which must reach the operator.
        """
        if self._stopped.is_set():
            return False

        scope = self._scope
        if not bypass_scope and scope is not None and not scope.matches_event(event):
            # Not a drop: kept out of the overflow counter, nothing failed.
            with self.lock:
                self._scope_suppressed += 1
            return False

        with self.lock:
            if self._is_duplicate(event):
                return False
            try:
                self.queue.put(event, block=False)
                self.recent_events.append(event)
                if len(self.recent_events) > 100:
                    self.recent_events.pop(0)
            except Exception as e:
                # Rate-limited: this warning lands in a log prax watches, so
                # per-event logging turns a full queue into a self-feeding firehose.
                self._dropped += 1
                now = time.monotonic()
                if now - self._last_drop_warning >= 30.0:
                    self._report_drops(e, event)
                    self._dropped = 0
                    self._last_drop_warning = now
                return False

        return True

    def _report_drops(self, exc: Exception, latest: MonitoringEvent) -> None:
        """Report skipped events to the operator in plain language.

        Full queue and unexpected failure stay separate: calling a bug an overflow hides it.
        """
        latest_desc = f"latest: {latest.event_type} from {latest.branch}"

        if isinstance(exc, Full):
            logger.warning(
                f"[event_queue] The live monitor display queue is full — {self._dropped} events "
                f"were skipped from the terminal monitor view since the last report ({latest_desc}). "
                f"Nothing is lost: the on-disk logs are complete."
            )
            return

        logger.error(
            f"[event_queue] The live monitor display could not queue an event — unexpected "
            f"{type(exc).__name__}, not a normal full queue ({latest_desc}); {self._dropped} events "
            f"were skipped from the terminal monitor view since the last report. The on-disk logs "
            f"are complete. This one is a bug."
        )

    def dequeue(self, timeout: float = 0.1) -> Optional[MonitoringEvent]:
        """Get next event from queue (thread-safe)"""
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None

    def flush(self):
        """Clear all events from queue"""
        with self.lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except Empty:
                    break
            self.recent_events.clear()

    def stop(self):
        """Stop accepting new events"""
        self._stopped.set()
        self.flush()

    def _is_duplicate(self, event: MonitoringEvent) -> bool:
        """Check if event duplicates recent event. Caller must hold self.lock."""
        for recent in self.recent_events[-10:]:
            if (
                recent.event_type == event.event_type
                and recent.branch == event.branch
                and recent.action == event.action
                and recent.message == event.message
                and abs((event.timestamp - recent.timestamp).total_seconds()) < 1
            ):
                return True
        return False

    def size(self) -> int:
        """Get current queue size"""
        return self.queue.qsize()
