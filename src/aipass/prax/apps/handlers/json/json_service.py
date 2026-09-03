# =================== AIPass ====================
# Name: json_service.py
# Description: The fleet's one JSON handler service (prax-owned)
# Version: 1.0.0
# Created: 2026-09-03
# Modified: 2026-09-03
# =============================================

"""The fleet's one JSON handler implementation (DPLAN-0325).

Every branch's ``apps/handlers/json/json_handler.py`` is a byte-identical shim
that binds this module's names to a handle for its own branch. There is no
second implementation and nothing per-branch lives here.

Reached through prax's lazy package init — ``from aipass.prax import
json_handler`` — never by importing this path from another branch.

Two constraints shape the code:

* **Stdlib only.** Importing this module must not pull the prax logger graph
  (30 modules, watchdog, the aipass.trigger edge). Warnings go to a plain
  ``logging`` logger; a consumer that wants them routed configures logging.
* **Dead working directory.** No ``Path.resolve()``, no ``os.getcwd()``, no
  ``inspect.stack()``. The module imports and runs in a process whose working
  directory has been deleted.

The json directory is computed PER CALL, never captured at import: a test that
sets ``AIPASS_TEST_LOG_DIR`` after importing still redirects the next write.
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

logger = logging.getLogger("aipass.prax.json")

JSON_TYPES = ("config", "data", "log")
DEFAULT_MAX_LOG_ENTRIES = 100

# os.replace on Windows raises PermissionError while ANY reader holds the target
# open (no FILE_SHARE_DELETE on Python's open). Readers hold handles for
# microseconds, so a short bounded retry converges; after the bound the error
# raises honestly. POSIX never takes this path for open files, so a genuine
# permission problem still surfaces — just ~200ms later.
_REPLACE_ATTEMPTS = 40
_REPLACE_BACKOFF_SECONDS = 0.005


class InvalidDocument(ValueError):
    """A document that does not match the structure its json_type declares."""


class WriteFailed(OSError):
    """The write could not land: retry exhausted, or an OSError on the way."""


# =============================================
# MODULE HELPERS
# =============================================


def _default_document(json_type: str, module_name: str) -> Any:
    """The in-code default document for a json_type.

    Replaces the old on-disk ``json_templates/`` directories: a default that
    lives in a file can go missing, and a handler whose default is missing
    stops self-healing exactly when it is needed.
    """
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


def _stage(directory: Path, content: str) -> str:
    """Write content to a temp file beside the target and return its path.

    Staged beside the target on purpose: os.replace is only atomic within one
    filesystem, and a temp directory can be on another one.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(directory),
        suffix=".tmp",
        delete=False,
    ) as staged:
        staged.write(content)
        staged.flush()
        os.fsync(staged.fileno())
        return staged.name


def _discard(temp_path: str) -> None:
    """Remove a staged file that never landed. Litter accumulates silently."""
    if not temp_path:
        return
    try:
        os.unlink(temp_path)
    except OSError as exc:
        logger.warning("json_service: temp cleanup failed for '%s': %s", temp_path, exc)


def _replace_with_retry(source: str, destination: str) -> None:
    """os.replace that tolerates Windows sharing violations, bounded.

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


def _get_caller_module_name() -> str:
    """Name the module that called ``log_operation``.

    Frame depth 2 is exact and load-bearing: [0] is this function, [1] is
    log_operation, [2] is the caller. This is why the branch shim BINDS the
    method and never wraps it — any wrapper adds a frame and silently renames
    every operation in the log.

    sys._getframe, never inspect.stack(): inspect reaches an unguarded
    os.path.realpath, and on Windows ntpath.realpath calls os.getcwd() before it
    checks anything, so on a box with no readable working directory every
    operation was recorded as "unknown".

    Returns:
        The caller's module name, or "unknown" when there is no module behind
        the frame.
    """
    try:
        caller_frame = sys._getframe(2)
    except ValueError:
        return "unknown"

    # A pseudo-frame has no module behind it. `<stdin>`, `<string>` from python
    # -c or exec, `<frozen importlib._bootstrap>` — Path("<stdin>").stem is
    # "<stdin>", and a log that attributes work to that asserts something false
    # about who did it. It also became a DIRECTORY name once (2026-08-31).
    filename = caller_frame.f_code.co_filename
    if filename.startswith("<") and filename.endswith(">"):
        return "unknown"

    module_name = Path(filename).stem
    if module_name and not module_name.startswith("_"):
        return module_name

    return "unknown"


def for_module(file: "str | os.PathLike") -> "JsonHandle":
    """Build the handle for the branch that owns ``file``.

    Args:
        file: A branch's ``apps/handlers/json/json_handler.py`` (``__file__``).

    Returns:
        A JsonHandle rooted at that branch.

    ``parents[3]`` walks json -> handlers -> apps -> the branch root. No
    resolve(): the shim's ``__file__`` is already absolute under every import
    form AIPass uses, and resolve() needs a working directory.
    """
    return JsonHandle(Path(file).parents[3])


# =============================================
# THE SERVICE
# =============================================


class JsonHandle:
    """One branch's bound view of the json service."""

    def __init__(self, branch_root: Path):
        self.branch_root = branch_root

    @property
    def json_dir(self) -> Path:
        """The branch's json directory, computed on every access.

        Never captured at import: the value is a function of the environment,
        and a test that sets AIPASS_TEST_LOG_DIR after importing must still be
        redirected. An EMPTY value is absence, not a redirect.
        """
        name = self.branch_root.name
        test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
        if test_dir:
            return Path(test_dir) / name / f"{name}_json"
        return self.branch_root / f"{name}_json"

    # ---------------------------------------------
    # Path primitives
    # ---------------------------------------------

    def read_json(self, file_path: Path) -> Optional[Any]:
        """Read any json document by path.

        Args:
            file_path: The document to read.

        Returns:
            The parsed document, or None when it is missing or unreadable.
            Never raises — a caller that wants the failure loud checks for None.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("json_service: unreadable document '%s': %s", file_path, exc)
            return None

    def write_json(self, file_path: Path, data: Any, indent: int = 2) -> bool:
        """Write any json document by path, atomically.

        Serialises BEFORE staging: a payload that cannot be serialised is a
        caller bug, not a write failure, so TypeError and ValueError propagate
        while an OSError only ever answers False.

        Args:
            file_path: The document to write.
            data: The payload.
            indent: json.dumps indent.

        Returns:
            True when the document landed, False on any OSError.

        Raises:
            TypeError: The payload is not serialisable.
            ValueError: The payload is circular.
        """
        file_path = Path(file_path)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("json_service: cannot create '%s': %s", file_path.parent, exc)
            return False

        content = json.dumps(data, indent=indent, ensure_ascii=False)

        temp_path = ""
        try:
            temp_path = _stage(file_path.parent, content)
            _replace_with_retry(temp_path, str(file_path))
            return True
        except OSError as exc:
            logger.warning("json_service: write failed for '%s': %s", file_path, exc)
            _discard(temp_path)
            return False

    # ---------------------------------------------
    # Typed documents
    # ---------------------------------------------

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
        """Path of a module's typed document.

        Raises:
            ValueError: json_type is not one of JSON_TYPES. Refused rather than
                written: a typo'd type used to create a document nothing reads.
        """
        if json_type not in JSON_TYPES:
            raise ValueError(f"Unknown json_type '{json_type}' (expected one of {JSON_TYPES})")

        return self.json_dir / f"{module_name}_{json_type}.json"

    def ensure_json_exists(self, module_name: str, json_type: str) -> bool:
        """Ensure a module's typed document exists and is structurally valid.

        Missing, empty, unreadable or structurally invalid documents are
        regenerated from the in-code default.

        Returns:
            True once the document is in place; False only if the write could
            not land.
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

        return self.write_json(json_path, _default_document(json_type, module_name))

    def ensure_module_jsons(self, module_name: str) -> bool:
        """Ensure all three typed documents exist for a module."""
        for json_type in JSON_TYPES:
            self.ensure_json_exists(module_name, json_type)
        return True

    def load_json(self, module_name: str, json_type: str) -> Optional[Any]:
        """Load a module's typed document, creating it if absent.

        Returns:
            The parsed document. A document still unreadable after ensure ran
            yields the in-code default rather than None — the caller asked for
            a document of a known shape and gets one.
        """
        self.ensure_json_exists(module_name, json_type)

        data = self.read_json(self.get_json_path(module_name, json_type))
        if data is None:
            logger.warning("json_service: '%s/%s' unreadable after ensure — using the default", module_name, json_type)
            return _default_document(json_type, module_name)

        return data

    def save_json(self, module_name: str, json_type: str, data: Any) -> bool:
        """Save a module's typed document.

        Returns:
            True. The write either lands or raises — it never answers False,
            which is how a lost document used to look like success.

        Raises:
            InvalidDocument: data does not match json_type.
            WriteFailed: the write could not land.
            TypeError: the payload is not serialisable.
            ValueError: the payload is circular.
        """
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
        """Append a timestamped entry to a module's operations log.

        Telemetry, so a write failure answers False instead of raising: this is
        called from watchdog and display threads where a raising writer is
        silent half-death. A structurally invalid document is a caller bug and
        stays loud.

        Args:
            operation: Operation name.
            data: Optional payload attached to the entry.
            module_name: Defaults to the calling module (frame 2).

        Returns:
            True when the entry landed, False on a write or payload failure.

        Raises:
            InvalidDocument: the log document does not match its type.
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

            return self.save_json(module_name, "log", log)
        except InvalidDocument:
            raise
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("json_service: log_operation('%s') failed for '%s': %s", operation, module_name, exc)
            return False

    def _max_log_entries(self, module_name: str) -> int:
        """The module's declared log cap, or the default.

        The knob is published in every module's config document, so a branch
        that sets it gets it — the cap used to be a constant while the config
        advertised a number nothing read.
        """
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
