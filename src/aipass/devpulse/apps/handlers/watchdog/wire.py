# =================== AIPass ====================
# Name: wire.py
# Description: Watchdog Wire Handler — deliver MY dispatch completions into THIS session
# Version: 2.2.0
# Created: 2026-08-19
# Modified: 2026-09-07
# =============================================

"""
Watchdog Wire Handler — deliver this seat's dispatch completions into THIS session.

Public surface:
  arm_wire(once=False, ...) -> dict
  find_repo_root(start=None) -> Path | None
  HEARTBEAT_FILE, HEARTBEAT_STALE_SECONDS
  DEAD_CHECK_SECONDS, DEAD_CURSOR_NAME

The arm door (``watchdog baseline`` routes here):
  1. sweep the registry — deregister dead entries and take over EVERY live
     wire: an existing wire proves a writer, never a listener, so only the arm
     happening right now is known to have ears;
  2. replay completions past the cursor as ``MISSED`` stdout lines;
  3. follow the notification feed, one stdout line per completion THAT THIS
     SEAT DISPATCHED, cursor advanced after every delivery;
  4. touch the heartbeat so the statusline can tell a live wire from a hung one;
  5. announce the dead — at sign-in and every DEAD_CHECK_SECONDS, one ``DEAD``
     line per dispatch of this seat's whose monitor can no longer report
     (FPLAN-0499; the hole DPLAN-0314 named "outcome M").

There is no detection process to ensure, watch, or mourn. Run via the Monitor
tool with description "watchdog".

The commentary below this docstring is the history — why the daemon this file
used to depend on no longer exists, and why delivery is a separate lifetime
from everything else. It is long on purpose and it stays.
"""

# WHAT CHANGED IN r4 (DPLAN-0317, FPLAN-0452 P2) — read this before the r2
# history below, because it deletes half of it.
#
# This file used to drain TWO sources every tick with no dedupe between them: a
# detection daemon's events file, and @ai_mail's notification feed. They carried
# THE SAME COMPLETIONS. The daemon polled ~19 branches every 2s to synthesise an
# event dispatch_monitor.py had already written 1-2 seconds earlier, and both
# lines cleared Monitor's 200ms batching window — so every dispatch completion
# produced TWO wakes, for months. Nobody noticed, because a duplicate wake looks
# exactly like a working wake.
#
# The daemon is gone. Detection by inference is replaced by detection by report:
# the agent that finishes says so, and this file delivers what it said. Idle is
# one stat on the feed per tick and nothing else running anywhere.
#
# AND THE WIRE NOW ANSWERS "WAS THIS MINE". The feed names the branch that
# FINISHED, never the branch that SENT the work, so this seat used to be woken
# for every citizen's completion fleet-wide. dispatches.py reads @ai_mail's
# register — written at send time — and only ids belonging to this seat are
# delivered. That is Patrick's rule 5, and it is not satisfiable from the feed
# alone at any price.
#
# KINDS: completions ONLY. The feed also carries "wake" start edges, and this
# wire used to deliver those too. Rule 5 again: only a COMPLETION wakes,
# because an agent may mail a report and then mail a correction — we wait for
# it to be finished, and wake once.
#
# ---------------------------------------------------------------------------
# WHY THIS FILE EXISTS AT ALL (DPLAN-0308 round 2) — still true, still the
# reason delivery is a separate lifetime from anything else:
#
# The round-1 baseline was one process doing two jobs, and its delivery depended
# on a LISTENER the process could neither see nor keep alive: witnessed live on
# 2026-08-19, @api (11:22) and @baud (12:34) COMPLETE lines sat unread in a task
# file while Patrick watched the live session stay silent. The registry said
# "armed", the pid was alive, and the idempotence check ("pid alive = covered")
# re-armed into a lie.
#
# THE 12:34 KILLER, NAMED FROM THE TRANSCRIPT: the 10:55 arm ran under Bash
# run_in_background — which notifies only when the command EXITS, and continuous
# mode never exits. Zero wakes by construction, healthy session or not. The
# Monitor tool (one notification per stdout line) is the ONLY correct wrapper
# for the continuous wire; nothing inside this process can distinguish the two
# wrappers, so the tripwire below refuses the combination outright. --once is
# the run_in_background-safe shape (it exits on delivery).
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
# that window.

import json
import os
import signal
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


# Delivery cadence. The feed drain is ONE stat when nothing changed, so a quiet
# system costs a syscall a second and wake latency is ~1s after the report
# lands. Measured idle cost of this loop: 0.033% of a core.
WIRE_POLL_SECONDS = 1.0

# The statusline reads this file's mtime. It is touched by the WIRE now — under
# r3 the daemon owned it, and deleting the daemon without moving this would
# have painted the statusline red forever with a perfectly healthy wire (the
# exact trap FPLAN-0451 P2 hit with a hardcoded /tmp path).
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "aipass-watchdog-active"
HEARTBEAT_STALE_SECONDS = 15.0

# Touched at most this often. Once a second would be a WRITE per tick to buy
# nothing: the staleness threshold above is 15s, so 5s leaves two missed
# touches of headroom before anything reads red.
_HEARTBEAT_INTERVAL_SECONDS = 5.0

# The feed kinds this wire delivers. Completions ONLY — see the header. Passed
# explicitly rather than taking feed.FEED_KINDS, because that default also
# carries "wake" start edges for other readers and a silent widening here would
# be a silent re-broadening of what wakes this seat.
_DELIVER_KINDS = ("dispatch",)

# THE DEAD-MONITOR BACKSTOP (FPLAN-0499). A completion is pushed by the agent
# that finishes — and a monitor that died in a host reboot, an OOM kill or a
# SIGKILL finishes nothing, so a pure push design is blind to exactly the case
# a watchdog exists for. DPLAN-0314 named it "outcome M" and called the
# backstop load-bearing; on 2026-09-07 the 12:17 reboot killed two wave-3
# agents mid-work and nothing said so for two and a half hours, although
# dispatches.overdue() already knew — it was pull-only.
#
# Patrick's shape (2026-09-07 15:00): five minutes, not sixty seconds, and the
# code checks, not the seat — "the whole redesign was to cut cpu and not need
# tokens to monitor". So: one register read through @ai_mail's door per five
# minutes, no agent polled, no process armed, and a stdout line only when a
# death is found. Overdue is THEIR reading: expected_by is dispatch_monitor's
# hard timeout, which a live monitor cannot overrun (dispatches.py).
#
# Phase 2 (2026-09-07 17:40, ai_mail 35147916): the register now carries the
# monitor's pid and serves ``monitor_alive`` derived from /proc at read time,
# so a death is announced within one cadence instead of at the two-hour
# timeout. Tri-state — see _is_dead for why None is NOT dead.
DEAD_CHECK_SECONDS = 300.0

# Announced once EVER per dispatch, not once per wire: a re-sign-in after the
# reboot that caused the death must not re-deliver it. Sibling of the feed
# cursor, same directory, its own name (feed.cursor_file_for explains why two
# readers never share one cursor).
DEAD_CURSOR_NAME = "wire_dead_cursor.json"
_DEAD_CURSOR_CAP = 200

_WIRE_KIND = "baseline_wire"

_REGISTRY_FILENAME = "AIPASS_REGISTRY.json"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default CWD) to the dir holding the registry.

    Lived in baseline.py until r4 deleted the daemon around it; it moved here
    rather than being re-copied, because this package already carries three
    near-duplicate pid checks and does not need a fourth duplicated primitive.
    """
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
    """Say 'a wire is alive' to the statusline. Never fatal.

    A failed touch must not end delivery: the heartbeat is an observability
    signal, and losing the signal is not losing the coverage. It IS logged —
    a statusline that goes red for a healthy wire sends someone re-arming for
    no reason, and the log is the only place that explains why.
    """
    try:
        HEARTBEAT_FILE.touch()
    except OSError as exc:
        logger.warning("[watchdog.wire] heartbeat touch failed %s: %s", HEARTBEAT_FILE, exc)


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


WRAPPER_MONITOR = "monitor"
WRAPPER_BACKGROUND = "background"
WRAPPER_FOREGROUND = "foreground"


def _wrapper_of(target: Path | None) -> str:
    """Which harness wrapper this wire runs under, read from stdout alone.

    Measured live 2026-08-19, and it is the entire arm-time health question:

      - a Monitor child's stdout is a SOCKET — one notification per line, the
        only shape a CONTINUOUS wire can be heard through;
      - a run_in_background child's is a REGULAR FILE under a session tasks dir
        — notifies on exit only, which a continuous wire never reaches (the
        12:34 miss);
      - anything else is a terminal, which nobody is reading asynchronously.

    Recorded at arm time rather than re-derived later, because deriving it needs
    ``/proc/<pid>/fd/1`` and by the time someone asks "was that wire real" the
    pid is usually gone. ``monitor`` is the only value that means covered.
    """
    if target is None:
        return WRAPPER_FOREGROUND
    if str(target).startswith("socket:"):
        return WRAPPER_MONITOR
    if _session_dir_of(target) is not None:
        return WRAPPER_BACKGROUND
    return WRAPPER_FOREGROUND


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


def _sweep_wires(storage_path: Path | None) -> None:
    """One pass over the registry: bury the dead, take over every live wire.

    Everything killed or buried is said on stderr — a slot silently reused is
    how a dead watcher passes for a live one.

    EVERY live wire is taken over, same session or not. There is no
    "already wired" answer: a wire process writing into the current session's
    tasks dir proves nothing about a LISTENER — witnessed live 2026-08-19, the
    10:55 wire kept writing into the live session dir (ac044dfb) after the
    resume killed its monitor, and @baud's 12:34 completion landed unread. Only
    the arm happening right now is known to have ears; the process that exists
    is always the newest arm.

    r4 note: this used to also find/migrate DAEMON entries. There is no daemon
    to find. A pre-r4 daemon still running from an older binary is swept as an
    ordinary stale watchdog entry by ``_sweep_stale_daemons`` below.
    """
    for watch in _registry.list_active(storage_path=storage_path, prune_stale=False):
        if watch.get("type") != _WIRE_KIND:
            continue
        pid = watch.get("pid")
        handle = watch.get("handle")
        if not isinstance(handle, str):
            # An entry with no handle can be neither killed nor deregistered
            # through the registry's doors — name it and move on.
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

    Written for ONE upgrade, and deliberately not deleted after it: an operator
    can still be running a months-old detached daemon from any checkout on the
    box. Leaving it alive would restore the exact double-wake r4 removes, and
    it would be invisible — the second wake looks like the first.
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

    One field comparison per record: @ai_mail stamps ``sender`` on the feed line
    at the terminal moment (FPLAN-0452 P1), so nothing is read and nothing is
    joined on the delivery path.

    An earlier version of this joined against the dispatch register to build an
    id allow-list. It raced the producer — which closes the register entry and
    writes the feed line in the same breath — and it duplicated a
    reconstruction rule @ai_mail owns. Both were reasons to stop reading a file
    to answer a question the record already answers.

    A record with no ``sender`` is NOT mine (see ``dispatches.is_mine``): it
    fails closed, because treating an unattributable completion as mine
    restores the fleet-wide wake this function exists to end.
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


# ─────────────────────────────────────────────────────────────────────────────
# The dead-monitor backstop (FPLAN-0499)
# ─────────────────────────────────────────────────────────────────────────────


def _dead_cursor_file(repo_root: Path) -> Path:
    return _feed.cursor_file_for(repo_root, name=DEAD_CURSOR_NAME)


def _load_announced(path: Path) -> list[str]:
    """The dispatch keys already announced as DEAD. Missing file = none yet.

    An unreadable cursor is logged and treated as empty: the cost of that
    failure is a repeated DEAD line, the cost of the opposite choice would be
    a death never delivered.
    """
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

    ``monitor_alive`` is tri-state on purpose (FPLAN-0499 phase 2): ``None`` means
    the register never learned a pid — every row written before 2026-09-07 and
    the systemd-scope spawn path — and those fall back to ``overdue`` exactly as
    before. Folding ``None`` into dead would announce the whole backlog at once.
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
        f"{head} — no completion by {_clock(entry.get('expected_by'))}, the hard timeout: "
        "its monitor died (reboot, OOM, kill). Re-dispatch in continue mode."
    )


def _announce_dead(root: Path, seat: str, announced: list[str]) -> int:
    """One register read; one stdout line per NEW dead dispatch of this seat's.

    Reads ``outstanding`` rather than ``overdue`` on purpose: the latter logs a
    json operation every time it finds a late row, and a row stays late until
    @ai_mail closes it — a log write every five minutes forever is exactly the
    idle cost this lane exists to avoid. The only write here is the cursor,
    and only when something new was announced.

    A register that cannot be read is a warning, not a dead wire: completions
    keep flowing through the feed regardless, and the next check retries.
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

    Args:
        once: Return after the first delivery (replayed MISSED events count —
            they ARE the wake the unwired window owed; so does a DEAD line).
        repo_root: Override the repo root holding AIPASS_REGISTRY.json.
        storage_path: Override the watch registry path (tests).
        max_ticks: Bound the follow loop to N ticks (tests). None = unbounded.
        wire_poll: Seconds between delivery ticks.
        dead_check: Seconds between register reads for the dead-monitor
            backstop (tests pass 0 to check every tick).

    Returns:
        dict with ``state`` in {"completed", "stopped"} plus
        ``replayed``/``delivered``/``dead``/``ticks`` counters and ``session``.

    Raises:
        SystemExit(1): after a ``BASELINE DEAD: ...`` stdout line, for any
            failure that ends delivery. Silence must never mean covered.
    """
    root = repo_root if repo_root is not None else find_repo_root()
    if root is None:
        _stdout_event(f"BASELINE DEAD: {_REGISTRY_FILENAME} not found — no root, no coverage")
        raise SystemExit(1)

    # Resolved ONCE, here, and fatal if it fails. Without an identity there is
    # no "mine", so every completion would be filtered out and the wire would
    # sit there looking armed while delivering nothing — silence that reads as
    # coverage, which is the failure this whole release removes. Note the
    # asymmetry with the register: a MISSING register is legitimate (no
    # dispatch has ever been sent here), an unknown seat never is.
    try:
        seat = _dispatches.seat_email(repo_root=root)
    except RuntimeError as exc:
        _stdout_event(f"BASELINE DEAD: cannot tell whose dispatches to deliver — {exc}")
        logger.error("[watchdog.wire] seat unresolved: %s", exc)
        raise SystemExit(1) from exc

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

    _sweep_wires(storage_path)
    _sweep_stale_daemons(storage_path)

    # SIGTERM must run the finally below — a takeover kills the old wire with
    # SIGTERM, and a wire that dies without deregistering leaves the stale
    # entry the next sweep has to bury.
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

    # The cursor is a digest set, not a byte offset, because the feed is trimmed
    # by os.replace and offsets go stale silently across that — see feed.py.
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

        # Sign-in is the moment a death is most likely to be waiting: the
        # reboot that killed the monitor killed the previous wire too.
        announced = _load_announced(_dead_cursor_file(root))
        dead = _announce_dead(root, seat, announced)
        last_dead_check = time.monotonic()

        _stderr(
            f"watchdog wire: armed handle={handle} session={session_name or 'NONE (fg)'} "
            f"replayed={replayed} tick={wire_poll}s"
        )
        if not once:
            # The wrapper is invisible from inside — this line is the only
            # tripwire for the 12:34 mistake (continuous wire armed via
            # run_in_background = zero wakes forever).
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
