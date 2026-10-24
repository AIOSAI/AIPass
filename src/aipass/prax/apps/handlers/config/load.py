# =================== AIPass ====================
# Name: load.py
# Description: Load Logging Configuration Handler
# Version: 1.3.0
# Created: 2025-11-07
# Modified: 2026-10-24
# =============================================

"""
Load Logging Configuration Handler
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.handlers.repo_root import find_repo_root
from aipass.prax.apps.handlers.repo_root import resolved_file

logger = logging.getLogger(__name__)

MODULE_NAME = "load"

PRAX_ROOT = resolved_file(Path(__file__)).parents[3]  # config/load.py → handlers/ → apps/ → prax/
ECOSYSTEM_ROOT = PRAX_ROOT.parent  # prax/ → aipass/ (contains all sibling modules)
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd."""
    return find_repo_root(Path(__file__))


def _is_pytest_session() -> bool:
    """Detect pytest session via sys.modules (immune to patch.dict(os.environ, clear=True))."""
    return "_pytest" in sys.modules


_system_logs_dir_cache: Path | None = None

USER_SYSTEM_LOGS = Path(".aipass") / "system_logs"


def system_logs_home(repo_root: Path) -> Path:
    """The system_logs/ directory for a resolved repo root — never the filesystem root.

    An installed package has no repo above it, so the walk ends at the filesystem
    root (unwritable); its logs go to ``~/.aipass/system_logs`` instead.
    """
    if repo_root == Path(repo_root.anchor):
        return Path.home() / USER_SYSTEM_LOGS
    return repo_root / "system_logs"


def get_system_logs_dir() -> Path:
    """Lazily resolve and create system_logs directory (see system_logs_home())."""
    test_log_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_log_dir:
        p = Path(test_log_dir) / "system"
        p.mkdir(parents=True, exist_ok=True)
        return p
    if os.environ.get("PYTEST_CURRENT_TEST") or _is_pytest_session():
        p = Path(tempfile.gettempdir()) / "aipass_test_logs" / "system"
        p.mkdir(parents=True, exist_ok=True)
        return p
    global _system_logs_dir_cache
    if _system_logs_dir_cache is None:
        logs_dir = system_logs_home(_find_repo_root())
        logs_dir.mkdir(parents=True, exist_ok=True)
        # Cache only after mkdir succeeds, or later callers get a directory never made.
        _system_logs_dir_cache = logs_dir
    return _system_logs_dir_cache


def _warn_routing(module_name: str, destination: object) -> None:
    """Log routing warning when a module's log path falls outside ECOSYSTEM_ROOT."""
    try:
        from aipass.prax.apps.modules.logger import get_direct_logger

        get_direct_logger().warning(
            "[get_module_logs_dir] '%s' not in ECOSYSTEM_ROOT; routing to %s",
            module_name,
            destination,
        )
    except Exception as e:
        logger.warning(
            "[get_module_logs_dir] '%s' routing to %s (logger unavailable: %s)",
            module_name,
            destination,
            e,
        )


_PSEUDO_FILENAME = ("<", ">")


def _module_name_from_filename(filename: str) -> str:
    """Turn a frame's ``co_filename`` into a module name, or admit there is none.

    The name becomes a directory (get_module_logs_dir mkdirs it): ``<stdin>`` makes
    a junk directory on Linux and raises on Windows, so a pseudo-frame gets "unknown".
    """
    if filename.startswith(_PSEUDO_FILENAME[0]) and filename.endswith(_PSEUDO_FILENAME[1]):
        return "unknown"
    name = Path(filename).stem
    return name or "unknown"


def _get_caller_module_name(depth: int = 1) -> str:
    """Name the module `depth` frames above this one, without touching the disk.

    sys._getframe, never inspect.stack(): inspect.stack() reaches realpath, which
    calls os.getcwd() on Windows and raises from the logging path with a dead cwd.
    """
    try:
        frame = sys._getframe(depth)
    except ValueError:
        return "unknown"
    return _module_name_from_filename(frame.f_code.co_filename)


def get_module_logs_dir(module_name: Optional[str] = None) -> Path:
    """Get the branch-root logs directory for a module.

    Unknown modules fall back to system_logs/external/: never create new
    directories inside the AIPass source tree.
    """
    if module_name is None:
        module_name = _get_caller_module_name(depth=2)

    test_log_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_log_dir:
        p = Path(test_log_dir) / module_name
        p.mkdir(parents=True, exist_ok=True)
        return p
    if os.environ.get("PYTEST_CURRENT_TEST") or _is_pytest_session():
        p = Path(tempfile.gettempdir()) / "aipass_test_logs" / module_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    branch_dir = ECOSYSTEM_ROOT / module_name
    if branch_dir.exists():
        logs_dir = branch_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    src_root = ECOSYSTEM_ROOT.parent
    alt_branch_dir = src_root / module_name
    if alt_branch_dir.exists():
        logs_dir = alt_branch_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    caller_cwd = os.environ.get("AIPASS_CALLER_CWD")
    if caller_cwd:
        caller_path = Path(caller_cwd)
        project_root = next(
            (
                c
                for c in [caller_path, *caller_path.parents]
                if (c / ".git").exists() or (c / "pyproject.toml").exists()
            ),
            None,
        )
        if project_root:
            logs_dir = project_root / "logs" / module_name
            logs_dir.mkdir(parents=True, exist_ok=True)
            _warn_routing(module_name, logs_dir)
            return logs_dir

    logs_dir = get_system_logs_dir() / "external" / module_name
    logs_dir.mkdir(parents=True, exist_ok=True)
    _warn_routing(module_name, "system_logs/external/")
    return logs_dir


PRAX_LOGGER_CONFIG_FILE = PRAX_JSON_DIR / "prax_logger_config.json"

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_LEVEL = "INFO"

# 3 backups keep the hot logs' tail cheaply; a firehose needs capture, not retention.
DEFAULT_SYSTEM_LOGS = {"max_lines": 1000, "backup_count": 3, "log_level": "INFO"}

DEFAULT_LOCAL_LOGS = {"max_lines": 250, "backup_count": 3, "log_level": "INFO"}

LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Set before the process starts: levels bind when a logger is created, not per call.
LOG_LEVEL_ENV = "AIPASS_LOG_LEVEL"

_config_schema_warned: bool = False

# Level resolution runs on every logger init fleet-wide: warn once per bad value.
_bad_level_warned: set = set()


def lines_to_bytes(num_lines: int, avg_line_length: int = 200) -> int:
    """Convert a line budget to a byte threshold for log rotation.

    200 bytes is a deliberate over-estimate (real lines average ~115) so verbose
    logs keep their line budget. Do not lower it: that shrinks every log's bytes.
    """
    return num_lines * avg_line_length


def resolve_log_level(configured: Any = None) -> Any:
    """Resolve the effective log level for a handler tier."""
    for candidate, source in ((os.environ.get(LOG_LEVEL_ENV), LOG_LEVEL_ENV), (configured, "config log_level")):
        if candidate is None or candidate == "":
            continue
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
        name = str(candidate).strip().upper()
        if name in LOG_LEVEL_NAMES:
            return name
        key = (source, str(candidate))
        if key not in _bad_level_warned:
            _bad_level_warned.add(key)
            logger.warning(
                "[config] %s is not a log level (%s) — using %s. Valid: %s",
                candidate,
                source,
                DEFAULT_LOG_LEVEL,
                ", ".join(LOG_LEVEL_NAMES),
            )
    return DEFAULT_LOG_LEVEL


def level_to_int(level: Any) -> int:
    """Convert a resolved log level to its numeric value for comparison."""
    if isinstance(level, int) and not isinstance(level, bool):
        return level
    numeric = logging.getLevelName(str(level).strip().upper())
    return numeric if isinstance(numeric, int) else logging.INFO


def _as_dict(value: Any) -> Dict[str, Any]:
    """A config section, or {} when it is missing or not an object."""
    return value if isinstance(value, dict) else {}


def load_log_config() -> Dict[str, Any]:
    """Load logging config from JSON, fallback to defaults"""
    global _config_schema_warned
    try:
        if PRAX_LOGGER_CONFIG_FILE.exists():
            with open(PRAX_LOGGER_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)

                # Missing sections mean the file's settings never reach a handler: warn,
                # once per process (prax's own log sits in the directory prax watches).
                section = _as_dict(config.get("config")) if isinstance(config, dict) else {}
                missing = [k for k in ("system_logs", "local_logs") if k not in section]
                if missing and not _config_schema_warned:
                    _config_schema_warned = True
                    logger.warning(
                        "[config] %s has no %s section — those settings are IGNORED, "
                        "using code defaults (system: %s, local: %s)",
                        PRAX_LOGGER_CONFIG_FILE.name,
                        " or ".join(missing),
                        DEFAULT_SYSTEM_LOGS,
                        DEFAULT_LOCAL_LOGS,
                    )

                system_logs = {**DEFAULT_SYSTEM_LOGS, **_as_dict(section.get("system_logs"))}
                local_logs = {**DEFAULT_LOCAL_LOGS, **_as_dict(section.get("local_logs"))}

                result = {
                    "system_logs": system_logs,
                    "local_logs": local_logs,
                    "log_format": section.get("log_format", LOG_FORMAT),
                    "date_format": section.get("date_format", DATE_FORMAT),
                }
                return result
    except (json.JSONDecodeError, OSError) as e:
        logger.info(f"Log config load error (using defaults): {e}")

    return {
        "system_logs": DEFAULT_SYSTEM_LOGS,
        "local_logs": DEFAULT_LOCAL_LOGS,
        "log_format": LOG_FORMAT,
        "date_format": DATE_FORMAT,
    }
