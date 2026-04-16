# =================== AIPass ====================
# Name: operations.py
# Description: Logging Operations
# Version: 1.0.0
# Created: 2025-11-10
# Modified: 2026-03-09
# =============================================

"""
PRAX Logging Operations

Operation logging and configuration management for prax logger.
"""

import json
from datetime import datetime, timezone
from typing import Dict, Optional

# Import from prax config
from aipass.prax.apps.handlers.config.load import PRAX_JSON_DIR
from aipass.prax.apps.handlers.logging.direct import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler

logger = get_direct_logger()

# Module constants
MODULE_NAME = "prax_logger"
CONFIG_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_config.json"
DATA_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_data.json"
LOG_FILE = PRAX_JSON_DIR / f"{MODULE_NAME}_log.json"


def log_operation(message: str, data: Optional[Dict] = None):
    """Log prax_logging operations to JSON log file

    Args:
        message: Operation description
        data: Optional operation data dict
    """
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "operation": message, "data": data or {}}

    # Load existing log
    log_entries = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                log_entries = json.load(f)
        except Exception as e:
            logger.warning("Failed to load log file %s, resetting entries: %s", LOG_FILE, e)
            log_entries = []

    # Add new entry
    log_entries.append(entry)

    # Keep only last 1000 entries
    if len(log_entries) > 1000:
        log_entries = log_entries[-1000:]

    # Save log
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_entries, f, indent=2, ensure_ascii=False)
    json_handler.log_operation("log_operation_performed", {"message": message})


def create_config_file():
    """Create default config file if it doesn't exist"""
    if not CONFIG_FILE.exists():
        default_config = {
            "module_name": MODULE_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "log_level": "INFO",
                "max_log_size_mb": 10,
                "backup_count": 5,
                "log_format": "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "console_output": True,
                "file_output": True,
                "rotation_enabled": True,
                "debug_prints": False,
                "log_directories": ["system_logs", "skill_logs", "error_logs"],
            },
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            logger.info("Config file created: %s", CONFIG_FILE)
        except Exception as e:
            logger.warning("Failed to create config file: %s", e)
