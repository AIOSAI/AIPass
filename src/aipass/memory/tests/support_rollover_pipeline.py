# =================== AIPass ====================
# Name: support_rollover_pipeline.py
# Description: Shared harness for the test_rollover_pipeline files - the extractor import over stand-ins
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers for tests/test_rollover_pipeline*.py (no test_ prefix: never collected).

The extractor import harness three of the split rollover-pipeline files use:
the extraction lane, the safety valve and the run lane each import
rollover/extractor.py over the same stand-ins. Moved verbatim from
test_rollover_pipeline.py when it was split by subject (2026-10-08).
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import sys
from pathlib import Path
from unittest.mock import MagicMock


def _import_extractor(monkeypatch):
    """Import extractor with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_memory_files = MagicMock()
    mock_memory_files.read_memory_file_data = MagicMock(return_value=None)
    mock_memory_files.write_memory_file_simple = MagicMock()

    mock_config_loader = MagicMock()
    mock_config_loader.section.return_value = {"defaults": {}, "per_branch": {}}

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler
    json_pkg.config_loader = mock_config_loader

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.config_loader", mock_config_loader)

    # Through monkeypatch, like the orchestrator above: the copy imported over
    # these mocks leaves with the test (leg 12 - a bare pop left it cached).
    monkeypatch.delitem(sys.modules, "aipass.memory.apps.handlers.rollover.extractor", raising=False)
    parent = sys.modules.get("aipass.memory.apps.handlers.rollover")
    if parent is not None:
        monkeypatch.delattr(parent, "extractor", raising=False)

    from aipass.memory.apps.handlers.rollover import extractor

    return extractor, {
        "json_handler": mock_json_handler,
        "memory_files": mock_memory_files,
        "config_loader": mock_config_loader,
    }
