"""Drone modules — business logic for command routing."""

from aipass.drone.apps.modules.resolver import normalize_branch_arg
from aipass.drone.apps.handlers.exceptions import (
    BranchAlreadyExistsError,
    BranchNotFoundError,
    CommandExecutionError,
    InvalidPathError,
    RegistryCorruptError,
    RegistryError,
    RegistryMismatchError,
    RegistryNotFoundError,
    RegistryPermissionError,
    RepoRootError,
    RoutingError,
)
from aipass.drone.apps.handlers.executor import CommandResult

__all__ = [
    "normalize_branch_arg",
    "BranchAlreadyExistsError",
    "BranchNotFoundError",
    "CommandExecutionError",
    "CommandResult",
    "InvalidPathError",
    "RegistryCorruptError",
    "RegistryError",
    "RegistryMismatchError",
    "RegistryNotFoundError",
    "RegistryPermissionError",
    "RepoRootError",
    "RoutingError",
]
