# =================== AIPass ====================
# Name: context_window.py
# Version: 1.3.0
# Description: Shared transcript reader (usage + model) and model-aware compact-window resolver (DPLAN-0253)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-20
# Modified: 2026-10-24
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


def _latest_assistant_message(
    transcript_path: str, wanted: Callable[[dict], bool], tail_bytes: int = _TAIL_BYTES
) -> dict | None:
    """Tail a transcript JSONL and return the newest assistant `message` dict that `wanted` accepts.

    The tail doubles until it holds one or covers the file: a long tool result can outgrow any fixed tail.
    Raises OSError when the transcript cannot be read; each public reader logs it and answers its own empty."""
    if not transcript_path:
        return None

    path = Path(transcript_path)
    size = path.stat().st_size
    while True:
        with path.open("rb") as fh:
            fh.seek(max(0, size - tail_bytes))
            chunk = fh.read(min(size, tail_bytes))
        message = _newest_wanted(chunk, wanted)
        if message is not None or tail_bytes >= size:
            return message
        tail_bytes = max(tail_bytes, 1) * 2


def _newest_wanted(chunk: bytes, wanted: Callable[[dict], bool]) -> dict | None:
    lines = [ln for ln in chunk.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.info("[HOOKS] context_window: skipping unparsable transcript line: %s", exc)
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if isinstance(message, dict) and wanted(message):
            return message
    return None


def read_latest_usage(transcript_path: str, tail_bytes: int = _TAIL_BYTES) -> dict | None:
    """Tail a transcript JSONL and return the most recent assistant message's usage dict."""
    try:
        message = _latest_assistant_message(transcript_path, lambda m: isinstance(m.get("usage"), dict), tail_bytes)
    except OSError as exc:
        logger.info("[HOOKS] context_window: transcript read failed: %s", exc)
        return None
    return message["usage"] if message is not None else None


def _is_real_model(message: dict) -> bool:
    model = message.get("model")
    # "<synthetic>" marks a locally made assistant line (API error, interrupt), not a model.
    return isinstance(model, str) and bool(model) and not model.startswith("<")


def read_latest_model(transcript_path: str, tail_bytes: int = _TAIL_BYTES) -> str:
    """The model id of the most recent assistant turn, or "" when the transcript names none."""
    try:
        message = _latest_assistant_message(transcript_path, _is_real_model, tail_bytes)
    except OSError as exc:
        logger.info("[HOOKS] context_window: transcript read failed: %s", exc)
        return ""
    return message["model"] if message is not None else ""


def context_fill_tokens(usage: dict) -> int:
    """Live context size ≈ input + cache_read + cache_creation of one turn."""
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


def resolve_compact_window(cwd: str, model_id: str = "") -> int:
    """The effective window: min(model window, explicit) when explicit is set, else the model window.

    With no model id the explicit value (or the 200k default) stands, as before model awareness."""
    explicit = explicit_window(cwd)
    if not model_id:
        return explicit if explicit is not None else _DEFAULT_WINDOW
    window = model_window(model_id)
    return min(window, explicit) if explicit is not None else window


def compact_threshold(window: int) -> int:
    """The fill at which Claude Code auto-compacts: window - 33k."""
    return window - AUTOCOMPACT_BUFFER


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
