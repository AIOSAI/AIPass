# =================== AIPass ====================
# Name: test_context_gauge.py
# Version: 1.2.0
# Description: Tests for context_gauge prompt handler (guard per window since 1.1.0; real model window since 1.2.0)
# Branch: hooks
# Created: 2026-07-20
# Modified: 2026-10-19
# =============================================

"""Tests for apps/handlers/prompt/context_gauge.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/prompt/context_gauge.py parses and imports
# seedgo: no-test-needed(stdlib) — tempfile.gettempdir() choosing the guard directory
# seedgo: no-test-needed(documentation) — the module docstring's account of the trigger

import json
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.prompt import context_gauge
from aipass.hooks.apps.handlers.prompt.context_gauge import handle
from aipass.hooks.apps.modules import context_window

MODULE = "aipass.hooks.apps.handlers.prompt.context_gauge"
CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


@pytest.fixture(autouse=True)
def no_user_settings(tmp_path, monkeypatch):
    """The user-level settings file moves under tmp_path and stays absent, so no live window leaks in."""
    monkeypatch.setattr(context_window, "user_settings_path", lambda: tmp_path / "home" / "user_settings.json")


def _write_transcript(path, input_tokens=0, cache_read=0, cache_creation=0, model=""):
    entry = {
        "type": "assistant",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            },
        },
    }
    path.write_text(json.dumps(entry), encoding="utf-8")


class TestContextGaugeHandle:
    def test_no_transcript_path_is_a_noop(self):
        result = handle({"session_id": "s1"})
        assert result == {"stdout": "", "exit_code": 0}

    def test_below_nudge_threshold_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=50_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-below", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_fires_nudge_at_80_percent_of_trigger(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        # trigger = 200000 - 33000 = 167000; 80% of that = 133600
        _write_transcript(transcript, cache_read=145_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-nudge", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        assert "CONTEXT GAUGE" in result["stdout"]
        assert "/prep" in result["stdout"]
        assert "Compact fires soon" not in result["stdout"]
        assert result["sound"] == "context gauge"

    def test_fires_escalate_at_95_percent_of_trigger(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        # 95% of 167000 trigger = 158650
        _write_transcript(transcript, cache_read=175_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-escalate", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["exit_code"] == 0
        assert "CONTEXT GAUGE" in result["stdout"]
        assert "Compact fires soon" in result["stdout"]
        assert result["sound"] == "context gauge"

    def test_fires_once_per_threshold_per_session(self, tmp_path, monkeypatch):
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
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=145_000)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            first = handle({"session_id": "s-indep-a", "transcript_path": str(transcript), "cwd": str(tmp_path)})
            second = handle({"session_id": "s-indep-b", "transcript_path": str(transcript), "cwd": str(tmp_path)})

        assert "CONTEXT GAUGE" in first["stdout"]
        assert "CONTEXT GAUGE" in second["stdout"]

    def test_missing_usage_is_a_noop(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(json.dumps({"type": "user", "message": {}}), encoding="utf-8")

        result = handle({"session_id": "s-nousage", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_never_raises_on_unexpected_error(self, monkeypatch, tmp_path):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(context_window, "read_latest_usage", _boom)
        result = context_gauge.handle({"session_id": "s-err", "transcript_path": str(tmp_path / "x.jsonl")})
        assert result == {"stdout": "", "exit_code": 0}


class TestGaugeMeasuresTheRealWindow:
    def test_a_1m_model_at_230k_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=230_000, model="claude-opus-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-1m", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result == {"stdout": "", "exit_code": 0}

    def test_a_200k_model_at_230k_escalates(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=230_000, model="claude-haiku-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-200k", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert "Compact fires soon" in result["stdout"]
        assert "~230k of 200k context (115%, as the status line counts it); auto-compact at ~167k." in result["stdout"]

    def test_the_printed_percent_is_fill_over_window(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=150_000, model="claude-haiku-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-pct", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert result["stdout"].startswith(
            "CONTEXT GAUGE: ~150k of 200k context (75%, as the status line counts it); auto-compact at ~167k. "
        )
        assert "Compact fires soon" not in result["stdout"]

    def test_a_1m_model_nudges_at_80_percent_of_its_own_trigger(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
        transcript = tmp_path / "t.jsonl"
        # trigger = 1000000 - 33000 = 967000; 80% of that = 773600
        _write_transcript(transcript, cache_read=800_000, model="claude-opus-5-5")

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle({"session_id": "s-1m-nudge", "transcript_path": str(transcript), "cwd": str(tmp_path)})
        assert "~800k of 1000k context (80%, as the status line counts it); auto-compact at ~967k." in result["stdout"]
        assert "Compact fires soon" not in result["stdout"]


class TestGaugeGuardIsPerWindow:
    """DPLAN-0347 row 5: the guard follows the context window, not the session.

    A session id outlives every compaction, so the old key let the gauge fire at
    most twice in a session's entire life — and it went silent exactly when the
    next window started filling again. cadence stamps a new window on every
    PreCompact reset; the guard reads that stamp.
    """

    @staticmethod
    def _data(tmp_path):
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, cache_read=145_000)
        return {"session_id": "s-window", "transcript_path": str(transcript), "cwd": str(tmp_path)}

    def test_the_next_window_gets_its_own_nudge(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
        hook_data = self._data(tmp_path)
        stamps = [None, None, 1_758_000_000.0]
        monkeypatch.setattr(f"{CADENCE_MODULE}.window_opened_at", lambda *_a, **_k: stamps.pop(0))

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            first = handle(hook_data)
            repeat = handle(hook_data)
            after_compact = handle(hook_data)

        assert "CONTEXT GAUGE" in first["stdout"]
        assert repeat == {"stdout": "", "exit_code": 0}, "same window, already said"
        assert "CONTEXT GAUGE" in after_compact["stdout"], "a fresh window is a fresh climb"

    def test_an_unreadable_stamp_falls_back_to_one_key_and_warns(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")

        def _boom(*_args, **_kwargs):
            raise RuntimeError("no state dir")

        monkeypatch.setattr(f"{CADENCE_MODULE}.window_opened_at", _boom)

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            result = handle(self._data(tmp_path))

        assert "CONTEXT GAUGE" in result["stdout"], "the nudge is never lost to its own guard"
        assert "window stamp unreadable" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
