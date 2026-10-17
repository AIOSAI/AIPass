# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: {{DATE}}
# Version: 3.1.0
# Category: {{BRANCH}}/tests
#
# CHANGELOG (Max 5 entries):
#   - v3.1.0 (2026-10-10): temp_test_dir and sample_test_data retired - their one
#     requester was the scaffold smoke test, and a fixture nothing requests is a
#     seedgo unused_conftest_fixture row in every newborn (DPLAN-0354)
#   - v3.0.0 ({{DATE}}): The json redirect is the AIPASS_TEST_LOG_DIR seam - the
#     fleet service resolves its directory per call, so there is no singleton
#     and no private attribute left to patch (DPLAN-0325)
#   - v2.0.0 ({{DATE}}): Real fixtures - temp dirs, captured logger, sandboxed
#     json handler, and an autouse guard that keeps tests out of {{BRANCH}}_json/
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for {{BRANCH}} tests."""

from pathlib import Path
from typing import List, Tuple

import pytest

from aipass.{{BRANCH}}.apps.handlers.json import json_handler


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir; autouse, since unset they hit {{BRANCH}}_json/."""
    # A subdirectory: a seam AT tmp_path makes tmp_path/<branch>/, colliding with a test's own branch dir.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def mock_logger(monkeypatch) -> List[Tuple[str, tuple]]:
    """Capture calls made to the entry point's logger as (level, args) tuples."""
    captured: List[Tuple[str, tuple]] = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    from aipass.{{BRANCH}}.apps import {{BRANCH}} as branch_entry

    monkeypatch.setattr(branch_entry, "logger", _CapturingLogger())
    return captured
