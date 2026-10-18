# =================== AIPass ====================
# Name: tag_handler.py
# Description: Tag handler — create, push, and list release tags
# Version: 1.2.0
# Created: 2026-07-02
# Modified: 2026-10-17
# =============================================

"""Tag handler — create, push, and list release tags.

AIPass's repo tags ``origin/main`` once both manifests carry the version; an
external repo tags its HEAD with no version guard (its manifests are its owner's).
Both refuse a tag that already exists locally or on the remote, never moving it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root
from aipass.drone.apps.handlers.git.repo_context import is_aipass_repo

_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def _run_git(argv: list[str], repo_root: Path) -> tuple[subprocess.CompletedProcess | None, str]:
    """Run a git command in *repo_root*; return (result, "") or (None, reason)."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, cwd=str(repo_root)), ""
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("%s failed: %s", " ".join(argv), exc)
        return None, str(exc)


def _tag_external(name: str, repo_root: Path) -> dict:
    """Tag an external repo's current HEAD and push the tag to its own origin.

    The name is checked by ``git check-ref-format``, not our ``vX.Y.Z`` rule, so a
    project's own convention (``v0.1.0-rc1``, ``2026.08.1``) is not refused.
    """
    if not name or name.startswith("-"):
        return {
            "success": False,
            "message": f"Invalid tag name '{name}' — a tag name cannot be empty or start with '-'.",
        }

    result, err = _run_git(["git", "check-ref-format", f"refs/tags/{name}"], repo_root)
    if result is None:
        return {"success": False, "message": f"Tag name check failed: {err}"}
    if result.returncode != 0:
        return {"success": False, "message": f"'{name}' is not a valid tag name (git check-ref-format refused it)."}

    result, err = _run_git(["git", "tag", "-l", name], repo_root)
    if result is None:
        return {"success": False, "message": f"Tag check failed: {err}"}
    if name in result.stdout.split():
        return {"success": False, "message": f"Tag '{name}' already exists locally."}

    # The return code matters here: with no fetch to fail first, an unreachable
    # remote's empty stdout reads exactly like "no such tag".
    result, err = _run_git(["git", "ls-remote", "--tags", "origin", f"refs/tags/{name}"], repo_root)
    if result is None:
        return {"success": False, "message": f"Remote tag check failed: {err}"}
    if result.returncode != 0:
        return {"success": False, "message": f"Remote tag check failed: {result.stderr.strip()}"}
    if result.stdout.strip():
        return {"success": False, "message": f"Tag '{name}' already exists on remote."}

    result, err = _run_git(["git", "rev-parse", "HEAD"], repo_root)
    if result is None:
        return {"success": False, "message": f"Failed to resolve HEAD: {err}"}
    if result.returncode != 0 or not result.stdout.strip():
        reason = result.stderr.strip() or "repository has no commits"
        return {"success": False, "message": f"Failed to resolve HEAD: {reason}"}
    sha = result.stdout.strip()

    result, err = _run_git(["git", "tag", "-a", name, "-m", f"Release {name}"], repo_root)
    if result is None:
        return {"success": False, "message": f"Tag creation failed: {err}"}
    if result.returncode != 0:
        return {"success": False, "message": f"Tag creation failed: {result.stderr.strip()}"}

    result, err = _run_git(["git", "push", "origin", name], repo_root)
    if result is None:
        return {"success": False, "message": f"Tag push failed: {err}"}
    if result.returncode != 0:
        return {"success": False, "message": f"Tag push failed: {result.stderr.strip()}"}

    json_handler.log_operation("tag_release", {"version": name, "sha": sha, "repo": repo_root.name, "seat": "external"})
    logger.info("Tagged %s at %s HEAD (%s)", name, repo_root.name, sha)

    return {"success": True, "message": f"Tagged {name} at {repo_root.name} HEAD ({sha}) and pushed to origin."}


def tag_release(version: str, repo_root: Path | None = None) -> dict:
    """Create and push an annotated release tag, by the external lane when the repo is not AIPass's."""
    if repo_root is None:
        repo_root = find_repo_root()
    if not is_aipass_repo(repo_root):
        return _tag_external(version, repo_root)

    if not _VERSION_RE.match(version):
        return {"success": False, "message": f"Invalid version format '{version}'. Expected vX.Y.Z (e.g. v2.6.1)."}

    bare_version = version[1:]  # strip leading 'v'

    try:
        result = subprocess.run(
            ["git", "fetch", "origin"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git fetch origin failed: %s", exc)
        return {"success": False, "message": f"Fetch failed: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Fetch failed: {result.stderr.strip()}"}

    try:
        result = subprocess.run(
            ["git", "show", "origin/main:pyproject.toml"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git show origin/main:pyproject.toml failed: %s", exc)
        return {"success": False, "message": f"Failed to read pyproject.toml from origin/main: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Failed to read pyproject.toml from origin/main: {result.stderr.strip()}"}

    pyproject_match = _PYPROJECT_VERSION_RE.search(result.stdout)
    pyproject_version = pyproject_match.group(1) if pyproject_match else None

    try:
        result = subprocess.run(
            ["git", "show", "origin/main:src/aipass/__init__.py"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git show origin/main:src/aipass/__init__.py failed: %s", exc)
        return {"success": False, "message": f"Failed to read __init__.py from origin/main: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Failed to read __init__.py from origin/main: {result.stderr.strip()}"}

    init_match = _INIT_VERSION_RE.search(result.stdout)
    init_version = init_match.group(1) if init_match else None

    if pyproject_version != bare_version or init_version != bare_version:
        return {
            "success": False,
            "message": (
                f"Version mismatch — tag: {bare_version}, "
                f"pyproject.toml: {pyproject_version}, "
                f"__init__.py: {init_version}. "
                "All three must agree before tagging."
            ),
        }

    try:
        result = subprocess.run(
            ["git", "tag", "-l", version],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git tag -l %s failed: %s", version, exc)
        return {"success": False, "message": f"Tag check failed: {exc}"}

    if result.stdout.strip():
        return {"success": False, "message": f"Tag '{version}' already exists locally."}

    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", f"refs/tags/{version}"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git ls-remote --tags origin %s failed: %s", version, exc)
        return {"success": False, "message": f"Remote tag check failed: {exc}"}

    if result.stdout.strip():
        return {"success": False, "message": f"Tag '{version}' already exists on remote."}

    try:
        result = subprocess.run(
            ["git", "rev-parse", "origin/main"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git rev-parse origin/main failed: %s", exc)
        return {"success": False, "message": f"Failed to resolve origin/main: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Failed to resolve origin/main: {result.stderr.strip()}"}

    sha = result.stdout.strip()

    try:
        result = subprocess.run(
            ["git", "tag", "-a", version, "origin/main", "-m", f"Release {version}"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git tag -a %s failed: %s", version, exc)
        return {"success": False, "message": f"Tag creation failed: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Tag creation failed: {result.stderr.strip()}"}

    try:
        result = subprocess.run(
            ["git", "push", "origin", version],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git push origin %s failed: %s", version, exc)
        return {"success": False, "message": f"Tag push failed: {exc}"}

    if result.returncode != 0:
        return {"success": False, "message": f"Tag push failed: {result.stderr.strip()}"}

    json_handler.log_operation("tag_release", {"version": version, "sha": sha})
    logger.info("Tagged %s at %s", version, sha)

    return {"success": True, "message": f"Tagged {version} on origin/main ({sha})."}


def list_tags(repo_root: Path | None = None) -> dict:
    """List all tags sorted newest-first, in *repo_root* (default: the standing repo)."""
    if repo_root is None:
        repo_root = find_repo_root()

    try:
        result = subprocess.run(
            ["git", "tag", "-l", "--sort=-v:refname"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git tag -l failed: %s", exc)
        return {"success": False, "tags": [], "message": f"Failed to list tags: {exc}"}

    if result.returncode != 0:
        return {"success": False, "tags": [], "message": f"Failed to list tags: {result.stderr.strip()}"}

    tags = [t for t in result.stdout.strip().splitlines() if t]

    return {"success": True, "tags": tags, "message": f"{len(tags)} tag(s) found."}
