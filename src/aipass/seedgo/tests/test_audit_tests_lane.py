# =================== AIPass ====================
# Name: test_audit_tests_lane.py
# Description: tests for the audit-tests runner, its target resolution and the verb
# Version: 1.3.1
# Created: 2026-08-29
# Modified: 2026-10-24
# =============================================

"""Tests for apps/modules/audit_tests.py, apps/handlers/audit_tests/runner.py and the pytest pack it drives."""

# Phase 4-5 of the audit-tests lane: the runner, its target and the verb; the gate, adapter and statement
# deletion live in the test_audit_tests_lane_*.py siblings. Each test names one behaviour a mutation could
# remove, and asserts the law's own words, never its prefix.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/audit_tests/ and handlers/tests_pytest_standards/ parses
# seedgo: no-test-needed(documentation) — that the public lane functions carry docstrings

import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import pytest

from aipass.seedgo.apps import seedgo as entry
from aipass.seedgo.apps.handlers.audit_tests import (
    artifact,
    m10,
    refusal,
    runner,
    selfcheck,
    spine,
    target as target_module,
)
from aipass.seedgo.apps.handlers.tests_pytest_standards import envcopy, gatelog
from aipass.seedgo.apps.modules import CommandRefused, audit_tests, standards_audit
from aipass.seedgo.apps.modules import audit_tests as verb
from aipass.seedgo.tests.support_audit_tests_lane import _records, _spec_for


def _target(tmp_path) -> target_module.Target:
    """A directory target the runner can carry through the pipeline."""
    return target_module.Target(name="probe", path=tmp_path, kind="directory", resolved_from="test")


class _SealedAdapter:
    """The pytest adapter with its subprocess edge sealed: `run_gated` hands back a canned run.

    Everything after the claim is the real runner, reached through `runner.run_target` as `audit-tests` does.
    """

    ECOSYSTEM = "pytest"

    def __init__(self, run: "dict | Callable[[], dict]", nominations=None) -> None:
        self.run = run
        self.nominations = dict(nominations or {})

    def declared_groups(self) -> list:
        """One adapter group, so composition has a namespaced group to place."""
        return ["static_nominators"]

    def build_env(self, path, env_root, options) -> envcopy.EnvSpec:
        """A scratch spec; nothing is copied because nothing runs."""
        return _spec_for(env_root)

    def assert_env_is_live(self, spec) -> dict:
        """The copy is declared live."""
        return {"live": True}

    def run_gated(self, spec, budget, options) -> dict:
        """The canned run, or the run a callable builds while the window is open."""
        return self.run() if callable(self.run) else self.run

    def nominate(self, spec) -> dict:
        """The canned nominations."""
        return self.nominations


def _measured(tmp_path, monkeypatch, run, *, options=None, nominations=None) -> dict:
    """`runner.run_target` over `tmp_path/real` with the adapter sealed; the published document."""
    monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path / "artifacts")
    sealed = _SealedAdapter(run, nominations)
    monkeypatch.setattr(runner.adapters, "discover_adapters", lambda: ([sealed], []))
    monkeypatch.setattr(
        runner.adapters, "claim_target", lambda registered, path: (sealed, {"pytest": {"unit_count": 1}})
    )
    real = tmp_path / "real"
    real.mkdir(exist_ok=True)
    target = target_module.Target(name="probe", path=real, kind="directory", resolved_from="test")
    return runner.run_target(target, {"no_m10_proof": True} if options is None else options).document


def _proven_run(violations: int = 0) -> dict:
    """A run whose gate is proven, with `violations` recorded writes."""
    return {
        "gate": gatelog.measure(_records(violations=violations), timed_out=False),
        "budget_seconds": 900,
        "elapsed_seconds": 1.5,
    }


def _suite_writes(path: Path, text: str):
    """A run that writes `path` from a CHILD process, as a measured suite would.

    In-process writes are the audit's own carrier writes, subtracted by design; a child process is the suite.
    """

    def run() -> dict:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; open(sys.argv[1], 'w', encoding='utf-8').write(sys.argv[2])",
                str(path),
                text,
            ],
            check=True,
        )
        return _proven_run()

    return run


class TestScoring:
    """The score is a gate, not an opinion: 100 or 0, never a percentage."""

    def test_a_clean_proven_run_scores_one_hundred(self, tmp_path, monkeypatch):
        document = _hygiene(tmp_path, monkeypatch, violations=0)
        assert document["score"] == 100
        assert document["passed"] is True

    def test_a_single_violation_scores_zero(self, tmp_path, monkeypatch):
        assert _hygiene(tmp_path, monkeypatch, violations=1)["score"] == 0

    def test_many_violations_score_the_same_zero_as_one(self, tmp_path, monkeypatch):
        # No partial credit: a percentage would let a branch improve its number without fixing anything.
        assert _hygiene(tmp_path, monkeypatch, violations=31)["score"] == 0

    def test_a_measured_group_declares_itself_measured(self, tmp_path, monkeypatch):
        assert _hygiene(tmp_path, monkeypatch, violations=0)["status"] == "measured"

    def test_the_proven_flag_survives_into_the_published_group(self, tmp_path, monkeypatch):
        assert _hygiene(tmp_path, monkeypatch, violations=0)["gate_proven"] is True

    def test_the_published_group_carries_no_internal_proven_key(self, tmp_path, monkeypatch):
        # `proven`/`unproven_reason` are the adapter's vocabulary; leaking them publishes two names for one fact.
        document = _hygiene(tmp_path, monkeypatch, violations=0)
        assert "proven" not in document
        assert "unproven_reason" not in document

    def test_the_budget_and_elapsed_are_both_published(self, tmp_path, monkeypatch):
        document = _hygiene(tmp_path, monkeypatch, violations=0)
        assert document["budget_seconds"] == 900
        assert document["elapsed_seconds"] == 1.5


def _hygiene(tmp_path, monkeypatch, *, violations: int) -> dict:
    """The published hygiene group of a proven run with `violations` recorded writes."""
    return _measured(tmp_path, monkeypatch, _proven_run(violations))["groups"]["hygiene"]


class TestGroupComposition:
    """Every declared group appears, in order, and none of them is ever 0."""

    def test_the_published_groups_match_the_group_list_exactly_and_in_order(self, tmp_path, monkeypatch):
        """Mutant: groups composed in reverse group_list order in apps/handlers/audit_tests/runner.py — killed."""
        group_list = spine.compose_group_list("pytest", ["static_nominators"])
        document = _measured(tmp_path, monkeypatch, _proven_run())
        # A refused run also lists every group in order, so the pin is on a PUBLISHED one.
        assert document["status"] == "published"
        assert list(document["groups"]) == group_list

    def test_an_unimplemented_spine_group_is_not_applicable_with_a_reason(self, tmp_path, monkeypatch):
        groups = _measured(tmp_path, monkeypatch, _proven_run())["groups"]
        assert groups["order_dependence"]["status"] == "not_applicable"
        assert groups["order_dependence"]["reason"]

    def test_an_unimplemented_spine_group_is_never_scored_zero(self, tmp_path, monkeypatch):
        groups = _measured(tmp_path, monkeypatch, _proven_run())["groups"]
        assert groups["oracle_execution"]["score"] is None

    def test_an_adapter_group_is_matched_by_its_bare_name(self, tmp_path, monkeypatch):
        nominations = {
            "static_nominators": {"tier": "static", "status": "not_applicable", "reason": "x", "score": None}
        }
        groups = _measured(tmp_path, monkeypatch, _proven_run(), nominations=nominations)["groups"]
        assert groups["pytest.static_nominators"]["reason"] == "x"

    def test_a_declared_group_the_adapter_forgot_still_appears_and_names_the_adapter(self, tmp_path, monkeypatch):
        groups = _measured(tmp_path, monkeypatch, _proven_run())["groups"]
        document = groups["pytest.static_nominators"]
        assert document["status"] == "not_applicable"
        assert "pytest adapter declared" in document["reason"]


class TestM10Proof:
    """The lane's central promise, measured — and proven able to fail."""

    def test_an_untouched_tree_proves_m10_held(self, tmp_path, monkeypatch):
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "state.json").write_text("{}", encoding="utf-8")
        proof = _measured(tmp_path, monkeypatch, _proven_run(), options={})["m10_proof"]
        assert proof["probed"] is True
        assert proof["real_tree_unchanged"] is True

    def test_a_forged_file_makes_the_proof_report_a_violation(self, tmp_path, monkeypatch):
        (tmp_path / "real").mkdir()
        probe = tmp_path / "real" / "state.json"
        probe.write_text("{}", encoding="utf-8")
        proof = _measured(tmp_path, monkeypatch, _suite_writes(probe, '{"forged": true}'), options={})["m10_proof"]
        assert proof["real_tree_unchanged"] is False
        assert str(probe) in proof["diff"]["modified"]

    def test_a_new_file_in_the_real_tree_is_a_violation_too(self, tmp_path, monkeypatch):
        run = _suite_writes(tmp_path / "real" / "left_behind.json", "{}")
        assert _measured(tmp_path, monkeypatch, run, options={})["m10_proof"]["real_tree_unchanged"] is False

    def test_the_number_of_files_compared_is_published(self, tmp_path, monkeypatch):
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "real" / "b.json").write_text("{}", encoding="utf-8")
        assert _measured(tmp_path, monkeypatch, _proven_run(), options={})["m10_proof"]["files_fingerprinted"] == 2

    def test_a_disturbed_tree_is_recorded_as_an_operational_event(self, tmp_path, monkeypatch):
        # Recorded where the fact is established, not at a call site a future caller might skip.
        recorded = []
        monkeypatch.setattr(m10.json_handler, "log_operation", lambda name, payload: recorded.append(name))
        probe = tmp_path / "state.json"
        probe.write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        probe.write_text('{"forged": true}', encoding="utf-8")
        m10.diff_snapshots(before, m10.snapshot_tree(tmp_path))
        assert "m10_violated" in recorded

    def test_an_intact_tree_records_no_violation_event(self, tmp_path, monkeypatch):
        recorded = []
        monkeypatch.setattr(m10.json_handler, "log_operation", lambda name, payload: recorded.append(name))
        (tmp_path / "state.json").write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        m10.diff_snapshots(before, m10.snapshot_tree(tmp_path))
        assert recorded == []

    def test_a_skipped_proof_says_not_probed_rather_than_reporting_clean(self, tmp_path, monkeypatch):
        # not_probed and passed must never look the same (Law S1 on the lane's own harness).
        proof = _measured(tmp_path, monkeypatch, _proven_run(), options={"no_m10_proof": True})["m10_proof"]
        assert proof["probed"] is False
        assert proof["real_tree_unchanged"] is None

    def test_a_skipped_proof_still_says_why(self, tmp_path, monkeypatch):
        """The skip's own reason, never the failure's (fleet green leg 14). Red first: a
        skipped run's note read "the before-fingerprint could not be taken"."""
        proof = _measured(tmp_path, monkeypatch, _proven_run(), options={"no_m10_proof": True})["m10_proof"]
        assert proof["note"] == (
            "skipped: this run was asked not to prove M10 (no_m10_proof), so nothing was fingerprinted"
        )

    def test_a_fingerprint_that_cannot_be_taken_says_so(self, tmp_path, monkeypatch):
        """Control: an unasked run whose before-fingerprint fails names the failure, not a skip."""

        def unreadable(*args, **kwargs):
            raise OSError("tree unreadable")

        monkeypatch.setattr(runner.m10, "snapshot_tree", unreadable)
        proof = _measured(tmp_path, monkeypatch, _proven_run(), options={})["m10_proof"]
        assert proof["probed"] is False
        assert proof["note"] == "the before-fingerprint could not be taken, so no comparison is possible"

    def test_the_proof_is_skipped_only_when_explicitly_asked(self, tmp_path, monkeypatch):
        """Mutant: an unasked run fingerprints nothing in apps/handlers/audit_tests/runner.py — killed."""
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "state.json").write_text("{}", encoding="utf-8")
        asked = _measured(tmp_path, monkeypatch, _proven_run(), options={"no_m10_proof": True})["m10_proof"]
        unasked = _measured(tmp_path, monkeypatch, _proven_run(), options={})["m10_proof"]
        assert asked["probed"] is False
        assert unasked["files_fingerprinted"] == 1


class TestUnprovenRefusalWording:
    """Each pre-built refusal is used only where its wording is true."""

    def test_a_timeout_gets_the_budget_refusal(self, tmp_path, monkeypatch):
        built = _measured(tmp_path, monkeypatch, {"gate": {}, "timed_out": True, "budget_seconds": 300})["refusal"]
        assert built["code"] == refusal.EXIT_BUDGET_EXHAUSTED
        assert built["law"] == "T-BUDGET"

    def test_a_missed_canary_gets_the_canary_refusal_only_when_the_hook_was_installed(self, tmp_path, monkeypatch):
        gate = {"hook_installed": True, "canary": {"attempted": True, "caught": False}}
        built = _measured(tmp_path, monkeypatch, {"gate": gate})["refusal"]
        assert "did not catch its own planted canary" in built["reason"]

    def test_a_disabled_gate_is_not_reported_as_a_blind_gate(self, tmp_path, monkeypatch):
        # --prove-refusal turns the hook OFF while the canary still goes uncaught: the hook check comes first,
        # or a run with no gate is diagnosed as a blind one.
        gate = {
            "hook_installed": False,
            "canary": {"attempted": True, "caught": False},
            "unproven_reason": "the write gate was not installed, so a clean result would mean nothing (Law T10)",
        }
        assert "was not installed" in _measured(tmp_path, monkeypatch, {"gate": gate})["refusal"]["reason"]

    def test_an_uninstalled_hook_keeps_the_measurements_own_reason(self, tmp_path, monkeypatch):
        # The canary builder would restate a cause the run never established.
        gate = {"canary": {"attempted": False}, "unproven_reason": "the write gate was not installed"}
        built = _measured(tmp_path, monkeypatch, {"gate": gate})["refusal"]
        assert built["reason"] == "the write gate was not installed"

    def test_every_unproven_refusal_carries_detail_a_reader_can_act_on(self, tmp_path, monkeypatch):
        assert _measured(tmp_path, monkeypatch, {"gate": {}})["refusal"]["detail"]


class TestRefusalPath:
    """A refusal publishes a complete artifact, never an empty one."""

    def test_a_refused_run_publishes_every_group_as_not_applicable(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_NO_ADAPTER, "nothing claims this")
        assert all(group["status"] == "not_applicable" for group in written["groups"].values())

    def test_a_refused_run_names_the_law_it_refuses_under(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_BUDGET_EXHAUSTED, "the budget expired")
        assert written["refusal"]["law"] == "T-BUDGET"

    def test_a_refused_run_carries_the_reason_into_every_group(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_UNPROVEN, "the gate was blind")
        assert all("the gate was blind" in group["reason"] for group in written["groups"].values())

    def test_a_refused_artifact_reaches_disk(self, tmp_path, monkeypatch):
        _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_UNPROVEN, "the gate was blind")
        assert list((tmp_path / "artifacts").glob("audit_tests_*.json"))

    def test_a_cleanup_failure_after_publish_keeps_the_published_artifact(self, tmp_path, monkeypatch):
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        class _CleanupFails:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __enter__(self) -> str:
                return str(scratch)

            def __exit__(self, *exc) -> None:
                raise OSError("a grandchild still holds the scratch tree")

        monkeypatch.setattr(tempfile, "TemporaryDirectory", _CleanupFails)
        document = _measured(tmp_path, monkeypatch, _proven_run())

        assert document["status"] != "refused"
        assert document["groups"]["hygiene"]["score"] == 100

    def test_the_cache_block_states_that_no_cache_lane_exists(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_UNPROVEN, "the gate was blind")
        assert written["cache"]["not_fingerprinted"]


def _publish_refusal(tmp_path, monkeypatch, code, reason) -> dict:
    """Run the refusal path against a redirected artifact directory."""
    monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path / "artifacts")
    result = runner.refuse(_target(tmp_path), refusal.Refusal(code=code, reason=reason))
    return result.document


class TestFleetForm:
    """The worst code wins, and a per-target line prints regardless."""

    def test_the_worst_code_is_returned_across_targets(self):
        assert refusal.worst_code([refusal.EXIT_PASSED, refusal.EXIT_UNPROVEN, refusal.EXIT_SCORED_FAILED]) == 2

    def test_a_refused_result_prints_its_law_and_reason(self, tmp_path):
        result = runner.RunResult(
            _target(tmp_path),
            {"status": "refused", "refusal": {"law": "T10", "reason": "the gate was blind"}},
            None,
            refusal.EXIT_UNPROVEN,
        )
        assert "REFUSED" in result.summary_line()
        assert "the gate was blind" in result.summary_line()

    def test_a_published_result_prints_its_score_and_violation_count(self, tmp_path):
        result = runner.RunResult(
            _target(tmp_path),
            {"status": "published", "groups": {"hygiene": {"score": 0, "violation_count": 31}}},
            tmp_path / "a.json",
            refusal.EXIT_SCORED_FAILED,
        )
        assert "hygiene 0" in result.summary_line()
        assert "31 violation(s)" in result.summary_line()


class TestBranchNameResolution:
    """The registry spells some branches uppercase and everyone types lowercase."""

    def test_an_exact_name_resolves(self, tmp_path):
        resolved = target_module.resolve("@CANARY", {"CANARY": tmp_path / "canary"})
        assert resolved.name == "CANARY"

    def test_a_lowercase_argument_resolves_to_the_canonical_spelling(self, tmp_path):
        # The CANONICAL name: two spellings of one branch must never produce two artifacts.
        resolved = target_module.resolve("@canary", {"CANARY": tmp_path / "canary"})
        assert resolved.name == "CANARY"
        assert resolved.artifact_name() == "audit_tests_CANARY"

    def test_an_exact_match_wins_over_a_case_insensitive_one(self):
        resolved = target_module.resolve("@canary", {"CANARY": Path("/a"), "canary": Path("/b")})
        assert resolved.path == Path("/b")

    def test_an_ambiguous_case_insensitive_match_raises_rather_than_guessing(self):
        with pytest.raises(ValueError) as caught:
            target_module.resolve("@Canary", {"CANARY": Path("/a"), "canary": Path("/b")})
        assert "more than one" in str(caught.value)

    def test_an_unknown_branch_still_refuses_loudly(self):
        with pytest.raises(ValueError) as caught:
            target_module.resolve("@nosuchbranch", {"CANARY": Path("/x")})
        assert "not a registered branch" in str(caught.value)


class TestVerbIsDiscoverable:
    """The router hides a broken module, so loading it is its own pin."""

    def test_the_verb_module_imports_cleanly(self):
        assert callable(audit_tests.handle_command)
        assert audit_tests.COMMANDS == ("audit-tests", "audit_tests")

    def test_seedgos_own_discovery_finds_the_verb(self):
        names = {getattr(module, "__name__", "") for module in entry.discover_modules()}
        assert "audit_tests" in names

    def test_the_discovered_module_actually_claims_the_verb(self, monkeypatch):
        claimed = [module for module in entry.discover_modules() if getattr(module, "__name__", "") == "audit_tests"]
        assert claimed, "audit_tests did not survive discovery"
        monkeypatch.setattr(claimed[0], "print_introspection", lambda: None)
        assert claimed[0].handle_command("audit-tests", []) is True

    def test_no_arguments_shows_introspection_rather_than_running(self, monkeypatch):
        seen = []
        monkeypatch.setattr(verb, "print_introspection", lambda: seen.append(True))
        monkeypatch.setattr(verb, "_run", lambda args: seen.append("ran"))
        verb.handle_command("audit-tests", [])
        assert seen == [True]

    def test_help_is_intercepted_before_any_target_is_resolved(self, monkeypatch):
        # Not "raise inside _run": handle_command catches every exception by design, so that pin could never fail.
        seen = []
        monkeypatch.setattr(verb, "_print_help", lambda: seen.append("help"))
        monkeypatch.setattr(verb, "_run", lambda args: seen.append("ran"))
        verb.handle_command("audit-tests", ["--help"])
        assert seen == ["help"]


class TestVerbClaiming:
    """Claim exactly, claim before working, and never claim a prefix."""

    def test_the_hyphenated_verb_is_claimed(self, monkeypatch):
        # True alone cannot tell "claimed and ran" from "claimed and did nothing"; no args takes introspection.
        ran = []
        monkeypatch.setattr(verb, "_run", lambda args: ran.append(args))
        assert verb.handle_command("audit-tests", ["@backup"]) is True
        assert ran == [["@backup"]]

    def test_the_underscore_alias_is_claimed(self, monkeypatch):
        ran = []
        monkeypatch.setattr(verb, "_run", lambda args: ran.append(args))
        assert verb.handle_command("audit_tests", ["@backup"]) is True
        assert ran == [["@backup"]], "the alias must forward its args, not just answer True"

    def test_the_audit_verb_is_never_swallowed(self):
        # audit_tests.py sorts before standards_audit.py, so a prefix claim would take the audit verb from its owner.
        assert verb.handle_command("audit", []) is False

    def test_a_crash_after_claiming_refuses_with_the_unproven_code(self, monkeypatch):
        """A crashed lane exits 2, and is never reported as an unknown command."""
        entered = []

        def explode(args):
            entered.append(args)
            raise RuntimeError("the lane broke")

        monkeypatch.setattr(verb, "_run", explode)
        with pytest.raises(CommandRefused) as refused:
            verb.handle_command("audit-tests", ["@backup"])

        assert entered == [["@backup"]], "the crash must happen inside _run, not before it"
        assert refused.value.code == refusal.EXIT_UNPROVEN


def _parsed(monkeypatch, argv: list) -> tuple:
    """`(target, options, refused_token)` as `audit-tests argv` hands them to the runner.

    The runner is a recorder, so nothing is measured; a refusal comes back as the token
    it named, and "" when the verb reached the runner.
    """
    handed: list = []
    monkeypatch.setattr(verb.runner, "run", lambda argument, options: handed.append((argument, options)) or ([], 0))
    try:
        verb.handle_command("audit-tests", argv)
    except CommandRefused as refused:
        return "", {}, refused.token
    ((target, options),) = handed
    return target, options, ""


class TestVerbParsing:
    """Options are read positionally-safe; the target is the first bare token."""

    def test_a_bare_token_is_the_target(self, monkeypatch):
        assert _parsed(monkeypatch, ["@backup"])[0] == "@backup"

    def test_the_budget_is_read_as_an_integer(self, monkeypatch):
        assert _parsed(monkeypatch, ["@backup", "--budget", "300"])[1]["budget_seconds"] == 300

    @pytest.mark.parametrize(
        "argv",
        [["@backup", "--budget", "soon"], ["--budget", "@backup"], ["@backup", "--budget", "--pseudo-tested"]],
    )
    def test_a_budget_without_a_number_is_refused_by_name(self, monkeypatch, argv):
        """Swallowing the next token would silently drop the target or a campaign."""
        with pytest.raises(CommandRefused) as refused:
            verb.handle_command("audit-tests", argv)
        assert (refused.value.code, refused.value.token) == (refusal.EXIT_UNKNOWN_ARGUMENT, "--budget")

    def test_prove_refusal_is_recognised(self, monkeypatch):
        assert _parsed(monkeypatch, ["@backup", "--prove-refusal"])[1]["prove_refusal"] is True

    def test_a_flag_is_never_mistaken_for_the_target(self, monkeypatch):
        assert _parsed(monkeypatch, ["--prove-refusal", "@backup"])[0] == "@backup"

    def test_symlink_siblings_is_off_unless_asked_for(self, monkeypatch):
        # Copy-always by default: a write through a symlinked sibling lands in the real tree.
        assert "symlink_siblings" not in _parsed(monkeypatch, ["@backup"])[1]


def _audit_vocabulary():
    """The `audit` verb's own flag list and sibling verbs, never a copy.

    Read off the module: a private duplicate would keep offering flags the verb stopped accepting (Law ARGV).
    """
    return standards_audit.AUDIT_FLAGS, standards_audit.SIBLING_VERBS


def _lane_vocabulary():
    """The `audit-tests` verb's own flag list and sibling verbs."""
    return verb.LANE_FLAGS, verb.SIBLING_VERBS


def _built_refusal():
    """The ARGV refusal for the typo that started this, built as the verb builds it."""
    flags, siblings = _audit_vocabulary()
    argv = ["-tests", "@backup"]
    return refusal.refusal_for_unknown_argument(
        "-tests", refusal.suggested_command("-tests", "audit", argv, flags, siblings), "audit"
    )


class TestUnknownArgumentSuggestion:
    """The did-you-mean is a real command, rebuilt from what the caller typed."""

    def test_the_space_typo_is_glued_back_into_the_verb_it_was_reaching_for(self):
        # The defect as typed: `drone @seedgo audit -tests @backup`. The suggestion is the canonical
        # `audit tests <target>`.
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("-tests", "audit", ["-tests", "@backup"], flags, siblings)
            == "drone @seedgo audit tests @backup"
        )

    def test_the_hyphenated_alias_is_still_a_suggestible_spelling(self):
        # `audit-tests` still works, so the verb list is read off the module and the glue is checked against it.
        _, siblings = _audit_vocabulary()

        assert "audit-tests" in siblings
        assert refusal.sibling_verb("-tests", "audit", ("audit-tests",)) == "audit-tests"

    def test_the_rest_of_the_line_is_carried_into_the_suggestion(self):
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("-tests", "audit", ["-tests", "@flow", "--full"], flags, siblings)
            == "drone @seedgo audit tests @flow --full"
        )

    def test_a_near_miss_flag_is_offered_spelled_correctly(self):
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("--nobypass", "audit", ["aipass", "--nobypass"], flags, siblings)
            == "drone @seedgo audit aipass --no-bypass"
        )

    def test_a_shared_verb_prefix_never_inflates_the_sibling_match(self):
        # Only the distinguishing part is compared: whole, `audit-zzz` scores 0.6 against `audit-tests` on `audit-`.
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("--zzz", "audit", ["aipass", "--zzz"], flags, siblings)
            == "drone @seedgo audit --help"
        )

    def test_an_extra_bare_word_is_suggested_away(self):
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("@prax", "audit", ["aipass", "@flow", "@prax"], flags, siblings)
            == "drone @seedgo audit aipass @flow"
        )

    def test_the_lane_offers_its_own_flag_back(self):
        flags, siblings = _lane_vocabulary()

        assert (
            refusal.suggested_command("-budget", "audit-tests", ["@backup", "-budget", "300"], flags, siblings)
            == "drone @seedgo audit-tests @backup --budget 300"
        )

    def test_the_verb_already_typed_is_never_suggested_back(self):
        # A suggestion identical to the failed command is not one; the exact and the fuzzy guard are both pinned.
        assert refusal.sibling_verb("-audit", "audit", ("audit", "audit-tests")) == ""
        assert refusal.sibling_verb("-tests", "audit-tests", ("audit-tests",)) == ""


class TestUnknownArgumentRefusal:
    """A refused token names itself, cites ARGV, and carries the fix."""

    def test_the_refusal_names_the_offending_token(self):
        built = _built_refusal()

        assert "'-tests'" in built.reason

    def test_the_refusal_carries_the_command_that_would_have_worked(self):
        built = _built_refusal()

        assert "did you mean: drone @seedgo audit tests @backup" in built.reason

    def test_the_refusal_exits_non_zero(self):
        built = _built_refusal()

        assert built.code == refusal.EXIT_UNKNOWN_ARGUMENT
        assert built.code != refusal.EXIT_PASSED
        assert refusal.is_refusal(built.code), "a command nobody understood is a refusal, never a publication"

    def test_the_stdout_line_cites_the_law_it_refuses_under(self):
        line = _built_refusal().stdout_line()

        assert line.startswith("REFUSED:")
        assert "[ARGV]" in line

    def test_the_detail_carries_a_pasteable_command(self):
        assert "try: drone @seedgo audit tests @backup" in _built_refusal().detail

    def test_argv_outranks_every_measurement_outcome_except_unproven(self):
        """Nothing ran at all, so it must never rank quieter than a run that did."""
        assert (
            refusal.worst_code([refusal.EXIT_UNKNOWN_ARGUMENT, refusal.EXIT_BUDGET_EXHAUSTED])
            == refusal.EXIT_UNKNOWN_ARGUMENT
        )
        assert refusal.worst_code([refusal.EXIT_UNKNOWN_ARGUMENT, refusal.EXIT_UNPROVEN]) == refusal.EXIT_UNPROVEN

    def test_the_verb_prints_the_refused_line_the_code_and_the_detail(self, capsys):
        """The refusal is only real once a reader sees it."""
        # Raises: the printed "exit code: 7" and the process's exit code are one number.
        with pytest.raises(CommandRefused) as refused:
            verb.handle_command("audit-tests", ["@backup", "--nonsense"])

        out, err = capsys.readouterr()
        assert "REFUSED: [ARGV] unknown argument '--nonsense'" in err
        assert "exit code: 7" in out
        assert "try: drone @seedgo audit-tests" in out
        assert refused.value.code == 7


class TestLaneParsingRefusesTheUnrecognized:
    """`audit-tests` collects what it could not read, and never drops it."""

    def test_an_unknown_flag_is_collected(self, monkeypatch):
        assert _parsed(monkeypatch, ["@backup", "--nonsense"])[2] == "--nonsense"

    def test_a_second_target_is_collected_because_a_run_measures_one(self, monkeypatch):
        # `runner.run()` takes ONE argument, so a second bare word would vanish; `aipass` is the fleet form.
        assert _parsed(monkeypatch, ["@backup", "@flow"])[2] == "@flow"

    def test_argv_order_is_kept_so_the_first_mistake_is_the_one_reported(self, monkeypatch):
        """Mutant: unrecognised tokens collected newest-first in apps/modules/audit_tests.py — killed."""
        assert _parsed(monkeypatch, ["--first", "@backup", "--second"])[2] == "--first"

    @pytest.mark.parametrize(
        "argv",
        [
            ["@backup"],
            ["."],
            ["/tmp/some_project"],
            ["aipass"],
            ["@backup", "--budget", "300"],
            ["@backup", "--prove-refusal"],
            ["@backup", "--symlink-siblings"],
            ["@backup", "--no-tmpdir-allowance"],
            ["--prove-refusal", "@backup"],
            ["@backup", "--budget", "300", "--prove-refusal", "--symlink-siblings", "--no-tmpdir-allowance"],
        ],
    )
    def test_every_documented_invocation_still_parses_clean(self, argv, monkeypatch):
        """A refusal that rejects a valid command is worse than the bug it fixes."""
        target, options, refused = _parsed(monkeypatch, argv)

        assert refused == "", f"{argv} is documented usage and must not be refused"
        assert target, f"{argv} names a target"

    def test_a_budget_with_no_value_is_refused_by_name(self, monkeypatch):
        """The help documents `--budget <seconds>`; a bare flag has no default to fall back on."""
        assert _parsed(monkeypatch, ["@backup", "--budget"])[2] == "--budget"


class TestLaneVerbRefusesTheUnrecognized:
    """The refusal happens before anything is measured."""

    def test_nothing_is_measured_once_a_token_is_unrecognized(self, monkeypatch, capsys):
        measured: list = []
        monkeypatch.setattr(verb.runner, "run", lambda *a, **k: measured.append("MEASURED"))

        with pytest.raises(CommandRefused):
            verb.handle_command("audit-tests", ["@backup", "--nonsense"])

        assert measured == [], "the lane measured a target it had already failed to understand"
        assert "REFUSED: [ARGV] unknown argument '--nonsense'" in capsys.readouterr().err

    def test_a_help_flag_beside_an_unknown_token_still_explains(self, monkeypatch):
        # help_flag_safety: a help flag anywhere explains, never executes or refuses; the unknown token waits.
        seen: list = []
        monkeypatch.setattr(verb, "_print_help", lambda: seen.append("help"))
        monkeypatch.setattr(verb, "_run", lambda args: seen.append("ran"))

        verb.handle_command("audit-tests", ["-tests", "--help"])

        assert seen == ["help"]


def _harness_rows(m10_proof: dict) -> list:
    """The harness's published rows for a run carrying this M10 proof."""
    block = selfcheck.harness_block(
        document={}, hygiene={}, run={}, environment={}, liveness={}, m10_proof=m10_proof, config_note=""
    )
    return block["checks"]


class TestLiveWriterProbeWindowIsDisclosed:
    """`live_writers_probed: true` must never read as "probed ADEQUATELY"."""

    def test_the_not_probed_proof_carries_the_window_field_too(self, tmp_path, monkeypatch):
        """A missing field and a zero window must not look the same."""

        assert "live_writer_probe_seconds" in _measured(tmp_path, monkeypatch, _proven_run())["m10_proof"]

    def test_an_unprobed_run_publishes_none_not_a_misleading_zero(self, tmp_path, monkeypatch):
        assert _measured(tmp_path, monkeypatch, _proven_run())["m10_proof"]["live_writer_probe_seconds"] is None

    def test_the_probe_records_how_long_its_window_actually_was(self, tmp_path, monkeypatch):
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "f.txt").write_text("x", encoding="utf-8")
        proof = _measured(tmp_path, monkeypatch, _proven_run(), options={})["m10_proof"]

        assert proof["live_writers_probed"] is True
        window = proof["live_writer_probe_seconds"]
        assert isinstance(window, float)
        assert window >= 0.0

    def test_a_failed_probe_still_publishes_a_window_of_none(self, tmp_path, monkeypatch):
        """The probe failing is the case where a bare `true` misleads most."""

        def boom(*a, **k):
            raise OSError("no")

        monkeypatch.setattr(m10, "live_writers", boom)
        proof = _measured(tmp_path, monkeypatch, _proven_run(), options={})["m10_proof"]

        assert proof["live_writers_probed"] is False
        assert proof["live_writer_probe_seconds"] is None

    def test_the_unattributed_row_states_the_window_beside_the_probe_flag(self):
        """The two numbers must meet in ONE sentence to be comparable."""
        proof = {
            "probed": True,
            "files_fingerprinted": 3,
            "unattributed_changes": ["a"],
            "attributed_to_concurrent_writers": [],
            "live_writers_probed": True,
            "live_writer_probe_seconds": 0.02,
            "changed_by_the_measured_suite": [],
            "diff": {},
        }
        row = next(c for c in _harness_rows(proof) if c["check"] == 17)
        assert re.search(r"\(probe ran: True, window 0\.02s", row["detail"])

    def test_the_published_proof_carries_the_window_not_just_the_options_dict(self, tmp_path, monkeypatch):
        """The reader of the ARTIFACT is who needs this number."""
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "f.txt").write_text("x", encoding="utf-8")

        proof = _measured(tmp_path, monkeypatch, _proven_run(), options={})["m10_proof"]

        assert proof["probed"] is True
        assert "live_writer_probe_seconds" in proof
        assert isinstance(proof["live_writer_probe_seconds"], float)


class TestCheck12VerdictIsSplitFromUnattributedChanges:
    """A FAIL must name what it found, not what it could not explain."""

    def _proof(self, *, by_suite, unattributed):
        return {
            "probed": True,
            "files_fingerprinted": 9,
            "unattributed_changes": unattributed,
            "attributed_to_concurrent_writers": [],
            "live_writers_probed": True,
            "live_writer_probe_seconds": 0.02,
            "changed_by_the_measured_suite": by_suite,
            "real_tree_unchanged": not (by_suite or unattributed),
            "diff": {},
        }

    def _row(self, rows, number):
        found = [r for r in rows if r["check"] == number]
        assert found, f"check {number} must be present"
        return found[0]

    def test_check_12_passes_when_the_suite_changed_nothing(self):
        """@trigger's exact case: ten unattributed, zero from the suite."""
        rows = _harness_rows(self._proof(by_suite=[], unattributed=["a", "b"]))
        assert self._row(rows, 12)["status"] == selfcheck.PASS

    def test_check_12_still_fails_when_the_suite_did_write_the_real_tree(self):
        """The finding the lane exists for must not be softened by the split."""
        rows = _harness_rows(self._proof(by_suite=["logs/x.jsonl"], unattributed=[]))
        assert self._row(rows, 12)["status"] == selfcheck.FAIL
        assert "logs/x.jsonl" in self._row(rows, 12)["detail"]

    def test_the_unattributed_set_gets_its_own_row_and_is_not_swallowed(self):
        """Splitting must not become hiding."""
        rows = _harness_rows(self._proof(by_suite=[], unattributed=["a", "b"]))
        assert self._row(rows, 17)["status"] == selfcheck.FAIL

    def test_the_unattributed_row_names_the_probe_window_so_the_red_is_judgeable(self):
        """A short probe UNDER-detects; the reader needs that number here."""
        rows = _harness_rows(self._proof(by_suite=[], unattributed=["a"]))
        assert "0.02" in self._row(rows, 17)["detail"]

    def test_the_two_rows_do_not_share_a_name(self):
        """If both rows say the same thing the split bought nothing."""
        rows = _harness_rows(self._proof(by_suite=["x"], unattributed=["a"]))
        assert self._row(rows, 12)["name"] != self._row(rows, 17)["name"]

    def test_a_clean_run_passes_both_rows(self):
        rows = _harness_rows(self._proof(by_suite=[], unattributed=[]))
        assert self._row(rows, 12)["status"] == selfcheck.PASS
        assert self._row(rows, 17)["status"] == selfcheck.PASS

    def test_an_unprobed_proof_publishes_both_rows_rather_than_one(self):
        """A missing row and a passing row must never look the same."""
        rows = _harness_rows({"probed": False, "note": "no fingerprint"})
        assert {r["check"] for r in rows} >= {1, 12, 17}
