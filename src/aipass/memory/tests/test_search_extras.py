# =================== AIPass ====================
# Name: tests/test_search_extras.py
# Description: Tests for search query_executor subprocess encoding and vector search
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-11-23
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/search/query_executor.py."""

# All tests use mocks: no live subprocess, ML model, or ChromaDB access.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — query_executor._pin_plan_id_matches(); tests/test_chroma_source_match.py
# sentry: no-test-needed(external) — the memory venv interpreter lane.memory_python() finds; every subprocess is stubbed

import json
import subprocess
from unittest.mock import MagicMock, patch

from aipass.memory.apps.handlers.cli import caller_gate
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.rollover import todo_roll
from aipass.memory.apps.handlers.search import query_executor


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

    def test_an_embedder_refusal_names_its_cause(self):
        """The embedder's real refusal: exit 1, its reason as JSON on stdout, stderr empty."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = json.dumps({"success": False, "error": "inhomogeneous shape"})
        mock_result.stderr = ""

        with patch.object(subprocess, "run", return_value=mock_result):
            result = query_executor.encode_query_subprocess("test query")

        assert result == {"success": False, "error": "Embedding failed (exit 1): inhomogeneous shape"}

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


class TestAFailedPlanFetchIsSaidNotReadAsNoMatch:
    """A store that fails is not a store with no match: the search says so.

    Each stand-in reads its stdin first, as the real store does: one that exits unread
    leaves the search writing into a closed pipe, where a default-SIGPIPE worker dies silently.
    """

    def _search(self, monkeypatch, tmp_path, script_text):
        script = tmp_path / "stand_in_store.py"
        script.write_text(script_text, encoding="utf-8")
        monkeypatch.setattr(query_executor, "CHROMA_SUBPROCESS_SCRIPT", script)
        monkeypatch.setattr(
            query_executor, "encode_query_subprocess", lambda query: {"success": True, "embedding": [0.0]}
        )
        found = {"success": True, "results": [], "collections_searched": 1, "total_results": 0}
        monkeypatch.setattr(query_executor, "search_vectors_subprocess", lambda **kwargs: found)
        operations = []
        monkeypatch.setattr(query_executor.json_handler, "log_operation", lambda name, *a, **k: operations.append(name))
        said = []
        monkeypatch.setattr(query_executor.logger, "warning", lambda msg, *a, **k: said.append(str(msg)))
        result = query_executor.execute_search("DPLAN-0012 hooks")
        assert [op for op in operations if op != "subprocess_lane"] == ["search_execute"]
        return result, said

    def test_a_store_that_exits_non_zero_is_named(self, monkeypatch, tmp_path):
        result, said = self._search(monkeypatch, tmp_path, "import sys\nsys.stdin.read()\nsys.exit(3)\n")

        assert result["results"] == []
        assert said[-1] == (
            "[search] Plan metadata fetch failed for DPLAN-0012: store failed (exit 3):"
            " no JSON reply on stdout (it was empty); stderr: empty — exact-ID pin skipped"
        )

    def test_a_store_that_answers_no_match_says_nothing(self, monkeypatch, tmp_path):
        """The control: an honest empty answer is not a failure."""
        answer = '{"success": true, "results": []}'
        result, said = self._search(monkeypatch, tmp_path, f"import sys\nsys.stdin.read()\nprint({answer!r})\n")

        assert result["results"] == []
        assert said == []

    def test_a_store_with_no_plans_yet_is_a_state_said_below_warning(self, monkeypatch, tmp_path):
        answer = '{"success": true, "results": [], "count": 0, "exists": false}'
        told = []
        monkeypatch.setattr(query_executor.logger, "info", lambda msg, *a, **k: told.append(str(msg)))
        result, said = self._search(monkeypatch, tmp_path, f"import sys\nsys.stdin.read()\nprint({answer!r})\n")

        assert result["results"] == []
        assert said == []
        assert "[search] No flow_plans in the global store yet — no plan to pin for DPLAN-0012" in told


class TestTheCallersOwnStore:
    """caller_local_store: the verified caller, else the cwd's branch; the lookup never creates the store."""

    def _fleet(self, monkeypatch, tmp_path, caller):
        wren = tmp_path / "wren"
        (wren / "sub").mkdir(parents=True)
        rows = [{"name": "wren", "path": str(wren)}]
        monkeypatch.setattr(detector, "write_scope", lambda: rows)
        monkeypatch.setattr(todo_roll, "in_scope_branches", lambda root=None: rows)
        monkeypatch.setattr(caller_gate, "verified_caller", lambda: (caller, False))
        return wren

    def test_the_verified_caller_names_its_store_and_nothing_is_created(self, monkeypatch, tmp_path):
        wren = self._fleet(monkeypatch, tmp_path, "@wren")

        assert query_executor.caller_local_store() == {"branch": "wren", "db_path": wren / ".chroma"}
        assert not (wren / ".chroma").exists()

    def test_with_no_verified_caller_the_cwd_branch_answers(self, monkeypatch, tmp_path):
        wren = self._fleet(monkeypatch, tmp_path, "")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(wren / "sub"))

        assert query_executor.caller_local_store() == {"branch": "wren", "db_path": wren / ".chroma"}

    def test_neither_is_refused_in_one_sentence(self, monkeypatch, tmp_path):
        self._fleet(monkeypatch, tmp_path, "")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        refusal = query_executor.caller_local_store()["refusal"]
        assert refusal.startswith("search reads your own branch's store and no branch resolves here")
        assert "not inside a registered branch directory" in refusal

    def test_a_caller_outside_the_scope_is_refused(self, monkeypatch, tmp_path):
        self._fleet(monkeypatch, tmp_path, "@ghost")

        assert "@ghost has none in the memory scope" in query_executor.caller_local_store()["refusal"]

    def test_a_dark_rail_is_refused_not_read_as_no_caller(self, monkeypatch, tmp_path):
        self._fleet(monkeypatch, tmp_path, "")

        def dark():
            raise ImportError("no ai_mail")

        monkeypatch.setattr(caller_gate, "verified_caller", dark)

        assert "rail is unavailable (ImportError('no ai_mail'))" in query_executor.caller_local_store()["refusal"]


class TestALocalSearchReadsOnlyItsStore:
    """The vector search and the plan-ID pin both go to the store handed in, never the global one."""

    def test_db_path_reaches_the_search_and_the_pin(self, monkeypatch, tmp_path):
        local = tmp_path / "wren" / ".chroma"
        sent = []

        def store(script, data, **kwargs):
            sent.append((data["operation"], data["db_path"]))
            return {"success": True, "results": [], "collections_searched": 1, "total_results": 0}

        monkeypatch.setattr(query_executor, "run_json", store)
        monkeypatch.setattr(
            query_executor, "encode_query_subprocess", lambda query: {"success": True, "embedding": [0.0]}
        )

        assert query_executor.execute_search("FPLAN-1202 lane", db_path=local)["success"] is True

        assert sent == [("search_vectors", str(local)), ("get_by_source", str(local))]
