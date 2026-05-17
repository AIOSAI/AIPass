# =================== AIPass ====================
# Name: ignore_handler.py
# Description: Ignore Pattern Configuration Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Ignore Pattern Configuration Handler

Provides ignore patterns for audit file filtering, template baseline checking,
and deprecated pattern tracking. Pure configuration with helper functions.
"""

# =============================================
# IMPORTS
# =============================================

from typing import List

from aipass.seedgo.apps.handlers.json import json_handler

# =============================================
# TEMPLATE IGNORE PATTERNS
# =============================================

# Template files that exist in spawn template but aren't required in branches
# Used by architecture_check.py when checking template baseline
TEMPLATE_IGNORE_PATTERNS = [
    ".gitkeep",  # Git placeholder files - not actual requirements
    "notepad.md",  # Optional scratch file
    ".gitignore",  # Optional - branches inherit from root
]

# =============================================
# AUDIT IGNORE PATTERNS
# =============================================

# Patterns for files/directories to skip during audit
# Used by standards_audit.py
AUDIT_IGNORE_PATTERNS = [
    "__pycache__",
    "/.archive/",  # Temp archive directories
    "/.backup/",  # Temp backup directories
    "/backups/",  # Actual backup storage (backup/backups/)
    "/artifacts/",  # Build artifacts
    "/integrations/",  # Private integrations (gitignored content)
    ".temp",  # Temp files
    ".old",  # Old files
    "/deprecated/",  # Deprecated code
    "/test/",  # Test directories
]

# =============================================
# DEPRECATED PATTERNS
# =============================================

# Patterns that have been removed from the system
# Used by standards_verify.py to detect leftover usage
DEPRECATED_PATTERNS = {"--verbose": "removed from audit (v0.4.0)", "--full": "removed from audit (v0.4.0)"}

# =============================================
# HELPER FUNCTIONS
# =============================================


def get_template_ignore_patterns() -> List[str]:
    """Return list of template files to skip in architecture baseline check

    Returns:
        Copy of template ignore patterns list

    Example:
        patterns = get_template_ignore_patterns()
        if template_name in patterns:
            # Skip this template file
    """
    json_handler.log_operation("config_accessed", {"config": "template_ignore_patterns"})
    return TEMPLATE_IGNORE_PATTERNS.copy()


def get_audit_ignore_patterns() -> List[str]:
    """Return list of patterns for files/directories to skip during audit

    Returns:
        Copy of audit ignore patterns list

    Example:
        patterns = get_audit_ignore_patterns()
        if any(pattern in file_path for pattern in patterns):
            # Skip this file
    """
    json_handler.log_operation("config_accessed", {"config": "audit_ignore_patterns"})
    return AUDIT_IGNORE_PATTERNS.copy()


def get_deprecated_patterns() -> dict:
    """Return dict of deprecated patterns and their removal reasons

    Returns:
        Copy of deprecated patterns dict

    Example:
        patterns = get_deprecated_patterns()
        for pattern, reason in patterns.items():
            # Check if pattern exists in codebase
    """
    json_handler.log_operation("config_accessed", {"config": "deprecated_patterns"})
    return DEPRECATED_PATTERNS.copy()


# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure configuration
