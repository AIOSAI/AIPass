# =================== AIPass ====================
# Name: operations.py
# Description: Logging Operations
# Version: 1.1.0
# Created: 2025-11-10
# Modified: 2026-10-17
# =============================================

"""PRAX Logging Operations"""

import json
from datetime import datetime, timezone
from typing import Dict, Optional

from aipass.prax.apps.handlers.config.load import (
    DEFAULT_LOCAL_LOGS,
    DEFAULT_SYSTEM_LOGS,
    PRAX_JSON_DIR,
)
from aipass.prax.apps.handlers.logging.direct import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

MODULE_NAME = "prax_logger"
CONFIG_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_config.json"
DATA_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_data.json"
LOG_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_log.json"


def log_operation(message: str, data: Optional[Dict] = None):
    """Log prax_logging operations to JSON log file"""
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "operation": message, "data": data or {}}

    log_entries = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log_entries = json.load(f)
        except Exception as e:
            logger.warning("Failed to load log file %s, resetting entries: %s", LOG_FILE, e)
            log_entries = []

    log_entries.append(entry)

    if len(log_entries) > 1000:
        log_entries = log_entries[-1000:]

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, indent=2, ensure_ascii=False)
    json_handler.log_operation("log_operation_performed", {"message": message})


def create_config_file():
    """Create default config file if it doesn't exist"""
    if not CONFIG_FILE.exists():
        # Every key must be one a reader looks for: load_log_config() reads config.system_logs
        # and config.local_logs, get_debug_prints_enabled() reads debug_prints_enabled. A key
        # nothing reads looks like configuration but changes nothing. Sections come from
        # load.py's constants so the file cannot drift from the defaults it mirrors.
        default_config = {
            "module_name": MODULE_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "system_logs": dict(DEFAULT_SYSTEM_LOGS),
                "local_logs": dict(DEFAULT_LOCAL_LOGS),
                "log_format": "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "debug_prints_enabled": False,
            },
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            logger.info("Config file created: %s", CONFIG_FILE)
        except Exception as e:
            logger.warning("Failed to create config file: %s", e)
