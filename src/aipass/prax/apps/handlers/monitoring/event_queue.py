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

    def enqueue(self, event: MonitoringEvent) -> bool:
        """Add event to queue (thread-safe)"""
        if self._stopped.is_set():
            return False

        json_handler.log_operation("event_queued", {"event_type": event.event_type, "branch": event.branch})

        # Simple deduplication + queue put under single lock
        with self.lock:
            if self._is_duplicate(event):
                return False
            try:
                self.queue.put(event, block=False)
                self.recent_events.append(event)
                if len(self.recent_events) > 100:
                    self.recent_events.pop(0)
                return True
            except Exception as e:
                logger.warning(
                    f"[event_queue] Failed to enqueue event (type={event.event_type}, branch={event.branch}): {e}"
                )
                return False

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
