# =================== AIPass ====================
# Name: test_host_verbs.py
# Description: Tests for the host API verb lane — wake, kill, lock (FPLAN-0411 Phase 3)
# Version: 1.0.1
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/verbs.py and the server routes that reach it: wake, kill, lock."""

# D0: every verb proxies the branch that owns the mechanism; the source-reading checks below are crude on purpose.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that verbs.py parses and imports
# seedgo: no-test-needed(external) — drone's real wake and baud's real end_room; both doors are patched
# seedgo: no-test-needed(covered_elsewhere) — resolve_branch_root itself, tests/test_host_read_lane.py

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.handlers.host import verbs as host_verbs

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_FACE_JSON = "aipass.api.apps.handlers.host.face.json_handler"
PATCH_FACE_LOGGER = "aipass.api.apps.handlers.host.face.logger"
PATCH_VERBS_JSON = "aipass.api.apps.handlers.host.verbs.json_handler"
PATCH_VERBS_LOGGER = "aipass.api.apps.handlers.host.verbs.logger"
PATCH_VERBS_DRONE = "aipass.api.apps.handlers.host.verbs.drone"
PATCH_VERBS_FLEET = "aipass.api.apps.handlers.host.verbs.host_fleet"
PATCH_RESOLVE = "aipass.api.apps.handlers.host.verbs.host_reads.resolve_branch_root"
PATCH_SEATED = "aipass.api.apps.handlers.host.verbs.host_reads.seated_project"
PATCH_HOST_FLEET = "aipass.api.apps.handlers.host.fleet"

# Mismatched case on purpose: @baud sends AIPASS, the directory says AIPass; a case-sensitive compare refuses all.
PROJECT = "aipass"
PROJECT_AS_SENT = "AIPASS"

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def quiet():
    """Silence the verb lane's own logging, and pin the seated project."""
    with patch(PATCH_VERBS_JSON), patch(PATCH_VERBS_LOGGER), patch(PATCH_SEATED, return_value=PROJECT):
        yield


@pytest.fixture
def routed(quiet: Any, tmp_path: Path):
    """A patched drone door that reports a successful wake."""
    with patch(PATCH_VERBS_DRONE) as door:
        door.route_command.return_value = MagicMock(exit_code=0, stdout="woken", stderr="")
        with patch(PATCH_RESOLVE, return_value=tmp_path / "branch"):
            yield door


@pytest.fixture
def killer(quiet: Any, tmp_path: Path):
    """@baud's kill door, patched, answering the ordinary success envelope."""
    with patch(PATCH_VERBS_FLEET) as door:
        door.FleetUnavailable = host_fleet.FleetUnavailable
        door.end_room.return_value = {
            "project": PROJECT_AS_SENT,
            "branch": "memory",
            "room": "baud-memory",
            "ended": True,
            "detail": "ended 'baud-memory'",
            "error": None,
        }
        with patch(PATCH_RESOLVE, return_value=tmp_path / "branch"):
            yield door


def _argv(door: Any) -> list:
    """The full command line the verb lane handed drone."""
    call = door.route_command.call_args
    return [call.args[0]] + [call.args[1]] + list(call.args[2])


class TestWakeGoesThroughThePublicDoor:
    """The mechanism belongs to @ai_mail. This lane only knocks."""

    def test_wake_routes_through_drone(self, routed: Any) -> None:
        """@ai_mail publishes no package door, so drone's router is the door."""
        host_verbs.wake_branch("memory", PROJECT)

        assert routed.route_command.called

    def test_wake_names_ai_mails_dispatch_wake(self, routed: Any) -> None:
        """The exact operator command, not a private entry point."""
        host_verbs.wake_branch("memory", PROJECT)

        argv = _argv(routed)
        assert argv[0] == "@ai_mail"
        assert argv[1] == "dispatch"
        assert argv[2] == "wake"

    def test_the_branch_is_addressed_as_a_citizen(self, routed: Any) -> None:
        """A name, resolved to an address — never a path."""
        host_verbs.wake_branch("memory", PROJECT)

        assert "@memory" in _argv(routed)

    def test_an_unknown_branch_is_refused_before_anything_spawns(self, quiet: Any) -> None:
        """The registry answers first. No subprocess for a name that is not a citizen."""
        with patch(PATCH_VERBS_DRONE) as door:
            with patch(PATCH_RESOLVE, side_effect=host_verbs.host_reads.ReadRefused("Unknown branch: 'nope'")):
                with pytest.raises(host_verbs.VerbRefused):
                    host_verbs.wake_branch("nope", PROJECT)

            assert not door.route_command.called

    def test_a_missing_branch_name_is_refused(self, quiet: Any) -> None:
        """No default target on any verb in this lane."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.wake_branch("", PROJECT)

    def test_a_failed_wake_is_never_reported_as_ok(self, quiet: Any, tmp_path: Path) -> None:
        """drone exiting non-zero means the wake did not happen."""
        with patch(PATCH_VERBS_DRONE) as door:
            door.route_command.return_value = MagicMock(exit_code=2, stdout="", stderr="Wake failed for @memory")
            with patch(PATCH_RESOLVE, return_value=tmp_path / "branch"):
                result = host_verbs.wake_branch("memory", PROJECT)

        assert result["ok"] is False

    def test_the_doors_own_sentence_survives_a_refusal(self, quiet: Any, tmp_path: Path) -> None:
        """@baud renders `detail` verbatim on the chip, so this is what the
        operator reads; a door that responded is ok=false, never a 503."""
        blocked = "target @devpulse is protected from manual wake"
        with patch(PATCH_VERBS_DRONE) as door:
            door.route_command.return_value = MagicMock(exit_code=1, stdout="", stderr=blocked)
            with patch(PATCH_RESOLVE, return_value=tmp_path / "branch"):
                result = host_verbs.wake_branch("devpulse", PROJECT)

        assert result["detail"] == blocked

    def test_the_wake_result_says_which_branch(self, routed: Any) -> None:
        """A phone showing 'ok' with no target is a phone showing nothing."""
        result = host_verbs.wake_branch("memory", PROJECT)

        assert result["branch"] == "@memory"
        assert result["ok"] is True


class TestTheProjectAlwaysTravels:
    """@baud's rule: a room name carries its project scope, and resolving it
    against anything else names a DIFFERENT room."""

    def test_wake_without_a_project_is_refused(self, quiet: Any) -> None:
        """Never optional, never inferred from this server's seat."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.wake_branch("memory", "")

    def test_kill_without_a_project_is_refused(self, quiet: Any) -> None:
        """The destructive one. Same rule, and this is the one it was bought for."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.kill_room("memory", "")

    def test_the_project_comparison_ignores_case(self, routed: Any) -> None:
        """Their wire log says AIPASS; the directory says AIPass."""
        result = host_verbs.wake_branch("memory", PROJECT_AS_SENT)

        assert result["ok"] is True

    def test_neither_verb_takes_a_project_default(self) -> None:
        """An implicit seat is exactly the value @baud got burned by."""
        import inspect

        for verb in (host_verbs.wake_branch, host_verbs.kill_room):
            parameter = inspect.signature(verb).parameters["project"]
            assert parameter.default is inspect.Parameter.empty


class TestAdminIsUnreachableNotJustUnset:
    """`dispatch wake` has no admin flag, so routing through the CLI makes admin
    structurally unexpressible from a network request, not merely unset."""

    def test_no_argument_mentions_admin(self, routed: Any) -> None:
        """The whole command line, checked — not just the parameters we chose."""
        host_verbs.wake_branch("memory", PROJECT, message="please check in")

        assert not any("admin" in str(part).lower() for part in _argv(routed))

    def test_the_caller_cannot_smuggle_admin_through_the_message(self, routed: Any) -> None:
        """The message is opaque payload; it never becomes a flag."""
        host_verbs.wake_branch("memory", PROJECT, message="--admin")

        argv = _argv(routed)

        assert "--admin" in argv, "the message text never reached the argv at all"

        # The message is the trailing POSITIONAL (no --message flag), the slot drone reads as text.
        assert argv.index("--admin") == len(argv) - 1, f"the message text is not the trailing positional: {argv}"
        assert argv.index("--admin") > 3, f"the message value landed where drone reads options: {argv}"

    def test_this_module_never_imports_wake_branch_directly(self) -> None:
        """The in-process import is the one that CAN pass admin."""
        source = Path(host_verbs.__file__).read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]

        assert not any("ai_mail" in line for line in imports)
        assert "handlers.dispatch.wake" not in source

    def test_no_identity_claim_is_forwarded(self, routed: Any) -> None:
        """`--sender` reaches a privilege-bearing parameter; a network claim never tries it."""
        host_verbs.wake_branch("memory", PROJECT)

        assert "--sender" not in _argv(routed)


class TestTheContractSpeaksNoVendorWords:
    """Gate 1, the owner's ruling: the branch config decides what it runs."""

    def test_wake_takes_no_model_argument(self) -> None:
        """The parameter does not exist — there is nothing to leave unset."""
        import inspect

        assert "model" not in inspect.signature(host_verbs.wake_branch).parameters

    def test_no_model_flag_reaches_the_command_line(self, routed: Any) -> None:
        """Not passed, not defaulted, not implied."""
        host_verbs.wake_branch("memory", PROJECT)

        assert "--model" not in _argv(routed)

    def test_no_vendor_name_appears_in_this_module(self) -> None:
        """A zero-vendor-word contract is checkable, so check it."""
        source = Path(host_verbs.__file__).read_text(encoding="utf-8").lower()

        for vendor in ("sonnet", "haiku", "gpt", "gemini"):
            assert vendor not in source


class TestTheMessageIsPayloadNotProtocol:
    """The one caller-controlled string in this lane."""

    def test_a_message_is_forwarded_opaquely(self, routed: Any) -> None:
        """@ai_mail owns prompt vocabulary; this lane does not parse it."""
        host_verbs.wake_branch("memory", PROJECT, message="check the rollover")

        assert "check the rollover" in _argv(routed)

    def test_an_oversized_message_is_refused_not_trimmed(self, quiet: Any) -> None:
        """A prompt is not a payload. Same refuse-never-trim rule as the reads."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.wake_branch("memory", PROJECT, message="x" * (host_verbs.MAX_MESSAGE_CHARS + 1))

    def test_no_message_means_no_empty_argument(self, routed: Any) -> None:
        """An empty positional would land in the message slot as a blank prompt."""
        host_verbs.wake_branch("memory", PROJECT)

        assert "" not in _argv(routed)

    def test_fresh_is_a_flag_not_a_string(self, routed: Any) -> None:
        """Booleans from a network request become flags or nothing."""
        host_verbs.wake_branch("memory", PROJECT, fresh=True)

        assert "--fresh" in _argv(routed)


class TestKillNeverPicksItsOwnTarget:
    """A destructive verb that can guess is a destructive verb that will."""

    def test_a_missing_branch_is_refused(self, quiet: Any) -> None:
        """There is no 'kill the obvious one'."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.kill_room("", PROJECT)

    def test_a_whitespace_branch_is_refused(self, quiet: Any) -> None:
        """A blank that survives a form field is still a blank."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.kill_room("   ", PROJECT)

    def test_the_target_is_validated_before_the_seam_is_consulted(self, quiet: Any) -> None:
        """Refusal order: the target is checked before the gate, so it is never untested."""
        with patch(PATCH_RESOLVE) as resolve:
            with pytest.raises(host_verbs.VerbRefused):
                host_verbs.kill_room("", PROJECT)

            assert not resolve.called


class TestTheKillSwitchIsOperationalNotStructural:
    """KILL_SEAM_READY is an operational switch, like fleet.SNAPSHOT_READY: closed
    means an honest 503, never a session quietly not ended and reported as fine."""

    def test_the_seam_is_open(self) -> None:
        """The door exists now, and the switch reflects that."""
        assert host_verbs.KILL_SEAM_READY is True

    def test_a_closed_switch_refuses_rather_than_pretending(self, quiet: Any, tmp_path: Path) -> None:
        """A shrug that returns 200 is worse than an error."""
        with patch.object(host_verbs, "KILL_SEAM_READY", False):
            with patch(PATCH_RESOLVE, return_value=tmp_path / "branch"):
                with pytest.raises(host_verbs.VerbUnavailable):
                    host_verbs.kill_room("memory", PROJECT)

    def test_a_closed_switch_never_reaches_the_binary(self, quiet: Any, tmp_path: Path) -> None:
        """Checked BEFORE the exec, which is the entire point of a kill switch."""
        with patch.object(host_verbs, "KILL_SEAM_READY", False):
            with patch(PATCH_RESOLVE, return_value=tmp_path / "branch"):
                with patch(PATCH_VERBS_FLEET) as door:
                    with pytest.raises(host_verbs.VerbUnavailable):
                        host_verbs.kill_room("memory", PROJECT)

                    assert not door.end_room.called

    def test_a_closed_switch_says_the_switch_is_closed(self, quiet: Any, tmp_path: Path) -> None:
        """The refusal must not still claim a missing seam; it names the flag on this host."""
        with patch.object(host_verbs, "KILL_SEAM_READY", False):
            with patch(PATCH_RESOLVE, return_value=tmp_path / "branch"):
                with pytest.raises(host_verbs.VerbUnavailable) as caught:
                    host_verbs.kill_room("memory", PROJECT)

        assert "KILL_SEAM_READY" in str(caught.value)


class TestKillRoutesThroughTheOneDoor:
    """The exec lives in fleet.py, which already owns @baud's binary; this lane
    calls a published function and imports no subprocess machinery."""

    def test_the_kill_reaches_bauds_door(self, killer: Any) -> None:
        """One hop, and it is theirs."""
        host_verbs.kill_room("memory", PROJECT_AS_SENT)

        assert killer.end_room.called

    def test_the_target_travels_as_a_name_never_an_address(self, killer: Any) -> None:
        """Their door takes names and refuses separators, in their own words."""
        host_verbs.kill_room("@memory", PROJECT_AS_SENT)

        assert killer.end_room.call_args.args[0] == "memory"

    def test_the_project_travels_verbatim_not_normalised(self, killer: Any) -> None:
        """It is a key in BAUD's census, so this server does not touch its case."""
        host_verbs.kill_room("memory", PROJECT_AS_SENT)

        assert killer.end_room.call_args.args[1] == PROJECT_AS_SENT

    def test_a_door_that_could_not_run_is_never_an_ok(self, killer: Any) -> None:
        """Binary missing, wedged or a bad invocation — none of those ran a kill."""
        killer.FleetUnavailable = host_fleet.FleetUnavailable
        killer.end_room.side_effect = host_fleet.FleetUnavailable("baud is not available")

        with pytest.raises(host_verbs.VerbUnavailable):
            host_verbs.kill_room("memory", PROJECT_AS_SENT)


class TestEndedIsAFactNotASuccessFlag:
    """@baud's contract: `ended: false` with no error means nothing to end, a
    success distinct from ending a live room; flattening them hides which happened."""

    def test_ending_a_live_room_reports_both_ok_and_ended(self, killer: Any) -> None:
        """The ordinary case, and the one that must never be ambiguous."""
        result = host_verbs.kill_room("memory", PROJECT_AS_SENT)

        assert result["ok"] is True
        assert result["ended"] is True
        assert result["room"] == "baud-memory"

    def test_nothing_to_end_is_a_success_that_ended_nothing(self, killer: Any) -> None:
        """ok true, ended false. Two fields because they answer two questions."""
        killer.end_room.return_value = {
            "project": PROJECT_AS_SENT,
            "branch": "memory",
            "room": None,
            "ended": False,
            "detail": "nothing to end",
            "error": None,
        }

        result = host_verbs.kill_room("memory", PROJECT_AS_SENT)

        assert result["ok"] is True
        assert result["ended"] is False
        assert result["detail"] == "nothing to end"

    def test_a_refusal_carries_their_sentence_and_never_ok(self, killer: Any) -> None:
        """Exit 1: they ran and said no. 200 with ok false, their words verbatim."""
        killer.end_room.return_value = {
            "project": PROJECT_AS_SENT,
            "branch": "nosuch",
            "room": None,
            "ended": False,
            "detail": None,
            "error": "no branch named nosuch in project AIPASS",
        }

        result = host_verbs.kill_room("memory", PROJECT_AS_SENT)

        assert result["ok"] is False
        assert result["ended"] is False
        assert result["detail"] == "no branch named nosuch in project AIPASS"

    def test_a_refusal_never_reads_as_nothing_to_end(self, killer: Any) -> None:
        """Both show room null and they are OPPOSITE facts; `ok` tells them apart."""
        killer.end_room.return_value = {
            "room": None,
            "ended": False,
            "detail": None,
            "error": "no branch named nosuch in project AIPASS",
        }
        refused = host_verbs.kill_room("memory", PROJECT_AS_SENT)

        killer.end_room.return_value = {"room": None, "ended": False, "detail": "nothing to end", "error": None}
        already_gone = host_verbs.kill_room("memory", PROJECT_AS_SENT)

        assert refused["room"] == already_gone["room"] is None
        assert refused["ended"] == already_gone["ended"] is False
        assert refused["ok"] is not already_gone["ok"]


class TestKillCarriesTheRoomsOwnProject:
    """The scope travels with the target, not the caller: resolving under the
    seat can end a session the operator never named."""

    def test_the_project_is_accepted_as_a_parameter(self) -> None:
        """It exists so a client can name it — that is the whole point."""
        import inspect

        assert "project" in inspect.signature(host_verbs.kill_room).parameters

    def test_the_project_is_checked_before_the_target(self, quiet: Any) -> None:
        """Scope first, then identity."""
        with patch(PATCH_RESOLVE) as resolve:
            with pytest.raises(host_verbs.VerbRefused):
                host_verbs.kill_room("memory", "")

            assert not resolve.called


class TestLockIsNeverGated:
    """@skills' doctrine: lock must work from anywhere, so this verb asks no questions before firing."""

    def test_lock_calls_the_skill(self, quiet: Any) -> None:
        """The mechanism is @skills'. This is a proxy and nothing else."""
        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {"locked": True, "method": "loginctl", "session": "3", "error": None}

            host_verbs.lock_screen()

            assert skill.lock_screen.called

    def test_lock_checks_no_precondition(self, quiet: Any) -> None:
        """Not screen state, not a desktop environment, not a session id."""
        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {"locked": True, "method": "dbus", "session": None, "error": None}

            result = host_verbs.lock_screen()

            assert result["ok"] is True
            assert skill.resolve_graphical_session.called is False


class TestTheSkillOwnsTheFailureText:
    """A screen that never locked can never be acked as locked."""

    def test_a_failed_lock_is_never_ok(self, quiet: Any) -> None:
        """The one thing that must never happen: a padlock drawn over a live desk.

        `ok: false` rather than a raise: the mechanism DID run and answered.
        """
        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {
                "locked": False,
                "method": None,
                "session": None,
                "error": "the screen locker refused and no fallback is installed",
            }

            assert host_verbs.lock_screen()["ok"] is False

    def test_the_skills_own_sentence_is_surfaced_verbatim(self, quiet: Any) -> None:
        """Rewriting another branch's error is how a diagnosis gets lost."""
        sentence = "the screen locker refused and no fallback is installed"
        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {"locked": False, "method": None, "session": None, "error": sentence}

            assert host_verbs.lock_screen()["detail"] == sentence

    def test_a_lock_with_no_error_text_still_says_something(self, quiet: Any) -> None:
        """A falsy 'locked' with an empty error must not render as a blank chip."""
        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {"locked": False, "method": None, "session": None, "error": None}

            result = host_verbs.lock_screen()

        assert result["ok"] is False
        assert result["detail"]

    def test_the_method_is_reported_so_the_fallback_is_visible(self, quiet: Any) -> None:
        """loginctl vs dbus tells an operator which path is carrying them."""
        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {"locked": True, "method": "dbus", "session": None, "error": None}

            assert host_verbs.lock_screen()["method"] == "dbus"


class TestNoMechanismIsReimplementedHere:
    """The review test for charter drift, written as an assertion."""

    def test_the_verb_lane_executes_nothing_itself(self) -> None:
        """The sharpest form of the rule: this module cannot run a program."""
        source = Path(host_verbs.__file__).read_text(encoding="utf-8")

        assert "import subprocess" not in source
        assert "Popen" not in source
        assert "os.system" not in source
        # The exec/spawn families and the from-import spelling that dodges "import subprocess".
        assert "from subprocess" not in source
        assert "os.exec" not in source
        assert "os.spawn" not in source
        assert "os.popen" not in source

    def test_the_verb_lane_still_executes_nothing_after_the_terminal_lane(self) -> None:
        """The terminal lane's PTY lives in attach.py, never in the module that decides."""
        source = Path(host_verbs.__file__).read_text(encoding="utf-8")

        assert "import subprocess" not in source
        assert "Popen" not in source
        assert "os.system" not in source
        assert "import pty" not in source

    def test_the_fleet_module_is_the_only_way_out(self) -> None:
        """Every mechanism import in this file, enumerated, so adding one is a decision."""
        source = Path(host_verbs.__file__).read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
        mechanisms = [line for line in imports if "aipass.api" not in line and "typing" not in line]

        assert mechanisms == [
            "import re",
            "from aipass.prax import logger",
            "import aipass.drone as drone",
            "from aipass.skills.lib.screen_lock import handler as screen_lock",
            "from aipass.aipass.apps.modules import new_project as project_door",
        ]

    def test_every_verb_names_the_branch_that_owns_it(self) -> None:
        """A proxy whose docstring does not name its owner drifts into a component."""
        source = Path(host_verbs.__file__).read_text(encoding="utf-8")

        for owner in ("@ai_mail", "@baud", "@skills"):
            assert owner in source


@pytest.fixture
def client(tmp_path: Path):
    """A test client over a temporary token store."""
    from fastapi.testclient import TestClient

    store = tmp_path / "secrets"
    with (
        patch(PATCH_SECRETS_BASE, store),
        patch(PATCH_SECRETS_JSON),
        patch(PATCH_SECRETS_LOGGER),
        patch(PATCH_TOKENS_JSON),
        patch(PATCH_TOKENS_LOGGER),
        patch(PATCH_SERVER_LOGGER),
        patch(PATCH_SERVER_JSON),
        patch(PATCH_FACE_JSON),
        patch(PATCH_FACE_LOGGER),
        patch(PATCH_VERBS_JSON),
        patch(PATCH_VERBS_LOGGER),
        patch(PATCH_SEATED, return_value=PROJECT),
    ):
        yield TestClient(host_server.create_app(), raise_server_exceptions=False)


def _body(**extra: Any) -> dict:
    """The body @baud's client actually sends, plus whatever a test adds."""
    return {"branch": "memory", "project": PROJECT_AS_SENT, **extra}


@fastapi_required
class TestTheScopeWallCarriesProductionWeight:
    """The first endpoints in AIPass that a read token must NOT reach."""

    @pytest.mark.parametrize("verb", ["wake", "kill", "lock"])
    def test_a_read_token_is_refused_by_every_verb(self, client: Any, verb: str) -> None:
        """Read is read. The phone's own token holds exactly this scope tonight."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        headers = {"Authorization": f"Bearer {raw}"}
        response = client.post(f"/v1/verbs/{verb}", json=_body(), headers=headers)

        assert response.status_code == 403

    @pytest.mark.parametrize("verb", ["wake", "kill", "lock"])
    def test_no_token_is_refused_by_every_verb(self, client: Any, verb: str) -> None:
        """401 before 403 — an anonymous caller never learns a scope exists."""
        response = client.post(f"/v1/verbs/{verb}", json=_body())

        assert response.status_code == 401

    @pytest.mark.parametrize("verb", ["wake", "kill", "lock"])
    def test_the_verb_never_runs_for_a_read_token(self, client: Any, verb: str) -> None:
        """The wall stops the mechanism, not just the response."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_VERBS_DRONE) as door, patch.object(host_verbs, "screen_lock") as skill:
            client.post(f"/v1/verbs/{verb}", json=_body(), headers={"Authorization": f"Bearer {raw}"})

            assert not door.route_command.called
            assert not skill.lock_screen.called

    @pytest.mark.parametrize("verb", ["wake", "kill", "lock"])
    def test_a_verb_is_not_reachable_by_get(self, client: Any, verb: str) -> None:
        """A destructive action must never be a URL somebody can click."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        response = client.get(f"/v1/verbs/{verb}", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 405


@fastapi_required
class TestTheVerbRouteTableIsExactlyFourThings:
    """The route table read back, so a verb cannot arrive quietly."""

    def _verb_routes(self) -> dict:
        """Path to (endpoint name, methods) for everything under /v1/verbs."""
        app = host_server.create_app()
        return {
            route.path: (route.endpoint.__name__, set(route.methods))
            for route in app.routes
            if getattr(route, "path", "").startswith("/v1/verbs")
        }

    def test_exactly_four_verbs_are_registered(self) -> None:
        """wake, kill, lock and new-project; keystrokes ride the attach PTY, never a /v1/verbs/keys proxy."""
        assert set(self._verb_routes()) == {
            "/v1/verbs/wake",
            "/v1/verbs/kill",
            "/v1/verbs/lock",
            "/v1/verbs/new-project",
        }

    def test_verb_wake_is_post_only(self) -> None:
        """A wake spawns a real agent — never something a browser can prefetch."""
        name, methods = self._verb_routes()["/v1/verbs/wake"]

        assert name == "verb_wake"
        assert methods == {"POST"}

    def test_verb_kill_is_post_only(self) -> None:
        """The destructive one. Same rule, higher stakes."""
        name, methods = self._verb_routes()["/v1/verbs/kill"]

        assert name == "verb_kill"
        assert methods == {"POST"}

    def test_verb_lock_is_post_only(self) -> None:
        """Locking is not a read, so it does not get a read's method."""
        name, methods = self._verb_routes()["/v1/verbs/lock"]

        assert name == "verb_lock"
        assert methods == {"POST"}


@fastapi_required
class TestTheVerbRoutesAnswer:
    """An operate token reaches the lane; the lane's own rules still apply."""

    def test_wake_reaches_the_door(self, client: Any, tmp_path: Path) -> None:
        """The proxy runs and reports the branch back."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch(PATCH_VERBS_DRONE) as door, patch(PATCH_RESOLVE, return_value=tmp_path / "b"):
            door.route_command.return_value = MagicMock(exit_code=0, stdout="ok", stderr="")
            response = client.post("/v1/verbs/wake", json=_body(), headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json()["branch"] == "@memory"

    def test_wake_without_a_branch_is_a_400(self, client: Any) -> None:
        """The caller's mistake, named as theirs."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        response = client.post("/v1/verbs/wake", json=_body(branch=""), headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 400

    def test_wake_without_a_project_is_a_400(self, client: Any) -> None:
        """Never inferred from the seat, even when there is only one seat."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        response = client.post("/v1/verbs/wake", json={"branch": "memory"}, headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 400

    def test_kill_reaches_the_door_and_reports_the_room(self, client: Any, tmp_path: Path) -> None:
        """The seam landed; the route carries their envelope through."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_RESOLVE, return_value=tmp_path / "b"):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            door.end_room.return_value = {"room": "baud-memory", "ended": True, "detail": "ended", "error": None}
            response = client.post("/v1/verbs/kill", json=_body(), headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json()["ended"] is True
        assert response.json()["room"] == "baud-memory"

    def test_kill_answers_503_when_the_switch_is_closed(self, client: Any, tmp_path: Path) -> None:
        """The operational switch still produces an honest refusal, not a 200."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch.object(host_verbs, "KILL_SEAM_READY", False):
            with patch(PATCH_RESOLVE, return_value=tmp_path / "b"):
                response = client.post("/v1/verbs/kill", json=_body(), headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 503

    def test_lock_reaches_the_skill(self, client: Any) -> None:
        """One proxy hop, no arguments, no preconditions."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {"locked": True, "method": "loginctl", "session": "3", "error": None}
            response = client.post("/v1/verbs/lock", json={}, headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_a_failed_lock_is_a_200_carrying_ok_false(self, client: Any) -> None:
        """The mechanism ran and said no: an answer for @baud's chip, not a server fault."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch.object(host_verbs, "screen_lock") as skill:
            skill.lock_screen.return_value = {"locked": False, "method": None, "session": None, "error": "no session"}
            response = client.post("/v1/verbs/lock", json={}, headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["detail"] == "no session"


@fastapi_required
class TestTheClientIsNeverTrusted:
    """@baud's confirm dialog and lock-screen check are pocket-safety, not
    security; this server honours no `confirmed` field."""

    def test_a_confirmed_flag_reaches_nothing_on_the_kill_lane(self, client: Any, tmp_path: Path) -> None:
        """Their confirm dialog is pocket-safety, not a gate this server honours."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_RESOLVE, return_value=tmp_path / "b"):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            door.end_room.return_value = {"room": None, "ended": False, "detail": "nothing to end", "error": None}
            client.post(
                "/v1/verbs/kill",
                json=_body(confirmed=True, admin=True),
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert door.end_room.call_args.args == ("memory", PROJECT_AS_SENT)

    def test_an_admin_field_in_the_body_reaches_nothing(self, client: Any, tmp_path: Path) -> None:
        """Unknown keys are ignored, and `admin` is not a key this lane reads."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch(PATCH_VERBS_DRONE) as door, patch(PATCH_RESOLVE, return_value=tmp_path / "b"):
            door.route_command.return_value = MagicMock(exit_code=0, stdout="ok", stderr="")
            client.post(
                "/v1/verbs/wake",
                json=_body(admin=True, confirmed=True),
                headers={"Authorization": f"Bearer {raw}"},
            )

        argv = _argv(door)
        assert not any("admin" in str(part).lower() for part in argv)
        assert not any("confirm" in str(part).lower() for part in argv)


class TestOneTerminalReachesAnyAgent:
    """One terminal reaches any agent in any project: WHO can be reached widens,
    but the project is STILL required, never inferred, and a garbage target still dies."""

    @pytest.fixture
    def census(self, quiet: Any, tmp_path: Path):
        """@baud's census, standing in for a branch in another project.

        Patched in TWO places: kill uses verbs' module-level `host_fleet`, branch
        resolution imports it off the package inside the read lane.
        """
        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_HOST_FLEET, door):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            # A REAL directory: the resolver checks the census path exists.
            elsewhere = tmp_path / "projects" / "baud" / "src" / "baud"
            elsewhere.mkdir(parents=True)
            door.resolve_branch.return_value = {"name": "baud", "path": str(elsewhere)}
            door.end_room.return_value = {
                "project": "BAUD",
                "branch": "baud",
                "room": "baud-baud",
                "ended": True,
                "detail": "ended 'baud-baud'",
                "error": None,
            }
            yield door

    def test_wake_reaches_a_branch_in_another_project(self, census: Any) -> None:
        """A sleeping agent must be able to appear in the one seat, wherever it lives."""
        with patch(PATCH_VERBS_DRONE) as door:
            door.route_command.return_value = MagicMock(exit_code=0, stdout="woken", stderr="")
            result = host_verbs.wake_branch("baud", "BAUD")

        assert result["ok"] is True
        assert result["project"] == "BAUD"

    def test_a_foreign_branch_is_resolved_through_the_census(self, census: Any) -> None:
        """The seated registry does not know a tenant's branches, so the census is the only door."""
        with patch(PATCH_VERBS_DRONE) as door:
            door.route_command.return_value = MagicMock(exit_code=0, stdout="woken", stderr="")
            host_verbs.wake_branch("baud", "BAUD")

        census.resolve_branch.assert_called_once_with("BAUD", "baud")

    def test_the_seat_never_pays_for_a_census(self, routed: Any, census: Any) -> None:
        """The local registry stays the fast path for the project we stand in."""
        host_verbs.wake_branch("memory", PROJECT_AS_SENT)

        census.resolve_branch.assert_not_called()

    def test_an_unknown_branch_in_a_known_project_is_still_refused(self, census: Any) -> None:
        """Widening WHO can be reached is not widening to nobody in particular."""
        census.resolve_branch.return_value = None

        with pytest.raises(host_verbs.VerbRefused) as exc:
            host_verbs.wake_branch("nosuch", "BAUD")

        assert "BAUD" in str(exc.value) and "nosuch" in str(exc.value)

    def test_an_unknown_project_carries_the_census_sentence(self, census: Any) -> None:
        """Unavailable, not refused, and phrased by the branch that knows."""
        census.resolve_branch.side_effect = host_fleet.FleetUnavailable("no project named 'nope' in BAUD's census")

        with pytest.raises(host_verbs.VerbUnavailable) as exc:
            host_verbs.wake_branch("baud", "nope")

        assert "no project named 'nope'" in str(exc.value)

    def test_kill_reaches_another_projects_room(self, census: Any) -> None:
        """The counterpart of attach on the same card; @baud's door resolves the room itself."""
        with patch.object(host_verbs, "KILL_SEAM_READY", True):
            result = host_verbs.kill_room("baud", "BAUD")

        assert result["ok"] is True
        census.end_room.assert_called_once_with("baud", "BAUD")

    def test_the_project_is_still_required_on_every_verb(self, quiet: Any) -> None:
        """The rule that did NOT change: widening reach makes an inferred seat MORE dangerous."""
        for verb in (host_verbs.wake_branch, host_verbs.kill_room):
            with pytest.raises(host_verbs.VerbRefused):
                verb("memory", "")

    def test_no_verb_says_it_does_not_serve_the_project(self) -> None:
        """The sentence is gone from this lane."""
        source = Path(host_verbs.__file__).read_text(encoding="utf-8")

        assert "does not serve project" not in source
