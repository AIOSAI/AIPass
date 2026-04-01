# =================== AIPass ====================
# Name: config_handler.py
# Description: Backup configuration — modes and destinations
# Version: 3.0.0
# Created: 2025-11-23
# Modified: 2026-03-14
# =============================================

"""
Backup Configuration Handler

Centralized configuration management for backup.
Contains backup modes, destinations, and configuration constants.

Ignore patterns and pattern-matching functions have been extracted to
ignore_patterns.py (FPLAN-0037) and are re-exported here for backwards
compatibility.
"""

# =============================================
# IMPORTS
# =============================================

from pathlib import Path

from aipass.backup.apps.handlers.json import json_handler

# Re-export from ignore_patterns for backwards compatibility
from aipass.backup.apps.handlers.config.ignore_patterns import (
    GLOBAL_IGNORE_PATTERNS, IGNORE_EXCEPTIONS, should_ignore,
    filter_tracked_items, get_ignore_patterns, get_cli_tracking_patterns,
    DIFF_IGNORE_PATTERNS, DIFF_INCLUDE_PATTERNS, CLI_TRACKING_PATTERNS,
    SOURCE_WHITELIST, MAX_FILE_SIZE_MB
)

# =============================================
# CONFIGURATION CONSTANTS
# =============================================

# Base backup directory - dynamically determined relative to branch root
# Module is in apps/handlers/config/, so parent.parent.parent.parent gets to branch root
BASE_BACKUP_DIR = str(Path(__file__).parent.parent.parent.parent / "backups")

# Specific backup destinations for each system
BACKUP_DESTINATIONS = {
    "system_snapshot": f"{BASE_BACKUP_DIR}",
    "versioned_backup": f"{BASE_BACKUP_DIR}",
}

# =============================================
# BACKUP MODE CONFIGURATIONS
# =============================================

BACKUP_MODES = {
    'snapshot': {
        'name': 'System Snapshot',
        'description': 'Dynamic instant backup (overwrites previous)',
        'destination': BACKUP_DESTINATIONS["system_snapshot"],
        'folder_name': 'system_snapshot',
        'behavior': 'dynamic',  # overwrites previous
        'usage': 'Quick saves before changes'
    },
    'versioned': {
        'name': 'Versioned Backup',
        'description': 'Cumulative version history (keeps all file versions)',
        'destination': BACKUP_DESTINATIONS["versioned_backup"],
        'folder_name': 'versioned_backup',
        'behavior': 'versioned',  # keeps all versions
        'usage': 'Complete file version history in single location'
    },
}

# =============================================
# MODULE INITIALIZATION
# =============================================

json_handler.log_operation("config_handler_loaded")
