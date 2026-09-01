# =================== AIPass ====================
# Name: read.py
# Description: Registry Read Handler
# Version: 1.2.0
# Created: 2025-11-15
# Modified: 2026-08-31
# =============================================

"""
Registry Read Handler

Handles reading branch registry data including:
- Reading all branches from AIPASS_REGISTRY.json
- Deriving email addresses from branch names
- Mapping email addresses to branch paths

Handler Independence:
- No module imports from ai_mail
- Only uses Prax logger and standard library
- Fully transportable and self-contained
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


# Constants
MODULE_NAME = "registry.read"

BRANCH_REGISTRY_PATH = find_repo_root() / "AIPASS_REGISTRY.json"


def get_all_branches() -> List[Dict]:
    """
    Get list of all branches for email routing and selection.
    Reads from AIPass branch registry (AIPASS_REGISTRY.json at repo root).

    Handles both list and dict formats for branches in the registry.
    Uses explicit email field from registry when present, falls back
    to derivation from branch name.

    Returns:
        List of dicts with branch info:
        [{"name": "AIPASS.admin", "path": "/", "email": "@admin"}, ...]

    Note:
        Returns empty list if registry not found or on error.
    """
    json_handler.log_operation("get_all_branches", {"registry_path": str(BRANCH_REGISTRY_PATH)})

    branches = []

    if not BRANCH_REGISTRY_PATH.exists():
        return []

    try:
        with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry_data = json.load(f)

        # Handle both formats: list of dicts or dict keyed by name
        raw_branches = registry_data.get("branches", [])
        if isinstance(raw_branches, dict):
            raw_branches = list(raw_branches.values())

        for branch in raw_branches:
            branch_name = branch.get("name", "")
            path = branch.get("path", "")

            if not branch_name or not path:
                continue

            # Use explicit email from registry if present (preferred)
            # Fall back to derivation only if email field is missing
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
    """
    Derive email address from branch name.

    Rules:
    - AIPASS.admin -> @admin (take part after dot)
    - AIPASS Workshop -> @aipass (take first word)
    - AIPASS-HELP -> @help (take second part to avoid collision)
    - BACKUP -> @backup (take whole name)
    - DRONE -> @drone (take whole name)

    Args:
        branch_name: Branch name from registry

    Returns:
        Email address in format "@email"
    """
    if "." in branch_name:
        # Special case: AIPASS.admin -> admin
        email_part = branch_name.split(".")[-1].lower()
    elif " " in branch_name:
        # Handle spaces: take first word
        email_part = branch_name.split()[0].lower()
    elif "-" in branch_name and branch_name.split("-")[0] == "AIPASS":
        # AIPASS-prefixed branches: use second part to avoid collision
        email_part = branch_name.split("-", 1)[1].lower()
    else:
        # Take first word before hyphen or whole name
        email_part = branch_name.split("-")[0].lower()

    return f"@{email_part}"


def get_branch_by_email(email: str) -> Optional[Dict]:
    """
    Get branch information by email address.

    Args:
        email: Email address (e.g., "@admin")

    Returns:
        Branch dict with name, path, email or None if not found
    """
    branches = get_all_branches()

    for branch in branches:
        if branch["email"] == email:
            return branch

    return None


def _branches_from_registry(reg_file: Path) -> Dict[str, str]:
    """Extract email->absolute-path mappings from one sealed registry file.

    Handles both registry shapes in the wild: branches as a list of dicts, and
    branches as a dict keyed by name. Relative paths resolve against the
    registry's own directory, so a project registry describes its own tree.

    Args:
        reg_file: Path to a *_REGISTRY.json file.

    Returns:
        Dict mapping email address to absolute path string.
        Empty dict if the file is unreadable or holds no usable branches.
    """
    try:
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("[registry] failed reading %s: %s", reg_file, exc)
        return {}

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


# Discovery: exactly one level under this directory, dot-prefixed components
# refused. The rule is named so it can be read, not buried in a glob string.
RESIDENT_PROJECTS_DIR = "projects"
RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"
PROJECT_TREE_REGISTRY_GLOB = f"{RESIDENT_PROJECTS_DIR}/{RESIDENT_REGISTRY_GLOB}"
PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

# The two values passport 2.0 defines for citizenship.residency.
RESIDENCY_CORE = "core"
RESIDENCY_RESIDENT = "resident"


def declared_residency(branch_path: Path) -> Optional[str]:
    """What the passport at *branch_path* declares itself to be.

    The single reader for ``citizenship.residency`` on this branch. An absent or
    unreadable passport declares NOTHING and does not raise: the caller decides
    what silence means, and here it always means refusal.

    Args:
        branch_path: Branch directory holding ``.trinity/passport.json``.

    Returns:
        The declared residency string, or None when nothing is declared.
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

    Registry-led and shallow, and both halves are load-bearing:

    - REGISTRY-LED, NEVER A PASSPORT WALK. On this machine a passport walk under
      projects/ returns EIGHT passports for FOUR residents — baud carries real
      resident-declaring passports under .backup/versioned/ and
      .backup/snapshots/, and a backup copy of a declaration is still a
      declaration. Passport-led discovery counts baud three times. Reading a
      passport only at a path some registry declared is what makes the count
      right.
    - ONE LEVEL, DOT COMPONENTS REFUSED BY AN EXPLICIT LINE. pathlib globs DO
      match hidden directories, unlike a shell, so without the filter below
      projects/.archive/ walks straight back in. The filter is separate from the
      depth rule on purpose: on the live tree the parked projects are excluded
      by both, so either one alone looks unnecessary until the other is removed.

    A checkout with no projects/ returns empty and does not raise — CI runs on
    exactly that tree.

    Args:
        repo_root: Repository root to resolve against.

    Returns:
        Absolute registry paths, sorted, one per candidate project.
    """
    projects = Path(repo_root) / RESIDENT_PROJECTS_DIR
    if not projects.is_dir():
        return []

    found: List[Path] = []
    for path in registries_in(projects, RESIDENT_REGISTRY_GLOB):
        if any(part.startswith(".") for part in path.relative_to(projects).parts):
            continue
        found.append(path)
    return found


def _refuse_resident(name: str, path: str, registry_path: Path, reason: str) -> None:
    """Log a refused resident candidate by name, path and reason.

    Every rejection goes through here so none can be silent. A candidate refused
    without a line in the log is indistinguishable from one that was never
    discovered, and those two need very different fixes.
    """
    logger.error(
        "[registry] REFUSED resident '%s' at %s (listed active in %s): %s",
        name,
        path,
        registry_path.name,
        reason,
    )


def _classify_resident(name: str, path: Path, registry_path: Path) -> bool:
    """Decide one candidate on its own passport, naming the refusal if it is one.

    Split out from the discovery loop so the decision can be read — and changed —
    without the two levels of iteration that surround it in the caller.
    """
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
    """Email->path for the residents one registry lists and their passports confirm.

    Rows are resolved against the registry that holds them, never against the
    caller's cwd: a registry is the only thing that knows what its own relative
    paths mean.
    """
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

    THE TWO-KEY RULE, restated here rather than imported. The registry says the
    branch is active — the anchor a passport cannot forge. The passport says
    ``resident`` — the declaration a registry does not carry. Both are required
    inside projects/, and every other outcome is refused and NAMED.

    This mirrors the SEMANTICS of @memory's registry_scope.accepted_resident_paths()
    as this branch's own code reading the same files. Deliberately not a runtime
    import: reaching into another branch's handlers is an encapsulation
    violation, and @all must not depend on @memory being importable to know who
    it is addressing. It replaces a hardcoded 4-tuple that mirrored theirs and an
    AST pin that compared the two constants — agreement between two literals was
    never evidence that either produced the right answer.

    THE TRUST MODEL. A passport can never ADD scope: nothing walks passports, so
    a declared resident that no discovered registry lists is unreachable by
    construction rather than filtered out later. A stale ``active`` can never
    add one either — status alone is never trusted, which is what answers the
    parked-project concern that the old named list carried by hand.

    Args:
        repo_root: Repository root to resolve against; defaults to this checkout.

    Returns:
        Dict mapping email address to absolute path string.
    """
    root = Path(repo_root) if repo_root is not None else find_repo_root()
    accepted: Dict[str, str] = {}
    for registry_path in resident_registry_paths(root):
        accepted.update(_residents_from_registry(registry_path))
    return accepted


def get_project_tree_branches(repo_root: Path) -> Dict[str, str]:
    """Load branch email->path mappings from every sealed project under repo_root.

    Globs ``projects/*/*_REGISTRY.json`` - one level down, deliberately, so this
    sees the projects the repo hosts and nothing else. This is the cross-project
    bridge's discovery half and is called ONLY for verified-admin callers; for
    everyone else resolution must not widen (FPLAN-0401 phase 5).

    Args:
        repo_root: Repository root containing the projects/ tree.

    Returns:
        Dict mapping email address to absolute path string.
        Empty dict when there is no projects/ tree.
    """
    result: Dict[str, str] = {}
    for reg_file in registries_in(Path(repo_root), PROJECT_TREE_REGISTRY_GLOB):
        result.update(_branches_from_registry(reg_file))
    return result


def get_caller_project_branches(caller_cwd: str) -> Dict[str, str]:
    """Load branch email→path mappings from the caller's project registry.

    Walks up from caller_cwd to find a *_REGISTRY.json file (e.g.
    VERA_REGISTRY.json), then extracts branch email→path mappings.
    Used for cross-project dispatch when the target branch is not in
    the AIPass registry.

    Args:
        caller_cwd: Working directory of the calling project (typically
                    from AIPASS_CALLER_CWD env var).

    Returns:
        Dict mapping email address to absolute path string.
        Empty dict if no registry found or on error.
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
