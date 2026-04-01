# =================== AIPass ====================
# Name: backup_models.py
# Description: Backup data models and structures
# Version: 2.0.1
# Created: 2025-11-16
# Modified: 2026-03-09
# =============================================

"""
Backup Data Models

Shared data structures used across all backup modules.
Simple data containers with no complex logic or dependencies.
Implements pure data model pattern following seedgo architecture standards.
"""

# =============================================
# IMPORTS
# =============================================

from pathlib import Path
import datetime
from typing import List

from aipass.backup.apps.handlers.json import json_handler

# =============================================
# DATA MODELS
# =============================================


class BackupResult:
    """Result of a backup operation

    Tracks statistics and errors for backup operations.
    Used by all modules to report success/failure and collect metrics.

    Attributes:
        files_checked (int): Number of files checked during backup
        files_copied (int): Number of files successfully copied
        files_added (int): New files added in versioned mode
        files_skipped (int): Number of files skipped
        files_deleted (int): Number of files deleted
        errors (int): Total error count
        error_details (List[str]): Detailed error messages
        warnings (List[str]): Non-critical warnings
        critical_errors (List[str]): Critical errors that failed the backup
        start_time (datetime.datetime): When backup operation started
        backup_path (str): Path to backup destination
        mode (str): Backup mode (e.g., 'full', 'versioned')
        success (bool): Overall success status of backup
    """

    def __init__(self):
        json_handler.log_operation("backup_result_created")
        # File statistics
        self.files_checked: int = 0
        self.files_copied: int = 0
        self.files_added: int = 0      # New files added (versioned mode)
        self.files_skipped: int = 0
        self.files_deleted: int = 0

        # Error tracking
        self.errors: int = 0
        self.error_details: List[str] = []
        self.warnings: List[str] = []
        self.critical_errors: List[str] = []

        # Metadata
        self.start_time = datetime.datetime.now()
        self.backup_path: str = ""
        self.mode: str = ""
        self.success: bool = True

    def add_error(self, error_msg: str, is_critical: bool = False):
        """Add an error to the result

        Args:
            error_msg: Error message describing what failed
            is_critical: If True, marks entire backup as failed
        """
        self.errors += 1
        self.error_details.append(error_msg)
        if is_critical:
            self.critical_errors.append(error_msg)
            self.success = False

    def add_warning(self, warning_msg: str):
        """Add a warning to the result

        Args:
            warning_msg: Warning message for non-critical issues
        """
        self.warnings.append(warning_msg)

# =============================================
# MODULE INITIALIZATION
# =============================================

# Pure data models - no initialization needed
