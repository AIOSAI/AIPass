# =================== AIPass ====================
# Name: test_compass_recall.py
# Version: 1.3.0
# Description: Tests for compass recall prompt handler
# Branch: hooks
# Created: 2026-07-16
# Modified: 2026-09-14
# =============================================

"""Tests for handlers/prompt/compass_recall.py."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_trust_banners(tmp_path):
    """dispatch() runs both trust banners unconditionally on UserPromptSubmit.

    Same neutralization as test_engine.py's autouse fixture: without it, the
    banners do a real CWD-to-home walk against the actual ~/.aipass registry,
    and on a never-enrolled machine (fresh clone, CI runner) the one-time
    nudge short-circuits dispatch() before the handlers under test run.

    The handler reads the project hooks.json and the cadence window stamp
    itself (FPLAN-0588): neither may reach the real repo config, the trust
    registry, or a live session's stamp in the temp dir. Memory's governance
    engine logs each surfacing to memory's own files; that is not ours to write.
    """
    with (
        patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
        patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
        patch("aipass.hooks.apps.handlers.prompt.compass_recall.find_project_config", return_value=None),
        patch("aipass.hooks.apps.modules.cadence._GUARD_DIR", tmp_path),
        patch("aipass.memory.apps.handlers.governance.engine.json_handler.log_operation"),
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
    "transcript_path": str(Path(tempfile.gettempdir()) / "transcript.jsonl"),
    "cwd": str(Path.home() / "project"),
    "permission_mode": "default",
    "hook_event_name": "UserPromptSubmit",
    "prompt": "How should we handle prompt config?",
}


def _payload(prompt, session_id="test-session"):
    """Build a realistic hook payload with documented keys."""
    return {"session_id": session_id, "prompt": prompt, "cwd": tempfile.gettempdir()}


def _candidate(item_id, relevance=0.8):
    return {"id": item_id, "rating": "good", "decision": f"Decision {item_id}", "relevance": relevance}


def _write_state(tmp_path, session_id, **fields):
    """A governance state file; last surfaced long ago, so only the budget can refuse."""
    state = {"surfaces_count": 0, "messages_since_last": 93, "last_surface_time": 1000.0, "surfaced_ids": [], **fields}
    (tmp_path / f"aipass-compass-recall-{session_id}.json").write_text(json.dumps(state))


def _read_state(tmp_path, session_id):
    return json.loads((tmp_path / f"aipass-compass-recall-{session_id}.json").read_text())


def _recall(tmp_path, session_id, candidates, hooks_block):
    """One UserPromptSubmit through the handler with memory's REAL governance engine."""
    from aipass.hooks.apps.handlers.prompt.compass_recall import handle

    project = None if hooks_block is None else {"UserPromptSubmit": {"compass_recall": hooks_block}}
    with (
        patch("aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR", tmp_path),
        patch("aipass.hooks.apps.handlers.prompt.compass_recall.find_project_config", return_value=project),
        patch("aipass.devpulse.apps.modules.compass.recall_decisions", return_value=candidates),
        patch("aipass.devpulse.apps.modules.compass.mark_surfaced", return_value=1),
    ):
        return handle(_payload("How should we handle prompt config?", session_id=session_id))


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


class TestGovernanceKnobsAndWindow:
    """FPLAN-0588 (devpulse 9d6fbf8e): hooks.json knobs reach governance, the
    budget is per context window, a budget refusal is logged. The real governance
    engine throughout: a mocked should_surface cannot tell whether a knob arrived."""

    def test_max_per_session_knob_lets_a_sixth_surfacing_through(self, tmp_path):
        _write_state(tmp_path, "knob", surfaces_count=5, surfaced_ids=["1", "2", "3", "4", "5"])

        result = _recall(tmp_path, "knob", [_candidate(400)], {"max_per_session": 10})

        assert "[GOOD] #400: Decision 400" in result["stdout"]
        assert _read_state(tmp_path, "knob")["surfaces_count"] == 6

    def test_budget_refusal_is_logged_with_id_and_reason(self, tmp_path):
        _write_state(tmp_path, "noknob", surfaces_count=5, surfaced_ids=["1", "2", "3", "4", "5"])

        with patch("aipass.hooks.apps.handlers.prompt.compass_recall.logger") as mock_logger:
            result = _recall(tmp_path, "noknob", [_candidate(400)], None)

        assert result["stdout"] == ""
        lines = [c.args[0] % c.args[1:] for c in mock_logger.info.call_args_list]
        assert "[HOOKS] compass_recall: refused #400: Session budget exhausted (5/5)" in lines

    def test_knobs_are_renamed_and_non_numbers_fall_to_defaults(self):
        from aipass.hooks.apps.handlers.prompt.compass_recall import _governance_config

        block = {
            "enabled": True,
            "timeout": 90,
            "max_per_session": 10,
            "threshold": 0.5,
            "min_messages_between": "ten",
            "cooldown_seconds": True,
        }
        project = {"UserPromptSubmit": {"compass_recall": block}}
        with patch("aipass.hooks.apps.handlers.prompt.compass_recall.find_project_config", return_value=project):
            assert _governance_config() == {"max_surfaces_per_session": 10, "threshold": 0.5}

    def test_precompact_opens_a_new_window_and_keeps_surfaced_ids(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.handlers.lifecycle.compact import handle as pre_compact

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "window")
        spent = [str(i) for i in range(1, 10)] + ["312"]
        _write_state(tmp_path, "window", surfaces_count=10, surfaced_ids=spent)
        candidates = [_candidate(312), _candidate(400)]
        assert _recall(tmp_path, "window", candidates, {"max_per_session": 10})["stdout"] == ""

        with patch("aipass.hooks.apps.handlers.lifecycle.compact._get_git_info", return_value=None):
            pre_compact({"session_id": "window", "cwd": str(tmp_path)})
        result = _recall(tmp_path, "window", candidates, {"max_per_session": 10})

        assert "#400:" in result["stdout"]
        assert "#312" not in result["stdout"]
        saved = _read_state(tmp_path, "window")
        assert saved["surfaces_count"] == 1
        assert saved["surfaced_ids"] == spent + ["400"]

    def test_the_budget_holds_within_one_window(self, tmp_path, monkeypatch):
        from aipass.hooks.apps.modules.cadence import reset_counter

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "same")
        reset_counter(hook_data={"session_id": "same"}, caller="compact")
        knobs = {"max_per_session": 1, "min_messages_between": 0, "cooldown_seconds": 0}

        assert "#400:" in _recall(tmp_path, "same", [_candidate(400)], knobs)["stdout"]
        assert _recall(tmp_path, "same", [_candidate(401)], knobs)["stdout"] == ""


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

    def test_dispatch_reopens_the_budget_when_a_new_window_opens(self, tmp_path, monkeypatch):
        """The engine counts compass_recall's fires against the same max_per_session.
        Kept per session id, it silences recall however many windows follow (FPLAN-0588)."""
        from aipass.hooks.apps.modules.cadence import reset_counter
        from aipass.hooks.apps.modules.engine import dispatch

        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "reopen")
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
        budget_file.write_text(json.dumps({"test_hook": {"fire_count": 10, "turns_since_fire": 40}}))
        payload = json.dumps({"session_id": "reopen", "prompt": "test"})

        with (
            patch("aipass.hooks.apps.modules.engine._budget_state_path", return_value=budget_file),
            patch(
                "aipass.hooks.apps.modules.engine._run_handler",
                return_value={"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1.0},
            ) as mock_run,
        ):
            dispatch("UserPromptSubmit", payload, config)
            mock_run.assert_not_called()

            reset_counter(hook_data={"session_id": "reopen"}, caller="compact")
            dispatch("UserPromptSubmit", payload, config)
            mock_run.assert_called_once()

        assert json.loads(budget_file.read_text())["test_hook"]["fire_count"] == 0
