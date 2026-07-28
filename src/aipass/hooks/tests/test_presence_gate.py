"""Tests for the presence gate handler."""

import json
import os
from unittest.mock import MagicMock, patch

from aipass.hooks.apps.handlers.security import presence_gate


def _make_mocks(our_pid: int | None = 1000, occupant=None):
    """Build presence + cc_sessions mocks for the gate."""
    presence_mock = MagicMock()
    presence_mock._resolve_session_pid.return_value = our_pid

    cc_mock = MagicMock()
    cc_mock.find_occupant.return_value = occupant

    def import_router(name):
        if "presence" in name and "cc_sessions" not in name:
            return presence_mock
        if "cc_sessions" in name:
            return cc_mock
        raise ImportError(name)

    return presence_mock, cc_mock, import_router


_OCCUPANT = {
    "pid": 5000,
    "sessionId": "existing-session",
    "cwd": "/tmp/branch",
    "kind": "interactive",
    "name": "hooks-ab",
}


def _blocking():
    """Patch observe-only off so blocking tests exercise the block path."""
    return patch.object(presence_gate, "_OBSERVE_ONLY", False)


class TestResolveBranch:
    def test_uses_hook_data_cwd(self, tmp_path):
        branch_dir = tmp_path / "devpulse"
        branch_dir.mkdir()
        (branch_dir / ".trinity").mkdir()
        assert presence_gate._resolve_branch({"cwd": str(branch_dir)}) == "devpulse"

    def test_walks_up_to_branch_root(self, tmp_path):
        branch_dir = tmp_path / "hooks"
        (branch_dir / "apps" / "modules").mkdir(parents=True)
        sub = branch_dir / "apps" / "modules"
        assert presence_gate._resolve_branch({"cwd": str(sub)}) == "hooks"

    def test_stops_at_repo_root(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert presence_gate._resolve_branch({"cwd": str(tmp_path)}) == tmp_path.name

    def test_fallback_to_path_cwd_when_no_cwd_in_hook_data(self):
        result = presence_gate._resolve_branch({})
        assert isinstance(result, str)
        assert len(result) > 0


class TestHandle:
    def test_no_occupant_allows(self):
        _, _, router = _make_mocks(our_pid=1000, occupant=None)
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True):
            with patch("importlib.import_module", side_effect=router):
                result = presence_gate.handle({})
        assert result["exit_code"] == 0

    def test_occupant_blocks(self):
        _, _, router = _make_mocks(our_pid=1000, occupant=_OCCUPANT)
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({})
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "5000" in parsed["reason"]

    def test_block_includes_session_info(self):
        _, _, router = _make_mocks(our_pid=1000, occupant=_OCCUPANT)
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({})
        parsed = json.loads(result["stdout"])
        assert "existing" in parsed["reason"]
        assert "interactive" in parsed["reason"]

    def test_subagent_skipped(self):
        result = presence_gate.handle({"agent_type": "Explore"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_general_purpose_subagent_skipped(self):
        result = presence_gate.handle({"agent_type": "general-purpose"})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_claude_agent_type_not_skipped(self):
        _, _, router = _make_mocks(our_pid=1000, occupant=None)
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True):
            with patch("importlib.import_module", side_effect=router):
                result = presence_gate.handle({"agent_type": "claude"})
        assert result["exit_code"] == 0

    def test_main_agent_not_skipped(self):
        _, _, router = _make_mocks(our_pid=1000, occupant=None)
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True):
            with patch("importlib.import_module", side_effect=router):
                result = presence_gate.handle({"agent_type": "main"})
        assert result["exit_code"] == 0

    def test_dispatched_session_skipped(self):
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "dispatched"}, clear=True):
            result = presence_gate.handle({})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_daemon_session_skipped(self):
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "daemon"}, clear=True):
            result = presence_gate.handle({})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_exclude_pid_passed_to_find_occupant(self):
        _, cc_mock, router = _make_mocks(our_pid=1000, occupant=None)
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True):
            with patch("importlib.import_module", side_effect=router):
                presence_gate.handle({})
        cc_mock.find_occupant.assert_called_once()
        assert cc_mock.find_occupant.call_args[1]["exclude_pid"] == 1000

    def test_no_session_pid_allows(self):
        _, _, router = _make_mocks(our_pid=None, occupant=None)
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True):
            with patch("importlib.import_module", side_effect=router):
                result = presence_gate.handle({})
        assert result["exit_code"] == 0

    def test_block_message_includes_branch(self, tmp_path):
        branch_dir = tmp_path / "devpulse"
        branch_dir.mkdir()
        (branch_dir / ".trinity").mkdir()
        _, _, router = _make_mocks(our_pid=1000, occupant=_OCCUPANT)
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({"cwd": str(branch_dir)})
        parsed = json.loads(result["stdout"])
        assert "devpulse" in parsed["reason"]
        assert "reclaim" in parsed["reason"]

    def test_observe_only_logs_but_allows(self):
        _, _, router = _make_mocks(our_pid=1000, occupant=_OCCUPANT)
        with (
            patch.object(presence_gate, "_OBSERVE_ONLY", True),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({})
        assert result["exit_code"] == 0
        assert result["sound"] == "presence gate"

    def test_gate_error_allows(self):
        with patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True):
            with patch("importlib.import_module", side_effect=ImportError("boom")):
                result = presence_gate.handle({})
        assert result["exit_code"] == 0


class TestHandleStop:
    def test_stop_is_noop(self):
        result = presence_gate.handle_stop({})
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_stop_does_not_call_anything(self):
        mock = MagicMock()
        with patch("importlib.import_module", return_value=mock):
            presence_gate.handle_stop({})
        mock.release.assert_not_called()
        mock.claim.assert_not_called()
        mock.find_occupant.assert_not_called()
