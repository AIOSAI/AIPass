# =================== AIPass ====================
# Name: roots.py
# Description: turn a target argument into the tree the inventory walks
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""WHICH TREE GETS WALKED.

A target that does not resolve raises; it never falls back to the current directory.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from aipass.seedgo.apps.handlers import registry_scan

FLEET_ARGUMENT = "aipass"


@dataclass
class Root:
    """The tree to walk, its label, and how the argument reached it."""

    name: str
    path: Path
    resolved_from: str


def resolve(argument: str, branch_paths: Optional[Dict[str, Path]] = None) -> Root:
    """The tree a target argument names.

    `branch_paths` comes from the caller so this stays testable without a registry.
    """
    if argument == FLEET_ARGUMENT:
        repo = fleet_root()
        return Root(name=FLEET_ARGUMENT, path=repo, resolved_from=f"the registry beside {repo}")

    if argument.startswith("@"):
        return _branch(argument[1:], branch_paths or {})

    return _directory(argument)


def fleet_root() -> Path:
    """The directory the registry sits in - the whole fleet, one tree."""
    return registry_scan.find_registry().parent


def _branch(name: str, branch_paths: Dict[str, Path]) -> Root:
    """One registered citizen, matched case-insensitively on its name."""
    wanted = name.casefold()
    for candidate, path in branch_paths.items():
        if candidate.casefold() == wanted:
            return Root(name=candidate, path=Path(path), resolved_from=f"registry entry for '{candidate}'")

    raise ValueError(f"'@{name}' is not a registered branch - pass a directory path to measure something else")


def _directory(argument: str) -> Root:
    """Any directory on disk, registered or not."""
    path = Path(argument).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"target path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"target must be a directory, not a file: {path}")

    resolved = path.resolve()
    return Root(name=resolved.name, path=resolved, resolved_from=f"filesystem path {resolved}")
