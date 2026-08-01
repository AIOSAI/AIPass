# =================== AIPass ====================
# Name: test_session_start.py
# Version: 1.0.0
# Description: Tests for SessionStart cadence reset handler
# Branch: hooks
# Created: 2026-07-07
# Modified: 2026-07-07
# =============================================

"""Tests for apps/handlers/lifecycle/session_start.py."""

import json
import os
from unittest.mock import patch

CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


def _reset_cadence_globals():
    import aipass.hooks.apps.modules.cadence as mod

    mod._turn = None
    mod._config = None


def _write_state(tmp_path, turn, session="test-session"):
    import time

    state_file = tmp_path / f"aipass-cadence-{session}.json"
    state_file.write_text(json.dumps({"turn": turn, "token": -1}))
    old = time.time() - 10
    os.utime(state_file, (old, old))
    return state_file


class TestSessionStartHandler:
    def setup_method(self):
        _reset_cadence_globals()

    def test_startup_resets_cadence(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle

        state_file = _write_state(tmp_path, turn=7)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "startup", "session_id": "test-session"})

        assert result["exit_code"] == 0
        assert result["sound"] == "cadence reset"
        data = json.loads(state_file.read_text())
        assert data["turn"] == -1

    def test_clear_resets_cadence(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle

        state_file = _write_state(tmp_path, turn=3)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "clear", "session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text())
        assert data["turn"] == -1

    def test_resume_skips_reset(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle

        state_file = _write_state(tmp_path, turn=7)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "resume", "session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text())
        assert data["turn"] == 7

    def test_compact_source_skips_reset(self, tmp_path):
        """source=compact is skipped — PreCompact (compact.py) already reset for the
        same boundary. A duplicate reset here re-arms the regroup token a second
        time per compact (DPLAN-0278 over-fire mechanism)."""
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle

        state_file = _write_state(tmp_path, turn=5)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "compact", "session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text())
        assert data["turn"] == 5

    def test_empty_source_resets(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle

        state_file = _write_state(tmp_path, turn=4)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text())
        assert data["turn"] == -1

    def test_no_stdout_output(self):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle

        with patch("importlib.import_module"):
            result = handle({"source": "startup"})

        assert result["stdout"] == ""

    def test_cadence_import_failure_does_not_crash(self):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle

        with patch("importlib.import_module", side_effect=ImportError("boom")):
            result = handle({"source": "startup"})

        assert result["exit_code"] == 0


class TestSessionStartCadenceIntegration:
    """End-to-end: SessionStart reset -> next turn fires all loaders."""

    def setup_method(self):
        _reset_cadence_globals()

    def test_clear_then_all_loaders_fire(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {
                        "tier0": {"period": 5, "offset": 0},
                        "navmap": {"period": 5, "offset": 0},
                        "branch": {"offset": 0},
                    },
                }
            )
        )

        _write_state(tmp_path, turn=3)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            handle({"source": "clear", "session_id": "test-session"})

        _reset_cadence_globals()

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("tier0") is True
            _reset_cadence_globals()
            assert should_fire("navmap") is True
            _reset_cadence_globals()
            assert should_fire("branch") is True

    def test_resume_does_not_reset_counter_continues(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.session_start import handle
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {
                        "tier0": {"period": 5, "offset": 0},
                        "navmap": {"period": 5, "offset": 0},
                    },
                }
            )
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            handle({"source": "resume", "session_id": "test-session"})

        _reset_cadence_globals()

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("tier0") is False
            _reset_cadence_globals()
            assert should_fire("navmap") is False
