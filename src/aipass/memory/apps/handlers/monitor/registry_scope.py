# =================== AIPass ====================
# Name: registry_scope.py
# Description: The one definition of "the fleet" — core citizens plus the named resident projects
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Fleet Scope

Which branches @memory's lanes are responsible for, defined once.

Before this module the answer differed per lane.  The trinity push resolved
its own scope from a named constant and reached all 22 branches; every other
lane — rollover, lint, health — walked ``detector._read_registry()`` and
reached 19, because it only knew the core registry plus whatever external
registry a caller's cwd happened to have persisted into
``known_registries.json``.  ``baud`` was in that file by accident of where
somebody once stood; ``earmark``, ``finch`` and ``aipass_site`` were not, and
so three citizens' memory files could overflow with no rollover ever running
on them.  A gap that depends on a caller's working directory is not a policy.

THE RESIDENT LIST IS A NAMED CONSTANT, NEVER A GLOB
---------------------------------------------------
``projects/`` also holds ``marketstand(on _hold)`` and ``speakeasy(on_hold)``.
``marketstand``'s registry marks its branch ``active`` while the directory
name says the project is parked, so a glob would sweep a held project into
every rollover, lint and push in the system on the strength of a stale status
field.  Naming the four residents costs one line per project and cannot go
wrong quietly; adding a resident is a deliberate edit here, which is the
correct amount of friction for "this project's memories are now ours to
maintain".

Discovery of registries OUTSIDE the repo (an external project whose agent
calls in from its own tree) is a separate mechanism and is untouched by this
module — see ``detector._find_caller_registries``.
"""

import json
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

CORE_REGISTRY = "AIPASS_REGISTRY.json"

# The DPLAN-0318 scope's resident projects, named one by one on purpose.
# See the module docstring: a glob here would widen the fleet without a ruling.
RESIDENT_REGISTRIES = (
    "projects/baud/BAUD_REGISTRY.json",
    "projects/earmark/EARMARK_REGISTRY.json",
    "projects/finch/FINCH_REGISTRY.json",
    "projects/aipass-site/AIPASS-SITE_REGISTRY.json",
)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* to the directory holding ``AIPASS_REGISTRY.json``."""
    current = Path(start) if start is not None else Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / CORE_REGISTRY).exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root()


def resident_registry_paths(repo_root: Path | None = None) -> list[Path]:
    """The resident-project registries that exist on this machine.

    A named resident whose registry file is absent is LOGGED and skipped, not
    invented: the constant records intent, the filesystem records reality, and
    a checkout that does not carry ``projects/`` must not raise.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.

    Returns:
        Absolute paths, in the order the constant names them.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    found = []
    for relative in RESIDENT_REGISTRIES:
        path = root / relative
        if path.is_file():
            found.append(path)
        else:
            logger.warning(f"[registry_scope] Resident registry not found: {path}")
    return found


def read_registry_branches(registry_path: Path, name_from: str = "path") -> list[dict[str, Any]]:
    """Read one registry's ACTIVE branches with absolute paths.

    Args:
        registry_path: The registry JSON file.
        name_from: ``"path"`` to name each branch by its DIRECTORY (what the
            trinity checker compares ``managed_by`` against, and what the
            per-branch config lookups key on), or ``"registry"`` to keep the
            registry's own ``name`` field, whose casing disagrees for several
            citizens (``BACKUP`` vs ``backup``).

    Returns:
        ``[{"name", "path", "registry"}]`` — empty when the file is
        unreadable, which is logged as an error rather than raised: one
        broken registry must not take out a fleet-wide lane.
    """
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable registry {registry_path}: {exc}")
        return []

    found = []
    for branch in data.get("branches", []):
        if branch.get("status") != "active":
            continue
        raw = branch.get("path", "")
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = Path(registry_path).parent / raw
        name = path.name if name_from == "path" else branch.get("name", path.name)
        found.append({"name": name, "path": path, "registry": Path(registry_path).name})
    return found


def fleet_branches(repo_root: Path | None = None, name_from: str = "path") -> list[dict[str, Any]]:
    """Every branch @memory maintains: the core citizens plus the residents.

    Deduplicated by resolved path, core registry first, residents in the
    order the constant names them.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.
        name_from: See :func:`read_registry_branches`.

    Returns:
        ``[{"name", "path", "registry"}]``.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    branches = read_registry_branches(root / CORE_REGISTRY, name_from=name_from)
    core_count = len(branches)
    seen = {str(item["path"]) for item in branches}
    for registry_path in resident_registry_paths(root):
        for item in read_registry_branches(registry_path, name_from=name_from):
            if str(item["path"]) not in seen:
                branches.append(item)
                seen.add(str(item["path"]))

    # Logged because the SIZE of the fleet is the whole point of this module:
    # the residents were invisible to rollover, lint and health for months and
    # nothing said so. A run that quietly sees 19 branches instead of 22 is the
    # exact regression, and this line is where it shows up.
    json_handler.log_operation(
        "fleet_scope",
        {"total": len(branches), "core": core_count, "resident": len(branches) - core_count},
        module_name="registry_scope",
    )
    return branches
