# =================== AIPass ====================
# Name: test_config_verbs_json.py
# Description: The config verbs' --json machine surface - one document on stdout, payloads, in-band refusals
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/modules/rollover_json.py — the `--json` surface of the config and rollover verbs."""

# Split from test_config_verbs.py on 2026-10-08 (oversize_test_file): the JSON
# lane, one subject - what `config ... --json` and `rollover push --json` put on
# stdout (@api reads this instead of the screen): exactly one parseable
# document, the payload shapes, every refusal in band as ok:false carrying the
# sentence the human path prints, and the flag honoured in any slot.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the human-path refusal sentences, tests/test_config_verbs_refusals.py

import json
from types import SimpleNamespace

import pytest

from aipass.memory.tests.support_config_verbs import (
    _payload,
    _raw_stdout,
    _rollover_section,
    _run,
    _run_rollover,
    _streams,
    _unwrapped,
)


def _payload_rollover(verbs: SimpleNamespace, capsys: pytest.CaptureFixture, *args: str) -> dict:
    """Same, for the `rollover` verb."""
    capsys.readouterr()
    _run_rollover(verbs, *args)
    return json.loads(capsys.readouterr().out)


# ===========================================================================
# 7. --json -- the machine surface (@api reads this instead of the screen)
# ===========================================================================


class TestJsonIsOneDocumentOnStdout:
    """stdout in JSON mode is ONE parseable document and nothing else.

    Not "contains JSON somewhere". A banner, a trailing decorative line or
    a Rich wrap inside a long string value would each make json.loads()
    fail on the whole stream -- which is exactly what @api's parser does.
    """

    @pytest.mark.parametrize(
        ("args", "verb"),
        [
            (("get", "--json"), "config get"),
            (("get", "@memory", "--json"), "config get"),
            (("set", "@memory", "sessions", "12", "--json"), "config set"),
            (("set-default", "sessions", "12", "--json"), "config set-default"),
            (("set", "@wizard", "sessions", "12", "--json"), "config set"),
            # `reset` is the one verb whose document does not name itself -- it
            # reports the bare "config". Pinned as MEASURED, not as wished: the
            # wire string is @api's to renegotiate, not a test's to assume.
            (("reset", "--json"), "config"),
        ],
    )
    def test_whole_stdout_parses(self, verbs, capsys, args, verb) -> None:
        payload = _payload(verbs, capsys, *args)
        assert set(payload) >= {"ok", "verb"}, payload
        assert payload["verb"] == verb, payload["verb"]

    @pytest.mark.parametrize(
        "args",
        [
            ("get", "--json"),
            ("get", "@memory", "--json"),
            ("set", "@memory", "sessions", "12", "--json"),
            ("set-default", "sessions", "12", "--json"),
            ("set", "@wizard", "sessions", "12", "--json"),
        ],
    )
    def test_exactly_one_line(self, verbs, capsys, args) -> None:
        """One document, one terminating newline -- no blank lines, no panels."""
        assert _raw_stdout(verbs, capsys, *args).count("\n") == 1

    def test_stderr_is_silent_on_a_refusal(self, verbs, capsys) -> None:
        """A JSON refusal is IN BAND -- nothing leaks onto the error stream."""
        capsys.readouterr()
        _run(verbs, "set", "@wizard", "sessions", "12", "--json")
        assert capsys.readouterr().err == ""

    def test_push_stdout_parses(self, verbs, capsys) -> None:
        payload = _payload_rollover(verbs, capsys, "push", "--json")
        assert set(payload) >= {"ok", "verb"}, payload
        assert payload["verb"] == "rollover push", payload["verb"]

    def test_human_path_emits_no_json(self, verbs, capsys) -> None:
        """Without the flag the surface is unchanged -- rendered, not parseable."""
        out = _raw_stdout(verbs, capsys, "get")
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)


class TestJsonGetPayload:
    """`config get --json` -- defaults plus only the branches that deviate."""

    def test_ok_and_verb(self, verbs, capsys) -> None:
        payload = _payload(verbs, capsys, "get", "--json")
        assert payload["ok"] is True
        assert payload["verb"] == "config get"

    def test_defaults_carry_the_three_types_and_todos(self, verbs, capsys) -> None:
        defaults = _payload(verbs, capsys, "get", "--json")["defaults"]
        assert set(defaults) == {"sessions", "key_learnings", "observations", "todos"}

    def test_default_counts(self, verbs, capsys) -> None:
        defaults = _payload(verbs, capsys, "get", "--json")["defaults"]
        assert defaults["sessions"]["count"] == 15
        assert defaults["key_learnings"]["count"] == 15
        assert defaults["observations"]["count"] == 15

    def test_auto_compact_cap_is_on_sessions_only(self, verbs, capsys) -> None:
        defaults = _payload(verbs, capsys, "get", "--json")["defaults"]
        assert defaults["sessions"]["auto_compact_cap"] == 3
        assert "auto_compact_cap" not in defaults["key_learnings"]
        assert "auto_compact_cap" not in defaults["observations"]

    def test_overrides_empty_when_all_at_defaults(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "get", "--json")["overrides"] == {}

    def test_a_deviating_branch_appears(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        assert "memory" in _payload(verbs, capsys, "get", "--json")["overrides"]

    def test_non_deviating_branches_are_absent(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        assert "devpulse" not in _payload(verbs, capsys, "get", "--json")["overrides"]

    def test_override_row_shape(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        row = _payload(verbs, capsys, "get", "--json")["overrides"]["memory"]["sessions"]
        assert row == {"count": 12, "default_count": 15, "is_override": True, "source": "per_branch"}

    def test_only_deviating_types_are_listed(self, verbs, capsys) -> None:
        """Same rule the rendered OVERRIDES block applies -- one notion of override."""
        _run(verbs, "set", "@memory", "sessions", "12")
        assert set(_payload(verbs, capsys, "get", "--json")["overrides"]["memory"]) == {"sessions"}


class TestJsonGetBranchPayload:
    """`config get @branch --json` -- the EFFECTIVE limits, per file key."""

    def test_ok_verb_and_branch(self, verbs, capsys) -> None:
        payload = _payload(verbs, capsys, "get", "@memory", "--json")
        assert payload["ok"] is True
        assert payload["verb"] == "config get"
        assert payload["branch"] == "memory"

    def test_branch_key_is_lowercased(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "get", "@DAEMON", "--json")["branch"] == "daemon"

    def test_the_three_types_and_todos_present(self, verbs, capsys) -> None:
        limits = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]
        assert set(limits) == {"sessions", "key_learnings", "observations", "todos"}

    def test_default_row_shape(self, verbs, capsys) -> None:
        row = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]["sessions"]
        assert row == {
            "count": 15,
            "default_count": 15,
            "is_override": False,
            "source": "per_branch",
            "auto_compact_cap": 3,
        }

    def test_override_is_reported(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        row = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]["sessions"]
        assert row["count"] == 12
        assert row["default_count"] == 15
        assert row["is_override"] is True

    def test_cap_absent_from_types_that_have_none(self, verbs, capsys) -> None:
        limits = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]
        assert "auto_compact_cap" not in limits["key_learnings"]
        assert "auto_compact_cap" not in limits["observations"]

    def test_count_is_null_when_no_limit_is_configured(self, verbs, capsys) -> None:
        """Never invent a number: report what the engine actually enforces.

        A per_branch entry carrying only `sessions` leaves key_learnings
        with NO limit -- the lookup is per FILE KEY. A payload that said 15
        would be claiming enforcement that does not happen.
        """
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        raw["rollover"]["per_branch"]["memory"] = {"local": {"sessions": {"count": 22}}}
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        limits = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]
        assert limits["key_learnings"]["count"] is None
        assert limits["sessions"]["count"] == 22
        assert limits["observations"]["source"] == "defaults"


class TestJsonWritePayloads:
    """`set` / `set-default` / `rollover push` report what they did."""

    def test_set_payload(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "set", "@memory", "sessions", "12", "--json") == {
            "ok": True,
            "verb": "config set",
            "branch": "memory",
            "entry_type": "sessions",
            "count": 12,
            "pushed": False,
        }

    def test_set_actually_wrote(self, verbs, capsys) -> None:
        _payload(verbs, capsys, "set", "@memory", "sessions", "12", "--json")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 12

    def test_set_branch_is_lowercased_in_the_payload(self, verbs, capsys) -> None:
        payload = _payload(verbs, capsys, "set", "@DAEMON", "sessions", "12", "--json")
        assert payload["branch"] == "daemon"

    def test_set_default_payload(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "set-default", "sessions", "12", "--json") == {
            "ok": True,
            "verb": "config set-default",
            "entry_type": "sessions",
            "count": 12,
            "pushed": False,
        }

    def test_set_default_pushed_false_is_the_truth(self, verbs, capsys) -> None:
        """`pushed: false` is a fact about the file, not a decoration."""
        before = _rollover_section(verbs)["per_branch"]
        payload = _payload(verbs, capsys, "set-default", "sessions", "12", "--json")
        assert payload["pushed"] is False
        assert _rollover_section(verbs)["per_branch"] == before

    def test_push_payload(self, verbs, capsys) -> None:
        payload = _payload_rollover(verbs, capsys, "push", "--json")
        assert payload["ok"] is True
        assert payload["verb"] == "rollover push"
        assert payload["branches"] == len(_rollover_section(verbs)["per_branch"])

    def test_push_actually_reset_the_branch(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        _payload_rollover(verbs, capsys, "push", "--json")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 15


class TestJsonRefusals:
    """Every refusal is ok:false carrying the SAME sentence as the screen.

    `ok` is the whole point of the flag: refusals exit 0 branch-wide, so a
    machine caller cannot infer failure from an exit code and used to have
    to infer it from output shape.
    """

    # One row per refusal path the config verbs own.
    _CASES = [
        ("set", "@wizard", "sessions", "12"),
        ("set", "@WiZaRd", "sessions", "12"),
        ("get", "@wizard"),
        ("set", "@memory", "foo", "12"),
        ("set-default", "todos", "12"),
        ("set", "@memory", "sessions", "abc"),
        ("set", "@memory", "sessions", "12.5"),
        ("set", "@memory", "sessions", "0"),
        ("set", "@memory", "sessions", "-5"),
        ("set", "@memory", "sessions", "500"),
        ("set", "@memory"),
        ("set",),
        ("set-default", "sessions"),
        ("set-default",),
        ("reset",),
    ]
    # seedgo SHORT-TABLE (2026-08-31): a non-empty parametrize is not a count
    # guard - a row silently dropped from _CASES still leaves every surviving
    # case green. Pin the count so a shrink is loud.
    assert len(_CASES) == 15

    @pytest.mark.parametrize("args", _CASES)
    def test_ok_is_false(self, verbs, capsys, args) -> None:
        assert _payload(verbs, capsys, *args, "--json")["ok"] is False

    @pytest.mark.parametrize("args", _CASES)
    def test_verb_is_stamped(self, verbs, capsys, args) -> None:
        assert _payload(verbs, capsys, *args, "--json")["verb"].startswith("config")

    @pytest.mark.parametrize("args", _CASES)
    def test_error_matches_the_human_sentence(self, verbs, capsys, args) -> None:
        """Read the sentence from ONE place -- the payload -- then find it on screen.

        Hardcoding it here twice would let the two surfaces drift while
        both suites stayed green.
        """
        payload = _payload(verbs, capsys, *args, "--json")
        capsys.readouterr()
        _run(verbs, *args)
        assert payload["error"] in _streams(capsys)

    @pytest.mark.parametrize("args", _CASES)
    def test_suggestion_matches_the_human_sentence(self, verbs, capsys, args) -> None:
        payload = _payload(verbs, capsys, *args, "--json")
        assert payload["suggestion"].strip() != ""
        capsys.readouterr()
        _run(verbs, *args)
        assert payload["suggestion"] in _streams(capsys)

    @pytest.mark.parametrize("args", _CASES)
    def test_refusal_writes_nothing(self, verbs, capsys, args) -> None:
        before = verbs.path.read_bytes()
        _payload(verbs, capsys, *args, "--json")
        assert verbs.path.read_bytes() == before

    def test_unknown_branch_echoes_what_was_typed(self, verbs, capsys) -> None:
        payload = _payload(verbs, capsys, "set", "@WiZaRd", "sessions", "12", "--json")
        assert payload["error"] == "Unknown branch: @WiZaRd"

    def test_unknown_subcommand_verb_is_the_root(self, verbs, capsys) -> None:
        """There is no valid subcommand to name, so the payload says `config`."""
        assert _payload(verbs, capsys, "reset", "--json")["verb"] == "config"


class TestJsonUnreadableConfigRefusal:
    """The one refusal with no remedy line -- suggestion is explicitly null."""

    def _break_the_file(self, verbs) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")

    def test_set_is_refused(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        payload = _payload(verbs, capsys, "set", "@memory", "sessions", "12", "--json")
        assert payload["ok"] is False
        assert payload["verb"] == "config set"

    def test_suggestion_key_is_present_and_null(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        payload = _payload(verbs, capsys, "set", "@memory", "sessions", "12", "--json")
        assert "suggestion" in payload
        assert payload["suggestion"] is None

    def test_error_matches_the_human_sentence(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        payload = _payload(verbs, capsys, "set-default", "sessions", "12", "--json")
        capsys.readouterr()
        _run(verbs, "set-default", "sessions", "12")
        assert _unwrapped(payload["error"]) in _unwrapped(_streams(capsys))

    def test_bytes_unchanged(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        before = verbs.path.read_bytes()
        _payload(verbs, capsys, "set", "@memory", "sessions", "12", "--json")
        assert verbs.path.read_bytes() == before

    def test_push_is_refused_too(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        payload = _payload_rollover(verbs, capsys, "push", "--json")
        assert payload["ok"] is False
        assert payload["verb"] == "rollover push"
        assert payload["suggestion"] is None

    def test_rollover_unknown_subcommand_is_refused(self, verbs, capsys) -> None:
        payload = _payload_rollover(verbs, capsys, "nonexistent", "--json")
        assert payload["ok"] is False
        assert payload["verb"] == "rollover"
        assert payload["error"] == "Unknown subcommand: 'nonexistent'"


class TestJsonSurvivesRich:
    """The payload must never travel through Rich. Two ways it gets ruined.

    1. The shared console is width-80 with is_terminal=False, so it wraps a
       long document -- a wrap landing inside a string value inserts a
       newline INTO the value.
    2. It parses markup, so a `[...]` token inside a string is eaten as a
       style name (that is how @daemon's lowercase [skip] markers vanished
       from the screen while the tests on the returned string stayed green).

    Both are invisible to a test that asserts on the string handed to the
    printer. These assert on what reached the pipe.
    """

    def test_a_long_refusal_arrives_unwrapped(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        raw = _raw_stdout(verbs, capsys, "set", "@memory", "sessions", "12", "--json")

        assert len(raw) > 150, "the guard is worthless unless the payload exceeds the console width"
        assert raw.count("\n") == 1
        assert json.loads(raw)["error"].startswith(f"Config at {verbs.path}")

    def test_no_newline_hides_inside_any_string_value(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        payload = _payload(verbs, capsys, "set", "@memory", "sessions", "12", "--json")
        strings = {key: value for key, value in payload.items() if isinstance(value, str)}
        assert set(strings) == {"verb", "error"}, strings
        for key, value in strings.items():
            assert "\n" not in value, key

    def test_emitter_round_trips_a_long_payload(self, verbs, capsys) -> None:
        document = {"ok": False, "verb": "config set", "error": "x" * 400, "suggestion": None}
        verbs.rollover._emit(document)
        assert json.loads(capsys.readouterr().out) == document

    def test_payload_bytes_are_ascii_safe(self, verbs, capsys) -> None:
        """The wire stays pure ASCII; the em-dash survives the round trip.

        The refusal sentences carry em-dashes and a machine caller execs
        this under a locale we do not control. Escaping them means the
        write can never raise UnicodeEncodeError, and json.loads hands back
        the exact character regardless.
        """
        raw = _raw_stdout(verbs, capsys, "set", "@wizard", "sessions", "12", "--json")
        raw.encode("ascii")  # raises if a literal em-dash reached the pipe
        assert "—" in json.loads(raw)["suggestion"]

    def test_emitter_does_not_eat_markup_tokens(self, verbs, capsys) -> None:
        document = {"ok": False, "verb": "config set", "error": "a [dim] and a [skip] must both survive"}
        verbs.rollover._emit(document)
        assert json.loads(capsys.readouterr().out) == document


class TestJsonFlagPosition:
    """`--json` rides in any slot, exactly like the help flag."""

    _EXPECTED = {
        "ok": True,
        "verb": "config set",
        "branch": "memory",
        "entry_type": "sessions",
        "count": 12,
        "pushed": False,
    }

    @pytest.mark.parametrize(
        "args",
        [
            ("set", "@memory", "sessions", "12", "--json"),
            ("set", "@memory", "sessions", "--json", "12"),
            ("set", "@memory", "--json", "sessions", "12"),
            ("set", "--json", "@memory", "sessions", "12"),
            ("--json", "set", "@memory", "sessions", "12"),
        ],
    )
    def test_payload_is_identical(self, verbs, capsys, args) -> None:
        assert _payload(verbs, capsys, *args) == self._EXPECTED

    @pytest.mark.parametrize(
        "args",
        [
            ("set", "@memory", "sessions", "12", "--json"),
            ("set", "--json", "@memory", "sessions", "12"),
            ("--json", "set", "@memory", "sessions", "12"),
        ],
    )
    def test_the_write_still_lands(self, verbs, capsys, args) -> None:
        _payload(verbs, capsys, *args)
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 12

    def test_push_flag_before_the_subcommand(self, verbs, capsys) -> None:
        assert _payload_rollover(verbs, capsys, "--json", "push")["verb"] == "rollover push"

    def test_bare_json_flag_introspects_rather_than_crashing(self, verbs, capsys) -> None:
        """Stripping the only token must not leave the parser holding nothing."""
        assert _run(verbs, "--json") is True
        assert "set-default" in _streams(capsys)

    def test_bare_json_flag_on_rollover_introspects(self, verbs, capsys) -> None:
        assert _run_rollover(verbs, "--json") is True
        assert "report-lines" in _streams(capsys)
