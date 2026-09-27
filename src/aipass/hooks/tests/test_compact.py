# =================== AIPass ====================
# Name: test_compact.py
# Version: 1.0.1
# Description: Tests for compact lifecycle handler
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/lifecycle/compact.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — _get_git_info's two git subprocess calls, patched at the edge in every test
# seedgo: no-test-needed(constant) — the Recovery Protocol and SAVE STATE NOW bullet texts beyond their headings
# seedgo: no-test-needed(generated) — the logger.info lines on each except path; the text is the exception's own

import json
from unittest.mock import patch, MagicMock

import pytest

from aipass.hooks.apps.handlers.lifecycle.compact import handle
from aipass.hooks.apps.modules import cadence


@pytest.fixture(autouse=True)
def _isolate_cadence_state(tmp_path, monkeypatch):
    """handle() calls cadence.reset_counter() for real. Without isolation each
    test mints a regroup token into the system temp dir's aipass-cadence-<live-session>.json —
    the developer's OWN session inherits CLAUDE_CODE_SESSION_ID — and the
    re-ground backstop then fires in that live session on its next tool call
    (the DPLAN-0278 "ghost re-arm": pytest swallows the arm log line, so the
    fire looks sourceless). Every suite run re-armed it."""
    monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-compact-session")


class TestCompactHandler:
    def test_injects_recovery_context(self, tmp_path):
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        local = trinity / "local.json"
        local.write_text(
            json.dumps(
                {
                    "sessions": [{"number": 10, "date": "2026-05-22", "summary": "did stuff", "status": "completed"}],
                    "key_learnings": [{"number": 1, "date": "2026-05-22", "key": "learn1", "value": "value1"}],
                }
            ),
            encoding="utf-8",
        )
        with patch("aipass.hooks.apps.handlers.lifecycle.compact._get_git_info", return_value="Git branch: dev"):
            result = handle({"cwd": str(tmp_path)})

        assert result["exit_code"] == 0
        assert "POST-COMPACT RECOVERY" in result["stdout"]
        assert "Git branch: dev" in result["stdout"]
        assert "did stuff" in result["stdout"]
        assert "STATUS.local.md" not in result["stdout"]
        assert result["sound"] == "pre compact"

    def test_returns_recovery_when_no_branch_dir(self, tmp_path):
        with patch("aipass.hooks.apps.handlers.lifecycle.compact._get_git_info", return_value=None):
            result = handle({"cwd": str(tmp_path / "nonexistent")})

        assert result["exit_code"] == 0
        assert "POST-COMPACT RECOVERY" in result["stdout"]
        assert result["sound"] == "pre compact"

    def test_dispatched_agent_gets_save_warning(self, tmp_path):
        trinity = tmp_path / ".trinity"
        trinity.mkdir()

        with patch("aipass.hooks.apps.handlers.lifecycle.compact._get_git_info", return_value=None):
            with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": "dispatched"}):
                result = handle({"cwd": str(tmp_path)})

        assert "SAVE STATE NOW" in result["stdout"]
        assert "STATUS.local.md" not in result["stdout"]

    def test_interactive_gets_recovery_protocol(self, tmp_path):
        trinity = tmp_path / ".trinity"
        trinity.mkdir()

        with patch("aipass.hooks.apps.handlers.lifecycle.compact._get_git_info", return_value=None):
            with patch.dict("os.environ", {"AIPASS_SESSION_TYPE": ""}):
                result = handle({"cwd": str(tmp_path)})

        assert "Recovery Protocol" in result["stdout"]
        assert "STATUS.local.md" not in result["stdout"]

    def test_empty_hook_data(self):
        with patch("aipass.hooks.apps.handlers.lifecycle.compact._get_git_info", return_value=None):
            with patch("pathlib.Path.cwd", return_value=MagicMock(parts=("/", "tmp"))):
                result = handle({})

        assert result["exit_code"] == 0
