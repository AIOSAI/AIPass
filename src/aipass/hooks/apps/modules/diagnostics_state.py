# =================== AIPass ====================
# Name: diagnostics_state.py
# Version: 1.0.0
# Description: Post-edit diagnostics state — location, meaning, and live re-validation
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Owns what `.diagnostics_state.json` means.

auto_fix (PostToolUse) records the errors it found; edit_gate (PreToolUse) decides
whether they should stop the next edit. Both used to hardcode the path and their own
reading of the contents. This module is the single definition, so the writer and the
reader cannot drift apart.

Two rules live here, both reported by @seedgo with a live repro (2026-08-13):

1. A recorded error that can only be fixed in ANOTHER file must not stop edits to
   other files. Red-first is mandated fleet-wide and the test and the implementation
   are always in different files, so a gate that blocks the resolving edit is
   unsatisfiable by any allowed action.
2. A block must be a live fact, not a remembered one. Any resolving write the hook
   does not observe (a Bash heredoc, an external editor) leaves the state behind and
   the block outlives the error it describes.
"""

import json
import subprocess
import sys
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console
HELP_COMMANDS = [("diagnostics_state", "Show what the edit gate remembers, re-checked live")]

STATE_FILE = Path(__file__).parent.parent.parent.parent / ".diagnostics_state.json"

# Errors that, by definition, cannot be resolved inside the file that reports them:
# the symbol or the module has to appear somewhere else. Matched on message text
# because that is what auto_fix records — pyright's rule name is not stored, and
# would over-match anyway (reportAttributeAccessIssue also covers a genuine local
# typo on a local object, which IS fixable where it is reported).
_CROSS_FILE_SIGNATURES = (
    "is unknown import symbol",
    "could not be resolved",
)

_PYRIGHT_TIMEOUT_SECONDS = 15


def load() -> dict:
    """Return the recorded diagnostics state, or {} when there is none to read."""
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[HOOKS] diagnostics_state: unreadable, treating as empty: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def clear() -> None:
    """Delete the state file. Safe when it is already gone."""
    try:
        STATE_FILE.unlink(missing_ok=True)
    except OSError as exc:
        logger.info("[HOOKS] diagnostics_state: could not clear state: %s", exc)


def is_cross_file_error(error: dict) -> bool:
    """True when this error can only be resolved outside the file that reports it."""
    message = str(error.get("message", ""))
    return any(signature in message for signature in _CROSS_FILE_SIGNATURES)


def all_cross_file(errors: list) -> bool:
    """True when EVERY error resolves elsewhere, so blocking edits here helps nobody.

    Empty means "no errors to judge", not "all resolvable elsewhere" — an empty list
    returns False so a caller cannot read absence as permission.
    """
    if not errors:
        return False
    return all(is_cross_file_error(e) for e in errors)


def revalidate(file_path: str) -> list[dict] | None:
    """Re-run pyright on *file_path* and return its current errors.

    Returns [] when the file is clean now, a list of {line, message} when it is not,
    and None when the answer could not be established (pyright missing, timed out,
    unparseable, file gone). None means "unknown" and must never be read as "clean":
    a gate that cannot verify should fall back to what it already knows rather than
    invent a verdict.
    """
    if not Path(file_path).exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--outputjson", file_path],
            capture_output=True,
            text=True,
            timeout=_PYRIGHT_TIMEOUT_SECONDS,
        )
        data = json.loads(result.stdout)
    except FileNotFoundError:
        logger.info("[HOOKS] diagnostics_state: pyright not installed — cannot re-validate")
        return None
    except subprocess.TimeoutExpired:
        logger.info("[HOOKS] diagnostics_state: pyright timed out re-validating %s", file_path)
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.info("[HOOKS] diagnostics_state: pyright output unparseable: %s", exc)
        return None
    except Exception as exc:
        logger.info("[HOOKS] diagnostics_state: re-validation failed: %s", exc)
        return None

    errors: list[dict] = []
    for diag in data.get("generalDiagnostics", []):
        if diag.get("severity", "") != "error":
            continue
        line = diag.get("range", {}).get("start", {}).get("line", 0)
        errors.append({"line": line, "message": str(diag.get("message", "Unknown error"))[:100]})
    return errors[:10]


# =============================================================================
# MODULE INTERFACE (drone @hooks routing)
# =============================================================================


def print_introspection() -> None:
    """Show what the gate currently remembers, and whether it is still true."""
    CONSOLE.print("[bold cyan]diagnostics_state[/bold cyan] Module")
    CONSOLE.print(f"  State file: {STATE_FILE}")

    state = load()
    errors = state.get("errors", [])
    if not errors:
        CONSOLE.print("  Recorded: [green]nothing — no edit is being gated[/green]")
        return

    errored_file = state.get("file", "")
    CONSOLE.print(f"  Recorded: {len(errors)} error(s) in {Path(errored_file).name}")
    CONSOLE.print(f"  Resolvable only elsewhere: {all_cross_file(errors)}")

    fresh = revalidate(errored_file)
    if fresh is None:
        CONSOLE.print("  Live check: [yellow]could not verify[/yellow] — recorded errors stand")
    elif not fresh:
        CONSOLE.print("  Live check: [green]file is clean now — this state is stale[/green]")
    else:
        CONSOLE.print(f"  Live check: [red]{len(fresh)} error(s) still present[/red]")


def handle_command(command: str, args: list) -> bool:
    """Route diagnostics_state commands from drone @hooks."""
    if command in ("--help", "-h", "help"):
        CONSOLE.print("[bold cyan]diagnostics_state[/bold cyan] — what the edit gate remembers")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks diagnostics_state    Show recorded errors and re-check them live")
        return True

    if command == "diagnostics_state":
        if not args:
            print_introspection()
            return True
    return False
