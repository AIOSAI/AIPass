# =================== AIPass ====================
# Name: cadence.py
# Version: 2.9.2
# Description: Per-session turn counter for prompt injection cadence (DPLAN-0200)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-06-08
# Modified: 2026-10-17
# =============================================

"""Turn counter for prompt injection cadence — fires loaders every Nth turn.

Each loader runs as its own process: flock + mtime debounce + a per-turn key count each real turn once.
"""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.hooks.apps.handlers.module_root import module_file
from aipass.hooks.apps.modules.grounding_content import find_branch_root

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
    # Transcript bytes within which a completed post-compact re-ground stands in for the turn-0
    # fire-all (0 = off). cadence_config.json is gitignored, so this is what a clone runs on.
    "regroup_fresh_bytes": 150000,
    "loaders": {
        "tier0": {"period": 5, "offset": 0},
        "navmap": {"period": 5, "offset": 0},
        "identity": {"period": 5, "offset": 0},
        "branch": {"offset": 0},
        "email": {"period": 5},
        "alert": {"period": 5},
    },
    # {"<branch>": {"loaders": {"<loader>": {...}}}}, each merged over that loader's global entry;
    # "beat": false fires a loader at turn 0 only.
    "branches": {},
}

MAIL_LOADER = "email"

#: The loaders that ground a seat: the post-compact backstop carries them and stands in for them at turn 0.
GROUNDING_LOADERS = frozenset({"tier0", "navmap", "identity", "branch"})

#: How a harness-sent turn (task-notification) opens when the payload has no `source` field.
_AUTOMATED_PROMPT_PREFIXES = ("<task-notification>", "[SYSTEM NOTIFICATION")

#: When turns cannot be counted only these fire; every other loader is WITHHELD. Not open (turn 0 on
#: every prompt, ~21k chars a turn), not closed (dark). alert and email are tiny channels, not grounding.
DEGRADED_LOADERS = frozenset({"tier0", "alert", MAIL_LOADER})

#: The one loader whose degraded line logs at WARNING, so a degraded turn costs one WARNING.
DEGRADED_REPORTER = "tier0"

_turn: int | None = None
_config: dict | None = None
#: Why the turn counter cannot count, when it cannot; set beside _turn so the memo carries its provenance.
_turn_degraded: str | None = None


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


def is_automated(hook_data: dict | None) -> bool:
    """True when the harness, not a person, sent this UserPromptSubmit (DPLAN-0348).

    `source` decides when present; else how the prompt OPENS (a quoted marker mid-sentence stays human).
    A missing prompt reads as human, so a payload change fails toward counting, not going dark.
    """
    data = hook_data or {}
    source = data.get("source")
    if isinstance(source, str) and source:
        return source == "system"
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return False
    return prompt.lstrip().startswith(_AUTOMATED_PROMPT_PREFIXES)


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


def _prompt_key(hook_data: dict, token: int) -> str | None:
    """One prompt's identity, shared by every sibling process of it; None when the payload has none.

    A headless first prompt runs before the transcript exists (size 0), so the text tells prompts
    apart and the size tells a repeated text apart.
    """
    prompt = hook_data.get("prompt")
    if not isinstance(prompt, str) and not hook_data.get("transcript_path"):
        return None
    text = prompt if isinstance(prompt, str) else ""
    return hashlib.sha1(f"{token}\0{text}".encode("utf-8")).hexdigest()[:16]


def _should_increment(stored_turn: int, stored_token: int, token: int, fd, key=None, stored_key=None) -> bool:
    """Decide whether to increment the counter: once per prompt key, else by the old window.

    Without a key on both sides, the 2s debounce and the nonzero-token guard decide.
    """
    if stored_turn < 0:
        return True
    if key is not None and stored_key is not None:
        return key != stored_key
    if _mtime_age(fd) < _DEBOUNCE_S:
        return False
    if token == stored_token and token != 0:
        return False
    return True


def _read_turn_uncounted(path: Path) -> int:
    """The stored turn for an automated prompt: read under the lock, never written.

    A stored token equal to the next real turn's would debounce it away, and a truncating
    write would cancel a queued post-compact re-ground.
    """
    global _turn_degraded
    if not path.exists():
        return -1
    fd = None
    try:
        fd = open(path, encoding="utf-8")
        _lock(fd)
        content = fd.read()
        _close_fd(fd)
        fd = None
        stored = json.loads(content).get("turn", -1) if content.strip() else -1
        return stored if isinstance(stored, int) else -1
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        _turn_degraded = f"cadence state file {path} could not be read: {exc}"
        logger.warning("[HOOKS] cadence: state read failed on an automated turn, turn falls back to 0: %s", exc)
        if fd is not None:
            _close_fd(fd)
        return 0


def _load_and_increment(hook_data: dict) -> int:
    """Load turn counter, increment exactly once per real turn. Multi-process safe."""
    global _turn, _turn_degraded
    if _turn is not None:
        return _turn

    path = _state_path()
    if path is None:
        _turn_degraded = "no CLAUDE_CODE_SESSION_ID in the environment, so there is no state file to count in"
        _turn = 0
        return 0

    if is_automated(hook_data):
        _turn = _read_turn_uncounted(path)
        return _turn

    token = _get_turn_token(hook_data)
    key = _prompt_key(hook_data, token)
    fd = None

    try:
        fd = open(path, "a+", encoding="utf-8")
        _lock(fd)
        fd.seek(0)
        content = fd.read()

        data = json.loads(content) if content.strip() else {}
        stored_turn = data.get("turn", -1)
        stored_token = data.get("token", -1)

        if _should_increment(stored_turn, stored_token, token, fd, key, data.get("key")):
            new_turn = max(stored_turn + 1, 0)
            fd.seek(0)
            fd.truncate()
            fd.write(json.dumps({"turn": new_turn, "token": token, "key": key}))
            fd.flush()
        else:
            new_turn = stored_turn

        _close_fd(fd)
        fd = None
        _turn = new_turn
        return new_turn

    except (OSError, json.JSONDecodeError) as exc:
        _turn_degraded = f"cadence state file {path} could not be read or written: {exc}"
        logger.warning("[HOOKS] cadence: state access failed, turn falls back to 0: %s", exc)
        if fd is not None:
            _close_fd(fd)
        _turn = 0
        return 0


def degraded_reason() -> str | None:
    """Why this process cannot count turns, or None when cadence is healthy.

    Meaningful only after should_fire() has read the state in this process.
    """
    return _turn_degraded


def _degraded_fire(loader_name: str) -> bool:
    """The degraded fail mode's answer for one loader, logged once per turn at WARNING."""
    fires = loader_name in DEGRADED_LOADERS
    log = logger.warning if loader_name == DEGRADED_REPORTER else logger.info
    log(
        "[HOOKS] cadence DEGRADED loader=%s %s: turns cannot be counted, so only %s fire and every other "
        "loader is withheld until this is cured — %s",
        loader_name,
        "fires" if fires else "WITHHELD",
        ", ".join(sorted(DEGRADED_LOADERS)),
        _turn_degraded,
    )
    return fires


def _prompt_branch(hook_data: dict) -> str:
    """The branch a prompt came from: its cwd's branch root, by name. "none" when there is none.

    The payload's cwd only, never this process's. No branch is not a failure: the global entries serve.
    """
    cwd = hook_data.get("cwd")
    root = find_branch_root(cwd) if isinstance(cwd, str) and cwd else None
    if root is None:
        logger.info("[HOOKS] cadence: cwd %r is under no branch, the global loader config applies", cwd)
        return "none"
    return root.name


def _branch_loader_override(config: dict, branch: str, loader_name: str) -> dict:
    """The branch's override for one loader (DPLAN-0355), {} when it has none.

    Malformed: logs ERROR and serves {} (the global entry); the operator-owned file is never rewritten.
    """
    override = config.get("branches")
    for key in (branch, "loaders", loader_name):
        if not isinstance(override, dict):
            break
        override = override.get(key, {})
    if not isinstance(override, dict):
        problem = "branches, branches.<branch>, .loaders and .loaders.<loader> must each be an object"
    elif "beat" in override and not isinstance(override["beat"], bool):
        problem = f"beat must be true or false, got {override['beat']!r}"
    elif any(type(override.get(key, 0)) is not int for key in ("period", "offset")):
        problem = "period and offset must be whole numbers"
    else:
        return override
    logger.error(
        "[HOOKS] cadence: malformed override for branch=%s loader=%s in %s (%s); the global entry serves",
        branch,
        loader_name,
        _CONFIG_PATH,
        problem,
    )
    return {}


def should_fire(loader_name: str, hook_data: dict | None = None) -> bool:
    """Check if a loader should fire this turn. Always True on turn 0 or if cadence disabled."""
    config = _load_config()

    if not config.get("enabled", True):
        return True

    global_period = config.get("period", 5)

    branch = _prompt_branch(hook_data or {})
    loader_config = _deep_merge(
        dict(config.get("loaders", {}).get(loader_name, {})),
        _branch_loader_override(config, branch, loader_name),
    )
    period = loader_config.get("period", global_period)
    offset = loader_config.get("offset", 0)
    beat = loader_config.get("beat", True) is not False

    if beat and period <= 0:
        return True

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    session_short = session_id[:8] if session_id else "none"

    # Before the turn-0 clause: an automated turn is no beat for any loader. Mail still announces
    # via should_fire_mail, and an alert's arrival never asks cadence.
    if is_automated(hook_data):
        logger.info(
            "[HOOKS] cadence skipped loader=%s automated turn session=%s branch=%s", loader_name, session_short, branch
        )
        return False

    turn = _load_and_increment(hook_data or {})
    if _turn_degraded is not None:
        return _degraded_fire(loader_name)

    if turn == 0 and loader_name in GROUNDING_LOADERS and _grounded_by_regroup(hook_data or {}, config):
        logger.info(
            "[HOOKS] cadence suppressed loader=%s turn=0: the post-compact re-ground already delivered it "
            "session=%s branch=%s",
            loader_name,
            session_short,
            branch,
        )
        return False

    fired = turn == 0 or (beat and (turn % period) == offset)

    action = "fired" if fired else "skipped"
    logger.info(
        "[HOOKS] cadence %s loader=%s turn=%d period=%d offset=%d beat=%s session=%s branch=%s",
        action,
        loader_name,
        turn,
        period,
        offset,
        "on" if beat else "off",
        session_short,
        branch,
    )

    return fired


def _mail_state_path() -> Path | None:
    """Per-session state for the mail notification loop.

    Not the turn counter's file: _load_and_increment() truncates it every turn, and that
    truncation is what disarms the post-compact regroup token.
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

    Zero new mail is silent AND clears the state, so the next arrival announces on the turn it lands.
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
    turn = _load_and_increment(hook_data or {})
    if path is None or _turn_degraded is not None:
        return _degraded_fire(MAIL_LOADER)
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
# Used only when the turn cannot be read: a throttle must never degrade to "every time".
ADVISORY_SECONDS = 600


def turn_token(hook_data: dict) -> int:
    """The per-turn token for *hook_data*: identical in every sibling process of one turn.

    Public for the injection ledger, which groups by it. Read-only: touches no cadence state.
    """
    return _get_turn_token(hook_data)


def current_turn() -> int | None:
    """The turn counter WITHOUT advancing it, or None when it cannot be read.

    A PreToolUse consumer must never call _load_and_increment: several tool calls share one
    turn, and its guard keys off UserPromptSubmit.
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

    Not the turn counter's file: _load_and_increment truncates that every turn.
    """
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    return _GUARD_DIR / f"aipass-advisory-{name}-{session_id}.json"


def should_fire_advisory(name: str, period: int = ADVISORY_PERIOD) -> bool:
    """True at most once per *period* turns for the named advisory.

    For standing conditions that re-assert on every edit. Also fires when the turn went BACKWARDS
    (compact or new session); falls back to elapsed seconds when the turn cannot be read.
    """
    path = _advisory_state_path(name)
    if path is None:
        logger.warning(
            "[HOOKS] cadence FAIL-OPEN advisory=%s: it fires EVERY time — "
            "no CLAUDE_CODE_SESSION_ID in the environment, so there is no state file to throttle in",
            name,
        )
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

    Also arms a one-shot regroup token for the PostToolUse backstop. A duplicate reset within
    _REGROUP_DEBOUNCE_S reuses the token, so the backstop fires at most once per compact.
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
        fd = open(path, "a+", encoding="utf-8")
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
            regroup_stamp = data.get("regroup_token")
            armed_at = prior_armed_at
        else:
            regroup_stamp = f"{int(now * 1000)}-{pid}"
            armed_at = now

        state = {"turn": -1, "token": -1, "regroup_token": regroup_stamp, "regroup_armed_at": armed_at}
        if debounced:
            # A duplicate reset on the SAME boundary must not cancel its queued re-ground parts.
            for key in ("regroup_next", "regroup_total"):
                if key in data:
                    state[key] = data[key]
        fd.seek(0)
        fd.truncate()
        fd.write(json.dumps(state))
        fd.flush()
        _close_fd(fd)
        fd = None
        window_id = (hook_data or {}).get("session_id", "") or session_id
        _stamp_window(window_id, armed_at if isinstance(armed_at, (int, float)) else now, caller)

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
                regroup_stamp,
                session_short,
                old_turn,
            )
    except OSError as exc:
        logger.info(
            "[HOOKS] cadence: reset write FAILED caller=%s pid=%d session=%s: %s", caller, pid, session_short, exc
        )
        if fd is not None:
            _close_fd(fd)


def _window_path(session_id: str) -> Path:
    return _GUARD_DIR / f"aipass-window-opened-{session_id}.json"


def _stamp_window(session_id: str, opened_at: float, caller: str) -> None:
    """Record when this session's context window opened, in a file of its own.

    Not the counter's file (truncated every real turn). A debounced reset passes the SAME
    armed_at, so two callers on one boundary open one window.
    """
    try:
        _window_path(session_id).write_text(json.dumps({"opened_at": opened_at, "caller": caller}), encoding="utf-8")
    except OSError as exc:
        logger.info("[HOOKS] cadence: window stamp write FAILED caller=%s session=%s: %s", caller, session_id[:8], exc)


def window_opened_at(hook_data: dict | None = None) -> float | None:
    """When the current context window opened (the last reset_counter), or None if never stamped.

    Session-keyed state outlives compaction: a consumer seeing this value change knows a new
    window opened. The payload's session id comes first on both sides, as consumers key by it.
    """
    session_id = (hook_data or {}).get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        return None
    path = _window_path(session_id)
    if not path.exists():
        return None
    try:
        opened_at = json.loads(path.read_text(encoding="utf-8") or "{}").get("opened_at")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        logger.info("[HOOKS] cadence: window stamp unreadable: %s", exc)
        return None
    if isinstance(opened_at, bool) or not isinstance(opened_at, (int, float)):
        return None
    return opened_at


def _regroup_done_path(session_id: str) -> Path:
    return _GUARD_DIR / f"aipass-regroup-done-{session_id}.json"


def stamp_regroup_complete(hook_data: dict | None = None) -> None:
    """Record that the post-compact backstop handed out its FINAL part (DPLAN-0348).

    Its own file (the counter's is truncated every real turn). The window lets a new compaction
    re-arm the fire-all; the transcript size lets the stand-in lapse with distance.
    """
    session_id = (hook_data or {}).get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    window = window_opened_at(hook_data)
    transcript_mark = _get_turn_token(hook_data or {})
    if not session_id or window is None or transcript_mark <= 0:
        logger.info(
            "[HOOKS] cadence: regroup completion NOT stamped (session=%s window=%s token=%d), fire-all stays",
            session_id[:8] or "none",
            window,
            transcript_mark,
        )
        return
    try:
        stamp = {"window": window, "token": transcript_mark, "used_token": None}
        _regroup_done_path(session_id).write_text(json.dumps(stamp), encoding="utf-8")
    except OSError as exc:
        logger.info("[HOOKS] cadence: regroup completion stamp write FAILED session=%s: %s", session_id[:8], exc)
        return
    logger.info("[HOOKS] cadence: regroup complete, stamped token=%d session=%s", transcript_mark, session_id[:8])


def _stands_in(stamp: dict, window: float | None, token: int, distance: int) -> bool:
    """Whether *stamp* covers a turn-0 prompt at *token* in *window*. Pure, so each rule reads alone."""
    stamped = stamp.get("token")
    used = stamp.get("used_token")
    return (
        window is not None
        and stamp.get("window") == window
        and isinstance(stamped, int)
        and token > 0
        and 0 <= token - stamped <= distance
        and used in (None, token)
    )


def _grounded_by_regroup(hook_data: dict, config: dict) -> bool:
    """True when a completed post-compact re-ground stands in for this turn-0 fire-all.

    All must hold: the stamp is for THIS window, within regroup_fresh_bytes, and unspent or spent by
    this same prompt (sibling loader processes share the token, so a later turn 0 still fires).
    """
    distance = config.get("regroup_fresh_bytes", 0)
    session_id = hook_data.get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if isinstance(distance, bool) or not isinstance(distance, int) or distance <= 0 or not session_id:
        return False
    path = _regroup_done_path(session_id)
    if not path.exists():
        return False
    window = window_opened_at(hook_data)
    token = _get_turn_token(hook_data)
    fd = None
    try:
        fd = open(path, "r+", encoding="utf-8")
        _lock(fd)
        content = fd.read()
        stamp = json.loads(content) if content.strip() else {}
        grounded = isinstance(stamp, dict) and _stands_in(stamp, window, token, distance)
        if grounded and stamp.get("used_token") is None:
            stamp["used_token"] = token
            fd.seek(0)
            fd.truncate()
            fd.write(json.dumps(stamp))
            fd.flush()
        _close_fd(fd)
        fd = None
        return grounded
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[HOOKS] cadence: regroup completion stamp unreadable, the fire-all stands: %s", exc)
        if fd is not None:
            _close_fd(fd)
        return False


def consume_regroup_pending(hook_data: dict | None = None) -> bool:
    """Atomically check-and-clear the post-compact regrounding token.

    True at most once per compact. The PostToolUse backstop fires grounding itself, since its
    additionalContext reaches Claude even when no UserPromptSubmit arrives.
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
        fd = open(path, "a+", encoding="utf-8")
        _lock(fd)
        fd.seek(0)
        content = fd.read()
        data = json.loads(content) if content.strip() else {}
        regroup_stamp = data.get("regroup_token")
        pending = bool(regroup_stamp)

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
                regroup_stamp,
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

    Output over Claude Code's 10,000-char hook limit reaches the agent as a 2,000-char preview.
    The queue shares the counter's file on purpose: a real prompt truncates it, and that is
    exactly when the remaining parts must stop.
    """
    if total < 2:
        return
    path, session_short = _regroup_state_path(hook_data)
    if path is None:
        return
    fd = None
    try:
        fd = open(path, "a+", encoding="utf-8")
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

    Read, advance and write under one flock; the keys go with the last part, so it ends silent.
    """
    path, session_short = _regroup_state_path(hook_data)
    if path is None or not path.exists():
        return None
    fd = None
    try:
        fd = open(path, "a+", encoding="utf-8")
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
            # No offset: the mail banner is an elapsed-turns loop, not a modulo slot.
            CONSOLE.print(f"  Loader '{name}': period={lp} (elapsed-turns loop, announces on arrival)")
        else:
            beat = "off" if lcfg.get("beat", True) is False else "on"
            CONSOLE.print(f"  Loader '{name}': period={lp} offset={lcfg.get('offset', 0)} beat={beat}")
    branches = config.get("branches")
    CONSOLE.print(f"  Branch overrides: {json.dumps(branches) if branches else 'none (every branch runs the above)'}")
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
