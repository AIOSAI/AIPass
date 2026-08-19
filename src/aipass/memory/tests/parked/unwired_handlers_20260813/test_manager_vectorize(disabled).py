# ===================AIPASS====================
# Name: tests/test_manager_vectorize.py
# Date: 2026-04-26
# Version: 1.0.0
# Category: memory/tests
# =============================================
"""Tests for manager vectorization and location helpers -- line coverage.

Covers: from aipass.memory.apps.handlers.learnings.manager import process_all_branches
"""

import sys
import json
import subprocess
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper: import learnings manager with mocked dependencies
# ---------------------------------------------------------------------------


def _import_manager(monkeypatch):
    """Import manager with mocked memory_files dependency."""
    mock_memory_files = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.json.memory_files",
        mock_memory_files,
    )

    sys.modules.pop("aipass.memory.apps.handlers.learnings.manager", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.learnings")
    if parent is not None and hasattr(parent, "manager"):
        delattr(parent, "manager")
    from aipass.memory.apps.handlers.learnings import manager

    return manager, mock_memory_files


# ===========================================================================
# _find_learnings_location
# ===========================================================================


class TestFindLearningsLocation:
    """Tests for _find_learnings_location helper."""

    def test_find_learnings_at_root(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"key_learnings": {"a": "val"}}
        parent, loc = mgr._find_learnings_location(data)
        assert parent is data
        assert loc == "root"

    def test_find_learnings_in_active_tasks(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"active_tasks": {"key_learnings": {"b": "val2"}}}
        parent, loc = mgr._find_learnings_location(data)
        assert parent is data["active_tasks"]
        assert loc == "active_tasks"

    def test_find_learnings_not_found(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"other_key": 1}
        parent, loc = mgr._find_learnings_location(data)
        assert parent is None
        assert loc == ""


# ===========================================================================
# _get_learnings / _set_learnings
# ===========================================================================


class TestGetSetLearnings:
    """Tests for _get_learnings and _set_learnings helpers."""

    def test_get_learnings_returns_dict(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"key_learnings": {"x": "y [2026-01-01]"}}
        result = mgr._get_learnings(data)
        assert result == {"x": "y [2026-01-01]"}

    def test_get_learnings_empty(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"something_else": True}
        result = mgr._get_learnings(data)
        assert result == []

    def test_set_learnings_existing(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"key_learnings": {"old": "val"}}
        ok = mgr._set_learnings(data, {"new": "val2"})
        assert ok is True
        assert data["key_learnings"] == {"new": "val2"}

    def test_set_learnings_creates_at_root(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"no_learnings_here": True}
        ok = mgr._set_learnings(data, {"fresh": "entry"})
        assert ok is True
        assert data["key_learnings"] == {"fresh": "entry"}

    def test_get_learnings_list(self, monkeypatch):
        """_get_learnings returns list when key_learnings is a list (v3)."""
        mgr, _ = _import_manager(monkeypatch)
        entries = [
            {"number": 2, "date": "2026-06-13", "key": "b", "value": "vb"},
            {"number": 1, "date": "2026-06-12", "key": "a", "value": "va"},
        ]
        data = {"key_learnings": entries}
        result = mgr._get_learnings(data)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["key"] == "b"

    def test_set_learnings_list(self, monkeypatch):
        """_set_learnings accepts and stores a list (v3)."""
        mgr, _ = _import_manager(monkeypatch)
        entries = [{"number": 1, "date": "2026-06-13", "key": "a", "value": "va"}]
        data = {"key_learnings": []}
        ok = mgr._set_learnings(data, entries)
        assert ok is True
        assert isinstance(data["key_learnings"], list)
        assert data["key_learnings"][0]["key"] == "a"

    def test_get_set_list_roundtrip(self, monkeypatch):
        """Round-trip: get list, modify, set back."""
        mgr, _ = _import_manager(monkeypatch)
        entries = [
            {"number": 2, "date": "2026-06-13", "key": "b", "value": "vb"},
            {"number": 1, "date": "2026-06-12", "key": "a", "value": "va"},
        ]
        data = {"key_learnings": list(entries)}
        learnings = mgr._get_learnings(data)
        learnings.append({"number": 3, "date": "2026-06-14", "key": "c", "value": "vc"})
        mgr._set_learnings(data, learnings)
        assert len(data["key_learnings"]) == 3
        assert data["key_learnings"][2]["key"] == "c"


# ===========================================================================
# _find_recently_completed_location
# ===========================================================================


class TestFindRecentlyCompletedLocation:
    """Tests for _find_recently_completed_location helper."""

    def test_find_recently_completed_at_root(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"recently_completed": ["task1"]}
        parent, loc = mgr._find_recently_completed_location(data)
        assert parent is data
        assert loc == "root"

    def test_find_recently_completed_in_active_tasks(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"active_tasks": {"recently_completed": ["task2"]}}
        parent, loc = mgr._find_recently_completed_location(data)
        assert parent is data["active_tasks"]
        assert loc == "active_tasks"

    def test_find_recently_completed_not_found(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"nothing": 0}
        parent, loc = mgr._find_recently_completed_location(data)
        assert parent is None
        assert loc == ""


# ===========================================================================
# _get_recently_completed / _set_recently_completed
# ===========================================================================


class TestGetSetRecentlyCompleted:
    """Tests for _get_recently_completed and _set_recently_completed helpers."""

    def test_get_recently_completed_returns_list(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"recently_completed": ["a", "b"]}
        result = mgr._get_recently_completed(data)
        assert result == ["a", "b"]

    def test_get_recently_completed_empty(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {}
        result = mgr._get_recently_completed(data)
        assert result == []

    def test_set_recently_completed_existing(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"recently_completed": ["old"]}
        ok = mgr._set_recently_completed(data, ["new1", "new2"])
        assert ok is True
        assert data["recently_completed"] == ["new1", "new2"]

    def test_set_recently_completed_creates_at_root(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        data = {"other": True}
        ok = mgr._set_recently_completed(data, ["fresh"])
        assert ok is True
        assert data["recently_completed"] == ["fresh"]


# ===========================================================================
# _vectorize_learnings
# ===========================================================================


def _mock_embedder(monkeypatch, encode_return):
    """Install a mock embedder in sys.modules so the in-function import succeeds."""
    mock_emb = MagicMock()
    mock_emb.encode_batch = MagicMock(return_value=encode_return)
    vector_pkg = MagicMock()
    vector_pkg.embedder = mock_emb
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", vector_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", mock_emb)
    return mock_emb


class TestVectorizeLearnings:
    """Tests for _vectorize_learnings."""

    def test_empty_learnings(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        result = mgr._vectorize_learnings("BRANCH", [])
        assert result["success"] is True
        assert "No learnings" in result["message"]

    def test_success(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1, 0.2]]})

        mock_completed = MagicMock()
        mock_completed.returncode = 0
        mock_completed.stdout = json.dumps({"success": True, "stored": 1})
        with patch.object(subprocess, "run", return_value=mock_completed) as mock_run:
            result = mgr._vectorize_learnings("TEST", [("key1", "value1 [2026-01-01]")])
        assert result["success"] is True
        assert mock_run.called

    def test_embedding_fails(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": False, "error": "model not found"})

        result = mgr._vectorize_learnings("BRANCH", [("k", "v")])
        assert result["success"] is False
        assert "Embedding failed" in result["error"]

    def test_no_embeddings(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": []})

        result = mgr._vectorize_learnings("BRANCH", [("k", "v")])
        assert result["success"] is False
        assert "No embeddings" in result["error"]

    def test_embedding_import_exception(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        # Make the import itself raise by inserting a broken module
        broken = MagicMock()
        broken.embedder = MagicMock()
        broken.embedder.encode_batch = MagicMock(side_effect=RuntimeError("import boom"))
        monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", broken)
        monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", broken.embedder)

        result = mgr._vectorize_learnings("BRANCH", [("k", "v")])
        assert result["success"] is False
        assert "import boom" in result["error"]

    def test_subprocess_timeout(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60)):
            result = mgr._vectorize_learnings("BR", [("k", "v")])
        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_subprocess_bad_json(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "NOT JSON {"
        with patch.object(subprocess, "run", return_value=mock_proc):
            result = mgr._vectorize_learnings("BR", [("k", "v")])
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_subprocess_nonzero_return(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "segfault"
        with patch.object(subprocess, "run", return_value=mock_proc):
            result = mgr._vectorize_learnings("BR", [("k", "v")])
        assert result["success"] is False
        assert "segfault" in result["error"]

    def test_subprocess_generic_exception(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        with patch.object(subprocess, "run", side_effect=OSError("disk full")):
            result = mgr._vectorize_learnings("BR", [("k", "v")])
        assert result["success"] is False
        assert "disk full" in result["error"]

    def test_numpy_tolist_conversion(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)

        # Simulate numpy-like objects with a tolist() method
        class FakeNdarray:
            def __init__(self, data):
                self._data = data

            def tolist(self):
                return self._data

        _mock_embedder(
            monkeypatch,
            {"success": True, "embeddings": [FakeNdarray([0.3, 0.4])]},
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"success": True})
        with patch.object(subprocess, "run", return_value=mock_proc) as mock_run:
            result = mgr._vectorize_learnings("BR", [("k", "v [2026-01-01]")])
        assert result["success"] is True
        # Verify the input sent to subprocess had plain lists, not FakeNdarray
        call_kwargs = mock_run.call_args
        sent_input = json.loads(call_kwargs.kwargs.get("input") or call_kwargs[1].get("input"))
        assert sent_input["embeddings"] == [[0.3, 0.4]]


# ===========================================================================
# _vectorize_completed_tasks
# ===========================================================================


class TestVectorizeCompletedTasks:
    """Tests for _vectorize_completed_tasks."""

    def test_empty_tasks(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        result = mgr._vectorize_completed_tasks("BRANCH", [])
        assert result["success"] is True
        assert "No tasks" in result["message"]

    def test_success(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.5, 0.6]]})

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"success": True, "stored": 1})
        with patch.object(subprocess, "run", return_value=mock_proc):
            result = mgr._vectorize_completed_tasks("TEST", ["did thing [2026-01-01]"])
        assert result["success"] is True

    def test_embedding_fails(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": False, "error": "no model"})

        result = mgr._vectorize_completed_tasks("BR", ["task1"])
        assert result["success"] is False
        assert "Embedding failed" in result["error"]

    def test_no_embeddings(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": []})

        result = mgr._vectorize_completed_tasks("BR", ["task1"])
        assert result["success"] is False
        assert "No embeddings" in result["error"]

    def test_embedding_import_exception(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        broken = MagicMock()
        broken.embedder = MagicMock()
        broken.embedder.encode_batch = MagicMock(side_effect=ValueError("bad weights"))
        monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", broken)
        monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", broken.embedder)

        result = mgr._vectorize_completed_tasks("BR", ["task1"])
        assert result["success"] is False
        assert "bad weights" in result["error"]

    def test_subprocess_timeout(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60)):
            result = mgr._vectorize_completed_tasks("BR", ["task1"])
        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_subprocess_bad_json(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "<<<BAD"
        with patch.object(subprocess, "run", return_value=mock_proc):
            result = mgr._vectorize_completed_tasks("BR", ["task1"])
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_subprocess_nonzero_return(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "oom killed"
        with patch.object(subprocess, "run", return_value=mock_proc):
            result = mgr._vectorize_completed_tasks("BR", ["task1"])
        assert result["success"] is False
        assert "oom killed" in result["error"]

    def test_subprocess_generic_exception(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)
        _mock_embedder(monkeypatch, {"success": True, "embeddings": [[0.1]]})

        with patch.object(subprocess, "run", side_effect=PermissionError("no access")):
            result = mgr._vectorize_completed_tasks("BR", ["task1"])
        assert result["success"] is False
        assert "no access" in result["error"]

    def test_numpy_tolist_conversion(self, monkeypatch):
        mgr, _ = _import_manager(monkeypatch)

        class FakeNdarray:
            def __init__(self, data):
                self._data = data

            def tolist(self):
                return self._data

        _mock_embedder(
            monkeypatch,
            {"success": True, "embeddings": [FakeNdarray([0.7, 0.8])]},
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"success": True})
        with patch.object(subprocess, "run", return_value=mock_proc) as mock_run:
            result = mgr._vectorize_completed_tasks("BR", ["task [2026-03-01]"])
        assert result["success"] is True
        call_kwargs = mock_run.call_args
        sent_input = json.loads(call_kwargs.kwargs.get("input") or call_kwargs[1].get("input"))
        assert sent_input["embeddings"] == [[0.7, 0.8]]
