# =================== AIPass ====================
# Name: registry_discovery.py
# Description: Shared registry file discovery (walk-up search)
# Version: 1.0.0
# Created: 2026-06-06
# Modified: 2026-10-17
# =============================================

"""Registry discovery — find *_REGISTRY.json by walking up the directory tree."""

# Stdlib only: importable before drone/prax exist.
import os
from pathlib import Path


_REGISTRY_SUFFIX = "_REGISTRY.json"
_REGISTRY_GLOB = "*" + _REGISTRY_SUFFIX


def registries_in(directory):
    """Every ``*_REGISTRY.json`` in *directory*, exact-case, sorted."""
    try:
        entries = list(directory.glob(_REGISTRY_GLOB))
    except (OSError, ValueError):
        return []
    # Path.glob is case-insensitive on Windows/macOS; re-check the suffix, never the stem.
    return sorted(p for p in entries if p.name.endswith(_REGISTRY_SUFFIX))


def _glob_registry(directory):
    """Find the first *_REGISTRY.json in a single directory."""
    matches = registries_in(directory)
    return matches[0] if matches else None


def find_registry(start_path=None, package_root=None):
    """Find *_REGISTRY.json — walks up from start_path/cwd, then package_root."""
    env_path = os.environ.get("AIPASS_REGISTRY")
    if env_path:  # an operator-named path is returned unchecked
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
