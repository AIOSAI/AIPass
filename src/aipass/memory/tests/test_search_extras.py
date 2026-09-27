# =================== AIPass ====================
# Name: tests/test_search_extras.py
# Description: Tests for search query_executor subprocess encoding and vector search
# Version: 1.0.1
# Created: 2026-04-25
# Modified: 2026-09-27
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/search/query_executor.py."""

# Covers:
#     from aipass.memory.apps.handlers.search.query_executor import encode_query_subprocess
#     from aipass.memory.apps.handlers.search.query_executor import search_vectors_subprocess
#
# Tests subprocess-based encoding/search.
# All tests use mocks -- no live subprocess, ML model, or ChromaDB access.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — query_executor._pin_plan_id_matches(); tests/test_chroma_source_match.py
# seedgo: no-test-needed(external) — the memory venv interpreter _get_memory_python() finds; every subprocess is stubbed

import json
import subprocess
from unittest.mock import MagicMock, patch

from aipass.memory.apps.handlers.search import query_executor


# ===========================================================================
# Tests: encode_query_subprocess
# ===========================================================================


class TestEncodeQuerySubprocess:
    """Verify encode_query_subprocess subprocess-based encoding."""

    def test_encode_returns_embedding_on_success(self, monkeypatch):
        """Successful subprocess returns embedding and dimension."""
        mod = query_executor

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
        mod = query_executor

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Model not found"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.encode_query_subprocess("test query")

        assert result["success"] is False
        assert "Model not found" in result["error"]

    def test_encode_handles_timeout(self, monkeypatch):
        """TimeoutExpired produces a timeout error."""
        mod = query_executor

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=120)):
            result = mod.encode_query_subprocess("slow query")

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_encode_handles_invalid_json(self, monkeypatch):
        """Invalid JSON from subprocess produces error dict."""
        mod = query_executor

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.encode_query_subprocess("test query")

        assert result["success"] is False
        assert "json" in result["error"].lower()

    def test_encode_handles_empty_embeddings(self, monkeypatch):
        """Response with empty embeddings list produces error."""
        mod = query_executor

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
        mod = query_executor

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
        mod = query_executor

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
        mod = query_executor

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "DB not found"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "DB not found" in result["error"]

    def test_search_handles_timeout(self, monkeypatch):
        """TimeoutExpired produces a timeout error."""
        mod = query_executor

        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=60)):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_search_handles_invalid_json(self, monkeypatch):
        """Invalid JSON from subprocess produces error dict."""
        mod = query_executor

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "{{bad json"

        with patch.object(subprocess, "run", return_value=mock_result):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "json" in result["error"].lower()

    def test_search_passes_db_path_as_string(self, monkeypatch, tmp_path):
        """db_path is converted to string in the input data."""
        mod = query_executor

        fake_output = json.dumps({"success": True, "results": []})
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        db_path = tmp_path / "test_chroma"
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
        mod = query_executor

        with patch.object(subprocess, "run", side_effect=OSError("Cannot execute")):
            result = mod.search_vectors_subprocess(query_embedding=[0.1])

        assert result["success"] is False
        assert "Cannot execute" in result["error"]
