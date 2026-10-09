# =================== AIPass ====================
# Name: test_trinity_check.py
# Description: Unit tests for trinity_check - trinity memory file standards checker
# Version: 1.6.0
# Created: 2026-08-25
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/aipass_standards/trinity_check.py and trinity_groups.py."""

# Tests for trinity_check -- the trinity memory file standards checker.
#
# The contract under test is devpulse ``dropbox/trinity_pattern.md``. The drift
# classes exercised by the regression suite are devpulse
# ``dropbox/trinity_audit/MASTER_LIST.md`` D1-D16, each named in its own test so
# a future blindness fails BY NAME rather than as an anonymous score drop.
#
# THE ONE LAW, and the reason this standard exists at all: a field the checker
# cannot measure is a VIOLATION, never a silent pass. The old gate measured an
# unparseable shape as zero chars and passed it fleet-wide for months.
# ``TestTheOneLaw`` exists so that cannot come back.
#
# Fixtures are synthetic: config and gold templates are pinned onto the module so
# a config edit on @memory's branch can never turn these tests red. The single
# exception is the fleet acceptance bar in ``TestFleetAcceptanceBar``, which is
# deliberately coupled to live branch state -- see its docstring.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.loads() of a well-formed trinity file; only the malformed ones are the subject

import copy
import json
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import ruff_check, template_check, trinity_groups
from aipass.seedgo.apps.handlers.audit import branch_audit
from aipass.seedgo.tests.support_trinity_check import (
    _BRANCH,
    _CONFIG,
    _TEMPLATES,
    _assert_failed,
    _canonical_local,
    _canonical_observations,
    _group,
    _write_branch,
)

pytestmark = pytest.mark.usefixtures("_mock_infrastructure")

_GROUP_NAMES = (
    "Entry shapes",
    "Top-level keys",
    "Ordering & numbering",
    "Char caps",
    "File set",
    "Meta lines & _usage",
    "Receipt",
    "Freshness",
)

# Fleet acceptance bar -- see TestFleetAcceptanceBar for why this is coupled
# to live state and what to do when a branch is migrated.
_CANONICAL_OBSERVATION_BRANCHES = frozenset(
    {
        "ai_mail",
        "aipass",
        "api",
        "backup",
        "canary",
        "cli",
        "commons",
        "daemon",
        "devpulse",
        "drone",
        "flow",
        "hooks",
        "memory",
        "prax",
        "seedgo",
        "skills",
        "spawn",
        "trigger",
    }
)


def _shapes(trinity, config=None, branch: str = _BRANCH) -> dict:
    """The entry shape the checker derives from a config -- the fixture's by default.

    Nothing in this file spells a shape out. The tests move the CONFIG and
    watch the shape follow it, which is the whole of FPLAN-0593 Phase 2.
    """
    return trinity.entry_shapes(_CONFIG if config is None else config, branch)


def _repo_root() -> Path | None:
    """Walk up from this file to the repo root -- the dir holding src/aipass."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "aipass").is_dir():
            return parent
    return None


def _fleet_dir() -> Path | None:
    """The directory holding the 18 citizens, or None outside this repo."""
    root = _repo_root()
    return None if root is None else root / "src" / "aipass"


# ===========================================================================
# A. THE ONE LAW -- fail loud, never silent-pass
# ===========================================================================


class TestTheOneLaw:
    """Nothing unmeasurable may ever produce a passing group."""

    def test_missing_trinity_dir_fails_every_group(self, trinity, tmp_path):
        # The registry marks this a LIVE installation. Without it the tree is
        # indistinguishable from a fresh clone, where an absent .trinity is an
        # environment fact rather than a violation -- see
        # TestACleanCheckoutIsNotAViolatingFleet.
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")
        branch = tmp_path / "nobody"
        branch.mkdir()

        result = trinity.check_branch(str(branch))

        assert result["passed"] is False
        assert result["score"] == 0
        for check in result["checks"]:
            assert check["passed"] is False, f"{check['name']} passed with no .trinity/ at all"
            assert check["score"] == 0, f"{check['name']} scored {check['score']} with no .trinity/"
            assert check["message"], f"{check['name']} failed without saying why"

    def test_missing_trinity_dir_names_the_missing_directory(self, trinity, tmp_path):
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")
        branch = tmp_path / "nobody"
        branch.mkdir()

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "File set"), ".trinity", "not found")

    def test_corrupt_local_json_fails_and_never_passes_a_group_that_reads_it(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local='{"document_metadata": {,,, malformed')

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "local.json", "not valid json")
        _assert_failed(_group(result, "Entry shapes"), "local.json")
        _assert_failed(_group(result, "Char caps"), "local.json")
        _assert_failed(_group(result, "Freshness"), "local.json")
        _assert_failed(_group(result, "Meta lines & _usage"), "local.json")

    def test_corrupt_observations_json_fails_and_never_passes(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, observations="not json at all")

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "observations.json", "not valid json")
        _assert_failed(_group(result, "Entry shapes"), "observations.json")
        _assert_failed(_group(result, "Char caps"), "observations.json")
        _assert_failed(_group(result, "Freshness"), "observations.json")

    def test_empty_file_is_not_valid_json_and_fails_loud(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="")

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "local.json", "not valid json")

    def test_top_level_list_is_a_violation_not_an_empty_object(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="[]")

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "top level must be an object", "list")
        _assert_failed(_group(result, "Entry shapes"), "local.json")

    def test_observations_top_level_list_is_a_violation(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, observations='[{"number": 1}]')

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "top level must be an object", "list")

    def test_missing_local_file_fails_every_group_that_reads_it(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local=None)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Top-level keys"), "local.json", "not found")
        _assert_failed(_group(result, "Entry shapes"), "local.json")
        _assert_failed(_group(result, "File set"), "missing local.json")

    def test_list_note_is_a_type_violation_in_entry_shapes(self, trinity, tmp_path):
        observations = _canonical_observations()
        observations["observations"][0]["note"] = [{"title": "a", "detail": "b"}]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "note must be str", "list")

    def test_list_note_is_unmeasurable_in_char_caps_not_zero_chars(self, trinity, tmp_path):
        """The original sin: a list note len()-ed to 0 and waved through."""
        observations = _canonical_observations()
        observations["observations"][0]["note"] = [{"title": "a", "detail": "b"}]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "note", "unmeasurable", "found list")

    def test_renamed_cap_field_is_flagged_not_read_as_empty_string(self, trinity, tmp_path):
        local = _canonical_local()
        local["key_learnings"][0] = {
            "number": 2,
            "date": "2026-08-24",
            "learning": "merged key+value into one blob",
        }
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "unexpected field 'learning'")
        _assert_failed(_group(result, "Char caps"), "value", "unmeasurable", "absent")

    def test_entry_without_number_is_flagged_by_ordering_not_skipped(self, trinity, tmp_path):
        local = _canonical_local()
        local["todos"] = [{"date": "2026-08-24", "task": "x", "priority": "low", "status": "open"}]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Ordering & numbering"), "no usable 'number'", "absent")

    def test_entry_that_is_not_a_dict_is_flagged_by_every_entry_group(self, trinity, tmp_path):
        local = _canonical_local()
        local["todos"] = ["just a string"]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "entry must be an object", "str")
        _assert_failed(_group(result, "Ordering & numbering"), "no usable number")
        _assert_failed(_group(result, "Char caps"), "entry must be an object")

    def test_container_that_is_not_a_list_is_flagged(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"] = {"1": {"summary": "a dict of sessions"}}
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "'sessions' must be a list", "dict")
        _assert_failed(_group(result, "Ordering & numbering"), "must be a list")
        _assert_failed(_group(result, "Char caps"), "must be a list")

    def test_missing_container_is_flagged_not_skipped(self, trinity, tmp_path):
        local = _canonical_local()
        del local["key_learnings"]
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Entry shapes"), "'key_learnings' section missing")

    def test_unreadable_config_fails_char_caps_rather_than_assuming_numbers(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "load_memory_config", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Char caps"), "memory.config.json", "never assumed")
        assert _group(result, "Char caps")["score"] == 0

    def test_unreadable_config_fails_meta_lines_rather_than_assuming_numbers(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "load_memory_config", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "memory.config.json", "never assumed")
        assert _group(result, "Meta lines & _usage")["score"] == 0

    def test_unreadable_templates_fail_meta_lines_rather_than_assuming_prose(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "template", "prose is never assumed")
        assert _group(result, "Meta lines & _usage")["score"] == 0

    def test_template_without_placeholder_prose_fails_loud(self, trinity, tmp_path, monkeypatch):
        broken = copy.deepcopy(_TEMPLATES)
        broken["local"]["sessions_meta"] = "no placeholder token here"
        monkeypatch.setattr(trinity, "_load_templates", lambda: copy.deepcopy(broken))
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Meta lines & _usage"), "template")

    def test_unreadable_templates_fail_the_receipt_version_check(self, trinity, tmp_path, monkeypatch):
        monkeypatch.setattr(trinity, "_load_templates", lambda: None)
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        _assert_failed(_group(result, "Receipt"), "gold templates unreadable")

    def test_validate_entry_shape_refuses_an_unknown_section(self, trinity):
        """Mutant: the problem drops the section's name, in trinity_groups.py — killed."""
        problems = trinity.validate_entry_shape("nonexistent", {"number": 1}, _shapes(trinity))

        assert problems == ["unknown section 'nonexistent' -- no canonical shape to measure against"]

    def test_validate_entry_shape_refuses_a_non_dict_entry(self, trinity):
        assert trinity.validate_entry_shape("observations", ["a", "list"], _shapes(trinity)) == [
            "entry must be an object, found list"
        ]

    def test_validate_entry_shape_rejects_bool_masquerading_as_number(self, trinity):
        problems = trinity.validate_entry_shape(
            "observations", {"number": True, "date": "2026-08-25", "note": "x", "tags": []}, _shapes(trinity)
        )

        assert any("number must be int" in problem for problem in problems)


# ===========================================================================
# CI. A clean checkout is an environment fact, not 18 simultaneous violations
# ===========================================================================


class TestACleanCheckoutIsNotAViolatingFleet:
    """CI ran seedgo-audit on a GitHub runner and every one of the 18 branches
    came back trinity 0 / FAILED. Nothing was wrong with the fleet: .trinity/
    and AIPASS_REGISTRY.json are BOTH gitignored by design -- memories never
    ship -- so a fresh clone has no memory files at all and the checker refused
    every group, which branch_audit turned into a score of 0.

    THE ONE LAW says unmeasurable is REFUSED, never zeroed, and a whole SPECIES
    missing on a tree that also has no registry is an environment fact. So the
    standard reports itself not-applicable for the run and is left out of the
    gating average entirely -- not scored 0 (a lie about the branch) and not
    scored 100 (a lie about the measurement).

    The discrimination is deliberately conservative: BOTH signals must be
    absent. A live installation missing .trinity on one branch still has the
    registry, so that stays exactly the violation it always was.
    """

    @staticmethod
    def _ci_tree(root: Path, name: str = _BRANCH) -> Path:
        """A branch as a fresh clone has it: code, no memories, no registry."""
        branch = root / name
        (branch / "apps").mkdir(parents=True)
        return branch

    def test_a_clean_checkout_is_not_applicable_rather_than_zero(self, trinity, tmp_path):
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result["not_applicable"] is True
        assert result["score"] != 0

    def test_a_clean_checkout_does_not_report_a_failure(self, trinity, tmp_path):
        """FAILED on a clean clone is what turned CI red."""
        assert trinity.check_branch(str(self._ci_tree(tmp_path)))["passed"] is not False

    def test_the_skip_announces_itself_loudly(self, trinity, tmp_path):
        """A silent skip is how a broken standard hides. Say why, by name."""
        lines = trinity.check_branch_info(str(self._ci_tree(tmp_path)))

        assert any("not measured" in line.lower() for line in lines)
        assert any("checkout" in line.lower() for line in lines)

    def test_a_live_installation_missing_trinity_is_still_a_violation(self, trinity, tmp_path):
        """The whole point of the discrimination -- a registry means a real
        install, so an absent .trinity there is a real finding.
        """
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}\n", encoding="utf-8")
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result.get("not_applicable") is not True
        assert result["passed"] is False

    def test_a_sibling_with_memories_also_means_a_live_installation(self, trinity, tmp_path):
        """Registry absent but the fleet clearly has citizens -- not a clone."""
        _write_branch(tmp_path, name="othercitizen")
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result.get("not_applicable") is not True
        assert result["passed"] is False

    def test_a_populated_branch_is_scored_normally(self, trinity, tmp_path):
        """Over-refusal guard: the escape hatch must not swallow real runs."""
        result = trinity.check_branch(str(_write_branch(tmp_path)))

        assert result.get("not_applicable") is not True
        assert result["score"] == 100

    def test_the_spawn_template_trinity_does_not_look_like_a_citizen(self, trinity, tmp_path):
        """The ONE .trinity that DOES ship: spawn/templates/*/.trinity is
        un-ignored in .gitignore. It sits two levels down, not at
        <fleet>/<branch>/.trinity, so it must not make a clone look live.
        """
        template = tmp_path / "spawn" / "templates" / "citizen" / ".trinity"
        template.mkdir(parents=True)
        (template / "local.json").write_text("{}\n", encoding="utf-8")

        assert trinity.check_branch(str(self._ci_tree(tmp_path)))["not_applicable"] is True

    def test_a_not_applicable_result_still_names_the_standard(self, trinity, tmp_path):
        """Downstream readers key on it; a bare dict would break them."""
        result = trinity.check_branch(str(self._ci_tree(tmp_path)))

        assert result["standard"] == "TRINITY"
        assert isinstance(result.get("checks"), list)


# ===========================================================================
# Marker 7. The gate, pinned so it cannot be downgraded by accident
# ===========================================================================


class TestTrinityIsAGateNotAReport:
    """Marker 7 asked for a REPORT -> GATE flip. Measured first: trinity was
    already a gate and has been since it shipped. In this standards family a
    gate is expressed by three things together, and trinity has all three --
    so there was nothing to flip, and these tests exist so it stays that way.

    The family's own vocabulary:
      * ``ADVISORY = True`` marks a standard that never gates (template). ruff
        gated from 2026-09-25 (owner 00:33), once CI ruff was green fleet-wide.
        trinity does not set it, so it counts in the gating average.
      * ``passed`` is the block signal. trinity requires a PERFECT 100, which
        is stricter than every other branch_level standard -- json_handler,
        the precedent named in the brief, passes at 75.
      * failing groups surface in ``checks[]``, which the audit lifts into
        ``failed_checks``.

    Each is pinned separately because each could be lost on its own.
    """

    def test_trinity_is_not_advisory(self, checker):
        """ADVISORY = True would silently drop trinity out of the average."""
        assert getattr(checker, "ADVISORY", False) is False

    def test_advisory_is_how_this_family_says_non_gating(self, checker):
        """The pin is only meaningful if ADVISORY still means what it means."""
        assert getattr(ruff_check, "ADVISORY", False) is False
        assert template_check.ADVISORY is True

    def test_a_gating_standard_is_counted_in_the_average(self, checker):
        """The audit computes its average over non-ADVISORY standards only."""
        source = Path(branch_audit.__file__).read_text(encoding="utf-8")
        assert 'getattr(mod, "ADVISORY", False) is True' in source
        assert "gating_scores = {k: v for k, v in scores.items() if k not in advisory_standards}" in source

    def test_anything_short_of_perfect_fails(self, trinity, tmp_path):
        """Not a threshold: 99 blocks. The push proved 100 is reachable."""
        local = _canonical_local()
        local["document_metadata"]["limits"] = {}
        branch = _write_branch(tmp_path, local=local)

        result = trinity.check_branch(str(branch))

        assert 0 < result["score"] < 100
        assert result["passed"] is False

    def test_a_fully_canonical_branch_passes(self, trinity, tmp_path):
        """The gate must be satisfiable, or it is a wall."""
        result = trinity.check_branch(str(_write_branch(tmp_path)))

        assert result["score"] == 100
        assert result["passed"] is True

    def test_failing_groups_reach_the_audits_failed_checks_channel(self, trinity, tmp_path):
        """What the audit lifts into failed_checks is checks[] with passed False."""
        branch = _write_branch(tmp_path, local={"document_metadata": {}})

        result = trinity.check_branch(str(branch))

        assert [c for c in result["checks"] if not c["passed"]]


# ===========================================================================
# D. The fleet acceptance bar -- the red-first proof, as a test
# ===========================================================================


class TestFleetAcceptanceBar:
    """The build brief's blindness guard, read off the LIVE fleet.

    INTENTIONALLY COUPLED TO LIVE STATE. Exactly 6 of the 18 citizens are
    fully canonical on OBSERVATIONS entry shape today; if more than six come
    back clean the checker has gone blind somewhere, and if fewer do a branch
    regressed. When a branch is migrated this expectation is UPDATED to the new
    clean set -- never deleted and never loosened, because the day it stops
    being an exact equality is the day it stops proving anything.
    """

    @staticmethod
    def _observation_problems(trinity, path: Path) -> list[str]:
        """Every entry-shape violation in one live observations.json.

        Reading goes through the checker's own reader, which reports a bad
        file rather than raising -- so an unparseable branch counts as
        drifted instead of blowing up the guard.
        """
        result = trinity._read_json_file(path)
        if result["error"] is not None:
            return [f"{path.name}: {result['error']}"]
        entries = result["data"].get("observations")
        if not isinstance(entries, list):
            return [f"{path.name} observations is {type(entries).__name__}, not a list"]
        shapes = _shapes(trinity)
        problems: list[str] = []
        for entry in entries:
            problems.extend(trinity.validate_entry_shape("observations", entry, shapes))
        return problems

    def test_exactly_six_citizens_are_canonical_on_observations(self, trinity):
        fleet = _fleet_dir()
        if fleet is None or not fleet.is_dir():
            pytest.skip("fleet directory src/aipass/ not present -- live-state guard skipped")

        clean: set[str] = set()
        audited: set[str] = set()
        for branch_dir in sorted(fleet.iterdir()):
            path = branch_dir / ".trinity" / "observations.json"
            if not path.is_file():
                continue
            audited.add(branch_dir.name)
            if not self._observation_problems(trinity, path):
                clean.add(branch_dir.name)

        if not audited:
            pytest.skip("no live .trinity/observations.json found -- live-state guard skipped")

        assert clean == set(_CANONICAL_OBSERVATION_BRANCHES), (
            "the clean set moved: update _CANONICAL_OBSERVATION_BRANCHES to the "
            "new migrated set, or find out why the checker stopped seeing drift"
        )

    def test_the_drifted_citizens_are_still_seen_as_drifted(self, trinity):
        fleet = _fleet_dir()
        if fleet is None or not fleet.is_dir():
            pytest.skip("fleet directory src/aipass/ not present -- live-state guard skipped")

        drifted = {}
        for branch_dir in sorted(fleet.iterdir()):
            path = branch_dir / ".trinity" / "observations.json"
            if not path.is_file() or branch_dir.name in _CANONICAL_OBSERVATION_BRANCHES:
                continue
            drifted[branch_dir.name] = self._observation_problems(trinity, path)

        if not drifted:
            pytest.skip("no drifted citizens on disk -- live-state guard skipped")

        blind = [name for name, problems in drifted.items() if not problems]
        assert blind == [], f"the checker went blind on {blind}"


# ===========================================================================
# E. Scoring mechanics
# ===========================================================================


class TestScoringMechanics:
    """Weights, group set, and the weighted mean."""

    def test_audit_scope_is_branch_level(self, trinity):
        assert trinity.AUDIT_SCOPE == "branch_level"

    def test_group_weights_sum_to_one_hundred(self, trinity):
        assert sum(trinity.GROUP_WEIGHTS.values()) == 100

    def test_group_weights_hold_the_eight_pinned_names(self, trinity):
        assert set(trinity.GROUP_WEIGHTS) == set(_GROUP_NAMES)

    def test_group_weights_are_the_pinned_numbers(self, trinity):
        """Todos hygiene retired 2026-09-15 (DPLAN-0345); its 5 moved to Entry shapes with the defect."""
        assert trinity.GROUP_WEIGHTS == {
            "Entry shapes": 30,
            "Top-level keys": 15,
            "Ordering & numbering": 12,
            "Char caps": 12,
            "File set": 10,
            "Meta lines & _usage": 10,
            "Receipt": 8,
            "Freshness": 3,
        }

    def test_shape_weighs_heaviest_and_freshness_lightest(self, trinity):
        weights = trinity.GROUP_WEIGHTS
        assert weights["Entry shapes"] == max(weights.values())
        assert weights["Freshness"] == min(weights.values())

    def test_check_branch_returns_the_pinned_result_shape(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert isinstance(result, dict)
        assert result["standard"] == "TRINITY"
        assert isinstance(result["score"], int)
        assert isinstance(result["passed"], bool)
        assert isinstance(result["checks"], list)

    def test_check_branch_returns_exactly_eight_named_checks(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert len(result["checks"]) == 8
        assert [check["name"] for check in result["checks"]] == list(_GROUP_NAMES)

    def test_every_check_carries_the_four_pinned_keys(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="{ broken")

        result = trinity.check_branch(str(branch))

        # Floor, measured: eight groups are always reported, even for a branch
        # whose local.json will not parse. Without it an empty checks list would
        # walk this row green having read no key at all.
        assert len(result["checks"]) == 8
        for check in result["checks"]:
            assert set(check) == {"name", "passed", "message", "score"}
            assert isinstance(check["score"], int)
            assert 0 <= check["score"] <= 100

    def test_overall_score_is_the_weighted_sum_of_group_subscores(self, trinity, tmp_path):
        local = _canonical_local()
        local["sessions"][0]["summary"] = "s" * 400
        local["document_metadata"]["last_updated"] = "2026-01-02"
        branch = _write_branch(tmp_path, local=local, receipt=None)

        result = trinity.check_branch(str(branch))

        weights = trinity.GROUP_WEIGHTS
        expected = round(sum(check["score"] * weights[check["name"]] for check in result["checks"]) / 100)
        assert result["score"] == expected

    def test_passed_is_true_only_at_one_hundred(self, trinity, tmp_path):
        clean_root = tmp_path / "clean"
        dirty_root = tmp_path / "dirty"
        local = _canonical_local()
        local["todos"][0]["status"] = "done"
        clean = trinity.check_branch(str(_write_branch(clean_root)))
        dirty = trinity.check_branch(str(_write_branch(dirty_root, local=local)))

        assert clean["score"] == 100 and clean["passed"] is True
        assert dirty["passed"] is False
        assert dirty["score"] < 100

    def test_a_single_bad_entry_in_a_hundred_never_rounds_up_to_a_pass(self, trinity, tmp_path):
        """99.75 must not become 100 -- a failure is never rounded into a pass."""
        observations = _canonical_observations()
        observations["observations"] = [
            {
                "number": number,
                "date": "2026-08-20",
                "note": f"observation {number}",
                "tags": [],
            }
            for number in range(100, 0, -1)
        ]
        observations["observations"][0]["session"] = 12
        del observations["observations"][0]["tags"]
        branch = _write_branch(tmp_path, observations=observations)

        result = trinity.check_branch(str(branch))

        assert _group(result, "Entry shapes")["score"] == 99
        assert result["score"] == 99
        assert result["passed"] is False

    def test_a_failing_group_never_scores_one_hundred(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="{ broken")

        result = trinity.check_branch(str(branch))

        # The failing groups are selected first and counted, because the guard
        # this replaces asserted nothing at all if every group happened to pass.
        # Measured on this fixture: 6 of the 8 groups fail on an unparseable
        # local.json; File set and Receipt are the two that survive it.
        failing = [check for check in result["checks"] if not check["passed"]]
        assert len(failing) == 6, f"expected 6 failing groups, got {[c['name'] for c in failing]}"
        for check in failing:
            assert check["score"] < 100


class TestTheCacheWatchesMemorysFiles:
    """external_inputs() names what the incremental audit cache must watch outside the branch.

    2026-09-15: a memory.config.json or template edit left cached Trinity rows
    scored from before it. The paths come from the same helpers the loaders
    read, so the cache and the checker cannot name different files.
    """

    @staticmethod
    def _memory(tmp_path, *templates: str) -> Path:
        memory_dir = tmp_path / "memory"
        config = memory_dir / "memory_json" / "custom_config" / "memory.config.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"marker": "config"}', encoding="utf-8")
        (memory_dir / "templates").mkdir()
        for name in templates:
            (memory_dir / "templates" / name).write_text(json.dumps({"marker": name}), encoding="utf-8")
        return memory_dir

    def test_the_inputs_are_the_files_the_loaders_read(self, checker, tmp_path, monkeypatch):
        memory_dir = self._memory(tmp_path, "LOCAL.template.json", "OBSERVATIONS.template.json")
        monkeypatch.setattr(checker, "_memory_dir", lambda: memory_dir)

        paths = checker.external_inputs()

        assert paths == [
            memory_dir / "memory_json" / "custom_config" / "memory.config.json",
            memory_dir / "templates" / "LOCAL.template.json",
            memory_dir / "templates" / "OBSERVATIONS.template.json",
        ]
        assert checker.load_memory_config() == {"marker": "config"}
        assert checker._load_templates() == {
            "local": {"marker": "LOCAL.template.json"},
            "observations": {"marker": "OBSERVATIONS.template.json"},
        }

    def test_an_absent_file_is_left_out(self, checker, tmp_path, monkeypatch):
        memory_dir = self._memory(tmp_path, "LOCAL.template.json")
        monkeypatch.setattr(checker, "_memory_dir", lambda: memory_dir)

        names = [path.name for path in checker.external_inputs()]

        assert names == ["memory.config.json", "LOCAL.template.json"]

    def test_no_memory_branch_watches_nothing(self, checker, monkeypatch):
        monkeypatch.setattr(checker, "_memory_dir", lambda: None)

        assert checker.external_inputs() == []

    def test_the_live_checker_names_memorys_real_files(self, checker):
        names = sorted(path.name for path in checker.external_inputs())

        assert names == ["LOCAL.template.json", "OBSERVATIONS.template.json", "memory.config.json"]


# ===========================================================================
# G. Bypass is deliberately absent
# ===========================================================================


class TestBypassIsDeliberatelyAbsent:
    """The contract: "None for shape rules, by design."

    A bypassable memory standard recreates the drift it exists to end. These
    tests pin the design decision so nobody "fixes" it into existence later.
    """

    _RULES = [
        {"file": ".trinity/local.json", "standard": "trinity", "reason": "would suppress the standard"},
        {"file": ".trinity/observations.json", "standard": "trinity", "reason": "would suppress the standard"},
        {"file": "", "standard": "trinity", "reason": "branch-wide suppression attempt"},
        {"standard": "trinity", "reason": "standard-level suppression attempt"},
    ]

    def test_bypass_rules_do_not_raise_a_failing_score(self, trinity, tmp_path):
        local = _canonical_local()
        local["key_learnings"][0] = {"number": 2, "date": "2026-08-24", "learning": "merged blob"}
        branch = _write_branch(tmp_path, local=local)

        without = trinity.check_branch(str(branch))
        with_rules = trinity.check_branch(str(branch), bypass_rules=self._RULES)

        assert with_rules == without
        assert with_rules["passed"] is False

    def test_bypass_rules_leave_every_group_untouched(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, local="{ broken", receipt=None)

        without = trinity.check_branch(str(branch))
        with_rules = trinity.check_branch(str(branch), bypass_rules=self._RULES)

        assert with_rules["checks"] == without["checks"]
        assert with_rules["score"] == without["score"]

    def test_a_clean_branch_is_unaffected_by_bypass_rules(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        assert trinity.check_branch(str(branch), bypass_rules=self._RULES) == trinity.check_branch(str(branch))

    def test_an_empty_bypass_list_and_none_agree(self, trinity, tmp_path):
        branch = _write_branch(tmp_path, receipt=None)

        assert trinity.check_branch(str(branch), bypass_rules=[]) == trinity.check_branch(
            str(branch), bypass_rules=None
        )

    def test_the_checker_never_imports_the_bypass_helper(self, trinity):
        """No bypass import, and no call to one -- only the prose that says why."""
        source = Path(trinity.__file__).read_text(encoding="utf-8")
        imports = [line.strip() for line in source.splitlines() if line.startswith(("import ", "from "))]

        assert not any("bypass" in line for line in imports), imports
        assert not hasattr(trinity, "is_bypassed")
        assert "trinity contract" in trinity.check_branch.__doc__.lower()


# ===========================================================================
# H. The silent-pass hole this checker was almost born with -- regression guard
# ===========================================================================


class TestKnownSilentPassHole:
    """The checker's own violation of THE ONE LAW, found by test and closed.

    Shipped state of _records_check dropped its violation records whenever the
    entry denominator came out clean, and _cap_probe's config-has-no-spec
    record contributes nothing to that denominator when the container is empty.
    Char caps answered 'All 0 entries are within their configured caps',
    passed=True, score=100 -- a silent pass of something the checker had just
    said it could not measure, inside the standard written to end exactly that.
    Fixed in _records_check: records decide whether, the denominator only
    decides how bad. This test is the guard, not a bug report.
    """

    def test_char_caps_must_not_pass_when_the_config_has_no_spec(self, trinity, tmp_path, monkeypatch):
        specless = copy.deepcopy(_CONFIG)
        specless["entry_limits"]["entry_types"] = {}
        local = _canonical_local()
        observations = _canonical_observations()
        for section in ("todos", "key_learnings", "sessions"):
            local[section] = []
        observations["observations"] = []
        branch = _write_branch(tmp_path, local=local, observations=observations)

        monkeypatch.setattr(trinity, "load_memory_config", lambda: copy.deepcopy(specless))

        result = trinity.check_branch(str(branch))

        check = _group(result, "Char caps")
        assert check["passed"] is False, f"silent pass: {check['message']}"
        assert check["score"] < 100


# ===========================================================================
# A RELATIVE BRANCH PATH NAMES THE SAME BRANCH AN ABSOLUTE ONE DOES
# ===========================================================================


class TestARelativeBranchPathStillNamesTheBranch:
    """Found while verifying my own memories after a write: running the checker
    on "." reported score 93 with 'document_name seedgo.LOCAL does not name
    branch ' and 'managed_by seedgo != branch directory name ' -- note the
    empty branch in both messages. The same tree on an absolute path scored
    100.

    Cause: _build_context took branch_path.name verbatim, and Path(".").name
    is the empty string. Every relative invocation -- a caller standing in the
    branch, a test helper, anything shelling out with cwd -- silently measured
    Top-level keys against a branch called "". The failure is worse than a
    crash because it looks like real drift and names files that are correct.

    Fix: resolve the path before deriving the name. These tests pin that a
    relative and an absolute path answer identically.
    """

    def test_a_relative_path_scores_the_same_as_an_absolute_one(self, trinity, tmp_path, monkeypatch):
        branch = _write_branch(tmp_path)

        absolute = trinity.check_branch(str(branch))
        monkeypatch.chdir(branch)
        relative = trinity.check_branch(".")

        assert relative["score"] == absolute["score"]
        assert relative["passed"] == absolute["passed"]

    def test_dot_does_not_invent_an_empty_branch_name(self, trinity, tmp_path, monkeypatch):
        branch = _write_branch(tmp_path)
        monkeypatch.chdir(branch)

        result = trinity.check_branch(".")

        top = _group(result, "Top-level keys")
        assert "branch " not in top["message"], f"empty branch name leaked: {top['message']}"
        assert top["passed"] is True

    def test_a_trailing_dot_segment_resolves_to_the_branch(self, trinity, tmp_path):
        """Green before the fix as well as after, and kept deliberately: it
        pins WHY the bug was only ever a bare "." -- pathlib drops interior and
        trailing "." segments when it parses, so "<branch>/." already carried
        the name. Without this the reader would reasonably assume every dotted
        form was broken.
        """
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(f"{branch}/.")

        assert result["score"] == 100


# ===========================================================================
# THE SPLIT: trinity_groups holds the nine, trinity_check holds the engine
# ===========================================================================


class TestTheGroupSplitKeepsEveryGroup:
    """trinity_check.py crossed the 1500-line architecture cap during the
    marker-7 work, so the group checkers moved to trinity_groups.py on
    2026-08-27. A relocation, not a redesign -- but the one regression a split
    invites is a group quietly going missing, and a missing group does not
    fail loudly: the weighted mean simply divides by less and the branch scores
    HIGHER. That is the exact shape of a silent pass this standard exists to
    end, so it gets pinned rather than assumed.
    """

    def test_all_groups_returns_every_weighted_group_in_reporting_order(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)
        ctx = trinity._build_context(branch)

        names = [check["name"] for check in trinity_groups.all_groups(ctx)]

        assert names == [
            "Entry shapes",
            "Top-level keys",
            "Ordering & numbering",
            "Char caps",
            "File set",
            "Meta lines & _usage",
            "Receipt",
            "Freshness",
        ]
        assert set(names) == set(trinity.GROUP_WEIGHTS), "a group is weighted but never run, or run but never weighted"

    def test_check_branch_reports_the_same_eight(self, trinity, tmp_path):
        branch = _write_branch(tmp_path)

        result = trinity.check_branch(str(branch))

        assert [c["name"] for c in result["checks"]] == list(trinity.GROUP_WEIGHTS)

    def test_the_engine_does_not_reach_past_the_public_entry_point(self, trinity):
        """The nine used to be imported by name into the engine, which is how a
        forgotten group becomes possible. Pin that the engine holds one handle.
        """
        source = Path(trinity.__file__).read_text(encoding="utf-8")

        assert "all_groups(ctx)" in source
        assert "_group_entry_shapes" not in source, "engine reaches past all_groups again"
