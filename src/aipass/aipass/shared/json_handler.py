# =================== AIPass ====================
# Name: json_handler.py
# Description: Shared JSON handler with injectable storage directory
# Version: 1.2.0
# Created: 2026-06-06
# Modified: 2026-08-31
# =============================================

"""Shared JSON handler — auto-creating, self-healing JSON system.

Dependency-free: uses only stdlib. Importable before drone/prax exist.

Each branch creates a JsonHandler instance with its own json_dir.
Contract: save_json raises ValueError on validation failure.

This module is the single write path behind five branch json_handler shims —
@aipass, @canary, @memory, @spawn, plus spawn's citizen TEMPLATE, so every
citizen minted from here on inherits whatever this file does. Measured
2026-08-31 by grepping importers fleet-wide; the line above used to name three
and predated @canary and the template. Any change here carries all five at
once — see _replace_with_retry, and _get_caller_module_name, which four of the
five reach without a local copy.
"""

import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_JSON_TYPES: tuple[str, ...] = ("config", "data", "log")


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


class JsonHandler:
    """JSON file handler with injectable storage directory.

    Provides JSON I/O utilities, validation, and operation logging
    for the three-JSON system (config, data, log).

    Args:
        json_dir: Directory for module JSON files (config/data/log).
    """

    MAX_LOG_ENTRIES = 100

    def __init__(self, json_dir: Path):
        self._json_dir = Path(json_dir)

    @staticmethod
    def read_json(file_path: Path) -> Optional[dict]:
        """Read and parse a JSON file.

        Args:
            file_path: Path to the JSON file.

        Returns:
            Parsed dict, or None on failure.
        """
        try:
            return json.loads(Path(file_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.warning("Failed to read JSON from %s: %s", file_path, e)
            return None

    @staticmethod
    def write_json(file_path: Path, data: Any, indent: int = 2) -> bool:
        """Write data to a JSON file atomically (temp file + os.replace).

        Args:
            file_path: Target path.
            data: JSON-serializable data.
            indent: JSON indentation level.

        Returns:
            True on success, False on OS error.

        Note:
            The swap goes through _replace_with_retry, not a bare os.replace:
            on Windows a reader holding the target open turns the move into a
            PermissionError, and one stuck move starved a whole CI run
            (2026-08-18). Bounded, then it raises — and a PermissionError is an
            OSError, so the exhausted retry lands in the handler below and this
            method answers False, its documented contract for an OS failure.
        """
        file_path = Path(file_path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(data, indent=indent) + "\n"
            fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
            closed = False
            try:
                os.write(fd, content.encode("utf-8"))
                os.fsync(fd)
                os.close(fd)
                closed = True
                _replace_with_retry(tmp_path, str(file_path))
            except BaseException:
                if not closed:
                    os.close(fd)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
            return True
        except OSError as e:
            logger.error("Failed to write JSON to %s: %s", file_path, e)
            return False

    @staticmethod
    def validate_json_structure(data: Any, json_type: str) -> bool:
        """Validate that data matches the expected shape for json_type.

        Args:
            data: Parsed JSON data to validate.
            json_type: One of "config", "data", "log".

        Returns:
            True when the structure is valid, False otherwise.
        """
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

    @staticmethod
    def _create_default(json_type: str, module_name: str) -> Any:
        """Return default content for a given JSON type.

        Args:
            json_type: One of "config", "data", "log".
            module_name: Logical module name.

        Returns:
            Default data structure.

        Raises:
            ValueError: For unknown json_type.
        """
        today = datetime.now().date().isoformat()
        if json_type == "config":
            return {
                "module_name": module_name,
                "version": "1.0.0",
                "config": {
                    "max_log_entries": JsonHandler.MAX_LOG_ENTRIES,
                },
                "created": today,
                "last_updated": today,
            }
        if json_type == "data":
            return {
                "created": today,
                "last_updated": today,
            }
        if json_type == "log":
            return []
        raise ValueError(f"Unknown json_type: {json_type!r}")

    def get_json_path(self, module_name: str, json_type: str) -> Path:
        """Return the filesystem path for a module's JSON file.

        Args:
            module_name: Logical module name.
            json_type: One of "config", "data", "log".

        Returns:
            Absolute Path to the JSON file.
        """
        return self._json_dir / f"{module_name}_{json_type}.json"

    def ensure_json_exists(self, module_name: str, json_type: str) -> bool:
        """Ensure a single JSON file exists; create with defaults if missing.

        If the file exists but fails validation it is regenerated.

        Args:
            module_name: Logical module name.
            json_type: One of "config", "data", "log".

        Returns:
            True after the file is confirmed present and valid.
        """
        self._json_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.get_json_path(module_name, json_type)

        if json_path.exists():
            try:
                if json_path.stat().st_size == 0:
                    logger.warning("ensure_json_exists: empty file at %s, regenerating", json_path)
                else:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    if self.validate_json_structure(data, json_type):
                        return True
            except Exception as exc:
                logger.warning("ensure_json_exists: failed to read %s, regenerating: %s", json_path, exc)

        default = self._create_default(json_type, module_name)
        self.write_json(json_path, default)
        return True

    def ensure_module_jsons(self, module_name: str) -> bool:
        """Ensure all three JSON files (config, data, log) exist for a module.

        Args:
            module_name: Logical module name.

        Returns:
            True when all files are present and valid.
        """
        for json_type in _JSON_TYPES:
            self.ensure_json_exists(module_name, json_type)
        return True

    def load_json(self, module_name: str, json_type: str) -> Any | None:
        """Load a module's JSON file, auto-creating it if missing.

        Args:
            module_name: Logical module name.
            json_type: One of "config", "data", "log".

        Returns:
            Parsed JSON data, or None on failure.
        """
        if not self.ensure_json_exists(module_name, json_type):
            return None

        json_path = self.get_json_path(module_name, json_type)
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("load_json: failed to read %s: %s", json_path, exc)
            return self._create_default(json_type, module_name)

    def save_json(self, module_name: str, json_type: str, data: Any) -> bool:
        """Write data to a module's JSON file after validation.

        For "data" type files the last_updated field is refreshed automatically.

        Args:
            module_name: Logical module name.
            json_type: One of "config", "data", "log".
            data: The data structure to persist.

        Returns:
            True on success.

        Raises:
            ValueError: When data fails structure validation.
        """
        if not self.validate_json_structure(data, json_type):
            raise ValueError(f"Invalid structure for {json_type} JSON")

        if json_type == "data" and isinstance(data, dict):
            data["last_updated"] = datetime.now().date().isoformat()

        json_path = self.get_json_path(module_name, json_type)
        return self.write_json(json_path, data)

    def log_operation(self, operation: str, data: Dict[str, Any] | None = None, module_name: str | None = None) -> bool:
        """Add entry to module operation log with automatic rotation.

        Auto-detects calling module if module_name not provided.

        Args:
            operation: Operation name to log.
            data: Optional data dict.
            module_name: Optional module name (auto-detected if not provided).

        Returns:
            True if successful, False otherwise.
        """
        if module_name is None:
            module_name = _get_caller_module_name()

        try:
            self.ensure_module_jsons(module_name)

            log = self.load_json(module_name, "log")
            if log is None:
                log = []

            entry: Dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "operation": operation,
            }
            if data:
                entry["data"] = data

            log.append(entry)

            if len(log) > self.MAX_LOG_ENTRIES:
                log = log[-self.MAX_LOG_ENTRIES :]

            return self.save_json(module_name, "log", log)
        except Exception as exc:
            logger.warning("log_operation: failed for %s/%s: %s", module_name, operation, exc)
            return False


def _get_caller_module_name() -> str:
    """Auto-detect calling module name from call stack.

    Walks the frame chain with ``sys._getframe`` rather than
    ``inspect.stack()``.  MEASURED 2026-08-31 (@canary's exposure report,
    @devpulse's round-4 follow-up): ``inspect.stack()`` builds a FrameInfo per
    frame, and for any frame whose filename is not on disk — ``<string>`` from
    a ``-c`` command-line source, a ``compile()``d source, the frozen
    importlib frames —
    ``getsourcefile()`` falls through to ``getmodule()``, whose module-scanning
    loop calls ``os.path.realpath`` OUTSIDE the ``try`` that wraps
    ``getabsfile``.  ``ntpath.realpath`` then reads ``os.getcwd()``
    unconditionally.

    On this hot path that made LOGGING TAKE DOWN THE CALLER IT LOGS FOR:
    ``log_operation`` resolves the module name BEFORE its own ``try``, so the
    raise escaped every handler below it.  A frame's ``co_filename`` is already
    a string in memory; reading it touches no filesystem.

    Returns:
        The calling module's filename stem, or ``"unknown"`` when the stack is
        too shallow or the name is private. Behaviour is unchanged from the
        ``inspect.stack()`` form — only the mechanism moved.
    """
    try:
        frame = sys._getframe(2)
    except ValueError:
        # Stack shallower than the caller-of-log_operation depth; the
        # inspect.stack() form spelled this as `len(stack) > 2`.
        return "unknown"
    module_name = Path(frame.f_code.co_filename).stem
    if module_name and not module_name.startswith("_"):
        return module_name
    return "unknown"
