# =================== AIPass ====================
# Name: read_cache.py
# Description: Host API Read Cache Handler — single-flight and TTL for expensive reads
# Version: 1.0.0
# Created: 2026-09-07
# Modified: 2026-09-07
# =============================================

"""
Host API Read Cache Handler

One expensive read, asked N times at once, run once. This is the mechanism
behind git_reads.py's change list, split out of it on 2026-09-07 when that file
crossed the 1500-line cap — but the split is not only bookkeeping: fleet.py had
already grown its own copy of exactly this for @baud's snapshot, so the shape
was proven twice before it had a name.

WHAT IT IS FOR, measured 2026-09-07. The phone walks the roster and asks one
question per branch, so a single screen becomes N concurrent reads in the same
instant. One read of the git change list costs 0.5s alone; twenty concurrent
cost 13.8s and thirty-one cost 17.9s on an idle box, and at 12:17:03 that day
thirty-one of them crossed a 30s timeout together under boot-window load. The
lane was never slow. It was N subprocesses fighting over one machine.

TWO HALVES, BOTH REQUIRED. The TTL kills the cost of a caller that re-polls;
the single flight kills the stampede a screen full of cards makes at once.
Either alone leaves half the incident in place — a TTL still lets the first N
callers of a cold key each run their own subprocess, and a flight alone pays
again the moment the phone refreshes.

A FAILURE IS NEVER CACHED. Only a value that came back is stored, so a key
whose read raised is retried on the very next call rather than being refused
for the rest of the TTL. Concurrent callers still SHARE the failed flight,
which is the part that matters: it stops N callers each waiting out their own
timeout, without turning one bad second into a cached refusal.

Classes:
    ReadCache - A keyed single-flight + TTL cache around one producer call
"""

import copy
import threading
import time
from typing import Any, Callable, Dict, Hashable, Optional

from aipass.api.apps.handlers.json import json_handler


class ReadCache:
    """
    A keyed cache that coalesces concurrent misses into one producer call.

    Not a general memoiser: it exists for reads that are expensive because they
    leave the process (a subprocess, a socket), where the cost of asking twice
    is measured in seconds rather than cycles.

    Attributes:
        name: Which cache this is, for the operation log.
        ttl_seconds: How long a stored answer stays fresh.
    """

    def __init__(self, name: str, ttl_seconds: float) -> None:
        """
        Args:
            name: Short identifier for the log line. A process can hold several
                of these, and "a cache was dropped" is not a useful sentence
                when it does not say which one.
            ttl_seconds: Freshness window for a stored answer. Short enough
                that nobody watching a screen sees a stale number; long enough
                that one screen's worth of callers costs one producer call per
                distinct question.
        """
        self.name = name
        self.ttl_seconds = ttl_seconds
        self._entries: Dict[Hashable, tuple] = {}
        self._flights: Dict[Hashable, threading.Lock] = {}
        self._guard = threading.Lock()

    def clear(self) -> None:
        """
        Forget every stored answer.

        For a caller that just CHANGED what the read reports, and for a test
        suite that needs a clean slate — one case's answer silently satisfying
        the next is the failure mode this prevents.

        Logged, and the hits/misses are not: this is the rare event, and it is
        the one an operator needs when asking why a number moved or did not.
        """
        with self._guard:
            dropped = len(self._entries)
            self._entries.clear()

        json_handler.log_operation(
            "host_api_read_cache_cleared",
            {"cache": self.name, "dropped": dropped},
        )

    def get(self, key: Hashable, producer: Callable[[], Any]) -> Any:
        """
        The answer for one key, produced at most once across concurrent callers.

        Args:
            key: Anything hashable that identifies the question. Normalise it
                BEFORE calling: two spellings of one question must not each pay
                for a producer call.
            producer: Zero-argument callable that does the expensive read. Run
                only on a miss, and only by the first caller to arrive.

        Returns:
            A DEEP COPY of the answer. The copy is the point when the answer
            carries mutable rows: handing back the stored object lets the first
            caller who edits a row edit it for everyone until the TTL runs out
            — silently, and only under the concurrency this exists to serve.

        Raises:
            Whatever `producer` raises, to the caller that ran it and to every
            caller sharing its flight. Nothing is stored on that path.
        """
        cached = self._fresh(key)
        if cached is not None:
            return cached

        with self._flight_lock(key):
            # Asked again INSIDE the lock: whoever we queued behind has just
            # filled it, and re-running the read they already ran IS the
            # stampede this class exists to stop.
            cached = self._fresh(key)
            if cached is not None:
                return cached

            answer = producer()
            with self._guard:
                self._entries[key] = (time.monotonic(), copy.deepcopy(answer))
            return answer

    def _flight_lock(self, key: Hashable) -> threading.Lock:
        """
        The lock that makes one key's read single-flight.

        Args:
            key: The question being asked.

        Returns:
            A lock unique to that key, created on first use. Per key and not
            global: a slow read of one key must not queue every other key
            behind it, which would turn a stampede into a traffic jam.
        """
        with self._guard:
            return self._flights.setdefault(key, threading.Lock())

    def _fresh(self, key: Hashable) -> Optional[Any]:
        """
        The stored answer for one key, if it is still young enough.

        Args:
            key: The question being asked.

        Returns:
            A deep copy of the answer, or None when absent or expired.

        Note:
            monotonic, never wall clock: a clock step must not resurrect or
            expire an entry.
        """
        with self._guard:
            entry = self._entries.get(key)
        if entry is None:
            return None

        stored_at, answer = entry
        if time.monotonic() - stored_at > self.ttl_seconds:
            return None
        return copy.deepcopy(answer)
