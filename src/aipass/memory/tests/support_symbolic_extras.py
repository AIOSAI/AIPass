# =================== AIPass ====================
# Name: support_symbolic_extras.py
# Description: Shared autouse fixtures for the test_symbolic_extras files - the handler-dependency stand-ins
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Fixtures for tests/test_symbolic_extras*.py (no test_ prefix: never collected).

Not in conftest.py: its autouse fixtures run suite-wide. Imported after each file's parked-tier skip.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_handler_deps(monkeypatch):
    """Mock heavy handler-level imports (memory_files, embedder, chromadb, api keys) on top of conftest's."""
    mock_memory_files = MagicMock()
    mock_memory_files.write_memory_file = MagicMock(return_value={"success": True})
    mock_memory_files.read_memory_file = MagicMock(
        return_value={"success": True, "data": {"enabled": True, "threshold": 0.3}}
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.json.memory_files",
        mock_memory_files,
    )

    mock_embedder = MagicMock()
    mock_embedder.encode_batch = MagicMock(return_value={"success": True, "embeddings": [[0.1, 0.2, 0.3]]})
    vector_pkg = MagicMock()
    vector_pkg.embedder = mock_embedder
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", vector_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", mock_embedder)

    mock_chromadb = MagicMock()
    monkeypatch.setitem(sys.modules, "chromadb", mock_chromadb)

    mock_keys = MagicMock()
    mock_keys.get_api_key = MagicMock(return_value="test-api-key")
    monkeypatch.setitem(sys.modules, "aipass.api", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers.auth", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers.auth.keys", mock_keys)

    for mod_name in [
        "aipass.memory.apps.handlers.symbolic.hook",
        "aipass.memory.apps.handlers.symbolic.storage",
        "aipass.memory.apps.handlers.symbolic.retriever",
        "aipass.memory.apps.handlers.symbolic.deduplicator",
        "aipass.memory.apps.handlers.symbolic.chroma_client",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


@pytest.fixture(autouse=True)
def _reset_hook_session():
    """Reset hook SESSION_STATE before each test."""
    yield
    hook_mod = sys.modules.get("aipass.memory.apps.handlers.symbolic.hook")
    if hook_mod and hasattr(hook_mod, "reset_session"):
        hook_mod.reset_session()


@pytest.fixture(autouse=True)
def _reset_chroma_clients():
    """Clear the chroma_client singleton cache between tests."""
    yield
    cc_mod = sys.modules.get("aipass.memory.apps.handlers.symbolic.chroma_client")
    if cc_mod and hasattr(cc_mod, "_clients"):
        cc_mod._clients.clear()
