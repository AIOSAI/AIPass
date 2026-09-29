# =================== AIPass ====================
# Name: diagnostics_state.py
# Version: 2.0.0
# Description: Post-edit diagnostics state per seat — location, meaning, and live re-validation
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-13
# Modified: 2026-09-28
# =============================================

"""Owns what the diagnostics state means: one file per seat since leg 4 (see load_seat).

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

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console
HELP_COMMANDS = [("diagnostics_state", "Show what the edit gate remembers, re-checked live")]

# One file per seat, named by a digest of the seat (hooks' choice, leg 4): no seat can
# lose another's write, and the age rule prunes whole files. Under the system temp, as
# the tripwire's and cadence's per-session files are. The version 1 file, one for every
# seat, is read by nobody and removed by the next write.
STATE_DIR = Path(tempfile.gettempdir()) / "aipass-diagnostics-state"
LEGACY_FILE = Path(__file__).parent.parent.parent.parent / ".diagnostics_state.json"
MAX_AGE_SECONDS = 24 * 60 * 60

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


def seat_key(hook_data: dict) -> str:
    """The seat a hook call belongs to: its session, and its agent id for a sub-agent.

    A payload without a session is one seat of its own, "nosession", as the tripwire
    keys it. The key is never written anywhere: _seat_file names the file by a digest.
    """
    session = str(hook_data.get("session_id") or "")
    if not session:
        return "nosession"
    agent = str(hook_data.get("agent_id") or "")
    return f"{session}/{agent}" if agent else session


def _now() -> float:
    """The clock the age rule reads.

    A seam: the tests are the reason it exists, so an entry of 25 hours is written
    without patching time process-wide. The decision is hooks', leg 4.
    """
    return time.time()


def _seat_file(seat: str) -> Path:
    return STATE_DIR / f"{hashlib.sha256(seat.encode('utf-8')).hexdigest()[:32]}.json"


def load_seat(seat: str) -> dict | None:
    """Return this seat's recorded errors as {"file", "errors"}, {} when it has none.

    What changed in leg 4 (devpulse's decision A): a seat is no longer refused for
    another seat's open error, and a seat whose own error a sibling's clean edit used to
    erase is refused again. Each seat reads its own file alone. The version 1 file shared
    by every seat is read as nobody's, and an entry older than 24 hours is ignored:
    sessions end without saying so. None means the seat's file could not be read (logged);
    the gate then refuses nothing, the side a broken state errs to.
    """
    return _read_seat_file(_seat_file(seat))


def _read_seat_file(path: Path) -> dict | None:
    """One seat file read by load_seat's rules: {} absent, stale or not version 2, None unreadable."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.info("[HOOKS] diagnostics_state: seat file unreadable: %s", exc)
        return None
    if not isinstance(data, dict) or data.get("version") != 2:
        return {}
    ts = data.get("ts")
    if not isinstance(ts, (int, float)) or _now() - ts > MAX_AGE_SECONDS:
        return {}
    return {"file": data.get("file", ""), "errors": data.get("errors", [])}


def save_seat(seat: str, file_path: str, errors: list[dict]) -> None:
    """Record this seat's errors whole: a temp file in the same directory, then a replace.

    Only this seat's file is written, so no seat's write can lose another's. The same
    write replaces the version 1 file and prunes seat files past the age rule. Never
    raises: a failed write is logged and leaves the seat unrefused.
    """
    temp_name = ""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"version": 2, "file": str(Path(file_path).resolve()), "errors": errors, "ts": _now()}
        fd, temp_name = tempfile.mkstemp(dir=STATE_DIR, prefix=".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temp_name, _seat_file(seat))
        temp_name = ""
        LEGACY_FILE.unlink(missing_ok=True)
        _prune()
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] diagnostics_state: seat state write failed: %s", exc)
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def clear_seat(seat: str) -> None:
    """Remove this seat's entry alone. Safe when it is already gone."""
    try:
        _seat_file(seat).unlink(missing_ok=True)
    except OSError as exc:
        logger.info("[HOOKS] diagnostics_state: could not clear seat state: %s", exc)


def _prune() -> None:
    """Remove seat files older than the age rule: their sessions ended without saying so."""
    cutoff = _now() - MAX_AGE_SECONDS
    for path in STATE_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError as exc:
            logger.info("[HOOKS] diagnostics_state: could not prune %s: %s", path.name, exc)


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
    """Show what the gate remembers for every seat, and whether it is still true.

    Seats are shown by the file they recorded, never by a session or agent id.
    """
    CONSOLE.print("[bold cyan]diagnostics_state[/bold cyan] Module")
    CONSOLE.print(f"  State directory: {STATE_DIR}")

    states = [_read_seat_file(path) for path in sorted(STATE_DIR.glob("*.json"))]
    recorded = [state for state in states if state and state.get("errors")]
    if not recorded:
        CONSOLE.print("  Recorded: [green]nothing — no edit is being gated[/green]")
        return

    for state in recorded:
        errors = state["errors"]
        errored_file = state.get("file", "")
        CONSOLE.print(f"  One seat recorded {len(errors)} error(s) in {Path(errored_file).name}")
        CONSOLE.print(f"    Resolvable only elsewhere: {all_cross_file(errors)}")

        fresh = revalidate(errored_file)
        if fresh is None:
            CONSOLE.print("    Live check: [yellow]could not verify[/yellow] — recorded errors stand")
        elif not fresh:
            CONSOLE.print("    Live check: [green]file is clean now — this state is stale[/green]")
        else:
            CONSOLE.print(f"    Live check: [red]{len(fresh)} error(s) still present[/red]")


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
