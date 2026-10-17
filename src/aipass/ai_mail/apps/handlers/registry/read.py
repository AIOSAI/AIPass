# =================== AIPass ====================
# Name: read.py
# Description: Registry Read Handler
# Version: 1.3.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""
Registry Read Handler

Reference: docs/identity_and_boundaries.md
"""

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root, registries_in

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


MODULE_NAME = "registry.read"

BRANCH_REGISTRY_PATH = find_repo_root() / "AIPASS_REGISTRY.json"


def get_all_branches() -> List[Dict]:
    """Get list of all branches for email routing and selection."""
    json_handler.log_operation("get_all_branches", {"registry_path": str(BRANCH_REGISTRY_PATH)})

    branches = []

    if not BRANCH_REGISTRY_PATH.exists():
        return []

    try:
        with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry_data = json.load(f)

        raw_branches = registry_data.get("branches", [])
        if isinstance(raw_branches, dict):
            raw_branches = list(raw_branches.values())

        for branch in raw_branches:
            branch_name = branch.get("name", "")
            path = branch.get("path", "")

            if not branch_name or not path:
                continue

            explicit_email = branch.get("email", "")
            if explicit_email:
                email = explicit_email
            else:
                email = _derive_email_from_branch_name(branch_name)

            branches.append({"name": branch_name, "path": path, "email": email})

        return branches

    except Exception as e:
        logger.warning("[registry] get_all_branches failed: %s", e)
        return []


def _derive_email_from_branch_name(branch_name: str) -> str:
    """Derive email address from branch name."""
    if "." in branch_name:
        email_part = branch_name.split(".")[-1].lower()
    elif " " in branch_name:
        email_part = branch_name.split()[0].lower()
    elif "-" in branch_name and branch_name.split("-")[0] == "AIPASS":
        email_part = branch_name.split("-", 1)[1].lower()
    else:
        email_part = branch_name.split("-")[0].lower()

    return f"@{email_part}"


def get_branch_by_email(email: str) -> Optional[Dict]:
    """Get branch information by email address."""
    branches = get_all_branches()

    for branch in branches:
        if branch["email"] == email:
            return branch

    return None


class RegistryUnreadable(Exception):
    """A registry exists and cannot be read, so who it names is unknown.

    Not "names nobody": read as empty, resolvers walk on and can serve another project's namesake.
    """


def _branches_from_registry(reg_file: Path) -> Dict[str, str]:
    """Extract email->absolute-path mappings from one sealed registry file.

    Relative paths resolve against the registry's own directory. Raises RegistryUnreadable rather than answering {}.
    """
    try:
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise RegistryUnreadable(f"{reg_file.name} could not be read ({reg_file}): {exc}") from exc
    if not isinstance(data, dict):
        raise RegistryUnreadable(f"{reg_file.name} could not be read ({reg_file}): not a JSON object")

    result: Dict[str, str] = {}
    branches = data.get("branches", [])
    if isinstance(branches, dict):
        entries = [{**info, "name": name} for name, info in branches.items()]
    elif isinstance(branches, list):
        entries = branches
    else:
        entries = []

    for b in entries:
        if not isinstance(b, dict):
            continue
        email = b.get("email", f"@{str(b.get('name', '')).lower()}")
        path = b.get("path", "")
        if path and not Path(path).is_absolute():
            path = str((reg_file.parent / path).resolve())
        if email and path:
            result[email] = path
    return result


def check_registry_readable(registry_path: Path) -> None:
    """Raise when a registry exists and cannot be read; a missing one passes.

    get_all_branches' [] cannot tell unreadable from empty; delivery asks this before widening tiers.
    """
    if registry_path.exists():
        _branches_from_registry(registry_path)


# Discovery: exactly one level under projects/, dot-prefixed components refused.
RESIDENT_PROJECTS_DIR = "projects"
RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"
PROJECT_TREE_REGISTRY_GLOB = f"{RESIDENT_PROJECTS_DIR}/{RESIDENT_REGISTRY_GLOB}"
PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

RESIDENCY_CORE = "core"
RESIDENCY_RESIDENT = "resident"


def _has_dot_component(path: Path, relative_to: Path) -> bool:
    """Whether any component of *path* below *relative_to* is dot-prefixed.

    The one dot rule shared by both projects/ discovery halves (pathlib globs match hidden dirs). Paths outside pass.
    """
    try:
        parts = path.relative_to(relative_to).parts
    except ValueError:
        return False
    return any(part.startswith(".") for part in parts)


def declared_residency(branch_path: Path) -> Optional[str]:
    """What the passport at *branch_path* declares itself to be.

    An absent or unreadable passport declares nothing (None) and does not raise; callers treat it as refusal.
    """
    passport = Path(branch_path) / PASSPORT_RELATIVE
    try:
        data = json.loads(passport.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("[registry] no passport at %s — declares nothing", passport)
        return None
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.error("[registry] unreadable passport %s: %s", passport, exc)
        return None
    residency = data.get("citizenship", {}).get("residency")
    return residency if isinstance(residency, str) else None


def resident_registry_paths(repo_root: Path) -> List[Path]:
    """Candidate resident-project registries. DISCOVERY ONLY — decides nothing.

    Registry-led, never a passport walk (.backup copies of passports would count residents twice).
    No projects/ returns empty and does not raise (CI runs on that tree).
    """
    projects = Path(repo_root) / RESIDENT_PROJECTS_DIR
    if not projects.is_dir():
        return []

    found: List[Path] = []
    for path in registries_in(projects, RESIDENT_REGISTRY_GLOB):
        if _has_dot_component(path, projects):
            continue
        found.append(path)
    return found


def _refuse_resident(name: str, path: str, registry_path: Path, reason: str) -> None:
    """Log a refused resident candidate by name, path and reason."""
    logger.error(
        "[registry] REFUSED resident '%s' at %s (listed active in %s): %s",
        name,
        path,
        registry_path.name,
        reason,
    )


def _classify_resident(name: str, path: Path, registry_path: Path) -> bool:
    """Decide one candidate on its own passport, naming the refusal if it is one."""
    residency = declared_residency(path)
    if residency == RESIDENCY_RESIDENT:
        return True
    if residency is None:
        reason = "passport declares no residency (missing, unreadable, or no field)"
    elif residency == RESIDENCY_CORE:
        reason = f"passport declares '{RESIDENCY_CORE}' from inside {RESIDENT_PROJECTS_DIR}/"
    else:
        reason = f"passport declares unknown residency '{residency}'"
    _refuse_resident(name, str(path), registry_path, reason)
    return False


def _residents_from_registry(registry_path: Path) -> Dict[str, str]:
    """Email->path for the residents one registry lists and their passports confirm."""
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.error("[registry] unreadable resident registry %s: %s", registry_path, exc)
        return {}

    raw = data.get("branches", [])
    entries = [{**info, "name": n} for n, info in raw.items()] if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return {}

    accepted: Dict[str, str] = {}
    for branch in entries:
        if not isinstance(branch, dict) or branch.get("status") != "active":
            continue
        rel = branch.get("path", "")
        if not rel:
            continue
        path = Path(rel)
        if not path.is_absolute():
            path = (registry_path.parent / rel).resolve()
        name = str(branch.get("name", path.name))
        email = branch.get("email") or f"@{name.lower()}"
        if _classify_resident(name, path, registry_path):
            accepted[email] = str(path)
    return accepted


def get_resident_branches(repo_root: Optional[Path] = None) -> Dict[str, str]:
    """Email->path for every project branch whose passport declares it a resident.

    Two keys, both required: the registry says active, the passport says ``resident``. Every other outcome is refused
    and named. Mirrors @memory's accepted_resident_paths() semantics without importing across the branch boundary.
    """
    root = Path(repo_root) if repo_root is not None else find_repo_root()
    accepted: Dict[str, str] = {}
    for registry_path in resident_registry_paths(root):
        accepted.update(_residents_from_registry(registry_path))
    return accepted


def get_project_tree_branches(repo_root: Path) -> Dict[str, str]:
    """Load branch email->path mappings from every sealed project under repo_root.

    Verified-admin callers only; dot-prefixed projects refused; any unreadable registry raises (no partial map).
    """
    root = Path(repo_root)
    projects = root / RESIDENT_PROJECTS_DIR
    result: Dict[str, str] = {}
    for reg_file in registries_in(root, PROJECT_TREE_REGISTRY_GLOB):
        if _has_dot_component(reg_file, projects):
            logger.debug("[registry] bridge skipped dot-prefixed project registry %s", reg_file)
            continue
        result.update(_branches_from_registry(reg_file))
    return result


def get_external_branches(repo_root: Path) -> Dict[str, str]:
    """Load email->path mappings for every declared-root external citizen.

    Reads @memory's fleet gateway (AIPASS_ROOTS.json). A gateway failure raises, unchanged; it is not "no citizens".
    """
    from aipass.memory.apps.modules import fleet

    rows = fleet.external_branches(repo_root=repo_root)
    result: Dict[str, str] = {}
    for citizen in rows:
        email = citizen.get("email")
        path = citizen.get("path")
        if isinstance(email, str) and path:
            result.setdefault(email.lower(), str(path))
    return result


def get_caller_project_branches(caller_cwd: str) -> Dict[str, str]:
    """Load branch email→path mappings from the caller's project registry.

    Raises RegistryUnreadable at the first unreadable registry: climbing on would serve another project's namesake.
    """
    current = Path(caller_cwd).resolve()
    for _ in range(10):
        for reg_file in registries_in(current):
            result = _branches_from_registry(reg_file)
            if result:
                return result
        parent = current.parent
        if parent == current:
            break
        current = parent
    return {}


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("AI_MAIL HANDLER: registry/read.py")
    console.print("=" * 70)
    console.print("\nRegistry Read Handler")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - get_all_branches() -> List[Dict]")
    console.print("  - get_branch_by_email(email) -> Optional[Dict]")
    console.print()
    console.print("TESTING:")

    branches = get_all_branches()
    console.print(f"\nLoaded {len(branches)} branches:")
    for branch in branches[:5]:  # Show first 5
        console.print(f"  {branch['email']:15} -> {branch['name']}")

    if len(branches) > 5:
        console.print(f"  ... and {len(branches) - 5} more")

    console.print("\n" + "=" * 70 + "\n")
