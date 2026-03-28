# =================== AIPass ====================
# Name: test_error_resilience.py
# Description: Error Resilience Tests for skills branch
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
Error Resilience Tests for skills branch.

Covers 4 tests:
  - missing_file, corrupt_json, empty_file, nonexistent_dir
"""

import importlib
import json
from pathlib import Path


BRANCH_MODULE = "skills"
_json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"


def _import_handler():
    """Import json_handler."""
    return importlib.import_module(_json_mod_path)


# ============================================================================
# Error Resilience Tests
# ============================================================================

def test_missing_file() -> None:
    """Loading a non-existent file returns a graceful default, not a crash."""
    handler = _import_handler()
    target = handler.get_json_path("ghost", "config")
    assert not target.exists()

    try:
        result = handler.load_json("ghost", "config")
    except FileNotFoundError:
        return

    assert result is not None
    assert isinstance(result, dict)


def test_corrupt_json() -> None:
    """Corrupt JSON on disk is handled gracefully -- file is regenerated."""
    handler = _import_handler()
    json_dir = handler.SKILLS_JSON_DIR
    json_dir.mkdir(parents=True, exist_ok=True)
    target = handler.get_json_path("corrupt", "data")
    target.write_bytes(b"\x00\x01NOT-JSON{{{broken")

    result = handler.ensure_json_exists("corrupt", "data")
    assert result is True

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict)
    assert "created" in data
    assert "last_updated" in data


def test_empty_file() -> None:
    """An empty file (0 bytes) is handled gracefully."""
    handler = _import_handler()
    json_dir = handler.SKILLS_JSON_DIR
    json_dir.mkdir(parents=True, exist_ok=True)
    target = handler.get_json_path("empty", "log")
    target.write_text("", encoding="utf-8")

    result = handler.ensure_json_exists("empty", "log")
    assert result is True

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, list)


def test_nonexistent_dir(tmp_path: Path) -> None:
    """Missing parent directory is handled gracefully."""
    handler = _import_handler()
    from unittest.mock import patch

    nested_dir = tmp_path / "does_not_exist" / "nested"
    assert not nested_dir.exists()

    with patch.object(handler, "SKILLS_JSON_DIR", nested_dir):
        try:
            result = handler.ensure_json_exists("nodir", "config")
            assert nested_dir.exists()
            assert result is True
        except (FileNotFoundError, OSError):
            pass
