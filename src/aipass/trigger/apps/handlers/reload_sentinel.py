# =================== AIPass ====================
# Name: reload_sentinel.py
# Description: Restarts the log watcher when its own handler code changes on disk
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Reload sentinel — keeps the running watcher on the shipped code.

The log watcher is a long-running process. It imports trigger's handler modules
once at startup and holds them in memory for as long as it runs; editing a
handler on disk changes precisely nothing until the process restarts. That gap
has cost this branch twice, most expensively on 2026-08-11, when a signature fix
sat unloaded for 25 hours while the branch reported it shipped and the operator
read the continuing noise as the fix being incomplete.

The obvious remedy — "remember to restart after shipping" — is a human
remembering something, which is the mechanism that already failed. This module
makes the process notice for itself.

Deliberately NOT importlib.reload(). Handlers register callbacks on the event
bus and hold module-level state; reloading a module in place leaves the bus
pointing at the old function objects and the new module holding fresh state.
A process restart has none of those failure modes: the supervisor starts a new
interpreter that imports everything exactly once, from disk.

Two guards make this safe rather than merely clever:

  SETTLE — a change is ignored until its mtime has stopped moving. An editor
  mid-save would otherwise restart the watcher into a half-written module.

  SUPERVISION — an unsupervised process never exits. Under systemd a restart
  costs ten seconds; run by hand, exiting would stop log watching altogether,
  trading a stale watcher for no watcher. That is strictly worse and this
  module will not do it.
"""

import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger
from aipass.trigger.apps.handlers.json import json_handler

logger = trail_logger(TRIGGER_ROOT / "logs" / "reload_sentinel.jsonl")

# The code the watcher actually loads: event handlers and the modules behind
# them. Deliberately not the whole branch — tests, docs and JSON state churn
# constantly and none of it is imported by the running process.
WATCHED_ROOTS: Tuple[Path, ...] = (
    TRIGGER_ROOT / "apps" / "handlers",
    TRIGGER_ROOT / "apps" / "modules",
)

# How long a file must sit unmodified before its change is believed. Long
# enough to outlast an editor writing a file, short enough that a ship is live
# within a minute of landing.
SETTLE_SECONDS = 15.0

# How often the loop looks. Cheap — an mtime stat over a few dozen files.
CHECK_INTERVAL_SECONDS = 30.0

# The systemd unit ships `Restart=on-failure`, so exiting 0 would be read as a
# clean shutdown and the watcher would simply stay down. 75 is EX_TEMPFAIL:
# "temporary failure, the user is invited to retry", which is exactly the
# request being made. If the unit ever moves to Restart=always, this should
# become 0 and the two must change together — a test pins that pairing.
RELOAD_EXIT_CODE = 75


def _scan_root(root: Path, seen: Dict[Path, float]) -> None:
    """Record every Python module under *root* into *seen*.

    Args:
        root: Directory to walk
        seen: Accumulator mapping module path to mtime, mutated in place
    """
    try:
        for path in root.rglob("*.py"):
            try:
                seen[path] = path.stat().st_mtime
            except OSError as exc:
                # Vanished between listing and stat — a rename in flight. Its
                # absence is itself a change and the next pass will see it.
                logger.warning(f"skipping {path.name}, gone before stat: {exc}")
    except OSError as exc:
        logger.warning(f"cannot read watched root {root}: {exc}")


def snapshot() -> Dict[Path, float]:
    """Record the modification time of every Python module the watcher loads.

    Returns:
        Mapping of module path to mtime; empty when no watched root exists
    """
    seen: Dict[Path, float] = {}
    for root in WATCHED_ROOTS:
        _scan_root(root, seen)
    return seen


def changed_since(baseline: Dict[Path, float]) -> List[Path]:
    """Return the modules that have changed AND settled since *baseline*.

    Args:
        baseline: A previous snapshot() result

    Returns:
        Sorted paths whose mtime differs from the baseline and has since
        stopped moving; additions and removals both count as changes
    """
    current = snapshot()
    cutoff = time.time() - SETTLE_SECONDS
    changed: List[Path] = []

    for path, mtime in current.items():
        if baseline.get(path) == mtime:
            continue
        # Still being written, or written so recently that more may follow.
        # Left for a later pass rather than acted on now.
        if mtime > cutoff:
            continue
        changed.append(path)

    # A handler that was renamed or archived is gone from `current` entirely.
    # There is no mtime left to settle, so it counts immediately.
    changed.extend(path for path in baseline if path not in current)

    return sorted(changed)


def is_supervised() -> bool:
    """Whether something will restart this process if it exits.

    systemd sets INVOCATION_ID for every service it starts, so its presence is
    a direct answer rather than an inference about the parent process.

    Returns:
        True when running under a supervisor that will bring the process back
    """
    return bool(os.environ.get("INVOCATION_ID"))


def evaluate(baseline: Dict[Path, float]) -> bool:
    """Decide whether the process should exit to pick up changed code.

    Args:
        baseline: The snapshot taken when the current code was loaded

    Returns:
        True when a settled change exists AND a supervisor will restart us
    """
    changed = changed_since(baseline)
    if not changed:
        return False

    names = ", ".join(path.name for path in changed)
    if not is_supervised():
        # Loud, and only ever loud: stopping here would end log watching.
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

    The baseline is taken HERE rather than at import time, so it describes the
    code this process actually loaded.

    Args:
        stop_event: Set by the caller's shutdown path; also set by this loop
            when a reload is warranted, so the service's existing wait() wakes
            through the ordinary route instead of a second signalling channel

    Returns:
        A predicate the caller checks after its wait() returns: True when the
        loop asked for a reload, False when this was an ordinary shutdown
    """
    baseline = snapshot()
    requested = threading.Event()

    def _loop() -> None:
        # wait() doubles as the sleep, so a SIGTERM during the interval ends
        # the thread immediately instead of after a full check period.
        while not stop_event.wait(CHECK_INTERVAL_SECONDS):
            try:
                if evaluate(baseline):
                    requested.set()
                    stop_event.set()
                    return
            except Exception as exc:
                # A sentinel that crashes must not take log watching with it.
                logger.warning(f"reload check failed, watcher continues on current code: {exc}")

    threading.Thread(target=_loop, name="reload-sentinel", daemon=True).start()
    return requested.is_set
