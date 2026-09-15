# =================== AIPass ====================
# Name: test_config_verbs.py
# Description: Tests for the `config` verbs (rollover limit get/set/set-default) and the todo verbs
# Version: 1.4.0
# Created: 2026-08-16
# Modified: 2026-09-15
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

import copy
import importlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# The registry these tests address, MINTED per test in tmp_path.
# AIPASS_REGISTRY.json is machine-managed and gitignored: on a fresh clone it
# does not exist at all, so a suite that read the live one proved only that
# THIS machine had already run AIPass. Mixed casing is deliberate -- the real
# registry carries lowercase and UPPERCASE names side by side, and
# case-insensitive branch matching is one of the things under test.
_REGISTRY_BRANCHES = [
    {"name": "memory", "path": "src/aipass/memory", "status": "active"},
    {"name": "DEVPULSE", "path": "src/aipass/devpulse", "status": "active"},
    {"name": "DAEMON", "path": "src/aipass/daemon", "status": "active"},
]

# Wide enough that no sentence in this file can reach it. See _pin_console_width.
_CONSOLE_WIDTH = 300

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_HANDLER_MODULES = (
    "aipass.memory.apps.handlers.json",
    "aipass.memory.apps.handlers.json.json_handler",
    "aipass.memory.apps.handlers.json.config_loader",
)


# ---------------------------------------------------------------------------
# Fixture: real modules, throwaway config
# ---------------------------------------------------------------------------


def _pin_console_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix both shared Rich consoles at a known width.

    Rich resolves its width from the ENVIRONMENT -- a real terminal if there
    is one, else COLUMNS, else 80. These tests assert refusal sentences that
    carry a tmp path, and under an xdist worker that path is long enough that
    an 80-column console folds a newline INTO the sentence: the assertion then
    fails on output that is perfectly correct. Green on a dev machine with a
    wide terminal, red on a runner with none. @daemon paid for this twice on
    08-16 one layer along -- name the rendering explicitly, never let the shell
    decide it.

    `_width` and not the public `width` setter: these are module-global console
    objects shared with every other suite, and monkeypatch would restore
    `width` by writing back the number it read (80), leaving the console pinned
    for whoever ran next. `_width` starts as None and restores as None, and it
    is the attribute Console.size honours last.
    """
    display = importlib.import_module("aipass.cli.apps.modules.display")
    for console_obj in (display.CONSOLE, display.err_console):
        monkeypatch.setattr(console_obj, "_width", _CONSOLE_WIDTH)


@pytest.fixture
def verbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real config_loader + rollover module wired to a MINTED config and registry.

    Hermetic on purpose: nothing here reads state that exists only on a machine
    someone has already run AIPass on.

      * The config is built from config_loader.DEFAULT_CONFIG -- the in-tree
        regeneration seed, kept in lockstep with the operator file by S193
        doctrine -- and written by the real _write_config_file. A hand-formatted
        copy would make the no-op-set byte-identity test assert against this
        file's formatting instead of the writer's.
      * per_branch is filled by the real materialize_per_branch() reading the
        minted registry, so the fixture and the engine cannot disagree about
        the seeded shape.
      * BOTH registry doors are shut. detector._read_registry reads
        _REPO_ROOT/AIPASS_REGISTRY.json and then walks up from the caller's CWD
        for any other *_REGISTRY.json -- run from a checkout, that second door
        finds the fleet's own registry and the suite goes quietly non-hermetic.

    conftest replaces the handlers.json package with a MagicMock, which would
    make the lazy `from ... import config_loader` inside the module return a
    mock instead of the code under test. Popping it forces a real import.
    """
    for name in _HANDLER_MODULES:
        sys.modules.pop(name, None)
    config_loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")

    # Captured BEFORE the repoint: the guard in TestOperatorConfigIsolation
    # needs to know where the real file would have been.
    operator_config_path = config_loader._CONFIG_PATH

    config_path = tmp_path / "custom_config" / "memory.config.json"
    config_path.parent.mkdir(parents=True)
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(config_loader, "json_handler", MagicMock())

    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps({"branches": _REGISTRY_BRANCHES}, indent=2), encoding="utf-8")
    monkeypatch.setattr(config_loader, "_find_repo_root", lambda: tmp_path)

    detector = importlib.import_module("aipass.memory.apps.handlers.monitor.detector")
    monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
    monkeypatch.setattr(detector, "config_loader", config_loader)

    config = copy.deepcopy(config_loader.DEFAULT_CONFIG)
    config["rollover"]["per_branch"] = config_loader.materialize_per_branch()
    assert config_loader._write_config_file(config), "fixture could not write its own config"

    sys.modules.pop("aipass.memory.apps.modules.rollover", None)
    rollover = importlib.import_module("aipass.memory.apps.modules.rollover")
    monkeypatch.setattr(rollover, "json_handler", MagicMock())

    _pin_console_width(monkeypatch)

    return SimpleNamespace(
        rollover=rollover,
        loader=config_loader,
        detector=detector,
        path=config_path,
        operator_path=operator_config_path,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(verbs: SimpleNamespace, *args: str) -> bool:
    """Invoke `config <args>` exactly as the entry point routes it."""
    return verbs.rollover.handle_command("config", list(args))


def _streams(capsys: pytest.CaptureFixture) -> str:
    """Both streams joined and ANSI-stripped -- refusals to stderr, displays to stdout.

    Stripping is not cosmetic. FORCE_COLOR makes Rich emit attributes into a
    captured non-terminal stream, so `assert "[DEFAULT]" in out` passes in one
    shell and fails in the next on byte-identical code (@daemon, 08-16).
    """
    captured = capsys.readouterr()
    return _ANSI.sub("", captured.out + captured.err)


def _unwrapped(text: str) -> str:
    """All whitespace removed -- the only comparison that survives ANY wrap.

    A Rich fold can land mid-token (`custom_config` arrives as `custom_con` +
    newline + `fig`), so collapsing runs of whitespace is not enough. Used for
    the refusal sentences that carry a tmp path; the console width is pinned
    as well, and this is the belt to that pair of braces.
    """
    return "".join(text.split())


def _snapshot(path: Path) -> bytes | None:
    """Bytes if the file is there, None if it is not -- absence IS a state.

    On a dev machine the operator's config exists and the guard is about its
    bytes. On a fresh clone it does not exist, and the same guard then says the
    suite did not CREATE it. Reading it unconditionally is what turned this
    file's isolation tests into CI errors.
    """
    return path.read_bytes() if path.exists() else None


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
    """Only three entry types are settable; anything unknown is refused by name (todos: see section 8)."""

    def test_set_unknown_type_message(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "foo", "25")
        assert "Unknown entry type: 'foo'" in _streams(capsys)

    def test_set_unknown_type_suggestion(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "foo", "25")
        assert "Valid types: sessions, key_learnings, observations" in _streams(capsys)

    def test_set_default_unknown_type_message(self, verbs, capsys) -> None:
        _run(verbs, "set-default", "wizard", "25")
        assert "Unknown entry type: 'wizard'" in _streams(capsys)

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
        assert _unwrapped(expected) in _unwrapped(_streams(capsys))

    def test_message_on_set_default(self, verbs, capsys) -> None:
        verbs.path.write_text("{ this is not json", encoding="utf-8")
        _run(verbs, "set-default", "sessions", "25")
        expected = f"Config at {verbs.path} is unreadable — fix or move it aside, then try again"
        assert _unwrapped(expected) in _unwrapped(_streams(capsys))

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
        assert _unwrapped("is unreadable — fix or move it aside, then try again") in _unwrapped(_streams(capsys))
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


class TestOperatorConfigIsolation:
    """A test that edited the fleet config would be the accident, not the guard.

    The operator's file is gitignored: present on every dev machine, absent on
    a fresh clone. The guard therefore compares SNAPSHOTS rather than bytes --
    "still absent" is as much a pass as "unchanged", and neither is a skip.
    """

    def test_config_path_is_repointed(self, verbs, tmp_path) -> None:
        assert verbs.loader._CONFIG_PATH != verbs.operator_path
        assert tmp_path in verbs.loader._CONFIG_PATH.parents

    def test_operator_config_unchanged_by_a_set(self, verbs) -> None:
        before = _snapshot(verbs.operator_path)
        _run(verbs, "set", "@memory", "sessions", "25")
        _run(verbs, "set-default", "sessions", "40")
        assert _snapshot(verbs.operator_path) == before

    def test_operator_config_unchanged_by_json_mode(self, verbs) -> None:
        before = _snapshot(verbs.operator_path)
        _run(verbs, "set", "@memory", "sessions", "25", "--json")
        _run(verbs, "set-default", "sessions", "40", "--json")
        _run_rollover(verbs, "push", "--json")
        assert _snapshot(verbs.operator_path) == before

    def test_no_registry_of_this_machine_is_reachable(self, verbs, tmp_path) -> None:
        """The second registry door: _find_caller_registries walks up from CWD.

        Left open, a run started inside a checkout picks up the fleet's own
        AIPASS_REGISTRY.json and the suite passes for a reason that has
        nothing to do with the code under test.
        """
        names = {b["name"] for b in verbs.detector._read_registry()}
        assert names == {"memory", "DEVPULSE", "DAEMON"}


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
            (("set", "@memory", "sessions", "25", "--json"), "config set"),
            (("set-default", "sessions", "25", "--json"), "config set-default"),
            (("set", "@wizard", "sessions", "25", "--json"), "config set"),
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


# ===========================================================================
# 8. Todos (DPLAN-0345) -- the count is shown, never set; ONE pad per rollover verb
# ===========================================================================


def _stdout(capsys: pytest.CaptureFixture) -> str:
    """Raw stdout, ANSI-stripped -- exactly what @hooks' PreCompact grep reads."""
    return _ANSI.sub("", capsys.readouterr().out)


class TestTodosCountIsDisplayOnly:
    """`config get` shows the todos count; `config set` / `set-default` never write it in v1."""

    def test_get_shows_the_todos_default(self, verbs, capsys) -> None:
        _run(verbs, "get")
        rows = [line for line in _streams(capsys).splitlines() if line.strip().startswith("todos")]
        assert len(rows) == 1 and "10" in rows[0] and "read-only in v1" in rows[0], rows

    def test_get_branch_shows_the_todos_count(self, verbs, capsys) -> None:
        _run(verbs, "get", "@memory")
        out = _streams(capsys)
        assert any(line.strip().startswith("todos") and "10" in line for line in out.splitlines()), out
        assert "read-only in v1 — the todo roll reads it, config set does not" in out

    def test_json_defaults_mark_todos_read_only(self, verbs, capsys) -> None:
        assert _payload(verbs, capsys, "get", "--json")["defaults"]["todos"] == {"count": 10, "read_only": True}

    def test_json_branch_limits_mark_todos_read_only(self, verbs, capsys) -> None:
        row = _payload(verbs, capsys, "get", "@memory", "--json")["limits"]["todos"]
        assert row == {
            "count": 10,
            "default_count": 10,
            "is_override": False,
            "source": "per_branch",
            "read_only": True,
        }

    @pytest.mark.parametrize("args", [("set", "@memory", "todos", "5"), ("set-default", "todos", "5")])
    def test_setting_todos_is_refused_and_writes_nothing(self, verbs, capsys, args) -> None:
        before = verbs.path.read_bytes()
        _run(verbs, *args)
        out = _unwrapped(_streams(capsys))
        assert (
            _unwrapped("'todos' is display-only in v1: config get shows its count, config set cannot change it") in out
        )
        assert _unwrapped("Settable types: sessions, key_learnings, observations") in out
        assert verbs.path.read_bytes() == before


class TestTodosCountMaterializesThroughTheVerbs:
    """Every per_branch local block a verb writes carries the todos count."""

    def test_the_seeded_per_branch_carries_todos(self, verbs) -> None:
        per_branch = _rollover_section(verbs)["per_branch"]
        assert set(per_branch) == {"memory", "devpulse", "daemon"}
        for name, entry in per_branch.items():
            assert entry["local"]["todos"] == {"count": 10}, name

    def test_a_set_on_a_block_without_todos_writes_it(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        del raw["rollover"]["per_branch"]["memory"]["local"]["todos"]
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        _run(verbs, "set", "@memory", "sessions", "25")

        local = _rollover_section(verbs)["per_branch"]["memory"]["local"]
        assert local["sessions"]["count"] == 25
        assert local["todos"] == {"count": 10}

    def test_a_push_writes_todos_into_every_block(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        for entry in raw["rollover"]["per_branch"].values():
            del entry["local"]["todos"]
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        _run_rollover(verbs, "push")

        for name, entry in _rollover_section(verbs)["per_branch"].items():
            assert entry["local"]["todos"] == {"count": 10}, name


class TestRolloverTodoPad:
    """`rollover check` / `run` act on ONE pad: --branch, or the branch the caller stood in."""

    @pytest.fixture
    def pad(self, verbs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
        """A @memory pad inside the minted repo; the todo lane and the memory writer pointed at the fixture."""
        todo_roll = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")
        todo_report = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_report")
        monkeypatch.setattr(todo_roll, "_find_repo_root", lambda: tmp_path)
        monkeypatch.setattr(todo_roll, "config_loader", verbs.loader)
        monkeypatch.setattr(todo_report, "todo_roll", todo_roll)
        monkeypatch.setattr(todo_report, "detector", verbs.detector)
        monkeypatch.setattr(verbs.rollover, "todo_report", todo_report)
        for holder in ("memory_files", "entry_limits"):
            module = importlib.import_module(f"aipass.memory.apps.handlers.json.{holder}")
            monkeypatch.setattr(module, "config_loader", verbs.loader)
        execute = MagicMock(return_value={"success": True, "triggers_count": 0})
        monkeypatch.setattr(verbs.rollover, "_handler_execute_rollover", execute)

        local = tmp_path / "src" / "aipass" / "memory" / ".trinity" / "local.json"
        local.parent.mkdir(parents=True)

        def write(count: int) -> bytes:
            todos = [
                {"number": n, "task": f"task {n}", "date": "2026-09-01", "priority": "normal"}
                for n in range(1, count + 1)
            ]
            document = {"document_metadata": {}, "sessions": [], "todos": todos}
            local.write_text(json.dumps(document, indent=2), encoding="utf-8")
            return local.read_bytes()

        backlog = tmp_path / ".backup" / "todo" / "memory" / "backlog.json"
        return SimpleNamespace(local=local, backlog=backlog, execute=execute, write=write, before=write(12))

    def test_check_over_count_says_ready_for_rollover(self, verbs, pad, capsys) -> None:
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@memory")
        out = _stdout(capsys)
        assert "@memory todos: pad 12/10 - 2 ready for rollover (oldest by number -> " in out, out
        assert pad.local.read_bytes() == pad.before
        assert not pad.backlog.exists()

    def test_the_phrase_survives_a_narrow_pipe(self, verbs, pad, capsys, monkeypatch) -> None:
        """@hooks greps raw stdout. At 40 columns a hard wrap would land between 'for' and 'rollover'."""
        display = importlib.import_module("aipass.cli.apps.modules.display")
        monkeypatch.setattr(display.CONSOLE, "_width", 40)
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@memory")
        assert "ready for rollover" in _stdout(capsys)

    def test_check_labels_the_classic_file_list_fleet_wide(self, verbs, pad, capsys, monkeypatch) -> None:
        """--branch scopes the pad line only. The classic list is the fleet walk (scope unchanged) and says so,
        with "ready for rollover" whole on its first line even on a 40-column pipe (@hooks greps it)."""
        display = importlib.import_module("aipass.cli.apps.modules.display")
        monkeypatch.setattr(display.CONSOLE, "_width", 40)
        triggers = ["CANARY.local 16/15", "memory.local 16/15"]
        monkeypatch.setattr(
            verbs.rollover.detector, "check_all_branches", lambda: {"success": True, "triggers": triggers}
        )
        within = pad.write(10)
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@memory")
        lines = _stdout(capsys).splitlines()
        assert "Found 2 files ready for rollover (fleet-wide):" in lines, lines
        assert verbs.rollover.FLEET_WIDE_NOTE in lines, lines
        assert "--branch" in verbs.rollover.FLEET_WIDE_NOTE and "fleet-wide" in verbs.rollover.FLEET_WIDE_NOTE
        assert [line for line in lines if line.startswith("  * ")] == [f"  * {trigger}" for trigger in triggers]
        assert any("@memory todos: pad 10/10 - within count" in line for line in lines), lines
        assert pad.local.read_bytes() == within, "check writes nothing"
        assert not pad.backlog.exists()

    def test_a_pad_at_its_count_is_within_count(self, verbs, pad, capsys) -> None:
        pad.write(10)
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch=@memory")
        out = _stdout(capsys)
        assert "@memory todos: pad 10/10 - within count" in out, out
        assert "ready for rollover" not in out

    def test_at_the_repo_root_no_pad_is_checked_or_rolled(self, verbs, pad, capsys, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        capsys.readouterr()
        _run_rollover(verbs, "check")
        _run_rollover(verbs, "run")
        out = _stdout(capsys)
        todo_lines = [line for line in out.splitlines() if line.startswith("Todos:")]
        assert len(todo_lines) == 2, out
        assert todo_lines[0].startswith("Todos: no branch resolved (")
        assert todo_lines[0].endswith("- no todo pad checked; pass --branch @name")
        assert todo_lines[1].endswith("- no todo pad rolled; pass --branch @name")
        assert "ready for rollover" not in out
        assert pad.local.read_bytes() == pad.before
        assert not pad.backlog.exists()

    def test_run_rolls_the_named_pad_into_its_backlog(self, verbs, pad, capsys) -> None:
        capsys.readouterr()
        assert _run_rollover(verbs, "run", "--branch", "@memory") is True
        out = _stdout(capsys)
        assert "@memory todos: rolled 2 oldest (#1, #2) -> " in out, out
        assert "pad now 10/10" in out
        assert [t["number"] for t in json.loads(pad.local.read_text(encoding="utf-8"))["todos"]] == list(range(3, 13))
        entries = json.loads(pad.backlog.read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in entries] == [1, 2]
        pad.execute.assert_called_once_with()

    @pytest.mark.parametrize(
        ("args", "sentence"),
        [
            (("run", "--branch"), "--branch needs a branch name (rollover run)"),
            (("check", "--brnach", "@memory"), "Unknown argument: '--brnach' (rollover check)"),
            (("run", "--branch", "@memory", "extra"), "Unknown argument: 'extra' (rollover run)"),
        ],
    )
    def test_a_bad_flag_is_refused_and_nothing_runs(self, verbs, pad, capsys, args, sentence) -> None:
        capsys.readouterr()
        _run_rollover(verbs, *args)
        assert _unwrapped(sentence) in _unwrapped(_streams(capsys))
        pad.execute.assert_not_called()
        assert pad.local.read_bytes() == pad.before
        assert not pad.backlog.exists()

    def test_an_unknown_branch_is_refused_by_name(self, verbs, pad, capsys) -> None:
        capsys.readouterr()
        _run_rollover(verbs, "check", "--branch", "@wizard")
        assert _unwrapped("Todos not checked - Unknown branch: @wizard") in _unwrapped(_streams(capsys))


_TODO_FORMS = (
    "drone @memory todo [@name]",
    "drone @memory todo backlog [@name]",
    "drone @memory todo restore <number>",
)


def _todo_exit(todo: SimpleNamespace, *args: str) -> int:
    """Run `todo <args>` through the module and map it to the exit code main() returns (resolve_exit)."""
    todo.display.reset_command_state()
    return todo.display.resolve_exit(todo.module.handle_command("todo", list(args)))


def _todo_pad(todo: SimpleNamespace, numbers) -> bytes:
    """Write canonical todos with these numbers onto the scratch pad; return its bytes."""
    todos = [{"number": n, "date": "2026-09-01", "task": f"task {n}", "priority": "medium"} for n in numbers]
    document = {"document_metadata": {}, "sessions": [], "todos": todos}
    todo.local.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return todo.local.read_bytes()


def _todo_record(number: int, task: str, rolled: str = "2026-09-15T01:00:00+10:00", **extra) -> dict:
    """One backlog record; *extra* lands inside the entry (priority, status), `reason` on the record."""
    reason = extra.pop("reason", "overflow")
    return {
        "rolled": rolled,
        "reason": reason,
        "entry": {"number": number, "date": "2026-09-01", "task": task, **extra},
    }


def _todo_backlog(todo: SimpleNamespace, records: list) -> bytes:
    """Write the scratch backlog document; return its bytes."""
    todo.backlog.parent.mkdir(parents=True, exist_ok=True)
    document = {"document_metadata": {"managed_by": "memory", "branch": "memory"}, "entries": records}
    todo.backlog.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return todo.backlog.read_bytes()


def _set_todos_count(verbs: SimpleNamespace, count: int) -> None:
    """Set the todos count in defaults and every materialized per_branch block of the minted config."""
    config = json.loads(verbs.path.read_text(encoding="utf-8"))
    for block in [config["rollover"]["defaults"], *config["rollover"]["per_branch"].values()]:
        block["local"]["todos"] = {"count": count}
    assert verbs.loader._write_config_file(config), "could not write the minted config"


class TestTodoVerbs:
    """`todo` / `todo backlog` / `todo restore` (FPLAN-0590 row 5): the real module and handlers on a minted repo."""

    @pytest.fixture(autouse=True)
    def _backlogs_stay_in_tmp(self, verbs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No pin in this class may reach the repo's real .backup/todo/: an unrouted backlog lands under tmp_path."""
        todo_roll = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")
        real = todo_roll.backlog_path_for

        def scratch(branch_dir, backup_root=None):
            return real(branch_dir, tmp_path / ".backup" if backup_root is None else backup_root)

        monkeypatch.setattr(todo_roll, "backlog_path_for", scratch)

    @pytest.fixture
    def todo(self, verbs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """The todo module wired to the minted repo; the caller stands in @memory's directory."""
        todo_roll = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_roll")
        todo_report = importlib.import_module("aipass.memory.apps.handlers.rollover.todo_report")
        monkeypatch.setattr(todo_roll, "_find_repo_root", lambda: tmp_path)
        monkeypatch.setattr(todo_roll, "config_loader", verbs.loader)
        monkeypatch.setattr(todo_roll, "json_handler", MagicMock())
        monkeypatch.setattr(todo_report, "todo_roll", todo_roll)
        monkeypatch.setattr(todo_report, "detector", verbs.detector)
        monkeypatch.setattr(todo_report, "json_handler", MagicMock())
        for holder in ("memory_files", "entry_limits"):
            module = importlib.import_module(f"aipass.memory.apps.handlers.json.{holder}")
            monkeypatch.setattr(module, "config_loader", verbs.loader)
        monkeypatch.delitem(sys.modules, "aipass.memory.apps.modules.todo", raising=False)
        module = importlib.import_module("aipass.memory.apps.modules.todo")
        monkeypatch.setattr(module, "todo_report", todo_report)
        monkeypatch.setattr(module, "json_handler", MagicMock())

        branch = tmp_path / "src" / "aipass" / "memory"
        local = branch / ".trinity" / "local.json"
        local.parent.mkdir(parents=True)
        (tmp_path / "src" / "aipass" / "devpulse").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(branch))
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        backlog = tmp_path / ".backup" / "todo" / "memory" / "backlog.json"
        assert todo_roll.backlog_path_for("memory") == backlog
        display = importlib.import_module("aipass.cli.apps.modules.display")
        yield SimpleNamespace(
            module=module, local=local, backlog=backlog, branch=branch, root=tmp_path, display=display, verbs=verbs
        )
        display.reset_command_state()

    def test_bare_is_one_line_the_pad_of_the_configured_count_and_the_backlog(self, todo, capsys) -> None:
        _set_todos_count(todo.verbs, 7)
        _todo_pad(todo, range(1, 7))
        capsys.readouterr()
        assert _todo_exit(todo) == 0
        captured = capsys.readouterr()
        assert _ANSI.sub("", captured.out).splitlines() == [
            "memory: pad 6 of 7 · backlog 0 (no backlog yet: .backup/todo/memory/backlog.json)"
        ], captured.out
        assert captured.err == ""

        _todo_backlog(todo, [_todo_record(1, "one"), _todo_record(2, "two")])
        assert _todo_exit(todo, "@memory") == 0
        assert _ANSI.sub("", capsys.readouterr().out).splitlines() == [
            "memory: pad 6 of 7 · backlog 2 (.backup/todo/memory/backlog.json)"
        ]

    def test_bare_at_the_repo_root_resolves_no_branch_and_says_so(self, todo, capsys, monkeypatch) -> None:
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(todo.root))
        _todo_pad(todo, range(1, 4))
        capsys.readouterr()
        assert _todo_exit(todo) == 0
        lines = _ANSI.sub("", capsys.readouterr().out).splitlines()
        assert len(lines) == 1, lines
        assert lines[0].startswith("Todos: no branch resolved (")
        assert lines[0].endswith(") - no todo pad counted; pass --branch @name")

        assert _todo_exit(todo, "--branch", "@memory") == 0
        assert _ANSI.sub("", capsys.readouterr().out).startswith("memory: pad 3 of ")

    def test_backlog_lists_each_record_with_its_task_and_never_its_status(self, todo, capsys) -> None:
        log = "open - 23:19 wake-back LOG-MARKER " * 40
        _todo_backlog(
            todo,
            [
                _todo_record(
                    7, "Check on seedgo's errors in logs", reason="non-canonical", priority="high", status=log
                ),
                _todo_record(9, "fix drone help", rolled="2026-09-15T02:00:00+10:00"),
            ],
        )
        capsys.readouterr()
        assert _todo_exit(todo, "backlog") == 0
        captured = capsys.readouterr()
        out = _ANSI.sub("", captured.out)
        assert out.splitlines() == [
            "memory backlog: 2 record(s), oldest roll first (.backup/todo/memory/backlog.json)",
            "  #7 · 2026-09-01 · priority high · rolled 2026-09-15T01:00:00+10:00 · non-canonical"
            " · Check on seedgo's errors in logs",
            "  #9 · 2026-09-01 · rolled 2026-09-15T02:00:00+10:00 · overflow · fix drone help",
        ], out
        assert "LOG-MARKER" not in out + captured.err

    def test_a_missing_backlog_is_an_honest_line_and_exits_zero(self, todo, capsys) -> None:
        capsys.readouterr()
        assert _todo_exit(todo, "backlog") == 0
        assert _todo_exit(todo, "backlog", "@devpulse") == 0
        captured = capsys.readouterr()
        lines = _ANSI.sub("", captured.out).splitlines()
        assert lines[0].startswith("memory: no backlog - .backup/todo/memory/backlog.json does not exist."), lines
        assert lines[1].startswith("devpulse: no backlog - .backup/todo/devpulse/backlog.json does not exist."), lines
        assert captured.err == ""
        assert not todo.backlog.exists()

    def test_a_corrupt_backlog_is_refused_non_zero_and_left_as_it_was(self, todo, capsys) -> None:
        _todo_pad(todo, range(1, 4))
        todo.backlog.parent.mkdir(parents=True)
        todo.backlog.write_text("{not json", encoding="utf-8")
        capsys.readouterr()
        assert _todo_exit(todo, "backlog") == 2
        assert _unwrapped("memory: backlog not listed - backlog at") in _unwrapped(
            _ANSI.sub("", capsys.readouterr().err)
        )
        assert _todo_exit(todo) == 2
        assert _unwrapped("memory: pad 3 of 10 · backlog unreadable - backlog at") in _unwrapped(
            _ANSI.sub("", capsys.readouterr().err)
        )
        assert todo.backlog.read_text(encoding="utf-8") == "{not json"

    def test_restore_renumbers_to_max_of_pad_and_backlog_plus_one(self, todo, capsys) -> None:
        _todo_pad(todo, range(9, 2, -1))
        _todo_backlog(
            todo, [_todo_record(1, "Check on seedgo's errors in logs", priority="high"), _todo_record(2, "b")]
        )
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1") == 0
        out = _ANSI.sub("", capsys.readouterr().out)
        assert out.splitlines() == [
            "@memory todo restored: #1 -> #10 · Check on seedgo's errors in logs · pad now 8/10"
        ]
        pad = json.loads(todo.local.read_text(encoding="utf-8"))["todos"]
        assert pad[0] == {
            "number": 10,
            "date": "2026-09-01",
            "task": "Check on seedgo's errors in logs",
            "priority": "high",
        }, "lists are newest-first: the restored todo carries the highest number, so it goes on top"
        assert [t["number"] for t in pad] == [10, 9, 8, 7, 6, 5, 4, 3]
        entries = json.loads(todo.backlog.read_text(encoding="utf-8"))["entries"]
        assert [record["entry"]["number"] for record in entries] == [2]

    def test_a_full_pad_refuses_non_zero_at_the_count_read_from_config(self, todo, capsys) -> None:
        _set_todos_count(todo.verbs, 4)
        pad_before = _todo_pad(todo, range(3, 7))
        backlog_before = _todo_backlog(todo, [_todo_record(1, "fix drone help")])
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped("@memory todo #1 NOT restored - pad is full (4/4) - finish or delete one") in err, err
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before

    def test_an_ambiguous_number_is_refused_naming_every_candidate(self, todo, capsys) -> None:
        pad_before = _todo_pad(todo, range(20, 23))
        backlog_before = _todo_backlog(
            todo,
            [
                _todo_record(5, "first five"),
                _todo_record(6, "six"),
                _todo_record(5, "second five", rolled="2026-09-15T03:00:00+10:00"),
            ],
        )
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "#5") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert (
            _unwrapped(
                "@memory todo #5 NOT restored - todo #5 is ambiguous - 2 backlog records carry it: "
                "rolled 2026-09-15T01:00:00+10:00: first five; rolled 2026-09-15T03:00:00+10:00: second five. "
                "Nothing restored"
            )
            in err
        ), err
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before

    def test_restore_acts_on_the_callers_own_branch_only(self, todo, capsys, monkeypatch) -> None:
        pad_before = _todo_pad(todo, range(5, 2, -1))
        backlog_before = _todo_backlog(todo, [_todo_record(1, "fix drone help")])
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1", "--branch", "@devpulse") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped("Todo #1 not restored - --branch names @devpulse, but you are in @memory") in err, err
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before
        assert not (todo.root / "src" / "aipass" / "devpulse" / ".trinity").exists()

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(todo.root))
        assert _todo_exit(todo, "restore", "1", "--branch", "@memory") == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped("Todo #1 not restored - no branch resolved from where you stand (") in err, err
        assert todo.local.read_bytes() == pad_before

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(todo.branch))
        assert _todo_exit(todo, "restore", "1", "@memory") == 0
        assert [t["number"] for t in json.loads(todo.local.read_text(encoding="utf-8"))["todos"]] == [6, 5, 4, 3]

    @pytest.mark.parametrize(
        ("args", "sentence"),
        [
            (("frobnicate",), "Unknown todo argument: 'frobnicate'"),
            (("--json",), "Unknown todo argument: '--json'"),
            (("restore",), "todo restore needs the todo's number from the backlog, got nothing"),
            (("restore", "seven"), "todo restore needs the todo's number from the backlog, got 'seven'"),
            (("backlog", "extra"), "Unknown argument: 'extra' (todo backlog)"),
            (("@memory", "extra"), "Unknown argument: 'extra' (todo)"),
            (("--branch",), "--branch needs a branch name (todo)"),
        ],
    )
    def test_a_bad_argument_is_refused_non_zero_naming_the_valid_forms(self, todo, capsys, args, sentence) -> None:
        pad_before = _todo_pad(todo, range(1, 4))
        capsys.readouterr()
        assert _todo_exit(todo, *args) == 2
        err = _unwrapped(_ANSI.sub("", capsys.readouterr().err))
        assert _unwrapped(sentence) in err, err
        for form in _TODO_FORMS:
            assert _unwrapped(form) in err, form
        assert todo.local.read_bytes() == pad_before
        assert not todo.backlog.exists()

    def test_help_in_any_slot_prints_usage_and_restores_nothing(self, todo, capsys) -> None:
        pad_before = _todo_pad(todo, range(3, 6))
        backlog_before = _todo_backlog(todo, [_todo_record(1, "fix drone help")])
        capsys.readouterr()
        assert _todo_exit(todo, "restore", "1", "--help") == 0
        out = _ANSI.sub("", capsys.readouterr().out)
        assert "USAGE:" in out
        for form in _TODO_FORMS:
            assert form in out, form
        assert todo.local.read_bytes() == pad_before
        assert todo.backlog.read_bytes() == backlog_before

    def test_the_entry_point_help_lists_the_todo_verbs(self, todo, capsys) -> None:
        """`drone @memory --help` names all three forms; the bare `drone @memory` map lists the discovered module."""
        entry = importlib.import_module("aipass.memory.apps.memory")
        capsys.readouterr()
        entry.print_help()
        out = _unwrapped(_ANSI.sub("", capsys.readouterr().out))
        for row in ("todo [@branch]", "todo backlog [@branch]", "todo restore <number>", "todo [backlog|restore]"):
            assert _unwrapped(row) in out, row

        entry.print_introspection()
        lines = [line.strip() for line in _ANSI.sub("", capsys.readouterr().out).splitlines()]
        assert "* todo" in lines, lines


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
        assert _unwrapped(payload["error"]) in _unwrapped(_streams(capsys))

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
        assert "report-lines" in _streams(capsys)


class TestHelpOutranksJson:
    """`--help --json` is still a question. The push scar, one flag later."""

    _COMBOS = [
        ("set", "@memory", "sessions", "25", "--help", "--json"),
        ("set", "@memory", "sessions", "25", "--json", "--help"),
        ("set", "--json", "@memory", "sessions", "25", "-h"),
        ("--json", "set", "@memory", "sessions", "25", "help"),
        ("set-default", "sessions", "25", "--json", "--help"),
    ]
    # seedgo SHORT-TABLE (2026-08-31): same guard as _CASES above.
    assert len(_COMBOS) == 5

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
