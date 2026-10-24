# =================== AIPass ====================
# Name: test_audit_tests_lane_adapter.py
# Description: audit-tests pytest adapter, its nominators and the M10 env copy (split from test_audit_tests_lane.py)
# Version: 1.2.2
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/tests_pytest_standards/adapter.py, envcopy.py and apps/handlers/audit_tests/m10.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/audit_tests/ and handlers/tests_pytest_standards/ parses
# seedgo: no-test-needed(documentation) — that the public lane functions carry docstrings
# seedgo: no-test-needed(stdlib) — hashlib.md5's digest of a file's bytes

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.audit_tests import adapters, m10
from aipass.seedgo.apps.handlers.tests_pytest_standards import (
    adapter,
    corpus,
    envcopy,
    envdiff,
    gutting,
    mutation_runner,
    mutation_shapes,
    nominators,
    statement_deletion,
    unread_redirect_check as R,
)
from aipass.seedgo.tests.support_audit_tests_lane import _spec_for


class TestAdapterShape:
    """The shape gate: this pack must stay invisible to the audit engine."""

    def test_the_adapter_defines_no_check_module(self):
        assert not hasattr(adapter, "check_module")

    def test_the_adapter_defines_no_check_branch(self):
        # If this ever goes green the pack becomes visible to a file-walk that
        # would invoke it once per .py file, with no timeout anywhere.
        assert not hasattr(adapter, "check_branch")

    def test_the_adapter_declares_the_api_this_core_speaks(self):
        assert adapter.ADAPTER_API == adapters.SUPPORTED_ADAPTER_API

    def test_the_pack_manifest_declares_execution_kind(self):
        manifest = json.loads((Path(adapter.__file__).parent / "pack.json").read_text(encoding="utf-8"))
        assert manifest["kind"] == "execution"

    def test_the_manifest_records_the_grant_as_conditional_on_the_machine_check(self):
        manifest = json.loads((Path(adapter.__file__).parent / "pack.json").read_text(encoding="utf-8"))
        assert "execution_isolation" in manifest["granted"]["condition"]


class TestPayloadIsolation:
    """The condition @devpulse's bypass grant is conditional on."""

    def test_the_real_payload_imports_no_aipass(self):
        assert adapters.execution_isolation(Path(adapter.__file__).parent)["isolated"] is True

    def test_a_planted_aipass_import_fails_registration(self, tmp_path):
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "leaky.py").write_text("from aipass.prax import logger\n", encoding="utf-8")
        result = adapters.execution_isolation(tmp_path)
        assert result["isolated"] is False
        assert any("leaky.py" in offender for offender in result["offenders"])


class TestDetect:
    """Cheap, read-only, never raises — and it never imports the target."""

    def test_a_directory_with_tests_is_claimed(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
        detected = adapter.detect(tmp_path)
        assert detected["applicable"] is True
        assert detected["unit_count"] == 1

    def test_a_directory_with_no_test_files_is_not_claimed(self, tmp_path):
        detected = adapter.detect(tmp_path)
        assert detected["applicable"] is False
        assert detected["unit_count"] == 0

    def test_a_refusal_to_claim_still_carries_a_reason(self, tmp_path):
        assert adapter.detect(tmp_path)["reason"]

    def test_loose_test_files_at_the_root_are_found(self, tmp_path):
        (tmp_path / "test_root.py").write_text("def test_a(): pass\n", encoding="utf-8")
        assert adapter.detect(tmp_path)["unit_count"] == 1

    def test_detect_never_raises_on_a_path_that_is_not_there(self, tmp_path):
        assert adapter.detect(tmp_path / "absent")["applicable"] is False


class TestNominate:
    """Static species nominate; they never score (Law M1)."""

    def test_every_nominated_group_carries_no_score(self, tmp_path):
        # Pinned against the DECLARATION, not a count. `== 13` re-broke the
        # moment three species were added, which is the growth the pack's own
        # "three files and one line" promise invites - a count here taxes
        # every addition and measures nothing the next line does not.
        documents = adapter.nominate(_spec_for(tmp_path))
        assert set(documents) == set(adapter.ADAPTER_GROUPS)

        for document in documents.values():
            assert document["score"] is None

    def test_every_group_that_did_not_run_says_why(self, tmp_path):
        # Written when NOTHING was built, so it asserted every group was
        # not_applicable - which pinned the calendar, not the law. The law is
        # Law S1: a group that did not run carries a reason. A group that DID
        # run is a different document, and both now exist.
        documents = adapter.nominate(_spec_for(tmp_path))
        did_not_run = {name for name, document in documents.items() if document["status"] == "not_applicable"}
        silent = sorted(name for name in did_not_run if not documents[name]["reason"])

        # Both DECLARATIONS, unioned, rather than one of them plus a literal:
        # a group moving from "unbuilt" to "opt-in" is a legitimate edit and
        # must not need this line rewritten to stay true.
        assert did_not_run == set(adapter.UNBUILT_EXECUTION_GROUPS) | set(adapter.OPT_IN_EXECUTION_GROUPS)
        assert silent == []

    def test_the_unbuilt_execution_groups_are_still_not_applicable(self, tmp_path):
        """Law S1 for every group that does not run, however many there are."""
        assert {"scoped_survival", "targeted_mutation"} <= set(adapter.UNBUILT_EXECUTION_GROUPS)

        for name in adapter.UNBUILT_EXECUTION_GROUPS:
            document = adapter.nominate(_spec_for(tmp_path))[name]
            assert document["status"] == "not_applicable" and document["reason"]

    def test_the_declared_groups_are_all_returned_by_nominate(self, tmp_path):
        # A declared group the adapter never fills would vanish from the
        # published list, which is precisely what S3 exists to catch.
        assert set(adapter.declared_groups()) == set(adapter.nominate(_spec_for(tmp_path)))


class TestOptInExecutionGroups:
    """A BUILT group nobody asked for still publishes, and says which it is."""

    def test_both_opt_in_groups_are_still_in_the_published_list(self, tmp_path):
        """Law S3: opting out may never remove a group from the artifact."""
        documents = adapter.nominate(_spec_for(tmp_path))

        for name in adapter.OPT_IN_EXECUTION_GROUPS:
            assert name in adapter.declared_groups()
            assert name in documents

    def test_an_unrequested_opt_in_group_is_not_reported_as_unbuilt(self, tmp_path):
        """The reason must not borrow the wording of the groups beside it."""
        documents = adapter.nominate(_spec_for(tmp_path))

        for name in adapter.OPT_IN_EXECUTION_GROUPS:
            reason = documents[name]["reason"]
            assert documents[name]["status"] == "not_applicable"
            assert "not built" not in reason
            assert adapter.OPT_IN_FLAGS[name] in reason, "the reason must name the flag that runs it"

    def test_no_opt_in_group_carries_a_score(self, tmp_path):
        """Neither is in SCORED_GROUPS, so Law S7a refuses a score on either."""
        documents = adapter.nominate(_spec_for(tmp_path))

        for name in adapter.OPT_IN_EXECUTION_GROUPS:
            assert documents[name]["score"] is None

    def test_the_request_rides_on_the_spec_rather_than_on_a_new_parameter(self, tmp_path):
        """The seam itself: `nominate(spec)` can see what the operator asked for."""
        spec = _spec_for(tmp_path)
        spec.execution_groups = ["width_coupling"]

        assert "width_coupling" in spec.execution_groups
        assert spec.to_document()["execution_groups"] == ["width_coupling"]

    def test_a_run_that_opted_in_does_not_document_as_one_that_did_not(self, tmp_path):
        """Two artifacts identical in what was ASKED FOR are unreadable later."""
        plain = _spec_for(tmp_path).to_document()
        opted = _spec_for(tmp_path)
        opted.execution_groups = ["pseudo_tested"]

        assert plain != opted.to_document()
        assert plain["execution_groups"] == []

    def test_the_opt_in_list_is_deduplicated_in_the_order_it_was_asked_for(self):
        """A flag typed twice must not read back as two campaigns requested."""
        assert envcopy.normalise_execution_groups(["width_coupling", "pseudo_tested", "width_coupling"]) == [
            "width_coupling",
            "pseudo_tested",
        ]

    def test_nothing_is_requested_when_nothing_was_asked_for(self):
        """The default is the behaviour the lane had before the seam existed."""
        assert envcopy.normalise_execution_groups(None) == []

    def test_an_engine_that_raises_produces_a_group_and_never_a_crash(self, monkeypatch, tmp_path):
        """Law S1 at its sharpest: could-not-run and found-nothing differ."""

        def _explode(*args, **kwargs):
            raise RuntimeError("no interpreter")

        monkeypatch.setattr(envdiff, "measure_width_coupling", _explode)
        spec = _spec_for(tmp_path)
        spec.execution_groups = [envdiff.GROUP]

        document = adapter.nominate(spec)[envdiff.GROUP]

        assert document["status"] == "not_applicable"
        assert "RuntimeError" in document["reason"] and "no interpreter" in document["reason"]
        assert document["score"] is None
        assert document["diverged"] == []


class TestCampaignBudget:
    """`--budget` reaches the mutation campaigns, not only the suite run (DPLAN-0405 M2)."""

    def _recording(self, monkeypatch, engine, discover):
        """Record the budget a campaign is started with, then stop it."""
        seen = {}

        def _record(*args, **kwargs):
            seen["budget_seconds"] = kwargs.get("budget_seconds")
            raise RuntimeError("recorded")

        monkeypatch.setattr(engine, discover, lambda *args, **kwargs: [])
        monkeypatch.setattr(engine, "run_campaign", _record)
        return seen

    def test_the_operators_budget_reaches_the_pseudo_tested_campaign(self, monkeypatch, tmp_path):
        seen = self._recording(monkeypatch, gutting, "discover_functions")
        spec = _spec_for(tmp_path)
        spec.execution_groups = [gutting.GROUP]
        spec.campaign_budget_seconds = 3600

        adapter.nominate(spec)

        assert seen["budget_seconds"] == 3600

    def test_the_operators_budget_reaches_the_statement_deletion_campaign(self, monkeypatch, tmp_path):
        seen = self._recording(monkeypatch, statement_deletion, "discover_statements")
        spec = _spec_for(tmp_path)
        spec.execution_groups = [statement_deletion.GROUP]
        spec.campaign_budget_seconds = 2400

        adapter.nominate(spec)

        assert seen["budget_seconds"] == 2400

    def test_no_budget_leaves_the_campaign_at_its_own_default(self, monkeypatch, tmp_path):
        seen = self._recording(monkeypatch, gutting, "discover_functions")
        spec = _spec_for(tmp_path)
        spec.execution_groups = [gutting.GROUP]

        adapter.nominate(spec)

        assert seen["budget_seconds"] == gutting.DEFAULT_BUDGET_SECONDS == 1800

    def test_build_env_carries_the_budget_option_onto_the_spec_it_publishes(self, tmp_path, monkeypatch):
        # rsync is the edge: Windows runners have none (PR #786, run 38365012946); the spec is the claim.
        monkeypatch.setattr(envcopy, "rsync", lambda source, destination: shutil.copytree(source, destination) and None)
        target = tmp_path / "proj"
        (target / "tests").mkdir(parents=True)
        (target / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")

        spec = adapter.build_env(target, tmp_path / "env", {"budget_seconds": 3600})

        assert spec.campaign_budget_seconds == 3600
        assert spec.to_document()["campaign_budget_seconds"] == 3600


class TestEnvLayout:
    """The aipass layout has to be mirrored or the copy is not what loads."""

    def test_a_branch_under_src_aipass_is_the_aipass_layout(self, tmp_path):
        branch = tmp_path / "src" / "aipass" / "somebranch"
        branch.mkdir(parents=True)
        layout, repo_root = envcopy.detect_layout(branch)
        assert layout == "aipass"
        assert repo_root == tmp_path

    def test_any_other_directory_is_plain(self, tmp_path):
        assert envcopy.detect_layout(tmp_path)[0] == "plain"

    def test_a_plain_target_has_no_repo_root(self, tmp_path):
        assert envcopy.detect_layout(tmp_path)[1] is None

    def test_a_plain_src_layout_puts_the_copy_first_and_probes_its_package(self, tmp_path):
        """An editable install of a src-layout project would otherwise import the real package."""
        project = tmp_path / "project"
        (project / "src" / "pkg").mkdir(parents=True)
        (project / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        plugin = tmp_path / "plugin.py"
        plugin.write_text("", encoding="utf-8")

        spec = envcopy.build_env(project, tmp_path / "env", plugin)

        assert spec.pythonpath.split(os.pathsep)[0] == str((tmp_path / "env" / "project" / "src").resolve())
        assert spec.target_module == "pkg"


class TestRootFiles:
    """A suite reading the launcher or `.aipass/` by path needs the clone's root, never its machine state."""

    def _repo(self, tmp_path):
        """A repo root with a launcher, an ignored registry and a declared directory."""
        (tmp_path / ".git").mkdir(parents=True)
        (tmp_path / "aipass").write_text("#!/bin/sh\n", encoding="utf-8")
        (tmp_path / "aipass").chmod(0o755)
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".aipass" / "__pycache__").mkdir(parents=True)
        (tmp_path / ".aipass" / "project_hooks.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".aipass" / "alerts.json").write_text("[]", encoding="utf-8")
        (tmp_path / ".aipass" / "__pycache__" / "x.pyc").write_bytes(b"")
        (tmp_path / "projects").mkdir()
        (tmp_path / "projects" / "big.bin").write_bytes(b"")
        return tmp_path

    def _answer(self, monkeypatch, caller, stdout, returncode=0):
        """Stand in for `drone @git tracked` and the caller seat it runs from; rsync still runs.

        The caller is resolved before drone runs, from a gitignored passport a clean checkout lacks.
        """
        asked = []
        real_run = envcopy.subprocess.run

        def _run(command, **kwargs):
            if tuple(command[:3]) != envcopy.TRACKED_QUERY:
                return real_run(command, **kwargs)
            assert kwargs["cwd"] == str(caller)
            asked.extend(command)
            return envcopy.subprocess.CompletedProcess(command, returncode, stdout, "refused")

        monkeypatch.setattr(envcopy, "caller_home", lambda: caller)
        monkeypatch.setattr(envcopy.subprocess, "run", _run)
        return asked

    def test_only_tracked_root_files_are_copied_and_the_launcher_keeps_its_mode(self, tmp_path, monkeypatch):
        repo = self._repo(tmp_path / "repo")
        for name in ("t", "prax"):
            (repo / "src" / "aipass" / name / "tests").mkdir(parents=True)
        plugin = tmp_path / "plugin.py"
        plugin.write_text("", encoding="utf-8")
        asked = self._answer(
            monkeypatch,
            tmp_path / "seat",
            "tracked    aipass\nignored    AIPASS_REGISTRY.json\n"
            "tracked    .aipass/project_hooks.json\nignored    .aipass/alerts.json\n",
        )

        spec = envcopy.build_env(repo / "src" / "aipass" / "t", tmp_path / "env", plugin)

        env = spec.env_root
        assert spec.to_document()["root_files"] == [".aipass/project_hooks.json", "aipass"]
        assert spec.root_basis == "2 of 4 repo-root file(s) are tracked and were copied"
        assert os.access(env / "aipass", os.X_OK)
        assert not (env / "AIPASS_REGISTRY.json").exists() and not (env / ".aipass" / "alerts.json").exists()
        assert not any("projects" in part or "__pycache__" in part for part in asked)

    def test_a_root_with_no_git_copies_nothing_and_says_why(self, tmp_path, monkeypatch):
        asked = self._answer(monkeypatch, tmp_path / "seat", "tracked    aipass\n")
        (tmp_path / "aipass").write_text("", encoding="utf-8")

        chosen, basis = envcopy.tracked_root_files(tmp_path)

        assert chosen == [] and asked == []
        assert basis.startswith("no .git at ")

    def test_an_unreadable_tracked_answer_refuses_the_env(self, tmp_path, monkeypatch):
        self._answer(monkeypatch, tmp_path / "seat", "", returncode=3)

        with pytest.raises(envcopy.EnvError, match="could not be read: refused"):
            envcopy.tracked_root_files(self._repo(tmp_path / "repo"))

    def test_a_checkout_with_no_caller_seat_refuses_the_env_before_drone_runs(self, tmp_path, monkeypatch):
        asked = self._answer(monkeypatch, tmp_path / "seat", "tracked    aipass\n")

        def _no_seat():
            raise envcopy.DiffScopeError("no passport above the handler, so drone has no caller")

        monkeypatch.setattr(envcopy, "caller_home", _no_seat)

        with pytest.raises(envcopy.EnvError, match="could not be read: DiffScopeError: no passport above"):
            envcopy.tracked_root_files(self._repo(tmp_path / "repo"))
        assert asked == []


class TestRedBaselineNamesItsFailures:
    """A refused baseline that names no test sends its reader to rebuild the sandbox."""

    def _target(self, tmp_path, body):
        """A one-file suite the baseline really runs."""
        (tmp_path / "test_t.py").write_text(body, encoding="utf-8")
        return mutation_shapes.SuiteTarget(
            python=Path(sys.executable),
            cwd=tmp_path,
            pythonpath=str(tmp_path),
            test_arg="test_t.py",
            target_copy=tmp_path,
        )

    def test_every_failed_and_errored_nodeid_is_recorded_with_its_message(self, tmp_path):
        body = "def test_ok():\n    pass\n\ndef test_a():\n    raise FileNotFoundError('env/aipass')\n"

        base = mutation_runner.baseline(self._target(tmp_path, body), timeout_seconds=120)

        assert base.green is False and base.passed == 1
        assert base.to_document()["failing"] == [
            {"nodeid": "test_t.py::test_a", "message": "FileNotFoundError: env/aipass"}
        ]

    def test_a_green_baseline_records_no_failure(self, tmp_path):
        base = mutation_runner.baseline(self._target(tmp_path, "def test_ok():\n    pass\n"), timeout_seconds=120)

        assert base.green is True and base.to_document()["failing"] == []


class TestTimeoutKillsTheGroup:
    """A timeout reaps everything the child started, not just the child."""

    def test_a_grandchild_dies_with_its_timed_out_parent(self, tmp_path):
        import subprocess
        import time

        marker = tmp_path / "grandchild_survived"
        grandchild = f"import time; time.sleep(1.5); open({str(marker)!r}, 'w').close()"
        parent = (
            f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {grandchild!r}]); time.sleep(60)"
        )

        with pytest.raises(subprocess.TimeoutExpired):
            mutation_runner.run_in_group(
                [sys.executable, "-c", parent], cwd=str(tmp_path), env=dict(os.environ), timeout=0.5
            )
        time.sleep(2.0)

        assert not marker.exists()


class TestM10Completeness:
    """A symlinked sibling is writable, so it is named rather than assumed away."""

    def test_an_env_with_no_symlinks_is_m10_complete(self, tmp_path):
        assert _spec_for(tmp_path).m10_complete is True

    def test_one_symlinked_sibling_makes_the_env_incomplete(self, tmp_path):
        spec = _spec_for(tmp_path)
        spec.symlinked_siblings = ["prax"]
        assert spec.m10_complete is False

    def test_the_environment_document_publishes_the_completeness_flag(self, tmp_path):
        spec = _spec_for(tmp_path)
        spec.symlinked_siblings = ["prax"]
        assert spec.to_document()["m10_complete"] is False

    def test_the_excludes_are_published_as_part_of_the_contract(self, tmp_path):
        published = _spec_for(tmp_path).to_document()["excludes"]
        assert ".chroma" in published
        assert ".venv" in published


class TestPythonResolution:
    """No interpreter path is hardcoded; a one-machine checker is not a checker."""

    def test_an_explicit_override_wins(self, tmp_path):
        # Built from tmp_path, never a POSIX literal: "/opt/py/bin/python" is
        # DRIVE-RELATIVE on Windows, so find_python's abspath correctly resolves
        # it against the current drive and the old literal could never match.
        override = tmp_path / "opt" / "py" / "bin" / "python"
        assert envcopy.find_python(tmp_path, str(override)) == override

    def test_a_nearby_venv_is_preferred_over_the_running_interpreter(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUDIT_TESTS_PYTHON", raising=False)
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("", encoding="utf-8")
        assert envcopy.find_python(tmp_path) == venv / "python"

    def test_the_environment_variable_is_honoured(self, tmp_path, monkeypatch):
        chosen = tmp_path / "opt" / "env" / "bin" / "python"
        monkeypatch.setenv("AUDIT_TESTS_PYTHON", str(chosen))
        assert envcopy.find_python(tmp_path) == chosen

    def test_a_relative_override_is_made_absolute(self, tmp_path, monkeypatch):
        # Kills the mutant that drops abspath. The two tests above cannot: they
        # pass an already-absolute tmp_path, for which abspath is the identity,
        # so both mutants SURVIVED on Linux (measured) while Windows CI was the
        # only thing defending the line. A RELATIVE override needs resolving on
        # every platform - and the lane must never hand subprocess a path whose
        # meaning depends on the working directory it happens to inherit.
        monkeypatch.delenv("AUDIT_TESTS_PYTHON", raising=False)
        monkeypatch.chdir(tmp_path)
        resolved = envcopy.find_python(tmp_path, os.path.join("rel", "python"))
        assert resolved.is_absolute()
        assert resolved == Path(os.path.abspath(os.path.join("rel", "python")))

    def test_a_tilde_override_is_expanded_to_the_home_directory(self, tmp_path, monkeypatch):
        # Found by mutation while fixing the Windows failures, NOT caused by
        # them: deleting .expanduser() killed no test. A "~" handed to
        # subprocess is a literal directory named "~", not the user's home.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("AUDIT_TESTS_PYTHON", raising=False)
        resolved = envcopy.find_python(tmp_path, os.path.join("~", "py", "python"))
        assert "~" not in str(resolved)
        assert resolved == tmp_path / "py" / "python"

    def test_a_relative_environment_variable_is_made_absolute_too(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIT_TESTS_PYTHON", os.path.join("rel", "envpython"))
        monkeypatch.chdir(tmp_path)
        resolved = envcopy.find_python(tmp_path)
        assert resolved.is_absolute()
        assert resolved == Path(os.path.abspath(os.path.join("rel", "envpython")))


class TestSnapshotDiff:
    """Content is hashed, because a same-tick timestamp restore is invisible."""

    def test_a_rewritten_file_is_reported_as_modified(self, tmp_path):
        probe = tmp_path / "state.json"
        probe.write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        probe.write_text('{"forged": true}', encoding="utf-8")
        os.utime(probe, ns=(0, 0))
        after = m10.snapshot_tree(tmp_path)
        assert str(probe) in m10.diff_snapshots(before, after)["modified"]

    def test_two_files_of_identical_size_are_told_apart_by_content(self, tmp_path):
        # The rewrite test above changes the file's SIZE, so the diff fires on
        # stat alone and the hash is never exercised - a mutation deleting the
        # md5 survived it. This is the pin the hash actually needs: the
        # same-size forge is the case stat fields cannot see, and it is the
        # only reason content is hashed rather than inferred.
        first, second = tmp_path / "a.json", tmp_path / "b.json"
        first.write_text('{"a": 1}', encoding="utf-8")
        second.write_text('{"a": 2}', encoding="utf-8")
        snapshot = m10.snapshot_tree(tmp_path)
        left, right = snapshot[str(first)], snapshot[str(second)]
        assert left[1] == right[1]
        assert left[4] != right[4]

    def test_a_same_size_rewrite_is_still_reported_as_modified(self, tmp_path):
        probe = tmp_path / "state.json"
        probe.write_text('{"a": 1}', encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        original = probe.stat().st_mtime_ns
        probe.write_text('{"a": 2}', encoding="utf-8")
        os.utime(probe, ns=(original, original))
        after = m10.snapshot_tree(tmp_path)
        assert str(probe) in m10.diff_snapshots(before, after)["modified"]

    def test_a_file_too_large_to_hash_is_still_fingerprinted_by_stat(self, tmp_path):
        probe = tmp_path / "big.bin"
        probe.write_bytes(b"x" * 64)
        fingerprint = m10.snapshot_tree(tmp_path, 8)[str(probe)]
        assert fingerprint[4] == ""

    def test_a_file_that_vanished_is_absent_rather_than_an_error(self, tmp_path):
        assert m10._fingerprint(str(tmp_path / "gone.txt"), m10.HASH_SIZE_LIMIT) is None

    def test_an_untouched_tree_diffs_to_nothing(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        assert m10.diff_snapshots(before, m10.snapshot_tree(tmp_path)) == {
            "added": [],
            "removed": [],
            "modified": [],
        }

    def test_a_removed_file_is_reported_as_removed(self, tmp_path):
        probe = tmp_path / "a.txt"
        probe.write_text("x", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        probe.unlink()
        assert m10.diff_snapshots(before, m10.snapshot_tree(tmp_path))["removed"] == [str(probe)]


class TestUnreadRedirectNominatesTheMechanism:
    """One autouse fixture that nothing reads blinds a whole seam."""

    def _corpus(self, tmp_path, conftest: str, test_body: str):

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "conftest.py").write_text(conftest, encoding="utf-8")
        (tests / "test_thing.py").write_text(test_body, encoding="utf-8")
        return corpus.build(tmp_path)

    REDIRECT = (
        "import pytest\n"
        "@pytest.fixture(autouse=True)\n"
        "def seam(tmp_path, monkeypatch):\n"
        "    monkeypatch.setenv('AIPASS_TEST_LOG_DIR', str(tmp_path))\n"
        "    return tmp_path\n"
    )

    def test_an_unread_redirect_that_hands_a_target_back_is_nominated(self, tmp_path):
        scanned = self._corpus(tmp_path, self.REDIRECT, "def test_a():\n    assert True\n")
        rows = R.nominate(scanned)
        assert [r["species"] for r in rows] == ["UNREAD-REDIRECT"]
        assert rows[0]["evidence"]["fixture"] == "seam"
        assert rows[0]["verdict"] == corpus.VERDICT_IMPROVE

    def test_a_fence_that_hands_nothing_back_is_never_nominated(self, tmp_path):
        """No target means nothing to read, so nothing reading it is the
        design. This clause is what acquits every isolation guard in the fleet."""
        fence = (
            "import pytest\n"
            "@pytest.fixture(autouse=True)\n"
            "def fence(tmp_path, monkeypatch):\n"
            "    monkeypatch.setenv('AIPASS_TEST_LOG_DIR', str(tmp_path))\n"
        )
        scanned = self._corpus(tmp_path, fence, "def test_a():\n    assert True\n")
        assert R.nominate(scanned) == []
        assert R.acquitted(scanned)[0]["why_not"].startswith("it hands nothing back")

    def test_a_requested_fixture_is_never_nominated(self, tmp_path):
        scanned = self._corpus(tmp_path, self.REDIRECT, "def test_a(seam):\n    assert seam.exists()\n")
        assert R.nominate(scanned) == []

    def test_usefixtures_counts_as_requesting_it(self, tmp_path):
        body = "import pytest\n@pytest.mark.usefixtures('seam')\ndef test_a():\n    assert True\n"
        scanned = self._corpus(tmp_path, self.REDIRECT, body)
        assert R.nominate(scanned) == []

    def test_substituting_the_writer_is_the_second_door_and_acquits(self, tmp_path):
        """MEASURED, not imagined: this is how seedgo observes its own trail,
        and reading it as blindness would report seedgo as blind."""
        body = (
            "def test_a(monkeypatch):\n"
            "    seen = []\n"
            "    monkeypatch.setattr(mod.json_handler, 'log_operation', lambda n, p: seen.append(n))\n"
            "    assert seen == []\n"
        )
        scanned = self._corpus(tmp_path, self.REDIRECT, body)
        assert R.nominate(scanned) == []

    def test_a_dotted_patch_target_is_the_same_door(self, tmp_path):
        """`patch("a.b.json_handler.log_operation")` names the writer inside
        one string. Comparing the whole literal made devpulse and hooks false
        positives; the comparison takes the dotted tail."""
        body = (
            "from unittest.mock import patch\n"
            "def test_a():\n"
            "    with patch('aipass.x.apps.handlers.json.json_handler.log_operation'):\n"
            "        assert True\n"
        )
        scanned = self._corpus(tmp_path, self.REDIRECT, body)
        assert R.nominate(scanned) == []
        assert "substitutes the seam writer" in R.acquitted(scanned)[0]["why_not"]

    def test_a_fixture_that_is_not_autouse_is_out_of_scope(self, tmp_path):
        plain = (
            "import pytest\n"
            "@pytest.fixture\n"
            "def seam(tmp_path, monkeypatch):\n"
            "    monkeypatch.setenv('AIPASS_TEST_LOG_DIR', str(tmp_path))\n"
            "    return tmp_path\n"
        )
        scanned = self._corpus(tmp_path, plain, "def test_a():\n    assert True\n")
        assert R.nominate(scanned) == []
        assert R.acquitted(scanned) == []

    def test_the_rule_declares_itself_to_the_lane(self):
        assert R.GROUP in adapter.STATIC_GROUPS
        assert R.GROUP in nominators.declared_groups()
        assert not hasattr(R, "check_module") and not hasattr(R, "check_branch")
        assert any("floor" in limit.lower() for limit in R.SPECIFICATION["limits"])
