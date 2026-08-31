# =================== AIPass ====================
# Name: registry_discovery.py
# Description: Shared registry file discovery (walk-up search)
# Version: 1.0.0
# Created: 2026-06-06
# Modified: 2026-06-10
# =============================================

"""Registry discovery — find *_REGISTRY.json by walking up the directory tree.

Dependency-free: uses only stdlib. Importable before drone/prax exist.
"""

import os
from pathlib import Path


def _glob_registry(directory):
    """Find *_REGISTRY.json in a single directory.

    Args:
        directory: Path to search in.

    Returns:
        Path to the registry file, or None if not found.
    """
    matches = sorted(directory.glob("*_REGISTRY.json"))
    return matches[0] if matches else None


def find_registry(start_path=None, package_root=None):
    """Find *_REGISTRY.json — walks up from start_path/cwd, then package_root.

    The first *_REGISTRY.json found while walking up IS the project boundary.
    If multiple exist in the same directory, picks the first alphabetically.

    Priority:
    1. AIPASS_REGISTRY environment variable — an explicit instruction, returned
       unchecked: an operator who names a path is not guessing.
    2. Walk up from start_path/cwd — first dir containing *_REGISTRY.json
    3. Walk up from package_root (caller's __file__ location) — fallback
    4. Absence — return None.

    On (4) this used to return ``Path.cwd() / "AIPASS_REGISTRY.json"``.  That
    was a guess about where the caller happens to stand, dressed as a fact
    about the machine, and it DISCARDED the ``start_path`` it was asked about:
    a caller asking "is there a registry under /x" was answered with a file in
    the process's cwd.  Every consumer here guards with ``.exists()``, so
    nothing fired — but a path that need not exist is a lie with a type
    signature, and @spawn's ``load_registry`` mints a fresh ``metadata.id``
    for exactly such a path.  Absence is a fact; say it as one and let the
    caller refuse by name.  (Sibling precedent already in this branch:
    ``apps/handlers/init/git_auth.py:find_registry`` returns ``Optional[Path]``.)

    Args:
        start_path: Directory to start searching from (default: cwd).
        package_root: Optional fallback directory for package-relative search.

    Returns:
        Path to *_REGISTRY.json, or None when no registry was found.
    """
    env_path = os.environ.get("AIPASS_REGISTRY")
    if env_path:
        return Path(env_path)

    current = Path(start_path).resolve() if start_path else Path.cwd()
    for parent in [current] + list(current.parents):
        found = _glob_registry(parent)
        if found:
            return found

    if package_root:
        pkg_dir = Path(package_root).resolve()
        for parent in [pkg_dir] + list(pkg_dir.parents):
            found = _glob_registry(parent)
            if found:
                return found

    return None
