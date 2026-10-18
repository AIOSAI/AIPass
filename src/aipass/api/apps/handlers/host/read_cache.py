# =================== AIPass ====================
# Name: read_cache.py
# Description: Host API Read Cache Handler — single-flight and TTL for expensive reads
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-10-17
# =============================================

"""Host API Read Cache Handler"""

import copy
import threading
import time
from typing import Any, Callable, Dict, Hashable, Optional

from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger


class ReadCache:
    """A keyed cache that coalesces concurrent misses into one producer call."""

    def __init__(self, name: str, ttl_seconds: float) -> None:
        self.name = name
        self.ttl_seconds = ttl_seconds
        self._entries: Dict[Hashable, tuple] = {}
        # Counter, not clock: a tie or frozen clock must not hand a later arrival an earlier failure.
        self._failures: Dict[Hashable, tuple] = {}
        self._failure_count = 0
        self._flights: Dict[Hashable, threading.Lock] = {}
        self._guard = threading.Lock()

    def clear(self) -> None:
        """Forget every stored answer."""
        with self._guard:
            dropped = len(self._entries)
            self._entries.clear()
            self._failures.clear()

        json_handler.log_operation(
            "host_api_read_cache_cleared",
            {"cache": self.name, "dropped": dropped},
        )

    def get(self, key: Hashable, producer: Callable[[], Any]) -> Any:
        """The answer for one key, produced at most once across concurrent callers.
        A deep copy: a stored row one caller edits would change for everyone until the TTL ends."""
        cached = self._fresh(key)
        if cached is not None:
            return cached

        with self._guard:
            arrived = self._failure_count
        with self._flight_lock(key):
            # Asked again inside the lock: re-running the read the flight ahead just ran is the stampede.
            cached = self._fresh(key)
            if cached is not None:
                return cached

            # Never cached, but a failure that ended after this caller arrived is shared: else N serial timeouts.
            with self._guard:
                failed = self._failures.get(key)
            if failed is not None and failed[0] > arrived:
                raise failed[1]
            with self._guard:
                self._failures.pop(key, None)

            try:
                answer = producer()
            except Exception as failure:
                with self._guard:
                    self._failure_count += 1
                    self._failures[key] = (self._failure_count, failure)
                # The key: two keys that resolve to one directory log alike in the caller's own line.
                logger.warning("[host_api] the %s read failed for key %r: %s", self.name, key, type(failure).__name__)
                raise
            with self._guard:
                self._entries[key] = (time.monotonic(), copy.deepcopy(answer))
            return answer

    def _flight_lock(self, key: Hashable) -> threading.Lock:
        """The lock that makes one key's read single-flight.
        Per key, not global: a slow read of one key must not queue every other key."""
        with self._guard:
            return self._flights.setdefault(key, threading.Lock())

    def _fresh(self, key: Hashable) -> Optional[Any]:
        """The stored answer for one key, if it is still young enough.
        Monotonic, never wall clock: a clock step must not resurrect or expire an entry."""
        with self._guard:
            entry = self._entries.get(key)
        if entry is None:
            return None

        stored_at, answer = entry
        if time.monotonic() - stored_at > self.ttl_seconds:
            return None
        return copy.deepcopy(answer)
