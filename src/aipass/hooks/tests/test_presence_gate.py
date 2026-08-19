"""Tests for the presence gate handler."""

import json
import os
from unittest.mock import MagicMock, patch

from aipass.hooks.apps.handlers.security import presence_gate


def _make_mocks(our_pid: int | None = 1000, occupant=None, all_sessions=None):
    """Build presence + cc_sessions mocks for the gate."""
    presence_mock = MagicMock()
    presence_mock._resolve_session_pid.return_value = our_pid

    cc_mock = MagicMock()
    cc_mock.find_occupant.return_value = occupant
    # Real list, not a MagicMock: the gate iterates this to find its own
    # session, and a non-iterable would be swallowed by the gate's own
    # error handler as a silent allow.
    cc_mock.read_all_sessions.return_value = list(all_sessions or [])

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

    def test_observe_only_plays_no_sound(self):
        """Audio for a decision the gate is NOT making is worse noise than the log line."""
        _, _, router = _make_mocks(our_pid=1000, occupant=_OCCUPANT)
        with (
            patch.object(presence_gate, "_OBSERVE_ONLY", True),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({})
        assert "sound" not in result

    def test_observe_only_records_at_info_not_warning(self):
        """Declining to act is chosen behavior — compass #277. Evidence kept, escalation dropped."""
        _, _, router = _make_mocks(our_pid=1000, occupant=_OCCUPANT)
        with (
            patch.object(presence_gate, "_OBSERVE_ONLY", True),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
            patch.object(presence_gate, "logger") as mock_logger,
        ):
            presence_gate.handle({})
        assert [c for c in mock_logger.info.call_args_list if c.args and "would-block" in c.args[0]]
        assert not [c for c in mock_logger.warning.call_args_list if c.args and "would-block" in c.args[0]]

    def test_real_block_still_warns(self):
        """GUARD: only the observe-only path was quietened."""
        _, _, router = _make_mocks(our_pid=1000, occupant=_OCCUPANT)
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
            patch.object(presence_gate, "logger") as mock_logger,
        ):
            presence_gate.handle({})
        assert [c for c in mock_logger.warning.call_args_list if c.args and "BLOCKED" in c.args[0]]


class TestRemedyIsSatisfiable:
    """A gate must be satisfiable by an action it permits. Ruling (a), DPLAN-0310
    (Patrick, 2026-08-18): one brain = one INTERACTIVE brain — a bg session is a
    job, not a seat, so it never gates at all. The previous pin (bg blocks with an
    honest cannot-stop message) is superseded by the ruling: an unsatisfiable
    block, however honestly worded, only teaches routing around the gate."""

    BG_OCCUPANT = {
        "pid": 434858,
        "sessionId": "bdbc613b",
        "cwd": "/tmp/branch",
        "kind": "bg",
        "name": "codeql debugging",
    }

    def _handle(self, occupant):
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant)
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            return presence_gate.handle({})

    def test_bg_occupant_is_a_job_not_a_seat_so_it_never_gates(self):
        """Ruling (a): the arriver is ALLOWED through when the only occupant is bg."""
        result = self._handle(self.BG_OCCUPANT)
        assert result["exit_code"] == 0

    def test_background_kind_spelling_also_skips(self):
        result = self._handle({**self.BG_OCCUPANT, "kind": "background"})
        assert result["exit_code"] == 0

    def test_interactive_occupant_still_offers_reclaim(self):
        """GUARD: interactive occupants still block, and the remedy that works survives."""
        result = self._handle(_OCCUPANT)
        assert result["exit_code"] == 2
        assert "reclaim" in json.loads(result["stdout"])["reason"]

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


def _seat(pid: int, started_ms: int, kind: str = "interactive", sid: str = "sid") -> dict:
    return {"pid": pid, "sessionId": sid, "cwd": "/tmp/branch", "kind": kind, "startedAt": started_ms}


class TestSecondSeatIsRefusedInWords:
    """The dispatch's pin: a second interactive session on an occupied branch is
    refused, and the refusal says who holds it and how to get in."""

    def test_refusal_names_the_occupant_and_the_way_in(self, tmp_path):
        occupant = _seat(5000, 1_000_000_000_000, sid="abc12345")
        ours = _seat(1000, 1_000_000_900_000)
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant, all_sessions=[ours, occupant])
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({"cwd": str(tmp_path)})
        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "PID 5000" in reason
        assert "abc12345" in reason
        assert "sessions reclaim @" in reason

    def test_refusal_names_the_arriver_too(self, tmp_path):
        """Five weeks of soak logged only the occupant — unanswerable evidence."""
        occupant = _seat(5000, 1_000_000_000_000)
        ours = _seat(1000, 1_000_000_900_000, sid="newseat1")
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant, all_sessions=[ours, occupant])
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({"cwd": str(tmp_path)})
        reason = json.loads(result["stdout"])["reason"]
        assert "PID 1000" in reason and "newseat1" in reason

    def test_observe_only_logs_the_arriver(self, tmp_path):
        occupant = _seat(5000, 1_000_000_000_000)
        ours = _seat(1000, 1_000_000_900_000, sid="newseat1")
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant, all_sessions=[ours, occupant])
        with (
            patch.object(presence_gate, "_OBSERVE_ONLY", True),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
            patch.object(presence_gate.logger, "info") as mock_info,
        ):
            result = presence_gate.handle({"cwd": str(tmp_path)})
        assert result == {"exit_code": 0, "stdout": ""}
        logged = " ".join(str(c) for c in mock_info.call_args_list)
        assert "arriver" in logged


class TestTwoSeatsCannotDeadlockEachOther:
    """Verified against the real module: find_occupant returns the first non-self
    match, so without a tiebreak each of two live seats sees the OTHER and
    enforcement refuses BOTH — and the blocked prompt is the very thing that
    would have run the remedy."""

    def test_the_incumbent_is_allowed_through(self, tmp_path):
        occupant = _seat(5000, 1_000_000_900_000)  # arrived later
        ours = _seat(1000, 1_000_000_000_000)  # we were here first
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant, all_sessions=[ours, occupant])
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({"cwd": str(tmp_path)})
        assert result == {"exit_code": 0, "stdout": ""}

    def test_the_newer_seat_is_the_one_refused(self, tmp_path):
        occupant = _seat(5000, 1_000_000_000_000)
        ours = _seat(1000, 1_000_000_900_000)
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant, all_sessions=[ours, occupant])
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            result = presence_gate.handle({"cwd": str(tmp_path)})
        assert result["exit_code"] == 2

    def test_exactly_one_of_two_live_seats_is_refused(self, tmp_path):
        """The property that matters, asserted as a property: run the gate from
        BOTH sides of the same pair and count the refusals."""
        older = _seat(1000, 1_000_000_000_000, sid="older")
        newer = _seat(2000, 1_000_000_900_000, sid="newer")
        refused = 0
        for me, them in ((older, newer), (newer, older)):
            _, _, router = _make_mocks(our_pid=me["pid"], occupant=them, all_sessions=[older, newer])
            with (
                _blocking(),
                patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
                patch("importlib.import_module", side_effect=router),
            ):
                if presence_gate.handle({"cwd": str(tmp_path)})["exit_code"] == 2:
                    refused += 1
        assert refused == 1, f"{refused} of 2 seats refused — 0 is no gate, 2 is a bricked branch"

    def test_unreadable_clock_never_promotes_us_to_incumbent(self, tmp_path):
        """Fail toward refusing the arriver, never toward letting both through."""
        occupant = _seat(5000, 1_000_000_000_000)
        ours = {"pid": 1000, "sessionId": "x", "cwd": "/tmp/branch", "kind": "interactive"}
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant, all_sessions=[ours, occupant])
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            assert presence_gate.handle({"cwd": str(tmp_path)})["exit_code"] == 2

    def test_no_session_file_of_our_own_is_not_incumbency(self, tmp_path):
        occupant = _seat(5000, 1_000_000_000_000)
        _, _, router = _make_mocks(our_pid=1000, occupant=occupant, all_sessions=[occupant])
        with (
            _blocking(),
            patch.dict(os.environ, {"AIPASS_SESSION_TYPE": "interactive"}, clear=True),
            patch("importlib.import_module", side_effect=router),
        ):
            assert presence_gate.handle({"cwd": str(tmp_path)})["exit_code"] == 2


class TestSessionStart:
    def test_reads_epoch_milliseconds(self):
        assert presence_gate._session_start({"startedAt": 1_000_000_000_000}) == 1_000_000_000.0

    def test_reads_iso_string(self):
        got = presence_gate._session_start({"startedAt": "2026-08-18T12:00:00Z"})
        assert got is not None and got > 0

    def test_missing_start_is_none_not_zero(self):
        """Zero would rank us as the oldest thing alive."""
        assert presence_gate._session_start({}) is None

    def test_garbage_start_is_none(self):
        assert presence_gate._session_start({"startedAt": "not a time"}) is None
