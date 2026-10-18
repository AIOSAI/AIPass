# =================== AIPass ====================
# Name: changelog.py
# Description: Per-project backup changelog append/read
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""Changelog state handler."""

from pathlib import Path

from ..audit import trail
from ..json import json_handler
from ..path import builder


def _read_changelog(cl_path: Path) -> dict:
    """Read a project's changelog document."""
    data = json_handler.read_json(cl_path)
    if data is None:
        if cl_path.exists():
            # An empty document here would let append_changelog overwrite every run already recorded.
            raise json_handler.InvalidDocument(f"Changelog unreadable: {cl_path}")
        return {}
    if not isinstance(data, dict):
        raise json_handler.InvalidDocument(f"Changelog is not a JSON object: {cl_path}")
    return data


def append_changelog(project_root: str, entry: dict) -> None:
    """Append a changelog entry for a project."""
    cl_path = builder.build_changelog_path(project_root)
    data = _read_changelog(cl_path)
    data.setdefault("entries", []).append(entry)
    if not json_handler.write_json(cl_path, data):
        raise json_handler.WriteFailed(f"Changelog write failed: {cl_path}")
    trail.log_operation("append_changelog", {"project_root": project_root})


def load_changelog(project_root: str) -> list[dict]:
    """Load changelog entries for a project."""
    cl_path = builder.build_changelog_path(project_root)
    entries = _read_changelog(cl_path).get("entries", [])
    trail.log_operation("load_changelog", {"project_root": project_root, "count": len(entries)})
    return entries
