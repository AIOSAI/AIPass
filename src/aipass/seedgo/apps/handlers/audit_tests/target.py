# =================== AIPass ====================
# Name: target.py
# Description: audit-tests target resolution - @branch or any directory
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
Target resolution. The lane points at a registered branch OR at any directory.

Two shapes, one resolver:

  * `@backup`      - a registry branch. The name is unique by construction, so
                     the artifact filename is the bare name.
  * `/some/path`   - any directory, including one outside the repo. Two
                     unrelated projects can both be called `src` or `tests`,
                     so an external target's artifact name carries an 8-char
                     hash of its RESOLVED ABSOLUTE PATH. Without it, the second
                     project silently overwrites the first's measurement.

`config_note` is a rev-4 requirement (design section 9.2). The lane measures
the branch-rootdir SERIAL configuration, and that is deliberately NOT the CI
configuration (`--rootdir=. -n auto --dist loadscope`). A reader who assumed
the number described CI would be wrong, and TAXONOMY section 5 rule 1 is
explicit that a hygiene gate measuring a configuration nobody uses is worse
than none. So the artifact says which one it measured, in words.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from aipass.seedgo.apps.handlers.json import json_handler

#: How many characters of the path hash an external target's name carries.
PATH_HASH_LENGTH = 8

#: The configuration this lane measures, stated in words for the artifact.
#: Rev 4, boardroom Q-C settlement plus @aipass's N5 note.
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

        A registry branch keeps its bare name. Anything else carries a hash of
        the resolved absolute path, so two external projects with the same
        directory name cannot overwrite each other's measurement.
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


# =============================================================================
# RESOLUTION
# =============================================================================


def resolve(argument: str, branch_paths: Optional[Dict[str, Path]] = None) -> Target:
    """Resolve a command-line target argument into a Target.

    `branch_paths` maps branch name to path; the caller supplies it so this
    module never imports the registry and stays testable without one.

    Raises FileNotFoundError when a path target does not exist, and ValueError
    when an `@name` does not resolve — both fail loudly rather than falling
    back to the current directory, because a lane that silently measures the
    wrong tree publishes a confidently wrong number.
    """
    branch_paths = branch_paths or {}

    if argument.startswith("@"):
        name = argument[1:]
        if name not in branch_paths:
            json_handler.log_operation("target_unresolved", {"argument": argument})
            raise ValueError(
                f"'{argument}' is not a registered branch - "
                f"pass a directory path to measure something outside the registry"
            )
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
    """Best-effort layout label, recorded rather than acted on.

    The label never changes what runs — the adapter's `detect()` decides that.
    It exists so a reader of two artifacts with different numbers can see
    whether they were even the same shape of project.
    """
    if (target.path / "pytest.ini").exists():
        return "pytest.ini at root"
    if (target.path / "tests").is_dir():
        return "tests/ directory, no pytest.ini"
    if (target.path / "pyproject.toml").exists():
        return "pyproject.toml, no tests/ directory"
    return "unrecognised"
