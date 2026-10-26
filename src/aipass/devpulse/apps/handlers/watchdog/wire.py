# =================== AIPass ====================
# Name: wire.py
# Description: Watchdog Wire Handler — deliver MY dispatch completions into THIS session
# Version: 2.5.0
# Created: 2026-08-19
# Modified: 2026-10-26
# =============================================

"""Watchdog Wire Handler — deliver this seat's dispatch completions into THIS session."""

# metadata.session is the conversation id the statusline checks; the tasks-dir id behind
# /proc/<pid>/fd/1 is another namespace that never equals it, used for takeover only.

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import dispatches as _dispatches
from aipass.devpulse.apps.handlers.watchdog import feed as _feed
from aipass.devpulse.apps.handlers.watchdog import registry as _registry
from aipass.devpulse.apps.handlers.json import json_handler


WIRE_POLL_SECONDS = 1.0

# The statusline reads this file's mtime.
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "aipass-watchdog-active"
HEARTBEAT_STALE_SECONDS = 15.0

_HEARTBEAT_INTERVAL_SECONDS = 5.0

# Completions only, passed explicitly: feed.FEED_KINDS also carries "wake" start edges.
_DELIVER_KINDS = ("dispatch",)

# A dead monitor pushes nothing, so the register is read through @ai_mail's door at this
# cadence: no agent polled, no process armed, a stdout line only when a death is found.
DEAD_CHECK_SECONDS = 300.0

# Announced once ever per dispatch, so a re-sign-in never repeats a death.
DEAD_CURSOR_NAME = "wire_dead_cursor.json"
_DEAD_CURSOR_CAP = 200

_WIRE_KIND = "baseline_wire"

_REGISTRY_FILENAME = "AIPASS_REGISTRY.json"

# A wedged ps or lsof costs a tick, not the wire.
_PROBE_TIMEOUT_SECONDS = 5.0


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default CWD) to the dir holding the registry."""
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / _REGISTRY_FILENAME).exists():
            return candidate
    return None


def _stderr(msg: str) -> None:
    """Arm-time/diagnostic channel — never a wake event."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _stdout_event(msg: str) -> None:
    """One flushed wake line. The Monitor wrapper notifies per stdout line."""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _sleep(seconds: float) -> None:
    """Inter-tick pause — its own function so tests replace it, not time.sleep
    globally (the prax logger's daemon threads sleep in the same process)."""
    time.sleep(seconds)


def _touch_heartbeat() -> None:
    """Say 'a wire is alive' to the statusline. Never fatal."""
    try:
        HEARTBEAT_FILE.touch()
    except OSError as exc:
        logger.warning("[watchdog.wire] heartbeat touch failed %s: %s", HEARTBEAT_FILE, exc)


def _stdout_target_via_lsof(pid: int) -> Path | None:
    """``lsof -p <pid> -a -d 1 -Fn`` — the portable half of ``_stdout_target``.

    None on any failure: a wrong path would be read as a wrapper identity.
    """
    try:
        done = subprocess.run(
            ["lsof", "-p", str(pid), "-a", "-d", "1", "-Fn"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[watchdog.wire] lsof unusable for pid=%s: %s", pid, exc)
        return None
    for line in done.stdout.splitlines():
        if line.startswith("n") and len(line) > 1:
            return Path(line[1:])
    logger.info("[watchdog.wire] lsof named no fd/1 for pid=%s", pid)
    return None


def _stdout_target(pid: int | None = None) -> Path | None:
    """Where a process's stdout actually goes — the wire-identity primitive.

    None when the pid is gone or fd/1 is unreadable: the target is unknown.
    """
    if sys.platform != "linux":
        return _stdout_target_via_lsof(os.getpid() if pid is None else pid)
    who = "self" if pid is None else str(pid)
    try:
        return Path(os.readlink(f"/proc/{who}/fd/1"))
    except OSError as exc:
        logger.info("[watchdog.wire] fd/1 unreadable for pid=%s: %s", who, exc)
        return None


def _session_dir_of(target: Path | None) -> Path | None:
    """The session dir a stdout target belongs to, or None."""
    if target is None or target.parent.name != "tasks":
        return None
    return target.parent.parent


WRAPPER_MONITOR = "monitor"
WRAPPER_BACKGROUND = "background"
WRAPPER_FOREGROUND = "foreground"


def _wrapper_of(target: Path | None) -> str:
    """Which harness wrapper this wire runs under, read from stdout alone.

    A Monitor child's stdout is a socket (notifies per line); a run_in_background child's is
    a file under a session tasks dir (notifies on exit only). Recorded at arm time: the pid is gone later.
    """
    if target is None:
        return WRAPPER_FOREGROUND
    if str(target).startswith("socket:"):
        return WRAPPER_MONITOR
    if _session_dir_of(target) is not None:
        return WRAPPER_BACKGROUND
    return WRAPPER_FOREGROUND


def _cmdline_via_ps(pid: int) -> str:
    """``ps -p <pid> -o command=`` — the portable half of ``_cmdline``."""
    try:
        done = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("[watchdog.wire] ps unusable for pid=%s: %s", pid, exc)
        return ""
    return done.stdout.strip()


def _cmdline(pid: int) -> str:
    """A process's cmdline, NUL-separated fields joined with spaces. "" on error."""
    if sys.platform != "linux":
        return _cmdline_via_ps(pid)
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError as exc:
        logger.info("[watchdog.wire] cmdline unreadable for pid=%s: %s", pid, exc)
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def _looks_like_ours(pid: int) -> bool:
    """True if the pid's cmdline names the watchdog.

    A takeover must never SIGTERM a recycled pid; its entry is still deregistered.
    """
    return "watchdog" in _cmdline(pid)


def _sweep_wires(storage_path: Path | None) -> None:
    """One pass over the registry: bury the dead, take over every live wire.

    Every live wire, same session or not: a wire proves a writer, never a listener;
    only the arm happening now is known to have ears.
    """
    for watch in _registry.list_active(storage_path=storage_path, prune_stale=False):
        if watch.get("type") != _WIRE_KIND:
            continue
        pid = watch.get("pid")
        handle = watch.get("handle")
        if not isinstance(handle, str):
            logger.warning("[watchdog.wire] registry entry without a handle: %s", watch)
            continue

        if not isinstance(pid, int) or not _registry.is_pid_alive(pid):
            _registry.deregister(handle, storage_path=storage_path)
            _stderr(f"watchdog wire: buried dead wire entry {handle} (pid {pid})")
            continue

        their_session = _session_dir_of(_stdout_target(pid))
        if _looks_like_ours(pid):
            result = _registry.kill_watch(handle, storage_path=storage_path)
            _stderr(
                f"watchdog wire: took over stale wire {handle} (pid {pid}, "
                f"session={their_session.name if their_session else 'unknown'}) — {result.get('reason', '')}"
            )
            logger.info("[watchdog.wire] took over stale wire handle=%s pid=%s", handle, pid)
        else:
            _registry.deregister(handle, storage_path=storage_path)
            _stderr(
                f"watchdog wire: {handle} records pid {pid} whose cmdline is not a watchdog "
                f"— entry buried, process left alone (recycled pid)"
            )


def _sweep_stale_daemons(storage_path: Path | None) -> int:
    """Retire any detection daemon left running by a pre-r4 binary.

    Kept after the upgrade: an old daemon left alive restores an invisible double wake.
    """
    retired = 0
    for watch in _registry.list_active(storage_path=storage_path, prune_stale=False):
        if watch.get("type") != "baseline":
            continue
        handle = watch.get("handle")
        pid = watch.get("pid")
        if not isinstance(handle, str):
            continue
        if isinstance(pid, int) and _registry.is_pid_alive(pid) and _looks_like_ours(pid):
            result = _registry.kill_watch(handle, storage_path=storage_path)
            _stderr(
                f"watchdog wire: retired pre-r4 detection daemon {handle} (pid {pid}) "
                f"— it double-wakes this seat — {result.get('reason', '')}"
            )
            logger.info("[watchdog.wire] retired pre-r4 daemon handle=%s pid=%s", handle, pid)
        else:
            _registry.deregister(handle, storage_path=storage_path)
            _stderr(f"watchdog wire: buried pre-r4 daemon entry {handle} (pid {pid})")
        retired += 1
    return retired


def _partition_mine(records: list[dict], seat: str) -> list[dict]:
    """Keep only the completions THIS seat dispatched — rule 5's implementation.

    A record with no ``sender`` fails closed: counting it as mine restores the fleet-wide wake.
    """
    mine = [record for record in records if _dispatches.is_mine(record, seat)]
    dropped = len(records) - len(mine)
    if dropped:
        logger.info("[watchdog.wire] %s completion(s) were not this seat's — not delivered", dropped)
    return mine


def _result(state: str, **extra) -> dict:
    """Uniform return shape for every path that returns at all."""
    base = {"state": state, "replayed": 0, "delivered": 0, "dead": 0, "ticks": 0}
    base.update(extra)
    return base


def _dead_cursor_file(repo_root: Path) -> Path:
    return _feed.cursor_file_for(repo_root, name=DEAD_CURSOR_NAME)


def _load_announced(path: Path) -> list[str]:
    """The dispatch keys already announced as DEAD. Missing file = none yet."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        logger.warning("[watchdog.wire] dead cursor unreadable %s: %s", path, exc)
        return []
    ids = doc.get("announced") if isinstance(doc, dict) else None
    return [key for key in ids if isinstance(key, str)] if isinstance(ids, list) else []


def _save_announced(path: Path, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "announced": keys[-_DEAD_CURSOR_CAP:]}), encoding="utf-8")
    os.replace(tmp, path)


def _dead_key(entry: dict) -> str:
    """dispatch_id when the register has one; target+timestamp otherwise, so an
    id-less row is still announced exactly once rather than never or always."""
    dispatch_id = str(entry.get("dispatch_id") or "")
    return dispatch_id or f"{entry.get('target', '?')}|{entry.get('ts', '?')}"


def _clock(stamp: object) -> str:
    """``2026-09-07T12:00:24.229153-07:00`` -> ``09-07 12:00``; anything else verbatim."""
    try:
        return datetime.fromisoformat(str(stamp)).strftime("%m-%d %H:%M")
    except ValueError:
        logger.info("[watchdog.wire] register stamp is not ISO, shown verbatim: %r", stamp)
        return str(stamp or "?")


def _is_dead(entry: dict) -> bool:
    """Dead = the monitor's pid is gone (``monitor_alive`` False, known within one
    check) OR the row is past ai_mail's hard timeout (``overdue``).

    ``None`` (no pid ever learned) is not dead: folding it in would announce the whole backlog.
    """
    return entry.get("monitor_alive") is False or bool(entry.get("overdue"))


def _format_dead(entry: dict) -> str:
    subject = str(entry.get("subject") or "").strip()
    head = f'DEAD {entry.get("target", "?")} [{_dead_key(entry)[:8]}] dispatched {_clock(entry.get("ts"))} "{subject}"'
    if entry.get("monitor_alive") is False:
        return (
            f"{head} — its monitor (pid {entry.get('monitor_pid', '?')}) is gone before the hard timeout "
            f"{_clock(entry.get('expected_by'))}: reboot, OOM or kill. Re-dispatch in continue mode."
        )
    return (
        f"{head} — no completion by {_clock(entry.get('expected_by'))}, the hard timeout. "
        "Nothing here checked whether its monitor is alive, and ai_mail retries a dispatch up to "
        "three times with a fresh timeout each attempt, so an overdue row is often a live monitor "
        "part way through attempt 2. Check the service and the dispatch log first: re-dispatching "
        "over a running retry doubles the work."
    )


def _announce_dead(root: Path, seat: str, announced: list[str]) -> int:
    """One register read; one stdout line per NEW dead dispatch of this seat's.

    Reads ``outstanding``, not ``overdue``, which logs on every late row: a write per check forever.
    """
    try:
        rows = _dispatches.outstanding(repo_root=root)
    except RuntimeError as exc:
        logger.warning("[watchdog.wire] dead check skipped, register unreadable: %s", exc)
        return 0
    fresh = [
        row for row in rows if _is_dead(row) and _dispatches.is_mine(row, seat) and _dead_key(row) not in announced
    ]
    for row in fresh:
        _stdout_event(_format_dead(row))
        announced.append(_dead_key(row))
    if fresh:
        _save_announced(_dead_cursor_file(root), announced)
        logger.warning("[watchdog.wire] announced %s dead dispatch(es)", len(fresh))
        json_handler.log_operation("dead_dispatches_announced", {"count": len(fresh)})
    return len(fresh)


def arm_wire(
    once: bool = False,
    repo_root: Path | None = None,
    storage_path: Path | None = None,
    max_ticks: int | None = None,
    wire_poll: float = WIRE_POLL_SECONDS,
    dead_check: float = DEAD_CHECK_SECONDS,
) -> dict:
    """The arm door: take the wire for THIS session and deliver my completions.

    ``once`` returns after the first delivery; a replayed MISSED or a DEAD line counts.
    A failure that ends delivery prints ``BASELINE DEAD:`` and exits 1: silence never means covered.
    """
    root = repo_root if repo_root is not None else find_repo_root()
    if root is None:
        _stdout_event(f"BASELINE DEAD: {_REGISTRY_FILENAME} not found — no root, no coverage")
        raise SystemExit(1)

    # Fatal: without a seat nothing is mine, and the wire would look armed while deaf.
    # A missing register is legitimate; an unknown seat never is.
    try:
        seat = _dispatches.seat_email(repo_root=root)
    except RuntimeError as exc:
        _stdout_event(f"BASELINE DEAD: cannot tell whose dispatches to deliver — {exc}")
        logger.error("[watchdog.wire] seat unresolved: %s", exc)
        raise SystemExit(1) from exc

    my_target = _stdout_target()
    my_session = _session_dir_of(my_target)
    # The statusline matches the conversation id; the tasks-dir name is only a fallback.
    session_name = _dispatches.seat_session_id() or (my_session.name if my_session is not None else None)

    # A continuous wire refuses when it cannot see its wrapper, or sees a run_in_background
    # file that is heard only on exit. The refusal itself exits, so it is heard; --once stays legal.
    if not once and my_target is None:
        reason = (
            "stdout target unresolvable — this continuous wire cannot tell which wrapper carries it, "
            "so it cannot know anyone would hear a delivery. Arm the one-shot instead, under the Bash "
            "tool with run_in_background: drone @devpulse watchdog baseline --once"
        )
        _stderr(f"watchdog wire: REFUSED — {reason}")
        _stdout_event(f"BASELINE DEAD: {reason}")
        logger.error("[watchdog.wire] refused continuous arm, stdout target unresolvable")
        raise SystemExit(1)

    if not once and my_target is not None and my_session is not None and my_target.is_file():
        _stdout_event(
            "BASELINE DEAD: continuous wire armed with run_in_background — its per-event stdout lines "
            "would never notify anyone. Arm the one-shot instead, same wrapper: "
            "drone @devpulse watchdog baseline --once (exits on the first delivery = one wake)"
        )
        logger.error("[watchdog.wire] refused continuous arm under run_in_background stdout=%s", my_target)
        raise SystemExit(1)

    _sweep_wires(storage_path)
    _sweep_stale_daemons(storage_path)

    # A takeover sends SIGTERM; the finally below must still deregister.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    handle = _registry.register(
        _WIRE_KIND,
        metadata={
            "session": session_name,
            "wrapper": _wrapper_of(my_target),
            "tasks_dir": my_session.name if my_session is not None else None,
            "stdout": str(my_target) if my_target is not None else None,
        },
        storage_path=storage_path,
    )
    json_handler.log_operation("arm_wire", {"handle": handle, "session": session_name, "once": once})

    feed_cursor_file = _feed.cursor_file_for(root)
    feed_source = _feed.feed_file(root)
    feed_state: dict | None = None

    replayed = 0
    delivered = 0
    ticks = 0
    last_heartbeat = 0.0
    try:
        _touch_heartbeat()
        last_heartbeat = time.monotonic()

        feed_records, feed_state = _feed.drain_feed(
            feed_cursor_file, kinds=_DELIVER_KINDS, feed_file_path=feed_source, state=feed_state
        )
        missed = _partition_mine(feed_records, seat)
        for record in missed:
            _stdout_event(f"MISSED {_feed.format_feed_event(record)} [completed while no wire was up]")
        if missed:
            replayed = len(missed)
            logger.info("[watchdog.wire] replayed %s missed completions", replayed)

        # A death most likely waits at sign-in: the reboot that killed the monitor killed the old wire.
        announced = _load_announced(_dead_cursor_file(root))
        dead = _announce_dead(root, seat, announced)
        last_dead_check = time.monotonic()

        _stderr(
            f"watchdog wire: armed handle={handle} session={session_name or 'NONE (fg)'} "
            f"replayed={replayed} tick={wire_poll}s"
        )
        if my_target is not None and str(my_target).startswith("pipe:"):
            _stderr(
                "watchdog wire: stdout is a pipe — this wire is recorded as foreground and the statusline "
                "will not count it. Arm it bare, no pipe and no redirect: drone @devpulse watchdog baseline --once"
            )
            logger.warning("[watchdog.wire] armed behind a pipe handle=%s stdout=%s", handle, my_target)
        if not once:
            _stderr(
                "watchdog wire: continuous mode NOTIFIES PER STDOUT LINE ONLY UNDER THE MONITOR TOOL — "
                "if this was armed with run_in_background, TaskStop it and re-arm via Monitor"
            )

        if once and (replayed or dead):
            return _result("completed", session=session_name, replayed=replayed, delivered=replayed, dead=dead)

        while True:
            ticks += 1
            now = time.monotonic()
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL_SECONDS:
                _touch_heartbeat()
                last_heartbeat = now
            if now - last_dead_check >= dead_check:
                dead += _announce_dead(root, seat, announced)
                last_dead_check = now

            feed_records, feed_state = _feed.drain_feed(
                feed_cursor_file, kinds=_DELIVER_KINDS, feed_file_path=feed_source, state=feed_state
            )
            fresh = _partition_mine(feed_records, seat)
            for record in fresh:
                _stdout_event(_feed.format_feed_event(record))
            if fresh:
                delivered += len(fresh)
                logger.info("[watchdog.wire] delivered %s completions", len(fresh))

            if once and (delivered or dead):
                return _result(
                    "completed",
                    session=session_name,
                    replayed=replayed,
                    delivered=replayed + delivered,
                    dead=dead,
                    ticks=ticks,
                )
            if max_ticks is not None and ticks >= max_ticks:
                return _result(
                    "stopped",
                    session=session_name,
                    replayed=replayed,
                    delivered=replayed + delivered,
                    dead=dead,
                    ticks=ticks,
                )

            _sleep(wire_poll)
    except KeyboardInterrupt:
        _stderr("watchdog wire: interrupted — this session is unwired")
        logger.info("[watchdog.wire] interrupted handle=%s", handle)
        raise
    finally:
        _registry.deregister(handle, storage_path=storage_path)
