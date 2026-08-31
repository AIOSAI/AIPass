# =================== AIPass ====================
# Name: json_handler.py
# Description: Auto-Creating & Self-Healing JSON System
# Version: 1.3.0
# Created: 2025-11-15
# Modified: 2026-08-30
# =============================================

"""
JSON Handler - Auto-Creating & Self-Healing JSON System

Handles default JSON files (config, data, log) for prax modules.
Never manually create JSONs - they build themselves.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
import inspect

logger = logging.getLogger(__name__)

# Resolve paths relative to this file (no hardcoded paths)
_HANDLER_DIR = Path(__file__).resolve().parent  # .../handlers/json/
_HANDLERS_DIR = _HANDLER_DIR.parent  # .../handlers/
_PRAX_ROOT = _HANDLERS_DIR.parent.parent  # .../prax/


def _resolve_prax_json_dir(test_log_dir: Optional[str], prax_root: Path) -> Path:
    """Resolve the prax_json directory, honouring the fleet's test-redirect seam.

    prax redirected its log FILES under pytest for a long time
    (``config/load.py::get_system_logs_dir``) and this constant never got the
    same branch, so one ``logger.info()`` under pytest wrote 4 redirected files
    and 24 real ones into the live ``prax_json/``. Every branch's suite paid it.

    ``AIPASS_TEST_LOG_DIR`` is the fleet contract, in @trigger's form
    (``trigger/apps/handlers/json/json_handler.py``) rather than a spelling
    invented here — five techniques already existed and a sixth would be the
    problem, not the fix.

    An EMPTY value is absence, not a redirect: ``Path("") / "prax"`` is a
    relative path that would scatter state wherever the process happens to
    stand, and an unset-looking env var must not do that.

    Args:
        test_log_dir: the raw ``AIPASS_TEST_LOG_DIR`` value, or None
        prax_root: the real prax branch root

    Returns:
        The directory prax JSON state should be written to.
    """
    if test_log_dir:
        return Path(test_log_dir) / "prax" / "prax_json"
    return prax_root / "prax_json"


_IMPORT_TIME_JSON_DIR = _resolve_prax_json_dir(os.environ.get("AIPASS_TEST_LOG_DIR"), _PRAX_ROOT)

# Kept as a module attribute because ~20 tests across this suite redirect state
# with ``monkeypatch.setattr(mod, "PRAX_JSON_DIR", tmp_path)``. That remains the
# supported override and it still wins — see _current_json_dir().
PRAX_JSON_DIR = _IMPORT_TIME_JSON_DIR


def _current_json_dir() -> Path:
    """Resolve the state directory at CALL time, not import time.

    Import-time resolution was not enough, and the reason is the same one that
    made the logger unmockable: a value captured when the module loads cannot be
    redirected by anything that runs afterwards. Measured here — prax's own
    conftest sets ``AIPASS_TEST_LOG_DIR`` at module scope and the constant STILL
    resolved to the live tree, because something imports this module before the
    conftest runs. A seam that depends on winning an import race is not a seam.

    Precedence, in order:
      1. An explicit ``PRAX_JSON_DIR`` override (a test patched the attribute),
         recognised as one only when it differs from BOTH the real directory and
         the current redirect target.
      2. ``AIPASS_TEST_LOG_DIR``, re-read every call so it works whenever it is set.
      3. The real ``prax_json/``.

    Why not compare against a captured import-time value — either by identity or
    by value. @daemon adopted the identity form from prax's own contract mail and
    9 of their pins went green alone and red in the full suite: a test that calls
    ``importlib.reload`` while a monkeypatch is live has its teardown write the
    PRE-reload Path back onto the POST-reload module, so the attribute is no
    longer the object the module now holds and every later call reads it as an
    explicit override. Reproduced here against this module, and prax is not
    immune — only shielded by a conftest that drops it from ``sys.modules``.

    @daemon's fix (compare by value) rescues their ordering but not the one that
    made call-time resolution necessary in the first place: import first, env set
    afterwards. There the written-back value is the REAL directory while the
    post-reload default is the REDIRECT, so the two differ and a value comparison
    also reads "explicitly patched" — and the writes go back to the live tree,
    silently, for the rest of the session.

    Comparing against both fixed points has no such stale reference. The cost is
    one lost distinction, stated rather than hidden: a test that patches this to
    the real directory, or to exactly the redirect target, is indistinguishable
    from one that never patched. Both resolve to the same path either way, so the
    answer is unchanged — which is why this is cheaper than @daemon's loss and far
    cheaper than a seam that dies to a reload.
    """
    default = _resolve_prax_json_dir(os.environ.get("AIPASS_TEST_LOG_DIR"), _PRAX_ROOT)
    real = _resolve_prax_json_dir(None, _PRAX_ROOT)
    if PRAX_JSON_DIR != real and PRAX_JSON_DIR != default:
        return PRAX_JSON_DIR
    return default


JSON_TEMPLATES_DIR = _HANDLERS_DIR / "json_templates"


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


def _get_caller_module_name() -> str:
    """
    Auto-detect calling module name from call stack

    Returns:
        Module name (e.g., "imports_standard" from imports_standard.py)
    """
    try:
        stack = inspect.stack()
        # Skip frames: [0]=this function, [1]=log_operation, [2]=actual caller
        if len(stack) > 2:
            caller_frame = stack[2]
            caller_path = Path(caller_frame.filename)
            module_name = caller_path.stem

            # Validate module name
            if module_name and not module_name.startswith("_"):
                return module_name

        # Fallback
        return "unknown"
    except Exception as e:
        logger.warning("json_handler: failed to detect caller module name: %s", e)
        return "unknown"


def load_template(json_type: str, module_name: str) -> Any:
    """Load JSON template from template file"""
    template_path = JSON_TEMPLATES_DIR / "default" / f"{json_type}.json"

    if not template_path.exists():
        return None

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template = json.load(f)

        # Replace placeholders
        template_str = json.dumps(template)
        template_str = template_str.replace("{{MODULE_NAME}}", module_name)
        template_str = template_str.replace("{{TIMESTAMP}}", datetime.now().date().isoformat())

        return json.loads(template_str)
    except Exception as e:
        logger.warning("json_handler: failed to load template '%s' for module '%s': %s", json_type, module_name, e)
        return None


def validate_json_structure(data: Any, json_type: str) -> bool:
    """Validate JSON structure matches expected type"""
    if json_type == "config":
        if not isinstance(data, dict):
            return False
        required = ["module_name", "version", "config"]
        return all(key in data for key in required)

    elif json_type == "data":
        if not isinstance(data, dict):
            return False
        required = ["created", "last_updated"]
        return all(key in data for key in required)

    elif json_type == "log":
        return isinstance(data, list)

    return False


def get_json_path(module_name: str, json_type: str) -> Path:
    """Get path for module JSON file"""
    filename = f"{module_name}_{json_type}.json"
    return _current_json_dir() / filename


def ensure_json_exists(module_name: str, json_type: str) -> bool:
    """Ensure JSON file exists, create from template if missing"""
    _current_json_dir().mkdir(parents=True, exist_ok=True)

    json_path = get_json_path(module_name, json_type)

    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if validate_json_structure(data, json_type):
                return True
            else:
                pass  # Corrupted - will regenerate
        except Exception as e:
            logger.warning("json_handler: unreadable json for '%s/%s', will regenerate: %s", module_name, json_type, e)

    template = load_template(json_type, module_name)
    if template is None:
        return False

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(template, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error("json_handler: failed to write json file '%s/%s': %s", module_name, json_type, e)
        return False


def load_json(module_name: str, json_type: str) -> Optional[Any]:
    """Load JSON file, auto-create if missing"""
    if not ensure_json_exists(module_name, json_type):
        return None

    json_path = get_json_path(module_name, json_type)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("json_handler: failed to load json '%s/%s': %s", module_name, json_type, e)
        return None


def _atomic_write(json_path: Path, content: str) -> None:
    """Write content to file atomically via temp file + rename.

    The rename goes through _replace_with_retry: on Windows a reader holding
    the target open turns the move into a PermissionError, and one stuck move
    starved a whole CI run (2026-08-18). Bounded, then it raises honestly.
    """
    fd, tmp_path = tempfile.mkstemp(dir=json_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        _replace_with_retry(tmp_path, str(json_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_err:
            logger.warning("json_handler: temp file cleanup failed: %s", cleanup_err)
        raise


def save_json(module_name: str, json_type: str, data: Any) -> bool:
    """Save JSON file using atomic write (temp file + rename) to prevent corruption."""
    json_path = get_json_path(module_name, json_type)

    if not validate_json_structure(data, json_type):
        return False

    if json_type == "data" and isinstance(data, dict):
        data["last_updated"] = datetime.now().date().isoformat()

    try:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        _atomic_write(json_path, content)
        return True
    except Exception as e:
        logger.error("json_handler: failed to save json '%s/%s': %s", module_name, json_type, e)
        return False


def ensure_module_jsons(module_name: str) -> bool:
    """Ensure all 3 JSON files exist for a module"""
    ensure_json_exists(module_name, "config")
    ensure_json_exists(module_name, "data")
    ensure_json_exists(module_name, "log")
    return True


def log_operation(operation: str, data: Dict[str, Any] | None = None, module_name: str | None = None) -> bool:
    """
    Add entry to module log with automatic rotation

    Auto-detects calling module if module_name not provided.
    Implements config-controlled log limits to prevent unbounded growth.
    When max_log_entries is reached, removes oldest entries (FIFO).

    Args:
        operation: Operation name to log
        data: Optional data dict
        module_name: Optional module name (auto-detected if not provided)

    Returns:
        True if successful, False otherwise
    """
    # Auto-detect module name if not provided
    if module_name is None:
        module_name = _get_caller_module_name()

    ensure_module_jsons(module_name)

    # Load config to get max_log_entries
    config = load_json(module_name, "config")
    max_entries = 100  # Default
    if config and "config" in config:
        max_entries = config["config"].get("max_log_entries", 100)

    # Load existing log
    log = load_json(module_name, "log")
    if log is None:
        log = []

    # Create new entry
    entry: Dict[str, Any] = {"timestamp": datetime.now().isoformat(), "operation": operation}

    if data:
        entry["data"] = data

    # Add new entry
    log.append(entry)

    # Rotate if exceeds max (keep most recent entries)
    if len(log) > max_entries:
        log = log[-max_entries:]

    return save_json(module_name, "log", log)


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("JSON HANDLER - Working Implementation")
    print("=" * 70)
    print("\n[TESTING] Creating prax JSONs...")

    # Test auto-creation
    log_operation("test_operation", {"test": "data"}, "prax")

    print("\nCheck src/aipass/prax/prax_json/ for created files:")
    print("  - prax_config.json")
    print("  - prax_data.json")
    print("  - prax_log.json")
    print("\n" + "=" * 70 + "\n")
