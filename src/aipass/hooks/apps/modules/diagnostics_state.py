# =================== AIPass ====================
# Name: diagnostics_state.py
# Version: 2.1.0
# Description: Post-edit diagnostics state per seat — location, meaning, and live re-validation
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Owns what the diagnostics state means: one file per seat since leg 4 (see load_seat).

A cross-file error must not block other files (red-first edits the test elsewhere), and a
block is re-checked live: a write the hook never saw (heredoc, editor) leaves stale state.
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

# One file per seat so no seat loses another's write; the shared version 1 file is removed on write.
STATE_DIR = Path(tempfile.gettempdir()) / "aipass-diagnostics-state"
LEGACY_FILE = Path(__file__).parent.parent.parent.parent / ".diagnostics_state.json"
MAX_AGE_SECONDS = 24 * 60 * 60

# Matched on message text: auto_fix stores no rule name, and reportAttributeAccessIssue
# would over-match a local typo that IS fixable where it is reported.
_CROSS_FILE_SIGNATURES = (
    "is unknown import symbol",
    "could not be resolved",
)

_PYRIGHT_TIMEOUT_SECONDS = 15


def seat_key(hook_data: dict) -> str:
    """The seat a hook call belongs to: its session, and its agent id for a sub-agent."""
    session = str(hook_data.get("session_id") or "")
    if not session:
        return "nosession"
    agent = str(hook_data.get("agent_id") or "")
    return f"{session}/{agent}" if agent else session


def _now() -> float:
    """The clock the age rule reads.

    A test seam: lets a 25-hour-old entry be written without patching time process-wide.
    """
    return time.time()


def _seat_file(seat: str) -> Path:
    return STATE_DIR / f"{hashlib.sha256(seat.encode('utf-8')).hexdigest()[:32]}.json"


def load_seat(seat: str) -> dict | None:
    """Return this seat's recorded errors as {"file", "errors"}, {} when it has none.

    None means unreadable (logged): the gate then refuses nothing, the side a broken state errs to.
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

    Never raises: a failed write is logged and leaves the seat unrefused.
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

    An empty list returns False so a caller cannot read absence as permission.
    """
    if not errors:
        return False
    return all(is_cross_file_error(e) for e in errors)


def of_the_tree(file_path: str, errors: list[dict] | None, base: int) -> list[dict] | None:
    """*errors* less those that are not diagnostics of the tree: a template's, or a placeholder line's.

    *base* is the checker's first line number: ruff 1, pyright 0.
    """
    if errors is None:
        return None
    if "templates" in Path(file_path).parts:
        return []
    try:
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        logger.info("[HOOKS] diagnostics_state: %s unreadable, its errors kept as found: %s", file_path, exc)
        return errors
    kept = []
    for error in errors:
        index = int(error.get("line", 0)) - base
        if 0 <= index < len(lines) and "{{" in lines[index]:
            continue
        kept.append(error)
    return kept


def pyright_cwd(file_path: str) -> str:
    """The directory pyright runs from for *file_path*: its project root, never the session's cwd.

    ``-m`` puts the cwd first on sys.path, so a stray ``types.py`` there breaks the interpreter.
    """
    start = Path(file_path).resolve().parent
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").is_file() or (candidate / "pyrightconfig.json").is_file():
            return str(candidate)
    return str(start)


def revalidate(file_path: str) -> list[dict] | None:
    """Re-run pyright on *file_path* and return its current errors.

    None means "unknown" (pyright missing, timed out, unparseable) and must never be read as clean.
    """
    if not Path(file_path).exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyright", "--outputjson", file_path],
            capture_output=True,
            text=True,
            timeout=_PYRIGHT_TIMEOUT_SECONDS,
            cwd=pyright_cwd(file_path),
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


def print_introspection() -> None:
    """Show what the gate remembers for every seat, and whether it is still true."""
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
