# =================== AIPass ====================
# Name: agent.py
# Description: Watchdog Agent Handler — block until dispatched agent exits
# Version: 1.2.1
# Created: 2026-04-14
# Modified: 2026-08-08
# =============================================

# Signal choice: ai_mail dispatch lock file polling.
#
# When ai_mail dispatches an agent, dispatch_monitor.py creates
# branch_path/.ai_mail.local/.dispatch.lock containing the monitor PID,
# and ALWAYS deletes it on exit (success OR crash). So the lock
# file's existence is the agent's liveness signal — OS-level, crash-aware,
# template-independent. We poll for: (a) lock file gone, OR (b) monitor
# PID dead. Crash vs success is distinguished by the presence of
# .ai_mail.local/last_bounce.json which the monitor writes on failure.

"""
Watchdog Agent Handler — block until a dispatched agent process exits.

The whole point: this function returns ONLY when the dispatched agent
has finished, however it finished. The exit is the wake signal — when
this function returns from a `run_in_background: true` invocation,
devpulse wakes.
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


def _stderr(msg: str) -> None:
    """Write to stderr — visible in debug runs, doesn't pollute stdout capture."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _stdout_event(msg: str) -> None:
    """Write one flushed event line to stdout so a Monitor-tool wrapper turns it
    into a live notification to devpulse.

    The Monitor tool treats each stdout line as an event but only captures stderr
    to a file (never surfaced). So mid-watch signals a caller must ACT on — a stall
    or a possibly-hung tool — go here, while the verbose debug trail stays on
    _stderr + logger. (#634 part 2.)
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


def _search_registry(registry_file: Path, target_email: str) -> Path | None:
    """Search a single registry file for a branch matching target_email."""
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[watchdog.agent] failed to read registry %s: %s", registry_file, exc)
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
    """Resolve an `@branch` token (or bare name) to its absolute branch path.

    Checks the AIPass registry first, then scans external project registries
    found via AIPASS_CALLER_CWD or known project paths.
    """
    target = f"@{agent_id.lstrip('@').lower()}"

    repo_root = _find_repo_root()
    if repo_root is not None:
        registry_file = repo_root / "AIPASS_REGISTRY.json"
        result = _search_registry(registry_file, target)
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
            resolved = reg.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            result = _search_registry(reg, target)
            if result is not None:
                return result
    return None


def _is_zombie_linux(pid: int) -> bool:
    """Linux-only zombie check via /proc. Returns True if zombie."""
    try:
        status_text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("[watchdog.agent] /proc/%s/status unreadable: %s", pid, exc)
        return False
    for line in status_text.splitlines():
        if line.startswith("State:"):
            return "Z" in line
    return False


def _pid_alive_windows(pid: int) -> bool:
    """Windows-safe liveness check via OpenProcess + GetExitCodeProcess."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]  # Windows-only
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    """Return True if the process is alive (not zombie)."""
    if sys.platform == "win32":
        try:
            return _pid_alive_windows(pid)
        except Exception as exc:
            logger.info("[watchdog.agent] PID %s Windows check failed (assuming alive): %s", pid, exc)
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError as exc:
        logger.info("[watchdog.agent] PID %s not found: %s", pid, exc)
        return False
    except PermissionError as exc:
        logger.info("[watchdog.agent] PID %s permission denied (alive): %s", pid, exc)
        return True
    except OSError as exc:
        logger.info("[watchdog.agent] PID %s os.kill error (assuming dead): %s", pid, exc)
        return False
    if sys.platform == "linux" and _is_zombie_linux(pid):
        return False
    return True


def _get_jsonl_projects_dir(branch_path: Path) -> Path:
    """Get Claude's JSONL projects directory for a branch path."""
    cwd = str(branch_path)
    encoded = cwd.replace("\\", "-").replace("/", "-").replace(":", "-").replace("_", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / encoded


def _snapshot_jsonl_sizes(projects_dir: Path) -> dict:
    """Snapshot current sizes of all JSONL files, recursively.

    Recursive because sub-agent transcripts live under ``<session>/subagents/``,
    not at the top level: a parent waiting on a synchronous sub-agent writes no
    JSONL of its own while the sub-agent's file grows, so a top-level-only scan
    misreads that whole span as idle and false-fires STALLED (seen live
    2026-08-08 on @trigger's digest build). Keys are paths relative to
    ``projects_dir`` so equal basenames in different session dirs can't collide.
    """
    sizes = {}
    if not projects_dir.exists():
        return sizes
    try:
        for f in projects_dir.rglob("*.jsonl"):
            try:
                sizes[str(f.relative_to(projects_dir))] = f.stat().st_size
            except OSError as exc:
                logger.info("[watchdog.agent] jsonl snapshot stat failed for %s: %s", f.name, exc)
    except OSError as exc:
        logger.info("[watchdog.agent] jsonl snapshot glob failed: %s", exc)
    return sizes


def _has_jsonl_activity(projects_dir: Path, baseline: dict) -> bool:
    """Return True if any JSONL file grew or a new file appeared since baseline.

    Recursive, keyed by relative path — see ``_snapshot_jsonl_sizes``.
    """
    if not projects_dir.exists():
        return False
    try:
        files = list(projects_dir.rglob("*.jsonl"))
    except OSError as exc:
        logger.info("[watchdog.agent] jsonl activity glob failed: %s", exc)
        return False
    for f in files:
        try:
            current_size = f.stat().st_size
        except OSError as exc:
            logger.info("[watchdog.agent] jsonl activity stat failed for %s: %s", f.name, exc)
            continue
        key = str(f.relative_to(projects_dir))
        if key not in baseline:
            return current_size > 0
        if current_size > baseline[key]:
            return True
    return False


def _newest_jsonl(projects_dir: Path) -> Path | None:
    """Return the most-recently-modified .jsonl under projects_dir (recursive), or None."""
    if not projects_dir.exists():
        return None
    try:
        files = list(projects_dir.rglob("*.jsonl"))
    except OSError as exc:
        logger.info("[watchdog.agent] newest jsonl glob failed: %s", exc)
        return None
    newest: Path | None = None
    newest_mtime = -1.0
    for f in files:
        try:
            mtime = f.stat().st_mtime
        except OSError as exc:
            logger.info("[watchdog.agent] newest jsonl stat failed for %s: %s", f.name, exc)
            continue
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest = f
    return newest


def _tail_lines(path: Path, max_bytes: int = 1_000_000) -> list[str]:
    """Non-blank newline-delimited lines from a bounded tail read of ``path``.
    Reads at most ``max_bytes`` from the end so a multi-MB transcript stays
    cheap; a line truncated by the bound decodes partially and simply fails to
    parse downstream (→ skipped)."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            chunk = fh.read()
    except OSError as exc:
        logger.info("[watchdog.agent] tail read failed for %s: %s", path.name, exc)
        return []
    if not chunk:
        return []
    text = chunk.decode("utf-8", errors="replace")
    return [ln for ln in text.splitlines() if ln.strip()]


# Backwards-walk bound for the in-flight scan: bookkeeping lines between the
# real message entries are few, so the last message entry sits well inside this.
_INFLIGHT_SCAN_LIMIT = 25


def _last_entry_is_inflight_tool(projects_dir: Path) -> bool:
    """True if the newest JSONL's last MESSAGE event is an assistant message
    dispatching a tool call — an in-flight ``tool_use`` awaiting its result.

    While a tool runs (a big Read, a long Bash, a synchronous sub-agent) the
    agent writes NO new JSONL lines, so size-growth alone misreads that span as
    idle and false-fires STALLED (#634 part 1). The last message entry being an
    assistant ``tool_use`` is the precise signal that the agent is actively
    working, not stuck.

    Transcripts interleave bookkeeping lines (``type: last-prompt``, summaries)
    with message entries, and bookkeeping can land AFTER the assistant's
    ``tool_use`` line — seen live 2026-08-08: a parent mid-Task-call had
    ``last-prompt`` as its literal last line, masking the in-flight signal. So
    walk backwards past roleless lines to the last entry carrying a role:
    assistant + ``tool_use`` → in-flight; any other message (text-only turn, a
    returned ``tool_result``) → not.

    Best-effort: any read/parse/shape surprise degrades to False so the stall
    detector never crashes on a format drift.
    """
    newest = _newest_jsonl(projects_dir)
    if newest is None:
        return False
    lines = _tail_lines(newest)
    for line in reversed(lines[-_INFLIGHT_SCAN_LIMIT:]):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            # torn partial write or format drift — keep walking
            logger.info("[watchdog.agent] skipping unparseable transcript line in %s: %s", newest.name, exc)
            continue
        if not isinstance(entry, dict):
            continue
        # Schemas vary: role/content may sit under "message" or at the top level.
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


def _read_lock(lock_file: Path) -> dict | None:
    """Read lock file, return dict or None on miss/error."""
    if not lock_file.exists():
        return None
    try:
        return json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[watchdog.agent] could not read lock %s: %s", lock_file, exc)
        return None


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

    Returns (agent_state, reason, exit_code).
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

    Liveness signal = new JSONL lines (size growth) OR an in-flight tool call. A
    long single tool call (big Read, long Bash, heavy compute) writes no new JSONL
    lines while it runs but leaves an assistant ``tool_use`` as the last entry, so
    it counts as activity instead of false-firing STALLED (#634 part 1).

    Actionable signals — stall, long-running tool, resumed — go to stdout via
    ``_stdout_event`` so a Monitor-tool wrapper surfaces them to devpulse live
    (#634 part 2). The verbose trail stays on ``_stderr`` + logger.
    """

    # Quiet spans with zero JSONL output are routine, not stalls: a model composing
    # a long response writes nothing until the turn completes, and compaction is one
    # multi-minute silent API call. 120s false-fired on every stall of S329 (8/8);
    # 300s clears normal turns and most compactions while a wedged agent still
    # surfaces well inside a long watch.
    STALL_THRESHOLD = 300.0
    # A single tool call held in-flight this long is surfaced as a soft advisory
    # (heavy op or a hung tool). Below the 600s default timeout so long watches
    # get a mid-flight heads-up instead of waiting on the timeout.
    LONG_TOOL_THRESHOLD = 300.0

    def __init__(self, agent_id: str, jsonl_dir: Path, baseline: dict, now: float, pid: object) -> None:
        self.agent_id = agent_id
        self.jsonl_dir = jsonl_dir
        self.baseline = baseline
        self.pid = pid
        self.last_activity_at = now
        self.in_flight_since: float | None = None
        self.stall_reported = False
        self.long_tool_reported = False

    def observe(self, now: float) -> None:
        """Evaluate one poll tick: reset on activity, else report a stall past threshold."""
        size_grew = _has_jsonl_activity(self.jsonl_dir, self.baseline)
        inflight = False if size_grew else _last_entry_is_inflight_tool(self.jsonl_dir)
        if size_grew or inflight:
            self._mark_active(now, size_grew, inflight)
        elif not self.stall_reported and (now - self.last_activity_at) >= self.STALL_THRESHOLD:
            self._report_stall(now)

    def _mark_active(self, now: float, size_grew: bool, inflight: bool) -> None:
        if size_grew:
            self.baseline = _snapshot_jsonl_sizes(self.jsonl_dir)
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

    Args:
        agent_id: Branch token like ``@drone`` (or bare ``drone``).
        timeout_seconds: Maximum wait. Default 10 min — catches crashes + silent-finishes
            fast; long agent watches should pass an explicit ``--timeout``.
        poll_interval: Seconds between checks. Default 5.0 — the per-tick work (lock
            stat, PID liveness, one-dir JSONL size scan) is cheap, so a tight cadence
            just burns CPU. 5s keeps completion latency invisible on multi-minute
            dispatches while the 300s stall threshold has ample resolution.

    Returns:
        dict with keys: woke, reason, elapsed, agent_state, exit_code, agent_id.
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
        branch_path = _resolve_branch_path(agent_id)
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
        tracker = StallTracker(agent_id, jsonl_dir, _snapshot_jsonl_sizes(jsonl_dir), time.monotonic(), initial_pid)

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
