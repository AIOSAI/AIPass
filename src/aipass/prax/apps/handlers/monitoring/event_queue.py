# =================== AIPass ====================
# Name: event_queue.py
# Description: Thread-Safe Event Queue
# Version: 0.1.1
# Created: 2025-11-23
# Modified: 2026-03-09
# =============================================

"""Thread-safe event coordination for monitoring system"""

from queue import Empty, PriorityQueue
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import threading
import time

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()


@dataclass(order=True)
class MonitoringEvent:
    """Unified event structure for all monitoring sources"""

    priority: int = field(compare=True)
    timestamp: datetime = field(compare=False, default_factory=datetime.now)
    event_type: str = field(compare=False, default="")  # 'file', 'log', 'module', 'command'
    branch: str = field(compare=False, default="")
    action: str = field(compare=False, default="")  # 'created', 'modified', 'deleted', 'executed'
    message: str = field(compare=False, default="")
    level: str = field(compare=False, default="info")  # 'info', 'warning', 'error'
    caller: Optional[str] = field(compare=False, default=None)  # Branch that initiated command
    pid: Optional[int] = field(compare=False, default=None)  # Process ID of the agent

    def __post_init__(self):
        # Convert level to priority number for queue ordering
        if self.priority == 0:  # Not set
            priority_map = {"error": 1, "warning": 2, "info": 3, "debug": 4}
            self.priority = priority_map.get(self.level, 3)


class MonitoringQueue:
    """Thread-safe event queue with deduplication"""

    def __init__(self, maxsize: int = 1000):
        self.queue = PriorityQueue(maxsize=maxsize)
        self.recent_events = []  # For deduplication
        self.lock = threading.Lock()
        self._stopped = threading.Event()
        self._dropped = 0
        self._last_drop_warning = 0.0

    def enqueue(self, event: MonitoringEvent) -> bool:
        """Add event to queue (thread-safe)"""
        if self._stopped.is_set():
            return False

        # Simple deduplication + queue put under single lock
        with self.lock:
            if self._is_duplicate(event):
                return False
            try:
                self.queue.put(event, block=False)
                self.recent_events.append(event)
                if len(self.recent_events) > 100:
                    self.recent_events.pop(0)
            except Exception as e:
                # Rate-limited on purpose: this warning lands in a log prax itself
                # watches, so per-event logging turns a full queue into a
                # self-feeding firehose — every warning spawns a new log event
                # that also fails to enqueue (live-caught 2026-07-31, 20-80
                # warnings/sec sustained). queue.Full has an empty str(), hence !r.
                self._dropped += 1
                now = time.monotonic()
                if now - self._last_drop_warning >= 30.0:
                    logger.warning(
                        f"[event_queue] Dropping events ({self._dropped} since last report; "
                        f"latest type={event.event_type}, branch={event.branch}): {e!r}"
                    )
                    self._dropped = 0
                    self._last_drop_warning = now
                return False

        # Outside the lock, and only for events that actually queued — logging
        # per *attempt* was another per-event write into a watched log.
        json_handler.log_operation("event_queued", {"event_type": event.event_type, "branch": event.branch})
        return True

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


# Global instance for the monitoring system
global_queue = MonitoringQueue()
