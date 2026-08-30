"""Tests for the audit-tests target resolver, artifact writer and adapter seam.

Three properties these pin, each of which the design argues is load-bearing:

  1. Two external projects with the same directory name must not overwrite
     each other's measurement. The hash suffix is the whole defence.
  2. An unlawful artifact NEVER reaches disk. Validation runs before the
     write, not after, because something could read a file the instant it
     exists.
  3. Registration is CONDITIONAL on payload isolation. @devpulse granted the
     payload bypass conditional on a machine check, so a payload that imports
     aipass must fail registration rather than warn — the grant cannot widen
     silently and it has to outlive everyone who agreed to it.
"""

# =================== META ====================
# Name: test_audit_tests_artifact.py
# Description: Target, artifact and adapter-seam pins for the audit-tests lane
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

# seedgo:bypass standard=architecture reason="test files live in tests/, not apps/"
# seedgo:bypass standard=encapsulation reason="tests import handlers directly for unit testing"

import json
import types
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.audit_tests import adapters, artifact, laws, refusal, spine, target


# =============================================================================
# HELPERS
# =============================================================================


def _branch_target(tmp_path: Path) -> target.Target:
    return target.Target(
        name="canary",
        path=tmp_path,
        kind="branch",
        resolved_from="test fixture",
    )


def _lawful_groups() -> dict:
    groups = {name: spine.spine_document(name) for name in spine.CORE_SPINE}
    groups["hygiene"] = {
        "tier": "exec",
        "status": "measured",
        "score": 100,
        "budget_seconds": 600,
        "elapsed_seconds": 3.7,
        "gate_coverage": {
            "mechanism": "sys.addaudithook (PEP 578), per-interpreter",
            "observed": ["write opens", "subprocess.Popen", "sqlite3.connect"],
            "blind": ["writes by child processes"],
            "child_processes_spawned": 0,
            "sqlite3_connections": {"file_backed": 0, "memory": 0, "read_only": 0},
        },
    }
    groups["ai_advisory"]["kind"] = "nominate_only"
    return groups


def _adapter_module(**overrides) -> types.ModuleType:
    """A module satisfying the adapter contract, for selective breaking."""
    module = types.ModuleType("fake_adapter")
    setattr(module, "ADAPTER_API", adapters.SUPPORTED_ADAPTER_API)
    setattr(module, "ECOSYSTEM", "pytest")
    for name in adapters.REQUIRED_FUNCTIONS:
        setattr(module, name, lambda *a, **k: {})
    for key, value in overrides.items():
        if value is None:
            delattr(module, key)
        else:
            setattr(module, key, value)
    return module


# =============================================================================
# TARGET RESOLUTION
# =============================================================================


class TestTargetResolution:
    def test_a_registry_branch_resolves_to_its_path(self, tmp_path):
        resolved = target.resolve("@backup", {"backup": tmp_path})

        assert resolved.kind == "branch"
        assert resolved.is_registry_branch
        assert resolved.path == tmp_path

    def test_an_unknown_branch_raises_rather_than_guessing(self):
        """A lane that silently measures the wrong tree publishes a wrong number."""
        with pytest.raises(ValueError, match="not a registered branch"):
            target.resolve("@nope", {"backup": Path("/tmp")})

    def test_a_directory_resolves_without_a_registry(self, tmp_path):
        resolved = target.resolve(str(tmp_path))

        assert resolved.kind == "directory"
        assert not resolved.is_registry_branch

    def test_a_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            target.resolve(str(tmp_path / "absent"))

    def test_a_file_target_raises(self, tmp_path):
        handle = tmp_path / "a.txt"
        handle.write_text("x", encoding="utf-8")

        with pytest.raises(NotADirectoryError):
            target.resolve(str(handle))


class TestArtifactNaming:
    def test_a_branch_keeps_its_bare_name(self, tmp_path):
        assert _branch_target(tmp_path).artifact_name() == "audit_tests_canary"

    def test_two_external_targets_with_one_name_do_not_collide(self, tmp_path):
        """The collision this hash exists to prevent, demonstrated."""
        first = tmp_path / "alpha" / "tests"
        second = tmp_path / "beta" / "tests"
        first.mkdir(parents=True)
        second.mkdir(parents=True)

        name_a = target.resolve(str(first)).artifact_name()
        name_b = target.resolve(str(second)).artifact_name()

        assert name_a.startswith("audit_tests_tests_")
        assert name_b.startswith("audit_tests_tests_")
        assert name_a != name_b

    def test_the_same_path_always_hashes_the_same(self, tmp_path):
        assert target.resolve(str(tmp_path)).artifact_name() == target.resolve(str(tmp_path)).artifact_name()

    def test_the_namespace_is_disjoint_from_the_audit(self, tmp_path):
        """Never last_audit_* - a different schema needs a different name."""
        assert not _branch_target(tmp_path).artifact_name().startswith("last_audit")


class TestConfigNote:
    def test_the_target_states_which_configuration_was_measured(self, tmp_path):
        note = _branch_target(tmp_path).to_document()["config_note"]

        assert "SERIAL" in note
        assert "NOT the CI configuration" in note

    def test_layout_is_described_without_changing_what_runs(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

        assert target.describe_layout(_branch_target(tmp_path)) == "pytest.ini at root"


# =============================================================================
# ARTIFACT ASSEMBLY
# =============================================================================


class TestAssembly:
    def test_a_first_run_says_its_baseline_check_did_not_run(self, tmp_path):
        """A check that silently did not run is what section 10 exists to stop."""
        document = artifact.assemble(
            _branch_target(tmp_path),
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="tests_pytest_standards",
            adapter_api=1,
        )

        assert document["group_baseline"] == artifact.FIRST_RUN_BASELINE

    def test_a_later_run_records_the_run_it_compared_against(self, tmp_path):
        previous = {"group_list": list(spine.CORE_SPINE), "provenance": {"run_id": "abc123"}}

        document = artifact.assemble(
            _branch_target(tmp_path),
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="tests_pytest_standards",
            adapter_api=1,
            previous=previous,
        )

        assert document["group_baseline"] == "abc123"

    def test_the_assembled_document_is_lawful(self, tmp_path):
        document = artifact.assemble(
            _branch_target(tmp_path),
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="tests_pytest_standards",
            adapter_api=1,
        )

        assert laws.validate(document) == []

    def test_executed_order_is_recorded(self, tmp_path):
        """Rev 4: order is unreconstructable later, so it is captured at run one."""
        document = artifact.assemble(
            _branch_target(tmp_path),
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="tests_pytest_standards",
            adapter_api=1,
            executed_order=["t.py::a", "t.py::b"],
        )

        assert document["executed_order"] == ["t.py::a", "t.py::b"]

    def test_the_laws_are_stamped_into_every_artifact(self, tmp_path):
        document = artifact.assemble(
            _branch_target(tmp_path),
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="tests_pytest_standards",
            adapter_api=1,
        )

        assert document["laws"]["S9"]
        assert document["scored_groups"] == ["hygiene"]


class TestRefusedArtifact:
    def test_a_refusal_still_publishes_a_complete_document(self, tmp_path):
        """No file at all is indistinguishable from a run that never happened."""
        document = artifact.refused_artifact(_branch_target(tmp_path), refusal.refusal_for_canary())

        assert document["status"] == "refused"
        assert document["refusal"]["law"] == "T10"
        assert set(document["groups"]) == set(spine.CORE_SPINE)

    def test_every_group_in_a_refused_run_is_not_applicable_never_zero(self, tmp_path):
        document = artifact.refused_artifact(_branch_target(tmp_path), refusal.refusal_for_canary())

        for group in document["groups"].values():
            assert group["status"] == "not_applicable"
            assert group["score"] is None
            assert group["reason"]

    def test_a_refused_artifact_is_lawful(self, tmp_path):
        document = artifact.refused_artifact(_branch_target(tmp_path), refusal.refusal_for_canary())

        assert laws.validate(document) == []


class TestExitCode:
    def test_a_clean_publication_is_zero(self, tmp_path):
        document = artifact.assemble(
            _branch_target(tmp_path),
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="a",
            adapter_api=1,
        )

        assert artifact.exit_code_for(document) == refusal.EXIT_PASSED

    def test_a_failing_scored_group_is_one(self, tmp_path):
        groups = _lawful_groups()
        groups["hygiene"]["score"] = 0
        document = artifact.assemble(
            _branch_target(tmp_path),
            groups,
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="a",
            adapter_api=1,
        )

        assert artifact.exit_code_for(document) == refusal.EXIT_SCORED_FAILED

    def test_a_refusal_carries_its_own_code(self, tmp_path):
        document = artifact.refused_artifact(
            _branch_target(tmp_path), refusal.refusal_for_budget(900.0, 600, "hygiene")
        )

        assert artifact.exit_code_for(document) == refusal.EXIT_BUDGET_EXHAUSTED

    def test_an_unscored_group_can_never_move_the_exit_code(self):
        """Advisory means advisory: only SCORED_GROUPS may produce exit 1."""
        document = {
            "status": "published",
            "group_list": ["order_dependence"],
            "groups": {"order_dependence": {"score": 3}},
        }

        assert artifact.exit_code_for(document) == refusal.EXIT_PASSED


class TestPublication:
    def test_an_unlawful_artifact_never_reaches_disk(self, tmp_path, monkeypatch):
        """Validation is BEFORE the write, because a file can be read the instant it exists."""
        monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path / "out")
        this_target = _branch_target(tmp_path)
        groups = _lawful_groups()
        del groups["hygiene"]["gate_coverage"]
        document = artifact.assemble(
            this_target, groups, list(spine.CORE_SPINE), ecosystem="pytest", adapter="a", adapter_api=1
        )

        with pytest.raises(laws.LawViolation):
            artifact.publish(document, this_target)
        assert not artifact.artifact_path(this_target).exists()

    def test_a_lawful_artifact_is_written_and_reloads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path / "out")
        this_target = _branch_target(tmp_path)
        document = artifact.assemble(
            this_target,
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="a",
            adapter_api=1,
        )

        path = artifact.publish(document, this_target)
        assert json.loads(path.read_text(encoding="utf-8"))["artifact_version"] == "audit-tests/1"

    def test_no_temp_file_survives_a_successful_write(self, tmp_path, monkeypatch):
        monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path / "out")
        this_target = _branch_target(tmp_path)
        document = artifact.assemble(
            this_target,
            _lawful_groups(),
            list(spine.CORE_SPINE),
            ecosystem="pytest",
            adapter="a",
            adapter_api=1,
        )

        artifact.publish(document, this_target)
        assert list((tmp_path / "out").glob("*.tmp")) == []

    def test_an_unreadable_previous_artifact_is_not_read_as_nothing_vanished(self, tmp_path, monkeypatch):
        monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path / "out")
        this_target = _branch_target(tmp_path)
        (tmp_path / "out").mkdir()
        artifact.artifact_path(this_target).write_text("{not json", encoding="utf-8")

        assert artifact.load_previous(this_target) is None
        assert artifact.previous_group_list(None) is None


# =============================================================================
# THE ADAPTER SEAM
# =============================================================================


class TestIsolationProof:
    """The condition @devpulse's payload grant is conditional on."""

    def test_a_clean_payload_is_isolated(self, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "plugin.py").write_text("import sys\nimport json\n", encoding="utf-8")

        result = adapters.execution_isolation(tmp_path)
        assert result["isolated"]
        assert result["checked"] == 1

    def test_a_plain_import_of_aipass_breaks_isolation(self, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "plugin.py").write_text("import aipass.prax\n", encoding="utf-8")

        assert not adapters.execution_isolation(tmp_path)["isolated"]

    def test_a_from_import_of_aipass_breaks_isolation(self, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "plugin.py").write_text("from aipass.prax import logger\n", encoding="utf-8")

        offenders = adapters.execution_isolation(tmp_path)["offenders"]
        assert any("from aipass" in o for o in offenders)

    def test_the_word_aipass_in_a_docstring_is_not_a_violation(self, tmp_path):
        """AST, not grep. Nominating on a token is the error this campaign already made twice."""
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "plugin.py").write_text('"""Runs inside aipass but imports none of it."""\n', encoding="utf-8")

        assert adapters.execution_isolation(tmp_path)["isolated"]

    def test_an_unparseable_payload_file_is_unproven_not_clean(self, tmp_path):
        """'Could not check' must never read as 'checked and clean'."""
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "broken.py").write_text("def (((\n", encoding="utf-8")

        result = adapters.execution_isolation(tmp_path)
        assert not result["isolated"]
        assert any("unparseable" in o for o in result["offenders"])

    def test_a_pack_with_no_payload_directory_is_vacuously_isolated(self, tmp_path):
        result = adapters.execution_isolation(tmp_path)

        assert result["isolated"]
        assert result["checked"] == 0


class TestAdapterContract:
    def test_a_complete_adapter_has_no_problems(self):
        assert adapters.contract_problems(_adapter_module()) == []

    @pytest.mark.parametrize("missing", adapters.REQUIRED_FUNCTIONS)
    def test_every_required_function_is_required(self, missing):
        assert any(missing in p for p in adapters.contract_problems(_adapter_module(**{missing: None})))

    @pytest.mark.parametrize("missing", adapters.REQUIRED_CONSTANTS)
    def test_every_required_constant_is_required(self, missing):
        assert any(missing in p for p in adapters.contract_problems(_adapter_module(**{missing: None})))

    def test_an_unsupported_api_version_is_refused(self):
        """The core refuses an adapter it does not speak rather than calling half of it."""
        problems = adapters.contract_problems(_adapter_module(ADAPTER_API=99))

        assert any("this core speaks" in p for p in problems)

    def test_a_non_callable_function_is_caught(self):
        assert any("not callable" in p for p in adapters.contract_problems(_adapter_module(detect="nope")))

    @pytest.mark.parametrize("forbidden", adapters.FORBIDDEN_FUNCTIONS)
    def test_the_shape_gate_forbids_audit_engine_entry_points(self, forbidden):
        """An adapter defining these becomes visible to the file-walk engine."""
        module = _adapter_module()
        setattr(module, forbidden, lambda *a, **k: {})

        assert any("shape gate" in p for p in adapters.contract_problems(module))


class TestClaimTarget:
    def test_the_claiming_adapter_wins(self, tmp_path):
        claimer = _adapter_module(detect=lambda p: {"applicable": True, "unit_count": 5})
        adapter_map = {"pytest": claimer}

        winner, detections = adapters.claim_target(adapter_map, tmp_path)
        assert winner is claimer
        assert detections["pytest"]["applicable"]

    def test_no_claim_returns_none_but_keeps_every_reason(self, tmp_path):
        """A 'no adapter claims this' refusal must be able to say what each one said."""
        adapter_map = {"pytest": _adapter_module(detect=lambda p: {"applicable": False, "reason": "no tests/"})}

        winner, detections = adapters.claim_target(adapter_map, tmp_path)
        assert winner is None
        assert detections["pytest"]["reason"] == "no tests/"

    def test_a_raising_detect_does_not_kill_the_run(self, tmp_path):
        def explode(_path):
            raise RuntimeError("boom")

        adapter_map = {"pytest": _adapter_module(detect=explode)}

        winner, detections = adapters.claim_target(adapter_map, tmp_path)
        assert winner is None
        assert "boom" in detections["pytest"]["reason"]


class TestDiscovery:
    def test_a_pack_without_an_adapter_is_rejected_with_a_reason(self, tmp_path):
        """A pack that vanished silently is how a fleet stops being measured."""
        (tmp_path / "tests_pytest_standards").mkdir()

        found, rejections = adapters.discover_adapters(tmp_path)
        assert found == {}
        assert any("no adapter.py" in r for r in rejections)

    def test_a_pack_whose_payload_imports_aipass_fails_registration(self, tmp_path):
        pack = tmp_path / "tests_pytest_standards"
        (pack / "payload").mkdir(parents=True)
        (pack / "adapter.py").write_text(
            "ADAPTER_API = 1\nECOSYSTEM = 'pytest'\n"
            + "".join(f"def {name}(*a, **k):\n    return {{}}\n" for name in adapters.REQUIRED_FUNCTIONS),
            encoding="utf-8",
        )
        (pack / "payload" / "plugin.py").write_text("from aipass.prax import logger\n", encoding="utf-8")

        found, rejections = adapters.discover_adapters(tmp_path)
        assert found == {}
        assert any("not isolated" in r and "M10" in r for r in rejections)

    def test_a_clean_pack_registers(self, tmp_path):
        pack = tmp_path / "tests_pytest_standards"
        (pack / "payload").mkdir(parents=True)
        (pack / "adapter.py").write_text(
            "ADAPTER_API = 1\nECOSYSTEM = 'pytest'\n"
            + "".join(f"def {name}(*a, **k):\n    return {{}}\n" for name in adapters.REQUIRED_FUNCTIONS),
            encoding="utf-8",
        )
        (pack / "payload" / "plugin.py").write_text("import sys\n", encoding="utf-8")

        found, rejections = adapters.discover_adapters(tmp_path)
        assert list(found) == ["pytest"]
        assert rejections == []


class TestRefusedArtifactAdapterGroups:
    """An adapter group in a refused run has no adapter output to inherit from.

    Added after a surviving mutant: the status override used to be redundant
    with both base documents, so deleting it changed nothing and no test could
    tell. Passing an adapter group makes the override the only source of the
    status, which is what a law-bearing line should be.
    """

    def test_an_adapter_group_is_not_applicable_with_a_reason(self, tmp_path):
        document = artifact.refused_artifact(
            _branch_target(tmp_path),
            refusal.refusal_for_canary(),
            group_list=list(spine.CORE_SPINE) + ["pytest.static_self_skip"],
        )

        group = document["groups"]["pytest.static_self_skip"]
        assert group["status"] == "not_applicable"
        assert group["reason"]
        assert group["score"] is None

    def test_a_refused_run_with_adapter_groups_is_lawful(self, tmp_path):
        document = artifact.refused_artifact(
            _branch_target(tmp_path),
            refusal.refusal_for_canary(),
            group_list=list(spine.CORE_SPINE) + ["pytest.static_self_skip"],
        )

        assert laws.validate(document) == []
