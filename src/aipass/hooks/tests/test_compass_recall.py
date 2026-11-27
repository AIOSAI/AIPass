# =================== AIPass ====================
# Name: test_compass_recall.py
# Version: 1.7.0
# Description: Tests for compass recall prompt handler
# Branch: hooks
# Created: 2026-07-16
# Modified: 2026-11-26
# =============================================

"""Tests for apps/handlers/prompt/compass_recall.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that compass_recall.py parses and imports, ruff and collection cover it
# sentry: no-test-needed(documentation) — handle()'s docstring, the documentation checker covers it
# sentry: no-test-needed(stdlib) — tempfile.gettempdir's choice of directory, the stdlib's own

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.lifecycle.compact import handle as pre_compact
from aipass.hooks.apps.handlers.prompt.compass_recall import handle
from aipass.hooks.apps.modules.cadence import reset_counter
from aipass.hooks.apps.modules.engine import dispatch
from aipass.memory import should_surface as governance_should_surface


@pytest.fixture(autouse=True)
def _manager_seat(request):
    """Recall is for manager seats; the handler tests run as one. TestSeatGate reads real passports."""
    if request.cls is not None and request.cls.__name__ == "TestSeatGate":
        yield
        return
    with patch("aipass.hooks.apps.modules.release_notice.is_manager_seat", return_value=True):
        yield


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
    The handler reads should_surface through memory's front door at
    call time, so that name is wrapped: memory's real verdict, record=False.
    """

    def _unrecorded(*args, **kwargs):
        return governance_should_surface(*args, **{**kwargs, "record": False})

    with (
        patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
        patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
        patch("aipass.hooks.apps.handlers.prompt.compass_recall.find_project_config", return_value=None),
        patch("aipass.hooks.apps.modules.cadence._GUARD_DIR", tmp_path),
        patch("aipass.memory.should_surface", side_effect=_unrecorded),
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


def _real_payload(root: Path) -> dict:
    """The official Claude Code hook keys, with every path under the test's own root."""
    return {
        "session_id": "abc-123-def",
        "transcript_path": str(root / "transcript.jsonl"),
        "cwd": str(root / "project"),
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
    (tmp_path / f"aipass-compass-recall-{session_id}.json").write_text(json.dumps(state), encoding="utf-8")


def _read_state(tmp_path, session_id):
    return json.loads((tmp_path / f"aipass-compass-recall-{session_id}.json").read_text(encoding="utf-8"))


def _recall(tmp_path, session_id, candidates, hooks_block):
    """One UserPromptSubmit through the handler with memory's REAL governance engine."""
    project = None if hooks_block is None else {"UserPromptSubmit": {"compass_recall": hooks_block}}
    with (
        patch("aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR", tmp_path),
        patch("aipass.hooks.apps.handlers.prompt.compass_recall.find_project_config", return_value=project),
        patch("aipass.devpulse.recall_decisions", return_value=candidates),
        patch("aipass.devpulse.mark_surfaced", return_value=1),
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
                "aipass.devpulse.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.mark_surfaced",
                return_value=1,
            ) as mock_mark,
            patch(
                "aipass.memory.should_surface",
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
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
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
                "aipass.devpulse.recall_decisions",
                return_value=[CANDIDATE_BAD],
            ),
            patch(
                "aipass.devpulse.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.should_surface",
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
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            result = handle(_payload("Is the usage gap a real bug?"))

            assert "[BAD] #84:" in result["stdout"]

    def test_empty_when_no_candidates(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.devpulse.recall_decisions",
                return_value=[],
            ),
            patch(
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
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
                "aipass.devpulse.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.memory.should_surface",
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
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
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
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
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
            result = handle(_payload("Some prompt about something important"))

            assert result["exit_code"] == 0
            assert result["stdout"] == ""

    def test_a_corrupt_state_file_is_left_untouched_never_overwritten(self, tmp_path):
        state_file = tmp_path / "aipass-compass-recall-corrupt.json"
        state_file.write_text("{not json", encoding="utf-8")
        result = _recall(tmp_path, "corrupt", [_candidate(1)], None)
        assert result == {"stdout": "", "exit_code": 0}
        assert state_file.read_text(encoding="utf-8") == "{not json"

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
                "aipass.devpulse.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.should_surface",
                return_value=(True, "Ready", updated_state),
            ),
            patch(
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            handle(_payload("How should we handle prompt config?", session_id="test-persist"))

            state_file = tmp_path / "aipass-compass-recall-test-persist.json"
            assert state_file.exists()
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            assert saved["surfaces_count"] == 1
            assert "56" in saved["surfaced_ids"]

    def test_multiple_candidates_partial_approval(self, tmp_path):
        def mock_should_surface(item_id, relevance, state, config=None, *, current_time=None, record=True):
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
                "aipass.devpulse.recall_decisions",
                return_value=[CANDIDATE_GOOD, CANDIDATE_LOW_RELEVANCE],
            ),
            patch(
                "aipass.devpulse.mark_surfaced",
                return_value=1,
            ) as mock_mark,
            patch(
                "aipass.memory.should_surface",
                side_effect=mock_should_surface,
            ),
            patch(
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
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
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            result = handle(_payload(""))

            assert result["exit_code"] == 0
            assert result["stdout"] == ""

    def test_no_session_id_degrades_safe(self, monkeypatch):
        """No session_id in payload or env = no injection, no crash."""
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
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
                "aipass.devpulse.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.should_surface",
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
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            result = handle(_real_payload(tmp_path))

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
                "aipass.devpulse.recall_decisions",
                return_value=[CANDIDATE_GOOD],
            ),
            patch(
                "aipass.devpulse.mark_surfaced",
                return_value=1,
            ),
            patch(
                "aipass.memory.should_surface",
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
                "aipass.memory.record_message",
                side_effect=lambda s: {**s, "messages_since_last": s.get("messages_since_last", 0) + 1},
            ),
        ):
            result = handle({"prompt": "How should we handle prompt config?"})

            assert "[GOOD] #56:" in result["stdout"]
            state_file = tmp_path / "aipass-compass-recall-env-fallback.json"
            assert state_file.exists()


def _seat_dir(tmp_path, name: str, citizen_class: str) -> Path:
    """A branch directory whose passport names *name* with *citizen_class*."""
    seat = tmp_path / name
    (seat / ".trinity").mkdir(parents=True)
    passport = {"branch_info": {"branch_name": name}, "identity": {"name": name, "citizen_class": citizen_class}}
    (seat / ".trinity" / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
    return seat


class TestSeatGate:
    """Compass is for manager agents, never builders: the gate is the passport's citizen_class, not a name."""

    def _recall_at(self, tmp_path, seat):
        payload = {**_payload("How should we handle prompt config?"), "cwd": str(seat)}
        with (
            patch("aipass.hooks.apps.handlers.prompt.compass_recall._STATE_DIR", tmp_path),
            patch("aipass.devpulse.recall_decisions", return_value=[CANDIDATE_GOOD]) as recall,
            patch("aipass.devpulse.mark_surfaced", return_value=1),
            patch("aipass.memory.should_surface", return_value=(True, "ok", {})),
            patch("aipass.memory.record_message", side_effect=lambda s: s),
        ):
            return handle(payload), recall

    def test_a_builder_hears_nothing_and_compass_is_not_read(self, tmp_path):
        result, recall = self._recall_at(tmp_path, _seat_dir(tmp_path, "canary", "specialist"))
        assert result == {"stdout": "", "exit_code": 0}
        recall.assert_not_called()

    def test_a_seat_with_no_passport_hears_nothing(self, tmp_path):
        bare = tmp_path / "bare"
        bare.mkdir()
        result, recall = self._recall_at(tmp_path, bare)
        assert result == {"stdout": "", "exit_code": 0}
        recall.assert_not_called()

    def test_a_builder_named_devpulse_hears_nothing(self, tmp_path):
        result, recall = self._recall_at(tmp_path, _seat_dir(tmp_path, "devpulse", "specialist"))
        assert result == {"stdout": "", "exit_code": 0}
        recall.assert_not_called()

    def test_devpulse_still_hears_its_decisions(self, tmp_path):
        result, _ = self._recall_at(tmp_path, _seat_dir(tmp_path, "devpulse", "manager"))
        assert "[GOOD] #56:" in result["stdout"]

    def test_a_repo_root_is_judged_by_the_seat_aipass_seat_names(self, tmp_path, monkeypatch):
        fleet = tmp_path / "src" / "aipass"
        _seat_dir(fleet, "devpulse", "manager")
        sentry = _seat_dir(fleet, "sentry", "specialist")
        monkeypatch.delenv("AIPASS_SEAT", raising=False)
        assert self._recall_at(tmp_path, tmp_path)[0] == {"stdout": "", "exit_code": 0}
        monkeypatch.setenv("AIPASS_SEAT", "devpulse")
        assert "[GOOD] #56:" in self._recall_at(tmp_path, tmp_path)[0]["stdout"]
        assert self._recall_at(tmp_path, sentry)[0] == {"stdout": "", "exit_code": 0}

    def test_a_future_manager_hears_recall_with_no_code_change(self, tmp_path):
        result, _ = self._recall_at(tmp_path, _seat_dir(tmp_path, "canary", "manager"))
        assert "[GOOD] #56:" in result["stdout"]


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
        assert "[hooks] compass_recall: refused #400: Session budget exhausted (5/5)" in lines

    def test_knobs_are_renamed_and_non_numbers_fall_to_defaults(self, tmp_path):
        """Read through handle() (fleet green leg 8), not _governance_config by name:
        the renamed max lets a sixth surfacing through, and the non-number knobs
        reach governance as its defaults rather than as text it cannot compare."""
        block = {
            "enabled": True,
            "timeout": 90,
            "max_per_session": 10,
            "threshold": 0.5,
            "min_messages_between": "ten",
            "cooldown_seconds": True,
        }
        _write_state(tmp_path, "knobs", surfaces_count=5, surfaced_ids=["1", "2", "3", "4", "5"])

        result = _recall(tmp_path, "knobs", [_candidate(400, relevance=0.6)], block)

        assert "[GOOD] #400: Decision 400" in result["stdout"]
        assert _read_state(tmp_path, "knobs")["surfaces_count"] == 6

    def test_precompact_opens_a_new_window_and_keeps_surfaced_ids(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "window")
        spent = [str(i) for i in range(1, 10)] + ["312"]
        _write_state(tmp_path, "window", surfaces_count=10, surfaced_ids=spent)
        candidates = [_candidate(312), _candidate(400)]
        assert _recall(tmp_path, "window", candidates, {"max_per_session": 10})["stdout"] == ""

        with patch("aipass.hooks.apps.handlers.lifecycle.compact._work_still_out", return_value=("window", [])):
            pre_compact({"session_id": "window", "cwd": str(tmp_path)})
        result = _recall(tmp_path, "window", candidates, {"max_per_session": 10})

        assert "#400:" in result["stdout"]
        assert "#312" not in result["stdout"]
        saved = _read_state(tmp_path, "window")
        assert saved["surfaces_count"] == 1
        assert saved["surfaced_ids"] == spent + ["400"]

    def test_the_budget_holds_within_one_window(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "same")
        reset_counter(hook_data={"session_id": "same"}, caller="compact")
        knobs = {"max_per_session": 1, "min_messages_between": 0, "cooldown_seconds": 0}

        assert "#400:" in _recall(tmp_path, "same", [_candidate(400)], knobs)["stdout"]
        assert _recall(tmp_path, "same", [_candidate(401)], knobs)["stdout"] == ""


class TestEngineCallsBudgetKeyedHandlers:
    def test_a_max_per_session_key_never_stops_the_engine_calling_the_handler(self, tmp_path):
        """max_per_session is the handler's own governance knob; the engine keeps no count of its own."""
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
        with patch(
            "aipass.hooks.apps.modules.engine._run_handler",
            return_value={"exit_code": 0, "stdout": "", "stderr": "", "elapsed_ms": 1.0},
        ) as mock_run:
            dispatch("UserPromptSubmit", json.dumps({"session_id": "no-engine-budget", "prompt": "test"}), config)
        assert [c.args[0] for c in mock_run.call_args_list] == [
            "aipass.hooks.apps.handlers.prompt.compass_recall.handle"
        ]
