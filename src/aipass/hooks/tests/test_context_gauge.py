# =================== AIPass ====================
# Name: test_context_gauge.py
# Version: 1.0.0
# Description: Tests for context_gauge prompt handler
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-07-20
# =============================================

"""Tests for handlers/prompt/context_gauge.py."""

import json
from unittest.mock import patch

import pytest

MODULE = "aipass.hooks.apps.handlers.prompt.context_gauge"


def _write_transcript(path, input_tokens=0, cache_read=0, cache_creation=0):
    entry = {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            }
        },
    }
    path.write_text(json.dumps(entry), encoding="utf-8")


class TestContextGaugeHandle:
    def test_no_transcript_path_is_a_noop(self):
        from aipass.hooks.apps.handlers.prompt.context_gauge import handle

        result = handle({"session_id": "s1"})
        assert result == {"stdout": "", "exit_code": 0}

    def test_below_nudge_threshold_is_silent(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.context_gauge import handle

        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=50_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-below", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_fires_nudge_at_80_percent_of_trigger(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.context_gauge import handle

        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        # trigger = 200000 * 0.9 = 180000; 80% of that = 144000
        _write_transcript(transcript, cache_read=145_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-nudge", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        assert "CONTEXT GAUGE" in result["stdout"]
        assert "run /prep NOW" in result["stdout"]
        assert "wrap up the current work item" not in result["stdout"]

    def test_fires_escalate_at_95_percent_of_trigger(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.context_gauge import handle

        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        # 95% of 180000 trigger = 171000
        _write_transcript(transcript, cache_read=175_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-escalate", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        assert "CONTEXT GAUGE" in result["stdout"]
        assert "wrap up the current work item" in result["stdout"]

    def test_fires_once_per_threshold_per_session(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.context_gauge import handle

        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=145_000)
        hook_data = {"session_id": "s-once", "transcript_path": str(transcript), "cwd": str(tmp_path)}

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            first = handle(hook_data)
            second = handle(hook_data)

        assert "CONTEXT GAUGE" in first["stdout"]
        assert second == {"stdout": "", "exit_code": 0}

    def test_different_sessions_fire_independently(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.prompt.context_gauge import handle

        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=145_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            first = handle({"session_id": "s-indep-a", "transcript_path": str(transcript), "cwd": str(tmp_path)})
            second = handle({"session_id": "s-indep-b", "transcript_path": str(transcript), "cwd": str(tmp_path)})

        assert "CONTEXT GAUGE" in first["stdout"]
        assert "CONTEXT GAUGE" in second["stdout"]

    def test_missing_usage_is_a_noop(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt.context_gauge import handle

        transcript = tmp_path / "t.jsonl"
        transcript.write_text(json.dumps({"type": "user", "message": {}}), encoding="utf-8")

        result = handle({"session_id": "s-nousage", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_never_raises_on_unexpected_error(self, monkeypatch):
        from aipass.hooks.apps.handlers.prompt import context_gauge
        from aipass.hooks.apps.modules import context_window

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(context_window, "read_latest_usage", _boom)
        result = context_gauge.handle({"session_id": "s-err", "transcript_path": "/tmp/x.jsonl"})
        assert result == {"stdout": "", "exit_code": 0}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
