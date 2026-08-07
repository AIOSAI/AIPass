# =================== AIPass ====================
# Name: load.py
# Description: Load Logging Configuration Handler
# Version: 1.1.0
# Created: 2025-11-07
# Modified: 2026-08-04
# =============================================

"""
Load Logging Configuration Handler

Loads logging configuration from prax_logger_config.json.
Returns configuration for system logs and local logs with fallback to defaults.

Features:
- Loads log config from prax_logger_config.json
- Returns system_logs and local_logs settings
- Fallback to code defaults if config missing
- Includes log_format and date_format
- Self-healing: auto-creates SYSTEM_LOGS_DIR if missing

Usage:
    from aipass.prax.apps.handlers.config.load import load_log_config

    config = load_log_config()
    system_logs = config['system_logs']
    max_lines = system_logs['max_lines']
"""

import inspect
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "load"

# Package path resolution (no hardcoded paths)
PRAX_ROOT = Path(__file__).resolve().parents[3]  # config/load.py → handlers/ → apps/ → prax/
ECOSYSTEM_ROOT = PRAX_ROOT.parent  # prax/ → aipass/ (contains all sibling modules)
PRAX_JSON_DIR = PRAX_ROOT / "prax_json"


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


def _is_pytest_session() -> bool:
    """Detect pytest session via sys.modules (immune to patch.dict(os.environ, clear=True))."""
    return "_pytest" in sys.modules


# Lazy SYSTEM_LOGS_DIR — resolved on first access, not at import time.
# Callers should use get_system_logs_dir() for guaranteed initialization.
_system_logs_dir_cache: Path | None = None


def get_system_logs_dir() -> Path:
    """Lazily resolve and create system_logs directory (package-relative).

    Central aggregation: all branches log here for system-wide monitoring.
    Per-module logs use get_module_logs_dir() for local debugging.
    """
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
        repo_root = _find_repo_root()
        _system_logs_dir_cache = repo_root / "system_logs"
        _system_logs_dir_cache.mkdir(parents=True, exist_ok=True)
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


def get_module_logs_dir(module_name: Optional[str] = None) -> Path:
    """Get the branch-root logs directory for a module.

    Checks ECOSYSTEM_ROOT (src/aipass/) first, then SRC_ROOT (src/) for
    branches that live outside the aipass namespace (e.g., commons). For
    cross-project dispatch, resolves paths relative to the caller's project
    root via AIPASS_CALLER_CWD (set by drone, DPLAN-0121) instead of
    ECOSYSTEM_ROOT. Falls back to system_logs/external/ for unknown modules —
    never creates new directories inside the AIPass source tree.

    This is the primary local log directory resolver for the two-tier
    model (system_logs/ for central aggregation + branch-root logs/
    for local debugging).

    Args:
        module_name: Module name (e.g., "flow", "prax", "commons").
                     Auto-detected from the calling module if not provided.

    Returns:
        Path to the module's logs directory
    """
    # Auto-detect caller module name when not provided
    if module_name is None:
        frame = inspect.stack()[1]
        module_name = Path(frame.filename).stem

    test_log_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_log_dir:
        p = Path(test_log_dir) / module_name
        p.mkdir(parents=True, exist_ok=True)
        return p
    if os.environ.get("PYTEST_CURRENT_TEST") or _is_pytest_session():
        p = Path(tempfile.gettempdir()) / "aipass_test_logs" / module_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    # Standard: src/aipass/{module}/logs
    branch_dir = ECOSYSTEM_ROOT / module_name
    if branch_dir.exists():
        logs_dir = branch_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    # Fallback: src/{module}/logs for branches outside aipass namespace
    src_root = ECOSYSTEM_ROOT.parent
    alt_branch_dir = src_root / module_name
    if alt_branch_dir.exists():
        logs_dir = alt_branch_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    # Cross-project dispatch: AIPASS_CALLER_CWD is set by drone router_handler
    # (DPLAN-0121). Walk up from the caller's CWD to find the project root
    # (.git or pyproject.toml), then log there rather than polluting ECOSYSTEM_ROOT
    # with directories for unknown/external modules (e.g. AIPL polyglot agents).
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

    # Final safe fallback: system_logs/external/ — never create unknown directories
    # inside the AIPass source tree. Fixes AIPL polyglot log leak (DPLAN-0125 Track G).
    logs_dir = get_system_logs_dir() / "external" / module_name
    logs_dir.mkdir(parents=True, exist_ok=True)
    _warn_routing(module_name, "system_logs/external/")
    return logs_dir


# Config file
PRAX_LOGGER_CONFIG_FILE = PRAX_JSON_DIR / "prax_logger_config.json"

# Default configuration constants
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_LEVEL = "INFO"

# backup_count raised 1 -> 3 on 2026-08-04. Retained history is not a fixed
# span: it swings between backup_count x threshold (just after a roll, when the
# live file is empty) and backup_count+1 x threshold (just before the next one).
# At 1 backup that is 200,000-400,000 bytes, so the bump triples the guaranteed
# floor and doubles the ceiling. Measured 2026-08-04: hooks_engine.log held
# 45 minutes across .log.1 + .log under fleet load; only 51 of 308 system logs
# have ever rotated at all, and just 4 of those retain under an hour, so this
# buys the hot tail without touching the quiet majority. Cost is a ~28 MB
# ceiling on a ~36 MB footprint.
#
# This does NOT rescue a true firehose — prax_event_queue.log kept 45 seconds
# during the 07-31 event-queue flood, and 3 backups only makes that ~2 minutes.
# Surviving that needs evidence capture at detection time, not a retention knob.
DEFAULT_SYSTEM_LOGS = {"max_lines": 1000, "backup_count": 3, "log_level": "INFO"}

DEFAULT_LOCAL_LOGS = {"max_lines": 250, "backup_count": 3, "log_level": "INFO"}

# Set once per process when the config file is present but missing its
# system_logs/local_logs sections — see load_log_config().
_config_schema_warned: bool = False

# =============================================
# HANDLER FUNCTIONS
# =============================================


def lines_to_bytes(num_lines: int, avg_line_length: int = 200) -> int:
    """Convert a line budget to a byte threshold for log rotation.

    The 200-byte default is a deliberate over-estimate, not a measurement.
    Real lines across system_logs/ average 115 bytes (median per-file 116, as
    measured 2026-08-04 over 301 files), so ``max_lines`` behaves as a floor:
    a 1000-line budget retains roughly 1,700 typical lines. That is the point.
    31 files average above 200 bytes/line and one reaches 700, and for those a
    tighter estimate would starve the line budget rather than honour it.

    So do not "correct" this to the observed average. Lowering it shrinks every
    log's byte budget — 200,000 to 115,000 bytes for system logs — which
    narrows the retention window instead of widening it. To retain more, raise
    ``max_lines`` or ``backup_count``; both change bytes in the intended
    direction.

    Args:
        num_lines: Line budget to convert.
        avg_line_length: Bytes per line to assume. Default 200, intentionally
            above the observed 115 so verbose logs still get their lines.

    Returns:
        Byte threshold for the rotating handler.
    """
    return num_lines * avg_line_length


def get_debug_prints_enabled() -> bool:
    """Check if debug prints are enabled in config

    Returns:
        True if debug prints enabled, False otherwise
    """
    try:
        if PRAX_LOGGER_CONFIG_FILE.exists():
            with open(PRAX_LOGGER_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config.get("config", {}).get("debug_prints_enabled", False)
    except (json.JSONDecodeError, OSError) as e:
        logger.info(f"Config load error (using defaults): {e}")
    return False


def load_log_config() -> Dict[str, Any]:
    """Load logging config from JSON, fallback to defaults

    Returns:
        Dict with system_logs and local_logs settings:
        {
            "system_logs": {
                "max_lines": 1000,
                "backup_count": 3,
                "log_level": "INFO"
            },
            "local_logs": {
                "max_lines": 250,
                "backup_count": 3,
                "log_level": "INFO"
            },
            "log_format": "%(asctime)s - ...",
            "date_format": "%Y-%m-%d %H:%M:%S"
        }

    If config file missing or invalid, returns code defaults. A config file that
    exists but omits the system_logs/local_logs sections also gets code defaults,
    and warns once per process rather than falling back silently.

    Example:
        >>> config = load_log_config()
        >>> max_lines = config['system_logs']['max_lines']
        >>> print(f"System logs max lines: {max_lines}")
    """
    global _config_schema_warned
    try:
        if PRAX_LOGGER_CONFIG_FILE.exists():
            with open(PRAX_LOGGER_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)

                # A config file that exists but carries neither key silently
                # yields code defaults, so anyone reading it believes settings
                # are live that never reach a handler. Found 2026-08-04: the
                # file create_config_file() generates (prax_json/ is gitignored,
                # so this is per-install, not in git) declared backup_count=5 and
                # max_log_size_mb=10 at the top level of "config", where nothing
                # reads them — effective retention was 1 backup of 200,000 bytes,
                # 250x less than the file advertised. Say so instead of falling
                # back quietly. Guarded to once per process: this runs on every
                # logger init fleet-wide, and prax's own log is inside the
                # directory prax watches (see DPLAN-0280).
                section = config.get("config", {})
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

                # Extract system and local log settings
                system_logs = section.get("system_logs", DEFAULT_SYSTEM_LOGS)
                local_logs = section.get("local_logs", DEFAULT_LOCAL_LOGS)

                result = {
                    "system_logs": system_logs,
                    "local_logs": local_logs,
                    "log_format": section.get("log_format", LOG_FORMAT),
                    "date_format": section.get("date_format", DATE_FORMAT),
                }
                json_handler.log_operation("config_loaded", {"source": str(PRAX_LOGGER_CONFIG_FILE)})
                return result
    except (json.JSONDecodeError, OSError) as e:
        logger.info(f"Log config load error (using defaults): {e}")

    # Fallback to code defaults
    return {
        "system_logs": DEFAULT_SYSTEM_LOGS,
        "local_logs": DEFAULT_LOCAL_LOGS,
        "log_format": LOG_FORMAT,
        "date_format": DATE_FORMAT,
    }
