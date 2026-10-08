# =================== AIPass ====================
# Name: support_symbolic_extras.py
# Description: Shared autouse fixtures for the test_symbolic_extras files - the handler-dependency stand-ins
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Fixtures for tests/test_symbolic_extras*.py (no test_ prefix: never collected).

The autouse fixtures both split symbolic-extras files apply to every test: the
handler-dependency stand-ins and the hook-session and chroma-client resets.
Moved verbatim from test_symbolic_extras.py when it was split by subject
(2026-10-08). They live here, not in conftest.py, because conftest's autouse
fixtures run for every test in the suite: these would stand in memory_files,
chromadb and @api's keys for all of them. Each test file imports them after its
module-level skip, so while the tier is PARKED they never run, as before.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import sys
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_handler_deps(monkeypatch):
    """Mock heavy handler-level imports used directly by the handler files.

    Builds on the conftest autouse ``_mock_infrastructure`` which already mocks
    prax logger, json_handler, and trigger at the sys.modules level.

    Here we additionally mock:
    - memory_files (used by hook.py save_config/load_config)
    - embedder (used by storage.py and retriever.py)
    - chromadb (used by chroma_client.py)
    - api keys (used by deduplicator.py)
    """
    # -- memory_files (used by hook) ----------------------------------------
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

    # -- embedder (used by storage + retriever) -----------------------------
    mock_embedder = MagicMock()
    mock_embedder.encode_batch = MagicMock(return_value={"success": True, "embeddings": [[0.1, 0.2, 0.3]]})
    vector_pkg = MagicMock()
    vector_pkg.embedder = mock_embedder
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector", vector_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.vector.embedder", mock_embedder)

    # -- chromadb (used by chroma_client) -----------------------------------
    mock_chromadb = MagicMock()
    monkeypatch.setitem(sys.modules, "chromadb", mock_chromadb)

    # -- api keys (used by deduplicator) ------------------------------------
    mock_keys = MagicMock()
    mock_keys.get_api_key = MagicMock(return_value="test-api-key")
    monkeypatch.setitem(sys.modules, "aipass.api", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers.auth", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.api.apps.handlers.auth.keys", mock_keys)

    # Force-clear cached handler modules so they re-import with mocks
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
    # Post-test cleanup: if the module was loaded, reset its state
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
