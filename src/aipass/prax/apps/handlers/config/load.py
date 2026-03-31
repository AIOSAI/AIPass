# =================== AIPass ====================
# Name: load.py
# Description: Load Logging Configuration Handler
# Version: 1.0.1
# Created: 2025-11-07
# Modified: 2026-03-09
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

import json
import logging
import os
logger = logging.getLogger(__name__)
from pathlib import Path
from typing import Dict, Any

from aipass.prax.apps.handlers.json import json_handler

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
    global _system_logs_dir_cache
    if _system_logs_dir_cache is None:
        repo_root = _find_repo_root()
        _system_logs_dir_cache = repo_root / "system_logs"
        _system_logs_dir_cache.mkdir(parents=True, exist_ok=True)
    return _system_logs_dir_cache


def get_module_logs_dir(module_name: str) -> Path:
    """Get the branch-root logs directory for a module.

    Checks ECOSYSTEM_ROOT (src/aipass/) first, then SRC_ROOT (src/) for
    branches that live outside the aipass namespace (e.g., commons).
    This is the primary local log directory resolver for the two-tier
    model (system_logs/ for central aggregation + branch-root logs/
    for local debugging).

    Args:
        module_name: Module name (e.g., "flow", "prax", "commons")

    Returns:
        Path to the module's branch-root logs directory
    """
    test_log_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_log_dir:
        p = Path(test_log_dir) / module_name
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

    # Default: create under ECOSYSTEM_ROOT (original behavior for new branches)
    logs_dir = branch_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir

# Config file
PRAX_LOGGER_CONFIG_FILE = PRAX_JSON_DIR / "prax_logger_config.json"

# Default configuration constants
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
DEFAULT_LOG_LEVEL = "INFO"

DEFAULT_SYSTEM_LOGS = {
    "max_lines": 1000,
    "backup_count": 1,
    "log_level": "INFO"
}

DEFAULT_LOCAL_LOGS = {
    "max_lines": 250,
    "backup_count": 1,
    "log_level": "INFO"
}

# =============================================
# HANDLER FUNCTIONS
# =============================================

def lines_to_bytes(num_lines: int, avg_line_length: int = 200) -> int:
    """Convert number of lines to approximate bytes for log rotation

    Args:
        num_lines: Number of lines to convert
        avg_line_length: Average line length in characters (default 200)

    Returns:
        Approximate number of bytes
    """
    return num_lines * avg_line_length

def get_debug_prints_enabled() -> bool:
    """Check if debug prints are enabled in config

    Returns:
        True if debug prints enabled, False otherwise
    """
    try:
        if PRAX_LOGGER_CONFIG_FILE.exists():
            with open(PRAX_LOGGER_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get('config', {}).get('debug_prints_enabled', False)
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
                "backup_count": 1,
                "log_level": "INFO"
            },
            "local_logs": {
                "max_lines": 250,
                "backup_count": 1,
                "log_level": "INFO"
            },
            "log_format": "%(asctime)s - ...",
            "date_format": "%Y-%m-%d %H:%M:%S"
        }

    If config file missing or invalid, returns code defaults.

    Example:
        >>> config = load_log_config()
        >>> max_lines = config['system_logs']['max_lines']
        >>> print(f"System logs max lines: {max_lines}")
    """
    try:
        if PRAX_LOGGER_CONFIG_FILE.exists():
            with open(PRAX_LOGGER_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)

                # Extract system and local log settings
                system_logs = config.get('config', {}).get('system_logs', DEFAULT_SYSTEM_LOGS)
                local_logs = config.get('config', {}).get('local_logs', DEFAULT_LOCAL_LOGS)

                result = {
                    'system_logs': system_logs,
                    'local_logs': local_logs,
                    'log_format': config.get('config', {}).get('log_format', LOG_FORMAT),
                    'date_format': config.get('config', {}).get('date_format', DATE_FORMAT)
                }
                json_handler.log_operation("config_loaded", {"source": str(PRAX_LOGGER_CONFIG_FILE)})
                return result
    except (json.JSONDecodeError, OSError) as e:
        logger.info(f"Log config load error (using defaults): {e}")

    # Fallback to code defaults
    return {
        'system_logs': DEFAULT_SYSTEM_LOGS,
        'local_logs': DEFAULT_LOCAL_LOGS,
        'log_format': LOG_FORMAT,
        'date_format': DATE_FORMAT
    }
