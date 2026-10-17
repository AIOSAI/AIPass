# =================== AIPass ====================
# Name: watcher.py
# Description: File System Watching
# Version: 1.6.0
# Created: 2025-11-26
# Modified: 2026-10-17
# =============================================

"""PRAX File Watcher (Handler)

Reference: docs/discovery.md"""

import logging
import threading
import time
from pathlib import Path

from datetime import datetime, timezone
from typing import Any

from watchdog.observers import Observer as WatchdogObserver
from watchdog.events import FileSystemEventHandler

from aipass.prax.apps.handlers.config.load import ECOSYSTEM_ROOT, get_system_logs_dir, get_module_logs_dir

from aipass.prax.apps.handlers.registry.load import load_module_registry
from aipass.prax.apps.handlers.registry.save import save_module_registry

from aipass.prax.apps.handlers.discovery.filtering import in_sandbox, should_ignore_path
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)


def _get_trigger() -> Any:
    """The trigger bus, or None when this host cannot hand us one.

    Imported here, never at module level: trigger imports prax's logger, which imports
    this module mid-init. OSError too: trigger's guard raises it with no readable cwd."""
    try:
        from aipass.trigger.apps.modules.core import trigger
    except (ImportError, OSError) as e:
        logger.info(f"[watcher] trigger module not available, falling back: {e}")
        return None
    return trigger


_observer: Any = None

# One scheduling thread at a time: a second would walk the tree for a watch the first installs.
_start_thread: Any = None

# _START_LOCK serialises the walk; _SPAWN_LOCK, the spawn decision only, is never held across it.
_START_LOCK = threading.Lock()
_SPAWN_LOCK = threading.Lock()

# A dispatcher death is silent, so we look; death_reported makes it fire once per death, not per check.
_LIVENESS_CHECK_INTERVAL_SEC = 60.0


class LivenessState:
    """Mutable bookkeeping for the liveness check."""

    def __init__(self) -> None:
        self.last_check = 0.0
        self.death_reported = False
        self.lock = threading.Lock()


_LIVENESS = LivenessState()


class PythonFileWatcher(FileSystemEventHandler):
    """Watch for new Python files (pure handler)"""

    def on_created(self, event):
        """Handle new file creation events.

        The whole body is guarded: watchdog's dispatcher catches only queue.Empty, so an
        escaping exception kills it silently and the event queue grows without bound."""
        try:
            self._register_created_module(event)
        except Exception as e:
            # Deliberately broad: a missed module is better than a dead dispatcher.
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

        if should_ignore_path(py_file) or in_sandbox(py_file, ECOSYSTEM_ROOT):
            return

        module_name = py_file.stem

        # None is an unreadable registry: saving this one module would replace every entry.
        modules = load_module_registry()
        if modules is None:
            logger.warning(f"[watcher] The module registry could not be read, so {py_file} was not registered")
            return
        if module_name in modules:
            return

        try:
            relative_path = py_file.relative_to(ECOSYSTEM_ROOT)
        except ValueError as e:
            logger.info(f"[watcher] Path outside ecosystem root, skipping {py_file}: {e}")
            return

        # One stat: the file may vanish mid-handler, the ordinary case, so it is
        # named here at INFO rather than reaching on_created's ERROR guard.
        try:
            stat_result = py_file.stat()
        except FileNotFoundError:
            logger.info(f"[watcher] {py_file} vanished before it could be registered — event dropped")
            return

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

        save_module_registry(modules)

        trigger = _get_trigger()
        if trigger is not None:
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
    """Start watching for new Python files, and WAIT for the watch to be in place.

    Serialised on _START_LOCK: two unserialised starts orphan an observer and deliver every event twice."""
    global _observer

    with _START_LOCK:
        if _observer and _observer.is_alive():
            return

        watcher = PythonFileWatcher()

        new_observer = WatchdogObserver()
        new_observer.schedule(watcher, str(ECOSYSTEM_ROOT), recursive=True)

        new_observer.start()
        _observer = new_observer
        _LIVENESS.death_reported = False  # New observer: a previous death is no longer the current state.

    # No "started" record: this runs on an unjoined daemon thread, so the write orphaned
    # staging temps at process exit, and nothing reads it. Do not restore it.


def start_file_watcher_in_background() -> None:
    """Start the watcher without making the caller wait for the inotify walk.

    The walk is one inotify syscall per directory and starves for the GIL under contention.
    Never raises: an unjoined thread has no caller to tell, so failures are logged."""
    global _start_thread

    def _schedule() -> None:
        try:
            start_file_watcher()
        except OSError as e:
            logger.warning("inotify limit reached, continuing without file watcher: %s", e)
        except Exception as e:  # a start failure must not kill an unjoined thread silently
            logger.error(f"[watcher] could not start the discovery watcher ({type(e).__name__}: {e})")

    with _SPAWN_LOCK:
        if _observer is not None and _observer.is_alive():
            return
        if _start_thread is not None and _start_thread.is_alive():
            return  # A walk is already under way; a second one installs nothing.

        _start_thread = threading.Thread(target=_schedule, name="prax-watcher-start", daemon=True)
        started = _start_thread

    # Outside both locks: the thread's first act is to take _START_LOCK.
    started.start()


def stop_file_watcher():
    """Stop the file watcher"""
    global _observer

    if _observer and _observer.is_alive():
        _observer.stop()
        _observer.join()
        _observer = None


def is_file_watcher_active() -> bool:
    """Check if file watcher is currently active"""
    return _observer is not None and _observer.is_alive()


def _report_watcher_death() -> None:
    """Say loudly that the watcher died. Best-effort; never raises."""
    queued = None
    try:
        queued = _observer.event_queue.qsize()
    except Exception as e:  # a missing diagnostic must not mask the report below
        logger.debug(f"[watcher] could not read queue depth for the death report: {e}")

    detail = "" if queued is None else f" ~{queued} events are queued with nobody draining them."
    logger.error(
        "[watcher] DISCOVERY WATCHER IS DEAD - the watchdog dispatcher thread has stopped in this "
        f"process, so no new Python module will be discovered until it restarts.{detail} "
        "Filesystem events accumulate in an unbounded queue while it stays dead, which shows up as "
        "steady memory growth (see DPLAN-0305). Restart this process to recover."
    )

    trigger = _get_trigger()
    if trigger is not None:
        try:
            trigger.fire("file_watcher_died", watch_root=str(ECOSYSTEM_ROOT), queued_events=queued)
        except Exception as e:  # a failed trigger must not silence the log line above
            logger.warning(f"[watcher] trigger.fire('file_watcher_died') failed: {e}")

    try:
        json_handler.log_operation(
            "discovery_watcher_event",
            {"action": "died", "watch_root": str(ECOSYSTEM_ROOT), "queued_events": queued},
        )
    except Exception as e:  # same reason
        logger.warning(f"[watcher] could not record watcher death: {e}")


def check_file_watcher_liveness(force: bool = False) -> bool:
    """Periodic health check: is the watcher we started still running?

    True when no watcher was started here. Throttled and never raises: the logger calls it."""
    try:
        if _observer is None:
            return True  # No watcher in this process - nothing to be dead.

        now = time.monotonic()

        # Lock-free fast path: this runs on every log call; a racy read costs one extra is_alive().
        if not force and (now - _LIVENESS.last_check) < _LIVENESS_CHECK_INTERVAL_SEC:
            return not _LIVENESS.death_reported

        with _LIVENESS.lock:
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
    except Exception as e:  # see docstring
        logger.warning(f"[watcher] liveness check itself failed: {e}")
        return True
