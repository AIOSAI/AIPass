# =================== AIPass ====================
# Name: test_compass_recall.py
# Version: 1.2.0
# Description: Tests for compass recall prompt handler
# Branch: hooks
# Created: 2026-07-16
# Modified: 2026-07-28
# =============================================

"""Tests for handlers/prompt/compass_recall.py."""

import json
import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_trust_banners():
    """dispatch() runs both trust banners unconditionally on UserPromptSubmit.

    Same neutralization as test_engine.py's autouse fixture: without it, the
    banners do a real CWD-to-home walk against the actual ~/.aipass registry,
    and on a never-enrolled machine (fresh clone, CI runner) the one-time
    nudge short-circuits dispatch() before the handlers under test run.
    """
    with (
        patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
        patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
    ):
        yield


CANDIDATE_GOOD = {
    "id": 56,
    "rating": "good",
    "decision": "Never hardcode config in prompts",
    "context": "Prompt config management",
    "note": "",
    "tags": "config,prompts",
    "relevance": 0.7,
}

CANDIDATE_BAD = {
    "id": 84,
    "rating": "bad",
    "decision": "Usage gap is not a bug",
    "context": "Compass audit",
    "note": "",
    "tags": "compass",
    "relevance": 0.5,
}

CANDIDATE_LOW_RELEVANCE = {
    "id": 99,
    "rating": "good",
    "decision": "Some low relevance decision",
    "context": "Testing",
    "note": "",
    "tags": "test",
    "relevance": 0.1,
}

REAL_PAYLOAD = {
    "session_id": "abc-123-def",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/home/user/project",
    "permission_mode": "default",
    "hook_event_name": "UserPromptSubmit",
    "prompt": "How should we handle prompt config?",
}


def _payload(prompt, session_id="test-session"):
    """Build a realistic hook payload with documented keys."""
    return {"session_id": session_id, "prompt": prompt, "cwd": "/tmp"}


class TestCompassRecallHandler:
    def test_surfaces_relevant_decision(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.mark_surfaced",
                return_value=1,
            ) as mock_mark,
            patch(
                "aipass.memory.apps.modules.governance.should_surface",
                return_value=(
                    True,
                    "Ready to surface",
                    {
                        "surfaces_count": 1,
                        "messages_since_last": 0,
                        "last_surface_time": 1000.0,
                        "surfaced_ids": ["56"],
                    },
                ),
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload("How should we handle prompt config?"))

            assert result["exit_code"] == 0
            assert "[GOOD] #56:" in result["stdout"]
            assert "Never hardcode config in prompts" in result["stdout"]
            assert result["sound"] == "compass recall"
            mock_mark.assert_called_once_with([56])

    def test_formats_bad_rating(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[CANDIDATE_BAD],
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.apps.modules.governance.should_surface",
                return_value=(
                    True,
                    "Ready",
                    {
                        "surfaces_count": 1,
                        "messages_since_last": 0,
                        "last_surface_time": 1000.0,
                        "surfaced_ids": ["84"],
                    },
                ),
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload("Is the usage gap a real bug?"))

            assert "[BAD] #84:" in result["stdout"]

    def test_empty_when_no_candidates(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[],
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload("Some prompt about something"))

            assert result["exit_code"] == 0
            assert result["stdout"] == ""

    def test_empty_when_governance_suppresses(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.memory.apps.modules.governance.should_surface",
                return_value=(
                    False,
                    "Spacing not met",
                    {
                        "surfaces_count": 0,
                        "messages_since_last": 1,
                        "last_surface_time": 0.0,
                        "surfaced_ids": [],
                    },
                ),
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload("How should we handle prompt config?"))

            assert result["exit_code"] == 0
            assert result["stdout"] == ""

    def test_empty_when_prompt_too_short(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload("Hi"))

            assert result["exit_code"] == 0
            assert result["stdout"] == ""

    def test_never_blocks_on_import_error(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._state_path",
                return_value=tmp_path / "state.json",
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._load_state",
                side_effect=Exception("DB locked"),
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload("Some prompt about something important"))

            assert result["exit_code"] == 0
            assert result["stdout"] == ""

    def test_persists_governance_state(self, tmp_path):
        updated_state = {
            "surfaces_count": 1,
            "messages_since_last": 0,
            "last_surface_time": 1000.0,
            "surfaced_ids": ["56"],
        }

        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.apps.modules.governance.should_surface",
                return_value=(True, "Ready", updated_state),
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            handle(_payload("How should we handle prompt config?", session_id="test-persist"))

            state_file = tmp_path / "aipass-compass-recall-test-persist.json"
            assert state_file.exists()
            saved = json.loads(state_file.read_text())
            assert saved["surfaces_count"] == 1
            assert "56" in saved["surfaced_ids"]

    def test_multiple_candidates_partial_approval(self, tmp_path):
        def mock_should_surface(item_id, relevance, state, config=None, *, current_time=None):
            if item_id == "56":
                new_st = {**state, "surfaces_count": 1, "surfaced_ids": list(state.get("surfaced_ids", [])) + ["56"]}
                return True, "Ready", new_st
            return False, "Below threshold", state

        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[CANDIDATE_GOOD, CANDIDATE_LOW_RELEVANCE],
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.mark_surfaced",
                return_value=1,
            ) as mock_mark,
            patch(
                "aipass.memory.apps.modules.governance.should_surface",
                side_effect=mock_should_surface,
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload("How should we handle prompt config?"))

            assert "[GOOD] #56:" in result["stdout"]
            assert "#99" not in result["stdout"]
            mock_mark.assert_called_once_with([56])

    def test_empty_prompt_no_cross_branch_import(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(_payload(""))

            assert result["exit_code"] == 0
            assert result["stdout"] == ""

    def test_no_session_id_degrades_safe(self):
        """No session_id in payload or env = no injection, no crash."""
        from aipass.hooks.apps.handlers.prompt.compass_recall import handle

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
            result = handle({"prompt": "How should we handle prompt config?"})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_real_documented_payload_shape(self, tmp_path):
        """Surfaces from a payload using the official Claude Code hook keys."""
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.apps.modules.governance.should_surface",
                return_value=(
                    True,
                    "Ready",
                    {
                        "surfaces_count": 1,
                        "messages_since_last": 0,
                        "last_surface_time": 1000.0,
                        "surfaced_ids": ["56"],
                    },
                ),
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle(REAL_PAYLOAD)

            assert result["exit_code"] == 0
            assert "[GOOD] #56:" in result["stdout"]

    def test_env_var_fallback_for_session_id(self, tmp_path):
        """Falls back to CLAUDE_CODE_SESSION_ID env var if payload has no session_id."""
        with (
            patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "env-fallback"}),
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.apps.modules.compass.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.apps.modules.governance.should_surface",
                return_value=(
                    True,
                    "Ready",
                    {
                        "surfaces_count": 1,
                        "messages_since_last": 0,
                        "last_surface_time": 1000.0,
                        "surfaced_ids": ["56"],
                    },
                ),
            ),
            patch(
                "aipass.memory.apps.modules.governance.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            from aipass.hooks.apps.handlers.prompt.compass_recall import handle

            result = handle({"prompt": "How should we handle prompt config?"})

            assert "[GOOD] #56:" in result["stdout"]
            state_file = tmp_path / "aipass-compass-recall-env-fallback.json"
            assert state_file.exists()


class TestEngineBudget:
    def test_check_budget_allows_first_fire(self):
        from aipass.hooks.apps.modules.engine import _check_budget

        allowed, reason = _check_budget("test_hook", {"max_per_session": 5}, {})
        assert allowed is True

    def test_check_budget_blocks_when_exhausted(self):
        from aipass.hooks.apps.modules.engine import _check_budget

        state = {"test_hook": {"fire_count": 5}}
        allowed, reason = _check_budget("test_hook", {"max_per_session": 5}, state)
        assert allowed is False
        assert "exhausted" in reason

    def test_check_budget_spacing_skipped_on_first_fire(self):
        from aipass.hooks.apps.modules.engine import _check_budget

        state = {"test_hook": {"fire_count": 0, "turns_since_fire": 0}}
        allowed, reason = _check_budget("test_hook", {"min_spacing_turns": 10}, state)
        assert allowed is True

    def test_check_budget_spacing_enforced_after_fire(self):
        from aipass.hooks.apps.modules.engine import _check_budget

        state = {"test_hook": {"fire_count": 1, "turns_since_fire": 3}}
        allowed, reason = _check_budget("test_hook", {"min_spacing_turns": 10}, state)
        assert allowed is False
        assert "spacing" in reason

    def test_check_budget_spacing_passes_after_enough_turns(self):
        from aipass.hooks.apps.modules.engine import _check_budget

        state = {"test_hook": {"fire_count": 1, "turns_since_fire": 10}}
        allowed, reason = _check_budget("test_hook", {"min_spacing_turns": 10}, state)
        assert allowed is True

    def test_check_budget_cooldown_enforced(self):
        import time

        from aipass.hooks.apps.modules.engine import _check_budget

        state = {"test_hook": {"fire_count": 1, "last_fire_time": time.time() - 10}}
        allowed, reason = _check_budget("test_hook", {"cooldown_seconds": 300}, state)
        assert allowed is False
        assert "cooldown" in reason

    def test_check_budget_cooldown_expired(self):
        import time

        from aipass.hooks.apps.modules.engine import _check_budget

        state = {"test_hook": {"fire_count": 1, "last_fire_time": time.time() - 400}}
        allowed, reason = _check_budget("test_hook", {"cooldown_seconds": 300}, state)
        assert allowed is True

    def test_budget_state_persistence(self, tmp_path):
        from aipass.hooks.apps.modules.engine import (
            _load_budget_state,
            _save_budget_state,
        )

        state = {"compass_recall": {"fire_count": 2, "last_fire_time": 1000.0, "turns_since_fire": 5}}

        with patch("aipass.hooks.apps.modules.engine._budget_state_path", return_value=tmp_path / "budget.json"):
            _save_budget_state(state)
            loaded = _load_budget_state()
            assert loaded["compass_recall"]["fire_count"] == 2

    def test_budget_state_missing_returns_empty(self, tmp_path):
        from aipass.hooks.apps.modules.engine import _load_budget_state

        with patch(
            "aipass.hooks.apps.modules.engine._budget_state_path",
            return_value=tmp_path / "nonexistent.json",
        ):
            assert _load_budget_state() == {}

    def test_dispatch_suppresses_over_budget_handler(self, tmp_path):
        from aipass.hooks.apps.modules.engine import dispatch

        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "test_hook": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.prompt.compass_recall.handle",
                    "max_per_session": 0,
                },
            },
        }
        budget_file = tmp_path / "budget.json"

        with (
            patch("aipass.hooks.apps.modules.engine._budget_state_path", return_value=budget_file),
            patch("aipass.hooks.apps.modules.engine._run_handler") as mock_run,
        ):
            dispatch("UserPromptSubmit", json.dumps({"session_id": "budget-test", "prompt": "test"}), config)
            mock_run.assert_not_called()

    def test_dispatch_records_fire_on_output(self, tmp_path):
        from aipass.hooks.apps.modules.engine import dispatch

        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "test_hook": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.prompt.compass_recall.handle",
                    "max_per_session": 10,
                },
            },
        }
        budget_file = tmp_path / "budget.json"

        with (
            patch("aipass.hooks.apps.modules.engine._budget_state_path", return_value=budget_file),
            patch(
                "aipass.hooks.apps.modules.engine._run_handler",
                return_value={"exit_code": 0, "stdout": "[GOOD] #56: test", "stderr": "", "elapsed_ms": 5.0},
            ),
        ):
            dispatch("UserPromptSubmit", json.dumps({"session_id": "fire-test", "prompt": "test"}), config)

            assert budget_file.exists()
            state = json.loads(budget_file.read_text())
            assert state["test_hook"]["fire_count"] == 1
            assert state["test_hook"]["turns_since_fire"] == 0

    def test_dispatch_threads_payload_session_id(self, tmp_path):
        """Budget state file is keyed by payload session_id, not env var."""
        from aipass.hooks.apps.modules.engine import dispatch

        config = {
            "hooks_enabled": True,
            "UserPromptSubmit": {
                "test_hook": {
                    "enabled": True,
                    "handler": "aipass.hooks.apps.handlers.prompt.compass_recall.handle",
                    "max_per_session": 10,
                },
            },
        }

        with (
            patch(
                "aipass.hooks.apps.modules.engine._run_handler",
                return_value={"exit_code": 0, "stdout": "output", "stderr": "", "elapsed_ms": 1.0},
            ),
        ):
            dispatch(
                "UserPromptSubmit",
                json.dumps({"session_id": "payload-sid", "prompt": "test"}),
                config,
            )

            from aipass.hooks.apps.modules.engine import _budget_state_path

            path = _budget_state_path("payload-sid")
            assert path is not None
            assert "payload-sid" in str(path)
