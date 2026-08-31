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


_REGISTRY_SUFFIX = "_REGISTRY.json"
_REGISTRY_GLOB = "*" + _REGISTRY_SUFFIX


def registries_in(directory):
    """Every ``*_REGISTRY.json`` in *directory*, exact-case, sorted.

    THE GLOB IS NOT THE FILTER.  ``Path.glob`` asks the FILESYSTEM to match, and
    on a case-insensitive one — Windows, and macOS by default — ``*_REGISTRY.json``
    also matches ``*_registry.json``.  The bait ships in every branch:
    ``flow_json/*_registry.json`` plan counters and a ``.spawn/.template_registry.json``
    (pathlib's ``*`` matches dotfiles, unlike the ``glob`` module).  Measured on
    Windows CI: ``find_registry()`` returned ``drone_command_registry.json``.

    A registry file is a project's TRUST ANCHOR — it decides which installation
    a caller belongs to, which project name gets stamped on their identity, and
    where the delete lane thinks the project root is.  A plan-id counter served
    in that role answers a question it was never asked.

    So the name is re-checked in Python, where ``str.endswith`` is case-sensitive
    on every platform.  SUFFIX only, never the stem: external projects name their
    registry after themselves (``VERA-STUDIO_REGISTRY.json``) and nothing
    promises the stem is uppercase.

    One reader, called from every walk in this branch — the eighth private copy
    of ``glob("*_REGISTRY.json")`` is how a fix lands on some of N identical
    paths.  ``tests/test_registry_case_sweep.py`` pins that by AST so a new
    private copy cannot be added quietly.

    Args:
        directory: Path to search in.

    Returns:
        Sorted list of registry paths; empty when the directory is absent or
        unreadable (a directory we cannot read holds no anchor we can trust).
    """
    try:
        entries = list(directory.glob(_REGISTRY_GLOB))
    except (OSError, ValueError):
        return []
    return sorted(p for p in entries if p.name.endswith(_REGISTRY_SUFFIX))


def _glob_registry(directory):
    """Find the first *_REGISTRY.json in a single directory.

    Args:
        directory: Path to search in.

    Returns:
        Path to the registry file, or None if not found.
    """
    matches = registries_in(directory)
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
