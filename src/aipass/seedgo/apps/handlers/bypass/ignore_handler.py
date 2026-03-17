# =================== AIPass ====================
# Name: ignore_handler.py
# Description: Business Logic Detection Ignore Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Business Logic Detection Ignore Handler

Provides ignore patterns for the modules checker to skip known acceptable patterns
in business logic detection. Helps reduce false positives.

Pure configuration with helper functions for pattern access and filtering.
"""

# =============================================
# IMPORTS
# =============================================

from pathlib import Path
from typing import List, Set, Optional
import fnmatch

from aipass.seedgo.apps.handlers.json import json_handler

# =============================================
# AIPASS_ROOT PATTERN
# =============================================


# =============================================
# IGNORE PATTERNS
# =============================================

# Variable names to ignore in business logic detection
# Start minimal - add patterns as we discover false positives
IGNORE_PATTERNS = [
    # Common configuration/constant patterns
    # "CONFIG_*",  # Example: CONFIG_FILE, CONFIG_PATH
    # "*_CONFIG",  # Example: DATABASE_CONFIG, API_CONFIG

    # Common metadata patterns
    # "METADATA",
    # "*_METADATA",

    # Version/build info patterns
    # "VERSION",
    # "BUILD_*",

    # Add patterns here as we discover false positives
]

# File-specific exceptions
# Format: {file_path_pattern: [variable_names]}
FILE_SPECIFIC_IGNORES = {
    # Example: "*/config.py": ["DATABASE_URL", "API_KEY"],
}

# =============================================
# TEMPLATE IGNORE PATTERNS
# =============================================

# Template files that exist in spawn template but aren't required in branches
# Used by architecture_check.py when checking template baseline
TEMPLATE_IGNORE_PATTERNS = [
    '.gitkeep',       # Git placeholder files - not actual requirements
    'notepad.md',     # Optional scratch file
    '.gitignore',     # Optional - branches inherit from root
]

# =============================================
# AUDIT IGNORE PATTERNS
# =============================================

# Patterns for files/directories to skip during audit
# Used by standards_audit.py
AUDIT_IGNORE_PATTERNS = [
    '__pycache__',
    '/.archive/',      # Temp archive directories
    '/.backup/',       # Temp backup directories
    '/backups/',       # Actual backup storage (backup_system/backups/)
    '/artifacts/',     # Build artifacts
    '.temp',           # Temp files
    '.old',            # Old files
    '/deprecated/',    # Deprecated code
    '/test/'           # Test directories
]

# =============================================
# DEPRECATED PATTERNS
# =============================================

# Patterns that have been removed from the system
# Used by standards_verify.py to detect leftover usage
DEPRECATED_PATTERNS = {
    "--verbose": "removed from audit (v0.4.0)",
    "--full": "removed from audit (v0.4.0)"
}

# =============================================
# HELPER FUNCTIONS
# =============================================

def get_ignore_patterns() -> List[str]:
    """Return list of variable names to ignore in business logic detection

    Returns:
        Copy of ignore patterns list

    Example:
        patterns = get_ignore_patterns()
        for pattern in patterns:
            if fnmatch.fnmatch(var_name, pattern):
                # Skip this variable
    """
    json_handler.log_operation("ignore_patterns_loaded", {"count": len(IGNORE_PATTERNS)})
    return IGNORE_PATTERNS.copy()


def get_template_ignore_patterns() -> List[str]:
    """Return list of template files to skip in architecture baseline check

    Returns:
        Copy of template ignore patterns list

    Example:
        patterns = get_template_ignore_patterns()
        if template_name in patterns:
            # Skip this template file
    """
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
    return DEPRECATED_PATTERNS.copy()


def should_ignore_variable(var_name: str, file_path: str = "") -> bool:
    """Check if a variable should be ignored in business logic detection

    Checks both global ignore patterns and file-specific exceptions.

    Args:
        var_name: Variable name to check
        file_path: Optional file path for file-specific rules

    Returns:
        True if variable should be ignored, False otherwise

    Example:
        if should_ignore_variable("CONFIG_FILE", "/path/to/module.py"):
            # Skip this variable
    """
    # Check global ignore patterns
    for pattern in IGNORE_PATTERNS:
        if fnmatch.fnmatch(var_name, pattern):
            return True

    # Check file-specific ignores if file_path provided
    if file_path:
        for path_pattern, var_patterns in FILE_SPECIFIC_IGNORES.items():
            if fnmatch.fnmatch(file_path, path_pattern):
                for var_pattern in var_patterns:
                    if fnmatch.fnmatch(var_name, var_pattern):
                        return True

    return False


def add_ignore_pattern(pattern: str) -> None:
    """Add a new ignore pattern to the list

    Helper function for testing or dynamic pattern addition.

    Args:
        pattern: Glob-style pattern to add (e.g., "CONFIG_*")

    Example:
        add_ignore_pattern("TEMP_*")
    """
    if pattern not in IGNORE_PATTERNS:
        IGNORE_PATTERNS.append(pattern)


def add_file_specific_ignore(file_pattern: str, var_patterns: List[str]) -> None:
    """Add file-specific ignore patterns

    Helper function for testing or dynamic pattern addition.

    Args:
        file_pattern: File path pattern (e.g., "*/config.py")
        var_patterns: List of variable patterns for this file

    Example:
        add_file_specific_ignore("*/settings.py", ["SECRET_KEY", "DATABASE_URL"])
    """
    if file_pattern in FILE_SPECIFIC_IGNORES:
        FILE_SPECIFIC_IGNORES[file_pattern].extend(var_patterns)
    else:
        FILE_SPECIFIC_IGNORES[file_pattern] = var_patterns


def get_file_specific_ignores(file_path: str) -> List[str]:
    """Get all variable patterns that should be ignored for a specific file

    Args:
        file_path: File path to check

    Returns:
        List of variable patterns to ignore for this file

    Example:
        ignores = get_file_specific_ignores("/path/to/config.py")
    """
    patterns = []
    for path_pattern, var_patterns in FILE_SPECIFIC_IGNORES.items():
        if fnmatch.fnmatch(file_path, path_pattern):
            patterns.extend(var_patterns)
    return patterns


# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure configuration
