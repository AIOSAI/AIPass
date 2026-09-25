# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_search_extras.py
# Date: 2026-04-25
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for search handler internals (query_executor and vector_search).

Covers:
    from aipass.memory.apps.handlers.search.query_executor import encode_query_subprocess
    from aipass.memory.apps.handlers.search.query_executor import search_vectors_subprocess

Tests subprocess-based encoding/search.
All tests use mocks -- no live subprocess, ML model, or ChromaDB access.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers: prepare the mock graph needed to import search handlers
# ---------------------------------------------------------------------------


def _prepare_query_executor_mocks(monkeypatch):
    """Insert mocks for query_executor module-level imports.

    Returns a dict of key mock objects so tests can assert against them.
    """
    # Mock the chroma_subprocess and embed_subprocess script paths
    mock_chroma_script = MagicMock()
    mock_embed_script = MagicMock()

    return {
        "chroma_script": mock_chroma_script,
        "embed_script": mock_embed_script,
    }


def _import_query_executor(monkeypatch):
    """Prepare mocks and import (or reimport) query_executor.

    Returns (module, mocks_dict).
    """
    mocks = _prepare_query_executor_mocks(monkeypatch)

    # Remove cached module so it gets re-imported with our mocks
    sys.modules.pop("aipass.memory.apps.handlers.search.query_executor", None)

    # Clear parent package attribute so Python re-executes module code
    parent = sys.modules.get("aipass.memory.apps.handlers.search")
    if parent is not None and hasattr(parent, "query_executor"):
        delattr(parent, "query_executor")

    from aipass.memory.apps.handlers.search import query_executor

    return query_executor, mocks


# ===========================================================================
# Tests: encode_query_subprocess
# ===========================================================================


class TestEncodeQuerySubprocess:
    """Verify encode_query_subprocess subprocess-based encoding."""

    def test_encode_returns_embedding_on_success(self, monkeypatch):
        """Successful subprocess returns embedding and dimension."""
        mod, mocks = _import_query_executor(monkeypatch)

        fake_output = json.dumps({"success": True, "embeddings": [[0.1, 0.2, 0.3]], "dimension": 3})
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        with patch.object(subprocess, "run", return_value=mock_result) as mock_run:
            result = mod.encode_query_subprocess("test query")

        assert result["success"] is True
        assert result["embedding"] == [0.1, 0.2, 0.3]
        assert result["dimension"] == 3
        mock_run.assert_called_once()

    def test_encode_returns_error_on_nonzero_exit(self, monkeypatch):
        """Non-zero return code produces error dict."""
        mod, mocks = _import_query_executor(monkeypatch)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Model not found"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.encode_query_subprocess("test query")

        assert result["success"] is False
        assert "Model not found" in result["error"]

    def test_encode_handles_timeout(self, monkeypatch):
        """TimeoutExpired produces a timeout error."""
        mod, mocks = _import_query_executor(monkeypatch)

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=120)):
            result = mod.encode_query_subprocess("slow query")

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_encode_handles_invalid_json(self, monkeypatch):
        """Invalid JSON from subprocess produces error dict."""
        mod, mocks = _import_query_executor(monkeypatch)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.encode_query_subprocess("test query")

        assert result["success"] is False
        assert "json" in result["error"].lower()

    def test_encode_handles_empty_embeddings(self, monkeypatch):
        """Response with empty embeddings list produces error."""
        mod, mocks = _import_query_executor(monkeypatch)

        fake_output = json.dumps({"success": True, "embeddings": [], "dimension": 384})
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.encode_query_subprocess("test query")

        assert result["success"] is False
        assert "no embedding" in result["error"].lower()

    def test_encode_handles_generic_exception(self, monkeypatch):
        """Unexpected exception produces error dict."""
        mod, mocks = _import_query_executor(monkeypatch)

        with patch.object(subprocess, "run", side_effect=OSError("Cannot execute")):
            result = mod.encode_query_subprocess("test query")

        assert result["success"] is False
        assert "Cannot execute" in result["error"]


# ===========================================================================
# Tests: search_vectors_subprocess
# ===========================================================================


class TestSearchVectorsSubprocess:
    """Verify search_vectors_subprocess subprocess-based search."""

    def test_search_returns_results_on_success(self, monkeypatch):
        """Successful subprocess returns parsed results."""
        mod, mocks = _import_query_executor(monkeypatch)

        fake_output = json.dumps(
            {"success": True, "results": [{"document": "hello", "distance": 0.1}], "total_results": 1}
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        with patch.object(subprocess, "run", return_value=mock_result) as mock_run:
            result = mod.search_vectors_subprocess(
                query_embedding=[0.1, 0.2, 0.3],
                branch="TEST",
                n_results=5,
            )

        assert result["success"] is True
        assert result["total_results"] == 1
        mock_run.assert_called_once()

    def test_search_returns_error_on_nonzero_exit(self, monkeypatch):
        """Non-zero exit code produces error dict."""
        mod, mocks = _import_query_executor(monkeypatch)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "DB not found"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "DB not found" in result["error"]

    def test_search_handles_timeout(self, monkeypatch):
        """TimeoutExpired produces a timeout error."""
        mod, mocks = _import_query_executor(monkeypatch)

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=60)):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_search_handles_invalid_json(self, monkeypatch):
        """Invalid JSON from subprocess produces error dict."""
        mod, mocks = _import_query_executor(monkeypatch)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "{{bad json"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "json" in result["error"].lower()

    def test_search_passes_db_path_as_string(self, monkeypatch):
        """db_path is converted to string in the input data."""
        mod, mocks = _import_query_executor(monkeypatch)

        fake_output = json.dumps({"success": True, "results": []})
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        db_path = Path("/tmp/test_chroma")
        with patch.object(subprocess, "run", return_value=mock_result) as mock_run:
            mod.search_vectors_subprocess(
                query_embedding=[0.1],
                db_path=db_path,
            )

        call_args = mock_run.call_args
        input_data = json.loads(call_args.kwargs.get("input", call_args[1].get("input", "")))
        # str(Path) differs by platform; assert matches platform-native string
        assert input_data["db_path"] == str(db_path)

    def test_search_handles_generic_exception(self, monkeypatch):
        """Unexpected exception produces error dict."""
        mod, mocks = _import_query_executor(monkeypatch)

        with patch.object(subprocess, "run", side_effect=OSError("Cannot execute")):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "Cannot execute" in result["error"]
