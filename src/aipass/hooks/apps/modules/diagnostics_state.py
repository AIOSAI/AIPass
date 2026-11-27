# =================== AIPass ====================
# Name: diagnostics_state.py
# Version: 2.5.2
# Description: Post-edit diagnostics state per seat — location, meaning, and live re-validation
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-13
# Modified: 2026-11-26
# =============================================

"""Owns what the diagnostics state means: one file per seat since leg 4 (see load_seat).

A cross-file error must not block other files (red-first edits the test elsewhere), and a
block is re-checked live: a write the hook never saw (heredoc, editor) leaves stale state.
"""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from aipass.cli import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax import logger

CONSOLE = err_console
HELP_COMMANDS = [("diagnostics_state", "Show what the edit gate remembers, re-checked live")]

# One file per seat so no seat loses another's write.
STATE_DIR = Path(tempfile.gettempdir()) / "aipass-diagnostics-state"
MAX_AGE_SECONDS = 24 * 60 * 60

# A name missing from ANOTHER module is cross-file. Matched on text: auto_fix stores no rule name,
# and all of reportAttributeAccessIssue would take in a typo on a local attribute, fixable here.
_CROSS_FILE_SIGNATURES = (
    "is unknown import symbol",
    "could not be resolved",
    "is not a known attribute of module",
    'for class "ModuleType"',
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


def _lock_dir() -> Path:
    """Beside STATE_DIR, never in it: a lock file is no seat record."""
    return STATE_DIR.with_name(STATE_DIR.name + ".locks")


def _still_named(fd: int, path: Path) -> bool:
    try:
        return os.stat(path).st_ino == os.fstat(fd).st_ino
    except FileNotFoundError:
        return False


@contextmanager
def _locked(name: str, wait: bool = True) -> Iterator[None]:
    """flock on lock *name* across read, decide, write; a waiter woken on a pruned inode reopens the name."""
    lock = _lock_dir() / f"{name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    while True:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise
        if _still_named(fd, lock):
            break
        os.close(fd)
    try:
        yield
    finally:
        os.close(fd)


def load_seat(seat: str) -> dict:
    """Return this seat's recorded errors as {"file", "errors"}, {} when it has none or its file was damaged.

    A damaged file is set aside and logged at ERROR. Any OSError but absence raises: edit_gate's
    fail-closed catch refuses with it.
    """
    with _locked(_seat_file(seat).stem):
        return _read_seat_file(_seat_file(seat))


def _damage(data: object) -> str:
    """Why a record is damage, not stale, "" if sound: save_seat only writes v2, str file, list, numeric ts."""
    if not isinstance(data, dict) or data.get("version") != 2:
        return "not a version 2 record"
    if not isinstance(data.get("file"), str) or not isinstance(data.get("errors"), list):
        return "wrong shape"
    ts = data.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts > _now() + MAX_AGE_SECONDS:
        return "no usable timestamp"
    return ""


def _read_seat_file(path: Path) -> dict:
    """One seat file, read under its lock: {} absent or stale, damage set aside as {}, the record else."""
    raw = _bytes(path)
    if raw is None:
        return {}
    data, damage = _parse(raw)
    damage = damage or _damage(data)
    if damage:
        return _set_aside(path, damage)
    if _now() - data["ts"] > MAX_AGE_SECONDS:
        return {}
    return {"file": data["file"], "errors": data["errors"]}


def _bytes(path: Path) -> bytes | None:
    """The file's bytes, or None when it is absent; any other OSError raises."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _parse(raw: bytes) -> tuple[Any, str]:
    """(the parsed value, "") or (None, why it is no JSON)."""
    try:
        return json.loads(raw), ""
    except ValueError as exc:
        return None, f"not JSON ({type(exc).__name__})"


def _set_aside(path: Path, why: str) -> dict:
    """Quarantine, under the lock: renamed beside, never unlinked; ERROR once, as the name is then absent."""
    logger.error("[hooks] diagnostics_state: a damaged seat file is set aside, the seat reads empty: %s", why)
    aside = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
    os.replace(path, aside)
    os.utime(aside)
    logger.info("[hooks] diagnostics_state: set aside as %s", aside)
    return {}


def save_seat(seat: str, file_path: str, errors: list[dict]) -> None:
    """Record this seat's errors whole under its lock (temp file, replace); a failure logs ERROR, never raises."""
    temp_name = ""
    try:
        with _locked(_seat_file(seat).stem):
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {"version": 2, "file": str(Path(file_path).resolve()), "errors": errors, "ts": _now()}
            fd, temp_name = tempfile.mkstemp(dir=STATE_DIR, prefix=".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(temp_name, _seat_file(seat))
            temp_name = ""
        _prune()
    except (OSError, ValueError) as exc:
        logger.error("[hooks] diagnostics_state: seat state write failed: %s", exc)
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
    json_handler.log_operation("save_seat", {"seat": seat, "errors": len(errors)})


def clear_seat(seat: str, when: Callable[[dict], bool] | None = None) -> None:
    """Remove this seat's entry alone, if *when* (asked under the lock, on the record as it stands) agrees.

    A save from a parallel tool call after the caller's own read is never removed on that stale read.
    """
    try:
        with _locked(_seat_file(seat).stem):
            path = _seat_file(seat)
            if when is None or when(_read_seat_file(path)):
                path.unlink(missing_ok=True)
    except OSError as exc:
        logger.error("[hooks] diagnostics_state: could not clear seat state: %s", exc)


def _older(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff
    except FileNotFoundError:
        return False


def _prune() -> None:
    """Age out seat files, set-aside copies and idle locks, each under its lock taken without waiting."""
    cutoff = _now() - MAX_AGE_SECONDS
    found = [*STATE_DIR.glob("*.json*"), *_lock_dir().glob("*.lock")]
    for path in [path for path in found if _older(path, cutoff)]:
        try:
            with _locked(path.name.split(".")[0], wait=False):
                if _older(path, cutoff):
                    path.unlink(missing_ok=True)
        except BlockingIOError:
            logger.warning("[hooks] diagnostics_state: %s is in use, kept for the next prune", path.name)
        except OSError as exc:
            logger.warning("[hooks] diagnostics_state: could not prune %s: %s", path.name, exc)


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
        logger.info("[hooks] diagnostics_state: %s unreadable, its errors kept as found: %s", file_path, exc)
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
        logger.warning("[hooks] diagnostics_state: pyright not installed — cannot re-validate")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("[hooks] diagnostics_state: pyright timed out re-validating %s", file_path)
        return None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("[hooks] diagnostics_state: pyright output unparseable: %s", exc)
        return None
    except Exception as exc:
        logger.warning("[hooks] diagnostics_state: re-validation failed: %s", exc)
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
    CONSOLE.print("[dim]What the edit gate remembers of each seat's type errors, re-checked live.[/dim]")
    CONSOLE.print(f"  State directory: {STATE_DIR}")

    states = [_read_seat_file(path) for path in sorted(STATE_DIR.glob("*.json"))]
    recorded = [state for state in states if state and state.get("errors")]
    if not recorded:
        CONSOLE.print("  Recorded: [green]nothing — no edit is being gated[/green]")
        CONSOLE.print("[dim]Run drone @hooks diagnostics_state --help for usage.[/dim]")
        return

    for state in recorded:
        errors = state["errors"]
        errored_file = state.get("file", "")
        CONSOLE.print(f"  One seat recorded {len(errors)} error(s) in {Path(errored_file).name}", highlight=False)
        CONSOLE.print(f"    Resolvable only elsewhere: {all_cross_file(errors)}")

        fresh = revalidate(errored_file)
        if fresh is None:
            CONSOLE.print("    Live check: [yellow]could not verify[/yellow] — recorded errors stand")
        elif not fresh:
            CONSOLE.print("    Live check: [green]file is clean now — this state is stale[/green]")
        else:
            CONSOLE.print(f"    Live check: [red]{len(fresh)} error(s) still present[/red]")
    CONSOLE.print("[dim]Run drone @hooks diagnostics_state --help for usage.[/dim]")


def print_help() -> None:
    """Print the diagnostics_state verb's usage and examples."""
    CONSOLE.print("[bold cyan]diagnostics_state[/bold cyan] — what the edit gate remembers")
    CONSOLE.print()
    CONSOLE.print("[bold]Usage:[/bold]")
    CONSOLE.print("  [cyan]drone @hooks diagnostics_state[/cyan]    Show recorded errors and re-check them live")
    CONSOLE.print()
    CONSOLE.print("[bold]Examples:[/bold]")
    CONSOLE.print("  [cyan]drone @hooks diagnostics_state[/cyan]")


def handle_command(command: str, args: list) -> bool:
    """Route diagnostics_state commands from drone @hooks."""
    if command in ("--help", "-h", "help") or (command == "diagnostics_state" and wants_help(args)):
        print_help()
        return True

    if command == "diagnostics_state":
        if not args:
            print_introspection()
            return True
    return False
