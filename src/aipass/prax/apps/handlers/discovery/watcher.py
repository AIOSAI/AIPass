# =================== AIPass ====================
# Name: watcher.py
# Description: File System Watching
# Version: 1.2.0
# Created: 2025-11-26
# Modified: 2026-03-09
# =============================================

"""
PRAX File Watcher (Handler)

Pure worker that watches for new Python files and updates module registry.
Memory file handling moved to memory branch's own watcher.

No console output - follows 3-tier handler pattern.
"""

import logging

logger = logging.getLogger(__name__)

import threading
import time
from pathlib import Path

from datetime import datetime, timezone
from typing import Any

from watchdog.observers import Observer as WatchdogObserver
from watchdog.events import FileSystemEventHandler

# Import from prax config
from aipass.prax.apps.handlers.config.load import ECOSYSTEM_ROOT, get_system_logs_dir, get_module_logs_dir

# Import from prax registry handlers
from aipass.prax.apps.handlers.registry.load import load_module_registry
from aipass.prax.apps.handlers.registry.save import save_module_registry

# Import filtering
from aipass.prax.apps.handlers.discovery.filtering import should_ignore_path
from aipass.prax.apps.handlers.json import json_handler

# Trigger integration - graceful fallback if trigger not available.
#
# The except is (ImportError, OSError), matching modules/logger.py's own trigger
# import, and the second half is not decoration. MEASURED 2026-08-31: @trigger's
# handlers/__init__.py guard resolves a frame filename at import time, and in a
# process with no readable working directory that raises FileNotFoundError — an
# OSError, never an ImportError. So this clause, which exists precisely to say
# "we can live without trigger", let a failure in the dependency we can live
# without kill the import of every prax consumer, including the fleet's logger.
#
# The rule that fixed it: an optional dependency's fallback must be at least as
# wide as the failures its import can produce. A peer branch being broken is
# allowed; us dying of it is not.
try:
    from aipass.trigger.apps.modules.core import trigger

    _HAS_TRIGGER = True
except (ImportError, OSError) as e:
    logger.info(f"[watcher] trigger module not available, falling back: {e}")
    trigger = None  # type: ignore[assignment]
    _HAS_TRIGGER = False

# Global observer instance
_observer: Any = None

# Liveness state. The dispatcher dying is silent by construction (watchdog lets
# the thread die and logs nothing to us), so the only way anyone learns about it
# is if we look. `_LIVENESS.death_reported` makes the report fire ONCE per death
# rather than once per check — prax owns the runaway-log detector, so a health check
# that floods the log it monitors would be its own bug.
_LIVENESS_CHECK_INTERVAL_SEC = 60.0


class LivenessState:
    """Mutable bookkeeping for the liveness check.

    A holder rather than three module-level names: these are mutable state, not
    constants, and naming them like module globals both reads wrong and forces a
    `global` statement at every write site.
    """

    def __init__(self) -> None:
        self.last_check = 0.0
        self.death_reported = False
        self.lock = threading.Lock()


_LIVENESS = LivenessState()


class PythonFileWatcher(FileSystemEventHandler):
    """Watch for new Python files (pure handler)"""

    def on_created(self, event):
        """Handle new file creation events.

        THE WHOLE BODY IS GUARDED, and that is the point — not defensive habit.
        watchdog's dispatcher (`observers/api.py::EventDispatcher.run`) catches
        ONLY `queue.Empty`, so any exception escaping this method kills the
        dispatcher thread permanently and SILENTLY. The emitter and inotify
        threads keep filling an UNBOUNDED EventQueue that nobody drains again,
        so the process retains every filesystem event in the ecosystem forever.

        That is not hypothetical. 2026-08-18 02:19, an archived probe file
        (`api/.../.archive/probe.py`) was created and deleted inside the same
        second; `stat()` on the vanished path raised FileNotFoundError from the
        line below; six long-running processes lost their dispatcher at the same
        instant and grew to ~2.3GB each (13.7 of 15GB, swap full) over 15 hours
        with nothing logged. One missing `except` ate the machine.

        A discovery handler must never be able to kill its own thread. Discovery
        is best-effort by nature: the file it describes is a moving target, and
        losing one module registration is a rounding error next to losing the
        watcher. So every failure here is reported and swallowed.
        """
        try:
            self._register_created_module(event)
        except Exception as e:
            # Deliberately broad: see the docstring. The alternative to
            # swallowing an unknown error here is a dead dispatcher and an
            # unbounded queue, which is strictly worse than a missed module.
            logger.error(
                f"[watcher] on_created failed for {getattr(event, 'src_path', '<unknown>')} "
                f"({type(e).__name__}: {e}) — event dropped, watcher still alive",
                exc_info=True,
            )

    def _register_created_module(self, event):
        """Register a newly created .py file. May raise; the caller guards."""
        if event.is_directory or not str(event.src_path).endswith(".py"):
            return

        py_file = Path(str(event.src_path))

        # Skip ignored paths
        if should_ignore_path(py_file):
            return

        module_name = py_file.stem

        # Skip if already in registry
        modules = load_module_registry()
        if module_name in modules:
            return

        # Add new module to registry
        try:
            relative_path = py_file.relative_to(ECOSYSTEM_ROOT)
        except ValueError as e:
            # File is outside ECOSYSTEM_ROOT, skip
            logger.info(f"[watcher] Path outside ecosystem root, skipping {py_file}: {e}")
            return

        # ONE stat, not two. The file that reaches this line is a file some other
        # process just created, so it may vanish mid-handler; two stat() calls are
        # two chances to lose the race and describe a file with a half-torn read.
        stat_result = py_file.stat()

        modules[module_name] = {
            "file_path": str(py_file),
            "relative_path": str(relative_path),
            "system_log_file": str(get_system_logs_dir() / f"prax_{module_name}.log"),
            "log_file": str(get_module_logs_dir("prax") / f"{module_name}.log"),
            "discovered_time": datetime.now(timezone.utc).isoformat(),
            "size": stat_result.st_size,
            "modified_time": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
            "enabled": True,
        }

        # Save updated registry
        save_module_registry(modules)

        # Fire trigger event for module discovery
        if _HAS_TRIGGER and trigger is not None:
            try:
                trigger.fire(
                    "module_discovered",
                    module_name=module_name,
                    file_path=str(py_file),
                    relative_path=str(relative_path),
                )
            except Exception as e:
                logger.warning(f"[watcher] trigger.fire('module_discovered') failed for {module_name}: {e}")


def start_file_watcher():
    """Start watching for new Python files

    Starts watchdog observer to monitor ECOSYSTEM_ROOT for new Python modules.
    """
    global _observer

    if _observer and _observer.is_alive():
        return

    # Create watcher instance
    watcher = PythonFileWatcher()

    new_observer = WatchdogObserver()
    # Watch ecosystem root for Python files (recursive)
    new_observer.schedule(watcher, str(ECOSYSTEM_ROOT), recursive=True)

    new_observer.start()
    _observer = new_observer
    _LIVENESS.death_reported = False  # New observer: a previous death is no longer the current state.
    json_handler.log_operation("discovery_watcher_event", {"action": "started", "watch_root": str(ECOSYSTEM_ROOT)})


def stop_file_watcher():
    """Stop the file watcher"""
    global _observer

    if _observer and _observer.is_alive():
        _observer.stop()
        _observer.join()
        _observer = None


def is_file_watcher_active() -> bool:
    """Check if file watcher is currently active

    Returns:
        True if watcher is running, False otherwise
    """
    return _observer is not None and _observer.is_alive()


def _report_watcher_death() -> None:
    """Say loudly that the watcher died. Best-effort; never raises.

    Reached only when an observer we started is no longer alive, which after the
    `on_created` guard should be unreachable through our own handler — so if this
    ever fires, it is news.
    """
    queued = None
    try:
        queued = _observer.event_queue.qsize()
    except Exception as e:  # noqa: BLE001 - a missing diagnostic must not mask the report below
        logger.debug(f"[watcher] could not read queue depth for the death report: {e}")

    detail = "" if queued is None else f" ~{queued} events are queued with nobody draining them."
    logger.error(
        "[watcher] DISCOVERY WATCHER IS DEAD - the watchdog dispatcher thread has stopped in this "
        f"process, so no new Python module will be discovered until it restarts.{detail} "
        "Filesystem events accumulate in an unbounded queue while it stays dead, which shows up as "
        "steady memory growth (see DPLAN-0305). Restart this process to recover."
    )

    if _HAS_TRIGGER and trigger is not None:
        try:
            trigger.fire("file_watcher_died", watch_root=str(ECOSYSTEM_ROOT), queued_events=queued)
        except Exception as e:  # noqa: BLE001 - a failed trigger must not silence the log line above
            logger.warning(f"[watcher] trigger.fire('file_watcher_died') failed: {e}")

    try:
        json_handler.log_operation(
            "discovery_watcher_event",
            {"action": "died", "watch_root": str(ECOSYSTEM_ROOT), "queued_events": queued},
        )
    except Exception as e:  # noqa: BLE001 - same reason
        logger.warning(f"[watcher] could not record watcher death: {e}")


def check_file_watcher_liveness(force: bool = False) -> bool:
    """Periodic health check: is the watcher we started still running?

    Returns True when healthy (or when no watcher was ever started here, which is
    a legitimate state - not every process runs one).

    Throttled to one real check per `_LIVENESS_CHECK_INTERVAL_SEC` because this
    sits on the logging path, which is the hottest path in the ecosystem. Never
    raises: this is called *by* the logger, and a health check that breaks
    logging is worse than the condition it detects.

    WHY THIS EXISTS SEPARATELY FROM `is_file_watcher_active`: that predicate was
    already called, but only from `SystemLogger._ensure_watcher`, whose body runs
    exactly ONCE per process behind a `_watcher_started` flag that is never
    reset. It therefore answered at the one moment the watcher could not yet have
    died, and never again. On 2026-08-18 the dispatcher died at 02:19 and no
    process noticed for 15 hours. A check that cannot fire after startup is not
    a liveness check.
    """
    try:
        if _observer is None:
            return True  # No watcher in this process - nothing to be dead.

        now = time.monotonic()

        # Lock-free fast path. This runs on every log call in the ecosystem, so
        # the common answer ("checked recently") must not touch a lock; a float
        # read is atomic under CPython and the worst case of a torn schedule is
        # one redundant is_alive() call.
        if not force and (now - _LIVENESS.last_check) < _LIVENESS_CHECK_INTERVAL_SEC:
            return not _LIVENESS.death_reported

        with _LIVENESS.lock:
            # Re-check under the lock: another thread may have just done it.
            if not force and (now - _LIVENESS.last_check) < _LIVENESS_CHECK_INTERVAL_SEC:
                return not _LIVENESS.death_reported
            _LIVENESS.last_check = now

            if _observer.is_alive():
                _LIVENESS.death_reported = False  # A fresh observer clears the latch.
                return True

            if _LIVENESS.death_reported:
                return False  # Already announced; do not flood.
            _LIVENESS.death_reported = True

        _report_watcher_death()
        return False
    except Exception as e:  # noqa: BLE001 - see docstring
        logger.warning(f"[watcher] liveness check itself failed: {e}")
        return True
