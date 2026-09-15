# =================== AIPass ====================
# Name: test_host_fleet.py
# Description: Tests for the host API fleet lane — baud --snapshot contract
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-09-14
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
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import lock as host_lock
from aipass.api.apps.handlers.host import machine as host_machine
from aipass.api.apps.handlers.host import read_cache as host_read_cache
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.skills.lib.screen_lock import handler as screen_lock
from aipass.skills.lib.system_status import handler as system_status


# A real card, trimmed from @baud's verified run.
SNAPSHOT = {
    "project": "AIPASS",
    "root": "/srv/aipass",
    "generated_at": "2026-08-14T20:04:40Z",
    "error": None,
    "live_agent_sessions": ["baud-devpulse"],
    "branches": [
        {
            "name": "devpulse",
            "project": "AIPASS",
            "path": "/srv/aipass/src/aipass/devpulse",
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
            "path": "/srv/aipass/src/aipass/api",
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


PATCH_CONFIG_LOGGER = "aipass.api.apps.handlers.host.config.logger"
PATCH_FLEET_LOGGER = "aipass.api.apps.handlers.host.fleet.logger"

posix_permissions = pytest.mark.skipif(sys.platform == "win32", reason="os.access X_OK is always true on Windows")


def _executable(path: Path, mode: int = 0o755) -> Path:
    """A stand-in binary: a regular file with the given mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(mode)
    return path


@pytest.fixture
def places(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """
    Every place the lookup reads, as empty temp stand-ins.

    The config store, the home directory, the checkout and PATH — so no case
    reads this machine's real baud_bin, ~/.aipass, build or PATH.
    """
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    on_path: dict = {}
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(host_fleet, "repo_root", lambda: repo)
    monkeypatch.setattr(host_fleet.shutil, "which", lambda name: on_path.get(name))

    with patch(PATCH_SECRETS_BASE, tmp_path / "secrets"), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_CONFIG_LOGGER), patch(PATCH_FLEET_LOGGER):
            yield SimpleNamespace(home=home, repo=repo, on_path=on_path, elsewhere=tmp_path / "elsewhere")


class TestBinaryResolution:
    """
    FPLAN-0589: which baud binary the host lanes exec, first hit wins.

    (1) the configured baud_bin, refused by name when unusable; (2) the installed
    ~/.aipass/baud/bin/baud-cli; (3) the checkout's baud-cli; (4) the checkout's
    desktop baud, the file Patrick's launcher execs; (5) baud-cli on PATH; (6)
    baud on PATH. The desktop binary links GTK even for --snapshot, which is why
    the headless one outranks it wherever both could be found.
    """

    def test_the_six_step_order(self, places: SimpleNamespace) -> None:
        """
        Each step answers only when every step above it is empty.

        All six are filled, then emptied from the top one at a time, so any swap
        in the order changes which binary answers at some rung.
        """
        configured = _executable(places.elsewhere / "baud-cli")
        installed = _executable(places.home / host_fleet.INSTALLED_BINARY_RELATIVE)
        headless = _executable(places.repo / host_fleet.CHECKOUT_HEADLESS_RELATIVE)
        desktop = _executable(places.repo / host_fleet.DEFAULT_BINARY_RELATIVE)
        places.on_path.update({"baud-cli": "/opt/bin/baud-cli", "baud": "/opt/bin/baud"})
        host_config.set_baud_bin(configured)

        empty_each_step = [
            lambda: host_config.set_baud_bin(None),
            installed.unlink,
            headless.unlink,
            desktop.unlink,
            lambda: places.on_path.pop("baud-cli"),
            lambda: places.on_path.pop("baud"),
        ]
        answered = []
        for empty in empty_each_step:
            location = host_fleet.locate_binary()
            answered.append((location.path, location.source))
            assert host_fleet.snapshot_binary() == location.path
            empty()

        assert answered == [
            (str(configured), host_fleet.SOURCE_CONFIGURED),
            (str(installed), host_fleet.SOURCE_INSTALLED),
            (str(headless), host_fleet.SOURCE_CHECKOUT),
            (str(desktop), host_fleet.SOURCE_CHECKOUT),
            ("/opt/bin/baud-cli", host_fleet.SOURCE_PATH),
            ("/opt/bin/baud", host_fleet.SOURCE_PATH),
        ]
        assert host_fleet.locate_binary().source == host_fleet.SOURCE_MISSING

    def test_a_configured_binary_that_is_gone_is_refused_by_name(self, places: SimpleNamespace) -> None:
        """
        Never fallen past: the installed binary is right there and is still not used.

        A setting somebody chose that silently stops mattering is how a host ends
        up running a binary nobody picked.
        """
        configured = _executable(places.elsewhere / "baud-cli")
        _executable(places.home / host_fleet.INSTALLED_BINARY_RELATIVE)
        host_config.set_baud_bin(configured)
        configured.unlink()

        with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
            host_fleet.snapshot_binary()

        message = str(excinfo.value)
        assert str(configured) in message
        assert "set-config --baud-bin default" in message

    @posix_permissions
    def test_a_configured_binary_that_lost_its_bit_is_refused_by_name(self, places: SimpleNamespace) -> None:
        """Present is not enough: a file that cannot be exec'd refuses here, not as a 500 at the exec."""
        configured = _executable(places.elsewhere / "baud-cli")
        _executable(places.repo / host_fleet.DEFAULT_BINARY_RELATIVE)
        host_config.set_baud_bin(configured)
        configured.chmod(0o644)

        with pytest.raises(host_fleet.FleetUnavailable, match="not executable") as excinfo:
            host_fleet.snapshot_binary()

        assert str(configured) in str(excinfo.value)

    def test_not_found_names_every_place_in_order_and_ends_with_the_install(self, places: SimpleNamespace) -> None:
        """'not found' without a location is a support ticket; without the cure, a second one."""
        with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
            host_fleet.snapshot_binary()

        message = str(excinfo.value)
        # Each followed by its separator: the desktop path is a prefix of the headless one.
        in_order = [
            f"{places.home / host_fleet.INSTALLED_BINARY_RELATIVE};",
            f"{places.repo / host_fleet.CHECKOUT_HEADLESS_RELATIVE};",
            f"{places.repo / host_fleet.DEFAULT_BINARY_RELATIVE};",
            "'baud-cli' on PATH;",
            "'baud' on PATH.",
        ]
        positions = [message.find(place) for place in in_order]

        assert -1 not in positions, message
        assert positions == sorted(positions), message
        assert message.endswith("Install it: aipass baud install.")

    @posix_permissions
    def test_an_automatic_file_without_the_bit_is_passed_and_named(self, places: SimpleNamespace) -> None:
        """A download nobody chmodded is skipped for the next step, and still named when nothing answers."""
        installed = _executable(places.home / host_fleet.INSTALLED_BINARY_RELATIVE, mode=0o644)
        desktop = _executable(places.repo / host_fleet.DEFAULT_BINARY_RELATIVE)

        assert host_fleet.snapshot_binary() == str(desktop)

        desktop.unlink()
        with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
            host_fleet.snapshot_binary()

        assert f"{installed} (present, not an executable file)" in str(excinfo.value)

    def test_resolution_is_per_request_so_an_install_needs_no_restart(self, places: SimpleNamespace) -> None:
        """The install can land while the server runs; the very next request uses it."""
        with pytest.raises(host_fleet.FleetUnavailable):
            host_fleet.snapshot_binary()

        installed = _executable(places.home / host_fleet.INSTALLED_BINARY_RELATIVE)

        assert host_fleet.snapshot_binary() == str(installed)

    def test_resolution_failure_surfaces_through_read_snapshot(self, ready: None, places: SimpleNamespace) -> None:
        """A missing binary is unavailable, not an empty fleet."""
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


# An empty room: BAUD made a session for this branch, and nobody is in it.
EMPTY_ROOM = {
    "project": "AIPASS",
    "generated_at": "2026-08-14T23:37:37Z",
    "error": None,
    # 'ghost' has a room; it is NOT in here, so it is not alive.
    "live_agent_sessions": ["baud-devpulse"],
    "branches": [
        {"name": "ghost", "has_room": True, "outside_room": None, "interactive": False},
        {"name": "devpulse", "has_room": True, "outside_room": None, "interactive": True},
        {"name": "squatter", "has_room": False, "outside_room": "some-other-session", "interactive": True},
    ],
}


class TestThreeFieldsThreeQuestions:
    """
    @baud's sharp edge, pinned at their request.

    has_room, outside_room and live_agent_sessions answer three DIFFERENT
    questions, and conflating the first with the third is the exact bug their m12
    badge work existed to kill — a green circle over a room with nobody in it.

        has_room            a session BAUD named for this branch EXISTS. Name
                            match only. An empty room is has_room true.
        outside_room        an agent is seated here in a session BAUD did not
                            create. Null when has_room is true.
        live_agent_sessions an INTERACTIVE claude is actually alive, decided by
                            the process table. A dispatched headless claude looks
                            like the same 'claude' in a pane, so panes alone lie.

    This server cannot enforce what a client renders. What it CAN guarantee is
    that it never manufactures an aliveness signal of its own, so the only thing
    a client can read aliveness from is the field that means it.
    """

    def test_an_empty_room_is_still_a_room(self, ready: None, seated: Path) -> None:
        """has_room means the room exists, not that anyone is home."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(EMPTY_ROOM))):
            rooms = host_fleet.read_rooms()

        listed = [branch["name"] for branch in rooms["branches_with_rooms"]]
        assert "ghost" in listed

    def test_the_empty_room_is_not_reported_as_alive(self, ready: None, seated: Path) -> None:
        """
        The lie this test exists to prevent.

        'ghost' has a room and is absent from live_agent_sessions. Nothing in the
        payload may suggest otherwise.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(EMPTY_ROOM))):
            rooms = host_fleet.read_rooms()

        assert "ghost" not in str(rooms["live_agent_sessions"])

    def test_no_aliveness_field_is_invented_anywhere(self, ready: None, seated: Path) -> None:
        """
        No synthesised 'alive'/'online'/'active' key, on the payload or the cards.

        If one ever appears, a client will render it, and it will be this
        server's guess rather than BAUD's process-table read.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(EMPTY_ROOM))):
            rooms = host_fleet.read_rooms()

        invented = {"alive", "online", "active", "is_alive", "running"}
        assert not invented & set(rooms.keys())
        for card in rooms["branches_with_rooms"]:
            assert not invented & set(card.keys())

    def test_outside_room_is_not_a_room_baud_made(self, ready: None, seated: Path) -> None:
        """
        'squatter' is seated somewhere BAUD did not create, so it is not a room.

        Its outside_room still travels on the full card via /v1/fleet — that is
        where a client asks "which session is this agent in". /v1/rooms answers
        the narrower question and says so.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(EMPTY_ROOM))):
            rooms = host_fleet.read_rooms()

        assert "squatter" not in [branch["name"] for branch in rooms["branches_with_rooms"]]

    def test_outside_room_survives_untouched_on_the_fleet_card(self, ready: None, seated: Path) -> None:
        """Nothing is dropped from the envelope, so nothing is lost system-wide."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(EMPTY_ROOM))):
            snapshot = host_fleet.read_snapshot()

        squatter = [card for card in snapshot["branches"] if card["name"] == "squatter"][0]
        assert squatter["outside_room"] == "some-other-session"


# ==============================================
# END-ROOM — the second headless verb
# ==============================================

ENDED = {
    "project": "AIPASS",
    "branch": "cli",
    "room": "baud-cli",
    "ended": True,
    "detail": "ended 'baud-cli'",
    "generated_at": "2026-08-15T03:50:40Z",
    "error": None,
}

NOTHING_TO_END = {**ENDED, "room": None, "ended": False, "detail": "nothing to end"}

REFUSED = {**ENDED, "room": None, "ended": False, "detail": None, "error": "no branch named nosuch in project AIPASS"}


class TestEndRoomInvocation:
    """
    The command line handed to their binary. It is short, and every part of it
    is load-bearing.
    """

    def test_the_flag_and_the_branch_are_what_they_published(self, seated: Path) -> None:
        """`baud --end-room <branch>`, exactly."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ENDED))) as run:
            host_fleet.end_room("cli", "AIPASS")

        assert run.call_args.args[0][:3] == ["baud", "--end-room", "cli"]

    def test_the_project_travels_verbatim(self, seated: Path) -> None:
        """
        A key in BAUD's census, so its case is theirs and not ours to fix.

        The read lane already passes it through raw; a kill that normalised it
        would refuse for a reason that looks like a missing project.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ENDED))) as run:
            host_fleet.end_room("cli", "AIPASS")

        assert run.call_args.args[0][3:] == ["--project", "AIPASS"]

    def test_the_two_headless_verbs_are_never_sent_together(self, seated: Path) -> None:
        """
        Their exit-2 rule, honoured by construction: this never builds a line
        carrying both. A caller who wrote a read AND a kill in one invocation
        does not know what they asked for, and guessing is how a read becomes a
        kill.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ENDED))) as run:
            host_fleet.end_room("cli", "AIPASS")

        assert "--snapshot" not in run.call_args.args[0]

    def test_it_runs_from_our_root_not_wherever_the_server_started(self, seated: Path) -> None:
        """BAUD walks UP from cwd to find a root — a server started from / would fail."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ENDED))) as run:
            host_fleet.end_room("cli", "AIPASS")

        assert run.call_args.kwargs["cwd"] == str(seated)

    def test_the_timeout_actually_reaches_subprocess(self, seated: Path) -> None:
        """A timeout constant that never reaches subprocess.run protects nothing."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ENDED))) as run:
            host_fleet.end_room("cli", "AIPASS")

        assert run.call_args.kwargs["timeout"] == host_fleet.END_ROOM_TIMEOUT_SECONDS


class TestEndRoomContract:
    """
    @baud's envelope, passed through rather than interpreted. `detail` and
    `error` are mutually exclusive by construction, and `ended` is a fact rather
    than a success flag.
    """

    def test_a_real_kill_comes_back_whole(self, seated: Path) -> None:
        """Their envelope, unchanged — this module adapts nothing."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ENDED))):
            envelope = host_fleet.end_room("cli", "AIPASS")

        assert envelope == ENDED

    def test_nothing_to_end_is_exit_zero_and_stays_a_success(self, seated: Path) -> None:
        """
        A room already gone IS the goal state, so it is not an error here.

        Turning this into a raise would tell an operator their kill failed when
        the thing they wanted is already true.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(NOTHING_TO_END))):
            envelope = host_fleet.end_room("cli", "AIPASS")

        assert envelope["ended"] is False
        assert envelope["error"] is None

    def test_a_refusal_arrives_as_a_whole_envelope_not_an_exception(self, seated: Path) -> None:
        """
        Exit 1 still carries a full envelope, so their sentence survives.

        Raising here would replace their diagnosis with ours, which is the one
        thing this lane is not allowed to do.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(1, json.dumps(REFUSED))):
            envelope = host_fleet.end_room("nosuch", "AIPASS")

        assert envelope["error"] == "no branch named nosuch in project AIPASS"

    def test_empty_stdout_is_our_invocation_fault(self, seated: Path) -> None:
        """Exit 2: BAUD never ran, so nothing was killed. Ours to own."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(2, "", "one headless verb at a time")):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.end_room("cli", "AIPASS")

        assert "invocation" in str(excinfo.value).lower()

    def test_unparseable_stdout_never_reads_as_a_kill(self, seated: Path) -> None:
        """Garbage on stdout is unavailable, never a quietly successful kill."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, "not json")):
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.end_room("cli", "AIPASS")

    def test_a_wedged_binary_cannot_park_the_request(self, seated: Path) -> None:
        """
        The window-hang hazard, on the verb where it would hurt most.

        If a build that does not know the flag is ever reached, it falls through
        to tauri and opens a GUI. The timeout is what stops that from holding a
        phone request open forever.
        """
        with patch.object(
            host_fleet.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="baud", timeout=host_fleet.END_ROOM_TIMEOUT_SECONDS),
        ):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.end_room("cli", "AIPASS")

        assert "timed out" in str(excinfo.value).lower()

    def test_a_missing_binary_is_named(self, seated: Path) -> None:
        """'Unavailable' with no subject is how a gap becomes folklore."""
        with patch.object(host_fleet.subprocess, "run", side_effect=FileNotFoundError("no baud")):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.end_room("cli", "AIPASS")

        assert "baud" in str(excinfo.value).lower()


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


# ============================================================================
# The roster lane — `baud --roster`, DPLAN-0300 (spec relayed 2026-08-16)
# ============================================================================

# @baud's roster envelope: the same BranchStatus rows as a snapshot, but
# spanning EVERY project, and with no project/root/live_agent_sessions keys
# because the answer is not seated anywhere.
ROSTER = {
    "branches": [
        {
            "name": "api",
            "project": "AIPASS",
            "path": "/srv/aipass/src/aipass/api",
            "is_citizen": True,
            "manager": False,
            "dispatched": True,
            "interactive": False,
            "has_history": True,
            "resume_id": None,
            "has_room": True,
            "outside_room": None,
            "subagents": 0,
            "new_mail": 1,
            "opened_mail": 0,
            "active_plans": 3,
            "todo_count": 8,
            "summary": "1 new emails, 3 active plans, 8 todos",
            "last_updated": "2026-08-16T09:55:09.000000",
        },
        {
            "name": "baud",
            "project": "BAUD",
            "path": "/srv/aipass/projects/baud/src/baud/baud",
            "is_citizen": True,
            "manager": False,
            "dispatched": True,
            "interactive": False,
            "has_history": True,
            "resume_id": None,
            "has_room": True,
            "outside_room": None,
            "subagents": 1,
            "new_mail": 0,
            "opened_mail": 0,
            "active_plans": 4,
            "todo_count": 2,
            "summary": "4 active plans, 2 todos",
            "last_updated": "2026-08-16T09:41:02.000000",
        },
    ],
    "generated_at": "2026-08-16T16:57:31Z",
    "error": None,
}

EMPTY_ROSTER = {"branches": [], "generated_at": "2026-08-16T16:57:31Z", "error": None}


class TestTheRosterIsOneSweepAcrossEveryProject:
    """
    The roster answers a question /v1/fleet structurally cannot.

    A snapshot is SEATED — one project per read. The phone's live and dispatched
    wheels span all of them, so aliasing the roster onto the fleet gave a wheel
    that looks full and is wrong. This lane execs @baud's own sweep, one process
    and one ranking behind both faces.
    """

    def test_the_invocation_carries_exactly_one_argument(self, ready: None, seated: Path) -> None:
        """
        `baud --roster`, nothing else.

        The binary REFUSES a project on this verb (exit 2, empty stdout, stderr
        naming the argument) — verified against the release build. Anything this
        server appends is a usage error it inflicted on itself.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))) as run:
            host_fleet.read_roster()

        assert run.call_args.args[0] == ["baud", "--roster"]

    def test_the_exec_runs_from_the_repo_root(self, ready: None, seated: Path) -> None:
        """BAUD walks UP from its CWD to find the tree. Same trap as the snapshot."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))) as run:
            host_fleet.read_roster()

        assert run.call_args.kwargs["cwd"] == str(seated)

    def test_the_payload_is_returned_unchanged(self, ready: None, seated: Path) -> None:
        """D0: their shape, serialised. Rows stay byte-identical to a fleet row."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))):
            result = host_fleet.read_roster()

        assert result == ROSTER
        assert set(result["branches"][0].keys()) == set(SNAPSHOT["branches"][0].keys())

    def test_an_empty_roster_is_an_answer_not_a_failure(self, ready: None, seated: Path) -> None:
        """
        Nobody working anywhere is TRUE, and the wheels must be able to say it.

        Turning it into an error would make the quietest state of the system
        look like a broken lane.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(EMPTY_ROSTER))):
            result = host_fleet.read_roster()

        assert result == EMPTY_ROSTER

    def test_the_gate_closes_this_lane_too(self, monkeypatch: pytest.MonkeyPatch, seated: Path) -> None:
        """
        The kill switch governs every exec of that binary, not just the snapshot.

        The subprocess is mocked to a VALID envelope on purpose: without it,
        removing the gate makes the lane exec a binary that is not on this
        machine's PATH, which raises FleetUnavailable anyway — and the test
        passes while guarding nothing. Mutation caught exactly that.
        """
        monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", False)

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))) as run:
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_roster()

        run.assert_not_called()

    def test_exit_one_carries_their_sentence(self, ready: None, seated: Path) -> None:
        """
        Their words reach the phone, not my paraphrase of them.

        Exit 1 means BAUD ran and could not answer; the envelope holds the
        reason and branches is empty.
        """
        failed = {"branches": [], "generated_at": "2026-08-16T16:57:31Z", "error": "registry is unreadable"}
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(1, json.dumps(failed))):
            with pytest.raises(host_fleet.FleetUnavailable) as excinfo:
                host_fleet.read_roster()

        assert "registry is unreadable" in str(excinfo.value)

    def test_an_empty_stdout_is_our_bug_not_theirs(self, ready: None, seated: Path) -> None:
        """
        Exit 2 with nothing on stdout is a usage error — this server called it wrong.

        A distinct exception, because the honest status code differs: 503 says
        'try later', and nothing about a malformed argv gets better with time.
        """
        rejected = _completed(2, "", "baud: unknown argument '--project'")
        with patch.object(host_fleet.subprocess, "run", return_value=rejected):
            with pytest.raises(host_fleet.FleetMisuse) as excinfo:
                host_fleet.read_roster()

        assert "--project" in str(excinfo.value)

    def test_malformed_json_is_unavailable_not_empty(self, ready: None, seated: Path) -> None:
        """Unparseable output is reported. An empty roster would be a lie."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, "{not json")):
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_roster()

    def test_a_non_object_envelope_is_refused(self, ready: None, seated: Path) -> None:
        """A JSON list parses fine and is still not an envelope."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, "[]")):
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_roster()

    def test_a_missing_binary_is_unavailable(self, ready: None, seated: Path) -> None:
        """Never an empty roster: absence of the binary is not absence of agents."""
        with patch.object(host_fleet.subprocess, "run", side_effect=FileNotFoundError("no baud")):
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_roster()

    def test_a_timeout_is_unavailable(self, ready: None, seated: Path) -> None:
        """A sweep that never returns must not hold the request open forever."""
        timeout = subprocess.TimeoutExpired(cmd="baud", timeout=30)
        with patch.object(host_fleet.subprocess, "run", side_effect=timeout):
            with pytest.raises(host_fleet.FleetUnavailable):
                host_fleet.read_roster()


@fastapi_required
class TestTheRosterRoute:
    """GET /v1/roster — read scope, no parameters, three honest status codes."""

    def test_route_requires_a_token(self, client) -> None:
        """The roster names every working agent in every project. Not public."""
        assert client.get("/v1/roster").status_code == 401

    def test_read_scope_is_enough(self, client, auth: dict, seated: Path) -> None:
        """It is a read, exactly like /v1/fleet."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))):
            response = client.get("/v1/roster", headers=auth)

        assert response.status_code == 200

    def test_the_envelope_arrives_verbatim(self, client, auth: dict, seated: Path) -> None:
        """No adapter in the request path either — body.branches is their rows."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))):
            response = client.get("/v1/roster", headers=auth)

        assert response.json() == ROSTER

    def test_an_empty_roster_is_200(self, client, auth: dict, seated: Path) -> None:
        """The quiet answer is still an answer. 200, branches [], no error."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(EMPTY_ROSTER))):
            response = client.get("/v1/roster", headers=auth)

        assert response.status_code == 200
        assert response.json()["branches"] == []
        assert response.json()["error"] is None

    def test_a_project_filter_is_refused_never_ignored(self, client, auth: dict, seated: Path) -> None:
        """
        THE point of the refusal: a dropped scope reads as a filter that worked.

        A phone asking for one project's roster and silently receiving every
        project's would show a wheel it believes is filtered. 400, naming it.
        """
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))) as run:
            response = client.get("/v1/roster?project=AIPASS", headers=auth)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "roster_refused"
        assert "project" in response.json()["error"]["message"]
        assert run.call_count == 0, "the binary was executed for a request that should have been refused"

    def test_any_parameter_is_refused_not_only_project(self, client, auth: dict, seated: Path) -> None:
        """
        The route takes NO parameters, so nothing is quietly dropped.

        Naming only `project` would leave the next filter someone invents to be
        ignored in silence — the same failure under a different key.
        """
        response = client.get("/v1/roster?branch=api", headers=auth)

        assert response.status_code == 400
        assert "branch" in response.json()["error"]["message"]

    def test_the_gate_is_503_with_a_reason(
        self,
        client,
        auth: dict,
        seated: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        A closed gate is unavailable, never a synthesized empty roster.

        Mocked to a valid envelope for the same reason as the handler test: a
        gate that stopped working must fail this, not fall through to a missing
        binary and refuse for an unrelated reason.
        """
        monkeypatch.setattr(host_fleet, "SNAPSHOT_READY", False)

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(ROSTER))) as run:
            response = client.get("/v1/roster", headers=auth)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "fleet_unavailable"
        run.assert_not_called()

    def test_their_failure_sentence_reaches_the_client(self, client, auth: dict, seated: Path) -> None:
        """Exit 1: 503 carrying BAUD's own words."""
        failed = {"branches": [], "generated_at": "2026-08-16T16:57:31Z", "error": "no project registry found"}
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(1, json.dumps(failed))):
            response = client.get("/v1/roster", headers=auth)

        assert response.status_code == 503
        assert "no project registry found" in response.json()["error"]["message"]

    def test_a_usage_error_is_500_because_it_is_ours(self, client, auth: dict, seated: Path) -> None:
        """
        Exit 2 is this server's bug, and 503 would blame the wrong side.

        503 tells a client to retry something that will fail identically every
        time; 500 says the fault is here.
        """
        rejected = _completed(2, "", "baud: unknown argument '--project'")
        with patch.object(host_fleet.subprocess, "run", return_value=rejected):
            response = client.get("/v1/roster", headers=auth)

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "roster_misuse"


# ============================================================================
# The machine lane — GET /v1/machine, FPLAN-0561 row 2 (DPLAN-0341)
# ============================================================================

PATCH_MACHINE_LOGGER = "aipass.api.apps.handlers.host.machine.logger"
PATCH_MACHINE_JSON = "aipass.api.apps.handlers.host.machine.json_handler"
PATCH_CACHE_JSON = "aipass.api.apps.handlers.host.read_cache.json_handler"

# The door itself, patched where it lives. machine.py imports it inside the
# call, so the stand-in is what every read in these cases reaches.
PATCH_VITALS_DOOR = "aipass.skills.lib.system_status.handler.machine_vitals"


def _present(**values: Any) -> dict:
    """A section that answered, in the skill's published shape."""
    return {"available": True, "reason": None, "sentence": None, "detail": None, **values}


def _absent(reason: str, **values: Any) -> dict:
    """A section that did not, carrying the skill's OWN sentence for its code."""
    return {"available": False, "reason": reason, "sentence": system_status.REASONS[reason], "detail": None, **values}


def _macos_vitals(sampled_at: str = "2026-09-13T07:20:00.000+00:00") -> dict:
    """
    What machine_vitals() answers on a Mac running macOS, manufactured here.

    psutil defines neither sensors_temperatures nor sensors_fans on macOS, so the
    skill answers `platform` for both and a number for everything else. The
    suite never needs a sensor chip: this box's applesmc plays no part.
    """
    return {
        "ok": True,
        "schema": 1,
        "sampled_at": sampled_at,
        "cpu": _present(percent=11.4, window_s=1.018),
        "load": _present(one=0.52, five=0.61, fifteen=0.7),
        "memory": _present(total_bytes=8000000000, used_bytes=5200000000, available_bytes=2800000000, percent=65.0),
        "swap": _present(total_bytes=2000000000, used_bytes=0, free_bytes=2000000000, percent=0.0),
        "temp": _absent("platform", chip=None, label=None, celsius=None, high=None, critical=None, seen=None),
        "fan": _absent("platform", label=None, current=None, range=None, percent_of_range=None, fans=None, seen=None),
        "network": _present(sent_bytes_per_s=1200.0, recv_bytes_per_s=5400.0, window_s=1.018),
        "processes": _present(count=245),
    }


@pytest.fixture
def machine_door():
    """A stand-in for @skills' door, with a cold cache on both sides of the case."""
    with patch(PATCH_MACHINE_LOGGER), patch(PATCH_MACHINE_JSON), patch(PATCH_CACHE_JSON):
        host_machine._vitals.clear()
        with patch(PATCH_VITALS_DOOR, autospec=True) as door:
            yield door
        host_machine._vitals.clear()


@fastapi_required
class TestTheMachineRoute:
    """A proxy with one status line: absence is a 200, 503 is the owner unable to answer."""

    def test_the_route_requires_a_token(self, client, machine_door) -> None:
        """Vitals are machine state; they sit behind the same auth as everything."""
        response = client.get("/v1/machine")

        assert response.status_code == 401
        machine_door.assert_not_called()

    def test_a_mac_with_no_sensors_is_a_200_that_says_so(self, client, auth: dict, machine_door) -> None:
        """
        The manufactured macOS host: temp and fan answer `platform`, the rest are numbers.

        Absence is the answer, not an error, and it arrives with the skill's own
        sentence and a None where a zero would have been a lie. The whole body is
        compared, so any adapter anywhere in the request path goes red.
        """
        machine_door.return_value = _macos_vitals()
        assert all(name in machine_door.return_value for name in system_status.SECTIONS), "stand-in drifted"

        response = client.get("/v1/machine", headers=auth)

        assert response.status_code == 200
        body = response.json()
        assert body == _macos_vitals()
        assert body["fan"]["available"] is False
        assert body["fan"]["reason"] == "platform"
        assert body["fan"]["sentence"] == system_status.REASONS["platform"]
        assert body["fan"]["current"] is None
        assert body["temp"]["celsius"] is None
        assert body["cpu"]["percent"] == 11.4

    @pytest.mark.parametrize(
        ("reason", "detail"),
        [
            ("psutil_missing", system_status.PSUTIL_RECIPE),
            ("switched_off", "Skill 'system_status' is switched OFF and takes no readings."),
            ("a_code_from_the_future", "a refusal this server has never seen"),
        ],
    )
    def test_a_refusal_is_a_503_with_its_code_and_detail_intact(
        self, client, auth: dict, machine_door, reason: str, detail: str
    ) -> None:
        """
        The skill said no: 503, its code in `reason`, its detail as the message.

        switched_off is 503 by the kill-switch rule (a closed switch names itself,
        never a 200 dressed as a reading), and a code nobody here has seen is 503
        with the code intact rather than guessed at.
        """
        machine_door.return_value = {"ok": False, "reason": reason, "detail": detail}

        response = client.get("/v1/machine", headers=auth)

        assert response.status_code == 503
        assert response.json()["error"] == {"code": "machine_refused", "message": detail, "reason": reason}

    def test_a_door_that_raises_is_a_503_naming_it_not_a_500(self, client, auth: dict, machine_door) -> None:
        """The skill never raises for a reading, so a raise is a defect in the door — named."""
        machine_door.side_effect = RuntimeError("boom inside the door")

        response = client.get("/v1/machine", headers=auth)

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "machine_door_failed"
        assert "RuntimeError: boom inside the door" in error["message"]

    @pytest.mark.parametrize("answer", [None, [], {"schema": 1}, {"ok": "yes"}])
    def test_an_answer_outside_the_published_shape_is_a_503(
        self, client, auth: dict, machine_door, answer: Any
    ) -> None:
        """No boolean `ok` means no way to tell an answer from a refusal, so nothing is served."""
        machine_door.return_value = answer

        response = client.get("/v1/machine", headers=auth)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "machine_door_failed"

    def test_a_parameter_is_refused_not_dropped(self, client, auth: dict, machine_door) -> None:
        """A `section=fan` the route ignored would read as a filter that worked."""
        response = client.get("/v1/machine?section=fan", headers=auth)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "machine_parameters_refused"
        assert "section" in response.json()["error"]["message"]
        machine_door.assert_not_called()


class TestTheMachineCache:
    """At most one read per second, and never a cached refusal."""

    def test_two_reads_inside_a_second_are_one_read(self, machine_door) -> None:
        """The second read is the first one's answer: one call, one sampled_at — absent sections included."""
        machine_door.return_value = _macos_vitals()

        first = host_machine.read_machine()
        second = host_machine.read_machine()

        assert machine_door.call_count == 1
        assert second["sampled_at"] == first["sampled_at"]
        assert second["fan"]["reason"] == "platform", "a success with absent sections is still a success"

    def test_the_window_is_one_second(self, machine_door, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inside 1.0 s the stored answer; past it a fresh read. On a clock this case owns."""
        clock = {"now": 100.0}
        monkeypatch.setattr(host_read_cache, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
        machine_door.side_effect = [_macos_vitals("first"), _macos_vitals("second")]

        assert host_machine.read_machine()["sampled_at"] == "first"
        clock["now"] = 100.9
        assert host_machine.read_machine()["sampled_at"] == "first"
        clock["now"] = 101.1
        assert host_machine.read_machine()["sampled_at"] == "second"
        assert machine_door.call_count == 2

    def test_a_refusal_is_never_cached(self, machine_door) -> None:
        """A skill switched back on answers on the very next request, not after the window."""
        machine_door.side_effect = [
            {"ok": False, "reason": "switched_off", "detail": "off"},
            _macos_vitals(),
        ]

        with pytest.raises(host_machine.MachineRefused) as refused:
            host_machine.read_machine()
        assert refused.value.reason == "switched_off"

        assert host_machine.read_machine()["ok"] is True
        assert machine_door.call_count == 2

    def test_a_failed_door_is_never_cached(self, machine_door) -> None:
        """A door that raised once is asked again, not refused for the rest of the second."""
        machine_door.side_effect = [RuntimeError("once"), _macos_vitals()]

        with pytest.raises(host_machine.MachineDoorFailed):
            host_machine.read_machine()

        assert host_machine.read_machine()["ok"] is True
        assert machine_door.call_count == 2

    def test_a_refusal_with_no_detail_still_says_something(self, machine_door) -> None:
        """An empty detail is replaced by a sentence that names the owner; a real one never is."""
        machine_door.return_value = {"ok": False, "reason": "switched_off", "detail": ""}

        with pytest.raises(host_machine.MachineRefused) as refused:
            host_machine.read_machine()

        assert refused.value.detail == host_machine.NO_DETAIL

    def test_a_server_that_never_serves_the_route_imports_nothing_new(self) -> None:
        """
        The door is imported inside the call, so importing this lane loads no skill.

        Asked of a fresh interpreter, because this one already imported the skill
        at the top of this file.
        """
        probe = (
            "import sys\n"
            "import aipass.api.apps.handlers.host.machine\n"
            "print('aipass.skills.lib.system_status.handler' in sys.modules)\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False)

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "False"


# ============================================================================
# The lock lane — GET /v1/lock, FPLAN-0585 row 2
# ============================================================================

PATCH_LOCK_LOGGER = "aipass.api.apps.handlers.host.lock.logger"
PATCH_LOCK_JSON = "aipass.api.apps.handlers.host.lock.json_handler"

# The door itself, patched where it lives. lock.py imports it inside the call,
# so the stand-in is what every read in these cases reaches — never a loginctl.
PATCH_LOCK_DOOR = "aipass.skills.lib.screen_lock.handler.lock_state"


def _lock_answer(locked: bool, method: str = screen_lock.METHOD_LOGINCTL, session: Any = "3") -> dict:
    """An answer in the skill's published shape. The unlocked default is this laptop's, read live 2026-09-13."""
    source = f"logind session {session}" if method == screen_lock.METHOD_LOGINCTL else "GNOME ScreenSaver"
    return {
        "ok": True,
        "locked": locked,
        "method": method,
        "session": session,
        "reason": None,
        "detail": f"The screen is {'locked' if locked else 'unlocked'}, per {source}.",
    }


def _cannot_tell(reason: str = screen_lock.REASON_NO_SESSION) -> dict:
    """The skill could not tell: ok False, locked None, its code and a sentence standing in for its own."""
    return {
        "ok": False,
        "locked": None,
        "method": None,
        "session": None,
        "reason": reason,
        "detail": f"Cannot tell whether the screen is locked ({reason}).",
    }


@pytest.fixture
def lock_door():
    """A stand-in for @skills' door, with a cold cache on both sides of the case."""
    with patch(PATCH_LOCK_LOGGER), patch(PATCH_LOCK_JSON), patch(PATCH_CACHE_JSON):
        host_lock._state.clear()
        with patch(PATCH_LOCK_DOOR, autospec=True) as door:
            yield door
        host_lock._state.clear()


@fastapi_required
class TestTheLockRoute:
    """Every answer in the door's shape is a 200, cannot-tell included; 503 is the door itself failing."""

    def test_the_route_requires_a_token(self, client, lock_door) -> None:
        """Whether a laptop is locked says whether anyone is at it. Not public."""
        response = client.get("/v1/lock")

        assert response.status_code == 401
        lock_door.assert_not_called()

    def test_read_scope_is_enough(self, client, auth: dict, lock_door) -> None:
        """A lock's position is observation; only the POST that locks sits under operate."""
        lock_door.return_value = _lock_answer(locked=False)

        assert client.get("/v1/lock", headers=auth).status_code == 200

    @pytest.mark.parametrize(
        "answer",
        [_lock_answer(locked=False), _lock_answer(locked=True, method=screen_lock.METHOD_DBUS, session=None)],
        ids=["unlocked_per_logind", "locked_per_gnome_screensaver"],
    )
    def test_both_answers_arrive_verbatim(self, client, auth: dict, lock_door, answer: dict) -> None:
        """The whole body is compared, so an adapter anywhere in the request path goes red."""
        lock_door.return_value = answer

        response = client.get("/v1/lock", headers=auth)

        assert response.status_code == 200
        assert response.json() == answer
        assert "cache-control" not in response.headers, "no cache header, matching /v1/machine"

    @pytest.mark.parametrize(
        "reason",
        [screen_lock.REASON_NO_SESSION, screen_lock.REASON_NO_READER, screen_lock.REASON_READ_FAILED],
    )
    def test_cannot_tell_is_a_200_carrying_the_skills_answer(self, client, auth: dict, lock_door, reason: str) -> None:
        """
        ok False is a reading that says "cannot tell", not a failed owner.

        It arrives whole — locked None, the code, the sentence — so the phone
        draws unknown, and nothing in the path turns it into a 503 or an unlocked.
        """
        lock_door.return_value = _cannot_tell(reason)

        response = client.get("/v1/lock", headers=auth)

        assert response.status_code == 200
        assert response.json() == _cannot_tell(reason)

    def test_a_door_that_raises_is_a_503_naming_it_not_a_500(self, client, auth: dict, lock_door) -> None:
        """The skill never raises for a reading, so a raise is a defect in the door — named."""
        lock_door.side_effect = RuntimeError("boom inside the door")

        response = client.get("/v1/lock", headers=auth)

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "lock_door_failed"
        assert "RuntimeError: boom inside the door" in error["message"]

    @pytest.mark.parametrize(
        "answer",
        [
            None,
            [],
            {"locked": False},
            {"ok": "yes", "locked": False},
            {"ok": True},
            {"ok": True, "locked": "no"},
            {"ok": True, "locked": 0},
            {"ok": True, "locked": None},
            {"ok": False, "locked": False},
        ],
        ids=[
            "none",
            "list",
            "no_ok",
            "string_ok",
            "no_locked",
            "string_locked",
            "int_locked",
            "an_answer_that_answers_nothing",
            "cannot_tell_that_reads_unlocked",
        ],
    )
    def test_an_answer_outside_the_published_shape_is_a_503(self, client, auth: dict, lock_door, answer: Any) -> None:
        """
        A boolean ok, a locked key, and the two agreeing — or nothing is served.

        The last case is the one the chip exists to avoid: a cannot-tell carrying
        locked False is exactly what a client could draw as unlocked.
        """
        lock_door.return_value = answer

        response = client.get("/v1/lock", headers=auth)

        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "lock_door_failed"
        assert "published shape" in error["message"]

    def test_a_parameter_is_refused_not_dropped(self, client, auth: dict, lock_door) -> None:
        """A cache-buster the route ignored would read as a parameter that did something."""
        response = client.get("/v1/lock?nocache=1757808000", headers=auth)

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "lock_parameters_refused"
        assert "nocache" in error["message"]
        lock_door.assert_not_called()


class TestTheLockCache:
    """At most one read per second, cannot-tell included, and never a cached door failure."""

    def test_two_reads_inside_a_second_are_one_read(self, lock_door) -> None:
        """The second read is the first one's answer."""
        lock_door.return_value = _lock_answer(locked=False)

        first = host_lock.read_lock()
        second = host_lock.read_lock()

        assert lock_door.call_count == 1
        assert first == second == _lock_answer(locked=False)

    def test_the_window_is_one_second(self, lock_door, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inside 1.0 s the stored answer; past it a fresh read. On a clock this case owns."""
        clock = {"now": 100.0}
        monkeypatch.setattr(host_read_cache, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
        lock_door.side_effect = [_lock_answer(locked=False), _lock_answer(locked=True)]

        assert host_lock.read_lock()["locked"] is False
        clock["now"] = 100.9
        assert host_lock.read_lock()["locked"] is False
        clock["now"] = 101.1
        assert host_lock.read_lock()["locked"] is True
        assert lock_door.call_count == 2

    def test_cannot_tell_is_served_for_its_window_like_any_reading(self, lock_door) -> None:
        """ok False is an answer, not a refusal: stored for the window, not re-asked per request."""
        lock_door.return_value = _cannot_tell()

        assert host_lock.read_lock() == _cannot_tell()
        assert host_lock.read_lock() == _cannot_tell()
        assert lock_door.call_count == 1

    def test_a_door_that_raised_is_never_cached(self, lock_door) -> None:
        """A door that raised once is asked again, not refused for the rest of the second."""
        lock_door.side_effect = [RuntimeError("once"), _lock_answer(locked=True)]

        with pytest.raises(host_lock.LockDoorFailed):
            host_lock.read_lock()

        assert host_lock.read_lock()["locked"] is True
        assert lock_door.call_count == 2

    def test_a_malformed_answer_is_never_cached(self, lock_door) -> None:
        """A shape fault is raised out of the producer, so the next request asks again."""
        lock_door.side_effect = [{"ok": True, "locked": None}, _lock_answer(locked=True)]

        with pytest.raises(host_lock.LockDoorFailed, match="published shape"):
            host_lock.read_lock()

        assert host_lock.read_lock()["locked"] is True
        assert lock_door.call_count == 2

    def test_a_hung_door_is_one_read_however_many_ask(self, lock_door) -> None:
        """
        The known limit's bound: the skill has no timeout, so a hung logind holds its flight.

        A second caller arriving mid-flight waits on that flight and shares its
        answer; it never starts a read of its own. Every wait is bounded, so a
        regression fails here rather than hanging the suite.
        """
        entered = threading.Event()
        release = threading.Event()

        def hung_door() -> dict:
            entered.set()
            assert release.wait(timeout=10), "the case never released the door"
            return _lock_answer(locked=True)

        lock_door.side_effect = hung_door
        answers: list = []
        first = threading.Thread(target=lambda: answers.append(host_lock.read_lock()))
        second = threading.Thread(target=lambda: answers.append(host_lock.read_lock()))

        first.start()
        assert entered.wait(timeout=10), "the first reader never reached the door"
        second.start()
        second.join(timeout=0.2)
        assert second.is_alive(), "the second reader did not wait on the flight"
        assert lock_door.call_count == 1

        release.set()
        first.join(timeout=10)
        second.join(timeout=10)

        assert not first.is_alive() and not second.is_alive()
        assert lock_door.call_count == 1
        assert answers == [_lock_answer(locked=True), _lock_answer(locked=True)]

    def test_a_server_that_never_serves_the_route_imports_nothing_new(self) -> None:
        """
        The door is imported inside the call, so importing this lane loads no skill.

        Asked of a fresh interpreter, because this one already imported the skill
        at the top of this file.
        """
        probe = (
            "import sys\n"
            "import aipass.api.apps.handlers.host.lock\n"
            "print('aipass.skills.lib.screen_lock.handler' in sys.modules)\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False)

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == "False"
