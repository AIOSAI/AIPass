# =================== AIPass ====================
# Name: cadence.py
# Version: 2.3.0
# Description: Per-session turn counter for prompt injection cadence (DPLAN-0200)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-06-08
# Modified: 2026-09-10
# =============================================

"""Turn counter for prompt injection cadence — fires loaders every Nth turn.

Multi-process safe: each UserPromptSubmit hook runs as a separate OS process.
Uses fcntl.flock + mtime debounce + per-turn token to ensure the counter
advances exactly once per real user turn.
"""

import json
import os
import tempfile
import time
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.hooks.apps.handlers.module_root import module_file

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("[HOOKS] cadence: fcntl unavailable (Windows)")

CONSOLE = err_console

_GUARD_DIR = Path(tempfile.gettempdir())
_BRANCH_ROOT = module_file(__file__).parent.parent.parent
_CONFIG_PATH = _BRANCH_ROOT / "hooks_json" / "custom_config" / "cadence_config.json"
_DEBOUNCE_S = 2.0

HELP_COMMANDS = [
    ("cadence", "Show prompt injection cadence config and state"),
]

DEFAULTS = {
    "enabled": True,
    "period": 5,
    "loaders": {
        "tier0": {"period": 5, "offset": 0},
        "navmap": {"period": 5, "offset": 0},
        "branch": {"offset": 0},
        "email": {"period": 5},
    },
}

MAIL_LOADER = "email"

_turn: int | None = None
_config: dict | None = None


def _deep_merge(base: dict, updates: dict) -> dict:
    """Deep merge updates into base (modifies base in-place)."""
    for key, value in updates.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_config() -> dict:
    global _config
    if _config is not None:
        return _config

    import copy

    result = copy.deepcopy(DEFAULTS)

    if _CONFIG_PATH.is_file():
        try:
            overrides = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            _deep_merge(result, overrides)
        except (json.JSONDecodeError, OSError) as exc:
            logger.info("[HOOKS] cadence: config load failed, using defaults: %s", exc)

    _config = result
    return result


def _state_path() -> Path | None:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-cadence-{session_id}.json"


def _get_turn_token(hook_data: dict) -> int:
    """Per-turn token from transcript_path size (monotonic, identical across siblings)."""
    tp = hook_data.get("transcript_path", "")
    if not tp:
        return 0
    try:
        return os.path.getsize(tp)
    except OSError as exc:
        logger.info("[HOOKS] cadence: transcript stat failed: %s", exc)
        return 0


def _lock(fd) -> None:
    """Acquire exclusive lock (no-op on Windows)."""
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd) -> None:
    """Release exclusive lock (no-op on Windows)."""
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _close_fd(fd) -> None:
    """Unlock and close a file descriptor safely."""
    try:
        _unlock(fd)
        fd.close()
    except OSError as exc:
        logger.info("[HOOKS] cadence: fd cleanup failed: %s", exc)


def _mtime_age(fd) -> float:
    """Seconds since file was last modified, via the open fd."""
    try:
        return time.time() - os.fstat(fd.fileno()).st_mtime
    except OSError as exc:
        logger.info("[HOOKS] cadence: fstat failed, assuming stale: %s", exc)
        return _DEBOUNCE_S + 1


def _should_increment(stored_turn: int, stored_token: int, token: int, fd) -> bool:
    """Decide whether to increment the counter. Extracted for nesting depth."""
    if stored_turn < 0:
        return True
    if _mtime_age(fd) < _DEBOUNCE_S:
        return False
    if token == stored_token and token != 0:
        return False
    return True


def _load_and_increment(hook_data: dict) -> int:
    """Load turn counter, increment exactly once per real turn. Multi-process safe."""
    global _turn
    if _turn is not None:
        return _turn

    path = _state_path()
    if path is None:
        _turn = 0
        return 0

    token = _get_turn_token(hook_data)
    fd = None

    try:
        fd = open(path, "a+", encoding="utf-8")  # noqa: SIM115
        _lock(fd)
        fd.seek(0)
        content = fd.read()

        data = json.loads(content) if content.strip() else {}
        stored_turn = data.get("turn", -1)
        stored_token = data.get("token", -1)

        if _should_increment(stored_turn, stored_token, token, fd):
            new_turn = max(stored_turn + 1, 0)
            fd.seek(0)
            fd.truncate()
            fd.write(json.dumps({"turn": new_turn, "token": token}))
            fd.flush()
        else:
            new_turn = stored_turn

        _close_fd(fd)
        fd = None
        _turn = new_turn
        return new_turn

    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] cadence: state access failed: %s", exc)
        if fd is not None:
            _close_fd(fd)
        _turn = 0
        return 0


def should_fire(loader_name: str, hook_data: dict | None = None) -> bool:
    """Check if a loader should fire this turn. Always True on turn 0 or if cadence disabled."""
    config = _load_config()

    if not config.get("enabled", True):
        return True

    global_period = config.get("period", 5)

    loader_config = config.get("loaders", {}).get(loader_name, {})
    period = loader_config.get("period", global_period)
    offset = loader_config.get("offset", 0)

    if period <= 0:
        return True

    turn = _load_and_increment(hook_data or {})

    fired = turn == 0 or (turn % period) == offset

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    session_short = session_id[:8] if session_id else "none"
    action = "fired" if fired else "skipped"
    logger.info(
        "[HOOKS] cadence %s loader=%s turn=%d period=%d offset=%d session=%s",
        action,
        loader_name,
        turn,
        period,
        offset,
        session_short,
    )

    return fired


def _mail_state_path() -> Path | None:
    """Per-session state for the mail notification loop.

    Deliberately a separate file from the turn counter: _load_and_increment()
    truncates its state to {turn, token} every turn, and that truncation is
    load-bearing — it is what disarms the post-compact regroup token once a real
    UserPromptSubmit arrives. Storing mail state there would either be wiped
    every turn or force that wipe to stop, changing regroup semantics.
    """
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-mailcadence-{session_id}.json"


def _read_last_mail_turn(path: Path) -> int | None:
    """Last turn the mail banner fired this session, or None if never/unreadable."""
    if not path.exists():
        return None  # never fired this session — the normal first-sighting path

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.info("[HOOKS] cadence: mail state read failed, treating as never fired: %s", exc)
        return None
    try:
        value = json.loads(content).get("last_fired_turn") if content.strip() else None
    except json.JSONDecodeError as exc:
        logger.info("[HOOKS] cadence: mail state unreadable, treating as never fired: %s", exc)
        return None
    return value if isinstance(value, int) else None


def _write_last_mail_turn(path: Path, turn: int | None) -> None:
    """Record (or clear) the last turn the mail banner fired."""
    try:
        if turn is None:
            path.write_text(json.dumps({}), encoding="utf-8")
        else:
            path.write_text(json.dumps({"last_fired_turn": turn}), encoding="utf-8")
    except OSError as exc:
        logger.info("[HOOKS] cadence: mail state write failed: %s", exc)


def should_fire_mail(new_count: int, hook_data: dict | None = None) -> bool:
    """Mail banner cadence: announce on arrival, then at most once every Nth turn.

    Zero new mail is fully silent AND clears the state, so the next arrival
    announces on the turn it lands rather than waiting out the rest of a period.
    A banner that shows up four turns after the mail did is not a notification.

    Cadence disabled, or period <= 0, restores the previous fire-every-turn
    behaviour — same convention as should_fire() returning True when disabled.
    """
    config = _load_config()
    if new_count <= 0:
        path = _mail_state_path()
        if path is not None and path.exists():
            _write_last_mail_turn(path, None)
        return False

    if not config.get("enabled", True):
        return True

    loader_config = config.get("loaders", {}).get(MAIL_LOADER, {})
    period = loader_config.get("period", config.get("period", 5))
    if period <= 0:
        return True

    path = _mail_state_path()
    if path is None:
        return True

    turn = _load_and_increment(hook_data or {})
    last_fired = _read_last_mail_turn(path)

    # turn < last_fired means the counter was reset under us (compact / new session);
    # the banner belongs to the old numbering, so re-announce rather than stay silent.
    fired = last_fired is None or turn < last_fired or (turn - last_fired) >= period
    if fired:
        _write_last_mail_turn(path, turn)

    logger.info(
        "[HOOKS] cadence mail %s count=%d turn=%d last_fired=%s period=%d",
        "fired" if fired else "skipped",
        new_count,
        turn,
        last_fired,
        period,
    )
    return fired


_REGROUP_DEBOUNCE_S = 30.0


ADVISORY_PERIOD = 10
# Used only when the turn cannot be read (no session id). Ten turns is roughly
# this long in practice, and a throttle that silently degrades to "every time"
# is the bug being fixed, not a fallback.
ADVISORY_SECONDS = 600


def current_turn() -> int | None:
    """The turn counter WITHOUT advancing it, or None when it cannot be read.

    A PreToolUse consumer must never call _load_and_increment: several tool
    calls share one turn, and the token guard that makes incrementing safe
    keys off UserPromptSubmit's transcript growth. Reading is always safe.
    """
    path = _state_path()
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] cadence: turn unreadable: %s", exc)
        return None
    turn = data.get("turn")
    return turn if isinstance(turn, int) else None


def _advisory_state_path(name: str) -> Path | None:
    """Per-session, per-advisory throttle state.

    Separate from the turn counter for the same reason mail state is:
    _load_and_increment truncates its file to {turn, token} every turn.
    """
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-advisory-{name}-{session_id}.json"


def should_fire_advisory(name: str, period: int = ADVISORY_PERIOD) -> bool:
    """True at most once per *period* turns for the named advisory.

    For standing conditions — states that stay true for days and re-assert on
    every qualifying edit. @devpulse's seat sat over the todos cap long enough
    to write 209 identical lines and trip repeat-signature escalation; the
    advisory was right and the cadence was the noise (Patrick, 2026-08-19).

    Fires when it has never fired, when the period has elapsed, and when the
    turn counter went BACKWARDS — a reset means compact or a new session, and
    the old numbering must not buy silence in the new one. Falls back to
    elapsed seconds when the turn cannot be read, so an unreadable counter
    still throttles rather than restoring fire-every-time.
    """
    path = _advisory_state_path(name)
    if path is None:
        return True

    turn = current_turn()
    now = time.time()
    last_turn, last_at = None, None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            last_turn = data.get("turn") if isinstance(data.get("turn"), int) else None
            last_at = data.get("at") if isinstance(data.get("at"), (int, float)) else None
        except (OSError, json.JSONDecodeError) as exc:
            logger.info("[HOOKS] cadence: advisory state unreadable, treating as never fired: %s", exc)

    if last_at is None and last_turn is None:
        fire = True
    elif turn is not None and last_turn is not None:
        fire = turn < last_turn or (turn - last_turn) >= period
    else:
        fire = last_at is None or (now - last_at) >= ADVISORY_SECONDS

    if fire:
        try:
            path.write_text(json.dumps({"turn": turn, "at": now}), encoding="utf-8")
        except OSError as exc:
            # Fire anyway — losing the advisory is worse than repeating it.
            logger.info("[HOOKS] cadence: advisory state write failed: %s", exc)
    return fire


def reset_counter(hook_data: dict | None = None, caller: str = "unknown") -> None:
    """Reset counter to -1 so next turn reads 0 (all loaders fire). Called from PreCompact.

    Also arms a one-shot regroup token for the PostToolUse re-ground backstop
    (DPLAN-0276). A duplicate reset within _REGROUP_DEBOUNCE_S of the last arm
    (e.g. two callers reacting to the same compact boundary, DPLAN-0278) reuses
    the existing token instead of minting a new one — hard-caps the backstop to
    at most one fire per compact regardless of how many callers reset here.
    """
    path = _state_path()
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    if path is None and hook_data:
        fallback_id = hook_data.get("session_id", "")
        if fallback_id:
            path = _GUARD_DIR / f"aipass-cadence-{fallback_id}.json"
            session_id = fallback_id

    session_short = session_id[:8] if session_id else "none"
    pid = os.getpid()

    if path is None:
        logger.info(
            "[HOOKS] cadence: reset_counter SKIPPED caller=%s pid=%d — no session ID (env var not set)",
            caller,
            pid,
        )
        return

    fd = None
    try:
        fd = open(path, "a+", encoding="utf-8")  # noqa: SIM115
        _lock(fd)
        fd.seek(0)
        content = fd.read()
        data: dict = {}
        if content.strip():
            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                logger.info("[HOOKS] cadence: reset read old state failed: %s", exc)
        old_turn = data.get("turn", -1)
        prior_armed_at = data.get("regroup_armed_at")
        now = time.time()
        elapsed = now - prior_armed_at if isinstance(prior_armed_at, (int, float)) else None

        debounced = elapsed is not None and elapsed < _REGROUP_DEBOUNCE_S
        if debounced:
            token = data.get("regroup_token")
            armed_at = prior_armed_at
        else:
            token = f"{int(now * 1000)}-{pid}"
            armed_at = now

        state = {"turn": -1, "token": -1, "regroup_token": token, "regroup_armed_at": armed_at}
        if debounced:
            # A duplicate reset on the SAME compact boundary must not cancel the
            # re-ground parts still queued for it (issue #752); a new compaction
            # (not debounced) starts over and rightly drops them.
            for key in ("regroup_next", "regroup_total"):
                if key in data:
                    state[key] = data[key]
        fd.seek(0)
        fd.truncate()
        fd.write(json.dumps(state))
        fd.flush()
        _close_fd(fd)
        fd = None

        if debounced:
            logger.info(
                "[HOOKS] cadence: regroup rearm debounced caller=%s pid=%d session=%s (%.1fs since last arm)",
                caller,
                pid,
                session_short,
                elapsed or 0.0,
            )
        else:
            logger.info(
                "[HOOKS] cadence: counter reset for post-compact re-injection caller=%s pid=%d token=%s "
                "session=%s prev_turn=%d",
                caller,
                pid,
                token,
                session_short,
                old_turn,
            )
    except OSError as exc:
        logger.info(
            "[HOOKS] cadence: reset write FAILED caller=%s pid=%d session=%s: %s", caller, pid, session_short, exc
        )
        if fd is not None:
            _close_fd(fd)


def consume_regroup_pending(hook_data: dict | None = None) -> bool:
    """Atomically check-and-clear the post-compact regrounding token.

    Set by reset_counter() on every PreCompact (armed once per compact — see
    the debounce there). Returns True at most once per compact — the caller
    (a PostToolUse backstop, DPLAN-0276) fires grounding content directly
    since PostToolUse's additionalContext reaches Claude even when no
    UserPromptSubmit arrives to let cadence's normal turn-0 path fire.
    """
    path = _state_path()
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    if path is None and hook_data:
        fallback_id = hook_data.get("session_id", "")
        if fallback_id:
            path = _GUARD_DIR / f"aipass-cadence-{fallback_id}.json"
            session_id = fallback_id

    session_short = session_id[:8] if session_id else "none"
    pid = os.getpid()

    if path is None or not path.exists():
        return False

    fd = None
    try:
        fd = open(path, "a+", encoding="utf-8")  # noqa: SIM115
        _lock(fd)
        fd.seek(0)
        content = fd.read()
        data = json.loads(content) if content.strip() else {}
        token = data.get("regroup_token")
        pending = bool(token)

        if pending:
            data["regroup_token"] = None
            fd.seek(0)
            fd.truncate()
            fd.write(json.dumps(data))
            fd.flush()

        _close_fd(fd)
        fd = None

        if pending:
            logger.info(
                "[HOOKS] cadence: regroup_pending consumed (mid-turn backstop) pid=%d token=%s session=%s",
                pid,
                token,
                session_short,
            )
        return pending

    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] cadence: consume_regroup_pending failed session=%s: %s", session_short, exc)
        if fd is not None:
            _close_fd(fd)
        return False


def _regroup_state_path(hook_data: dict | None) -> tuple[Path | None, str]:
    """The cadence state file and a short session tag, same resolution as consume."""
    path = _state_path()
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if path is None and hook_data:
        fallback_id = hook_data.get("session_id", "")
        if fallback_id:
            path = _GUARD_DIR / f"aipass-cadence-{fallback_id}.json"
            session_id = fallback_id
    return path, (session_id[:8] if session_id else "none")


def queue_regroup_parts(total: int, hook_data: dict | None = None) -> None:
    """Record that this compaction's re-ground was split into *total* parts, part 1 fired.

    Issue #752: one PostToolUse additionalContext over Claude Code's 10,000-char
    hook-output limit is persisted to a file and the agent sees a 2,000-char
    preview, so the backstop now spreads the re-ground over consecutive tool
    calls. The queue lives in the SAME state file as the regroup token, on
    purpose. A real UserPromptSubmit truncates that file to {turn, token}
    (_load_and_increment), and that is exactly when the remaining parts must
    stop: the cadence turn-0 path then fires every loader as its own injection.
    A new compaction's reset_counter() rewrites the file as well, so a queue
    left over from one compaction can never leak into the next.
    """
    if total < 2:
        return
    path, session_short = _regroup_state_path(hook_data)
    if path is None:
        return
    fd = None
    try:
        fd = open(path, "a+", encoding="utf-8")  # noqa: SIM115
        _lock(fd)
        fd.seek(0)
        content = fd.read()
        data = json.loads(content) if content.strip() else {}
        data["regroup_next"] = 2
        data["regroup_total"] = total
        fd.seek(0)
        fd.truncate()
        fd.write(json.dumps(data))
        fd.flush()
        _close_fd(fd)
        fd = None
        logger.info("[HOOKS] cadence: regroup queued %d more part(s) session=%s", total - 1, session_short)
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] cadence: queue_regroup_parts failed session=%s: %s", session_short, exc)
        if fd is not None:
            _close_fd(fd)


def pop_regroup_part(hook_data: dict | None = None) -> tuple[int, int] | None:
    """Atomically take the next queued re-ground part as (index, total), or None.

    Each index is handed out exactly once — read, advance and write happen under
    one flock — and the keys are removed with the last part, so the sequence
    ends silent however many tool calls follow. That keeps DPLAN-0276's cure:
    one re-ground per compaction, now delivered as at most *total* fires.
    """
    path, session_short = _regroup_state_path(hook_data)
    if path is None or not path.exists():
        return None
    fd = None
    try:
        fd = open(path, "a+", encoding="utf-8")  # noqa: SIM115
        _lock(fd)
        fd.seek(0)
        content = fd.read()
        data = json.loads(content) if content.strip() else {}
        index, total = data.get("regroup_next"), data.get("regroup_total")
        part = None
        if isinstance(index, int) and isinstance(total, int) and index <= total:
            part = (index, total)
            if index >= total:
                data.pop("regroup_next", None)
                data.pop("regroup_total", None)
            else:
                data["regroup_next"] = index + 1
            fd.seek(0)
            fd.truncate()
            fd.write(json.dumps(data))
            fd.flush()
        _close_fd(fd)
        fd = None
        return part
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] cadence: pop_regroup_part failed session=%s: %s", session_short, exc)
        if fd is not None:
            _close_fd(fd)
        return None


def log_regroup_fire(loaders: str, part: int, total: int, text: str, budget: int, hook_data=None) -> None:
    """One cadence.log line per re-ground fire, sized, so an over-budget fire is one grep.

    ``bytes`` is the UTF-8 size (what ``wc -c`` shows on a persisted file);
    ``chars`` is the UTF-16 length Claude Code compares against its limit.
    """
    _, session_short = _regroup_state_path(hook_data)
    chars = len(text.encode("utf-16-le")) // 2
    over = chars > budget
    (logger.warning if over else logger.info)(
        "[HOOKS] regroup fired loader=%s part=%d/%d bytes=%d chars=%d budget=%d%s session=%s",
        loaders,
        part,
        total,
        len(text.encode("utf-8")),
        chars,
        budget,
        " OVER-BUDGET" if over else "",
        session_short,
    )


# =============================================================================
# MODULE INTERFACE (drone @hooks routing)
# =============================================================================


def print_introspection() -> None:
    """Print cadence config and current state."""
    config = _load_config()
    CONSOLE.print("[bold cyan]cadence[/bold cyan] Module")
    CONSOLE.print(f"  Enabled: {config.get('enabled', True)}")
    global_period = config.get("period", 5)
    CONSOLE.print(f"  Period: {global_period} turns (global default)")
    loaders = config.get("loaders", {})
    for name, lcfg in loaders.items():
        lp = lcfg.get("period", global_period)
        if name == MAIL_LOADER:
            # No offset: the mail banner is an elapsed-turns loop off its own last
            # fire, not a modulo slot, so it can announce the turn mail arrives.
            CONSOLE.print(f"  Loader '{name}': period={lp} (elapsed-turns loop, announces on arrival)")
        else:
            CONSOLE.print(f"  Loader '{name}': period={lp} offset={lcfg.get('offset', 0)}")
    path = _state_path()
    if path and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            CONSOLE.print(f"  Current turn: {data.get('turn', '?')}")
        except (json.JSONDecodeError, OSError) as exc:
            logger.info("[HOOKS] cadence: state read for introspection failed: %s", exc)
            CONSOLE.print("  Current turn: (unreadable)")
    else:
        CONSOLE.print("  Current turn: (no state file)")
    CONSOLE.print(f"  Config file: {_CONFIG_PATH}")


def handle_command(command: str, args: list) -> bool:
    """Route cadence commands from drone @hooks."""
    if command in ("--help", "-h", "help"):
        CONSOLE.print("[bold cyan]cadence[/bold cyan] — Prompt injection cadence control")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks cadence    Show cadence config and current turn state")
        return True

    if command == "cadence":
        if not args:
            print_introspection()
            return True
    return False
