# =================== AIPass ====================
# Name: json_handler.py
# Description: JSON auto-creating handler for drone data files
# Version: 1.2.1
# Created: 2026-03-17
# Modified: 2026-08-31
# =============================================

"""JSON auto-creating handler for drone data files.

Provides log_operation() for structured operation logging and
ensure_json_file() for auto-creating branch-scoped JSON files.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger

from aipass.drone.apps.handlers.module_root import module_file

# ---------------------------------------------------------------------------
# Infrastructure — auto-detect branch root from file location
# json_handler.py -> json/ -> handlers/ -> apps/ -> drone/
# ---------------------------------------------------------------------------

_BRANCH_ROOT: Path = module_file(__file__).parents[3]
_BRANCH_NAME: str = _BRANCH_ROOT.name  # "drone"

# The real tree, captured once so an explicit patch can be told apart from it.
_IMPORT_TIME_JSON_DIR: Path = _BRANCH_ROOT / f"{_BRANCH_NAME}_json"

# Kept as a module attribute because ~20 tests across this suite redirect state
# with monkeypatch.setattr(json_handler, "JSON_DIR", ...). Reading it directly
# is what put 4189 write records in this branch's hygiene artifact, so the path
# builders go through _current_json_dir() instead.
JSON_DIR: Path = _IMPORT_TIME_JSON_DIR

# @prax's contract (2026-08-30), in @trigger's form. Adopted per branch in its
# OWN json_handler: five mocking techniques already existed and every one of
# them reaches nothing, so a sixth would be the problem rather than the fix.
_TEST_DIR_ENV_VAR = "AIPASS_TEST_LOG_DIR"


def _current_json_dir() -> Path:
    r"""Where JSON state belongs RIGHT NOW — resolved per call, never at import.

    Measured on this tree before this existed: under pytest the env var held a
    temp directory and the module constant STILL pointed at the live
    ``drone_json``. Something imports this module before the conftest that sets
    the variable runs, and a value captured at import cannot be redirected by
    anything afterwards. It is the same defect as the unmockable logger, and a
    seam that has to win an import race is not a seam.

    THE OVERRIDE TEST COMPARES AGAINST BOTH FIXED POINTS and holds nothing
    stale, which is @prax's corrected contract after @daemon's 9 pins went green
    alone and red in the full suite. A test that calls ``importlib.reload``
    while a monkeypatch is live has its teardown write the PRE-reload Path back
    onto the POST-reload module: same value, different object. An identity check
    then reports "explicitly patched" for the rest of the session and the
    redirect dies in a branch that looks adopted — measured here at 3757
    resolutions per suite run before this was fixed.

    Comparing by value against the real directory ALONE is not sufficient in
    general either: where a branch's import-time constant can itself be the
    redirect target, the written-back value and the post-reload default differ
    and value comparison reads "patched" too. Drone survives both orderings
    because ``_IMPORT_TIME_JSON_DIR`` is env-INDEPENDENT — it is always the real
    directory, never the redirect — and that precondition is load-bearing, so it
    is stated here rather than left to be rediscovered.

    An override therefore counts only when it differs from the real directory
    AND from the current redirect target. The cost, stated not hidden: patching
    the dir to either of those two is indistinguishable from not patching at
    all. Both resolve to the same path, so no answer changes.

    An EMPTY env value is absence, not a redirect. ``Path("") / "x"`` is
    relative, so honouring it would scatter state wherever the process happens
    to be standing.

    THE SECOND COMPARISON IS VALUE-NEUTRAL AND IS KEPT ANYWAY — @prax found this
    by mutating their own copy, and it reproduces here: dropping
    ``and current != default`` kills no test in this suite (1309 green with the
    mutant). It cannot, on POSIX. The only branch the two forms disagree on is
    ``current != real and current == default``, where one returns ``current``
    and the other ``default`` — and ``Path`` equality on POSIX means identical
    string parts, so the returned path is the same path. Untested by
    construction, not a gap in coverage.

    ONE ASYMMETRY MAKES KEEPING IT THE CHEAPER SIDE, and it is the reason this
    is not simply dead weight: ``PurePath.__eq__`` compares case-folded on
    Windows, so ``PureWindowsPath(r"C:\Temp\Drone_Json")`` equals
    ``PureWindowsPath(r"c:\temp\drone_json")`` while ``str()`` of the two
    differs. There, returning ``current`` instead of ``default`` yields the same
    FILE under a different string — invisible to a write, visible in a log line
    or in any assertion that compares paths as text. The clause also states the
    two-fixed-point rule that three trees now implement identically, which is
    worth more than removing a line that costs nothing.
    """
    real = _IMPORT_TIME_JSON_DIR
    test_dir = os.environ.get(_TEST_DIR_ENV_VAR)
    default = Path(test_dir) / _BRANCH_NAME / f"{_BRANCH_NAME}_json" if test_dir else real

    current = Path(JSON_DIR)
    if current != real and current != default:
        return current
    return default


_JSON_TYPES: tuple[str, ...] = ("config", "data", "log")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    """Return today's date as ISO string."""
    return datetime.now().date().isoformat()


def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack.

    Walks past internal frames ([0] = this function, [1] = public function,
    [2] = actual caller) and returns the stem of the caller's filename.

    Reads the frame directly rather than through ``inspect.stack()``. MEASURED
    2026-08-31 in the hostile world that emulates a Windows box with no working
    directory: ``inspect.stack()`` builds a ``FrameInfo`` per frame, and for any
    frame whose filename is a PSEUDO-file — ``<string>``, which every interpreter
    ``-c`` invocation and every exec'd hook puts on the stack — it reaches
    ``getmodule()``, whose ``os.path.realpath`` sits outside that function's
    every ``try``. The whole call then raises ``FileNotFoundError``, so
    ``log_operation`` — the audit line drone writes on essentially every
    operation — took the caller down from inside its own logging. On POSIX the
    equivalent raise happens earlier, where ``inspect`` catches it, which is why
    this stood on Linux for as long as it existed.

    ``FrameInfo.filename`` is ``getsourcefile(frame) or getfile(frame)``, and
    both fall back to ``co_filename`` for the frames this walk looks at, so the
    stem is the same string by a route that touches no filesystem at all.

    Returns:
        Module name (e.g. ``"flight_controller"`` from ``flight_controller.py``).
    """
    # Skip frames: [0]=this function, [1]=public wrapper, [2]=actual caller
    try:
        caller_frame = sys._getframe(2)
    except ValueError:
        # Fewer than three frames — the old form's `len(stack) > 2` guard.
        return "unknown"

    module_name = Path(caller_frame.f_code.co_filename).stem
    if module_name and not module_name.startswith("_"):
        return module_name
    return "unknown"


# os.replace on Windows raises PermissionError while ANY reader holds the
# target open (no FILE_SHARE_DELETE on Python's open). Readers hold handles
# for microseconds, so a short bounded retry converges; after the bound the
# error raises honestly. POSIX never takes this path for open files, so a
# genuine permission problem still surfaces — just ~200ms later.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005


def _replace_with_retry(source: str, destination: str) -> None:
    """
    os.replace that tolerates Windows sharing violations, bounded.

    Args:
        source: Staged file to move into place.
        destination: The live document being replaced.

    Raises:
        PermissionError: Still blocked after every attempt.
        OSError: Any non-sharing failure, immediately.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically — write to temp file then rename.

    Prevents truncation/corruption during concurrent access. The rename goes
    through _replace_with_retry: on Windows a reader holding the target open
    turns the move into a PermissionError, and one stuck move starved a whole
    CI run (2026-08-18). Bounded, then it raises honestly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".json_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        _replace_with_retry(tmp_path, str(path))
    except BaseException as exc:
        logger.warning("_atomic_write_json: failed for %s: %s", path, exc)
        # Clean up temp file on failure — BaseException covers KeyboardInterrupt
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_exc:
            logger.warning("_atomic_write_json: cleanup failed for %s: %s", tmp_path, cleanup_exc)
        raise


def _default_config(module_name: str) -> dict[str, Any]:
    """Return inline default for a *_config.json file."""
    today = _today()
    return {
        "module_name": module_name,
        "version": "1.0.0",
        "config": {
            "max_log_entries": 100,
        },
        "created": today,
        "last_updated": today,
    }


def _default_data(module_name: str) -> dict[str, Any]:
    """Return inline default for a *_data.json file."""
    today = _today()
    return {
        "created": today,
        "last_updated": today,
    }


def _default_log(module_name: str) -> list[Any]:  # noqa: ARG001
    """Return inline default for a *_log.json file."""
    return []


_DEFAULTS: dict[str, Any] = {
    "config": _default_config,
    "data": _default_data,
    "log": _default_log,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_json_structure(data: Any, json_type: str) -> bool:
    """Validate that *data* matches the expected shape for *json_type*.

    Args:
        data: Parsed JSON data to validate.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        ``True`` when the structure is valid, ``False`` otherwise.
    """
    if json_type == "config":
        if not isinstance(data, dict):
            return False
        required = ("module_name", "version", "config")
        return all(key in data for key in required)

    if json_type == "data":
        if not isinstance(data, dict):
            return False
        required = ("created", "last_updated")
        return all(key in data for key in required)

    if json_type == "log":
        return isinstance(data, list)

    return False


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def get_json_path(module_name: str, json_type: str) -> Path:
    """Return the filesystem path for *module_name*'s JSON of *json_type*.

    Args:
        module_name: Logical module name (e.g. ``"flight_controller"``).
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        Absolute :class:`~pathlib.Path` to the JSON file.
    """
    return _current_json_dir() / f"{module_name}_{json_type}.json"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure a single JSON file exists; create with inline defaults if missing.

    If the file exists but fails validation it is regenerated.

    Args:
        module_name: Logical module name.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        ``True`` after the file is confirmed present and valid.
    """
    _current_json_dir().mkdir(parents=True, exist_ok=True)
    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            # Guard: empty or zero-byte files cause JSONDecodeError
            if json_path.stat().st_size == 0:
                logger.warning("ensure_json_exists: empty file at %s, regenerating", json_path)
            else:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if validate_json_structure(data, json_type):
                    return True
                # Corrupted — fall through to regenerate
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_json_exists: failed to read %s, regenerating: %s", json_path, exc)

    # Create from inline default
    factory = _DEFAULTS.get(json_type)
    if factory is None:
        raise ValueError(f"Unknown json_type: {json_type!r}")

    default = factory(module_name)
    _atomic_write_json(json_path, default)

    return True


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all three JSON files (config, data, log) exist for *module_name*.

    Args:
        module_name: Logical module name.

    Returns:
        ``True`` when all files are present and valid.
    """
    for json_type in _JSON_TYPES:
        ensure_json_exists(module_name, json_type)
    return True


def load_json(module_name: str, json_type: str) -> Any | None:
    """Load a module's JSON file, auto-creating it if missing.

    Args:
        module_name: Logical module name.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.

    Returns:
        Parsed JSON data, or ``None`` on failure.
    """
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)
    try:
        if json_path.stat().st_size == 0:
            logger.warning("load_json: empty file at %s, returning default", json_path)
            factory = _DEFAULTS.get(json_type)
            return factory(module_name) if factory else None
        with open(json_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("load_json: failed to read %s, returning default: %s", json_path, exc)
        factory = _DEFAULTS.get(json_type)
        return factory(module_name) if factory else None


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Write *data* to the module's JSON file after validation.

    For ``"data"`` type files the ``last_updated`` field is refreshed
    automatically.

    Args:
        module_name: Logical module name.
        json_type: One of ``"config"``, ``"data"``, ``"log"``.
        data: The data structure to persist.

    Returns:
        ``True`` on success.

    Raises:
        ValueError: When *data* fails structure validation.
    """
    if not validate_json_structure(data, json_type):
        raise ValueError(f"Invalid structure for {json_type} JSON")

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = _today()

    json_path = get_json_path(module_name, json_type)
    _atomic_write_json(json_path, data)
    return True


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


def log_operation(
    operation: str,
    data: dict[str, Any] | None = None,
    module_name: str | None = None,
) -> bool:
    """Append an entry to a module's log with automatic FIFO rotation.

    Auto-detects the calling module when *module_name* is not supplied.
    Reads ``max_log_entries`` from the module's config (default 100) and
    trims oldest entries when the limit is exceeded.

    Args:
        operation: Short label for the logged action.
        data: Optional payload dict attached to the log entry.
        module_name: Explicit module name; auto-detected from stack if ``None``.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    if module_name is None:
        module_name = _get_caller_module_name()

    try:
        ensure_module_jsons(module_name)

        # Read rotation limit from config
        config = load_json(module_name, "config")
        max_entries = 100
        if config and "config" in config:
            max_entries = config["config"].get("max_log_entries", 100)

        # Load existing log
        log = load_json(module_name, "log")
        if log is None:
            log = []

        # Build entry
        entry: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
        }
        if data:
            entry["data"] = data

        log.append(entry)

        # FIFO rotation — keep only the most recent entries
        if len(log) > max_entries:
            log = log[-max_entries:]

        return save_json(module_name, "log", log)
    except Exception as exc:
        logger.warning("log_operation: failed for %s/%s, skipping: %s", module_name, operation, exc)
        return False


def increment_counter(
    module_name: str,
    counter_name: str,
    amount: int = 1,
) -> bool:
    """Increment a named counter in a module's data JSON.

    Creates the counter initialised to ``0`` if it does not yet exist.

    Args:
        module_name: Logical module name.
        counter_name: Key within the data dict.
        amount: Value to add (default ``1``).

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    if counter_name not in data:
        data[counter_name] = 0

    data[counter_name] += amount
    return save_json(module_name, "data", data)


def update_data_metrics(module_name: str, **metrics: Any) -> bool:
    """Merge arbitrary key/value pairs into a module's data JSON.

    Args:
        module_name: Logical module name.
        **metrics: Keyword arguments written directly into the data dict.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    ensure_module_jsons(module_name)

    data = load_json(module_name, "data")
    if data is None:
        return False

    for key, value in metrics.items():
        data[key] = value

    return save_json(module_name, "data", data)


# ---------------------------------------------------------------------------
# __all__ — controls `from .json_handler import *`
# ---------------------------------------------------------------------------

__all__ = [
    "JSON_DIR",
    "ensure_json_exists",
    "ensure_module_jsons",
    "get_json_path",
    "increment_counter",
    "load_json",
    "log_operation",
    "save_json",
    "update_data_metrics",
    "validate_json_structure",
]


# ---------------------------------------------------------------------------
# Quick smoke-test when run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]JSON HANDLER (drone) — Smoke Test[/bold cyan]",
            border_style="bright_blue",
        )
    )
    console.print()
    console.print(f"[dim]Branch root:[/dim]  {_BRANCH_ROOT}")
    console.print(f"[dim]JSON dir:[/dim]     {_current_json_dir()}")
    console.print()

    console.print("[yellow]TESTING:[/yellow] Creating drone JSONs...")
    log_operation("smoke_test", {"status": "ok"}, "drone")
    increment_counter("drone", "smoke_runs", 1)
    update_data_metrics("drone", smoke_metric="working")

    console.print()
    console.print("[green]Check drone/drone_json/ for created files:[/green]")
    for jt in _JSON_TYPES:
        console.print(f"  [dim]>[/dim] drone_{jt}.json")
    console.print()
