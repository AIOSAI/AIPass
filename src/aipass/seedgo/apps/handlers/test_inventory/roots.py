# =================== AIPass ====================
# Name: roots.py
# Description: turn a target argument into the tree the inventory walks
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
WHICH TREE GETS WALKED.

    aipass          the whole fleet - the directory the registry lives in
    @branch         one registered citizen
    <path>          any directory, registered or not

A TARGET THAT DOES NOT RESOLVE RAISES. It never falls back to the current
directory: a report that silently measured the wrong tree would publish a
confidently wrong number under the right heading, and the reader has no way to
tell. The same rule the audit-tests lane already follows, for the same reason.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from aipass.seedgo.apps.handlers import registry_scan

#: The argument that means "every citizen, one tree".
FLEET_ARGUMENT = "aipass"


@dataclass
class Root:
    """The tree to walk, its label, and how the argument reached it."""

    name: str
    path: Path
    resolved_from: str


def resolve(argument: str, branch_paths: Optional[Dict[str, Path]] = None) -> Root:
    """The tree a target argument names.

    `branch_paths` is supplied by the caller rather than read here, so this
    module resolves a name without importing the registry and stays testable
    on a machine that has none.
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
