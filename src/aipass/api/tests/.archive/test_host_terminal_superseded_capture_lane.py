#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_terminal.py
# Description: Tests for the host API terminal lane — room pane and keys (DPLAN-0300 Seam 2)
# Version: 1.0.0
# Created: 2026-08-14
# =============================================

"""
Tests for the Terminal Lane

Seam 2 of DPLAN-0300's terminal contract: `GET /v1/room/pane` proxying
`baud --capture-room`, and `POST /v1/verbs/keys` proxying `baud --send-room`.

BUILT AGAINST THE CONTRACT, NOT THE BINARY. @baud is building Seam 1 in
parallel and the flags may not exist on disk yet — the same way the verb lane
was built against their written envelope before their door existed. Nothing
here launches the real binary.

THE TWO THINGS THIS LANE COULD GET WRONG, and neither is "does it work":

  1. A cap that silently trims. A client that asked for 5000 lines and quietly
     received 2000 renders a partial screen as the whole screen. Every cap here
     REFUSES, and each refusal is mutation-checked — stubbed off to watch the
     test fail — because a guard nobody has seen bite is a guard nobody knows
     they have.

  2. Typing. `--key` is sent WITHOUT `-l`, so tmux INTERPRETS it: the only path
     in this lane where a caller's bytes are not literal. That is why the key
     allowlist is mirrored at this door as well as @baud's, and why `--text`
     never carrying a newline is pinned rather than assumed.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

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
PATCH_VERBS_FLEET = "aipass.api.apps.handlers.host.verbs.host_fleet"
PATCH_FLEET_JSON = "aipass.api.apps.handlers.host.fleet.json_handler"
PATCH_FLEET_LOGGER = "aipass.api.apps.handlers.host.fleet.logger"
PATCH_RESOLVE = "aipass.api.apps.handlers.host.verbs.host_reads.resolve_branch_root"
PATCH_SEATED = "aipass.api.apps.handlers.host.verbs.host_reads.seated_project"

PROJECT = "aipass"
PROJECT_AS_SENT = "AIPASS"

# A real capture carries escape sequences — that is the whole point of -e, and
# the phone renders the colour. Anything this lane does to them is a bug.
PANE_TEXT = "\x1b[32mapi\x1b[0m $ pytest\n  865 passed\n"

CAPTURED = {
    "project": PROJECT_AS_SENT,
    "branch": "api",
    "room": "baud-api",
    "pane": PANE_TEXT,
    "cols": 120,
    "rows": 40,
    "captured": True,
    "detail": "captured 40 rows",
    "error": None,
    "generated_at": "2026-08-15T04:40:00Z",
}

SENT = {
    "project": PROJECT_AS_SENT,
    "branch": "api",
    "room": "baud-api",
    "sent": True,
    "detail": "sent 6 characters",
    "error": None,
    "generated_at": "2026-08-15T04:40:00Z",
}

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def quiet():
    """Silence the lane's logging and pin the seated project."""
    with patch(PATCH_VERBS_JSON), patch(PATCH_VERBS_LOGGER), patch(PATCH_SEATED, return_value=PROJECT):
        yield


@pytest.fixture
def captor(quiet: Any):
    """@baud's capture door, patched, answering a real pane."""
    with patch(PATCH_VERBS_FLEET) as door:
        door.FleetUnavailable = host_fleet.FleetUnavailable
        door.capture_room.return_value = dict(CAPTURED)
        with patch(PATCH_RESOLVE, return_value=Path("/tmp/branch")):
            yield door


@pytest.fixture
def typist(quiet: Any):
    """@baud's send door, patched, answering a successful send."""
    with patch(PATCH_VERBS_FLEET) as door:
        door.FleetUnavailable = host_fleet.FleetUnavailable
        door.send_room.return_value = dict(SENT)
        with patch(PATCH_RESOLVE, return_value=Path("/tmp/branch")):
            yield door


# ==============================================
# THE PANE — a read, and it changes nothing
# ==============================================


class TestThePaneIsReturnedExactlyAsCaptured:
    """
    A screen read that alters the screen is worse than no screen read.

    Escape sequences, trailing whitespace, blank lines: all of it is what the
    operator would see at the desk, so all of it survives this lane untouched.
    """

    def test_the_escape_sequences_survive(self, captor: Any) -> None:
        """Colour is data here. Stripping it is a silent change to the answer."""
        result = host_verbs.read_pane("api")

        assert result["pane"] == PANE_TEXT
        assert "\x1b[32m" in result["pane"]

    def test_the_geometry_travels(self, captor: Any) -> None:
        """The phone renders at the CAPTURED geometry — it never resizes the room."""
        result = host_verbs.read_pane("api")

        assert (result["cols"], result["rows"]) == (120, 40)

    def test_a_captured_pane_is_ok(self, captor: Any) -> None:
        """The ordinary case, and the one the 1s poll hits every second."""
        result = host_verbs.read_pane("api")

        assert result["ok"] is True
        assert result["captured"] is True

    def test_an_unknown_room_is_a_refusal_never_an_empty_pane(self, captor: Any) -> None:
        """
        @baud's rule, and it is the same shape as their kill door.

        An empty pane and a refused capture would both render as a blank
        terminal, and they are opposite facts: one means the room is quiet, the
        other means the name is wrong.
        """
        captor.capture_room.return_value = {
            "room": None,
            "pane": None,
            "captured": False,
            "detail": None,
            "error": "no room for branch 'api' in project AIPASS",
        }

        result = host_verbs.read_pane("api")

        assert result["ok"] is False
        assert result["detail"] == "no room for branch 'api' in project AIPASS"

    def test_a_door_that_could_not_run_is_never_an_ok(self, captor: Any) -> None:
        """Binary missing or wedged: nothing was read, so there is no answer."""
        captor.capture_room.side_effect = host_fleet.FleetUnavailable("baud is not available")

        with pytest.raises(host_verbs.VerbUnavailable):
            host_verbs.read_pane("api")


class TestThePaneTargetsARoomLikeEveryOtherRoomVerb:
    """The room-targeting contract, applied to a read."""

    def test_a_branch_is_required(self, quiet: Any) -> None:
        """No default target, on a read as much as on a kill."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.read_pane("")

    def test_an_unknown_branch_is_refused_before_the_door(self, quiet: Any) -> None:
        """My registry, my answer — @baud never hears about a name I can reject."""
        with patch(PATCH_VERBS_FLEET) as door:
            with patch(PATCH_RESOLVE, side_effect=host_verbs.host_reads.ReadRefused("Unknown branch: 'nope'")):
                with pytest.raises(host_verbs.VerbRefused):
                    host_verbs.read_pane("nope")

                assert not door.capture_room.called

    def test_the_branch_travels_as_a_name_never_an_address(self, captor: Any) -> None:
        """Their door takes names; '@api' would read as a branch they never heard of."""
        host_verbs.read_pane("@api")

        assert captor.capture_room.call_args.args[0] == "api"

    def test_the_project_is_optional_unlike_the_verbs(self, captor: Any) -> None:
        """
        The asymmetry is deliberate and it is about consequence.

        Reading the wrong room shows the wrong screen to someone who is looking
        at it; typing into the wrong one puts keystrokes somewhere nobody
        looked. So this matches the fleet lane, not the verb lane.
        """
        result = host_verbs.read_pane("api")

        assert result["ok"] is True

    def test_a_project_this_server_does_not_serve_is_still_refused(self, captor: Any) -> None:
        """Optional does not mean unchecked — a named project must be ours."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.read_pane("api", project="some-other-project")

    def test_the_project_travels_verbatim_when_given(self, captor: Any) -> None:
        """A census key. Their casing, not ours — the wire says AIPASS."""
        host_verbs.read_pane("api", project=PROJECT_AS_SENT)

        assert captor.capture_room.call_args.args[1] == PROJECT_AS_SENT


class TestTheLinesCapRefusesRatherThanTrims:
    """
    The cap the contract left open, decided the way every other cap on this
    server is decided.

    A client that asked for 5000 lines and silently received 2000 cannot tell it
    was cut, and would render a partial screen as the whole screen. The one
    place this server clamps instead is the feed cursor — and there the clamp is
    reported in a `gap` flag, for exactly this reason.
    """

    def test_the_cap_is_what_the_contract_says(self) -> None:
        """2000, from DPLAN-0300 Round 18."""
        assert host_verbs.MAX_PANE_LINES == 2000

    def test_the_visible_pane_is_the_default(self, captor: Any) -> None:
        """Zero scrollback: the poll should not drag history every second."""
        host_verbs.read_pane("api")

        assert captor.capture_room.call_args.args[2] == 0

    def test_a_request_at_the_cap_is_allowed(self, captor: Any) -> None:
        """The boundary belongs to the caller — off-by-one here is a real bug."""
        result = host_verbs.read_pane("api", lines=host_verbs.MAX_PANE_LINES)

        assert result["lines"] == host_verbs.MAX_PANE_LINES

    def test_one_over_the_cap_is_refused_and_never_reaches_the_door(self, captor: Any) -> None:
        """Refused, not trimmed — and the mechanism does not run."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.read_pane("api", lines=host_verbs.MAX_PANE_LINES + 1)

        assert not captor.capture_room.called

    def test_the_refusal_names_the_cap_and_says_it_was_not_trimmed(self, captor: Any) -> None:
        """A cap the caller cannot see is a cap they will hit again next second."""
        with pytest.raises(host_verbs.VerbRefused) as caught:
            host_verbs.read_pane("api", lines=5000)

        assert "2000" in str(caught.value)
        assert "trimmed" in str(caught.value)

    def test_a_negative_line_count_is_refused(self, captor: Any) -> None:
        """Nonsense in, refusal out — never quietly reinterpreted as zero."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.read_pane("api", lines=-1)

    def test_a_non_numeric_line_count_is_refused(self, captor: Any) -> None:
        """The caller's mistake, named as theirs rather than crashed on."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.read_pane("api", lines="lots")  # type: ignore[arg-type]


# ==============================================
# TYPING — the one place bytes get interpreted
# ==============================================


class TestExactlyOneOfTextOrKey:
    """
    Both is ambiguous; neither is a no-op wearing an action's clothes.

    @baud refuses this at their end too, which is the point: a bug on either
    side produces a refusal rather than a surprise keystroke in a live session.
    """

    def test_neither_is_refused(self, typist: Any) -> None:
        """An empty send is not a send."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.send_keys("api", PROJECT_AS_SENT)

    def test_both_is_refused(self, typist: Any) -> None:
        """Two intentions in one request, and no rule for which wins."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.send_keys("api", PROJECT_AS_SENT, text="ls", key="Enter")

    def test_neither_reaches_the_door(self, typist: Any) -> None:
        """The refusal happens here, so an ambiguous request types nothing."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.send_keys("api", PROJECT_AS_SENT, text="ls", key="Enter")

        assert not typist.send_room.called


class TestTextIsLiteralAndNeverSubmits:
    """
    @baud's doctrine, carried unchanged: text is inserted WITHOUT a newline, so
    submitting stays the operator's keystroke and a paste alone can never
    execute. The defence lives in their code; this lane's job is to not go
    looking for a way around it.
    """

    def test_the_text_travels_unchanged(self, typist: Any) -> None:
        """No trimming, no escaping, no normalising — literal means literal."""
        host_verbs.send_keys("api", PROJECT_AS_SENT, text="  ls -la  ")

        assert typist.send_room.call_args.args[2] == "  ls -la  "

    def test_no_newline_is_ever_appended(self, typist: Any) -> None:
        """
        The single most important assertion in this file.

        If this lane appended a newline, every paste from the phone would
        EXECUTE, and the operator's confirm-by-keystroke would be gone without
        anybody deciding to remove it.
        """
        host_verbs.send_keys("api", PROJECT_AS_SENT, text="rm -rf /")

        sent = typist.send_room.call_args.args[2]
        assert sent == "rm -rf /"
        assert not sent.endswith("\n")

    def test_a_control_sequence_in_text_stays_four_characters(self, typist: Any) -> None:
        """Their rule: a literal 'C-c' in text types those characters, never a signal."""
        host_verbs.send_keys("api", PROJECT_AS_SENT, text="C-c")

        assert typist.send_room.call_args.args[2] == "C-c"
        assert typist.send_room.call_args.args[3] == ""

    def test_text_at_the_cap_is_allowed(self, typist: Any) -> None:
        """The boundary belongs to the caller."""
        result = host_verbs.send_keys("api", PROJECT_AS_SENT, text="x" * host_verbs.MAX_TEXT_CHARS)

        assert result["ok"] is True

    def test_one_character_over_the_cap_is_refused_not_trimmed(self, typist: Any) -> None:
        """
        A truncated command is worse than a rejected one, because it is still a
        valid command — and a shorter one may do something entirely different.
        """
        with pytest.raises(host_verbs.VerbRefused) as caught:
            host_verbs.send_keys("api", PROJECT_AS_SENT, text="x" * (host_verbs.MAX_TEXT_CHARS + 1))

        assert str(host_verbs.MAX_TEXT_CHARS) in str(caught.value)
        assert not typist.send_room.called


class TestTheKeyAllowlistIsCheckedAtThisDoorToo:
    """
    `--key` is sent WITHOUT `-l`, so tmux interprets it — the only path in this
    lane where a caller's bytes are not literal.

    Mirroring another branch's enum is something this file otherwise refuses to
    do. It earns its place here because a stale mirror fails SAFE and LOUD: a
    key @baud adds and this list has not learned is refused with a sentence
    naming the mirror. The reverse — an unvalidated string reaching an
    interpreting send-keys — has no such recovery.
    """

    def test_the_allowlist_is_exactly_the_published_contract(self) -> None:
        """Fourteen names, from DPLAN-0300 Round 18. Not a superset."""
        assert set(host_verbs.KEY_ALLOWLIST) == {
            "Enter",
            "Escape",
            "Tab",
            "Up",
            "Down",
            "Left",
            "Right",
            "C-c",
            "C-d",
            "C-l",
            "C-u",
            "BSpace",
            "PageUp",
            "PageDown",
        }

    @pytest.mark.parametrize("key", ["Enter", "Escape", "C-c", "PageDown"])
    def test_every_published_key_is_accepted(self, typist: Any, key: str) -> None:
        """A key bar button that 400s is a feature that reads as broken."""
        result = host_verbs.send_keys("api", PROJECT_AS_SENT, key=key)

        assert result["ok"] is True
        assert typist.send_room.call_args.args[3] == key

    def test_an_unknown_key_is_refused(self, typist: Any) -> None:
        """The fence, and it must bite before the door is reached."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.send_keys("api", PROJECT_AS_SENT, key="C-z")

        assert not typist.send_room.called

    def test_a_shell_fragment_as_a_key_is_refused(self, typist: Any) -> None:
        """
        The reason this mirror exists, written as a test.

        Without it, an arbitrary string reaches a send-keys that INTERPRETS its
        argument. @baud's fence is the real one; this is the one that means a
        bug in theirs is not automatically a bug in mine.
        """
        for candidate in ("Enter; rm -rf /", "C-c Enter", "$(whoami)", "Enter\nEnter"):
            with pytest.raises(host_verbs.VerbRefused):
                host_verbs.send_keys("api", PROJECT_AS_SENT, key=candidate)

        assert not typist.send_room.called

    def test_the_refusal_says_the_list_may_be_the_stale_one(self, typist: Any) -> None:
        """
        A mirror that refuses without admitting it is a mirror sends an operator
        hunting in @baud's code for a key they already shipped.
        """
        with pytest.raises(host_verbs.VerbRefused) as caught:
            host_verbs.send_keys("api", PROJECT_AS_SENT, key="F5")

        assert "mirror" in str(caught.value).lower()

    def test_the_key_name_is_case_sensitive(self, typist: Any) -> None:
        """
        Their enum, their casing — 'enter' is not a tmux key name.

        Deliberately unlike `project`, which is compared case-insensitively:
        that is a name a human types on a phone, this is a constant a client
        emits from a button.
        """
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.send_keys("api", PROJECT_AS_SENT, key="enter")


class TestTypingTargetsARoomAndTheProjectIsRequired:
    """A verb that names a target: the full room-targeting contract applies."""

    def test_a_project_is_required(self, typist: Any) -> None:
        """Typing into the wrong room puts keystrokes where nobody looked."""
        with pytest.raises(host_verbs.VerbRefused):
            host_verbs.send_keys("api", "", key="Enter")

    def test_the_project_is_checked_before_the_target(self, quiet: Any) -> None:
        """Scope first: a branch name is only meaningful inside a project."""
        with patch(PATCH_RESOLVE) as resolve:
            with pytest.raises(host_verbs.VerbRefused):
                host_verbs.send_keys("api", "", key="Enter")

            assert not resolve.called

    def test_an_unknown_branch_never_reaches_the_door(self, quiet: Any) -> None:
        """My registry answers first, so @baud never hears a name I can reject."""
        with patch(PATCH_VERBS_FLEET) as door:
            with patch(PATCH_RESOLVE, side_effect=host_verbs.host_reads.ReadRefused("Unknown branch: 'nope'")):
                with pytest.raises(host_verbs.VerbRefused):
                    host_verbs.send_keys("nope", PROJECT_AS_SENT, key="Enter")

                assert not door.send_room.called

    def test_a_refusal_from_their_door_is_a_200_with_their_sentence(self, typist: Any) -> None:
        """The mechanism ran and said no — that is an answer, not a server fault."""
        typist.send_room.return_value = {
            "room": None,
            "sent": False,
            "detail": None,
            "error": "no room for branch 'api' in project AIPASS",
        }

        result = host_verbs.send_keys("api", PROJECT_AS_SENT, key="Enter")

        assert result["ok"] is False
        assert result["sent"] is False
        assert result["detail"] == "no room for branch 'api' in project AIPASS"

    def test_a_door_that_could_not_run_is_a_503(self, typist: Any) -> None:
        """Nothing was typed, so there is no sentence for the operator to read."""
        typist.send_room.side_effect = host_fleet.FleetUnavailable("baud is not available")

        with pytest.raises(host_verbs.VerbUnavailable):
            host_verbs.send_keys("api", PROJECT_AS_SENT, key="Enter")


# ==============================================
# THE EXEC — fleet.py owns @baud's binary
# ==============================================


@pytest.fixture
def seated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Pin the repo root and the resolved binary the exec would use."""
    monkeypatch.setattr(host_fleet, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(host_fleet, "snapshot_binary", lambda: "baud")
    with patch(PATCH_FLEET_JSON), patch(PATCH_FLEET_LOGGER):
        yield tmp_path


def _completed(code: int, stdout: str = "", stderr: str = ""):
    """A finished subprocess, shaped like the real one."""
    from unittest.mock import MagicMock

    result = MagicMock()
    result.returncode = code
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestTheCaptureInvocation:
    """The command line handed to their binary, part by part."""

    def test_the_flag_and_branch_are_what_they_published(self, seated: Path) -> None:
        """`baud --capture-room <branch>`, exactly."""
        import json

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(CAPTURED))) as run:
            host_fleet.capture_room("api", "AIPASS")

        assert run.call_args.args[0][:3] == ["baud", "--capture-room", "api"]

    def test_lines_is_omitted_entirely_when_zero(self, seated: Path) -> None:
        """
        Their default is the visible pane, so this sends nothing rather than
        '--lines 0'. Two ways to say the same thing is how a default drifts.
        """
        import json

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(CAPTURED))) as run:
            host_fleet.capture_room("api", "AIPASS", 0)

        assert "--lines" not in run.call_args.args[0]

    def test_lines_travels_when_asked_for(self, seated: Path) -> None:
        """Scrollback is opt-in, and the number is the caller's."""
        import json

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(CAPTURED))) as run:
            host_fleet.capture_room("api", "AIPASS", 500)

        assert run.call_args.args[0][-2:] == ["--lines", "500"]

    def test_the_capture_timeout_reaches_subprocess(self, seated: Path) -> None:
        """A 1s poll behind a 30s timeout stacks requests behind each other."""
        import json

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(CAPTURED))) as run:
            host_fleet.capture_room("api", "AIPASS")

        assert run.call_args.kwargs["timeout"] == host_fleet.CAPTURE_TIMEOUT_SECONDS

    def test_empty_stdout_is_our_invocation_fault(self, seated: Path) -> None:
        """Exit 2: BAUD never ran, so nothing was captured."""
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(2, "", "usage")):
            with pytest.raises(host_fleet.FleetUnavailable) as caught:
                host_fleet.capture_room("api", "AIPASS")

        assert "invocation" in str(caught.value).lower()


class TestTheSendInvocation:
    """The typing command line — the one that reaches a live session."""

    def test_text_is_passed_as_a_single_argument(self, seated: Path) -> None:
        """
        A list, never a shell string.

        subprocess with a list never invokes a shell, so a semicolon in the
        text is a semicolon in the text. This is why the payload can be
        forwarded opaquely at all.
        """
        import json

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SENT))) as run:
            host_fleet.send_room("api", "AIPASS", "ls; rm -rf /", "")

        argv = run.call_args.args[0]
        assert argv[-2:] == ["--text", "ls; rm -rf /"]
        assert run.call_args.kwargs.get("shell") is None

    def test_a_key_is_sent_as_key_and_never_as_text(self, seated: Path) -> None:
        """Different flags, different tmux behaviour — never conflated."""
        import json

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SENT))) as run:
            host_fleet.send_room("api", "AIPASS", "", "C-c")

        argv = run.call_args.args[0]
        assert argv[-2:] == ["--key", "C-c"]
        assert "--text" not in argv

    def test_the_send_timeout_reaches_subprocess(self, seated: Path) -> None:
        """send-keys returns immediately; a long wait fixes nothing."""
        import json

        with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SENT))) as run:
            host_fleet.send_room("api", "AIPASS", "ls", "")

        assert run.call_args.kwargs["timeout"] == host_fleet.SEND_TIMEOUT_SECONDS

    def test_a_refusal_arrives_whole_rather_than_as_an_exception(self, seated: Path) -> None:
        """Exit 1 still carries an envelope, so their sentence survives."""
        import json

        refused = {**SENT, "sent": False, "detail": None, "error": "no room for branch 'api'"}
        with patch.object(host_fleet.subprocess, "run", return_value=_completed(1, json.dumps(refused))):
            envelope = host_fleet.send_room("api", "AIPASS", "ls", "")

        assert envelope["error"] == "no room for branch 'api'"


class TestThePayloadNeverReachesALog:
    """
    A pane is whatever is on Patrick's screen; typed text may be a password.

    Logging either would create a second, permanent copy in a place nobody
    chose — and this server's logs are not where a secret goes to live.
    """

    def test_the_pane_text_is_not_logged(self, seated: Path) -> None:
        """Its SIZE is the useful signal; its contents are nobody's business."""
        import json

        with patch(PATCH_FLEET_JSON) as recorder:
            with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(CAPTURED))):
                host_fleet.capture_room("api", "AIPASS")

        recorded = str(recorder.log_operation.call_args)
        assert "pytest" not in recorded
        assert "pane_chars" in recorded

    def test_the_typed_text_is_not_logged(self, seated: Path) -> None:
        """The password case, pinned."""
        import json

        with patch(PATCH_FLEET_JSON) as recorder:
            with patch.object(host_fleet.subprocess, "run", return_value=_completed(0, json.dumps(SENT))):
                host_fleet.send_room("api", "AIPASS", "hunter2-is-my-password", "")

        recorded = str(recorder.log_operation.call_args)
        assert "hunter2" not in recorded
        assert "text_chars" in recorded


# ==============================================
# ROUTES
# ==============================================


@pytest.fixture
def client(tmp_path: Path):
    """A test client over a temporary token store."""
    from fastapi.testclient import TestClient

    store = tmp_path / "secrets"
    with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
            with patch(PATCH_SERVER_JSON), patch(PATCH_FACE_JSON), patch(PATCH_FACE_LOGGER):
                with patch(PATCH_VERBS_JSON), patch(PATCH_VERBS_LOGGER):
                    with patch(PATCH_SEATED, return_value=PROJECT):
                        yield TestClient(host_server.create_app(), raise_server_exceptions=False)


@fastapi_required
class TestTheScopeSplitIsTheWholeUiStory:
    """
    Learning #389, which cost Patrick four "broken" features: a scope-refused UI
    is indistinguishable from breakage.

    The split is what lets @baud render the input row DISABLED with a reason
    rather than dead: a read token SEES the pane and cannot type into it. Both
    halves have to be true for that to work, so both are pinned.
    """

    def test_a_read_token_can_see_the_pane(self, client: Any) -> None:
        """The 95% case — 'is @api stuck' — must work on the weaker token."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_RESOLVE, return_value=Path("/tmp/b")):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            door.capture_room.return_value = dict(CAPTURED)
            response = client.get("/v1/room/pane?branch=api", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json()["pane"] == PANE_TEXT

    def test_a_read_token_cannot_type(self, client: Any) -> None:
        """403, so the client knows it is scope and not a fault."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        response = client.post(
            "/v1/verbs/keys",
            json={"branch": "api", "project": PROJECT_AS_SENT, "key": "Enter"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 403

    def test_a_read_token_never_reaches_the_send_door(self, client: Any) -> None:
        """The wall stops the mechanism, not just the response."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_VERBS_FLEET) as door:
            client.post(
                "/v1/verbs/keys",
                json={"branch": "api", "project": PROJECT_AS_SENT, "key": "Enter"},
                headers={"Authorization": f"Bearer {raw}"},
            )

            assert not door.send_room.called

    def test_the_pane_needs_a_token_at_all(self, client: Any) -> None:
        """It is a screen read — anonymous is not a scope."""
        response = client.get("/v1/room/pane?branch=api")

        assert response.status_code == 401

    def test_an_operate_token_can_do_both(self, client: Any) -> None:
        """Operate implies read, so the sheet works fully on Patrick's token."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_RESOLVE, return_value=Path("/tmp/b")):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            door.capture_room.return_value = dict(CAPTURED)
            door.send_room.return_value = dict(SENT)

            seen = client.get("/v1/room/pane?branch=api", headers={"Authorization": f"Bearer {raw}"})
            typed = client.post(
                "/v1/verbs/keys",
                json={"branch": "api", "project": PROJECT_AS_SENT, "text": "ls"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert (seen.status_code, typed.status_code) == (200, 200)


@fastapi_required
class TestTheTerminalRoutesMapStatusLikeTheVerbLane:
    """
    Refusal → 400 · unreachable mechanism → 503 · ran-and-said-no → 200 with
    ok false. The same three-way split, so a client learns one rule.
    """

    def test_a_bad_line_count_is_a_400(self, client: Any) -> None:
        """The caller's mistake, named as theirs."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        response = client.get(
            "/v1/room/pane?branch=api&lines=99999",
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400

    def test_a_missing_branch_is_a_400(self, client: Any) -> None:
        """No default target reaches the route layer too."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        response = client.get("/v1/room/pane", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 400

    def test_an_unreachable_binary_is_a_503(self, client: Any) -> None:
        """Nothing ran, so it is a status code rather than an ok."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_RESOLVE, return_value=Path("/tmp/b")):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            door.capture_room.side_effect = host_fleet.FleetUnavailable("baud is not available")
            response = client.get("/v1/room/pane?branch=api", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 503

    def test_a_refused_capture_is_a_200_carrying_ok_false(self, client: Any) -> None:
        """@baud ran and said no. Their sentence, rendered verbatim on the chip."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_RESOLVE, return_value=Path("/tmp/b")):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            door.capture_room.return_value = {"room": None, "pane": None, "detail": None, "error": "no room"}
            response = client.get("/v1/room/pane?branch=api", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["detail"] == "no room"

    def test_an_unknown_key_is_a_400_from_the_route(self, client: Any) -> None:
        """The allowlist bites through the full stack, not just in-process."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        with patch(PATCH_VERBS_FLEET) as door, patch(PATCH_RESOLVE, return_value=Path("/tmp/b")):
            door.FleetUnavailable = host_fleet.FleetUnavailable
            response = client.post(
                "/v1/verbs/keys",
                json={"branch": "api", "project": PROJECT_AS_SENT, "key": "C-z"},
                headers={"Authorization": f"Bearer {raw}"},
            )

            assert response.status_code == 400
            assert not door.send_room.called

    def test_the_pane_route_is_registered_as_a_read_not_a_verb(self) -> None:
        """
        `room_pane` read back off the app, by name and method.

        It sits at /v1/room/ rather than /v1/verbs/ on purpose: the verb route
        table has its own test asserting it holds exactly four things, and a
        read filed under verbs would either break that or quietly widen it.
        """
        app = host_server.create_app()
        routes = {
            route.path: (route.endpoint.__name__, set(route.methods))
            for route in app.routes
            # The trailing slash matters: "/v1/room" also prefixes "/v1/rooms",
            # which is the fleet lane's projection and nothing to do with this.
            if getattr(route, "path", "").startswith("/v1/room/")
        }

        assert routes == {"/v1/room/pane": ("room_pane", {"GET"})}

    def test_the_pane_is_not_reachable_by_post(self, client: Any) -> None:
        """A read is a GET. Method confusion is how a read becomes a write."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        response = client.post("/v1/room/pane", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 405

    def test_typing_is_not_reachable_by_get(self, client: Any) -> None:
        """Never something a browser can prefetch into a live session."""
        _, raw = host_tokens.issue_token("operator", scope="operate")

        response = client.get("/v1/verbs/keys", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 405
