# =================== AIPass ====================
# Name: test_error_resilience.py
# Description: Error resilience tests for spawn json_handler
# Version: 1.0.1
# Created: 2026-03-28
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/json/json_handler.py's read_json and write_json error handling."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in apps/handlers/json/ parses and imports
# seedgo: no-test-needed(covered_elsewhere) — the happy path, in test_json_handler.py
# seedgo: no-test-needed(covered_elsewhere) — write_json's OSError-false branch, in test_json_handler.py

import json
from pathlib import Path

from aipass.spawn.apps.handlers.json.json_handler import read_json, write_json

# Covers: a missing file, corrupt JSON, an empty file, and write_json auto-creating a missing parent dir.


# ============================================================================
# Error Resilience Tests (4 tests)
# ============================================================================


def test_missing_file(tmp_path: Path) -> None:  # ER-001
    """Loading a non-existent file returns None gracefully (FileNotFoundError handled)."""
    target = tmp_path / "ghost_config.json"
    assert not target.exists(), "Precondition: file must not exist"

    result = read_json(target)
    assert result is None, "read_json must return None for missing file, not crash"


def test_corrupt_json(tmp_path: Path) -> None:  # ER-002
    """Corrupt/malformed JSON on disk is handled gracefully."""
    target = tmp_path / "corrupt_data.json"
    target.write_bytes(b"\x00\x01NOT-JSON{{{broken")

    result = read_json(target)
    assert result is None, "read_json must return None for corrupt JSON (JSONDecodeError)"


def test_empty_file(tmp_path: Path) -> None:  # ER-003
    """An empty file (0 bytes / empty_content) is handled gracefully.

    Writes an empty file, then calls read_json. The handler must not crash
    on empty content -- it should return None since empty is not valid JSON.
    """
    target = tmp_path / "empty_log.json"
    target.write_text("", encoding="utf-8")

    result = read_json(target)
    assert result is None, "read_json must return None for empty_file, not crash"


def test_nonexistent_dir(tmp_path: Path) -> None:  # ER-004
    """Missing parent directory is handled gracefully by write_json.

    Points write_json at a file inside a directory that does not exist.
    The handler must create the directory automatically (mkdir parents=True).
    """
    nested_dir = tmp_path / "does_not_exist" / "nested"
    target = nested_dir / "nodir_config.json"
    assert not nested_dir.exists(), "Precondition: directory must not exist"

    result = write_json(target, {"key": "value"})
    assert result is True, "write_json must succeed by creating missing directories"
    assert target.exists(), "File must exist after write_json"

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["key"] == "value"
