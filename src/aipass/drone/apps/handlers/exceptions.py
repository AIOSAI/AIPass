# =================== AIPass ====================
# Name: exceptions.py
# Description: Custom exceptions for routing and branch resolution
# Version: 1.1.0
# Created: 2026-03-09
# Modified: 2026-11-15
# =============================================

"""
Drone module custom exceptions.
"""

# Logs nothing at import: a module-level write fires during pytest collection, before any seam.


class RoutingError(Exception):
    """Base exception for all routing-related errors."""

    pass


class BranchNotFoundError(RoutingError):
    """Raised when a branch cannot be found in the registry."""

    pass


class BranchAlreadyExistsError(RoutingError):
    """Raised when attempting to register a branch that already exists."""

    pass


class InvalidPathError(RoutingError):
    """Raised when a path is invalid or doesn't exist."""

    pass


class RegistryError(RoutingError):
    """Base exception for registry-related errors."""

    pass


class RegistryNotFoundError(RegistryError):
    """Raised when the registry file doesn't exist."""

    pass


class RegistryMismatchError(RegistryError):
    """Raised when registry credential doesn't match caller's passport; never fall back on it."""

    pass


class RegistryCorruptError(RegistryError):
    """Raised when the registry file is corrupted or invalid JSON."""

    pass


class RegistryPermissionError(RegistryError):
    """Raised when there are permission issues accessing the registry."""

    pass


class CommandExecutionError(RoutingError):
    """Raised when command execution fails."""

    pass


class RepoRootError(RoutingError):
    """Raised when the caller's directory is inside no git repository and below no *_REGISTRY.json."""

    pass
