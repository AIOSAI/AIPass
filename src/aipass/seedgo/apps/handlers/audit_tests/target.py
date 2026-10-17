# =================== AIPass ====================
# Name: target.py
# Description: audit-tests target resolution - @branch or any directory
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""Target resolution. The lane points at a registered branch OR at any directory."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.json import json_handler

PATH_HASH_LENGTH = 8

#: The lane measures branch-rootdir serial, not CI; the artifact says so in words.
CONFIG_NOTE = (
    "branch-rootdir SERIAL: pytest is run from the target's own root under its "
    "own pytest.ini, one process, no xdist. This is NOT the CI configuration "
    "(--rootdir=. --ignore=tests/e2e -n auto --dist loadscope), and the two "
    "execute different test orders. Serial is a ruling, not a default: it is "
    "the cheap REVERSIBLE one, because moving to xdist is per-worker gate logs "
    "in the adapter and never a core change."
)


@dataclass
class Target:
    """A resolved measurement target."""

    name: str
    path: Path
    kind: str
    resolved_from: str
    layout: str = "unknown"
    unit_count: int = 0
    config_note: str = CONFIG_NOTE
    notes: List[str] = field(default_factory=list)

    @property
    def is_registry_branch(self) -> bool:
        """True if this target is a registered citizen branch."""
        return self.kind == "branch"

    def artifact_name(self) -> str:
        """The artifact filename stem for this target.

        Non-registry targets carry a path hash: two projects named `src` must not overwrite each other.
        """
        if self.is_registry_branch:
            return f"audit_tests_{self.name}"

        digest = hashlib.sha256(str(self.path.resolve()).encode("utf-8")).hexdigest()
        return f"audit_tests_{self.name}_{digest[:PATH_HASH_LENGTH]}"

    def to_document(self) -> dict:
        """The artifact's `target` block."""
        return {
            "name": self.name,
            "path": str(self.path),
            "kind": self.kind,
            "layout": self.layout,
            "unit_count": self.unit_count,
            "resolved_from": self.resolved_from,
            "config_note": self.config_note,
            "notes": list(self.notes),
        }


def _canonical_branch(name: str, branch_paths: Dict[str, Path]) -> str:
    """The registry's own spelling of a branch name. Raises if it has none.

    Returns the canonical spelling so two capitalisations never yield two artifacts;
    an ambiguous case-insensitive match raises rather than guessing.
    """
    if name in branch_paths:
        return name

    matches = sorted(known for known in branch_paths if known.lower() == name.lower())
    if len(matches) == 1:
        return matches[0]

    json_handler.log_operation("target_unresolved", {"argument": f"@{name}", "candidates": matches})
    if matches:
        raise ValueError(f"'@{name}' matches more than one registered branch ({', '.join(matches)}) - name one exactly")
    raise ValueError(
        f"'@{name}' is not a registered branch - pass a directory path to measure something outside the registry"
    )


def resolve(argument: str, branch_paths: Optional[Dict[str, Path]] = None) -> Target:
    """Resolve a command-line target argument into a Target.

    The caller supplies `branch_paths` so this module never imports the registry.
    Unresolvable targets raise; never fall back to cwd and measure the wrong tree.
    """
    branch_paths = branch_paths or {}

    if argument.startswith("@"):
        name = _canonical_branch(argument[1:], branch_paths)
        return Target(
            name=name,
            path=Path(branch_paths[name]),
            kind="branch",
            resolved_from=f"registry entry for '{name}'",
        )

    path = Path(argument).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"target path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"target must be a directory, not a file: {path}")

    resolved = path.resolve()
    return Target(
        name=resolved.name,
        path=resolved,
        kind="directory",
        resolved_from=f"filesystem path {resolved}",
    )


def describe_layout(target: Target) -> str:
    """Best-effort layout label, recorded rather than acted on (`detect()` decides what runs)."""
    if (target.path / "pytest.ini").exists():
        return "pytest.ini at root"
    if (target.path / "tests").is_dir():
        return "tests/ directory, no pytest.ini"
    if (target.path / "pyproject.toml").exists():
        return "pyproject.toml, no tests/ directory"
    return "unrecognised"
