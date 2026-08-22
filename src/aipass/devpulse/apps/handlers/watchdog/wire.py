# =================== AIPass ====================
# Name: wire.py
# Description: Watchdog Wire Handler — per-session delivery of the baseline daemon's completion events
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

# WHY THIS FILE EXISTS (DPLAN-0308 round 2): the round-1 baseline was one
# process doing two jobs — detecting completions AND delivering them into the
# chat via its own stdout. Its delivery depends on a LISTENER the process can
# neither see nor keep alive: witnessed live on 2026-08-19, @api (11:22) and
# @baud (12:34) COMPLETE lines sat unread in a task file while Patrick watched
# the live session stay silent. The registry said "armed", the pid was alive,
# and the idempotence check ("pid alive = covered") re-armed into a lie —
# detection and delivery share a lifetime only by accident.
#
# So detection and delivery are now SEPARATE lifetimes:
#   - baseline.py --daemon: session-agnostic detection, events appended to a
#     durable JSONL, heartbeat for the statusline. Never dies with a session.
#   - THIS file: the wire — a cheap follower whose stdout IS the session task
#     file (Monitor-wrapped). On arm it replays everything past the delivery
#     cursor as MISSED lines, so churn delays events instead of losing them.
#
# THE 12:34 KILLER, NAMED FROM THE TRANSCRIPT: the 10:55 arm ran under Bash
# run_in_background — which notifies only when the command EXITS, and
# continuous mode never exits. Zero wakes by construction, healthy session or
# not. The Monitor tool (one notification per stdout line) is the ONLY correct
# wrapper for the continuous wire; nothing inside this process can distinguish
# the two wrappers, so the arm banner and the branch reflex both prescribe the
# exact call. --once is the run_in_background-safe shape (exits on delivery).
#
# TWO ID NAMESPACES, measured 2026-08-19, do not confuse them:
#   - conversation/session id (env CLAUDE_CODE_SESSION_ID, statusline input
#     session_id): long-lived, survives compaction — what the statusline can
#     check, so metadata.session records THIS one.
#   - task-dir id (the .../<id>/tasks/ dir readlink(/proc/<pid>/fd/1) lands
#     in): the harness's runtime namespace — on this box it never equals the
#     conversation id. Takeover identity and diagnostics only.
# Residual, on the record: a wire from a PREVIOUS claude process of the same
# conversation would still session-match the statusline (green) while its
# listener is gone. Takeover-always + the arm-at-session-start reflex bound
# that window; the @hooks cadence check (P2b) closes it properly.

"""
Watchdog Wire Handler — deliver baseline completions into THIS session.

Public surface:
  arm_wire(once=False, ...) -> dict

The arm door (``watchdog baseline`` routes here):
  1. sweep the registry — deregister dead entries, migrate a live LEGACY
     single-process watcher (no role=daemon), and take over EVERY live wire:
     an existing wire proves a writer, never a listener, so only the arm
     happening right now is known to have ears;
  2. ensure the detection daemon runs (spawn detached if not);
  3. replay events past the cursor as ``MISSED`` stdout lines;
  4. follow the events file, one stdout line per completion, cursor advanced
     after every delivery;
  5. watch the daemon back — dead pid or stale heartbeat prints
     ``BASELINE DEAD`` on stdout and exits nonzero, never a quiet stop.

Run via the Monitor tool with description "watchdog".
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import baseline as _baseline
from aipass.devpulse.apps.handlers.watchdog import feed as _feed
from aipass.devpulse.apps.handlers.watchdog import registry as _registry
from aipass.devpulse.apps.handlers.json import json_handler


# Delivery cadence. Detection already pays the per-branch stats every 2s; the
# wire only stats ONE file (the events JSONL) plus the heartbeat, so 1s keeps
# wake latency ~3s worst case (2s detect + 1s deliver) for two syscalls a tick.
WIRE_POLL_SECONDS = 1.0

# How long the arm door waits for a freshly spawned daemon to register itself
# before declaring the spawn failed and pointing at the daemon log.
_DAEMON_SPAWN_WAIT_SECONDS = 10.0
_DAEMON_SPAWN_POLL_SECONDS = 0.25

_WIRE_KIND = "baseline_wire"
_DAEMON_KIND = "baseline"

# Relative to the devpulse branch dir. The daemon's stdout/stderr land here
# when the wire spawns it detached — its BASELINE DEAD confessions included.
_DAEMON_LOG_RELPATH = ("logs", "baseline_daemon.out")


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


def _stdout_target(pid: int | None = None) -> Path | None:
    """Where a process's stdout actually goes — the wire-identity primitive.

    /proc is the honest source for where writes LAND (env only says which
    conversation spawned the process — a different namespace, see the header).
    None when the pid is gone or fd/1 is unreadable.
    """
    who = "self" if pid is None else str(pid)
    try:
        return Path(os.readlink(f"/proc/{who}/fd/1"))
    except OSError as exc:
        logger.info("[watchdog.wire] fd/1 unreadable for pid=%s: %s", who, exc)
        return None


def _session_dir_of(target: Path | None) -> Path | None:
    """The session dir a stdout target belongs to, or None.

    The harness writes background/monitor output to
    ``.../<session-id>/tasks/<task-id>.output`` — the ``tasks`` parent is the
    shape we key on. A tty/pipe/regular-file stdout has no session.
    """
    if target is None or target.parent.name != "tasks":
        return None
    return target.parent.parent


def _cmdline(pid: int) -> str:
    """A process's cmdline, NUL-separated fields joined with spaces. "" on error."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError as exc:
        logger.info("[watchdog.wire] cmdline unreadable for pid=%s: %s", pid, exc)
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip()


def _looks_like_ours(pid: int) -> bool:
    """True if the pid's cmdline names the watchdog.

    The registry can hold a pid the OS has recycled to an innocent process; a
    takeover must never SIGTERM anything whose cmdline doesn't say watchdog.
    The entry still gets deregistered — it describes a watch that no longer
    exists — but the process is left alone.
    """
    return "watchdog" in _cmdline(pid)


def _read_cursor(cursor_file: Path) -> int:
    """The delivery offset — how many bytes of the events file were delivered."""
    try:
        data = json.loads(cursor_file.read_text(encoding="utf-8"))
        offset = data.get("offset")
        return offset if isinstance(offset, int) and offset >= 0 else 0
    except FileNotFoundError:
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        # A corrupt cursor resets delivery to the top of the file: duplicates
        # over silence, always — a replayed event is noise, a lost one is the
        # exact failure this handler exists to end.
        logger.warning("[watchdog.wire] cursor unreadable %s — resetting to 0: %s", cursor_file, exc)
        _stderr(f"watchdog wire: cursor unreadable ({exc}) — replaying from the top (duplicates possible)")
        return 0


def _write_cursor(cursor_file: Path, offset: int) -> None:
    """Persist the delivery offset atomically (tmp + replace).

    A torn cursor would reset delivery to 0 on the next arm — survivable
    (duplicates), but two lines of atomicity buy exactness.
    """
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cursor_file.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"offset": offset, "updated": datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
    os.replace(tmp, cursor_file)


def _drain_events(events_file: Path, offset: int) -> tuple[list[dict], int]:
    """Read complete event lines past ``offset``. Returns (records, new_offset).

    A trailing line without its newline is a write still in flight — left
    unconsumed for the next tick. A COMPLETE line that fails to parse is junk
    to step over loudly, never a reason to wedge delivery forever at the same
    offset. A file shorter than the offset means it was replaced/truncated —
    delivery resets to the top and says so (duplicates over silence).
    """
    try:
        size = events_file.stat().st_size
    except FileNotFoundError:
        # No events file yet — the daemon hasn't detected anything since the
        # split shipped. Nothing to deliver is a normal answer.
        return [], 0 if offset else offset

    if size < offset:
        logger.warning("[watchdog.wire] events file shrank (%s < %s) — replaying from 0", size, offset)
        _stderr("watchdog wire: events file was replaced — replaying from the top (duplicates possible)")
        offset = 0
    if size == offset:
        return [], offset

    with open(events_file, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read()

    records: list[dict] = []
    consumed = 0
    for raw_line in chunk.splitlines(keepends=True):
        if not raw_line.endswith(b"\n"):
            break
        consumed += len(raw_line)
        text = raw_line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("[watchdog.wire] unparseable event line skipped: %s (%s)", text[:120], exc)
            _stderr(f"watchdog wire: skipped an unparseable event line ({exc})")
            continue
        if isinstance(record, dict):
            records.append(record)

    return records, offset + consumed


def _format_delivery(record: dict, missed: bool) -> str:
    """Render one delivered event — the baseline formatter plus lateness."""
    line = _baseline.format_completion(record)
    if missed:
        detected = str(record.get("iso") or "?")
        line = f"MISSED {line} [detected {detected}, delivered on re-arm — no wire was up]"
    return line


def _heartbeat_age() -> float | None:
    """Seconds since the daemon last touched the heartbeat, or None if absent."""
    try:
        return max(0.0, time.time() - _baseline.HEARTBEAT_FILE.stat().st_mtime)
    except OSError as exc:
        logger.info("[watchdog.wire] heartbeat unreadable: %s", exc)
        return None


def _spawn_daemon(devpulse_dir: Path, daemon_log: Path) -> None:
    """Start the detection daemon detached from every session.

    ``start_new_session`` puts it in its own process group — no tty, no
    harness task file, nothing a session teardown can reach. Its stdout and
    stderr go to the daemon log so its BASELINE DEAD confessions survive.
    Spawned through drone — the sanctioned door, same as every routed call.
    """
    daemon_log.parent.mkdir(parents=True, exist_ok=True)
    with open(daemon_log, "ab") as log_fh:
        subprocess.Popen(
            ["drone", "@devpulse", "watchdog", "baseline", "--daemon"],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(devpulse_dir),
        )


def _find_live_daemon(storage_path: Path | None) -> dict | None:
    """The registry's live round-2 daemon entry, or None."""
    for watch in _registry.list_active(storage_path=storage_path, prune_stale=False):
        if watch.get("type") != _DAEMON_KIND:
            continue
        pid = watch.get("pid")
        meta = watch.get("metadata") or {}
        if isinstance(pid, int) and _registry.is_pid_alive(pid) and meta.get("role") == "daemon":
            return watch
    return None


def _sweep_and_migrate(storage_path: Path | None) -> dict:
    """One pass over the registry: bury the dead, migrate legacies, kill wires.

    Returns {"daemon": entry|None}. Everything it kills or buries is said on
    stderr — a slot silently reused is how a dead watcher passes for a live
    one (round 1's _arm doctrine, now wire-aware).

    EVERY live wire is taken over, same session or not. There is no
    "already wired" answer: a wire process writing into the current session's
    tasks dir proves nothing about a LISTENER — witnessed live 2026-08-19, the
    10:55 wire kept writing into the live session dir (ac044dfb) after the
    resume killed its monitor, and @baud's 12:34 completion landed unread. Only
    the arm happening right now is known to have ears; the process that exists
    is always the newest arm.
    """
    daemon_entry: dict | None = None

    for watch in _registry.list_active(storage_path=storage_path, prune_stale=False):
        wtype = watch.get("type")
        if wtype not in (_DAEMON_KIND, _WIRE_KIND):
            continue
        pid = watch.get("pid")
        handle = watch.get("handle")
        meta = watch.get("metadata") or {}
        if not isinstance(handle, str):
            # An entry with no handle can be neither killed nor deregistered
            # through the registry's doors — name it and move on.
            logger.warning("[watchdog.wire] registry entry without a handle: %s", watch)
            continue

        if not isinstance(pid, int) or not _registry.is_pid_alive(pid):
            _registry.deregister(handle, storage_path=storage_path)
            _stderr(f"watchdog wire: buried dead {wtype} entry {handle} (pid {pid})")
            continue

        if wtype == _DAEMON_KIND:
            if meta.get("role") == "daemon":
                daemon_entry = watch
                continue
            # A live baseline WITHOUT the daemon role is the round-1 shape:
            # one process wired to one session's task file. Its detection is
            # real but its delivery is a coin flip — migrate it.
            if _looks_like_ours(pid):
                result = _registry.kill_watch(handle, storage_path=storage_path)
                _stderr(
                    f"watchdog wire: migrated legacy single-process watcher {handle} "
                    f"(pid {pid}) — {result.get('reason', '')}"
                )
                logger.info("[watchdog.wire] migrated legacy watcher handle=%s pid=%s", handle, pid)
            else:
                _registry.deregister(handle, storage_path=storage_path)
                _stderr(
                    f"watchdog wire: {handle} records pid {pid} whose cmdline is not a watchdog "
                    f"— entry buried, process left alone (recycled pid)"
                )
            continue

        # A live wire — taken over unconditionally (see the docstring: its
        # existence proves a writer, never a listener). The session name rides
        # along only so the takeover line says where the corpse was pointed.
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

    return {"daemon": daemon_entry}


def _ensure_daemon(
    storage_path: Path | None,
    repo_root: Path,
    existing: dict | None,
    spawn_fn=None,
) -> dict:
    """A live daemon entry — the one found, or one spawned and waited for.

    Raises RuntimeError when a spawn doesn't register in time, with the daemon
    log's tail on stderr — the spawn's own words beat a guess about them.
    """
    if existing is not None:
        return existing

    devpulse_dir = _baseline.devpulse_dir_for(repo_root)
    daemon_log = devpulse_dir.joinpath(*_DAEMON_LOG_RELPATH)
    spawn = spawn_fn if spawn_fn is not None else _spawn_daemon
    _stderr("watchdog wire: no detection daemon — spawning one detached")
    spawn(devpulse_dir, daemon_log)

    waited = 0.0
    while waited < _DAEMON_SPAWN_WAIT_SECONDS:
        entry = _find_live_daemon(storage_path)
        if entry is not None:
            _stderr(f"watchdog wire: daemon up pid={entry.get('pid')} handle={entry.get('handle')}")
            return entry
        _sleep(_DAEMON_SPAWN_POLL_SECONDS)
        waited += _DAEMON_SPAWN_POLL_SECONDS

    tail = ""
    try:
        tail = "\n".join(daemon_log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:])
    except OSError as exc:
        tail = f"(daemon log unreadable: {exc})"
    raise RuntimeError(f"daemon did not register within {_DAEMON_SPAWN_WAIT_SECONDS:.0f}s — its log ends:\n{tail}")


def _daemon_dead_reason(daemon_pid: int | None) -> str | None:
    """Why the daemon should be called dead this tick, or None if it's fine.

    Two checks because they fail differently: a gone pid is a crash, a live
    pid with a stale heartbeat is a hang — and a hung detector is the more
    dangerous corpse, it still LOOKS armed everywhere.
    """
    if daemon_pid is None or not _registry.is_pid_alive(daemon_pid):
        return f"detection daemon gone (pid={daemon_pid})"
    age = _heartbeat_age()
    if age is None:
        # No heartbeat file at all while the pid lives: the daemon hasn't
        # completed a tick yet (fresh spawn) — the pid check carries liveness
        # until the first touch lands. Not a death.
        return None
    if age > _baseline.HEARTBEAT_STALE_SECONDS:
        return f"detection daemon hung (pid={daemon_pid} heartbeat_age={age:.0f}s)"
    return None


def _result(state: str, **extra) -> dict:
    """Uniform return shape for every path that returns at all."""
    base = {"state": state, "replayed": 0, "delivered": 0, "ticks": 0}
    base.update(extra)
    return base


def arm_wire(
    once: bool = False,
    repo_root: Path | None = None,
    storage_path: Path | None = None,
    max_ticks: int | None = None,
    spawn_fn=None,
    wire_poll: float = WIRE_POLL_SECONDS,
) -> dict:
    """The arm door: ensure the daemon, take the wire for THIS session, deliver.

    Args:
        once: Return after the first delivery (replayed MISSED events count —
            they ARE the wake the unwired window owed).
        repo_root: Override the repo root holding AIPASS_REGISTRY.json.
        storage_path: Override the watch registry path (tests).
        max_ticks: Bound the follow loop to N ticks (tests). None = unbounded.
        spawn_fn: Override the daemon spawner (tests).
        wire_poll: Seconds between delivery ticks.

    Returns:
        dict with ``state`` in {"completed", "stopped"} plus
        ``replayed``/``delivered``/``ticks`` counters and ``session``.

    Raises:
        SystemExit(1): after a ``BASELINE DEAD: ...`` stdout line, for any
            failure that ends delivery — daemon death included. Silence must
            never mean covered.
    """
    root = repo_root if repo_root is not None else _baseline.find_repo_root()
    if root is None:
        _stdout_event("BASELINE DEAD: AIPASS_REGISTRY.json not found — no roster, no coverage")
        raise SystemExit(1)

    my_target = _stdout_target()
    my_session = _session_dir_of(my_target)
    # The statusline matches on the CONVERSATION id (its input's session_id);
    # the tasks-dir id is a different namespace (see the header). Fall back to
    # the tasks-dir name only when the env var is absent entirely.
    session_name = os.environ.get("CLAUDE_CODE_SESSION_ID") or (my_session.name if my_session is not None else None)

    # THE WRAPPER TRIPWIRE, measured live 2026-08-19: a Monitor child's stdout
    # is a SOCKET; a run_in_background child's stdout is a REGULAR FILE under a
    # session tasks dir. A continuous wire behind that file delivers nothing
    # until exit — the 12:34 failure — so it refuses to exist. The refusal
    # itself IS heard: bg-Bash notifies on exit, and this exits immediately.
    # ``--once`` stays legal there (it exits on first delivery = one wake).
    if not once and my_target is not None and my_session is not None and my_target.is_file():
        _stdout_event(
            "BASELINE DEAD: continuous wire armed with run_in_background — its per-event stdout lines "
            "would never notify anyone. Re-arm via the Monitor tool: "
            "Monitor(command='drone @devpulse watchdog baseline', description='watchdog', persistent=true)"
        )
        logger.error("[watchdog.wire] refused continuous arm under run_in_background stdout=%s", my_target)
        raise SystemExit(1)

    sweep = _sweep_and_migrate(storage_path)

    try:
        daemon_entry = _ensure_daemon(storage_path, root, sweep["daemon"], spawn_fn=spawn_fn)
    except RuntimeError as exc:
        _stdout_event(f"BASELINE DEAD: {exc}")
        logger.error("[watchdog.wire] daemon ensure failed: %s", exc)
        raise SystemExit(1) from exc
    daemon_pid = daemon_entry.get("pid") if isinstance(daemon_entry.get("pid"), int) else None

    # SIGTERM must run the finally below — a takeover kills the old wire with
    # SIGTERM, and a wire that dies without deregistering leaves the stale
    # entry the next sweep has to bury.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    handle = _registry.register(
        _WIRE_KIND,
        metadata={
            "session": session_name,
            "tasks_dir": my_session.name if my_session is not None else None,
            "stdout": str(my_target) if my_target is not None else None,
            "daemon_pid": daemon_pid,
        },
        storage_path=storage_path,
    )
    json_handler.log_operation("arm_wire", {"handle": handle, "session": session_name, "once": once})

    events_file = _baseline.events_file_for(root)
    cursor_file = _baseline.cursor_file_for(root)
    # The push source (FPLAN-0451 P2). Its cursor is a digest set, not a byte
    # offset, because the feed is trimmed by os.replace and offsets go stale
    # silently across that — see feed.py's header.
    feed_cursor_file = _feed.cursor_file_for(root)
    feed_source = _feed.feed_file(root)
    feed_state: dict | None = None

    replayed = 0
    delivered = 0
    ticks = 0
    try:
        offset = _read_cursor(cursor_file)
        records, offset = _drain_events(events_file, offset)
        for record in records:
            _stdout_event(_format_delivery(record, missed=True))
        if records:
            _write_cursor(cursor_file, offset)
            replayed = len(records)
            logger.info("[watchdog.wire] replayed %s missed events", replayed)

        feed_records, feed_state = _feed.drain_feed(feed_cursor_file, feed_file_path=feed_source, state=feed_state)
        for record in feed_records:
            _stdout_event(f"MISSED {_feed.format_feed_event(record)} [reported while no wire was up]")
        if feed_records:
            replayed += len(feed_records)
            logger.info("[watchdog.wire] replayed %s missed feed events", len(feed_records))

        _stderr(
            f"watchdog wire: armed handle={handle} session={session_name or 'NONE (fg)'} "
            f"daemon_pid={daemon_pid} replayed={replayed} tick={wire_poll}s"
        )
        if not once:
            # The wrapper is invisible from inside — this line is the only
            # tripwire for the 12:34 mistake (continuous wire armed via
            # run_in_background = zero wakes forever).
            _stderr(
                "watchdog wire: continuous mode NOTIFIES PER STDOUT LINE ONLY UNDER THE MONITOR TOOL — "
                "if this was armed with run_in_background, TaskStop it and re-arm via Monitor"
            )

        if once and replayed:
            return _result("completed", session=session_name, replayed=replayed, delivered=replayed)

        while True:
            ticks += 1
            reason = _daemon_dead_reason(daemon_pid)
            if reason is not None:
                _stdout_event(f"BASELINE DEAD: {reason} — re-arm with: drone @devpulse watchdog baseline")
                logger.error("[watchdog.wire] %s", reason)
                raise SystemExit(1)

            feed_records, feed_state = _feed.drain_feed(feed_cursor_file, feed_file_path=feed_source, state=feed_state)
            for record in feed_records:
                _stdout_event(_feed.format_feed_event(record))
            if feed_records:
                delivered += len(feed_records)
                logger.info("[watchdog.wire] delivered %s feed events", len(feed_records))

            records, new_offset = _drain_events(events_file, offset)
            for record in records:
                _stdout_event(_format_delivery(record, missed=False))
            if records:
                offset = new_offset
                _write_cursor(cursor_file, offset)
                delivered += len(records)
                logger.info("[watchdog.wire] delivered %s events", len(records))
            elif new_offset != offset:
                # Junk/blank lines consumed without a delivery still move the
                # cursor — otherwise the same junk is re-skipped every tick.
                offset = new_offset
                _write_cursor(cursor_file, offset)

            if once and delivered:
                return _result(
                    "completed", session=session_name, replayed=replayed, delivered=replayed + delivered, ticks=ticks
                )
            if max_ticks is not None and ticks >= max_ticks:
                return _result(
                    "stopped", session=session_name, replayed=replayed, delivered=replayed + delivered, ticks=ticks
                )

            _sleep(wire_poll)
    except KeyboardInterrupt:
        _stderr("watchdog wire: interrupted — this session is unwired")
        logger.info("[watchdog.wire] interrupted handle=%s", handle)
        raise
    finally:
        _registry.deregister(handle, storage_path=storage_path)
