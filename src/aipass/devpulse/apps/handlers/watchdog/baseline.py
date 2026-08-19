# =================== AIPass ====================
# Name: baseline.py
# Description: Watchdog Baseline Handler — one always-on watch over every citizen's dispatch lock
# Version: 1.1.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

# Signal choice: the dispatch lock — the same doctrine agent.py polls, widened
# from ONE branch to the whole roster. dispatch_monitor.py creates
# <branch>/.ai_mail.local/.dispatch.lock and ALWAYS deletes it on exit (success
# OR crash), so present->gone is a completion signal for EVERY dispatcher (mine,
# a peer's, the daemon's) — not only for runs devpulse remembered to arm a watch
# for. .ai_mail.local/last_bounce.json separates crash from clean finish.
#
# Poll, never inotify: a recursive observer per process is what leaked 13.7GB on
# 2026-08-18 (DPLAN-0305). ~17 stats every 2s is invisible, and the failure mode
# of stat-polling is a missed tick, not a leak.
#
# CRASH-HONESTY is the profile's whole reason to exist (learning #420): a watcher
# that dies quietly while its owner believes coverage exists is worse than no
# watcher at all. So there is NO blanket try/except around the loop body — a
# per-branch stat miss is logged and retried on the next tick (a branch directory
# vanishing mid-stat is normal), and anything else prints BASELINE DEAD on stdout
# and exits nonzero. Silence must never mean covered.

"""
Watchdog Baseline Handler — wake devpulse when ANY citizen run completes.

The default watch profile: no per-dispatch arming decision, no re-arm after a
wake. One long-lived process polls every citizen — the root AIPASS_REGISTRY.json
plus every hosted project's ``projects/*/*_REGISTRY.json`` — and emits one
stdout line per completion, which a Monitor-tool wrapper turns into a live
notification.

Public surface:
  watch_baseline(once=False, ...) -> dict

Event line (one per completion, flushed, stdout only):
  COMPLETE @<branch> subject="<subject>" age=<seconds>s bounce=<yes|no>
  ...plus ``state=completed_crashed stale_lock_pid=<pid>`` when the monitor PID
  died with its lock still on disk.

See DPLAN-0308 for the design record.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import registry as _registry
from aipass.devpulse.apps.handlers.json import json_handler


# Tick cadence. 2s keeps a completion's wake latency below human notice while
# costing one stat per citizen — the roster is ~17 branches, so a tick is ~17
# syscalls. Named, never inlined: this number is the profile's whole cost model.
POLL_INTERVAL_SECONDS = 2.0

# Consecutive ticks a lock may sit on disk with a DEAD recorded pid before it is
# called a crashed completion. >2 (i.e. the 3rd sighting) rides out the window
# where dispatch_monitor.py rewrites the lock to self-register its own pid — the
# parent's pid is briefly the recorded one and can already be gone.
_STALE_PID_TICKS = 2

_WATCH_KIND = "baseline"
# Self-completions are meaningless — devpulse cannot wake itself with news of
# its own run finishing.
_SELF_BRANCH = "devpulse"
_REGISTRY_FILENAME = "AIPASS_REGISTRY.json"
_LOCK_RELPATH = (".ai_mail.local", ".dispatch.lock")
_BOUNCE_RELPATH = (".ai_mail.local", "last_bounce.json")


def _stderr(msg: str) -> None:
    """Write to stderr — the arm-time/diagnostic channel, never a wake event."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _stdout_event(msg: str) -> None:
    """Write one flushed event line to stdout.

    Same contract as ``agent.py`` (#634 part 2): a Monitor-tool wrapper turns
    every STDOUT line into a live notification and captures stderr to a file it
    never surfaces. So stdout carries ONLY things devpulse must act on —
    completions and the watcher's own death — and everything else goes to
    ``_stderr`` + logger.
    """
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _sleep(seconds: float) -> None:
    """Inter-tick pause.

    Its own function so tests can replace the pause without patching the global
    ``time`` module — a global patch also fires on every daemon thread sleeping
    in the same process (the prax logger spawns three), which the agent suite
    got bitten by.
    """
    time.sleep(seconds)


def _pid_alive(pid: int) -> bool:
    """Liveness for a lock's recorded pid.

    Delegates to the registry's implementation rather than growing a third copy:
    it already guards Windows (``os.kill(pid, 0)`` TERMINATES the target there)
    and treats a Linux zombie as dead.
    """
    return _registry.is_pid_alive(pid)


def _find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward looking for AIPASS_REGISTRY.json. Returns None if not found."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / _REGISTRY_FILENAME).exists():
            return candidate
    return None


def _read_registry_branches(registry_file: Path) -> list[tuple[str, Path]]:
    """Parse the registry into ``[(branch_name, branch_path), ...]``.

    ``branches`` may be a list OR a dict (both shapes exist in the wild — see
    ``agent.py``). Relative paths resolve against the registry's own directory,
    so an off-tree citizen with an absolute path works unchanged.

    Raises OSError / json.JSONDecodeError to the caller: whether an unreadable
    registry is fatal depends on whether a roster is already held, and only the
    caller knows that.
    """
    data = json.loads(registry_file.read_text(encoding="utf-8"))
    raw_branches = data.get("branches", []) if isinstance(data, dict) else []
    if isinstance(raw_branches, dict):
        raw_branches = list(raw_branches.values())

    roster: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for entry in raw_branches:
        if not isinstance(entry, dict):
            continue
        email = str(entry.get("email") or "").strip().lstrip("@").lower()
        name = email or str(entry.get("name") or "").strip().lower()
        raw_path = str(entry.get("path") or "").strip()
        if not name or not raw_path or name in seen:
            continue
        if name == _SELF_BRANCH:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = registry_file.parent / path
        seen.add(name)
        roster.append((name, path))
    return roster


class Roster:
    """The watched roster: the root registry PLUS every hosted project's registry.

    Not every citizen lives in AIPASS_REGISTRY.json. A project the repo hosts
    keeps its own ``<NAME>_REGISTRY.json`` under ``projects/<project>/``, with
    branch paths relative to THAT project's root — and those citizens dispatch
    through the same monitor, so their completions are exactly the wakes this
    profile promises. Missing them is not a smaller roster, it is a silent
    coverage hole: @baud completed at 20:14 on 2026-08-18 and the baseline said
    nothing, while ``watchdog agent @baud`` had been resolving that seat for
    days. Discovery mirrors ai_mail's ``get_project_tree_branches`` and
    agent.py's resolver — one level down, deliberately, never a recursive walk.

    Two cadences, deliberately different:
      - the GLOB runs every tick (a handful of directory entries), so a project
        born mid-watch joins the roster without a restart;
      - the PARSE stays gated on mtime PER FILE, so the cost that actually
        matters is still paid only for the file that changed (DPLAN-0305).
    """

    def __init__(self, registry_file: Path) -> None:
        self.registry_file = registry_file
        self.projects_dir = registry_file.parent / "projects"
        self.branches: list[tuple[str, Path]] = []
        self.root_count = 0
        self.project_count = 0
        self.reloads = 0
        self._mtimes: dict[Path, float] = {}
        self._parsed: dict[Path, list[tuple[str, Path]]] = {}

    def refresh(self, required: bool = False) -> bool:
        """Re-glob, re-parse what changed, rebuild. True if the roster changed.

        ``required=True`` (the first load) lets a ROOT registry failure raise —
        a watcher that starts with no roster covers nothing while looking alive.
        Nothing else is fatal: a hosted project's broken or vanished registry
        costs its own citizens their coverage, never the whole fleet's.
        """
        files = [self.registry_file, *self._project_registries()]
        changed = False

        for gone in [path for path in self._parsed if path not in files]:
            del self._parsed[gone]
            self._mtimes.pop(gone, None)
            logger.info("[watchdog.baseline] project registry gone, dropping its citizens: %s", gone)
            _stderr(f"watchdog baseline: {gone.name} is gone — its citizens leave the roster")
            changed = True

        for path in files:
            if self._reload_file(path, required=required and path == self.registry_file):
                changed = True

        if changed:
            self._rebuild()
            self.reloads += 1
        return changed

    def _project_registries(self) -> list[Path]:
        """Every hosted project's registry — ``projects/*/*_REGISTRY.json``."""
        try:
            return sorted(self.projects_dir.glob("*/*_REGISTRY.json"))
        except OSError as exc:
            # Keep the projects already known rather than shrinking the roster
            # because one directory listing failed for an instant.
            logger.warning("[watchdog.baseline] projects glob failed, keeping known projects: %s", exc)
            return sorted(path for path in self._parsed if path != self.registry_file)

    def _reload_file(self, path: Path, required: bool) -> bool:
        """Parse one registry if its mtime moved. True if this file's branches changed."""
        try:
            mtime = path.stat().st_mtime
            if self._mtimes.get(path) == mtime:
                return False
            branches = _read_registry_branches(path)
        except (OSError, json.JSONDecodeError) as exc:
            if required:
                raise
            held = len(self._parsed.get(path, []))
            logger.warning("[watchdog.baseline] registry %s re-read failed, keeping %s branches: %s", path, held, exc)
            _stderr(f"watchdog baseline: {path.name} re-read failed ({exc}) — keeping its {held} branches")
            return False

        self._parsed[path] = branches
        self._mtimes[path] = mtime
        return True

    def _rebuild(self) -> None:
        """Merge every parsed registry, root FIRST.

        Order is the collision rule agent.py already ships: a local branch
        always wins a name a hosted project also claims.
        """
        merged: list[tuple[str, Path]] = []
        seen: set[str] = set()
        root_count = 0
        project_count = 0
        project_files = sorted(path for path in self._parsed if path != self.registry_file)
        for path in [self.registry_file, *project_files]:
            for name, branch_path in self._parsed.get(path, []):
                if name in seen:
                    continue
                seen.add(name)
                merged.append((name, branch_path))
                if path == self.registry_file:
                    root_count += 1
                else:
                    project_count += 1
        self.branches = merged
        self.root_count = root_count
        self.project_count = project_count

    def summary(self) -> str:
        """Count split for the arm line — a coverage gap has to be visible at a glance."""
        return f"branches={len(self.branches)} (root={self.root_count} projects={self.project_count})"

    def names(self) -> set[str]:
        """Branch names currently on the roster."""
        return {name for name, _path in self.branches}


class BranchState:
    """One branch's lock memory between ticks.

    The lock's contents are cached WHILE IT EXISTS because the completion event
    has to name a subject and an age for a file that is already gone by the time
    we notice — and because dispatch_monitor.py rewrites the lock non-atomically
    to self-register its pid, so a tick can catch a torn document and must fall
    back on what it last read rather than forget the dispatch.
    """

    __slots__ = (
        "present",
        "lock_data",
        "lock_key",
        "lock_stamp",
        "lock_mtime",
        "stat_key",
        "dead_ticks",
        "crashed_reported",
        "error_reported",
    )

    def __init__(self) -> None:
        self.present = False
        self.lock_data: dict | None = None
        self.lock_key: tuple | None = None
        self.lock_stamp: float | None = None
        self.lock_mtime: float | None = None
        self.stat_key: tuple | None = None
        self.dead_ticks = 0
        self.crashed_reported = False
        self.error_reported = False

    def observe_present(self, st: os.stat_result) -> bool:
        """Record a sighting. True if the file changed since the last sighting.

        Presence is recorded BEFORE anything tries to parse the lock, so a torn
        read can never lose the sighting itself — losing it would mean the
        following disappearance reports no completion at all.
        """
        self.present = True
        self.lock_mtime = st.st_mtime
        key = (st.st_mtime, st.st_size)
        changed = key != self.stat_key
        self.stat_key = key
        return changed

    def adopt_lock(self, data: dict) -> None:
        """Cache freshly read lock contents; reset per-dispatch state on a new lock."""
        key = (data.get("pid"), data.get("timestamp"))
        if key != self.lock_key:
            self.lock_key = key
            self.dead_ticks = 0
            self.crashed_reported = False
        self.lock_data = data
        self.lock_stamp = _parse_lock_timestamp(data.get("timestamp"))

    def reset(self) -> None:
        """Forget the dispatch — the lock is gone."""
        self.present = False
        self.lock_data = None
        self.lock_key = None
        self.lock_stamp = None
        self.lock_mtime = None
        self.stat_key = None
        self.dead_ticks = 0
        self.crashed_reported = False


def _parse_lock_timestamp(raw: object) -> float | None:
    """Lock ``timestamp`` -> epoch seconds, or None when it can't be read.

    Two writers, two formats: daemon.py writes ``datetime.now().isoformat()``
    (microseconds) and wake.py writes ``time.strftime("%Y-%m-%dT%H:%M:%S")``.
    ``fromisoformat`` accepts both, plus the space-separated variant.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip()).timestamp()
    except ValueError as exc:
        logger.warning("[watchdog.baseline] unparseable lock timestamp %r: %s", raw, exc)
        return None


def _stat_lock(lock_file: Path) -> os.stat_result | None:
    """Stat the lock: its result if present, None if absent.

    One syscall answers both questions the tick asks — existence and mtime — and
    absence is the expected answer for most branches most of the time, so it is
    not an error. Any OTHER OSError (permissions, a vanished parent mid-walk)
    propagates to the per-branch handler.
    """
    try:
        return lock_file.stat()
    except FileNotFoundError as exc:
        # debug, deliberately: an absent lock is the ordinary answer for most
        # branches on most ticks. At info it would write ~17 lines every 2s
        # forever and bury the events that matter; at debug the probe trail is
        # there the moment someone lowers the level to look for it.
        logger.debug("[watchdog.baseline] no lock at %s: %s", lock_file, exc)
        return None


def _read_lock_json(lock_file: Path) -> dict | None:
    """Read the lock document, or None if it can't be read this tick.

    A miss is routine, not fatal: dispatch_monitor.py rewrites the lock in place
    (no atomic replace) to self-register its pid, so a reader can catch a
    half-written document. The caller keeps whatever it last read.
    """
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[watchdog.baseline] lock unreadable this tick %s: %s", lock_file, exc)
        return None
    return data if isinstance(data, dict) else None


def _bounce_after(branch_path: Path, base_epoch: float | None) -> bool:
    """True if last_bounce.json exists and is newer than the lock's timestamp.

    The bounce file is the monitor's crash marker; an OLD one belongs to a
    previous run and must not brand this completion a crash.
    """
    bounce_file = branch_path.joinpath(*_BOUNCE_RELPATH)
    try:
        st = bounce_file.stat()
    except FileNotFoundError as exc:
        # No bounce marker is the good news — a clean finish, not a failure.
        logger.debug("[watchdog.baseline] no bounce file at %s: %s", bounce_file, exc)
        return False
    except OSError as exc:
        # Deliberate: a probe failure downgrades ONE field rather than killing
        # the report. Losing the completion event entirely — the thing this
        # watcher exists to emit — would be the worse trade.
        logger.warning("[watchdog.baseline] bounce stat failed for %s: %s", branch_path, exc)
        return False
    if base_epoch is None:
        logger.warning(
            "[watchdog.baseline] no comparable lock timestamp for %s — reporting bounce on presence alone",
            branch_path,
        )
        return True
    return st.st_mtime > base_epoch


def _one_line(text: str) -> str:
    """Collapse whitespace and neutralize quotes — one event is one line."""
    return " ".join(text.split()).replace('"', "'")


def _completion_record(name: str, branch_path: Path, state: BranchState, kind: str, pid: object = None) -> dict:
    """Build the completion event from the lock data cached while it existed."""
    subject = ""
    if isinstance(state.lock_data, dict):
        subject = _one_line(str(state.lock_data.get("subject") or ""))
    age = None
    if state.lock_stamp is not None:
        age = max(0, int(time.time() - state.lock_stamp))
    # Bounce is compared against the lock's own timestamp; when that was
    # unparseable the lock file's mtime is the honest stand-in (logged above).
    base = state.lock_stamp if state.lock_stamp is not None else state.lock_mtime
    return {
        "branch": name,
        "subject": subject or "?",
        "age": age,
        "bounce": _bounce_after(branch_path, base),
        "state": kind,
        "pid": pid,
    }


def _format_completion(record: dict) -> str:
    """Render one completion as its stdout event line."""
    age = f"{record['age']}s" if record["age"] is not None else "unknown"
    line = (
        f'COMPLETE @{record["branch"]} subject="{record["subject"]}" '
        f"age={age} bounce={'yes' if record['bounce'] else 'no'}"
    )
    if record["state"] == "completed_crashed":
        line += (
            f" state=completed_crashed stale_lock_pid={record['pid']} "
            f"— monitor PID dead with the lock still on disk; lock NOT removed (not ours)"
        )
    return line


def _scan_branch(name: str, branch_path: Path, state: BranchState) -> dict | None:
    """One branch, one tick. Returns a completion record or None.

    Two completions exist:
      - lock present -> gone: the ordinary finish, however it finished.
      - lock present with a DEAD recorded pid for more than ``_STALE_PID_TICKS``
        ticks: a crashed run whose monitor never got to clean up. Reported once,
        loudly, and the branch is treated as idle from then on — the lock is NOT
        deleted, it isn't ours to delete.
    """
    lock_file = branch_path.joinpath(*_LOCK_RELPATH)
    st = _stat_lock(lock_file)

    if st is None:
        record = None
        if state.present and not state.crashed_reported:
            record = _completion_record(name, branch_path, state, "completed")
        state.reset()
        return record

    changed = state.observe_present(st)
    if changed:
        data = _read_lock_json(lock_file)
        if data is not None:
            state.adopt_lock(data)

    if state.crashed_reported:
        return None

    pid = state.lock_data.get("pid") if isinstance(state.lock_data, dict) else None
    if not isinstance(pid, int):
        # No pid to check (never read the lock, or it carries none). The
        # present->gone signal still covers this branch; only the crashed-lock
        # detection is unavailable.
        return None

    if _pid_alive(pid):
        state.dead_ticks = 0
        return None

    state.dead_ticks += 1
    if state.dead_ticks <= _STALE_PID_TICKS:
        return None

    state.crashed_reported = True
    return _completion_record(name, branch_path, state, "completed_crashed", pid=pid)


def _note_branch_error(name: str, state: BranchState, exc: OSError) -> None:
    """Announce a per-branch probe failure on stderr — once, on the transition.

    The caller logs every occurrence; stderr gets only the change of state,
    because a branch failing every 2s forever would otherwise bury the real
    events under its own repetition.
    """
    if not state.error_reported:
        _stderr(f"watchdog baseline: @{name} probe failed ({exc}) — retrying next tick")
        state.error_reported = True


def _clear_branch_error(name: str, state: BranchState) -> None:
    """Announce recovery once, so a reported failure always gets an ending."""
    if state.error_reported:
        _stderr(f"watchdog baseline: @{name} probe recovered")
        state.error_reported = False


def _arm(storage_path: Path | None, poll_interval: float) -> dict:
    """Claim the single baseline slot in watchdog_active.json.

    Idempotent by design (DPLAN-0308): session-start arming has to be safe to
    repeat blindly or it will not be run every session. A live registered pid
    means coverage already exists; a dead one is a watcher that died without
    deregistering, which is replaced and SAID OUT LOUD — a slot silently reused
    is how a dead watcher passes for a live one.

    ``prune_stale=False`` deliberately: pruning here would also delete other
    watch types' entries as a side effect of arming.
    """
    active = _registry.list_active(storage_path=storage_path, prune_stale=False)
    stale_replaced = 0
    for watch in active:
        if watch.get("type") != _WATCH_KIND:
            continue
        pid = watch.get("pid")
        handle = watch.get("handle")
        if isinstance(pid, int) and _pid_alive(pid):
            return {"state": "already_armed", "pid": pid, "handle": handle}
        if isinstance(handle, str):
            _registry.deregister(handle, storage_path=storage_path)
        _stderr(f"watchdog baseline: replaced stale entry {handle} (registered pid {pid} is dead)")
        logger.info("[watchdog.baseline] replaced stale entry handle=%s pid=%s", handle, pid)
        stale_replaced += 1

    handle = _registry.register(
        _WATCH_KIND,
        metadata={"scope": "all citizens", "tick_seconds": poll_interval},
        storage_path=storage_path,
    )
    return {"state": "armed", "handle": handle, "stale_replaced": stale_replaced}


def _run_loop(
    registry_file: Path,
    handle: str,
    once: bool,
    poll_interval: float,
    max_ticks: int | None,
    started_at: float,
) -> dict:
    """The poll loop. Raises on anything unexpected — see the crash boundary."""
    roster = Roster(registry_file)
    roster.refresh(required=True)
    if not roster.branches:
        # An empty roster is the exact shape of the failure this profile exists
        # to prevent: a watcher that runs, looks healthy, and covers nothing.
        raise RuntimeError(
            f"roster is empty — neither {registry_file} nor projects/*/*_REGISTRY.json "
            f"lists a citizen besides @{_SELF_BRANCH}"
        )

    # The count split is the line that would have caught tonight's gap on sight:
    # projects=0 with a projects/ tree full of citizens is a visible wrong number.
    _stderr(
        f"watchdog baseline: armed handle={handle} {roster.summary()} "
        f"tick={poll_interval}s mode={'once' if once else 'continuous'}"
    )

    states: dict[str, BranchState] = {}
    ticks = 0
    completions = 0

    while True:
        ticks += 1
        if roster.refresh():
            live = roster.names()
            states = {name: state for name, state in states.items() if name in live}
            _stderr(f"watchdog baseline: roster reloaded — {roster.summary()}")

        batch: list[dict] = []
        for name, branch_path in roster.branches:
            state = states.setdefault(name, BranchState())
            try:
                record = _scan_branch(name, branch_path, state)
            except OSError as exc:
                # ONE branch's filesystem probe failing this tick is an event to
                # log, not a reason to stop watching the other sixteen.
                logger.warning("[watchdog.baseline] branch %s probe failed: %s", name, exc)
                _note_branch_error(name, state, exc)
                continue
            _clear_branch_error(name, state)
            if record is not None:
                batch.append(record)

        for record in batch:
            _stdout_event(_format_completion(record))
            logger.info(
                "[watchdog.baseline] completion branch=%s state=%s age=%s bounce=%s",
                record["branch"],
                record["state"],
                record["age"],
                record["bounce"],
            )
        completions += len(batch)

        if once and batch:
            return _result("completed", handle, roster, ticks, completions, started_at)
        if max_ticks is not None and ticks >= max_ticks:
            return _result("stopped", handle, roster, ticks, completions, started_at)

        _sleep(poll_interval)


def _result(
    state: str, handle: str | None, roster: Roster | None, ticks: int, completions: int, started_at: float
) -> dict:
    """Uniform return shape for every exit path that returns at all."""
    return {
        "state": state,
        "handle": handle,
        "branches": len(roster.branches) if roster is not None else 0,
        "ticks": ticks,
        "completions": completions,
        "elapsed": int(time.monotonic() - started_at),
    }


def watch_baseline(
    once: bool = False,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    repo_root: Path | None = None,
    storage_path: Path | None = None,
    max_ticks: int | None = None,
) -> dict:
    """Watch every citizen's dispatch lock and report each completion.

    Args:
        once: Return after the first tick that reports at least one completion
            (the ``run_in_background`` Bash wake style). Default False = run
            forever emitting event lines, which is what a Monitor-tool wrapper
            consumes — one long-lived watcher, no re-arm after each wake.
        poll_interval: Seconds between ticks. Default ``POLL_INTERVAL_SECONDS``.
        repo_root: Override the repo root holding AIPASS_REGISTRY.json.
        storage_path: Override the watch registry path.
        max_ticks: Bound the run to N ticks. None = unbounded.

    Returns:
        dict with keys ``state``, ``handle``, ``branches``, ``ticks``,
        ``completions``, ``elapsed``. ``state`` is one of ``already_armed``
        (another live baseline holds the slot), ``completed`` (``once`` fired),
        ``stopped`` (``max_ticks`` reached).

    Raises:
        SystemExit(1): after printing ``BASELINE DEAD: <error>`` on stdout, for
            any failure that ends the watch. Never returns quietly on error —
            silence must never mean covered.
    """
    started_at = time.monotonic()

    root = repo_root if repo_root is not None else _find_repo_root()
    registry_file = (root / _REGISTRY_FILENAME) if root is not None else None
    if registry_file is None or not registry_file.exists():
        _stdout_event(f"BASELINE DEAD: {_REGISTRY_FILENAME} not found — no roster, no coverage")
        logger.error("[watchdog.baseline] no registry found from root=%s", root)
        raise SystemExit(1)

    armed = _arm(storage_path, poll_interval)
    if armed["state"] == "already_armed":
        _stderr(f"baseline already armed (pid {armed['pid']})")
        logger.info("[watchdog.baseline] already armed pid=%s", armed["pid"])
        return {
            "state": "already_armed",
            "handle": armed.get("handle"),
            "branches": 0,
            "ticks": 0,
            "completions": 0,
            "elapsed": int(time.monotonic() - started_at),
            "pid": armed["pid"],
        }

    handle = armed["handle"]
    json_handler.log_operation("watch_baseline", {"handle": handle, "once": once})

    try:
        return _run_loop(registry_file, handle, once, poll_interval, max_ticks, started_at)
    except KeyboardInterrupt:
        # An operator stopping the watcher is not a crash — it is still the end
        # of coverage, so it is announced, just not on the wake channel.
        _stderr("watchdog baseline: interrupted — watch ended")
        logger.info("[watchdog.baseline] interrupted handle=%s", handle)
        raise
    except Exception as exc:
        # The crash boundary: announce and die. It does NOT continue the loop —
        # a caught-and-continued exception is precisely the silent half-dead
        # watcher this profile refuses to be.
        _stdout_event(f"BASELINE DEAD: {type(exc).__name__}: {exc}")
        logger.error("[watchdog.baseline] died handle=%s: %s", handle, exc, exc_info=True)
        raise SystemExit(1) from exc
    finally:
        _registry.deregister(handle, storage_path=storage_path)
