# =================== AIPass ====================
# Name: context_window.py
# Version: 1.0.0
# Description: Shared transcript-usage reader + per-branch compact-window resolver (DPLAN-0253)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""Reads live context fill from a session transcript and resolves the branch's
auto-compact window — shared by pre_compact_prep.py and context_gauge.py.

Live context size ≈ input_tokens + cache_read_input_tokens + cache_creation_input_tokens
of the most recent assistant turn (proven readable S326)."""

import json
import os
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

_DEFAULT_WINDOW = 200_000
_TAIL_BYTES = 50_000


def find_branch_dir(cwd: str) -> Path | None:
    """Resolve the branch root (src/aipass/<name>) from a cwd. Same walk as compact.py."""
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "aipass" and i > 0 and parts[i - 1] == "src":
            branch_dir = Path(*parts[: i + 2])
            if branch_dir.is_dir():
                return branch_dir
    if (Path(cwd) / ".trinity").is_dir():
        return Path(cwd)
    return None


def read_latest_usage(transcript_path: str, tail_bytes: int = _TAIL_BYTES) -> dict | None:
    """Tail a transcript JSONL and return the most recent assistant message's usage dict."""
    if not transcript_path:
        return None

    path = Path(transcript_path)
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
            chunk = fh.read()
    except OSError as exc:
        logger.info("[HOOKS] context_window: transcript read failed: %s", exc)
        return None

    lines = [ln for ln in chunk.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.info("[HOOKS] context_window: skipping unparsable transcript line: %s", exc)
            continue
        if entry.get("type") != "assistant":
            continue
        usage = entry.get("message", {}).get("usage")
        if isinstance(usage, dict):
            return usage
    return None


def context_fill_tokens(usage: dict) -> int:
    """Live context size ≈ input + cache_read + cache_creation of one turn."""
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def resolve_compact_window(cwd: str) -> int:
    """Resolve the auto-compact window: env var > branch settings.local.json > default.

    Mirrors CC's own precedence (env beats settings)."""
    env_window = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "")
    if env_window:
        try:
            return int(env_window)
        except ValueError:
            logger.info("[HOOKS] context_window: bad env window value %r", env_window)

    branch_dir = find_branch_dir(cwd)
    if branch_dir is not None:
        settings_path = branch_dir / ".claude" / "settings.local.json"
        if settings_path.is_file():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                window = data.get("autoCompactWindow")
                if isinstance(window, int) and window > 0:
                    return window
            except (json.JSONDecodeError, OSError) as exc:
                logger.info("[HOOKS] context_window: settings read failed: %s", exc)

    return _DEFAULT_WINDOW


# =============================================================================
# MODULE INTERFACE (drone @hooks routing)
# =============================================================================


def print_introspection() -> None:
    """Print context_window config and the resolved window for CWD."""
    CONSOLE.print("[bold cyan]context_window[/bold cyan] Module")
    CONSOLE.print(f"  Default window: {_DEFAULT_WINDOW:,}")
    CONSOLE.print(f"  Transcript tail read: {_TAIL_BYTES:,} bytes")
    window = resolve_compact_window(str(Path.cwd()))
    CONSOLE.print(f"  Resolved window (CWD): {window:,}")


def handle_command(command: str, args: list) -> bool:
    """Route context_window commands from drone @hooks."""
    if command in ("--help", "-h", "help"):
        CONSOLE.print("[bold cyan]context_window[/bold cyan] — Transcript usage + compact-window resolver")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks context_window    Show default window, tail size, resolved window for CWD")
        return True

    if command == "context_window":
        if not args:
            print_introspection()
            return True
    return False
