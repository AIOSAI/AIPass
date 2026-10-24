# =================== AIPass ====================
# Name: json_service.py
# Description: The fleet's one JSON handler service (prax-owned)
# Version: 1.2.0
# Created: 2026-09-03
# Modified: 2026-10-24
# =============================================

"""The fleet's one JSON handler implementation (DPLAN-0325).

Reference: docs/json_service.md
"""

import itertools
import json
import logging
import os
import stat
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("aipass.prax.json")

JSON_TYPES = ("config", "data", "log")
DEFAULT_MAX_LOG_ENTRIES = 100

# Windows os.replace raises PermissionError while any reader holds the target; readers hold it microseconds.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005

# What open(path, "w") asks for; the umask narrows it, so a new document gets this process's usual mode.
_NEW_DOCUMENT_MODE = 0o666

_STAGE_NAME_ATTEMPTS = 8
_ORPHAN_AGE_SECONDS = 3600

# pid + counter, never the clock: callers stub this module's `time` to skip the retry sleep.
_stage_serial = itertools.count()


class InvalidDocument(ValueError):
    """A document that does not match the structure its json_type declares."""


class WriteFailed(OSError):
    """The write could not land: retry exhausted, or an OSError on the way."""


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
            "json_service: cannot read the current mode of '%s' (%s) — writing it as a new document",
            file_path,
            exc,
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
        # fchmod on the fd, not chmod on the path: no second lookup to redirect. Absent on Windows.
        if mode is not None and hasattr(os, "fchmod"):
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
                logger.info("json_service: orphan sweep skipped '%s': %s", orphan, exc)
    except OSError as exc:
        logger.info("json_service: orphan sweep of '%s' failed: %s", directory, exc)


def _discard(temp_path: str) -> None:
    """Remove a staged file that never landed. Litter accumulates silently."""
    if not temp_path:
        return
    try:
        os.unlink(temp_path)
    except OSError as exc:
        logger.warning("json_service: temp cleanup failed for '%s': %s", temp_path, exc)


def replace_with_retry(source: str, destination: str) -> None:
    """os.replace that tolerates Windows sharing violations, bounded.

    Public as a test seam: patch ``aipass.prax.json_handler.replace_with_retry``; write_json reads it at call time.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS)


def _get_caller_module_name() -> str:
    """Name the module that called ``log_operation``, or "unknown" when no module is behind the frame.

    Frame depth 2 is exact: the branch shim BINDS log_operation and never wraps it, or every entry is renamed.
    sys._getframe, never inspect.stack(): inspect reaches os.getcwd() via realpath on Windows.
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


def for_module(file: "str | os.PathLike") -> "JsonHandle":
    """Build the handle for the branch that owns ``file``.

    ``parents[3]`` is the branch root; no resolve(), which needs a working directory.
    """
    return JsonHandle(Path(file).parents[3])


class JsonHandle:
    """One branch's bound view of the json service."""

    def __init__(self, branch_root: Path):
        self.branch_root = branch_root

    @property
    def json_dir(self) -> Path:
        """The branch's json directory, computed per access so AIPASS_TEST_LOG_DIR redirects; empty is absence."""
        name = self.branch_root.name
        test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
        if test_dir:
            return Path(test_dir) / name / f"{name}_json"
        return self.branch_root / f"{name}_json"

    def read_json(self, file_path: Path) -> Optional[Any]:
        """Read any json document by path; None when missing or unreadable, never raises."""
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("json_service: unreadable document '%s': %s", file_path, exc)
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
            logger.warning("json_service: cannot create '%s': %s", file_path.parent, exc)
            return False

        content = json.dumps(data, indent=indent, ensure_ascii=False, allow_nan=False)

        temp_path = ""
        try:
            temp_path = _stage(file_path.parent, content, _current_mode(file_path))
            replace_with_retry(temp_path, str(file_path))
            return True
        except OSError as exc:
            logger.warning("json_service: write failed for '%s': %s", file_path, exc)
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
        """Ensure a module's typed document exists and is structurally valid.

        A dict "data" document missing base keys is healed in place, never replaced: other writers share it.
        """
        json_path = self.get_json_path(module_name, json_type)

        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("json_service: cannot create '%s': %s", json_path.parent, exc)
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
                logger.warning("json_service: cannot heal '%s' without losing its keys: %s", json_path, exc)
                return False

        return self.write_json(json_path, _default_document(json_type, module_name))

    def ensure_module_jsons(self, module_name: str) -> bool:
        """Ensure all three typed documents exist for a module."""
        for json_type in JSON_TYPES:
            self.ensure_json_exists(module_name, json_type)
        return True

    def load_json(self, module_name: str, json_type: str) -> Optional[Any]:
        """Load a module's typed document, creating it if absent; the in-code default if still unreadable."""
        self.ensure_json_exists(module_name, json_type)

        data = self.read_json(self.get_json_path(module_name, json_type))
        if data is None:
            logger.warning("json_service: '%s/%s' unreadable after ensure — using the default", module_name, json_type)
            return _default_document(json_type, module_name)

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

    def log_operation(
        self,
        operation: str,
        data: Optional[Dict[str, Any]] = None,
        module_name: Optional[str] = None,
    ) -> bool:
        """Append a timestamped entry to a module's operations log, then bump its data document.

        Telemetry on watchdog and display threads: a write failure answers False, never raises.
        """
        if module_name is None:
            module_name = _get_caller_module_name()

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
        except InvalidDocument:
            raise
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("json_service: log_operation('%s') failed for '%s': %s", operation, module_name, exc)
            return False

        self._bump_data(module_name, operation)
        return logged

    def _bump_data(self, module_name: str, operation: str) -> None:
        """Count one more operation in the module's lifetime data document; never raises.

        Read-modify-write keeping every other key; under racing writers the total is a lower bound.
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
                "json_service: data bump after '%s' failed for '%s' — the log entry landed, the count did not: %s",
                operation,
                module_name,
                exc,
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
