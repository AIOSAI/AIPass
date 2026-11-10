# =================== AIPass ====================
# Name: context_window.py
# Version: 1.13.0
# Description: Context fill per CLI (Claude transcript, Codex rollout, OpenCode store) and the compact window
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-20
# Modified: 2026-11-10
# =============================================

"""Live context fill from a session transcript, and the window each CLI runs, read from a live source only.

Shared by pre_compact_prep.py and context_gauge.py.

Live context size ≈ input_tokens + cache_read_input_tokens + cache_creation_input_tokens
of the most recent assistant turn (proven readable S326).

Claude window: the context_window_size Claude Code hands its status line, which the status line writes
to live_window_path(session_id); capped by an explicit window when one is set (env beats settings).
No file, or a value that is not a positive int, is None: window unknown. No model list backs it.
Auto-compact fires at window - 33k. Codex: the rollout's model_context_window, else config's.
OpenCode keeps no transcript: opencode_fill reads its store, and opencode_window its models.dev catalog
and compaction.buffer, the rule OpenCode 2.2 compacts by; a model the catalog lacks is window unknown.
A Seed transcript (provider "seed") is Seed's own shape with no usage yet: it reads as none."""

import json
import os
import re
import sqlite3
import tempfile
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config.opencode_paths import opencode_db_path, opencode_store
from aipass.hooks.apps.handlers.json import files as json_files
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

_EXPLICIT_MIN = 100_000
_EXPLICIT_MAX = 1_000_000
_TAIL_BYTES = 50_000
_ENV_WINDOW = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
_SETTINGS_KEY = "autoCompactWindow"
_CODEX_USABLE_PCT = 95  # codex-rs default_effective_context_window_percent

AUTOCOMPACT_BUFFER = 33_000

SEED = "seed"

_SESSION_ID = re.compile(r"[\w-]+")
_STATE_DIR = Path(tempfile.gettempdir())
# One top-level `key = <int>` line of a TOML file: tomllib is 3.11+ and the project supports 3.10.
_TOML_INT = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=\s*\+?(\d[\d_]*)\s*(?:#.*)?$")


def user_settings_path() -> Path:
    """The user-level Claude Code settings file, resolved at call time (tests point it at tmp_path)."""
    return Path.home() / ".claude" / "settings.json"


def find_branch_dir(cwd: str) -> Path | None:
    """Resolve the branch root (src/aipass/<name>) from a cwd: the one walk the lifecycle handlers share."""
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "aipass" and i > 0 and parts[i - 1] == "src":
            branch_dir = Path(*parts[: i + 2])
            if branch_dir.is_dir():
                return branch_dir
    if (Path(cwd) / ".trinity").is_dir():
        return Path(cwd)
    return None


def transcript_provider(transcript_path: str) -> str:
    """ "codex" when the transcript's first line is a Codex rollout's session_meta, else "claude".

    Raises OSError when the transcript cannot be read."""
    with Path(transcript_path).open(encoding="utf-8", errors="replace") as fh:
        first = fh.readline()
    try:
        entry = json.loads(first)
    except json.JSONDecodeError:
        return "claude"
    return "codex" if isinstance(entry, dict) and entry.get("type") == "session_meta" else "claude"


def _latest(transcript_path: str, pick: Callable[[dict], object], tail_bytes: int = _TAIL_BYTES) -> object:
    """Tail a transcript JSONL and return what `pick` finds in the newest line it answers non-None for.

    The tail doubles until it holds one or covers the file: a long tool result can outgrow any fixed tail.
    Raises OSError when the transcript cannot be read; each public reader logs it and answers its own empty."""
    path = Path(transcript_path)
    size = path.stat().st_size
    while True:
        with path.open("rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            chunk = fh.read(min(size, tail_bytes))
        found = _newest_picked(chunk, pick)
        if found is not None or tail_bytes >= size:
            return found
        tail_bytes = max(tail_bytes, 1) * 2


def _newest_picked(chunk: bytes, pick: Callable[[dict], object]) -> object:
    lines = [ln for ln in chunk.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.info("[HOOKS] context_window: skipping unparsable transcript line: %s", exc)
            continue
        found = pick(entry) if isinstance(entry, dict) else None
        if found is not None:
            return found
    return None


def _claude_message(entry: dict, field: str, accept: Callable[[object], bool]) -> object:
    message = entry.get("message") if entry.get("type") == "assistant" else None
    value = message.get(field) if isinstance(message, dict) else None
    return value if accept(value) else None


def _codex_token_info(entry: dict, field: str) -> object:
    payload = entry.get("payload") if entry.get("type") == "event_msg" else None
    info = payload.get("info") if isinstance(payload, dict) else None
    return info.get(field) if isinstance(info, dict) else None


def read_latest_usage(transcript_path: str, tail_bytes: int = _TAIL_BYTES, provider: str = "") -> dict | None:
    """The newest usage dict: Claude's assistant message.usage, or Codex's token_count last_token_usage.

    *provider* is the caller's transcript_provider() reading or the payload's; empty reads it here."""
    if not transcript_path or provider == SEED:
        return None
    try:
        if (provider or transcript_provider(transcript_path)) == "codex":
            usage = _latest(transcript_path, lambda e: _codex_token_info(e, "last_token_usage"), tail_bytes)
        else:
            usage = _latest(transcript_path, lambda e: _claude_message(e, "usage", _is_dict), tail_bytes)
    except FileNotFoundError:
        logger.debug("[HOOKS] context_window: no transcript yet (turn 0): %s", transcript_path)
        return None
    except OSError as exc:
        logger.info("[HOOKS] context_window: transcript read failed: %s", exc)
        return None
    return usage if isinstance(usage, dict) else None


def _is_dict(value: object) -> bool:
    return isinstance(value, dict)


def context_fill_tokens(usage: dict) -> int:
    """Live context size of one turn. Claude: input + cache_read + cache_creation.

    Codex: total_tokens, the count its status line reads (input, which holds the cached part, plus output)."""
    if "total_tokens" in usage:
        return usage["total_tokens"]
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def live_window_path(session_id: str) -> Path | None:
    """The status line's window file for a session, beside the hooks' per-session state; None for an unsafe id."""
    if not _SESSION_ID.fullmatch(session_id or ""):
        return None
    return _STATE_DIR / f"aipass-cc-window-{session_id}.json"


def live_window(session_id: str) -> int | None:
    """The context_window_size the status line last wrote for the session; None when absent or not a positive int."""
    path = live_window_path(session_id)
    if path is None or not path.is_file():
        return None
    try:
        data = json_files.read_json_file(path)
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] context_window: live window unreadable for %s: %s", session_id, exc)
        return None
    size = data.get("context_window_size") if isinstance(data, dict) else None
    return size if isinstance(size, int) and not isinstance(size, bool) and size > 0 else None


def _settings_window(settings_path: Path) -> int | None:
    """A positive int autoCompactWindow from one settings file; "auto" or missing -> None.

    Raises json.JSONDecodeError / OSError on an unreadable file; explicit_window logs it and moves on."""
    if not settings_path.is_file():
        return None
    data = json_files.read_json_file(settings_path)
    window = data.get(_SETTINGS_KEY) if isinstance(data, dict) else None
    if isinstance(window, int) and not isinstance(window, bool) and window > 0:
        return window
    return None


def explicit_window(cwd: str) -> int | None:
    """An explicitly set window: env (clamped 100k..1M) > branch settings.local.json >
    branch settings.json > user settings. None when nothing sets one."""
    env_window = os.environ.get(_ENV_WINDOW, "")
    if env_window:
        try:
            return max(_EXPLICIT_MIN, min(_EXPLICIT_MAX, int(env_window)))
        except ValueError:
            logger.info("[HOOKS] context_window: bad env window value %r", env_window)

    candidates: list[Path] = []
    branch_dir = find_branch_dir(cwd)
    if branch_dir is not None:
        candidates.append(branch_dir / ".claude" / "settings.local.json")
        candidates.append(branch_dir / ".claude" / "settings.json")
    candidates.append(user_settings_path())

    for settings_path in candidates:
        try:
            window = _settings_window(settings_path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.info("[HOOKS] context_window: settings read failed: %s", exc)
            continue
        if window is not None:
            return window
    return None


def codex_home() -> Path:
    """Codex's home: $CODEX_HOME, else ~/.codex, resolved at call time (tests point it at tmp_path)."""
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_config_path() -> Path:
    """Codex's config.toml in its home."""
    return codex_home() / "config.toml"


def codex_hooks_path() -> Path:
    """Codex's user-level hooks.json, the only place its hook rows live."""
    return codex_home() / "hooks.json"


_OPENCODE_LATEST = (
    "SELECT data FROM session_message WHERE session_id = ? AND type = 'assistant' ORDER BY seq DESC LIMIT 1"
)
_OPENCODE_MODEL = "SELECT model FROM session_v2 WHERE id = ?"
# The catalog is ~11 MB of JSON: SQLite extracts the one row instead of Python parsing it all.
_OPENCODE_LIMIT = (
    "SELECT json_extract(json_extract(value, '$.body'), '$.' || json_quote(?) || '.models.' || json_quote(?) || '.limit')"
    " FROM kv WHERE key = 'models-dev:v2:catalog'"
)
_CATALOG_UPDATED = "SELECT time_updated FROM kv WHERE key = 'models-dev:v2:catalog'"
_LIMIT_CACHE_SECONDS = 24 * 60 * 60
_OPENCODE_HELD_BACK_PCT = 15
_OPENCODE_HELD_BACK_FLOOR = 16_000
_OPENCODE_FLOOR_FROM = 32_000


def opencode_config_path() -> Path:
    """OpenCode's user config: opencode/opencode.json in the XDG config home."""
    config = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config) / "opencode" / "opencode.json"


def opencode_fill(session_id: str) -> int | None:
    """An OpenCode session's live context as its status line counts it, or None when the store has no reading.

    The newest assistant message's input + output + reasoning + cache read + cache write; session_v2's
    tokens columns are running totals over every call, not the fill. The store is opened read-only.
    """
    db = opencode_db_path()
    if not session_id or not db.is_file():
        return None
    try:
        with closing(opencode_store()) as conn:
            row = conn.execute(_OPENCODE_LATEST, (session_id,)).fetchone()
        tokens = json.loads(row[0]).get("tokens") if row else None
    except (sqlite3.Error, ValueError, AttributeError) as exc:
        logger.info("[HOOKS] context_window: OpenCode store unreadable for %s: %s", session_id, exc)
        return None
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache")
    if not isinstance(cache, dict):
        cache = {}
    counted = [
        tokens.get("input"),
        tokens.get("output"),
        tokens.get("reasoning"),
        cache.get("read"),
        cache.get("write"),
    ]
    return sum(n for n in counted if isinstance(n, int))


def opencode_compact_point(limit: int, buffer: int | None) -> int:
    """OpenCode's auto-compact trigger: limit - compaction.buffer when set below the limit, else 15% held back, 16k at least from a 32k limit."""
    if buffer is not None and 0 <= buffer < limit:
        return limit - buffer
    floor = _OPENCODE_HELD_BACK_FLOOR if limit >= _OPENCODE_FLOOR_FROM else 0
    return limit - max(limit * _OPENCODE_HELD_BACK_PCT // 100, floor)


def opencode_window(session_id: str, cwd: str) -> tuple[int | None, int | None]:
    """(limit, compact point) OpenCode runs the session at; (None, None) when the catalog lacks the model (logged)."""
    limit = _opencode_limit(session_id)
    if not limit:
        logger.info("[HOOKS] context_window: no catalog limit for OpenCode session %s, window unknown", session_id)
        return None, None
    return limit, opencode_compact_point(limit, _opencode_buffer(cwd))


def opencode_limit_cache_path() -> Path:
    """Catalog limits already read, per model, so a prompt skips the 11 MB catalog."""
    return Path(tempfile.gettempdir()) / "aipass-opencode-limits.json"


def _opencode_limit(session_id: str) -> int:
    """The session model's limit.input, else limit.context, from the models.dev catalog in the store; 0 when absent.

    A limit is cached per model until the catalog row's time_updated changes, or for a day.
    """
    if not session_id or not opencode_db_path().is_file():
        return 0
    cache = _read_limit_cache()
    try:
        with closing(opencode_store()) as conn:
            row = conn.execute(_OPENCODE_MODEL, (session_id,)).fetchone()
            model = json.loads(row[0]) if row and row[0] else {}
            updated = (conn.execute(_CATALOG_UPDATED).fetchone() or [None])[0]
            name = f"{model.get('providerID')}/{model.get('id')}"
            hit = cache.get(name)
            if (
                isinstance(hit, dict)
                and hit.get("catalog") == updated
                and time.time() - hit.get("at", 0) < _LIMIT_CACHE_SECONDS
            ):
                return hit.get("limit", 0)
            found = conn.execute(_OPENCODE_LIMIT, (model.get("providerID"), model.get("id"))).fetchone()
        limit = json.loads(found[0]) if found and found[0] else {}
    except (sqlite3.Error, ValueError, AttributeError) as exc:
        logger.info("[HOOKS] context_window: OpenCode catalog unreadable for %s: %s", session_id, exc)
        return 0
    value = limit.get("input") or limit.get("context") if isinstance(limit, dict) else None
    value = value if isinstance(value, int) and value > 0 else 0
    cache[name] = {"limit": value, "catalog": updated, "at": time.time()}
    try:
        json_files.write_json_file(opencode_limit_cache_path(), cache)
    except OSError as exc:
        logger.info("[HOOKS] context_window: OpenCode limit cache not written: %s", exc)
    return value


def _read_limit_cache() -> dict:
    path = opencode_limit_cache_path()
    if not path.is_file():
        return {}
    try:
        cache = json_files.read_json_file(path)
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] context_window: OpenCode limit cache unreadable, reading the catalog: %s", exc)
        return {}
    return cache if isinstance(cache, dict) else {}


def _opencode_buffer(cwd: str) -> int | None:
    """compaction.buffer by OpenCode's precedence: OPENCODE_CONFIG_CONTENT, the project's opencode.json, the user's."""
    texts = [os.environ.get("OPENCODE_CONFIG_CONTENT", "")]
    start = Path(cwd)
    for folder in (start, *start.parents):
        texts.append(_read_text(folder / "opencode.json"))
        if (git := folder / ".git").is_file() or (git.is_dir() and any(git.iterdir())):
            break
    texts.append(_read_text(opencode_config_path()))
    for text in filter(None, texts):
        try:
            buffer = json.loads(text).get("compaction", {}).get("buffer")
        except (ValueError, AttributeError) as exc:
            logger.info("[HOOKS] context_window: OpenCode config unreadable: %s", exc)
            continue
        if isinstance(buffer, int):
            return buffer
    return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[HOOKS] context_window: %s unreadable: %s", path, exc)
        return ""


def _codex_config_int(key: str) -> int | None:
    """A positive int `key` from Codex's config.toml; None when unset, 0 when the file is unreadable (logged)."""
    path = codex_config_path()
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[HOOKS] context_window: codex config read failed: %s", exc)
        return 0
    for line in lines:
        if line.lstrip().startswith("["):
            return None  # a table header ends the top level; a same-named key below it is not Codex's
        match = _TOML_INT.match(line)
        if match and match.group(1) == key:
            value = int(match.group(2).replace("_", ""))
            return value if value > 0 else None
    return None


def _codex_window(transcript_path: str) -> int | None:
    """The window Codex counts against: the rollout's model_context_window, else config's (cut to the usable 95%), else None."""
    try:
        window = _latest(transcript_path, lambda e: _codex_token_info(e, "model_context_window"))
    except OSError as exc:
        logger.info("[HOOKS] context_window: rollout window read failed: %s", exc)
        window = None
    if isinstance(window, int) and window > 0:
        return window
    configured = _codex_config_int("model_context_window")
    return configured * _CODEX_USABLE_PCT // 100 if configured else None


def resolve_compact_window(cwd: str, session_id: str = "", transcript_path: str = "", provider: str = "") -> int | None:
    """The effective window. A Codex rollout: the window Codex counts against (_codex_window).

    Claude: the session's live window, capped by explicit when one is set. None when the status line
    has written no window for the session: window unknown, whatever is explicit."""
    if transcript_path and (provider or _provider_or_claude(transcript_path)) == "codex":
        return _codex_window(transcript_path)
    window = live_window(session_id)
    if window is None:
        return None
    explicit = explicit_window(cwd)
    return min(window, explicit) if explicit is not None else window


def compact_threshold(window: int | None, provider: str = "claude") -> int | None:
    """The fill at which the CLI auto-compacts. Claude Code: window - 33k.

    Codex (codex-rs protocol/src/openai_models.rs, ModelInfo::auto_compact_token_limit): 90% of the full
    window, lowered by config model_auto_compact_token_limit; `window` is the usable 95% of the full one.
    An unknown window (None) has no point."""
    if window is None:
        return None
    if provider != "codex":
        return window - AUTOCOMPACT_BUFFER
    default = window * 100 // _CODEX_USABLE_PCT * 9 // 10
    limit = _codex_config_int("model_auto_compact_token_limit")
    return min(limit, default) if limit else default


def _provider_or_claude(transcript_path: str) -> str:
    try:
        return transcript_provider(transcript_path)
    except OSError as exc:
        logger.info("[HOOKS] context_window: transcript shape unreadable, reading it as Claude's: %s", exc)
        return "claude"


# =============================================================================
# MODULE INTERFACE (drone @hooks routing)
# =============================================================================


def print_introspection() -> None:
    """Print context_window config and the resolved window for CWD."""
    CONSOLE.print("[bold cyan]context_window[/bold cyan] Module")
    CONSOLE.print("  Claude window: the status line's context_window_size per session (none written: unknown)")
    CONSOLE.print(f"  Auto-compact buffer: {AUTOCOMPACT_BUFFER:,}")
    CONSOLE.print(f"  Transcript tail read: {_TAIL_BYTES:,} bytes")
    explicit = explicit_window(str(Path.cwd()))
    CONSOLE.print(f"  Explicit window (CWD): {f'{explicit:,}' if explicit is not None else 'none'}")
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    window = resolve_compact_window(str(Path.cwd()), session_id)
    CONSOLE.print(f"  Resolved window (this session): {f'{window:,}' if window is not None else 'unknown'}")


def handle_command(command: str, args: list) -> bool:
    """Route context_window commands from drone @hooks."""
    if command in ("--help", "-h", "help") or (command == "context_window" and wants_help(args)):
        CONSOLE.print("[bold cyan]context_window[/bold cyan] — Transcript usage + compact-window resolver")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks context_window    Show known windows, buffer, tail size, resolved window for CWD")
        return True

    if command == "context_window":
        if not args:
            print_introspection()
            return True
    return False
