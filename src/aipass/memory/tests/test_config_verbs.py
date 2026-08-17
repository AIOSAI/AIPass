# =================== AIPass ====================
# Name: test_config_verbs.py
# Description: Tests for the `config` verbs (rollover limit get/set/set-default)
# Version: 1.1.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
Tests for `drone @memory config` -- the verb surface over rollover limits.

DPLAN-0302. The CLI output and the refusal sentences ARE the API contract
(@api exec's this CLI to serve BAUD's memory-settings screen), so these
tests pin the exact sentences, not merely "an error happened".

Covers:
  - Every refusal sentence, message AND suggestion, verbatim
  - `set @branch <type> <count>` lands in per_branch and reads back as an override
  - `set-default` writes defaults and leaves per_branch untouched
  - Round-trip: set -> `rollover push` returns the branch to defaults
  - Effective limits resolve per FILE KEY exactly like detector._should_rollover
    (a deep merge would report a limit the engine does not enforce)
  - auto_compact_cap survives a `sessions` set (never dropped, never settable)
  - A help flag in ANY slot prints help and leaves the file byte-identical
  - A malformed config is refused, not clobbered (bytes unchanged)
  - Bounds: 0, negative, 101, non-numeric
  - Rich actually renders the [DEFAULT] / [OVERRIDE] markers on screen
    (a lowercase [default] tag is eaten by Rich's markup parser while the
    source string still reads correctly -- the assertion must see the screen)
  - `--json`: EXACTLY one parseable document on stdout per verb, every
    refusal as ok:false carrying the same sentence the human path prints,
    the flag honoured in any slot, and --help still outranking it

Isolation: the live memory_json/custom_config/memory.config.json is COPIED
into tmp_path and config_loader._CONFIG_PATH is repointed at the copy. These
tests write limits; a suite that edited the fleet config would be the exact
accident these verbs exist to prevent.
"""

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# The live operator config -- read (copied) here, NEVER written by this suite.
_LIVE_CONFIG = Path(__file__).resolve().parents[1] / "memory_json" / "custom_config" / "memory.config.json"

_HANDLER_MODULES = (
    "aipass.memory.apps.handlers.json",
    "aipass.memory.apps.handlers.json.json_handler",
    "aipass.memory.apps.handlers.json.config_loader",
)


# ---------------------------------------------------------------------------
# Fixture: real modules, throwaway config
# ---------------------------------------------------------------------------


@pytest.fixture
def verbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real config_loader + rollover module wired to a copy of the live config.

    conftest replaces the handlers.json package with a MagicMock, which would
    make the lazy `from ... import config_loader` inside the module return a
    mock instead of the code under test. Popping it forces a real import.
    """
    # Rich wraps at the detected width; long refusal sentences carry a tmp path,
    # so widen the console or the exact-sentence assertions test line wrapping.
    monkeypatch.setenv("COLUMNS", "300")

    for name in _HANDLER_MODULES:
        sys.modules.pop(name, None)
    config_loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")

    config_path = tmp_path / "custom_config" / "memory.config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(_LIVE_CONFIG.read_bytes())

    monkeypatch.setattr(config_loader, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(config_loader, "json_handler", MagicMock())

    sys.modules.pop("aipass.memory.apps.modules.rollover", None)
    rollover = importlib.import_module("aipass.memory.apps.modules.rollover")
    monkeypatch.setattr(rollover, "json_handler", MagicMock())

    detector = importlib.import_module("aipass.memory.apps.handlers.monitor.detector")
    monkeypatch.setattr(detector, "config_loader", config_loader)

    return SimpleNamespace(
        rollover=rollover,
        loader=config_loader,
        detector=detector,
        path=config_path,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(verbs: SimpleNamespace, *args: str) -> bool:
    """Invoke `config <args>` exactly as the entry point routes it."""
    return verbs.rollover.handle_command("config", list(args))


def _streams(capsys: pytest.CaptureFixture) -> str:
    """Both streams joined -- refusals go to stderr, displays to stdout."""
    captured = capsys.readouterr()
    return captured.out + captured.err


def _run_rollover(verbs: SimpleNamespace, *args: str) -> bool:
    """Invoke `rollover <args>` exactly as the entry point routes it."""
    return verbs.rollover.handle_command("rollover", list(args))


def _rollover_section(verbs: SimpleNamespace) -> dict:
    """Read the rollover section straight off the throwaway file."""
    return json.loads(verbs.path.read_text(encoding="utf-8"))["rollover"]


def _raw_stdout(verbs: SimpleNamespace, capsys: pytest.CaptureFixture, *args: str) -> str:
    """Run `config <args>` and return stdout EXACTLY as it reached the pipe."""
    capsys.readouterr()
    _run(verbs, *args)
    return capsys.readouterr().out


def _payload(verbs: SimpleNamespace, capsys: pytest.CaptureFixture, *args: str) -> dict:
    """Run `config <args>` and parse the WHOLE of stdout as one document.

    Deliberately not a substring search: a banner line, a stray trailing
    blank or a Rich-injected wrap all make json.loads fail right here --
    which is the contract, because @api pipes this straight into a parser.
    """
    return json.loads(_raw_stdout(verbs, capsys, *args))


def _payload_rollover(verbs: SimpleNamespace, capsys: pytest.CaptureFixture, *args: str) -> dict:
    """Same, for the `rollover` verb."""
    capsys.readouterr()
    _run_rollover(verbs, *args)
    return json.loads(capsys.readouterr().out)


# ===========================================================================
# 1. Refusal sentences -- the API contract, verbatim
# ===========================================================================


class TestUnknownBranchRefusal:
    """Registry is truth; an unknown branch never reaches the writer."""

    def test_set_unknown_branch_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@wizard", "sessions", "25")
        assert "Unknown branch: @wizard" in _streams(capsys)

    def test_set_unknown_branch_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@wizard", "sessions", "25")
        assert "Registry is truth — run 'drone systems' to list branches" in _streams(capsys)

    def test_get_unknown_branch_refuses(self, verbs, capsys) -> None:
        _run(verbs, "get", "@wizard")
        assert "Unknown branch: @wizard" in _streams(capsys)

    def test_unknown_branch_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@wizard", "sessions", "25")
        assert verbs.path.read_bytes() == before

    def test_refusal_echoes_the_branch_as_typed(self, verbs, capsys) -> None:
        """Echo what the operator typed -- not a normalized form they never used."""
        _run(verbs, "set", "@WiZaRd", "sessions", "25")
        assert "Unknown branch: @WiZaRd" in _streams(capsys)


class TestUnknownTypeRefusal:
    """Only three entry types map onto a rollover limit key."""

    def test_set_unknown_type_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "foo", "25")
        assert "Unknown entry type: 'foo'" in _streams(capsys)

    def test_set_unknown_type_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "foo", "25")
        assert "Valid types: sessions, key_learnings, observations" in _streams(capsys)

    def test_set_default_unknown_type_message(self, verbs, capsys) -> None:
        _run(verbs, "set-default", "todos", "25")
        assert "Unknown entry type: 'todos'" in _streams(capsys)

    def test_unknown_type_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "foo", "25")
        assert verbs.path.read_bytes() == before


class TestCountRefusals:
    """A limit is a whole number in [1, 100] -- everything else is refused."""

    def test_non_numeric_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "abc")
        assert "Count must be a whole number: 'abc'" in _streams(capsys)

    def test_non_numeric_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "abc")
        assert "Example: drone @memory config set @devpulse sessions 25" in _streams(capsys)

    def test_decimal_is_not_a_whole_number(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12.5")
        assert "Count must be a whole number: '12.5'" in _streams(capsys)

    def test_zero_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "0")
        assert "Count must be at least 1 (got 0)" in _streams(capsys)

    def test_zero_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "0")
        assert "A limit of 0 would roll over every entry immediately" in _streams(capsys)

    def test_negative_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "-5")
        assert "Count must be at least 1 (got -5)" in _streams(capsys)

    def test_above_cap_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "500")
        assert "Count must not exceed 100 (got 500)" in _streams(capsys)

    def test_above_cap_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "500")
        assert "100 is the cap — larger limits defeat rollover entirely" in _streams(capsys)

    def test_one_hundred_and_one_is_over(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "101")
        assert "Count must not exceed 100 (got 101)" in _streams(capsys)

    def test_bounds_are_inclusive(self, verbs) -> None:
        """1 and 100 are legal -- the refusal is for what lies outside."""
        assert _run(verbs, "set", "@memory", "sessions", "1") is True
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 1
        assert _run(verbs, "set", "@memory", "sessions", "100") is True
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 100

    def test_bad_count_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "0")
        assert verbs.path.read_bytes() == before


class TestMissingArgumentRefusals:
    """Half a command is a question, not an instruction."""

    def test_set_missing_args_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory")
        assert "config set needs: @branch <type> <count>" in _streams(capsys)

    def test_set_missing_args_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set")
        assert "Example: drone @memory config set @devpulse sessions 25" in _streams(capsys)

    def test_set_default_missing_args_message(self, verbs, capsys) -> None:
        _run(verbs, "set-default", "sessions")
        assert "config set-default needs: <type> <count>" in _streams(capsys)

    def test_set_default_missing_args_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set-default")
        assert "Example: drone @memory config set-default sessions 25" in _streams(capsys)


class TestUnknownSubcommandRefusal:
    """`config` owns three verbs and names them when asked for a fourth."""

    def test_message(self, verbs, capsys) -> None:
        _run(verbs, "reset")
        assert "Unknown subcommand: 'reset'" in _streams(capsys)

    def test_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "reset")
        assert "Available: get, set, set-default" in _streams(capsys)

    def test_still_handled(self, verbs) -> None:
        assert _run(verbs, "reset") is True


class TestUnreadableConfigRefusal:
    """A file we cannot parse may be one comma from correct -- never clobber it."""

    def test_message_on_set(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        _run(verbs, "set", "@memory", "sessions", "25")
        expected = f"Config at {verbs.path} is unreadable — fix or move it aside, then try again"
        assert expected in _streams(capsys)

    def test_message_on_set_default(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        _run(verbs, "set-default", "sessions", "25")
        expected = f"Config at {verbs.path} is unreadable — fix or move it aside, then try again"
        assert expected in _streams(capsys)

    def test_bytes_unchanged(self, verbs) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "25")
        assert verbs.path.read_bytes() == before

    def test_wrong_shape_is_also_refused(self, verbs, capsys) -> None:
        """Valid JSON, wrong type -- same no-clobber path as malformed."""
        verbs.path.write_text('["a", "list"]', encoding="utf-8")
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "25")
        assert "is unreadable — fix or move it aside, then try again" in _streams(capsys)
        assert verbs.path.read_bytes() == before


# ===========================================================================
# 2. Writes that land
# ===========================================================================


class TestSetBranchLimit:
    """`config set @branch <type> <count>` writes rollover.per_branch."""

    def test_sessions_lands_in_per_branch(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 25

    def test_key_learnings_lands_in_per_branch(self, verbs) -> None:
        _run(verbs, "set", "@memory", "key_learnings", "42")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["key_learnings"]["count"] == 42

    def test_observations_lands_in_its_own_file_key(self, verbs) -> None:
        _run(verbs, "set", "@memory", "observations", "7")
        per_branch = _rollover_section(verbs)["per_branch"]["memory"]
        assert per_branch["observations"]["observations"]["count"] == 7

    def test_reads_back_as_an_override(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 25
        assert limits["sessions"]["is_override"] is True

    def test_untouched_types_stay_default(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["key_learnings"]["is_override"] is False

    def test_branch_matching_is_case_insensitive(self, verbs) -> None:
        """The registry carries DAEMON uppercase; per_branch keys are lowercase."""
        assert _run(verbs, "set", "@DAEMON", "sessions", "25") is True
        assert _rollover_section(verbs)["per_branch"]["daemon"]["local"]["sessions"]["count"] == 25

    def test_write_key_is_always_lowercase(self, verbs) -> None:
        _run(verbs, "set", "@DAEMON", "sessions", "25")
        assert "DAEMON" not in _rollover_section(verbs)["per_branch"]

    def test_bare_branch_name_without_at_works(self, verbs) -> None:
        _run(verbs, "set", "memory", "sessions", "33")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 33

    def test_defaults_untouched_by_a_branch_set(self, verbs) -> None:
        before = _rollover_section(verbs)["defaults"]
        _run(verbs, "set", "@memory", "sessions", "25")
        assert _rollover_section(verbs)["defaults"] == before

    def test_other_branches_untouched(self, verbs) -> None:
        before = _rollover_section(verbs)["per_branch"]["devpulse"]
        _run(verbs, "set", "@memory", "sessions", "25")
        assert _rollover_section(verbs)["per_branch"]["devpulse"] == before

    def test_other_config_sections_survive(self, verbs) -> None:
        before = json.loads(verbs.path.read_text(encoding="utf-8"))["entry_limits"]
        _run(verbs, "set", "@memory", "sessions", "25")
        after = json.loads(verbs.path.read_text(encoding="utf-8"))["entry_limits"]
        assert after == before


class TestWriteDoesNotReencodeTheFile:
    """A one-limit edit must not rewrite every non-ASCII character in the file.

    _write_config_file used json.dumps' default ensure_ascii=True while the
    operator's file (and every other JSON writer on this branch) holds literal
    UTF-8. One `config set` therefore turned every em-dash into \\u2014 -- a
    whole-file diff carrying no change, on the file BAUD shows the operator.
    """

    def test_em_dashes_stay_literal(self, verbs) -> None:
        assert "—" in verbs.path.read_text(encoding="utf-8")
        _run(verbs, "set", "@memory", "sessions", "25")
        after = verbs.path.read_text(encoding="utf-8")
        assert "—" in after
        assert "\\u2014" not in after

    def test_a_no_op_set_is_byte_identical(self, verbs) -> None:
        """Setting a limit to the value it already holds changes nothing."""
        current = _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"]
        before = verbs.path.read_bytes()
        _run(verbs, "set", "@memory", "sessions", str(current))
        assert verbs.path.read_bytes() == before


class TestAutoCompactCapPreserved:
    """auto_compact_cap is not settable in v1 but must never be dropped."""

    def test_survives_a_sessions_set(self, verbs) -> None:
        before = _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["auto_compact_cap"]
        _run(verbs, "set", "@memory", "sessions", "25")
        after = _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["auto_compact_cap"]
        assert after == before

    def test_survives_a_default_set(self, verbs) -> None:
        before = _rollover_section(verbs)["defaults"]["local"]["sessions"]["auto_compact_cap"]
        _run(verbs, "set-default", "sessions", "25")
        after = _rollover_section(verbs)["defaults"]["local"]["sessions"]["auto_compact_cap"]
        assert after == before

    def test_exposed_read_only_by_get(self, verbs) -> None:
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["auto_compact_cap"] == 3


class TestSeedingANewBranchEntry:
    """A branch with no per_branch entry gets the materialize_per_branch shape."""

    def test_seeded_entry_carries_the_note(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        raw["rollover"]["per_branch"].pop("memory", None)
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        _run(verbs, "set", "@memory", "sessions", "25")

        entry = _rollover_section(verbs)["per_branch"]["memory"]
        assert entry["_note"] == "Limits for @memory. Manual edits persist until next push."

    def test_seeded_entry_carries_the_other_limits(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        raw["rollover"]["per_branch"].pop("memory", None)
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        _run(verbs, "set", "@memory", "sessions", "25")

        entry = _rollover_section(verbs)["per_branch"]["memory"]
        assert entry["local"]["key_learnings"]["count"] == 15
        assert entry["observations"]["observations"]["count"] == 15
        assert entry["local"]["sessions"]["auto_compact_cap"] == 3


class TestSetDefault:
    """`config set-default` writes defaults and DOES NOT touch per_branch."""

    def test_writes_defaults(self, verbs) -> None:
        _run(verbs, "set-default", "sessions", "40")
        assert _rollover_section(verbs)["defaults"]["local"]["sessions"]["count"] == 40

    def test_leaves_per_branch_untouched(self, verbs) -> None:
        before = _rollover_section(verbs)["per_branch"]
        _run(verbs, "set-default", "sessions", "40")
        assert _rollover_section(verbs)["per_branch"] == before

    def test_observations_default(self, verbs) -> None:
        _run(verbs, "set-default", "observations", "9")
        assert _rollover_section(verbs)["defaults"]["observations"]["observations"]["count"] == 9

    def test_default_note_survives(self, verbs) -> None:
        before = _rollover_section(verbs)["defaults"]["_note"]
        _run(verbs, "set-default", "sessions", "40")
        assert _rollover_section(verbs)["defaults"]["_note"] == before

    def test_raising_the_default_turns_a_materialized_branch_into_an_override(self, verbs) -> None:
        """Marking is BY VALUE: the branch did not move, the default did."""
        _run(verbs, "set-default", "sessions", "40")
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 15
        assert limits["sessions"]["is_override"] is True


class TestPushRoundTrip:
    """set -> push must return the branch to defaults. Push is THE reset."""

    def test_set_then_push_restores_defaults(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 25

        result = verbs.loader.push_defaults_to_per_branch()
        assert result["success"] is True

        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 15
        assert limits["sessions"]["is_override"] is False

    def test_push_via_the_rollover_verb_also_restores(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        verbs.rollover.handle_command("rollover", ["push"])
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 15


# ===========================================================================
# 3. Effective-limit semantics -- must mirror detector._should_rollover
# ===========================================================================


class TestEffectiveLimitsPerFileKey:
    """The lookup is per FILE KEY, not per leaf key, and not a deep merge.

    detector._should_rollover reads per_branch[branch][file_type] and falls
    back to defaults[file_type] ONLY when that whole dict is absent. So a
    per_branch entry carrying only `sessions` leaves key_learnings with NO
    limit -- a deep merge would claim 15 and the engine would enforce none.
    """

    def _plant_partial_local(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        raw["rollover"]["per_branch"]["memory"] = {"local": {"sessions": {"count": 30}}}
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def test_partial_file_key_does_not_deep_merge(self, verbs) -> None:
        self._plant_partial_local(verbs)
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 30
        assert limits["key_learnings"]["count"] is None

    def test_absent_file_key_falls_back_to_defaults(self, verbs) -> None:
        self._plant_partial_local(verbs)
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["observations"]["count"] == 15
        assert limits["observations"]["source"] == "defaults"

    def test_source_is_reported(self, verbs) -> None:
        self._plant_partial_local(verbs)
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["source"] == "per_branch"

    def test_matches_the_detector_on_a_real_file(self, verbs, tmp_path) -> None:
        """The engine is the oracle: what get says must be what rollover does."""
        self._plant_partial_local(verbs)

        trinity = tmp_path / "memory" / ".trinity"
        trinity.mkdir(parents=True)
        local = trinity / "local.json"
        local.write_text(
            json.dumps(
                {
                    "sessions": [{"number": i, "summary": "s"} for i in range(20)],
                    "key_learnings": [{"number": i, "value": "k"} for i in range(99)],
                }
            ),
            encoding="utf-8",
        )

        should, _lines, _schema, reason = verbs.detector._should_rollover(local)

        # 20 sessions >= 30? No. 99 key_learnings has NO limit at all.
        assert "key_learnings" not in reason
        assert should is False
        assert verbs.loader.get_effective_limits("memory")["key_learnings"]["count"] is None


# ===========================================================================
# 4. Display -- rendered through Rich, not asserted on source strings
# ===========================================================================


class TestGetDisplay:
    """`config get` prints defaults plus only the branches that deviate."""

    def test_all_at_defaults_says_so(self, verbs, capsys) -> None:
        _run(verbs, "get")
        assert "All branches at defaults" in _streams(capsys)

    def test_defaults_block_shows_the_three_types(self, verbs, capsys) -> None:
        _run(verbs, "get")
        out = _streams(capsys)
        for entry_type in ("sessions", "key_learnings", "observations"):
            assert entry_type in out

    def test_a_deviating_branch_is_listed(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        capsys.readouterr()
        _run(verbs, "get")
        out = _streams(capsys)
        assert "@memory" in out
        assert "All branches at defaults" not in out

    def test_non_deviating_branches_are_not_listed(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        capsys.readouterr()
        _run(verbs, "get")
        assert "@devpulse" not in _streams(capsys)


class TestBranchDisplayMarkers:
    """Rich eats a lowercase [default] tag silently -- assert on the SCREEN.

    Learned live by @daemon: console.print() parses markup, so the source
    string can read perfectly while the terminal shows nothing at all.
    """

    def test_default_marker_survives_rich(self, verbs, capsys) -> None:
        _run(verbs, "get", "@memory")
        assert "[DEFAULT]" in _streams(capsys)

    def test_override_marker_survives_rich(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        capsys.readouterr()
        _run(verbs, "get", "@memory")
        assert "[OVERRIDE]" in _streams(capsys)

    def test_override_row_shows_both_numbers(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        capsys.readouterr()
        _run(verbs, "get", "@memory")
        out = _streams(capsys)
        assert "25" in out
        assert "15" in out

    def test_get_branch_lists_all_three_types(self, verbs, capsys) -> None:
        _run(verbs, "get", "@memory")
        out = _streams(capsys)
        for entry_type in ("sessions", "key_learnings", "observations"):
            assert entry_type in out


# ===========================================================================
# 5. A help flag is never an instruction
# ===========================================================================


class TestHelpNeverWrites:
    """The `rollover push --help` scar: a question must not be executed."""

    @pytest.mark.parametrize(
        "args",
        [
            ("set", "@memory", "sessions", "25", "--help"),
            ("set", "@memory", "sessions", "--help", "25"),
            ("set", "--help", "@memory", "sessions", "25"),
            ("--help", "set", "@memory", "sessions", "25"),
            ("set", "@memory", "sessions", "25", "-h"),
            ("set", "@memory", "sessions", "25", "help"),
            ("set-default", "sessions", "25", "--help"),
        ],
    )
    def test_file_is_byte_identical(self, verbs, args) -> None:
        before = verbs.path.read_bytes()
        assert _run(verbs, *args) is True
        assert verbs.path.read_bytes() == before

    def test_help_is_actually_printed(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25", "--help")
        out = _streams(capsys)
        assert "set-default" in out
        assert "USAGE" in out


class TestIntrospectionAndHelp:
    """Seedgo standard: bare verb introspects, --help documents."""

    def test_no_args_returns_true(self, verbs) -> None:
        assert _run(verbs) is True

    def test_no_args_prints_introspection(self, verbs, capsys) -> None:
        _run(verbs)
        out = _streams(capsys)
        assert "config" in out
        assert "get" in out
        assert "set-default" in out

    def test_no_args_writes_nothing(self, verbs) -> None:
        before = verbs.path.read_bytes()
        _run(verbs)
        assert verbs.path.read_bytes() == before

    def test_help_flag_prints_help(self, verbs, capsys) -> None:
        _run(verbs, "--help")
        assert "USAGE" in _streams(capsys)

    def test_help_documents_the_bounds(self, verbs, capsys) -> None:
        _run(verbs, "--help")
        out = _streams(capsys)
        assert "1" in out and "100" in out

    def test_help_documents_that_set_default_does_not_push(self, verbs, capsys) -> None:
        _run(verbs, "--help")
        assert "per_branch" in _streams(capsys)

    def test_bare_help_word_prints_help(self, verbs, capsys) -> None:
        _run(verbs, "help")
        assert "USAGE" in _streams(capsys)


# ===========================================================================
# 6. The live config is never touched by this suite
# ===========================================================================


class TestLiveConfigIsolation:
    """A test that edited the fleet config would be the accident, not the guard."""

    def test_config_path_is_repointed(self, verbs) -> None:
        assert verbs.loader._CONFIG_PATH != _LIVE_CONFIG

    def test_live_config_bytes_unchanged_by_a_set(self, verbs) -> None:
        before = _LIVE_CONFIG.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "25")
        _run(verbs, "set-default", "sessions", "40")
        assert _LIVE_CONFIG.read_bytes() == before

    def test_live_config_bytes_unchanged_by_json_mode(self, verbs) -> None:
        before = _LIVE_CONFIG.read_bytes()
        _run(verbs, "set", "@memory", "sessions", "25", "--json")
        _run(verbs, "set-default", "sessions", "40", "--json")
        _run_rollover(verbs, "push", "--json")
        assert _LIVE_CONFIG.read_bytes() == before


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
        "args",
        [
            ("get", "--json"),
            ("get", "@memory", "--json"),
            ("set", "@memory", "sessions", "25", "--json"),
            ("set-default", "sessions", "25", "--json"),
            ("set", "@wizard", "sessions", "25", "--json"),
            ("reset", "--json"),
        ],
    )
    def test_whole_stdout_parses(self, verbs, capsys, args) -> None:
        assert isinstance(_payload(verbs, capsys, *args), dict)

    @pytest.mark.parametrize(
        "args",
        [
            ("get", "--json"),
            ("get", "@memory", "--json"),
            ("set", "@memory", "sessions", "25", "--json"),
            ("set-default", "sessions", "25", "--json"),
            ("set", "@wizard", "sessions", "25", "--json"),
        ],
    )
    def test_exactly_one_line(self, verbs, capsys, args) -> None:
        """One document, one terminating newline -- no blank lines, no panels."""
        assert _raw_stdout(verbs, capsys, *args).count("\n") == 1

    def test_stderr_is_silent_on_a_refusal(self, verbs, capsys) -> None:
        """A JSON refusal is IN BAND -- nothing leaks onto the error stream."""
        capsys.readouterr()
        _run(verbs, "set", "@wizard", "sessions", "25", "--json")
        assert capsys.readouterr().err == ""

    def test_push_stdout_parses(self, verbs, capsys) -> None:
        assert isinstance(_payload_rollover(verbs, capsys, "push", "--json"), dict)

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

    def test_defaults_carry_all_three_types(self, verbs, capsys) -> None:
        defaults = _payload(verbs, capsys, "get", "--json")["defaults"]
        assert set(defaults) == {"sessions", "key_learnings", "observations"}

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
        _run(verbs, "set", "@memory", "sessions", "25")
        assert "memory" in _payload(verbs, capsys, "get", "--json")["overrides"]

    def test_non_deviating_branches_are_absent(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        assert "devpulse" not in _payload(verbs, capsys, "get", "--json")["overrides"]

    def test_override_row_shape(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        row = _payload(verbs, capsys, "get", "--json")["overrides"]["memory"]["sessions"]
        assert row == {"count": 25, "default_count": 15, "is_override": True, "source": "per_branch"}

    def test_only_deviating_types_are_listed(self, verbs, capsys) -> None:
        """Same rule the rendered OVERRIDES block applies -- one notion of override."""
        _run(verbs, "set", "@memory", "sessions", "25")
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

    def test_all_three_types_present(self, verbs, capsys) -> None:
        limits = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]
        assert set(limits) == {"sessions", "key_learnings", "observations"}

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
        _run(verbs, "set", "@memory", "sessions", "25")
        row = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]["sessions"]
        assert row["count"] == 25
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
        raw["rollover"]["per_branch"]["memory"] = {"local": {"sessions": {"count": 30}}}
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        limits = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]
        assert limits["key_learnings"]["count"] is None
        assert limits["sessions"]["count"] == 30
        assert limits["observations"]["source"] == "defaults"


class TestJsonWritePayloads:
    """`set` / `set-default` / `rollover push` report what they did."""

    def test_set_payload(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "set", "@memory", "sessions", "25", "--json") == {
            "ok": True,
            "verb": "config set",
            "branch": "memory",
            "entry_type": "sessions",
            "count": 25,
            "pushed": False,
        }

    def test_set_actually_wrote(self, verbs, capsys) -> None:
        _payload(verbs, capsys, "set", "@memory", "sessions", "25", "--json")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 25

    def test_set_branch_is_lowercased_in_the_payload(self, verbs, capsys) -> None:
        payload = _payload(verbs, capsys, "set", "@DAEMON", "sessions", "25", "--json")
        assert payload["branch"] == "daemon"

    def test_set_default_payload(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "set-default", "sessions", "25", "--json") == {
            "ok": True,
            "verb": "config set-default",
            "entry_type": "sessions",
            "count": 25,
            "pushed": False,
        }

    def test_set_default_pushed_false_is_the_truth(self, verbs, capsys) -> None:
        """`pushed: false` is a fact about the file, not a decoration."""
        before = _rollover_section(verbs)["per_branch"]
        payload = _payload(verbs, capsys, "set-default", "sessions", "40", "--json")
        assert payload["pushed"] is False
        assert _rollover_section(verbs)["per_branch"] == before

    def test_push_payload(self, verbs, capsys) -> None:
        payload = _payload_rollover(verbs, capsys, "push", "--json")
        assert payload["ok"] is True
        assert payload["verb"] == "rollover push"
        assert payload["branches"] == len(_rollover_section(verbs)["per_branch"])

    def test_push_actually_reset_the_branch(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
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
        ("set", "@wizard", "sessions", "25"),
        ("set", "@WiZaRd", "sessions", "25"),
        ("get", "@wizard"),
        ("set", "@memory", "foo", "25"),
        ("set-default", "todos", "25"),
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
        assert payload["suggestion"] is not None
        capsys.readouterr()
        _run(verbs, *args)
        assert payload["suggestion"] in _streams(capsys)

    @pytest.mark.parametrize("args", _CASES)
    def test_refusal_writes_nothing(self, verbs, capsys, args) -> None:
        before = verbs.path.read_bytes()
        _payload(verbs, capsys, *args, "--json")
        assert verbs.path.read_bytes() == before

    def test_unknown_branch_echoes_what_was_typed(self, verbs, capsys) -> None:
        payload = _payload(verbs, capsys, "set", "@WiZaRd", "sessions", "25", "--json")
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
        payload = _payload(verbs, capsys, "set", "@memory", "sessions", "25", "--json")
        assert payload["ok"] is False
        assert payload["verb"] == "config set"

    def test_suggestion_key_is_present_and_null(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        payload = _payload(verbs, capsys, "set", "@memory", "sessions", "25", "--json")
        assert "suggestion" in payload
        assert payload["suggestion"] is None

    def test_error_matches_the_human_sentence(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        payload = _payload(verbs, capsys, "set-default", "sessions", "25", "--json")
        capsys.readouterr()
        _run(verbs, "set-default", "sessions", "25")
        assert payload["error"] in _streams(capsys)

    def test_bytes_unchanged(self, verbs, capsys) -> None:
        self._break_the_file(verbs)
        before = verbs.path.read_bytes()
        _payload(verbs, capsys, "set", "@memory", "sessions", "25", "--json")
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
        raw = _raw_stdout(verbs, capsys, "set", "@memory", "sessions", "25", "--json")

        assert len(raw) > 150, "the guard is worthless unless the payload exceeds the console width"
        assert raw.count("\n") == 1
        assert json.loads(raw)["error"].startswith(f"Config at {verbs.path}")

    def test_no_newline_hides_inside_any_string_value(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        payload = _payload(verbs, capsys, "set", "@memory", "sessions", "25", "--json")
        for value in payload.values():
            assert not isinstance(value, str) or "\n" not in value

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
        raw = _raw_stdout(verbs, capsys, "set", "@wizard", "sessions", "25", "--json")
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
        "count": 25,
        "pushed": False,
    }

    @pytest.mark.parametrize(
        "args",
        [
            ("set", "@memory", "sessions", "25", "--json"),
            ("set", "@memory", "sessions", "--json", "25"),
            ("set", "@memory", "--json", "sessions", "25"),
            ("set", "--json", "@memory", "sessions", "25"),
            ("--json", "set", "@memory", "sessions", "25"),
        ],
    )
    def test_payload_is_identical(self, verbs, capsys, args) -> None:
        assert _payload(verbs, capsys, *args) == self._EXPECTED

    @pytest.mark.parametrize(
        "args",
        [
            ("set", "@memory", "sessions", "25", "--json"),
            ("set", "--json", "@memory", "sessions", "25"),
            ("--json", "set", "@memory", "sessions", "25"),
        ],
    )
    def test_the_write_still_lands(self, verbs, capsys, args) -> None:
        _payload(verbs, capsys, *args)
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 25

    def test_push_flag_before_the_subcommand(self, verbs, capsys) -> None:
        assert _payload_rollover(verbs, capsys, "--json", "push")["verb"] == "rollover push"

    def test_bare_json_flag_introspects_rather_than_crashing(self, verbs, capsys) -> None:
        """Stripping the only token must not leave the parser holding nothing."""
        assert _run(verbs, "--json") is True
        assert "set-default" in _streams(capsys)

    def test_bare_json_flag_on_rollover_introspects(self, verbs, capsys) -> None:
        assert _run_rollover(verbs, "--json") is True
        assert "sync-lines" in _streams(capsys)


class TestHelpOutranksJson:
    """`--help --json` is still a question. The push scar, one flag later."""

    _COMBOS = [
        ("set", "@memory", "sessions", "25", "--help", "--json"),
        ("set", "@memory", "sessions", "25", "--json", "--help"),
        ("set", "--json", "@memory", "sessions", "25", "-h"),
        ("--json", "set", "@memory", "sessions", "25", "help"),
        ("set-default", "sessions", "25", "--json", "--help"),
    ]

    @pytest.mark.parametrize("args", _COMBOS)
    def test_file_is_byte_identical(self, verbs, args) -> None:
        before = verbs.path.read_bytes()
        assert _run(verbs, *args) is True
        assert verbs.path.read_bytes() == before

    @pytest.mark.parametrize("args", _COMBOS)
    def test_no_payload_is_emitted(self, verbs, capsys, args) -> None:
        out = _raw_stdout(verbs, capsys, *args)
        assert '"ok"' not in out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)

    @pytest.mark.parametrize("args", _COMBOS)
    def test_help_is_printed(self, verbs, capsys, args) -> None:
        _run(verbs, *args)
        assert "USAGE" in _streams(capsys)

    def test_push_help_json_does_not_push(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "25")
        capsys.readouterr()
        assert _run_rollover(verbs, "push", "--json", "--help") is True
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 25

    def test_help_documents_the_flag(self, verbs, capsys) -> None:
        _run(verbs, "--help")
        assert "--json" in _streams(capsys)
