# =================== AIPass ====================
# Name: json_service.py
# Description: The fleet's one JSON handler service (prax-owned)
# Version: 2.5.0
# Created: 2026-09-03
# Modified: 2026-11-18
# =============================================

"""The fleet's one JSON handler implementation (DPLAN-0325).

Reference: docs/json_service.md
"""

import fcntl
import itertools
import json
import os
import stat
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from aipass.prax.apps.handlers.logging.trail import PraxTrail
from aipass.prax.apps.handlers.state_root import StateRootUnwritable, branch_root, state_root_of, writable_dir

# The trail, never door one: every branch's logger build reaches this service.
logger = PraxTrail("json_service")

JSON_TYPES = ("config", "data", "log")
DEFAULT_MAX_LOG_ENTRIES = 100

_NEW_DOCUMENT_MODE = 0o666  # what open(path, "w") asks for: the umask narrows it to this process's usual mode

_STAGE_NAME_ATTEMPTS = 8
_ORPHAN_AGE_SECONDS = 3600

# pid + counter, never the clock: callers stub this module's `time` to skip the retry sleep.
_stage_serial = itertools.count()

# An uncontended log_operation costs ~1.3 ms: 2 s is some 1500 queued writers; only a frozen holder outlasts it.
LOCK_DEADLINE_SECONDS = 2.0


class InvalidDocument(ValueError):
    """A document that does not match the structure its json_type declares."""


class WriteFailed(OSError):
    """The write could not land: retry exhausted, or an OSError on the way."""


class LockTimeout(TimeoutError):
    """A live holder kept a module's trail lock past the deadline."""


def _default_document(json_type: str, module_name: str) -> Any:
    """The in-code default document for a json_type: a default in a file can go missing."""
    today = datetime.now().date().isoformat()

    if json_type == "config":
        return {
            "module_name": module_name,
            "version": "1.0.0",
            "config": {"max_log_entries": DEFAULT_MAX_LOG_ENTRIES},
            "created": today,
            "last_updated": today,
        }

    if json_type == "data":
        return {"created": today, "last_updated": today}

    return []


def _current_mode(file_path: Path) -> Optional[int]:
    """The document's own permission bits, or None when there is no document yet."""
    try:
        return stat.S_IMODE(os.stat(file_path).st_mode)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning(
            "json_service: cannot read the current mode — writing it as a new document",
            path=str(file_path),
            error=str(exc),
        )
        return None


def _stage(directory: Path, content: str, mode: Optional[int] = None) -> str:
    """Write content to a temp file beside the target and return its path.

    Beside the target: os.replace is atomic only within one filesystem. os.open, not
    NamedTemporaryFile: tempfile creates 0600 and os.replace carries that mode onto the target.
    """
    _sweep_orphans(directory)
    fd = -1
    temp_path = ""
    for attempt in range(_STAGE_NAME_ATTEMPTS):
        temp_path = str(directory / f".{os.getpid()}_{next(_stage_serial)}.tmp")
        try:
            fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _NEW_DOCUMENT_MODE)
            break
        except FileExistsError:
            if attempt == _STAGE_NAME_ATTEMPTS - 1:
                raise

    try:
        # fchmod on the fd, not chmod on the path: no second lookup to redirect.
        if mode is not None:
            os.fchmod(fd, mode)
        staged = open(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        _discard(temp_path)
        raise

    try:
        with staged:
            staged.write(content)
            staged.flush()
            os.fsync(staged.fileno())
    except BaseException:
        _discard(temp_path)
        raise

    return temp_path


def _sweep_orphans(directory: Path) -> None:
    """Best effort: remove staged files a killed writer left behind over an hour ago."""
    # datetime, not time: callers stub this module's `time`.
    cutoff = datetime.now().timestamp() - _ORPHAN_AGE_SECONDS
    try:
        for orphan in directory.glob(".[0-9]*_[0-9]*.tmp"):
            try:
                if orphan.stat().st_mtime < cutoff:
                    orphan.unlink()
            except OSError as exc:
                logger.info("json_service: orphan sweep skipped a file", path=str(orphan), error=str(exc))
    except OSError as exc:
        logger.info("json_service: orphan sweep failed", path=str(directory), error=str(exc))


def _discard(temp_path: str) -> None:
    """Remove a staged file that never landed. Litter accumulates silently."""
    if not temp_path:
        return
    try:
        os.unlink(temp_path)
    except OSError as exc:
        logger.warning("json_service: temp cleanup failed", path=temp_path, error=str(exc))


def _acquire(lock_path: Path, deadline: float) -> int:
    """An fd holding the exclusive flock on lock_path; LockTimeout when a live holder keeps it past the deadline.

    The kernel drops a dead holder's lock, so the file on disk is never stale and never inspected.
    """
    writable_dir(lock_path.parent)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, _NEW_DOCUMENT_MODE)

    # The kernel's blocking flock is the queue; it runs on a helper thread so the wait can have a deadline.
    outcome = {"won": False, "abandoned": False}
    guard = threading.Lock()
    settled = threading.Event()

    def wait_turn() -> None:
        """Take the lock in turn, then hand it to the waiter, or let it go if the waiter gave up."""
        acquired = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            acquired = True
        finally:
            with guard:
                outcome["won"] = acquired and not outcome["abandoned"]
                if not outcome["won"]:
                    os.close(fd)
            settled.set()

    # shortcut: a timed-out waiter's thread stays parked in flock until the frozen holder lets go or dies.
    threading.Thread(target=wait_turn, name="json_service-lock-wait", daemon=True).start()
    settled.wait(deadline)
    with guard:
        if outcome["won"]:
            return fd
        outcome["abandoned"] = True
    raise LockTimeout(f"lock not acquired within {deadline} seconds")


def _get_caller_module_name() -> str:
    """Name the module that called ``log_operation``, or "unknown" when no module is behind the frame.

    Frame depth 2 is exact: the branch shim BINDS log_operation and never wraps it, or every entry is renamed.
    sys._getframe, never inspect.stack(): inspect resolves every frame's file, and a relative one reads os.getcwd().
    """
    try:
        caller_frame = sys._getframe(2)
    except ValueError:
        return "unknown"

    # A pseudo-frame (<stdin>, <string>, <frozen ...>) has no module behind it.
    filename = caller_frame.f_code.co_filename
    if filename.startswith("<") and filename.endswith(">"):
        return "unknown"

    module_name = Path(filename).stem
    if module_name and not module_name.startswith("_"):
        return module_name

    return "unknown"


# flock is per open file: a thread taking a lock it already holds would wait on itself until the deadline.
_held_locks = threading.local()


class LockReentry(LockTimeout):
    """The calling thread already holds this module's lock: refused at once, never a wait on itself."""


def _take(lock_path: Path) -> int:
    """An fd holding a module's lock; LockReentry when this thread already holds it, LockTimeout past the deadline."""
    held = _held_locks.__dict__.setdefault("paths", set())
    if lock_path in held:
        raise LockReentry(f"{lock_path.name} is already held by this thread: re-entry refused")
    fd = _acquire(lock_path, LOCK_DEADLINE_SECONDS)
    held.add(lock_path)
    return fd


def _give(lock_path: Path, fd: int) -> None:
    """Release a lock _take handed out."""
    _held_locks.paths.discard(lock_path)
    os.close(fd)


def for_module(file: "str | os.PathLike") -> "JsonHandle":
    """Build the handle for the branch that owns ``file``.

    ``parents[3]`` is the branch root; no resolve(), which would follow a symlink to the wrong branch.
    """
    return JsonHandle(Path(file).parents[3])


def for_branch(name: str) -> "JsonHandle":
    """Build the handle for the branch named ``name``, found by its package, wherever the caller's file runs from.

    A name that is not an AIPass branch (no package, or no apps/ in it) raises LookupError: no default branch.
    """
    root = branch_root(name) if name.isidentifier() else None
    if root is None or not (root / "apps").is_dir():
        raise LookupError(f"no AIPass branch named {name!r}")
    return JsonHandle(root)


class JsonHandle:
    """One branch's bound view of the json service."""

    def __init__(self, branch_root: Path):
        self.branch_root = branch_root

    @property
    def json_dir(self) -> Path:
        """The branch's json directory in its state folder, per access so AIPASS_TEST_LOG_DIR redirects."""
        return state_root_of(self.branch_root) / f"{self.branch_root.name}_json"

    def read_json(self, file_path: Path) -> Optional[Any]:
        """Read any json document by path; None when missing or unreadable, never raises."""
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("json_service: unreadable document", path=str(file_path), error=str(exc))
            return None

    def write_json(self, file_path: Path, data: Any, indent: int = 2) -> bool:
        """Write any json document by path, atomically; False on any OSError.

        Serialises before staging, so TypeError/ValueError (a caller bug) propagate. allow_nan=False:
        NaN/Infinity are not JSON and every strict parser rejects them later, far from the writer.
        """
        file_path = Path(file_path)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("json_service: cannot create the directory", path=str(file_path.parent), error=str(exc))
            return False

        content = json.dumps(data, indent=indent, ensure_ascii=False, allow_nan=False)

        temp_path = ""
        try:
            temp_path = _stage(file_path.parent, content, _current_mode(file_path))
            os.replace(temp_path, str(file_path))
            return True
        except OSError as exc:
            logger.warning("json_service: write failed", path=str(file_path), error=str(exc))
            _discard(temp_path)
            return False

    def validate_json_structure(self, data: Any, json_type: str) -> bool:
        """Check a document against the structure its json_type declares."""
        if json_type == "config":
            if not isinstance(data, dict):
                return False
            return all(key in data for key in ("module_name", "version", "config"))

        if json_type == "data":
            if not isinstance(data, dict):
                return False
            return all(key in data for key in ("created", "last_updated"))

        if json_type == "log":
            return isinstance(data, list)

        return False

    def get_json_path(self, module_name: str, json_type: str) -> Path:
        """Path of a module's typed document; ValueError on an unknown json_type, never a document nothing reads."""
        if json_type not in JSON_TYPES:
            raise ValueError(f"Unknown json_type '{json_type}' (expected one of {JSON_TYPES})")

        return self.json_dir / f"{module_name}_{json_type}.json"

    def ensure_json_exists(self, module_name: str, json_type: str) -> bool:
        """Create a module's typed document if absent; InvalidDocument if it exists unreadable or misshaped.

        A dict "data" document missing base keys is healed in place, never replaced: other writers share it.
        """
        json_path = self.get_json_path(module_name, json_type)

        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("json_service: cannot create the directory", path=str(json_path.parent), error=str(exc))
            return False

        existing = self.read_json(json_path)
        if existing is not None and self.validate_json_structure(existing, json_type):
            return True

        if json_type == "data" and isinstance(existing, dict):
            for key, value in _default_document(json_type, module_name).items():
                existing.setdefault(key, value)
            try:
                return self.write_json(json_path, existing)
            except (TypeError, ValueError) as exc:
                # json.load accepts NaN the writer refuses; the heal never destroys keys to write.
                logger.warning(
                    "json_service: cannot heal the document without losing its keys",
                    path=str(json_path),
                    error=str(exc),
                )
                return False

        if existing is not None or json_path.exists():
            raise InvalidDocument(f"{json_path}: unreadable or misshaped, not overwritten")

        return self.write_json(json_path, _default_document(json_type, module_name))

    def ensure_module_jsons(self, module_name: str) -> bool:
        """Ensure all three typed documents exist for a module."""
        for json_type in JSON_TYPES:
            self.ensure_json_exists(module_name, json_type)
        return True

    def load_json(self, module_name: str, json_type: str) -> Optional[Any]:
        """Load a module's typed document, creating it if absent; InvalidDocument if unreadable or misshaped."""
        self.ensure_json_exists(module_name, json_type)

        json_path = self.get_json_path(module_name, json_type)
        data = self.read_json(json_path)
        if data is None:
            raise InvalidDocument(f"{json_path}: unreadable after ensure")

        return data

    def save_json(self, module_name: str, json_type: str, data: Any) -> bool:
        """Save a module's typed document: True or raises (InvalidDocument, WriteFailed), never False."""
        json_path = self.get_json_path(module_name, json_type)

        if not self.validate_json_structure(data, json_type):
            raise InvalidDocument(
                f"Document for '{module_name}/{json_type}' does not match the '{json_type}' structure"
            )

        if json_type == "data" and isinstance(data, dict):
            data["last_updated"] = datetime.now().date().isoformat()

        if not self.write_json(json_path, data):
            raise WriteFailed(f"Could not write '{json_path}'")

        return True

    def update_json(self, module_name: str, json_type: str, fn: Callable[[Any], Any]) -> bool:
        """Read-modify-write a module's typed document under log_operation's lock: True or raises.

        fn takes the document and returns the one to write; if fn raises, nothing is written. A missing
        document starts from the in-code default. A corrupt or misshaped one is moved aside to
        <name>.corrupt-<stamp>, logged at ERROR and refused, so the next call starts from the default.
        A lock not acquired (LockTimeout, or LockReentry when fn asks for this module's lock again) is
        logged at ERROR and raised, nothing written.
        """
        lock_path = self.json_dir / f"{module_name}.lock"
        try:
            lock_fd = _take(lock_path)
        except LockTimeout as exc:
            logger.error(
                "json_service: update_json lock not acquired",
                module=module_name,
                path=str(lock_path),
                error=str(exc),
            )
            raise
        try:
            document = self._load_or_set_aside(module_name, json_type)
            return self.save_json(module_name, json_type, fn(document))
        finally:
            _give(lock_path, lock_fd)

    def _load_or_set_aside(self, module_name: str, json_type: str) -> Any:
        """load_json, except that a corrupt or misshaped document is set aside, logged at ERROR and refused."""
        try:
            return self.load_json(module_name, json_type)
        except InvalidDocument as exc:
            json_path = self.get_json_path(module_name, json_type)
            logger.error(
                "json_service: update_json refused a corrupt document",
                module=module_name,
                path=str(json_path),
                kept=self._set_aside(json_path),
                error=str(exc),
            )
            raise

    def _set_aside(self, json_path: Path) -> str:
        """Move a refused document to <name>.corrupt-<stamp> beside it; one that cannot be read may be whole, so stays."""
        try:
            json_path.read_bytes()
            kept = json_path.with_name(f"{json_path.name}.corrupt-{datetime.now():%Y%m%dT%H%M%S%f}")
            os.replace(json_path, kept)
        except OSError as exc:
            logger.warning("json_service: a refused document stays where it is", path=str(json_path), error=str(exc))
            return f"left in place: {exc}"
        return str(kept)

    def log_operation(
        self,
        operation: str,
        data: Optional[Dict[str, Any]] = None,
        module_name: Optional[str] = None,
    ) -> bool:
        """Append a timestamped entry to a module's operations log, then bump its data document.

        One exclusive lock per module holds the whole read-modify-write: writers queue and none is lost.
        Telemetry on watchdog and display threads: a failure answers False, never raises, save one case:
        a state folder that cannot be written raises StateRootUnwritable, naming it and the errno. A misshaped
        document on disk, or a lock not acquired (a live holder past the deadline, or this thread
        already holding it), is logged at ERROR.
        """
        if module_name is None:
            module_name = _get_caller_module_name()

        lock_path = self.json_dir / f"{module_name}.lock"
        try:
            lock_fd = _take(lock_path)
            try:
                self.ensure_module_jsons(module_name)

                log = self.load_json(module_name, "log")
                if not isinstance(log, list):
                    log = []

                entry: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}
                if data:
                    entry["data"] = data
                log.append(entry)

                max_entries = self._max_log_entries(module_name)
                if len(log) > max_entries:
                    log = log[-max_entries:]

                logged = self.save_json(module_name, "log", log)
                self._bump_data(module_name, operation)
            finally:
                _give(lock_path, lock_fd)
        except StateRootUnwritable:
            raise
        except LockTimeout as exc:
            logger.error(
                "json_service: log_operation lock not acquired",
                operation=operation,
                module=module_name,
                path=str(lock_path),
                error=str(exc),
            )
            return False
        except InvalidDocument as exc:
            logger.error("json_service: log_operation refused", operation=operation, module=module_name, error=str(exc))
            return False
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "json_service: log_operation failed", operation=operation, module=module_name, error=str(exc)
            )
            return False

        return logged

    def _bump_data(self, module_name: str, operation: str) -> None:
        """Count one more operation in the module's lifetime data document; never raises.

        Read-modify-write keeping every other key, under log_operation's lock: exact for its writers.
        """
        try:
            document = self.load_json(module_name, "data")
            if not isinstance(document, dict):
                document = _default_document("data", module_name)

            today = datetime.now().date().isoformat()
            document.setdefault("module_name", module_name)
            document.setdefault("created", today)
            document.setdefault("last_updated", today)

            current = document.get("operations_total")
            if isinstance(current, bool) or not isinstance(current, int):
                current = 0
            document["operations_total"] = current + 1
            document["last_operation"] = operation

            self.save_json(module_name, "data", document)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "json_service: data bump failed — the log entry landed, the count did not",
                operation=operation,
                module=module_name,
                error=str(exc),
            )

    def _max_log_entries(self, module_name: str) -> int:
        """The module's declared log cap (config.max_log_entries), or the default."""
        config = self.load_json(module_name, "config")
        if not isinstance(config, dict):
            return DEFAULT_MAX_LOG_ENTRIES

        section = config.get("config")
        if not isinstance(section, dict):
            return DEFAULT_MAX_LOG_ENTRIES

        declared = section.get("max_log_entries", DEFAULT_MAX_LOG_ENTRIES)
        if isinstance(declared, bool) or not isinstance(declared, int):
            return DEFAULT_MAX_LOG_ENTRIES

        return declared
