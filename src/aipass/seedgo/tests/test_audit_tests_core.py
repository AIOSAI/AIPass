"""Tests for the audit-tests lane core: spine, refusal vocabulary, laws.

These pin the three things the design argues are load-bearing, and each was
written to fail against an implementation that got it wrong:

  1. The group list COMPOSES (spine + namespaced adapter groups) rather than
     equalling a constant. Revision 1's constant is the one shape the design
     review called a true rebuild trigger.
  2. A refusal is never a score, and the fleet form ranks an UNPROVEN harness
     as worse than an honest gate failure.
  3. Every law bites. A law that cannot fail is decoration, and a suite that
     cannot fail is the exact species this whole lane exists to catch (L0).

Law S9 and the rev-4 group contracts are pinned even though the groups they
bind report `not_applicable: "not built"` — that is the point of writing a
contract before the capability, and an untested contract is a promise.
"""

# =================== META ====================
# Name: test_audit_tests_core.py
# Description: Core pins for the audit-tests lane (spine, refusal, laws)
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

# seedgo:bypass standard=architecture reason="test files live in tests/, not apps/"
# seedgo:bypass standard=encapsulation reason="tests import handlers directly for unit testing"

import pytest

from aipass.seedgo.apps.handlers.audit_tests import laws, refusal, spine


# =============================================================================
# HELPERS
# =============================================================================


def _lawful_document(**overrides) -> dict:
    """A minimal artifact that passes every law, for mutation by each test.

    Deliberately built from the real spine rather than a hand-written list, so
    a change to CORE_SPINE that breaks the fixture surfaces here instead of
    silently making every test below vacuous.
    """
    groups = {name: spine.spine_document(name) for name in spine.CORE_SPINE}
    groups["hygiene"] = {
        "tier": "exec",
        "status": "measured",
        "score": 100,
        "budget_seconds": 600,
        "elapsed_seconds": 12.5,
        "gate_coverage": {
            "mechanism": "sys.addaudithook (PEP 578), per-interpreter",
            # Written "open [write]" rather than with parentheses on purpose: my
            # own checklist pattern check reads the parenthesised form inside a
            # STRING as a real call and flags a missing encoding. A live example
            # of Law M1 - static nominates, it does not convict - caught by the
            # instrument's own suite on its first day. Logged for a proper fix.
            "observed": ["open [write]", "subprocess.Popen", "sqlite3.connect"],
            "blind": ["writes by child processes"],
            "child_processes_spawned": 0,
            "sqlite3_connections": {"file_backed": 0, "memory": 0, "read_only": 0},
        },
    }
    groups["ai_advisory"]["kind"] = "nominate_only"

    document = {
        "artifact_version": "audit-tests/1",
        "status": "published",
        "group_list": list(spine.CORE_SPINE),
        "groups": groups,
        "retired_groups": [],
        "group_baseline": "first run for this pair",
        "cache": {"served_from_cache": False, "not_fingerprinted": []},
    }
    document.update(overrides)
    return document


# =============================================================================
# THE SPINE - composition, not a constant
# =============================================================================


class TestComposition:
    """The group list must be able to GROW without touching the core."""

    def test_adapter_groups_are_namespaced_and_appended(self):
        composed = spine.compose_group_list("pytest", ["static_ruff_pt", "scoped_survival"])

        assert composed[: len(spine.CORE_SPINE)] == list(spine.CORE_SPINE)
        assert composed[len(spine.CORE_SPINE) :] == [
            "pytest.static_ruff_pt",
            "pytest.scoped_survival",
        ]

    def test_a_second_ecosystem_needs_no_core_change(self):
        """The property the rebuild trigger destroyed: two ecosystems coexist."""
        python_groups = spine.compose_group_list("pytest", ["static_ruff_pt"])
        rust_groups = spine.compose_group_list("cargo", ["static_clippy"])

        assert "pytest.static_ruff_pt" in python_groups
        assert "cargo.static_clippy" in rust_groups
        assert "pytest.static_ruff_pt" not in rust_groups
        for composed in (python_groups, rust_groups):
            assert composed[: len(spine.CORE_SPINE)] == list(spine.CORE_SPINE)

    def test_an_adapter_may_not_shadow_a_spine_group(self):
        """A shadowed spine group would VANISH from the list without a ruling."""
        with pytest.raises(ValueError, match="spine is reserved"):
            spine.compose_group_list("pytest", ["hygiene"])

    def test_an_adapter_may_not_declare_the_same_group_twice(self):
        with pytest.raises(ValueError, match="duplicate"):
            spine.compose_group_list("pytest", ["scoped_survival", "scoped_survival"])

    def test_hygiene_is_the_only_scored_group(self):
        assert spine.SCORED_GROUPS == ("hygiene",)
        assert spine.is_scored("hygiene")
        for name in spine.CORE_SPINE:
            if name != "hygiene":
                assert not spine.is_scored(name)


class TestSpineDocuments:
    """Law S1 at the source: an unbuilt group is not_applicable, never 0."""

    def test_unbuilt_spine_group_is_not_applicable_with_a_reason(self):
        document = spine.spine_document("oracle_execution")

        assert document["status"] == "not_applicable"
        assert document["reason"]
        assert document["score"] is None

    def test_every_spine_group_declares_a_tier(self):
        for name in spine.CORE_SPINE:
            assert spine.spine_document(name)["tier"]


class TestRev4Contracts:
    """The contracts bind groups that do not exist yet. That is the point."""

    def test_kill_cause_contract_is_attached_to_every_bound_group(self):
        for name in spine.KILL_CAUSE_BOUND:
            assert "kill_cause" in spine.contract_for(name)

    def test_contract_resolves_through_the_namespaced_name(self):
        """Callers legitimately hold `pytest.scoped_survival`, not the bare name."""
        assert spine.contract_for("pytest.scoped_survival") == spine.contract_for("scoped_survival")

    def test_scoped_survival_contract_refuses_the_pseudo_tested_reading(self):
        contract = spine.contract_for("scoped_survival")

        assert "pseudo-testedness" in contract
        assert "NEW group" in contract

    def test_an_unbound_group_has_no_contract(self):
        assert spine.contract_for("hygiene") == ""


# =============================================================================
# REFUSAL - a refusal is never a score
# =============================================================================


class TestRefusalVocabulary:
    def test_publication_codes_are_not_refusals(self):
        assert not refusal.is_refusal(refusal.EXIT_PASSED)
        assert not refusal.is_refusal(refusal.EXIT_SCORED_FAILED)

    def test_every_other_code_is_a_refusal(self):
        for code in (2, 3, 4, 5, 6):
            assert refusal.is_refusal(code)

    def test_unproven_outranks_every_honest_failure(self):
        """The whole ordering exists for this one comparison."""
        assert refusal.worst_code([refusal.EXIT_UNPROVEN, refusal.EXIT_BUDGET_EXHAUSTED]) == refusal.EXIT_UNPROVEN
        assert refusal.worst_code([0, 1, 3, 4, 5, 6, 2]) == refusal.EXIT_UNPROVEN

    def test_a_clean_fleet_returns_zero(self):
        assert refusal.worst_code([0, 0, 0]) == refusal.EXIT_PASSED
        assert refusal.worst_code([]) == refusal.EXIT_PASSED

    def test_a_scored_failure_beats_a_pass_but_loses_to_a_refusal(self):
        assert refusal.worst_code([0, 1]) == refusal.EXIT_SCORED_FAILED
        assert refusal.worst_code([1, 3]) == refusal.EXIT_NO_UNITS

    def test_an_unknown_code_is_treated_as_the_worst(self):
        """Silently downgrading an unrecognised code is how a refusal becomes a pass."""
        assert refusal.worst_code([0, 99]) == 99

    def test_every_refusal_cites_a_law(self):
        for code in refusal.REFUSAL_CODES:
            assert refusal.Refusal(code=code, reason="x").law

    def test_refusal_prints_a_load_bearing_stdout_line(self):
        """The exit code cannot survive seedgo.py's return path; this must."""
        line = refusal.refusal_for_canary().stdout_line()

        assert line.startswith("REFUSED:")
        assert "T10" in line

    def test_budget_refusal_never_carries_a_partial_measurement(self):
        built = refusal.refusal_for_budget(elapsed=930.4, budget=600, group="hygiene")

        assert built.code == refusal.EXIT_BUDGET_EXHAUSTED
        assert built.law == "T-BUDGET"
        assert any("930.4" in line for line in built.detail)
        assert any("no partial measurement" in line for line in built.detail)


# =============================================================================
# LAWS - every one of them bites
# =============================================================================


class TestLawsAcceptTheLawful:
    def test_the_reference_document_passes_every_law(self):
        assert laws.validate(_lawful_document()) == []


class TestS1:
    def test_not_applicable_without_a_reason_is_caught(self):
        document = _lawful_document()
        document["groups"]["order_dependence"]["reason"] = ""

        assert any(p.startswith("S1") for p in laws.validate(document))

    def test_a_zero_for_a_group_that_never_ran_is_caught(self):
        """not-run is not_applicable, never 0 - the lie the lane exists to stop."""
        document = _lawful_document()
        document["groups"]["order_dependence"]["score"] = 0

        problems = laws.validate(document)
        assert any("never 0" in p for p in problems)

    def test_an_unknown_status_is_caught(self):
        document = _lawful_document()
        document["groups"]["order_dependence"]["status"] = "skipped"

        assert any(p.startswith("S1") for p in laws.validate(document))


class TestS2:
    def test_a_group_without_a_tier_is_caught(self):
        document = _lawful_document()
        document["groups"]["order_dependence"]["tier"] = ""

        assert any(p.startswith("S2") for p in laws.validate(document))


class TestS3S4:
    def test_group_list_and_groups_must_agree(self):
        document = _lawful_document()
        document["group_list"] = list(spine.CORE_SPINE) + ["pytest.invented"]

        assert any(p.startswith("S4") for p in laws.validate(document))

    def test_a_vanished_group_without_a_ruling_is_caught(self):
        document = _lawful_document()
        previous = list(spine.CORE_SPINE) + ["pytest.retired_yesterday"]

        problems = laws.validate(document, previous_group_list=previous)
        assert any("pytest.retired_yesterday" in p and p.startswith("S3") for p in problems)

    def test_a_vanished_group_WITH_a_ruling_is_allowed(self):
        """S3 is a no-vanishing property, not a freeze - retirement stays possible."""
        document = _lawful_document()
        document["retired_groups"] = [
            {"group": "pytest.retired_yesterday", "ruling": "boardroom post 6", "date": "2026-08-29"}
        ]
        previous = list(spine.CORE_SPINE) + ["pytest.retired_yesterday"]

        assert laws.validate(document, previous_group_list=previous) == []

    def test_a_retirement_entry_without_a_ruling_is_caught(self):
        document = _lawful_document()
        document["retired_groups"] = [{"group": "pytest.retired_yesterday", "ruling": ""}]
        previous = list(spine.CORE_SPINE) + ["pytest.retired_yesterday"]

        assert any("names no ruling" in p for p in laws.validate(document, previous_group_list=previous))

    def test_adding_a_group_is_always_free(self):
        """The rebuild trigger, pinned: growth must never be a violation."""
        document = _lawful_document()
        document["group_list"] = list(spine.CORE_SPINE) + ["pytest.brand_new"]
        document["groups"]["pytest.brand_new"] = {
            "tier": "static",
            "status": "not_applicable",
            "reason": "not built",
            "score": None,
        }

        assert laws.validate(document, previous_group_list=list(spine.CORE_SPINE)) == []

    def test_a_missing_group_baseline_is_caught(self):
        """A check that silently did not run must say so."""
        document = _lawful_document()
        del document["group_baseline"]

        assert any("group_baseline" in p for p in laws.validate(document))


class TestS6S7:
    def test_an_ai_group_that_is_not_nominate_only_is_caught(self):
        document = _lawful_document()
        document["groups"]["ai_advisory"]["kind"] = "scores_things"

        assert any(p.startswith("S6") for p in laws.validate(document))

    def test_an_unscored_group_carrying_a_score_is_caught(self):
        document = _lawful_document()
        document["groups"]["order_dependence"]["status"] = "measured"
        document["groups"]["order_dependence"]["score"] = 87
        document["groups"]["order_dependence"]["budget_seconds"] = 60
        document["groups"]["order_dependence"]["elapsed_seconds"] = 1.0

        assert any(p.startswith("S7a") for p in laws.validate(document))

    @pytest.mark.parametrize("verdict", sorted(laws.DELETE_FAMILY))
    def test_every_delete_family_verdict_is_caught(self, verdict):
        """Asserts the DELETE-FAMILY branch specifically, not merely 'some S7b'.

        A survivor found this on day one: deleting the delete-family check let
        the generic unknown-verdict branch catch the same input, so a prefix
        assertion still passed while the rule that answers TAXONOMY section 7
        Q1 - USELESS is not a verdict any tier may emit - was gone.
        """
        document = _lawful_document()
        document["groups"]["ai_advisory"]["nominations"] = [{"nodeid": "t::a", "verdict": verdict}]

        problems = laws.validate(document)
        assert any("delete-family" in p for p in problems)

    def test_an_unknown_verdict_is_caught_by_its_own_branch(self):
        document = _lawful_document()
        document["groups"]["ai_advisory"]["nominations"] = [{"nodeid": "t::a", "verdict": "probably_fine"}]

        problems = laws.validate(document)
        assert any("unknown verdict" in p for p in problems)

    @pytest.mark.parametrize("verdict", sorted(laws.ALLOWED_VERDICTS))
    def test_every_allowed_verdict_passes(self, verdict):
        document = _lawful_document()
        document["groups"]["ai_advisory"]["nominations"] = [{"nodeid": "t::a", "verdict": verdict}]

        assert laws.validate(document) == []


class TestS8:
    def test_a_score_without_gate_coverage_is_caught(self):
        document = _lawful_document()
        del document["groups"]["hygiene"]["gate_coverage"]

        assert any(p.startswith("S8") for p in laws.validate(document))

    def test_a_gate_claiming_it_is_blind_to_nothing_is_caught(self):
        """Every real instrument is blind to something; omniscience is unearned."""
        document = _lawful_document()
        document["groups"]["hygiene"]["gate_coverage"]["blind"] = []

        assert any("blind to something" in p for p in laws.validate(document))

    def test_gate_coverage_must_name_its_mechanism(self):
        document = _lawful_document()
        document["groups"]["hygiene"]["gate_coverage"]["mechanism"] = ""

        assert any("mechanism" in p for p in laws.validate(document))


class TestS9:
    """The rev-4 contract, pinned before the capability exists."""

    def test_a_mutant_record_without_a_kill_cause_is_caught(self):
        document = _lawful_document()
        document["groups"]["oracle_execution"]["mutants"] = [{"id": "m1", "killed": True}]

        assert any(p.startswith("S9") for p in laws.validate(document))

    def test_a_mutant_record_WITH_a_kill_cause_passes(self):
        document = _lawful_document()
        document["groups"]["oracle_execution"]["mutants"] = [
            {"id": "m1", "killed": True, "kill_cause": "AssertionError"}
        ]

        assert laws.validate(document) == []


class TestBudget:
    def test_an_execution_group_without_a_budget_is_caught(self):
        document = _lawful_document()
        del document["groups"]["hygiene"]["budget_seconds"]

        assert any(p.startswith("T-BUDGET") for p in laws.validate(document))

    def test_an_exhausted_group_may_not_be_measured(self):
        document = _lawful_document()
        document["groups"]["hygiene"]["budget_exhausted"] = True

        assert any("not 'refused'" in p for p in laws.validate(document))

    def test_an_exhausted_group_may_not_carry_a_score(self):
        """A partial suite that reports a number is forgery by omission."""
        document = _lawful_document()
        document["groups"]["hygiene"]["budget_exhausted"] = True
        document["groups"]["hygiene"]["status"] = "refused"
        document["groups"]["hygiene"]["reason"] = "budget exhausted"

        assert any("still carries a score" in p for p in laws.validate(document))

    def test_an_unbuilt_execution_group_needs_no_budget(self):
        """not_applicable groups never ran, so a budget would be theatre."""
        assert laws.validate(_lawful_document()) == []


class TestS5:
    def test_a_cache_served_artifact_without_a_stamp_is_caught(self):
        document = _lawful_document()
        document["cache"]["served_from_cache"] = True

        assert any(p.startswith("S5") for p in laws.validate(document))

    def test_a_cache_block_without_not_fingerprinted_is_caught(self):
        document = _lawful_document()
        del document["cache"]["not_fingerprinted"]

        assert any("not_fingerprinted" in p for p in laws.validate(document))


class TestEnforce:
    def test_enforce_raises_naming_the_law(self):
        document = _lawful_document()
        del document["groups"]["hygiene"]["gate_coverage"]

        with pytest.raises(laws.LawViolation) as caught:
            laws.enforce(document)
        assert caught.value.law == "S8"

    def test_enforce_is_silent_on_a_lawful_document(self):
        laws.enforce(_lawful_document())

    def test_validate_reports_every_problem_at_once(self):
        """One reason per attempt would make fixing an artifact a guessing game."""
        document = _lawful_document()
        del document["groups"]["hygiene"]["gate_coverage"]
        document["groups"]["order_dependence"]["tier"] = ""

        problems = laws.validate(document)
        assert any(p.startswith("S8") for p in problems)
        assert any(p.startswith("S2") for p in problems)
