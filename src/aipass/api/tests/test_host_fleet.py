#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_fleet.py
# Description: Tests for the host API fleet lane — baud --snapshot contract
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Tests for the Host API Fleet Lane

The contract under test is @baud's, delivered 2026-08-14: `baud --snapshot`, one
JSON envelope on stdout, three exit codes with distinct meanings.

NOTHING HERE INVOKES THE REAL BINARY. It is a GUI application that this suite has
no business launching, and a test that shells a 5MB desktop binary is a test that
fails on a machine which has never built it. Every test drives a mocked
subprocess; the real binary is exercised by a live probe, recorded in FPLAN-0411.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens


# A real card, trimmed from @baud's verified run.
SNAPSHOT = {
    "project": "AIPASS",
    "root": "/home/patrick/Projects/AIPass",
    "generated_at": "2026-08-14T20:04:40Z",
    "error": None,
    "live_agent_sessions": ["baud-devpulse"],
    "branches": [
        {
            "name": "devpulse",
            "project": "AIPASS",
            "path": "/home/patrick/Projects/AIPass/src/aipass/devpulse",
            "is_citizen": True,
            "manager": True,
            "dispatched": False,
            "interactive": True,
            "has_history": True,
            "resume_id": None,
            "has_room": True,
            "outside_room": None,
            "subagents": 0,
            "new_mail": 0,
            "opened_mail": 0,
            "active_plans": 22,
            "todo_count": 10,
            "summary": "22 active plans, 10 todos",
            "last_updated": "2026-08-14T09:29:28.721184",
        },
        {
            "name": "api",
            "project": "AIPASS",
            "path": "/home/patrick/Projects/AIPass/src/aipass/api",
            "is_citizen": True,
            "manager": False,
            "dispatched": True,
            "interactive": False,
            "has_history": True,
            "resume_id": None,
            "has_room": False,
            "outside_room": None,
            "subagents": 0,
            "new_mail": 0,
            "opened_mail": 1,
            "active_plans": 2,
            "todo_count": 7,
            "summary": "1 opened, 2 active plans",
            "last_updated": "2026-08-14T13:05:38.710253",
        },
    ],
}


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a fake CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


@pytest.fixture
def ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the gate open explicitly, so these tests do not depend on its default."""
    monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", True)


@pytest.fixture
def seated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pin the repo root and the resolved binary the exec would use."""
    monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(host_fleet, "snapshot_binary", lambda: "baud")
    return tmp_path


class TestTheGate:
    """
    The gate is OPEN as of the 2026-08-14 rebuild.

    It used to be closed because the shipped m12 binary did not know the flag and
    would fall through to tauri and open a GUI window, hanging the request. That
    hazard is GONE: Patrick rebuilt, ran the release binary himself, and I
    re-verified from this branch — exit 0, one JSON envelope, 17 branches, no
    window. The constant stays in the code as an operational kill switch, so the
    refusal path below is still real behaviour worth pinning.
    """

    def test_gate_allows_the_exec(self) -> None:
        """The rebuild landed, so the exec is allowed to run."""
        assert host_fleet.SNAPSHOT_READY is True

    def test_closing_the_gate_still_refuses_rather_than_fakes(
        self,
        seated: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The kill switch survives the flip: shut means 503, never a fake fleet."""
        monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", False)

        with pytest.raises(host_fleet.FleetUnavailable):
            host_fleet.read_snapshot()

    def test_a_closed_gate_never_reaches_subprocess(
        self,
        seated: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The switch is checked before exec — the whole point is not to run it."""
        monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", False)

        with patch.object(host_fleet.subprocess, "run") as run:
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_snapshot()

        run.assert_not_called()


class TestBinaryResolution:
    """
    Finding the binary, which is NOT on PATH.

    Patrick's launcher execs the built release path directly. Resolving to that
    same file is the same argument @baud made when they refused to ship a second
    artifact for C1: one binary, one version, no silent disagreement.
    """

    def test_built_release_path_is_preferred(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The file the desktop launcher runs is the file the phone lane runs."""
        built = tmp_path / host_fleet.DEFAULT_BINARY_RELATIVE
        built.parent.mkdir(parents=True)
        built.touch()
        monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)

        assert host_fleet.snapshot_binary() == str(built)

    def test_built_path_wins_over_path_lookup(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A stale copy on PATH must not quietly outrank the deployed build."""
        built = tmp_path / host_fleet.DEFAULT_BINARY_RELATIVE
        built.parent.mkdir(parents=True)
        built.touch()
        monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
        monkeypatch.setattr(host_fleet.shutil, "which", lambda _name: "/usr/local/bin/baud")

        assert host_fleet.snapshot_binary() == str(built)

    def test_path_is_used_when_there_is_no_build(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """An installed baud is a legitimate deployment; it is second, not ignored."""
        monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
        monkeypatch.setattr(host_fleet.shutil, "which", lambda _name: "/usr/local/bin/baud")

        assert host_fleet.snapshot_binary() == "/usr/local/bin/baud"

    def test_missing_everywhere_names_both_places_looked(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """
        'not found' without a location is a support ticket.

        The error carries the exact path that was checked, so whoever reads it can
        see whether the build is missing or the layout moved.
        """
        monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
        monkeypatch.setattr(host_fleet.shutil, "which", lambda _name: None)

        with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
            host_fleet.snapshot_binary()

        assert str(tmp_path) in str(excinfo.value)
        assert "PATH" in str(excinfo.value)

    def test_resolution_failure_surfaces_through_read_snapshot(
        self,
        ready: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A missing binary is unavailable, not an empty fleet."""
        monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
        monkeypatch.setattr(host_fleet.shutil, "which", lambda _name: None)

        with pytest.raises(host_fleet.FleetUnavailable):
            host_fleet.read_snapshot()


class TestExitZero:
    """Exit 0: a real read. The payload is theirs and passes through unchanged."""

    def test_payload_returned_unchanged(self, ready: None, seated: Path) -> None:
        """D0: I serialise their shape, I do not reshape it."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))):
            result = host_fleet.read_snapshot()

        assert result == SNAPSHOT

    def test_no_field_is_added_or_dropped(self, ready: None, seated: Path) -> None:
        """An adapter here is a second fleet model. There is no adapter."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))):
            result = host_fleet.read_snapshot()

        assert set(result.keys()) == set(SNAPSHOT.keys())
        assert set(result["branches"][0].keys()) == set(SNAPSHOT["branches"][0].keys())

    def test_exec_runs_from_the_repo_root(self, ready: None, seated: Path) -> None:
        """
        The root-resolution trap @baud warned would bite first.

        BAUD walks UP from its CWD looking for a tree containing src/aipass. A
        server started from / or a systemd unit would fail even with a valid
        --project, so the exec is pinned to the root we are seated in.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))) as run:
            host_fleet.read_snapshot()

        assert run.call_args.kwargs["cwd"] == str(seated)

    def test_bare_invocation_has_no_project_flag(self, ready: None, seated: Path) -> None:
        """No project asked for means the anchor project. Nothing else accepted."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))) as run:
            host_fleet.read_snapshot()

        assert run.call_args.args[0] == ["baud", "--snapshot"]

    def test_project_passes_through_case_intact(self, ready: None, seated: Path) -> None:
        """
        Project names are case-sensitive keys in BAUD's census.

        Helpfully lowercasing 'BAUD' to 'baud' would turn a valid request into a
        refusal. The string is the caller's; it travels verbatim.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))) as run:
            host_fleet.read_snapshot(project="BAUD")

        assert run.call_args.args[0] == ["baud", "--snapshot", "--project", "BAUD"]

    def test_malformed_json_is_unavailable_not_empty(self, ready: None, seated: Path) -> None:
        """Unparseable output is reported, never smoothed into an empty fleet."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, "{not json")):
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_snapshot()


class TestExitOne:
    """Exit 1: BAUD ran, the read failed. stdout is still a full envelope."""

    def test_error_sentence_comes_from_the_envelope(self, ready: None, seated: Path) -> None:
        """`error != null` is the only runtime failure branch the parser needs."""
        envelope = {
            "project": None,
            "error": "could not locate the AIPass root: set AIPASS_ROOT",
            "live_agent_sessions": [],
            "branches": [],
        }

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(1, json.dumps(envelope), "mirror")):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.read_snapshot()

        assert "could not locate the AIPass root" in str(excinfo.value)

    def test_stderr_is_never_parsed(self, ready: None, seated: Path) -> None:
        """
        stderr is a mirror for humans tailing a log. Their contract says so, and
        a parser that reads it would break the day they reword a log line.
        """
        envelope = {"error": "the real reason", "branches": [], "live_agent_sessions": []}

        with patch.object(
            host_fleet.subprocess,
            "run",
            return_value=_completed(1, json.dumps(envelope), "a completely different sentence"),
        ):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.read_snapshot()

        assert "the real reason" in str(excinfo.value)
        assert "completely different" not in str(excinfo.value)

    def test_error_envelope_is_not_returned_as_a_fleet(self, ready: None, seated: Path) -> None:
        """An envelope with empty branches is a failure, not a fleet of zero."""
        envelope = {"error": "read failed", "branches": [], "live_agent_sessions": []}

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(1, json.dumps(envelope))):
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_snapshot()


class TestExitTwo:
    """Exit 2: BAUD never ran. stdout is zero bytes — our bug, not the caller's."""

    def test_empty_stdout_is_named_as_an_invocation_fault(self, ready: None, seated: Path) -> None:
        """Deploy-time bug, and the message should say so rather than blame the phone."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(2, "", "baud: unknown argument")):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.read_snapshot()

        assert "invocation" in str(excinfo.value).lower()


class TestExecFailures:
    """The binary may be missing or wedged. Neither may hang a request."""

    def test_missing_binary_is_reported(self, ready: None, seated: Path) -> None:
        """No baud on PATH is a real, nameable state."""
        with patch.object(host_fleet.subprocess, "run", side_effect=FileNotFoundError("no baud")):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.read_snapshot()

        assert "baud" in str(excinfo.value).lower()

    def test_timeout_is_bounded_and_reported(self, ready: None, seated: Path) -> None:
        """
        The window-hang hazard in one test.

        If the wrong build is ever reached, it opens a GUI and never returns. The
        timeout is what stops that from parking a request forever.
        """
        with patch.object(
            host_fleet.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="baud", timeout=host_fleet.SNAPSHOT_TIMEOUT_SECONDS),
        ):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.read_snapshot()

        assert "timed out" in str(excinfo.value).lower()

    def test_a_timeout_is_actually_passed_to_subprocess(self, ready: None, seated: Path) -> None:
        """A timeout constant that never reaches subprocess.run protects nothing."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))) as run:
            host_fleet.read_snapshot()

        assert run.call_args.kwargs["timeout"] == host_fleet.SNAPSHOT_TIMEOUT_SECONDS


class TestRooms:
    """Rooms is a projection of their snapshot — a filter, not a judgment."""

    def test_rooms_lists_only_branches_reporting_a_room(self, ready: None, seated: Path) -> None:
        """has_room is their bool. We filter on it; we do not compute it."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))):
            rooms = host_fleet.read_rooms()

        assert [branch["name"] for branch in rooms["branches_with_rooms"]] == ["devpulse"]

    def test_live_sessions_pass_through_untouched(self, ready: None, seated: Path) -> None:
        """
        Deliberately NOT joined to the branch list.

        Matching 'baud-devpulse' to branch 'devpulse' would mean implementing
        BAUD's session-naming convention over here — a second place that has to
        change when they rename. Both lists are served raw; the client joins.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))):
            rooms = host_fleet.read_rooms()

        assert rooms["live_agent_sessions"] == ["baud-devpulse"]

    def test_rooms_carries_the_snapshot_timestamp(self, ready: None, seated: Path) -> None:
        """Stale room data must be recognisable as stale."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))):
            rooms = host_fleet.read_rooms()

        assert rooms["generated_at"] == "2026-08-14T20:04:40Z"

    def test_rooms_is_gated_with_the_snapshot(self, seated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The projection cannot outrun the source it projects."""
        monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", False)

        with pytest.raises(host_fleet.FleetUnavailable):
            host_fleet.read_rooms()


# ==============================================
# ROUTES
# ==============================================

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def client(tmp_path: Path):
    """A TestClient over the real app with an isolated token store."""
    from fastapi.testclient import TestClient

    with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
            yield TestClient(host_server.create_app(), raise_server_exceptions=False)


@pytest.fixture
def auth(client) -> dict:
    """A valid read-scope bearer header against the isolated store."""
    _, raw = host_tokens.issue_token("fleet-test", scope="read")
    return {"Authorization": f"Bearer {raw}"}


@fastapi_required
class TestFleetRoutes:
    """The routes serve the snapshot, and refuse honestly when they cannot."""

    @pytest.mark.parametrize("path", ["/v1/fleet", "/v1/rooms"])
    def test_route_requires_a_token(self, client, path: str) -> None:
        """The fleet is fleet-wide state; it sits behind the same auth as everything."""
        response = client.get(path)

        assert response.status_code == 401

    @pytest.mark.parametrize("path", ["/v1/fleet", "/v1/rooms"])
    def test_route_serves_the_snapshot(
        self,
        client,
        auth: dict,
        seated: Path,
        path: str,
    ) -> None:
        """End to end through the app: token, route, exec, envelope."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))):
            response = client.get(path, headers=auth)

        assert response.status_code == 200

    def test_fleet_returns_the_envelope_verbatim(self, client, auth: dict, seated: Path) -> None:
        """No adapter anywhere in the request path, not just in the handler."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SNAPSHOT))):
            response = client.get("/v1/fleet", headers=auth)

        assert response.json() == SNAPSHOT

    @pytest.mark.parametrize("path", ["/v1/fleet", "/v1/rooms"])
    def test_route_reports_503_when_the_read_fails(
        self,
        client,
        auth: dict,
        seated: Path,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        """
        A failed read is 503 with a code — not 404, and never an empty fleet.

        This is the behaviour the kill switch existed to guarantee while the seam
        was held, and it has to survive the seam being opened.
        """
        monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", False)

        response = client.get(path, headers=auth)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "fleet_unavailable"
