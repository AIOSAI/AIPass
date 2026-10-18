# =================== AIPass ====================
# Name: reload_sentinel.py
# Description: Restarts the log watcher when its own handler code changes on disk
# Version: 1.1.0
# Created: 2026-08-12
# Modified: 2026-10-17
# =============================================

"""Reload sentinel — keeps the running watcher on the shipped code.

Restarts the process, never importlib.reload(): the bus would keep old callbacks."""

import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger
from aipass.trigger.apps.handlers.json import json_handler

logger = trail_logger(TRIGGER_ROOT / "logs" / "reload_sentinel.jsonl")

WATCHED_ROOTS: Tuple[Path, ...] = (
    TRIGGER_ROOT / "apps" / "handlers",
    TRIGGER_ROOT / "apps" / "modules",
)

# Outlasts an editor mid-save, so the watcher never restarts into a half-written module.
SETTLE_SECONDS = 15.0

CHECK_INTERVAL_SECONDS = 30.0

# EX_TEMPFAIL: the unit has Restart=on-failure, so exit 0 would leave the watcher
# down. Changes together with the unit's Restart= policy; a test pins the pair.
RELOAD_EXIT_CODE = 75


SKIPPED_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def _scan_root(root: Path, seen: Dict[Path, float]) -> None:
    """Record every Python module under *root* into *seen*, sandboxes left out.

    Skips match only parts below *root*, so a root under a dropbox still shows."""
    try:
        for path in root.rglob("*.py"):
            if SKIPPED_DIRS.intersection(path.relative_to(root).parts):
                continue
            try:
                seen[path] = path.stat().st_mtime
            except OSError as exc:
                logger.warning(f"skipping {path.name}, gone before stat: {exc}")
    except OSError as exc:
        logger.warning(f"cannot read watched root {root}: {exc}")


def snapshot() -> Dict[Path, float]:
    """Record the modification time of every Python module the watcher loads."""
    seen: Dict[Path, float] = {}
    for root in WATCHED_ROOTS:
        _scan_root(root, seen)
    return seen


def changed_since(baseline: Dict[Path, float]) -> List[Path]:
    """Return the modules that have changed AND settled since *baseline*."""
    current = snapshot()
    cutoff = time.time() - SETTLE_SECONDS
    changed: List[Path] = []

    for path, mtime in current.items():
        if baseline.get(path) == mtime:
            continue
        if mtime > cutoff:
            continue
        changed.append(path)

    # A removed module has no mtime left to settle, so it counts at once.
    changed.extend(path for path in baseline if path not in current)

    return sorted(changed)


def is_supervised() -> bool:
    """Whether something will restart this process if it exits.

    systemd sets INVOCATION_ID for every service it starts."""
    return bool(os.environ.get("INVOCATION_ID"))


def evaluate(baseline: Dict[Path, float]) -> bool:
    """Decide whether the process should exit to pick up changed code."""
    changed = changed_since(baseline)
    if not changed:
        return False

    names = ", ".join(path.name for path in changed)
    if not is_supervised():
        # Never exit unsupervised: nothing would restart log watching.
        logger.warning(
            f"handler code changed on disk ({names}) but this process is not supervised — "
            f"still running the OLD code. Restart it to load the change."
        )
        return False

    logger.warning(f"handler code changed on disk ({names}) — exiting {RELOAD_EXIT_CODE} so the supervisor reloads it")
    json_handler.log_operation(
        "watcher_reload_requested",
        {"success": True, "files": [path.name for path in changed], "exit_code": RELOAD_EXIT_CODE},
    )
    return True


def start(stop_event: threading.Event) -> Callable[[], bool]:
    """Watch for settled handler changes until *stop_event* is set.

    Sets *stop_event* itself on a reload; the returned predicate tells reload from shutdown."""
    baseline = snapshot()
    requested = threading.Event()

    def _loop() -> None:
        while not stop_event.wait(CHECK_INTERVAL_SECONDS):
            try:
                if evaluate(baseline):
                    requested.set()
                    stop_event.set()
                    return
            except Exception as exc:
                logger.warning(f"reload check failed, watcher continues on current code: {exc}")

    threading.Thread(target=_loop, name="reload-sentinel", daemon=True).start()
    return requested.is_set
