#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_memory_config.py
# Description: Tests for the host API memory-config lane — @memory's rollover limits
# Version: 2.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
Tests for the Host API Memory Config Lane

The contract under test is @memory's, delivered 2026-08-16 through @devpulse
and MACHINE-READABLE since the same evening: five verbs, three entry types,
bounds 1-100, and `--json` on every one of them.

THE VERDICT IS `ok`, NOT THE EXIT CODE. Their branch-wide convention is that
refusals exit 0, so the code has never been the signal here — but until --json
landed the signal was a refusal glyph recovered from a rendered screen. Now it
is a boolean they emit. The class below keeps its name because the rule it
guards is unchanged; only the field it reads moved.

NOTHING HERE ROUTES A REAL COMMAND. Every test drives a stubbed
drone.route_command against the documents at the top of this file — real
captured stdout where a read could be run safely, and transcriptions of
@memory's own _emit call sites where producing one for real would mean WRITING
to Patrick's live limits. A suite that resets 17 branches to defaults to see
what the answer looks like is not a suite.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import memory_config as host_memory_config
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens


try:
    import fastapi  # noqa: F401

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

fastapi_required = pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="the [host] extra is not installed")

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.host.tokens.secrets_store.SECRETS_BASE"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler.log_operation"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler.log_operation"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_MEMORY_JSON = "aipass.api.apps.handlers.host.memory_config.json_handler.log_operation"


# @memory's --json documents. The first three are VERBATIM stdout, captured
# from their live verbs on 2026-08-16 — byte for byte, escapes and all, because
# a fixture retyped by hand tests my typing rather than their surface.
#
# The three write payloads and the populated OVERRIDES block are transcribed
# from @memory's own _emit call sites in rollover.py, for the reason that has
# governed this file since it shipped: producing them for real means WRITING
# Patrick's live limits, and a suite that resets 17 branches to see what the
# answer looks like is not a suite.
FLEET_JSON = (
    '{"ok": true, "verb": "config get", "defaults": {"sessions": {"count": 15, "auto_compact_cap": 3}, '
    '"key_learnings": {"count": 15}, "observations": {"count": 15}}, "overrides": {}}'
)

FLEET_WITH_OVERRIDES_JSON = (
    '{"ok": true, "verb": "config get", "defaults": {"sessions": {"count": 15, "auto_compact_cap": 3}, '
    '"key_learnings": {"count": 15}, "observations": {"count": 15}}, "overrides": '
    '{"devpulse": {"sessions": {"count": 25, "default_count": 15, "is_override": true, "source": "per_branch"}, '
    '"key_learnings": {"count": 30, "default_count": 15, "is_override": true, "source": "per_branch"}}, '
    '"memory": {"observations": {"count": 40, "default_count": 15, "is_override": true, '
    '"source": "per_branch"}}}}'
)

BRANCH_JSON = (
    '{"ok": true, "verb": "config get", "branch": "api", "limits": '
    '{"sessions": {"count": 15, "default_count": 15, "is_override": false, "source": "per_branch", '
    '"auto_compact_cap": 3}, "key_learnings": {"count": 25, "default_count": 15, "is_override": true, '
    '"source": "per_branch"}, "observations": {"count": 15, "default_count": 15, "is_override": false, '
    '"source": "per_branch"}}}'
)

# Their em-dash arrives \\u2014-escaped: _emit leaves ensure_ascii at its default
# so the write can never raise UnicodeEncodeError crossing a pipe of unknown
# locale. json.loads hands back the real character, and the assertions below
# key on the real one — which is the proof that this lane decodes rather than
# string-matches.
REFUSAL_JSON = (
    '{"ok": false, "verb": "config set", "error": "Count must not exceed 100 (got 999)", '
    '"suggestion": "100 is the cap \\u2014 larger limits defeat rollover entirely"}'
)

UNKNOWN_BRANCH_JSON = (
    '{"ok": false, "verb": "config get", "error": "Unknown branch: @nosuchbranch", '
    '"suggestion": "Registry is truth \\u2014 run \'drone systems\' to list branches"}'
)

# suggestion is null where a refusal genuinely has none — @memory's word, and
# the field is always present so a reader never has to test for its absence.
REFUSAL_WITHOUT_SUGGESTION_JSON = (
    '{"ok": false, "verb": "rollover push", "error": "Nothing to push — no defaults are configured", '
    '"suggestion": null}'
)

SET_OK_JSON = (
    '{"ok": true, "verb": "config set", "branch": "api", "entry_type": "sessions", "count": 25, "pushed": false}'
)

SET_DEFAULT_OK_JSON = (
    '{"ok": true, "verb": "config set-default", "entry_type": "sessions", "count": 25, "pushed": false}'
)

PUSH_OK_JSON = '{"ok": true, "verb": "rollover push", "branches": 17}'

# The human screen @memory prints WITHOUT --json, verbatim. A negative fixture
# only: it stands for the day this lane's --json stops being honoured, and no
# test here may recover a single field from it.
HUMAN_SCREEN = """
DEFAULTS (drone @memory config set-default <type> <count>)
  sessions       15  auto_compact_cap 3 (read-only)
  key_learnings  15
  observations   15

> All branches at defaults — no per-branch overrides
"""


def _result(stdout: str = "", stderr: str = "", exit_code: int = 0) -> MagicMock:
    """Build a fake drone CommandResult."""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.exit_code = exit_code
    return result


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the handler's own logging and trail out of the branch files."""
    monkeypatch.setattr(host_memory_config.logger, "info", lambda *a, **k: None)
    monkeypatch.setattr(host_memory_config.logger, "error", lambda *a, **k: None)
    monkeypatch.setattr(host_memory_config.json_handler, "log_operation", lambda *a, **k: True)


class TestTheExitCodeIsNeverTheVerdict:
    """
    @memory refuses with exit 0. Every guard here exists because of that.

    A handler that keyed success off the code would report a refused write as
    done, and the phone would show a limit that was never written.
    """

    def test_a_refusal_that_exited_zero_is_still_a_refusal(self) -> None:
        """ok:false decides, and it arrives on a process that exited 0."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(REFUSAL_JSON, exit_code=0)):
            with pytest.raises(host_memory_config.MemoryConfigRefused) as refused:
                host_memory_config.set_branch_limit("api", "sessions", 50)

        assert "Count must not exceed 100" in str(refused.value)

    def test_a_success_that_exited_nonzero_is_still_read_as_their_answer(self) -> None:
        """
        The mirror of the rule, and the reason it is stated as 'never'.

        A non-zero code on an ok:true document would be the router's noise, not
        @memory's verdict. Reading the code either way re-introduces exactly the
        guessing that --json removed.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_OK_JSON, exit_code=1)):
            answer = host_memory_config.set_branch_limit("api", "sessions", 25)

        assert answer["ok"] is True

    def test_their_suggestion_travels_with_their_message(self) -> None:
        """The suggestion is half the sentence — dropping it drops the fix."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(REFUSAL_JSON)):
            with pytest.raises(host_memory_config.MemoryConfigRefused) as refused:
                host_memory_config.set_branch_limit("api", "sessions", 50)

        assert "100 is the cap" in str(refused.value)

    def test_their_escaped_em_dash_arrives_as_the_character_they_typed(self) -> None:
        """
        Decoded, never string-matched.

        @memory escapes non-ASCII so the payload cannot raise crossing a pipe.
        A lane that grepped the raw document instead of parsing it would show
        the phone a literal backslash-u-2014 in the middle of their sentence.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(REFUSAL_JSON)):
            with pytest.raises(host_memory_config.MemoryConfigRefused) as refused:
                host_memory_config.set_branch_limit("api", "sessions", 50)

        assert "—" in str(refused.value)
        assert "\\u2014" not in str(refused.value)

    def test_a_refusal_with_no_suggestion_carries_only_the_sentence(self) -> None:
        """suggestion is null there, and null must not print as the word None."""
        with patch.object(
            host_memory_config.drone, "route_command", return_value=_result(REFUSAL_WITHOUT_SUGGESTION_JSON)
        ):
            with pytest.raises(host_memory_config.MemoryConfigRefused) as refused:
                host_memory_config.push_defaults()

        assert str(refused.value) == "Nothing to push — no defaults are configured"
        assert refused.value.suggestion is None

    def test_a_success_that_exited_zero_is_a_success(self) -> None:
        """The same exit code on the other answer. Only the text differs."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_OK_JSON)):
            answer = host_memory_config.set_branch_limit("api", "sessions", 25)

        assert answer["ok"] is True
        assert "sessions limit set to 25" in answer["detail"]

    def test_their_words_are_never_paraphrased(self) -> None:
        """D0 for a text lane: I carry their sentence, I do not rewrite it."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(UNKNOWN_BRANCH_JSON)):
            with pytest.raises(host_memory_config.MemoryConfigRefused) as refused:
                host_memory_config.set_branch_limit("api", "sessions", 25)

        assert "Unknown branch: @nosuchbranch" in str(refused.value)

    def test_the_raw_output_is_always_carried(self) -> None:
        """
        The parse can drift; the screen cannot.

        This lane reads a human screen, so every answer ships their stdout
        verbatim — if a heading changes and a field is lost, the truth is
        still in the envelope.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_OK_JSON)):
            answer = host_memory_config.set_branch_limit("api", "sessions", 25)

        assert answer["raw"].strip() == SET_OK_JSON.strip()


class TestReadingTheLimits:
    """The two read shapes: the fleet view and one branch's effective set."""

    def test_the_fleet_view_parses_the_defaults(self) -> None:
        """Three types, their counts, and the read-only cap where it appears."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(FLEET_JSON)):
            payload = host_memory_config.read_config()

        assert payload["scope"] == "fleet"
        assert payload["defaults"]["sessions"]["count"] == 15
        assert payload["defaults"]["sessions"]["auto_compact_cap"] == 3
        assert payload["defaults"]["key_learnings"]["auto_compact_cap"] is None

    def test_all_branches_at_defaults_is_an_empty_override_list(self) -> None:
        """
        Their sentence, not an empty block.

        @memory prints prose when nothing deviates. Reading that as 'could not
        parse' would show the phone a broken lane on the healthiest state.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(FLEET_JSON)):
            payload = host_memory_config.read_config()

        assert payload["overrides"] == []

    def test_deviating_branches_are_listed_with_their_rows(self) -> None:
        """Two branches, three deviating rows, each with the default alongside."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(FLEET_WITH_OVERRIDES_JSON)):
            payload = host_memory_config.read_config()

        assert [entry["branch"] for entry in payload["overrides"]] == ["devpulse", "memory"]
        assert payload["overrides"][0]["limits"][0]["type"] == "sessions"
        assert payload["overrides"][0]["limits"][0]["count"] == 25
        assert payload["overrides"][0]["limits"][0]["default"] == 15
        assert len(payload["overrides"][1]["limits"]) == 1

    def test_an_override_block_carries_only_the_rows_that_deviate(self) -> None:
        """
        @memory projects only deviating types into a branch's override entry.

        Listing all three would show @memory as deviating on sessions when only
        observations does — the fleet view's whole job is who differs, and how.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(FLEET_WITH_OVERRIDES_JSON)):
            payload = host_memory_config.read_config()

        assert [row["type"] for row in payload["overrides"][1]["limits"]] == ["observations"]
        assert all(row["is_override"] is True for entry in payload["overrides"] for row in entry["limits"])

    def test_the_defaults_never_take_a_number_from_an_override(self) -> None:
        """
        The two blocks are separate keys now, and this pins that they stay so.

        The screen-reading version could file @devpulse's 25 as the fleet
        default because both rows opened with an entry type; the documents
        cannot collide that way, and the assertion outlives the reason.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(FLEET_WITH_OVERRIDES_JSON)):
            payload = host_memory_config.read_config()

        assert payload["defaults"]["sessions"]["count"] == 15

    def test_a_branch_view_marks_each_row_default_or_override(self) -> None:
        """Default-or-override is the whole point of the branch view."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(BRANCH_JSON)):
            payload = host_memory_config.read_config(branch="api")

        assert payload["scope"] == "branch"
        assert payload["branch"] == "api"
        assert [row["type"] for row in payload["limits"]] == ["sessions", "key_learnings", "observations"]
        assert payload["limits"][0]["is_override"] is False
        assert payload["limits"][1]["is_override"] is True
        assert payload["limits"][1]["count"] == 25

    def test_the_rows_keep_memorys_own_order(self) -> None:
        """
        Their document is ordered; this lane publishes a list, so the order is
        a real decision. It is theirs — a list re-sorted here would put the
        phone's rows in an order @memory never chose.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(BRANCH_JSON)):
            payload = host_memory_config.read_config(branch="api")

        assert [row["type"] for row in payload["limits"]] == list(host_memory_config.ENTRY_TYPES)

    def test_an_entry_type_this_lane_has_never_heard_of_still_travels(self) -> None:
        """
        @memory owns the list of entry types, so a fourth one is theirs to add.

        Iterating a hardcoded triple here would silently drop it from the
        phone — the branch that owns the concept would ship a limit that this
        server, and only this server, refused to show.
        """
        with_todos = BRANCH_JSON.replace(
            '"observations": {"count": 15',
            '"todos": {"count": 7, "default_count": 7, "is_override": false, "source": "per_branch"}, '
            '"observations": {"count": 15',
        )
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(with_todos)):
            payload = host_memory_config.read_config(branch="api")

        assert [row["type"] for row in payload["limits"]] == [
            "sessions",
            "key_learnings",
            "todos",
            "observations",
        ]

    def test_the_read_only_cap_rides_the_row_it_belongs_to(self) -> None:
        """
        The cap is a field on its own row now, and only sessions carries one.

        @memory omits the key entirely where there is none; this lane publishes
        it as null, so the phone never has to test for a missing field to learn
        that key_learnings has no compaction cap.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(BRANCH_JSON)):
            payload = host_memory_config.read_config(branch="api")

        assert payload["limits"][0]["auto_compact_cap"] == 3
        assert payload["limits"][1]["auto_compact_cap"] is None

    def test_a_limit_that_is_not_configured_is_null_and_never_zero(self) -> None:
        """
        @memory's rule, carried unchanged: 0 would mean 'roll over everything
        immediately', which is the opposite of 'no limit is set'.
        """
        unset = BRANCH_JSON.replace('"key_learnings": {"count": 25', '"key_learnings": {"count": null')
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(unset)):
            payload = host_memory_config.read_config(branch="api")

        assert payload["limits"][1]["count"] is None

    def test_where_a_limit_came_from_reaches_the_caller(self) -> None:
        """
        source is theirs and new with --json — the screen never carried it in a
        form worth parsing. A settings face that shows an effective number
        should be able to say where it was resolved from.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(BRANCH_JSON)):
            payload = host_memory_config.read_config(branch="api")

        assert payload["limits"][0]["source"] == "per_branch"

    def test_the_branch_travels_with_an_at_sign_exactly_once(self) -> None:
        """Their verb wants @branch; a caller may or may not have typed one."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(BRANCH_JSON)) as route:
            host_memory_config.read_config(branch="@api")

        assert route.call_args.args[2][:2] == ["get", "@api"]

    def test_the_fleet_read_asks_for_no_branch(self) -> None:
        """An empty branch is the fleet view, not a branch named ''."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(FLEET_JSON)) as route:
            host_memory_config.read_config()

        assert route.call_args.args[2][0] == "get"
        assert "@" not in " ".join(route.call_args.args[2])

    def test_a_refused_read_is_refused_not_answered_empty(self) -> None:
        """
        An unknown branch has no rows, and no rows is not an answer.

        Returning an empty limit list would render as 'this branch has no
        limits', which is a different and false statement.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(UNKNOWN_BRANCH_JSON)):
            with pytest.raises(host_memory_config.MemoryConfigRefused) as excinfo:
                host_memory_config.read_config(branch="nosuchbranch")

        assert "Unknown branch" in str(excinfo.value)


class TestTheArgumentsAreCheckedBeforeAnythingIsRouted:
    """
    Bad input never becomes a routed command.

    @memory validates too and theirs is the ruling gate — this one exists so an
    obviously broken request costs no router round-trip and gets a 400 rather
    than a 200 carrying a refusal.
    """

    @pytest.mark.parametrize("value", [0, 101, -5, 1000])
    def test_a_count_outside_the_bounds_is_refused_here(self, value: int) -> None:
        """Their documented bounds are 1-100 inclusive."""
        with patch.object(host_memory_config.drone, "route_command") as route:
            with pytest.raises(host_memory_config.MemoryConfigRefused):
                host_memory_config.set_branch_limit("api", "sessions", value)

        route.assert_not_called()

    @pytest.mark.parametrize("value", [1, 100])
    def test_both_bounds_are_inclusive(self, value: int) -> None:
        """
        Off-by-one at either end would refuse a legal limit.

        The proof is that the value REACHED @memory. It used to be that the
        returned count echoed the argument, so asserting on it worked — the
        answer now carries @memory's echo of what they actually wrote, and
        asserting on that here would test the fixture rather than the bound.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_OK_JSON)) as route:
            host_memory_config.set_branch_limit("api", "sessions", value)

        assert route.call_args.args[2] == ["set", "@api", "sessions", str(value), host_memory_config.JSON_FLAG]

    @pytest.mark.parametrize("value", ["25", 25.0, None, True])
    def test_a_count_that_is_not_a_whole_number_is_refused(self, value: Any) -> None:
        """
        True is refused explicitly.

        Python calls a bool an int, so 'sessions True' would otherwise route as
        'sessions 1' — a limit nobody asked for, applied silently.
        """
        with patch.object(host_memory_config.drone, "route_command") as route:
            with pytest.raises(host_memory_config.MemoryConfigRefused):
                host_memory_config.set_branch_limit("api", "sessions", value)

        route.assert_not_called()

    def test_an_unknown_entry_type_is_refused_with_the_list(self) -> None:
        """A client guessing at a fourth type deserves the three that exist."""
        with pytest.raises(host_memory_config.MemoryConfigRefused) as excinfo:
            host_memory_config.set_branch_limit("api", "todos", 25)

        assert "sessions" in str(excinfo.value)
        assert "key_learnings" in str(excinfo.value)
        assert "observations" in str(excinfo.value)

    def test_a_missing_branch_is_refused(self) -> None:
        """set needs a branch; there is no 'current branch' from a phone."""
        with pytest.raises(host_memory_config.MemoryConfigRefused):
            host_memory_config.set_branch_limit("", "sessions", 25)

    def test_a_branch_name_carrying_shell_shapes_is_refused(self) -> None:
        """
        The router takes an argument list, not a shell line, so this is not an
        injection fence — it is a shape check that keeps a nonsense name from
        becoming a nonsense command.
        """
        with patch.object(host_memory_config.drone, "route_command") as route:
            with pytest.raises(host_memory_config.MemoryConfigRefused):
                host_memory_config.set_branch_limit("api; rm -rf /", "sessions", 25)

        route.assert_not_called()

    def test_whether_a_branch_exists_is_memorys_ruling(self) -> None:
        """
        A well-shaped unknown name IS routed.

        The registry is @memory's, and a second copy of it here would drift —
        their refusal is the right answer, not my guess at one.
        """
        with patch.object(
            host_memory_config.drone, "route_command", return_value=_result(UNKNOWN_BRANCH_JSON)
        ) as route:
            with pytest.raises(host_memory_config.MemoryConfigRefused):
                host_memory_config.set_branch_limit("nosuchbranch", "sessions", 25)

        route.assert_called_once()


class TestSetDefaultDoesNotPush:
    """@memory's documented consequence, surfaced rather than smoothed."""

    def test_the_answer_says_it_did_not_push(self) -> None:
        """
        set-default leaves per_branch alone, so all 17 branches keep their old
        numbers. A UI that does not know this shows a default that appears not
        to have worked.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_DEFAULT_OK_JSON)):
            answer = host_memory_config.set_default_limit("sessions", 25)

        assert answer["ok"] is True
        assert answer["pushed"] is False

    def test_pushed_is_reported_from_their_payload_not_from_a_constant_here(self) -> None:
        """
        THE test that separates reporting from remembering.

        This lane used to hardcode pushed:false, which was correct only for as
        long as @memory's semantics never changed — a fact about their branch,
        pinned in mine. They now emit it themselves, so a document saying the
        write DID push must come out of this lane saying so. A handler still
        writing the constant passes every other test in this class and fails
        this one.
        """
        pushed = SET_DEFAULT_OK_JSON.replace('"pushed": false', '"pushed": true')
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(pushed)):
            answer = host_memory_config.set_default_limit("sessions", 25)

        assert answer["pushed"] is True

    def test_a_branch_write_reports_pushed_too(self) -> None:
        """Their set payload carries the same fact, and it travels the same."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_OK_JSON)):
            answer = host_memory_config.set_branch_limit("api", "sessions", 25)

        assert answer["pushed"] is False

    def test_set_default_carries_no_branch(self) -> None:
        """It is the global verb — a branch here would be a different command."""
        with patch.object(
            host_memory_config.drone, "route_command", return_value=_result(SET_DEFAULT_OK_JSON)
        ) as route:
            host_memory_config.set_default_limit("sessions", 25)

        assert route.call_args.args[2][:3] == ["set-default", "sessions", "25"]

    def test_push_is_the_rollover_verb_not_a_config_one(self) -> None:
        """Push lives under rollover on their side. Same door, different verb."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(PUSH_OK_JSON)) as route:
            answer = host_memory_config.push_defaults()

        assert route.call_args.args[1] == "rollover"
        assert route.call_args.args[2][0] == "push"
        assert answer["ok"] is True

    def test_the_number_of_branches_reset_is_their_count_not_an_estimate(self) -> None:
        """
        A push answers with how many branches it touched. That number is the
        only evidence the reset was fleet-wide, and it is @memory's to state.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(PUSH_OK_JSON)):
            answer = host_memory_config.push_defaults()

        assert answer["branches"] == 17
        assert "17" in answer["detail"]


class TestTheMachineSurfaceIsWhatIsAsked:
    """
    Every verb is asked for --json, and the flag is what retires the scraper.

    A call that forgot it would get a rendered screen back and — because the
    screen no longer parses here at all — turn a perfectly good answer into a
    503. These five assertions are cheap and they fail loudly.
    """

    @pytest.mark.parametrize(
        "call",
        [
            lambda: host_memory_config.read_config(),
            lambda: host_memory_config.read_config(branch="api"),
            lambda: host_memory_config.set_branch_limit("api", "sessions", 25),
            lambda: host_memory_config.set_default_limit("sessions", 25),
            lambda: host_memory_config.push_defaults(),
        ],
        ids=["fleet-read", "branch-read", "set", "set-default", "push"],
    )
    def test_every_verb_asks_for_the_machine_surface(self, call: Any) -> None:
        """All five, by @memory's own list."""
        answers = {
            "get": FLEET_JSON,
            "set": SET_OK_JSON,
            "set-default": SET_DEFAULT_OK_JSON,
            "push": PUSH_OK_JSON,
        }

        def answer(_target: str, _command: str, args: list, **_kwargs: Any) -> MagicMock:
            if args[0] == "get" and len(args) > 1 and args[1].startswith("@"):
                return _result(BRANCH_JSON)
            return _result(answers[args[0]])

        with patch.object(host_memory_config.drone, "route_command", side_effect=answer) as route:
            call()

        assert host_memory_config.JSON_FLAG in route.call_args.args[2]

    def test_the_flag_rides_last_and_never_displaces_a_positional(self) -> None:
        """
        @memory strips it from any slot, so last is a choice rather than a
        requirement — but a flag inserted mid-list would be the kind of thing
        that only breaks against an older build, silently.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_OK_JSON)) as route:
            host_memory_config.set_branch_limit("api", "sessions", 25)

        assert route.call_args.args[2] == ["set", "@api", "sessions", "25", host_memory_config.JSON_FLAG]


class TestAScreenIsNotAnAnswer:
    """
    Anything that is not one parseable document is a 503, never a verdict.

    This is the failure mode the whole switch introduces: if --json ever stops
    being honoured — an older @memory on a fresh clone, a flag they rename, a
    banner printed ahead of the payload — this lane gets prose back. Prose must
    fail as unreachable, because 'I cannot tell whether the write happened' is
    the honest answer and a 200 is not.
    """

    def test_a_routing_error_is_unavailable(self) -> None:
        """Unreachable is not the same as refused, and must not read as one."""
        with patch.object(
            host_memory_config.drone, "route_command", side_effect=host_memory_config.drone.RoutingError("no route")
        ):
            with pytest.raises(host_memory_config.MemoryConfigUnavailable):
                host_memory_config.read_config()

    def test_the_human_screen_is_not_parsed_for_anything(self) -> None:
        """
        The old fixture, now a negative one.

        Every field the scraper used to recover is still sitting in this text.
        Recovering one would be a second reading of @memory's config living on
        past the day it was retired.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(HUMAN_SCREEN)):
            with pytest.raises(host_memory_config.MemoryConfigUnavailable) as excinfo:
                host_memory_config.read_config()

        assert "did not answer" in str(excinfo.value)

    def test_a_screen_never_reads_as_a_completed_write(self) -> None:
        """The same rule where it costs the most: a write of unknown outcome."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(HUMAN_SCREEN)):
            with pytest.raises(host_memory_config.MemoryConfigUnavailable):
                host_memory_config.set_branch_limit("api", "sessions", 25)

    def test_silence_is_unavailable_not_success(self) -> None:
        """No stdout, no stderr, exit 0 — and no basis for saying it worked."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result("")):
            with pytest.raises(host_memory_config.MemoryConfigUnavailable):
                host_memory_config.push_defaults()

    def test_a_document_that_is_not_an_object_is_unavailable(self) -> None:
        """Valid JSON is not the bar. A list has no ok to read."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result("[1, 2, 3]")):
            with pytest.raises(host_memory_config.MemoryConfigUnavailable):
                host_memory_config.read_config()

    def test_a_document_with_no_verdict_is_unavailable(self) -> None:
        """
        ok is the verdict, so a document without one has not given a verdict.

        Defaulting a missing ok to true would make every malformed answer a
        success; defaulting it to false would invent a refusal @memory never
        spoke. Neither is available, so neither is guessed.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result('{"verb": "config get"}')):
            with pytest.raises(host_memory_config.MemoryConfigUnavailable):
                host_memory_config.read_config()

    def test_what_actually_arrived_travels_with_the_failure(self) -> None:
        """
        Whoever debugs this at 2am needs the bytes, not the word 'unparseable'.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result("not json at all")):
            with pytest.raises(host_memory_config.MemoryConfigUnavailable) as excinfo:
                host_memory_config.read_config()

        assert "not json at all" in str(excinfo.value)

    def test_stderr_is_read_when_stdout_is_empty(self) -> None:
        """
        @memory writes zero bytes to stderr, verified on their side before they
        shipped it. The fallback stays anyway: it costs nothing, and the day a
        router wraps their payload onto the other stream, one document on the
        wrong pipe is still an answer.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result("", REFUSAL_JSON)):
            with pytest.raises(host_memory_config.MemoryConfigRefused) as refused:
                host_memory_config.set_branch_limit("api", "sessions", 50)

        assert "Count must not exceed 100" in str(refused.value)
        assert refused.value.raw.strip() == REFUSAL_JSON.strip()


@fastapi_required
class TestTheMemoryConfigRoutes:
    """The HTTP surface: reads are read scope, every write is operate."""

    @pytest.fixture
    def client(self, tmp_path):
        """A TestClient over the real app with an isolated token store."""
        from fastapi.testclient import TestClient

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
            with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
                yield TestClient(host_server.create_app(), raise_server_exceptions=False)

    @pytest.fixture
    def read_auth(self, client) -> dict:
        """A read-scope bearer against the isolated store."""
        _, raw = host_tokens.issue_token("memory-config-read", scope="read")
        return {"Authorization": f"Bearer {raw}"}

    @pytest.fixture
    def operate_auth(self, client) -> dict:
        """An operate-scope bearer against the isolated store."""
        _, raw = host_tokens.issue_token("memory-config-operate", scope="operate")
        return {"Authorization": f"Bearer {raw}"}

    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/v1/memory-config"),
            ("post", "/v1/memory-config/set"),
            ("post", "/v1/memory-config/set-default"),
            ("post", "/v1/memory-config/push"),
        ],
    )
    def test_every_route_requires_a_token(self, client, method: str, path: str) -> None:
        """Limits are fleet configuration. Not public, not on any verb."""
        assert getattr(client, method)(path).status_code == 401

    def test_the_read_serves_the_fleet_view(self, client, read_auth: dict) -> None:
        """Read scope is enough to look."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(FLEET_JSON)):
            response = client.get("/v1/memory-config", headers=read_auth)

        assert response.status_code == 200
        assert response.json()["defaults"]["sessions"]["count"] == 15

    def test_the_read_serves_one_branch(self, client, read_auth: dict) -> None:
        """The branch travels as a query parameter, like every other read here."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(BRANCH_JSON)):
            response = client.get("/v1/memory-config?branch=api", headers=read_auth)

        assert response.status_code == 200
        assert response.json()["branch"] == "api"

    @pytest.mark.parametrize(
        "path,payload",
        [
            ("/v1/memory-config/set", {"branch": "api", "type": "sessions", "count": 25}),
            ("/v1/memory-config/set-default", {"type": "sessions", "count": 25}),
            ("/v1/memory-config/push", {}),
        ],
    )
    def test_a_read_token_cannot_write(self, client, read_auth: dict, path: str, payload: dict) -> None:
        """
        Reading limits and changing them fleet-wide are different powers.

        A phone enrolled to watch must not be able to reset every branch's
        memory to defaults.
        """
        with patch.object(host_memory_config.drone, "route_command") as route:
            response = client.post(path, json=payload, headers=read_auth)

        assert response.status_code == 403
        route.assert_not_called()

    def test_a_bad_count_is_400_and_never_routed(self, client, operate_auth: dict) -> None:
        """The caller got it wrong before @memory was ever asked."""
        with patch.object(host_memory_config.drone, "route_command") as route:
            response = client.post(
                "/v1/memory-config/set",
                json={"branch": "api", "type": "sessions", "count": 999},
                headers=operate_auth,
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "memory_config_refused"
        route.assert_not_called()

    def test_a_successful_write_answers_ok(self, client, operate_auth: dict) -> None:
        """The happy path, through the whole request stack."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(SET_OK_JSON)):
            response = client.post(
                "/v1/memory-config/set",
                json={"branch": "api", "type": "sessions", "count": 25},
                headers=operate_auth,
            )

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "detail": "@api sessions limit set to 25",
            "raw": SET_OK_JSON.strip(),
            "branch": "api",
            "type": "sessions",
            "count": 25,
            "pushed": False,
        }

    def test_push_needs_no_body(self, client, operate_auth: dict) -> None:
        """It takes no arguments, so a body would be a field nobody reads."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(PUSH_OK_JSON)):
            response = client.post("/v1/memory-config/push", headers=operate_auth)

        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_an_unreachable_memory_is_503(self, client, read_auth: dict) -> None:
        """Unavailable, with a reason — never an empty limit set."""
        with patch.object(
            host_memory_config.drone,
            "route_command",
            side_effect=host_memory_config.drone.RoutingError("no route"),
        ):
            response = client.get("/v1/memory-config", headers=read_auth)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "memory_config_unavailable"


class TestARefusalIsOneShapeWhereverItHappens:
    """
    One fact, one place to read it.

    Found by @baud reading the handler and confirmed by devpulse on the wire
    (2026-08-16): a well-formed body naming a branch @memory does not have came
    back 200 with ok=false, while a body that failed my own bounds check came
    back 400. Same outcome — the write was refused, nothing changed — but the
    client had to check the status code AND a flag to learn it.

    The split was not even consistent inside this module: read_config already
    raised on a refusal from the same source. I made the right call once and did
    not carry it through, and the reason the shape leaked is written into the
    fixture names here so it does not re-form.

    The rule now: a refusal is 400 memory_config_refused with their sentence,
    whether it was caught here or spoken by @memory. 503 stays what it was —
    @memory could not be reached at all.
    """

    @pytest.fixture
    def client(self, tmp_path):
        """A TestClient over the real app with an isolated token store."""
        from fastapi.testclient import TestClient

        with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
            with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
                yield TestClient(host_server.create_app(), raise_server_exceptions=False)

    @pytest.fixture
    def operate_auth(self, client) -> dict:
        """An operate-scope bearer against the isolated store."""
        _, raw = host_tokens.issue_token("memory-config-operate", scope="operate")
        return {"Authorization": f"Bearer {raw}"}

    def test_the_unknown_branch_that_started_this_is_a_400(self, client, operate_auth: dict) -> None:
        """The exact request devpulse sent on the wire. It answered 200 then."""
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(UNKNOWN_BRANCH_JSON)):
            response = client.post(
                "/v1/memory-config/set",
                json={"branch": "nosuchbranch", "type": "sessions", "count": 5},
                headers=operate_auth,
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "memory_config_refused"
        assert "Unknown branch: @nosuchbranch" in response.json()["error"]["message"]

    def test_before_and_after_routing_answer_identically(self, client, operate_auth: dict) -> None:
        """
        THE point of the fix, stated as one assertion.

        A count of 0 never leaves this server; an unknown branch is refused by
        @memory. Two refusals from opposite ends of the pipeline, one shape.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(UNKNOWN_BRANCH_JSON)):
            after = client.post(
                "/v1/memory-config/set",
                json={"branch": "nosuchbranch", "type": "sessions", "count": 5},
                headers=operate_auth,
            )
        with patch.object(host_memory_config.drone, "route_command"):
            before = client.post(
                "/v1/memory-config/set",
                json={"branch": "api", "type": "sessions", "count": 0},
                headers=operate_auth,
            )

        assert after.status_code == before.status_code == 400
        assert after.json()["error"]["code"] == before.json()["error"]["code"]

    def test_no_write_route_can_answer_200_with_ok_false(self, client, operate_auth: dict) -> None:
        """
        The guard against the shape re-forming on a route added later.

        Every write, refused by @memory, across the whole lane. If someone adds
        a fourth write verb and returns the answer dict straight through, this
        is what fails.
        """
        calls = [
            ("/v1/memory-config/set", {"branch": "api", "type": "sessions", "count": 25}),
            ("/v1/memory-config/set-default", {"type": "sessions", "count": 25}),
            ("/v1/memory-config/push", {}),
        ]

        for path, payload in calls:
            with patch.object(host_memory_config.drone, "route_command", return_value=_result(REFUSAL_JSON)):
                response = client.post(path, json=payload, headers=operate_auth)

            assert response.status_code == 400, path
            assert response.json()["error"]["code"] == "memory_config_refused", path

    def test_a_refused_push_never_reads_as_a_completed_reset(self, client, operate_auth: dict) -> None:
        """
        Push is the fleet-wide one, so a false 'done' costs the most here.

        It also has no arguments to validate, which means before this fix it was
        the one write with NO path to a 400 at all.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(REFUSAL_JSON)):
            response = client.post("/v1/memory-config/push", headers=operate_auth)

        assert response.status_code == 400
        assert "ok" not in response.json()

    def test_their_whole_payload_survives_the_refusal(self, client, operate_auth: dict) -> None:
        """
        The raw document must not be the price of the better status code.

        Every answer carries their stdout verbatim, and a refusal is exactly
        where this lane's reading of it is most likely to be the thing that is
        wrong.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(UNKNOWN_BRANCH_JSON)):
            response = client.post(
                "/v1/memory-config/set",
                json={"branch": "nosuchbranch", "type": "sessions", "count": 5},
                headers=operate_auth,
            )

        assert response.json()["error"]["raw"].strip() == UNKNOWN_BRANCH_JSON.strip()

    def test_their_remedy_line_reaches_the_phone_as_its_own_field(self, client, operate_auth: dict) -> None:
        """
        A suggestion joined into one sentence can only be rendered as one.

        @memory emits it separately, so a face that wants to show the fix on
        its own line — or as a button — does not have to split their prose back
        apart on a dash it does not own.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(UNKNOWN_BRANCH_JSON)):
            response = client.post(
                "/v1/memory-config/set",
                json={"branch": "nosuchbranch", "type": "sessions", "count": 5},
                headers=operate_auth,
            )

        assert response.json()["error"]["suggestion"] == "Registry is truth — run 'drone systems' to list branches"

    def test_a_refusal_decided_here_offers_no_suggestion_it_did_not_get(self, client, operate_auth: dict) -> None:
        """
        The other half of one-shape: the field is present and null.

        A bounds check on this side has no remedy line from @memory, and
        inventing one would put words in their mouth on a screen that reads as
        theirs. Present-and-null is the honest shape, and it means the phone
        renders both halves of the rule the same way.
        """
        with patch.object(host_memory_config.drone, "route_command") as route:
            response = client.post(
                "/v1/memory-config/set",
                json={"branch": "api", "type": "sessions", "count": 999},
                headers=operate_auth,
            )

        route.assert_not_called()
        assert response.json()["error"]["suggestion"] is None

    def test_unreachable_is_still_a_503_and_not_swept_in(self, client, operate_auth: dict) -> None:
        """
        The distinction that must NOT be unified.

        Refused and unreachable are different facts: one says the write was
        considered and declined, the other says nobody was home.
        """
        with patch.object(
            host_memory_config.drone,
            "route_command",
            side_effect=host_memory_config.drone.RoutingError("no route"),
        ):
            response = client.post("/v1/memory-config/push", headers=operate_auth)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "memory_config_unavailable"

    def test_a_refusal_carries_no_pushed_field_to_misread(self, client, operate_auth: dict) -> None:
        """
        set-default's pushed=false means 'changed the default, branches wait'.

        On a REFUSED set-default there is no default change to describe, so the
        field must not ride along — false there would read as a true statement
        about a write that never happened.
        """
        with patch.object(host_memory_config.drone, "route_command", return_value=_result(REFUSAL_JSON)):
            response = client.post(
                "/v1/memory-config/set-default",
                json={"type": "sessions", "count": 25},
                headers=operate_auth,
            )

        assert response.status_code == 400
        assert "pushed" not in response.json()
        assert "pushed" not in response.json()["error"]
