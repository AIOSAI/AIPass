# =================== AIPass ====================
# Name: agent.py
# Description: Watchdog Agent Handler — block until dispatched agent exits
# Version: 1.6.0
# Created: 2026-04-14
# Modified: 2026-10-26
# =============================================

# Liveness is ai_mail's dispatch lock: dispatch_monitor deletes it on any exit.
# last_bounce.json, which the monitor writes only on failure, tells a crash from a success.

"""Watchdog Agent Handler — block until a dispatched agent process exits."""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import registry as _registry
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.ai_mail.apps.modules.door_session_pointer import CLAUDE, CODEX, codex_thread_file, read_pointer


def _stderr(msg: str) -> None:
    """Write to stderr — visible in debug runs, doesn't pollute stdout capture."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _stdout_event(msg: str) -> None:
    """Write one flushed event line to stdout so a Monitor-tool wrapper turns it
    into a live notification to devpulse.

    The Monitor tool never surfaces stderr, so signals a caller must act on go here.
    """
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward looking for AIPASS_REGISTRY.json. Returns None if not found."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "AIPASS_REGISTRY.json").exists():
            return candidate
    return None


class RegistryUnreadable(Exception):
    """The main registry exists but cannot be read; no branch may be resolved past it."""


def _search_registry(registry_file: Path, target_email: str, strict: bool = False) -> Path | None:
    """Search a single registry file for a branch matching target_email.

    An unreadable registry costs only its own rows, except with ``strict`` (the
    main registry): there it raises RegistryUnreadable, because skipping it lets
    a projects/* namesake answer for a core citizen.
    """
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        if not isinstance(registry, dict):
            raise ValueError(f"not a JSON object: {type(registry).__name__}")
    except (OSError, ValueError) as exc:
        logger.warning("[watchdog.agent] failed to read registry %s: %s", registry_file, exc)
        if strict:
            raise RegistryUnreadable(f"{registry_file}: {exc}") from exc
        return None
    registry_dir = registry_file.parent
    raw_branches = registry.get("branches", [])
    if isinstance(raw_branches, dict):
        raw_branches = list(raw_branches.values())
    for branch in raw_branches:
        if branch.get("email", "").lower() == target_email:
            raw_path = branch.get("path", "")
            path = Path(raw_path)
            if not path.is_absolute():
                path = registry_dir / path
            return path if path.exists() else None
        name = branch.get("name", "").lower()
        if f"@{name}" == target_email:
            raw_path = branch.get("path", "")
            path = Path(raw_path)
            if not path.is_absolute():
                path = registry_dir / path
            return path if path.exists() else None
    return None


def _resolve_branch_path(agent_id: str) -> Path | None:
    """Resolve an `@branch` token (or bare name) to its absolute branch path."""
    target = f"@{agent_id.lstrip('@').lower()}"

    repo_root = _find_repo_root()
    if repo_root is not None:
        registry_file = repo_root / "AIPASS_REGISTRY.json"
        result = _search_registry(registry_file, target, strict=True)
        if result is not None:
            return result

        # After the main registry, so a local branch wins a name collision. Windows globs
        # case-insensitively: re-check the suffix so a *_registry.json is never a trust anchor.
        project_regs = (repo_root / "projects").glob("*/*_REGISTRY.json")
        for reg in sorted(p for p in project_regs if p.name.endswith("_REGISTRY.json")):
            result = _search_registry(reg, target)
            if result is not None:
                return result

    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    search_roots = []
    if caller_cwd:
        search_roots.append(Path(caller_cwd))
    projects_dir = Path.home() / "Projects"
    if projects_dir.is_dir():
        search_roots.extend(sorted(projects_dir.iterdir()))

    seen = set()
    if repo_root:
        seen.add((repo_root / "AIPASS_REGISTRY.json").resolve())
    for root in search_roots:
        if not root.is_dir():
            continue
        for reg in root.glob("*_REGISTRY.json"):
            if not reg.name.endswith("_REGISTRY.json"):
                continue  # Windows globs case-insensitively; exact-case names only
            resolved = reg.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            result = _search_registry(reg, target)
            if result is not None:
                return result
    return None


def _pid_alive(pid: int) -> bool:
    """registry.py owns the one liveness rule (Windows OpenProcess, zombie check); a probe that raises is seen."""
    return _registry.is_pid_alive(pid)


def _get_jsonl_projects_dir(branch_path: Path) -> Path:
    """Get Claude's JSONL projects directory for a branch path."""
    cwd = str(branch_path)
    encoded = cwd.replace("\\", "-").replace("/", "-").replace(":", "-").replace("_", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _tail_lines(path: Path, max_bytes: int = 1_000_000) -> list[str] | None:
    """Non-blank newline-delimited lines from a bounded tail read of ``path``; ``None`` when it cannot be read.

    A line cut by the bound fails to parse downstream and is skipped. ``None`` is no verdict: the
    caller treats it as in flight and never caches it.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            chunk = fh.read()
    except OSError as exc:
        logger.info("[watchdog.agent] tail read failed for %s: %s", path.name, exc)
        return None
    if not chunk:
        return []
    text = chunk.decode("utf-8", errors="replace")
    return [ln for ln in text.splitlines() if ln.strip()]


# Bookkeeping lines between message entries are few; the last message sits well inside this.
_INFLIGHT_SCAN_LIMIT = 25


def _inflight_from_lines(lines: list[str], source: str = "?") -> bool:
    """True if the last MESSAGE event in ``lines`` is an assistant message
    dispatching a tool call — an in-flight ``tool_use`` awaiting its result.

    A running tool writes no JSONL, so size growth alone false-fires STALLED. Bookkeeping
    lines can land after the ``tool_use``, so walk back to the last line carrying a role.
    """
    for line in reversed(lines[-_INFLIGHT_SCAN_LIMIT:]):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.info("[watchdog.agent] skipping unparseable transcript line in %s: %s", source, exc)
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            message = entry
        role = message.get("role")
        if role == "assistant":
            content = message.get("content")
            if not isinstance(content, list):
                return False
            return any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content)
        if role == "user":
            return False
    return False


# turn_aborted is how an interrupted rollout ends; Codex writes no session_end/shutdown record.
_CODEX_TURN_END = frozenset({"task_complete", "turn_aborted"})


def _codex_inflight_from_lines(lines: list[str], source: str = "?") -> bool:
    """True unless the rollout's last line is an ``event_msg`` ending the turn.

    An unparseable last line is Codex mid-write, so it counts as in flight.
    """
    if not lines:
        return False
    try:
        entry = json.loads(lines[-1])
    except (json.JSONDecodeError, ValueError) as exc:
        logger.info("[watchdog.agent] unparseable rollout tail in %s, treated as in flight: %s", source, exc)
        return True
    payload = entry.get("payload") if isinstance(entry, dict) else None
    ended = entry.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") in _CODEX_TURN_END
    return not ended


class TranscriptScanner:
    """Cached per-tick view of one branch's ``~/.claude/projects/<dir>`` tree, or of the one
    Codex rollout its session pointer names when built with ``branch_path``.

    A full walk and tail re-read every tick cost a few percent of a core per watch, so a
    tick is one ``os.stat`` pass and the tail verdict is cached on ``(size, mtime)``.
    """

    # New transcripts are rare and the 300s stall threshold dwarfs this cadence.
    REFRESH_INTERVAL = 60.0
    _VERDICT_CACHE_MAX = 64

    def __init__(self, projects_dir: Path, now: float, branch_path: Path | None = None) -> None:
        self.projects_dir = projects_dir
        self.branch_path = branch_path
        self.provider = CLAUDE
        self._codex_thread: str | None = None
        self._watched: tuple[str, str] | None = None
        self._top_dir = str(projects_dir)
        self._paths: list[str] = []
        self._last_refresh = now
        self.sizes: dict[str, int] = {}
        self.newest: tuple[str, int, float] | None = None
        self.newest_toplevel: tuple[str, int, float] | None = None
        self._verdicts: dict[str, tuple[tuple[int, float], bool]] = {}
        self.unreadable: dict[str, str] = {}
        self.refresh(now)
        self._stat_pass()  # seed sizes: watch start is the baseline, not "everything is new"

    def refresh(self, now: float) -> None:
        """Re-read the pointer, then re-list the watched files with the provider's lister."""
        self._follow_pointer()
        paths, unreadable = self._codex_paths() if self.provider == CODEX else self._claude_paths()
        self._paths = paths
        self.unreadable = unreadable
        self._last_refresh = now

    def _follow_pointer(self) -> None:
        """Pick the provider from the branch's pointer, so a ``/codex`` switch is followed next refresh."""
        if self.branch_path is None:
            return
        pointer = read_pointer(self.branch_path) or {}
        codex = pointer.get("provider") == CODEX
        self.provider = CODEX if codex else CLAUDE
        self._codex_thread = pointer.get("session_id") if codex else None

    def _codex_paths(self) -> tuple[list[str], dict[str, str]]:
        thread_file = codex_thread_file(self._codex_thread) if self._codex_thread else None
        self._note_watched(str(thread_file))
        return ([str(thread_file)] if thread_file is not None else []), {}

    def _note_watched(self, path: str) -> None:
        if self._watched != (self.provider, path):
            self._watched = (self.provider, path)
            logger.debug("[watchdog.agent] scanner watching provider=%s path=%s", self.provider, path)

    def _claude_paths(self) -> tuple[list[str], dict[str, str]]:
        """Walk the tree for ``.jsonl`` files (``os.walk`` — pathlib.rglob
        spent most of the old tick in ``relative_to``/path-object overhead).

        An unlistable directory lands in ``unreadable``, never dropped in silence.
        """
        if self.branch_path is not None:
            self._note_watched(self._top_dir)
        paths: list[str] = []
        unreadable: dict[str, str] = {}

        def _record(exc: OSError) -> None:
            unreadable[exc.filename or self._top_dir] = exc.strerror or str(exc)

        for root, _dirs, files in os.walk(self.projects_dir, onerror=_record):
            for name in files:
                if name.endswith(".jsonl"):
                    paths.append(os.path.join(root, name))
        if unreadable:
            logger.warning(
                "[watchdog.agent] scanner could not list %d dir(s) under %s: %s",
                len(unreadable),
                self.projects_dir,
                "; ".join(f"{path}: {err}" for path, err in unreadable.items()),
            )
        return paths, unreadable

    def _stat_pass(self) -> dict:
        """Stat every known file; update ``sizes``/``newest``; return the previous sizes."""
        sizes: dict[str, int] = {}
        newest: tuple[str, int, float] | None = None
        newest_top: tuple[str, int, float] | None = None
        vanished = False
        for path in self._paths:
            try:
                st = os.stat(path)
            except OSError as exc:
                # rolled/cleaned — deletion is not activity; pruned below, so one log per file
                logger.info("[watchdog.agent] transcript vanished, dropping from scan: %s (%s)", path, exc)
                vanished = True
                continue
            sizes[path] = st.st_size
            if newest is None or st.st_mtime > newest[2]:
                newest = (path, st.st_size, st.st_mtime)
            if os.path.dirname(path) == self._top_dir and (newest_top is None or st.st_mtime > newest_top[2]):
                newest_top = (path, st.st_size, st.st_mtime)
        if vanished:
            self._paths = list(sizes)
        self.newest = newest
        self.newest_toplevel = newest_top
        prev, self.sizes = self.sizes, sizes
        return prev

    def tick(self, now: float) -> bool:
        """One poll tick: True if any known transcript grew or a newly
        discovered one has content, compared against the sizes seen at the
        previous tick.

        Recursive: a parent waiting on a sub-agent writes nothing while ``subagents/`` grows.
        """
        if now - self._last_refresh >= self.REFRESH_INTERVAL:
            self.refresh(now)
        prev = self._stat_pass()
        return any(size > prev.get(path, 0) for path, size in self.sizes.items())

    def last_entry_inflight(self) -> bool:
        """In-flight tool_use in the newest transcript OR the newest top-level
        session transcript.

        A parent blocked on a sub-agent holds its in-flight call in the parent
        transcript while the sub-agent's nested file is the newest.
        """
        checked: set[str] = set()
        for candidate in (self.newest, self.newest_toplevel):
            if candidate is None or candidate[0] in checked:
                continue
            checked.add(candidate[0])
            if self._cached_verdict(*candidate):
                return True
        return False

    def _cached_verdict(self, path: str, size: int, mtime: float) -> bool:
        key = (size, mtime)
        hit = self._verdicts.get(path)
        if hit is not None and hit[0] == key:
            return hit[1]
        lines = _tail_lines(Path(path))
        if lines is None:
            return True
        rule = _codex_inflight_from_lines if self.provider == CODEX else _inflight_from_lines
        verdict = rule(lines, source=os.path.basename(path))
        if len(self._verdicts) >= self._VERDICT_CACHE_MAX:
            self._verdicts = {p: v for p, v in self._verdicts.items() if p in self.sizes}
        self._verdicts[path] = (key, verdict)
        return verdict


def _read_lock(lock_file: Path) -> dict | None:
    """Read the dispatch lock: its dict, None when absent, ``{"unreadable": reason}`` when held but unreadable.

    An unparseable lock is still a dispatch in flight, the same rule as ai_mail's pid_lock.
    """
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("[watchdog.agent] lock %s unreadable, treated as held: %s", lock_file, exc)
        return {"unreadable": str(exc)}
    return data if isinstance(data, dict) else {}


def _check_sent_for_reply(branch_path: Path, dispatch_ts: str | None) -> bool:
    """Check if the agent sent any messages after the dispatch timestamp."""
    sent_dir = branch_path / ".ai_mail.local" / "sent"
    if not sent_dir.is_dir():
        return False

    baseline = None
    if dispatch_ts:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                baseline = datetime.strptime(dispatch_ts, fmt)
                break
            except ValueError:
                logger.info("[watchdog.agent] dispatch_ts %r didn't match fmt %s", dispatch_ts, fmt)
                continue

    for msg_file in sent_dir.iterdir():
        if not msg_file.suffix == ".json":
            continue
        try:
            data = json.loads(msg_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.info("[watchdog.agent] skipping unreadable sent file %s: %s", msg_file.name, exc)
            continue
        if baseline is None:
            return True
        msg_ts_str = data.get("timestamp", "")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                msg_ts = datetime.strptime(msg_ts_str, fmt)
                if msg_ts >= baseline:
                    return True
                break
            except ValueError:
                logger.info("[watchdog.agent] msg timestamp %r didn't match fmt %s", msg_ts_str, fmt)
                continue
    return False


def _classify_exit(
    branch_path: Path,
    lock_existed: bool,
    dispatch_ts: str | None = None,
) -> tuple[str, str, int | None]:
    """After lock disappears, decide success vs crash vs silent finish.

    States: completed_replied, completed_silent, crashed.
    """
    bounce_file = branch_path / ".ai_mail.local" / "last_bounce.json"
    if bounce_file.exists():
        try:
            data = json.loads(bounce_file.read_text(encoding="utf-8"))
            exit_code = data.get("exit_code")
            return (
                "crashed",
                f"agent crashed (last_bounce.json exit_code={exit_code})",
                exit_code if isinstance(exit_code, int) else None,
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[watchdog.agent] bounce file unreadable: %s", exc)
            return ("crashed", "agent crashed (bounce file present, unreadable)", None)

    replied = _check_sent_for_reply(branch_path, dispatch_ts)
    if replied:
        reason = "agent finished cleanly (lock removed)" if lock_existed else "agent finished cleanly"
        return ("completed_replied", reason, 0)

    reason = "agent exited without sending a reply"
    if lock_existed:
        reason += " (lock removed)"
    return ("completed_silent", reason, 0)


class StallTracker:
    """Per-watch JSONL liveness/stall state — one ``observe()`` call per poll tick.

    Liveness is JSONL growth OR an in-flight tool call, so one long tool call is not a stall.
    """

    # Silent spans are routine: a long response or a compaction writes nothing for minutes.
    # 120s false-fired on every one; 300s clears them and still surfaces a wedged agent.
    STALL_THRESHOLD = 300.0
    # Below the 600s default timeout, so a long watch hears of a hung tool before it ends.
    LONG_TOOL_THRESHOLD = 300.0

    def __init__(
        self,
        agent_id: str,
        jsonl_dir: Path,
        now: float,
        pid: object,
        scanner: TranscriptScanner | None = None,
        branch_path: Path | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.jsonl_dir = jsonl_dir
        self.pid = pid
        self.scanner = scanner if scanner is not None else TranscriptScanner(jsonl_dir, now, branch_path)
        self.last_activity_at = now
        self.in_flight_since: float | None = None
        self.stall_reported = False
        self.long_tool_reported = False

    def observe(self, now: float) -> None:
        """Evaluate one poll tick: reset on activity, else report a stall past threshold."""
        size_grew = self.scanner.tick(now)
        inflight = False if size_grew else self.scanner.last_entry_inflight()
        if (
            not size_grew
            and not inflight
            and not self.stall_reported
            and (now - self.last_activity_at) >= self.STALL_THRESHOLD
        ):
            # Re-walk before declaring a stall, so a transcript born since the last refresh counts.
            self.scanner.refresh(now)
            size_grew = self.scanner.tick(now)
            inflight = False if size_grew else self.scanner.last_entry_inflight()
        if size_grew or inflight:
            self._mark_active(now, inflight)
        elif not self.stall_reported and (now - self.last_activity_at) >= self.STALL_THRESHOLD:
            self._report_stall(now)

    def _mark_active(self, now: float, inflight: bool) -> None:
        self.last_activity_at = now
        if self.stall_reported:
            _stdout_event(f"[watchdog.resumed] {self.agent_id}: JSONL activity resumed — stall cleared")
            _stderr(f"[watchdog.agent] {self.agent_id}: activity resumed")
            logger.info("[watchdog.agent] activity resumed agent_id=%s", self.agent_id)
            self.stall_reported = False
        if inflight:
            self._track_inflight(now)
        else:
            self.in_flight_since = None
            self.long_tool_reported = False

    def _track_inflight(self, now: float) -> None:
        if self.in_flight_since is None:
            self.in_flight_since = now
        inflight_secs = int(now - self.in_flight_since)
        if self.long_tool_reported or inflight_secs < self.LONG_TOOL_THRESHOLD:
            return
        _stdout_event(
            f"[watchdog.longtool] {self.agent_id}: one tool call running {inflight_secs}s "
            f"(PID {self.pid} alive) — likely a heavy op, but may be a hung tool. "
            f"Check, or kill+resume if stuck."
        )
        logger.info(
            "[watchdog.agent] long-running tool agent_id=%s inflight=%ss pid=%s",
            self.agent_id,
            inflight_secs,
            self.pid,
        )
        self.long_tool_reported = True

    def _report_stall(self, now: float) -> None:
        idle_secs = int(now - self.last_activity_at)
        _stdout_event(
            f"[watchdog.stall] {self.agent_id}: STALLED — no JSONL activity for {idle_secs}s "
            f"(PID {self.pid} alive, no in-flight tool call). Agent may be stuck — "
            f"check, or kill+resume."
        )
        _stderr(
            f"[watchdog.agent] {self.agent_id}: STALLED — no JSONL activity for {idle_secs}s "
            f"(PID {self.pid} still alive)"
        )
        logger.info(
            "[watchdog.agent] stall detected agent_id=%s idle=%ss pid=%s",
            self.agent_id,
            idle_secs,
            self.pid,
        )
        self.stall_reported = True


def watch_agent(
    agent_id: str,
    timeout_seconds: int = 600,
    poll_interval: float = 5.0,
) -> dict:
    """Block until the dispatched agent at `agent_id` exits.

    Returns woke, reason, elapsed, agent_state, exit_code, agent_id and handle.
    agent_state is one of: "completed_replied", "completed_silent", "crashed", "timeout".
    """
    started_at = time.monotonic()
    _stderr(f"[watchdog.agent] watching {agent_id} (timeout={timeout_seconds}s)")
    logger.info("[watchdog.agent] start agent_id=%s timeout=%s", agent_id, timeout_seconds)

    handle = _registry.register(
        "agent",
        metadata={"agent_id": agent_id, "timeout_seconds": timeout_seconds},
    )

    try:
        try:
            branch_path = _resolve_branch_path(agent_id)
        except RegistryUnreadable as exc:
            _stderr(f"[watchdog.agent] {agent_id}: main registry unreadable — refusing to resolve: {exc}")
            return {
                "woke": False,
                "reason": f"main registry unreadable: {exc}",
                "elapsed": int(time.monotonic() - started_at),
                "agent_state": "timeout",
                "exit_code": None,
                "agent_id": agent_id,
                "handle": handle,
            }
        if branch_path is None:
            elapsed = int(time.monotonic() - started_at)
            _stderr(f"[watchdog.agent] {agent_id}: branch not found in registry")
            return {
                "woke": False,
                "reason": "agent not found",
                "elapsed": elapsed,
                "agent_state": "timeout",
                "exit_code": None,
                "agent_id": agent_id,
                "handle": handle,
            }

        lock_file = branch_path / ".ai_mail.local" / ".dispatch.lock"
        initial_lock = _read_lock(lock_file)
        initial_pid = initial_lock.get("pid") if initial_lock else None
        dispatch_ts = initial_lock.get("timestamp") if initial_lock else None
        lock_existed_initially = initial_lock is not None

        if not lock_existed_initially:
            _stderr(f"[watchdog.agent] {agent_id}: no active lock — agent already idle")
            elapsed = int(time.monotonic() - started_at)
            state, reason, exit_code = _classify_exit(branch_path, lock_existed=False, dispatch_ts=dispatch_ts)
            return {
                "woke": True,
                "reason": f"no active dispatch ({reason})",
                "elapsed": elapsed,
                "agent_state": state,
                "exit_code": exit_code,
                "agent_id": agent_id,
                "handle": handle,
            }

        _stderr(f"[watchdog.agent] {agent_id}: lock present, monitor PID={initial_pid}")

        jsonl_dir = _get_jsonl_projects_dir(branch_path)
        tracker = StallTracker(agent_id, jsonl_dir, time.monotonic(), initial_pid, branch_path=branch_path)

        while True:
            elapsed = time.monotonic() - started_at
            if elapsed >= timeout_seconds:
                _stderr(f"[watchdog.agent] {agent_id}: TIMEOUT after {int(elapsed)}s")
                logger.info("[watchdog.agent] timeout agent_id=%s elapsed=%s", agent_id, int(elapsed))
                return {
                    "woke": False,
                    "reason": f"timeout after {int(elapsed)}s",
                    "elapsed": int(elapsed),
                    "agent_state": "timeout",
                    "exit_code": None,
                    "agent_id": agent_id,
                    "handle": handle,
                }

            if not lock_file.exists():
                _stderr(f"[watchdog.agent] {agent_id}: lock removed — agent done")
                elapsed_int = int(time.monotonic() - started_at)
                state, reason, exit_code = _classify_exit(branch_path, lock_existed=True, dispatch_ts=dispatch_ts)
                logger.info("[watchdog.agent] wake agent_id=%s state=%s elapsed=%s", agent_id, state, elapsed_int)
                result = {
                    "woke": True,
                    "reason": reason,
                    "elapsed": elapsed_int,
                    "agent_state": state,
                    "exit_code": exit_code,
                    "agent_id": agent_id,
                    "handle": handle,
                }
                json_handler.log_operation("watch_agent", {"agent_id": agent_id, "state": result.get("agent_state")})
                return result

            if isinstance(initial_pid, int) and not _pid_alive(initial_pid):
                _stderr(
                    f"[watchdog.agent] {agent_id}: monitor PID {initial_pid} dead "
                    f"but lock still present — treating as crash"
                )
                elapsed_int = int(time.monotonic() - started_at)
                state, reason, exit_code = _classify_exit(branch_path, lock_existed=True, dispatch_ts=dispatch_ts)
                if state.startswith("completed"):
                    state = "crashed"
                    reason = f"monitor PID {initial_pid} dead, lock still present"
                logger.info("[watchdog.agent] wake agent_id=%s state=%s elapsed=%s", agent_id, state, elapsed_int)
                return {
                    "woke": True,
                    "reason": reason,
                    "elapsed": elapsed_int,
                    "agent_state": state,
                    "exit_code": exit_code,
                    "agent_id": agent_id,
                    "handle": handle,
                }

            tracker.observe(time.monotonic())

            time.sleep(poll_interval)
    finally:
        _registry.deregister(handle)
