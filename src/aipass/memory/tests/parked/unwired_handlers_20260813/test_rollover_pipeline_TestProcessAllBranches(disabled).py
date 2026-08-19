# ===================AIPASS====================
# META DATA HEADER
# Name: test_rollover_pipeline_TestProcessAllBranches.py
# Date: 2026-08-13
# Version: 1.0.0
# Category: memory/.archive
# =============================================

"""ARCHIVED verbatim from tests/test_rollover_pipeline.py (2026-08-13).

These 5 tests, and the _import_manager fixture they depend on, were the only
manager-facing tests in that file; the rest of it covers the live rollover
pipeline and stayed in tests/. Moved here with the handler they exercise --
see README.md in this directory for the measurement.

Not collected by pytest: .archive/ is outside testpaths.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


def _import_manager(monkeypatch):
    """Import manager with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_memory_files = MagicMock()
    mock_memory_files.read_memory_file_data = MagicMock(return_value=None)
    mock_memory_files.write_memory_file_simple = MagicMock()

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)

    sys.modules.pop("aipass.memory.apps.handlers.learnings.manager", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.learnings")
    if parent is not None and hasattr(parent, "manager"):
        delattr(parent, "manager")

    from aipass.memory.apps.handlers.learnings import manager

    return manager, {
        "json_handler": mock_json_handler,
        "memory_files": mock_memory_files,
    }


# ===========================================================================
# Tests: orchestrator.store_vectors_subprocess
# ===========================================================================


# ===========================================================================
# Tests: manager.process_all_branches
# ===========================================================================


class TestProcessAllBranches:
    """Test process_all_branches iterates registry branches."""

    def test_returns_error_when_registry_not_found(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        with patch.object(mgr, "_find_repo_root", return_value=Path("/nonexistent")):
            result = mgr.process_all_branches()
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_processes_branches_with_local_files(self, monkeypatch, tmp_path):
        mgr, mocks = _import_manager(monkeypatch)

        # Create branch with local file
        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        local_data = {
            "document_metadata": {
                "limits": {"max_learnings": 100, "max_recently_completed": 20},
                "status": {},
            },
            "key_learnings": {"item1": "test learning [2026-01-01]"},
            "recently_completed": [],
        }
        local_file = branch_dir / "TEST.local.json"
        local_file.write_text(json.dumps(local_data, indent=2), encoding="utf-8")

        # Mock read_memory_file_data to return the data
        mocks["memory_files"].read_memory_file_data.return_value = local_data

        registry = {"branches": [{"name": "TEST", "path": str(branch_dir)}]}
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(mgr, "_find_repo_root", return_value=tmp_path):
            result = mgr.process_all_branches()

        assert result["success"] is True
        assert result["processed"] >= 1

    def test_skips_branches_without_local_file(self, monkeypatch, tmp_path):
        mgr, _ = _import_manager(monkeypatch)

        # Create branch dir without local file
        branch_dir = tmp_path / "empty_branch"
        branch_dir.mkdir()

        registry = {"branches": [{"name": "EMPTY", "path": str(branch_dir)}]}
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(mgr, "_find_repo_root", return_value=tmp_path):
            result = mgr.process_all_branches()

        assert result["success"] is True
        assert result["skipped"] >= 1
        assert result["processed"] == 0

    def test_skips_branches_with_nonexistent_paths(self, monkeypatch, tmp_path):
        mgr, _ = _import_manager(monkeypatch)

        registry = {
            "branches": [
                {"name": "MISSING", "path": str(tmp_path / "no_such_dir")},
            ]
        }
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(mgr, "_find_repo_root", return_value=tmp_path):
            result = mgr.process_all_branches()

        assert result["success"] is True
        assert result["skipped"] >= 1
        assert result["processed"] == 0

    def test_handles_read_registry_failure(self, monkeypatch, tmp_path):
        mgr, _ = _import_manager(monkeypatch)

        # Create a malformed registry
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text("not json", encoding="utf-8")

        with patch.object(mgr, "_find_repo_root", return_value=tmp_path):
            result = mgr.process_all_branches()

        assert result["success"] is False
        assert "error" in result
