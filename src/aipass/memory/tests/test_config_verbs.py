# =================== AIPass ====================
# Name: test_config_verbs.py
# Description: Tests for the `config` verbs (rollover limit get/set/set-default): writes, display, help, isolation
# Version: 1.8.0
# Created: 2026-08-16
# Modified: 2026-10-08
# =============================================

"""Tests for apps/modules/rollover_config.py — config verbs' writes, display and help, via apps/modules/rollover.py."""

# Tests for `drone @memory config` -- the verb surface over rollover limits.
#
# DPLAN-0302. The CLI output and the refusal sentences ARE the API contract
# (@api exec's this CLI to serve BAUD's memory-settings screen), so these
# tests pin the exact sentences, not merely "an error happened".
#
# Split by subject on 2026-10-08 (oversize_test_file). This file keeps the
# writes, the display, help and isolation; its siblings hold the rest:
#   - test_config_verbs_refusals.py -- every refusal sentence, verbatim, and the ceiling
#   - test_config_verbs_json.py     -- the --json machine surface
#   - test_config_verbs_todo.py     -- the todos count, the rollover pad, the todo verbs
# The minted world and the shared helpers live in support_config_verbs.py; the
# `verbs` fixture is in conftest.py.
#
# Covers:
#   - `set @branch <type> <count>` lands in per_branch and reads back as an override
#   - `set-default` writes defaults and leaves per_branch untouched
#   - Round-trip: set -> `rollover push` returns the branch to defaults
#   - Effective limits resolve per FILE KEY exactly like detector._should_rollover
#     (a deep merge would report a limit the engine does not enforce)
#   - auto_compact_cap survives a `sessions` set (never dropped, never settable)
#   - A help flag in ANY slot prints help and leaves the file byte-identical,
#     and --help still outranks --json
#   - Rich actually renders the [DEFAULT] / [OVERRIDE] markers on screen
#     (a lowercase [default] tag is eaten by Rich's markup parser while the
#     source string still reads correctly -- the assertion must see the screen)
#   - Every example count a refusal or the help page prints is within its ceiling
#
# Isolation: the live memory_json/custom_config/memory.config.json is COPIED
# into tmp_path and config_loader._CONFIG_PATH is repointed at the copy. These
# tests write limits; a suite that edited the fleet config would be the exact
# accident these verbs exist to prevent.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — push_defaults_to_per_branch() itself, tests/test_config_loader.py
# seedgo: no-test-needed(covered_elsewhere) — get_count_ceilings() arithmetic, pinned in tests/test_config_loader.py

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# The minted verbs world (conftest's `verbs` fixture is _real_verbs) and the
# run/read helpers the split config-verbs files share.
from aipass.memory.tests.support_config_verbs import (
    _HANDLER_MODULES,
    _ROLLOVER_MODULE,
    _raw_stdout,
    _real_verbs,
    _rollover_section,
    _run,
    _run_rollover,
    _streams,
)


class TestVerbsFixtureIsUndoneAtTeardown:
    """What the verbs fixture re-imports must not outlive the test that re-imported it."""

    def test_every_evicted_module_and_its_parent_attribute_is_restored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        names = (*_HANDLER_MODULES, _ROLLOVER_MODULE)
        # A known object in each parent slot the fixture evicts, so the parent-attribute half is read on
        # every worker: run alone, neither parent package is imported yet and there is nothing to restore.
        # This test's own monkeypatch takes the stand-ins away again.
        for name in (_HANDLER_MODULES[0], _ROLLOVER_MODULE):
            parent_name, _, leaf = name.rpartition(".")
            stand_in = SimpleNamespace(stand_in=name)
            monkeypatch.setattr(importlib.import_module(parent_name), leaf, stand_in, raising=False)
        missing = object()
        parents = {name: sys.modules.get(name.rpartition(".")[0]) for name in names}
        modules_before = {name: sys.modules.get(name) for name in names}
        attrs_before = {name: getattr(parents[name], name.rpartition(".")[2], missing) for name in names}

        with pytest.MonkeyPatch.context() as mp:
            fixture = _real_verbs(tmp_path, mp)
            # Guard the guard: the fixture really re-imported config_loader and rollover.
            assert fixture.loader is sys.modules[_HANDLER_MODULES[-1]]
            assert fixture.loader is not modules_before[_HANDLER_MODULES[-1]]
            assert fixture.rollover is not modules_before[_ROLLOVER_MODULE]

        leaked = [name for name in names if sys.modules.get(name) is not modules_before[name]]
        renamed = [
            name for name in names if getattr(parents[name], name.rpartition(".")[2], missing) is not attrs_before[name]
        ]
        assert leaked == [], f"the fixture's {leaked} outlived its test in sys.modules"
        assert renamed == [], f"a parent package still names the fixture's {renamed}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(path: Path) -> bytes | None:
    """Bytes if the file is there, None if it is not -- absence IS a state.

    On a dev machine the operator's config exists and the guard is about its
    bytes. On a fresh clone it does not exist, and the same guard then says the
    suite did not CREATE it. Reading it unconditionally is what turned this
    file's isolation tests into CI errors.
    """
    return path.read_bytes() if path.exists() else None


# ===========================================================================
# 2. Writes that land
# ===========================================================================


class TestSetBranchLimit:
    """`config set @branch <type> <count>` writes rollover.per_branch."""

    def test_sessions_lands_in_per_branch(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 12

    def test_key_learnings_lands_in_per_branch(self, verbs) -> None:
        _run(verbs, "set", "@memory", "key_learnings", "12")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["key_learnings"]["count"] == 12

    def test_observations_lands_in_its_own_file_key(self, verbs) -> None:
        _run(verbs, "set", "@memory", "observations", "7")
        per_branch = _rollover_section(verbs)["per_branch"]["memory"]
        assert per_branch["observations"]["observations"]["count"] == 7

    def test_reads_back_as_an_override(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 12
        assert limits["sessions"]["is_override"] is True

    def test_untouched_types_stay_default(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["key_learnings"]["is_override"] is False

    def test_branch_matching_is_case_insensitive(self, verbs) -> None:
        """The registry carries DAEMON uppercase; per_branch keys are lowercase."""
        assert _run(verbs, "set", "@DAEMON", "sessions", "12") is True
        assert _rollover_section(verbs)["per_branch"]["daemon"]["local"]["sessions"]["count"] == 12

    def test_write_key_is_always_lowercase(self, verbs) -> None:
        _run(verbs, "set", "@DAEMON", "sessions", "12")
        assert "DAEMON" not in _rollover_section(verbs)["per_branch"]

    def test_bare_branch_name_without_at_works(self, verbs) -> None:
        _run(verbs, "set", "memory", "sessions", "13")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 13

    def test_defaults_untouched_by_a_branch_set(self, verbs) -> None:
        before = _rollover_section(verbs)["defaults"]
        _run(verbs, "set", "@memory", "sessions", "12")
        assert _rollover_section(verbs)["defaults"] == before

    def test_other_branches_untouched(self, verbs) -> None:
        before = _rollover_section(verbs)["per_branch"]["devpulse"]
        _run(verbs, "set", "@memory", "sessions", "12")
        assert _rollover_section(verbs)["per_branch"]["devpulse"] == before

    def test_other_config_sections_survive(self, verbs) -> None:
        before = json.loads(verbs.path.read_text(encoding="utf-8"))["entry_limits"]
        _run(verbs, "set", "@memory", "sessions", "12")
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
        _run(verbs, "set", "@memory", "sessions", "12")
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
        _run(verbs, "set", "@memory", "sessions", "12")
        after = _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["auto_compact_cap"]
        assert after == before

    def test_survives_a_default_set(self, verbs) -> None:
        before = _rollover_section(verbs)["defaults"]["local"]["sessions"]["auto_compact_cap"]
        _run(verbs, "set-default", "sessions", "12")
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

        _run(verbs, "set", "@memory", "sessions", "12")

        entry = _rollover_section(verbs)["per_branch"]["memory"]
        assert entry["_note"] == "Limits for @memory. Manual edits persist until next push."

    def test_seeded_entry_carries_the_other_limits(self, verbs) -> None:
        raw = json.loads(verbs.path.read_text(encoding="utf-8"))
        raw["rollover"]["per_branch"].pop("memory", None)
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

        _run(verbs, "set", "@memory", "sessions", "12")

        entry = _rollover_section(verbs)["per_branch"]["memory"]
        assert entry["local"]["key_learnings"]["count"] == 15
        assert entry["observations"]["observations"]["count"] == 15
        assert entry["local"]["sessions"]["auto_compact_cap"] == 3


class TestSetDefault:
    """`config set-default` writes defaults and DOES NOT touch per_branch."""

    def test_writes_defaults(self, verbs) -> None:
        _run(verbs, "set-default", "sessions", "12")
        assert _rollover_section(verbs)["defaults"]["local"]["sessions"]["count"] == 12

    def test_leaves_per_branch_untouched(self, verbs) -> None:
        before = _rollover_section(verbs)["per_branch"]
        _run(verbs, "set-default", "sessions", "12")
        assert _rollover_section(verbs)["per_branch"] == before

    def test_observations_default(self, verbs) -> None:
        _run(verbs, "set-default", "observations", "9")
        assert _rollover_section(verbs)["defaults"]["observations"]["observations"]["count"] == 9

    def test_default_note_survives(self, verbs) -> None:
        before = _rollover_section(verbs)["defaults"]["_note"]
        _run(verbs, "set-default", "sessions", "12")
        assert _rollover_section(verbs)["defaults"]["_note"] == before

    def test_raising_the_default_turns_a_materialized_branch_into_an_override(self, verbs) -> None:
        """Marking is BY VALUE: the branch did not move, the default did."""
        _run(verbs, "set-default", "sessions", "12")
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 15
        assert limits["sessions"]["is_override"] is True


class TestPushRoundTrip:
    """set -> push must return the branch to defaults. Push is THE reset."""

    def test_set_then_push_restores_defaults(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 12

        result = verbs.loader.push_defaults_to_per_branch()
        assert result["success"] is True

        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 15
        assert limits["sessions"]["is_override"] is False

    def test_push_via_the_rollover_verb_also_restores(self, verbs) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
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
        raw["rollover"]["per_branch"]["memory"] = {"local": {"sessions": {"count": 22}}}
        verbs.path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def test_partial_file_key_does_not_deep_merge(self, verbs) -> None:
        self._plant_partial_local(verbs)
        limits = verbs.loader.get_effective_limits("memory")
        assert limits["sessions"]["count"] == 22
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

        # 20 sessions >= 22? No. 99 key_learnings has NO limit at all.
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
        _run(verbs, "set", "@memory", "sessions", "12")
        capsys.readouterr()
        _run(verbs, "get")
        out = _streams(capsys)
        assert "@memory" in out
        assert "All branches at defaults" not in out

    def test_non_deviating_branches_are_not_listed(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
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
        _run(verbs, "set", "@memory", "sessions", "12")
        capsys.readouterr()
        _run(verbs, "get", "@memory")
        assert "[OVERRIDE]" in _streams(capsys)

    def test_override_row_shows_both_numbers(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12")
        capsys.readouterr()
        _run(verbs, "get", "@memory")
        out = _streams(capsys)
        assert "12" in out
        assert "15" in out

    def test_get_branch_lists_all_three_types(self, verbs, capsys) -> None:
        _run(verbs, "get", "@memory")
        out = _streams(capsys)
        for entry_type in ("sessions", "key_learnings", "observations"):
            assert entry_type in out


# ===========================================================================
# 5. A help flag is never an instruction
# ===========================================================================

# A help flag beside --json, in every position. TestHelpOutranksJson asks what
# they print; TestHelpNeverWrites asks that none of them writes.
_HELP_WITH_JSON = [
    ("set", "@memory", "sessions", "12", "--help", "--json"),
    ("set", "@memory", "sessions", "12", "--json", "--help"),
    ("set", "--json", "@memory", "sessions", "12", "-h"),
    ("--json", "set", "@memory", "sessions", "12", "help"),
    ("set-default", "sessions", "12", "--json", "--help"),
]


class TestHelpNeverWrites:
    """The `rollover push --help` scar: a question must not be executed."""

    @pytest.mark.parametrize(
        "args",
        [
            ("set", "@memory", "sessions", "12", "--help"),
            ("set", "@memory", "sessions", "--help", "12"),
            ("set", "--help", "@memory", "sessions", "12"),
            ("--help", "set", "@memory", "sessions", "12"),
            ("set", "@memory", "sessions", "12", "-h"),
            ("set", "@memory", "sessions", "12", "help"),
            ("set-default", "sessions", "12", "--help"),
        ]
        + _HELP_WITH_JSON,
    )
    def test_file_is_byte_identical(self, verbs, args) -> None:
        """A help request, alone or beside --json, leaves the config byte-identical.

        The --json half was a second test of the same name and body in
        TestHelpOutranksJson; it was retired into this table in leg 7 (compass 443),
        so the twelve requests are still each run once.
        """
        before = verbs.path.read_bytes()
        assert _run(verbs, *args) is True
        assert verbs.path.read_bytes() == before

    def test_help_is_actually_printed(self, verbs, capsys) -> None:
        _run(verbs, "set", "@memory", "sessions", "12", "--help")
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
        _run(verbs, "set", "@memory", "sessions", "12")
        _run(verbs, "set-default", "sessions", "12")
        assert _snapshot(verbs.operator_path) == before

    def test_operator_config_unchanged_by_json_mode(self, verbs) -> None:
        before = _snapshot(verbs.operator_path)
        _run(verbs, "set", "@memory", "sessions", "12", "--json")
        _run(verbs, "set-default", "sessions", "12", "--json")
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


class TestHelpOutranksJson:
    """`--help --json` is still a question. The push scar, one flag later."""

    _COMBOS = _HELP_WITH_JSON
    # seedgo SHORT-TABLE (2026-08-31): same guard as _CASES above.
    assert len(_COMBOS) == 5

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
        _run(verbs, "set", "@memory", "sessions", "12")
        capsys.readouterr()
        assert _run_rollover(verbs, "push", "--json", "--help") is True
        assert _rollover_section(verbs)["per_branch"]["memory"]["local"]["sessions"]["count"] == 12

    def test_help_documents_the_flag(self, verbs, capsys) -> None:
        _run(verbs, "--help")
        assert "--json" in _streams(capsys)


class TestThePrintedExamplesAreLegalCommands:
    """A suggestion naming a command the next verb refuses teaches the wrong thing.

    The count ceiling (FPLAN-0593) turned `sessions 25` — printed in four
    refusals and the help block — into an illegal command overnight. Nothing
    caught it; three tests pinned the stale text and went red only because the
    string moved. This pins the PROPERTY instead of the string.
    """

    def test_every_example_count_in_a_refusal_is_within_its_ceiling(self):
        import re

        from aipass.memory.apps.handlers.json import config_loader
        from aipass.memory.apps.modules import rollover as rollover_mod
        from aipass.memory.apps.handlers.cli import config_content
        from aipass.memory.apps.modules import rollover_config

        # Every file an example can be printed from: the verbs (and every
        # refusal they print) moved to rollover_config.py, the routing stayed in
        # rollover.py, and the help page's TEXT moved to config_content.py — the
        # file holding `set @b sessions 12`. Leaving it out would let the one
        # page operators copy from drift past its own ceiling unpinned.
        source = "".join(
            Path(str(module.__file__)).read_text(encoding="utf-8")
            for module in (rollover_mod, rollover_config, config_content)
        )
        ceilings = config_loader.get_count_ceilings()
        examples = re.findall(r"config set(?:-default)?(?: @\w+)? (\w+) (\d+)", source)
        assert len(examples) >= 1, "no example commands found — the pin would pass vacuously"
        for entry_type, raw in examples:
            ceiling = ceilings.get(entry_type, {}).get("ceiling")
            if ceiling is None:
                continue
            assert int(raw) <= ceiling, f"example '{entry_type} {raw}' exceeds its ceiling of {ceiling}"


class TestTheConfigContentHandlerReturnsLinesAndNeverPrints:
    """handlers/cli/config_content.py: the help page and limit blocks as lines.

    FPLAN-0593 Phase 5. rollover_config.py sat at 657 lines against @seedgo's
    600-line module band, and its display code could not move to handlers/
    because handlers may not print. The TEXT could: this handler builds it and
    returns it, the module prints it. These pins hold both halves of that
    bargain — the handler never reaches a console, and the module prints exactly
    what the handler returns, so the page an operator reads is the page built.
    """

    def test_the_handler_never_imports_the_cli_service_or_prints(self):
        import ast

        from aipass.memory.apps.handlers.cli import config_content

        tree = ast.parse(Path(config_content.__file__).read_text(encoding="utf-8"))
        imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        }
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert not any(name.startswith("aipass.cli") for name in imported), imported
        assert "print" not in called, "a handler that prints is the defect this file exists to avoid"

    def test_every_block_is_a_list_of_strings_ending_in_a_blank_line(self):
        from aipass.memory.apps.handlers.cli import config_content as cc

        blocks = [
            cc.help_lines(1, 100, {"sessions": {"ceiling": 16, "file_key": "local", "budget_chars": 25000}}),
            cc.defaults_lines({"sessions": {"count": 15}}, ("sessions", "todos"), ("todos",)),
            cc.overrides_lines({}, ("sessions",)),
            cc.overrides_lines({"daemon": {"sessions": {"count": 12, "is_override": True}}}, ("sessions",)),
            cc.branch_limits_lines("memory", {"sessions": {"count": 12}}, ("sessions",), ()),
        ]
        for block in blocks:
            assert block and all(isinstance(line, str) for line in block)
            assert block[-1] == ""

    def test_the_help_bounds_print_the_ceilings_they_are_handed(self):
        # Data in, lines out: the handler reads no config of its own, so the
        # BOUNDS block cannot print a ceiling the refusal would contradict.
        from aipass.memory.apps.handlers.cli import config_content as cc

        lines = cc.help_lines(
            1, 100, {"observations": {"ceiling": 7, "file_key": "observations", "budget_chars": 15000}}
        )
        text = "\n".join(lines)

        assert "1-100 inclusive" in text
        assert "at most 7" in text and "budget 15,000 chars" in text

    def test_an_absent_count_says_unset_never_zero(self):
        from aipass.memory.apps.handlers.cli import config_content as cc

        line = cc.defaults_lines({"sessions": {"count": None}}, ("sessions",), ())[1]

        assert "unset" in line and " 0" not in line

    def test_the_module_prints_exactly_what_the_handler_returns(self, verbs, monkeypatch):
        """`config get` prints the defaults block the handler builds, line for line, after its banner.

        Through the command since leg 6 of DPLAN-0354: the handler is a recorder
        that answers two known lines, so the assert needs no private name.
        """
        from aipass.memory.apps.handlers.cli import config_content as cc
        from aipass.memory.apps.modules import rollover_config

        printed = []
        monkeypatch.setattr(rollover_config, "console", SimpleNamespace(print=lambda *a, **k: printed.append(a)))
        handed = []

        def defaults_lines(defaults, display_types, read_only_types):
            handed.append(defaults)
            return ["DEFAULTS LINE ONE", "DEFAULTS LINE TWO"]

        monkeypatch.setattr(cc, "defaults_lines", defaults_lines)

        _run(verbs, "get")

        texts = [args[0] for args in printed if args and isinstance(args[0], str)]
        assert texts[:2] == ["DEFAULTS LINE ONE", "DEFAULTS LINE TWO"]
        assert handed == [verbs.loader.get_default_limits()]
