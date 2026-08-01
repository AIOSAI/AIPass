# =================== AIPass ====================
# Name: cadence.py
# Version: 2.0.0
# Description: Per-session turn counter for prompt injection cadence (DPLAN-0200)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-06-08
# Modified: 2026-06-08
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

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("[HOOKS] cadence: fcntl unavailable (Windows)")

CONSOLE = err_console

_GUARD_DIR = Path(tempfile.gettempdir())
_BRANCH_ROOT = Path(__file__).resolve().parent.parent.parent
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
    },
}

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
        fd = open(path, "a+")  # noqa: SIM115
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


_REGROUP_DEBOUNCE_S = 30.0


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
        fd = open(path, "a+")  # noqa: SIM115
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

        fd.seek(0)
        fd.truncate()
        fd.write(json.dumps({"turn": -1, "token": -1, "regroup_token": token, "regroup_armed_at": armed_at}))
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
        fd = open(path, "a+")  # noqa: SIM115
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
