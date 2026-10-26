# =================== AIPass ====================
# Name: context_window.py
# Version: 1.5.0
# Description: Transcript reader (Claude transcript + Codex rollout) and the compact window and point per CLI
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-20
# Modified: 2026-10-26
# =============================================

"""Live context fill and the model from a session transcript, and the window Claude Code runs.

Shared by pre_compact_prep.py and context_gauge.py.

Live context size ≈ input_tokens + cache_read_input_tokens + cache_creation_input_tokens
of the most recent assistant turn (proven readable S326).

Window, as Claude Code 2.1.304 picks it: the model's own window (`[1m]` suffix or a native-1M
id -> 1M, else 200k), capped by an explicit window when one is set (env beats settings).
Auto-compact fires at window - 33k."""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.json import files as json_files
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

_DEFAULT_WINDOW = 200_000
_NATIVE_1M_WINDOW = 1_000_000
_EXPLICIT_MIN = 100_000
_EXPLICIT_MAX = 1_000_000
_TAIL_BYTES = 50_000
_ENV_WINDOW = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
_SETTINGS_KEY = "autoCompactWindow"
_CODEX_USABLE_PCT = 95  # codex-rs default_effective_context_window_percent

AUTOCOMPACT_BUFFER = 33_000

NATIVE_1M_MODELS = frozenset(
    {
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-opus-5-5",
        "claude-sonnet-5",
        "claude-sonnet-5-5",
        "claude-fable-5",
        "claude-fable-5-1",
        "claude-mythos-5",
        "claude-mythos-5-1",
    }
)

_BRACKET_SUFFIX = re.compile(r"\[[^\]]*\]$")
_DATE_SUFFIX = re.compile(r"-\d{8}$")
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


def _codex_model(entry: dict) -> str | None:
    payload = entry.get("payload") if entry.get("type") == "turn_context" else None
    model = payload.get("model") if isinstance(payload, dict) else None
    return model if isinstance(model, str) and model else None


def _is_real_model(model: object) -> bool:
    # "<synthetic>" marks a locally made assistant line (API error, interrupt), not a model.
    return isinstance(model, str) and bool(model) and not model.startswith("<")


def read_latest_usage(transcript_path: str, tail_bytes: int = _TAIL_BYTES) -> dict | None:
    """The newest usage dict: Claude's assistant message.usage, or Codex's token_count last_token_usage."""
    if not transcript_path:
        return None
    try:
        if transcript_provider(transcript_path) == "codex":
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


def read_latest_model(transcript_path: str, tail_bytes: int = _TAIL_BYTES) -> str:
    """The model id of the most recent turn (Codex: turn_context), or "" when the transcript names none."""
    if not transcript_path:
        return ""
    try:
        if transcript_provider(transcript_path) == "codex":
            model = _latest(transcript_path, _codex_model, tail_bytes)
        else:
            model = _latest(transcript_path, lambda e: _claude_message(e, "model", _is_real_model), tail_bytes)
    except FileNotFoundError:
        logger.debug("[HOOKS] context_window: no transcript yet (turn 0): %s", transcript_path)
        return ""
    except OSError as exc:
        logger.info("[HOOKS] context_window: transcript read failed: %s", exc)
        return ""
    return model if isinstance(model, str) else ""


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


def model_window(model_id: str) -> int:
    """The window Claude Code gives a model id: `[1m]` or a native-1M id -> 1M, anything else -> 200k."""
    model = (model_id or "").strip().lower()
    if not model:
        return _DEFAULT_WINDOW
    if "[1m]" in model:
        return _NATIVE_1M_WINDOW
    model = _DATE_SUFFIX.sub("", _BRACKET_SUFFIX.sub("", model))
    return _NATIVE_1M_WINDOW if model in NATIVE_1M_MODELS else _DEFAULT_WINDOW


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


def codex_config_path() -> Path:
    """Codex's config.toml under $CODEX_HOME or ~/.codex, resolved at call time (tests point it at tmp_path)."""
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"


def _codex_config_int(key: str) -> int | None:
    """A positive int `key` from Codex's config.toml; None when unset or unreadable (logged)."""
    path = codex_config_path()
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[HOOKS] context_window: codex config read failed: %s", exc)
        return None
    for line in lines:
        if line.lstrip().startswith("["):
            return None  # a table header ends the top level; a same-named key below it is not Codex's
        match = _TOML_INT.match(line)
        if match and match.group(1) == key:
            value = int(match.group(2).replace("_", ""))
            return value if value > 0 else None
    return None


def _codex_window(transcript_path: str) -> int:
    """The window Codex counts against: the rollout's model_context_window, else config's (cut to the usable 95%)."""
    try:
        window = _latest(transcript_path, lambda e: _codex_token_info(e, "model_context_window"))
    except OSError as exc:
        logger.info("[HOOKS] context_window: rollout window read failed: %s", exc)
        window = None
    if isinstance(window, int) and window > 0:
        return window
    configured = _codex_config_int("model_context_window")
    return configured * _CODEX_USABLE_PCT // 100 if configured else _DEFAULT_WINDOW


def resolve_compact_window(cwd: str, model_id: str = "", transcript_path: str = "") -> int:
    """The effective window. A Codex rollout: the window Codex counts against (_codex_window).

    Claude: min(model window, explicit) when explicit is set, else the model window; with no model id
    the explicit value (or the 200k default) stands, as before model awareness."""
    if transcript_path and _provider_or_claude(transcript_path) == "codex":
        return _codex_window(transcript_path)
    explicit = explicit_window(cwd)
    if not model_id:
        return explicit if explicit is not None else _DEFAULT_WINDOW
    window = model_window(model_id)
    return min(window, explicit) if explicit is not None else window


def compact_threshold(window: int, provider: str = "claude") -> int:
    """The fill at which the CLI auto-compacts. Claude Code: window - 33k.

    Codex (codex-rs protocol/src/openai_models.rs, ModelInfo::auto_compact_token_limit): 90% of the full
    window, lowered by config model_auto_compact_token_limit; `window` is the usable 95% of the full one."""
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
    CONSOLE.print(f"  Default window: {_DEFAULT_WINDOW:,} (native-1M models: {_NATIVE_1M_WINDOW:,})")
    CONSOLE.print(f"  Auto-compact buffer: {AUTOCOMPACT_BUFFER:,}")
    CONSOLE.print(f"  Transcript tail read: {_TAIL_BYTES:,} bytes")
    explicit = explicit_window(str(Path.cwd()))
    CONSOLE.print(f"  Explicit window (CWD): {f'{explicit:,}' if explicit is not None else 'none'}")
    window = resolve_compact_window(str(Path.cwd()))
    CONSOLE.print(f"  Resolved window (CWD, no model): {window:,}")


def handle_command(command: str, args: list) -> bool:
    """Route context_window commands from drone @hooks."""
    if command in ("--help", "-h", "help") or (command == "context_window" and wants_help(args)):
        CONSOLE.print("[bold cyan]context_window[/bold cyan] — Transcript usage + compact-window resolver")
        CONSOLE.print()
        CONSOLE.print(
            "  drone @hooks context_window    Show default window, buffer, tail size, resolved window for CWD"
        )
        return True

    if command == "context_window":
        if not args:
            print_introspection()
            return True
    return False
