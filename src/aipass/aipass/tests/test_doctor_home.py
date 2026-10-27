# =================== AIPass ====================
# Name: test_doctor_home.py
# Description: Tests for doctor's home, owner-seating, preflight, citizen-count, shared-skills and shadow rows
# Version: 1.4.0
# Created: 2026-10-08
# Modified: 2026-10-26
# =============================================

"""Tests for apps/modules/doctor.py: the AIPASS_HOME rows, owner seating, preflight, the drone count, shared skills, shadows."""
# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module this file imports parses and imports

import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.ui.progress import (
    GLYPH_FAIL,
    GLYPH_PASS,
    GLYPH_WARN,
)
from aipass.aipass.apps.modules.doctor import (
    CheckResult,
    check_identity,
    run_doctor,
    run_doctor_preflight,
)
from aipass.aipass.shared import scaffold_content as sc
from aipass.aipass.tests.support_doctor import _home_at


class TestCheckGlobalAipassHome:
    """Tests for _check_global_aipass_home doctor check."""

    @staticmethod
    def _global_rows():
        """The global-settings rows, reached through check_identity, the Identity group.

        No registry is found, so the group stops before the registry, passport and owner rows.
        """
        with patch("aipass.aipass.apps.modules.doctor._find_registry", return_value=None):
            rows = check_identity()
        return [r for r in rows if r.label in ("global settings", "global AIPASS_HOME")]

    def test_nonexistent_path_is_error(self, tmp_path):
        """AIPASS_HOME pointing to a nonexistent path is flagged as error."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"env": {"AIPASS_HOME": str(tmp_path / "gone")}}),
            encoding="utf-8",
        )
        with _home_at(tmp_path):
            results = self._global_rows()
        fails = [r for r in results if "does not exist" in r.detail]
        assert len(fails) == 1

    def test_throwaway_path_is_error(self, tmp_path):
        """AIPASS_HOME pointing to a temp path is flagged as error."""
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"env": {"AIPASS_HOME": str(tmp_path)}}),
            encoding="utf-8",
        )
        with _home_at(tmp_path):
            results = self._global_rows()
        fails = [r for r in results if "throwaway" in r.detail]
        assert len(fails) == 1

    def test_valid_path_passes(self, tmp_path):
        """AIPASS_HOME pointing to a real, non-temp path passes."""
        real_home = tmp_path / "AIPass"
        real_home.mkdir()
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"env": {"AIPASS_HOME": str(real_home)}}),
            encoding="utf-8",
        )
        with (
            _home_at(tmp_path),
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.is_throwaway_path",
                return_value=False,
            ),
        ):
            results = self._global_rows()
        assert any(r.glyph == GLYPH_PASS for r in results)

    def test_no_settings_file_is_noop(self, tmp_path):
        """Missing ~/.claude/settings.json produces no results."""
        with _home_at(tmp_path):
            results = self._global_rows()
        assert results == []

    def test_unreadable_settings_is_error_not_silence(self, tmp_path):
        """Corrupt settings.json is a FAIL row, not the silence of a missing file.

        Mutant: the unreadable branch returns `results` (empty) again -> red.
        """
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("{not json", encoding="utf-8")
        with _home_at(tmp_path):
            results = self._global_rows()
        assert [(r.label, r.glyph) for r in results] == [("global settings", GLYPH_FAIL)]
        assert "~/.claude/settings.json" in results[0].detail


class TestCheckOwnerSeating:
    """Tests for owner/identity detection via sync-registry --check.

    Through check_identity: a tmp registry with one branch reaches the owner rows, and
    the two reads of the live provider settings answer nothing.
    """

    @pytest.fixture(autouse=True)
    def _identity_edges(self, tmp_path, monkeypatch) -> None:
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(json.dumps({"branches": [{"name": "vera"}]}), encoding="utf-8")
        mod = "aipass.aipass.apps.modules.doctor"
        monkeypatch.setattr(f"{mod}._find_registry", lambda: registry)
        monkeypatch.setattr(f"{mod}._check_global_aipass_home", lambda: [])
        monkeypatch.setattr(f"{mod}._configured_aipass_home", lambda: "")

    @staticmethod
    def _owner_rows():
        return [r for r in check_identity() if r.label.startswith("owner")]

    def test_clean_owner_returns_pass(self):
        check_json = json.dumps({"clean": True, "owner": "vera", "owner_uid": "8fb38c96-abcd", "issues": []})
        mock_proc = MagicMock(returncode=0, stdout=check_json, stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._owner_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_PASS
        assert "@vera" in results[0].detail
        assert "8fb38c96" in results[0].detail

    def test_unseated_owner_returns_errors(self):
        check_json = json.dumps(
            {
                "clean": False,
                "owner": None,
                "owner_uid": "",
                "issues": [
                    {"flag": "no_owner", "detail": "No owner:true in registry"},
                    {"flag": "metadata_id_missing", "detail": "metadata.id absent"},
                ],
            }
        )
        mock_proc = MagicMock(returncode=1, stdout=check_json, stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._owner_rows()
        assert len(results) == 2
        assert all(r.glyph == GLYPH_FAIL for r in results)
        assert results[0].label == "owner/no_owner"

    def test_issue_with_branch_field(self):
        check_json = json.dumps(
            {
                "clean": False,
                "owner": "vera",
                "owner_uid": "8fb38c96",
                "issues": [
                    {"flag": "entry_rid_stale", "detail": "stale rid", "branch": "vera"},
                ],
            }
        )
        mock_proc = MagicMock(returncode=1, stdout=check_json, stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._owner_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_FAIL
        assert results[0].label == "owner/entry_rid_stale"

    def test_drone_not_found_returns_warn(self):
        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=FileNotFoundError("drone"),
        ):
            results = self._owner_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN
        assert "drone" in results[0].detail

    def test_timeout_returns_warn(self):
        import subprocess as _sp

        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=_sp.TimeoutExpired("drone", 30),
        ):
            results = self._owner_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_non_json_output_returns_warn(self):
        mock_proc = MagicMock(returncode=1, stdout="not json at all", stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._owner_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_empty_stdout_exit_zero(self):
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._owner_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_PASS


class TestFixOwnerSeating:
    """Tests for owner/identity repair via sync-registry --fix.

    Through run_doctor(fix=True): the other groups and the live-settings fix steps answer nothing.
    """

    @pytest.fixture(autouse=True)
    def _every_other_edge(self, monkeypatch) -> None:
        mod = "aipass.aipass.apps.modules.doctor"
        for name in ("_check_system", "check_identity", "_check_community", "_check_structure", "_check_scaffold"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_sandbox", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.check_provider_manifest", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.reconcile_stale_deny", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.check_wire_verify", lambda: [])
        self.printed: dict = {}

        def _record(groups):
            self.printed.update(groups)
            return 0, 0, 0

        monkeypatch.setattr(f"{mod}._print_doctor_groups", _record)

    def _fix_rows(self):
        run_doctor(fix=True)
        return [r for r in self.printed["Identity"] if r.label.startswith("owner")]

    def test_fix_success_returns_pass(self):
        """A fix that exits 0 shows the re-check's row (here a clean, empty --check), not its own tick."""
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._fix_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_PASS
        assert results[0].label == "owner"

    def test_fix_failure_returns_fail(self):
        mock_proc = MagicMock(returncode=1, stdout="", stderr="owner conflict")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._fix_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_FAIL

    def test_fix_drone_not_found(self):
        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=FileNotFoundError("drone"),
        ):
            results = self._fix_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN

    def test_fix_timeout(self):
        import subprocess as _sp

        with patch(
            "aipass.aipass.apps.modules.doctor.subprocess.run",
            side_effect=_sp.TimeoutExpired("drone", 60),
        ):
            results = self._fix_rows()
        assert len(results) == 1
        assert results[0].glyph == GLYPH_WARN


class TestRunDoctorPreflight:
    """Tests for run_doctor_preflight — doctor-before-hello (round-2 addendum 2)."""

    def test_returns_error_count_and_empty_items_when_hooks_wired(self) -> None:
        groups = {
            "System": [],
            "Identity": [],
            "Services": [CheckResult("hooks", GLYPH_PASS, "9 provider hooks wired", "")],
            "Community": [],
            "Structure": [],
            "Sandbox": [],
        }
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            error_count, hook_action_items = run_doctor_preflight()
        assert error_count == 0
        assert hook_action_items == []

    def test_still_broken_hooks_surfaced_as_action_items(self) -> None:
        groups = {
            "Services": [
                CheckResult("hooks", GLYPH_WARN, "2 hook(s) missing from provider settings: Stop, Notification", ""),
                CheckResult("wire verify", GLYPH_FAIL, "verify failed", ""),
            ],
        }
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            _error_count, hook_action_items = run_doctor_preflight()
        assert any("hooks:" in item for item in hook_action_items)
        assert any("wire verify:" in item for item in hook_action_items)

    def test_passing_checks_excluded_from_action_items(self) -> None:
        groups = {"Services": [CheckResult("hooks", GLYPH_PASS, "9 provider hooks wired", "")]}
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            _error_count, hook_action_items = run_doctor_preflight()
        assert hook_action_items == []

    def test_fix_true_and_the_install_door_passed_through_to_compute_groups(self) -> None:
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value={}) as mock_compute:
            run_doctor_preflight(fix=True)
        mock_compute.assert_called_once_with(fix=True, door="install")

    def test_error_count_reflects_fail_glyphs(self) -> None:
        groups = {"System": [CheckResult("test", GLYPH_FAIL, "bad", "")]}
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups):
            error_count, _hook_action_items = run_doctor_preflight()
        assert error_count == 1


class TestDroneCitizenCount:
    """`drone systems` lists addressable SYSTEMS; the registry lists CITIZENS.

    `@git` is routed by drone but has no passport, so the counts legitimately differ.
    """

    @staticmethod
    def _systems_stdout(names) -> str:
        return "\n".join(f"  @{n}    Some description here" for n in names)

    @staticmethod
    def _run(stdout, registry_names):
        """The drone row, reached through run_doctor, first row of its Services group.

        Every other group, and each Services row reading live settings or the home, answers nothing.
        """
        import subprocess as _sp

        mod = "aipass.aipass.apps.modules.doctor"
        proc = _sp.CompletedProcess(args=["drone", "systems"], returncode=0, stdout=stdout, stderr="")
        printed: dict = {}

        def _record(groups):
            printed.update(groups)
            return 0, 0, 0

        with (
            patch("subprocess.run", return_value=proc),
            patch(f"{mod}._registry_citizen_names", return_value=set(registry_names)),
            patch(f"{mod}._check_system", return_value=[]),
            patch(f"{mod}.check_identity", return_value=[]),
            patch(f"{mod}._check_community", return_value=[]),
            patch(f"{mod}._check_structure", return_value=[]),
            patch(f"{mod}._check_scaffold", return_value=[]),
            patch(f"{mod}._check_sandbox", return_value=[]),
            patch(f"{mod}.check_provider_manifest", return_value=[]),
            patch(f"{mod}.check_wire_verify", return_value=[]),
            patch(f"{mod}.reconcile_stale_deny", return_value=[]),
            patch(f"{mod}.check_admin_lane", return_value=[]),
            patch(f"{mod}._print_doctor_groups", side_effect=_record),
        ):
            run_doctor()
        return printed["Services"][0]

    def test_extra_system_is_named_not_silently_counted(self) -> None:
        """The unregistered name appears, so nobody has to guess what the +1 is."""
        row = self._run(self._systems_stdout(["drone", "aipass", "git"]), ["drone", "aipass"])

        assert "git" in row.detail
        assert "2 citizens" in row.detail

    def test_counts_agree_reads_as_plain_citizens(self) -> None:
        """No discrepancy → no extra noise; the row stays the short old form."""
        row = self._run(self._systems_stdout(["drone", "aipass"]), ["drone", "aipass"])

        assert row.detail == "2 citizens"
        assert "service" not in row.detail

    def test_registry_only_citizen_is_not_reported_as_extra(self) -> None:
        """A citizen drone does not route is not an 'extra system'."""
        row = self._run(self._systems_stdout(["drone"]), ["drone", "ghost"])

        assert "ghost" not in row.detail

    def test_row_still_passes_when_counts_differ(self) -> None:
        """A legitimate difference is not a health failure."""
        row = self._run(self._systems_stdout(["drone", "git"]), ["drone"])

        assert row.glyph == GLYPH_PASS

    def test_many_extras_are_summarized_not_dumped(self) -> None:
        """The detail stays a one-liner even if the sets diverge badly."""
        extras = [f"svc{n}" for n in range(9)]
        row = self._run(self._systems_stdout(["drone", *extras]), ["drone"])

        assert len(row.detail) < 120
        assert "more" in row.detail

    def test_description_text_containing_an_at_sign_is_not_counted(self) -> None:
        """Counting lines-with-@ counted prose; count NAMES at line start."""
        stdout = "  @aipass    Concierge — talks to @drone and @spawn for routing\n"
        row = self._run(stdout, ["aipass"])

        assert row.detail == "1 citizens"


class TestHomeAgreement:
    """Doctor prints the active tree and Claude Code's tree on adjacent lines.

    A second install can leave terminal tooling and Claude Code's hooks on different trees.
    """

    @staticmethod
    def _run(active, configured):
        """The agreement rows, reached through check_identity, the Identity group doctor runs.

        No registry, so the active tree is AIPASS_HOME; both live-settings reads are stood in for.
        """
        mod = "aipass.aipass.apps.modules.doctor"
        with (
            patch(f"{mod}._find_registry", return_value=None),
            patch(f"{mod}._configured_aipass_home", return_value=configured),
            patch(f"{mod}._check_global_aipass_home", return_value=[]),
            patch.dict(os.environ, {"AIPASS_HOME": active}),
        ):
            rows = check_identity()
        return [r for r in rows if r.label in ("AIPASS_HOME split", "AIPASS_HOME pair")]

    @staticmethod
    def _run_at_registry(root, configured):
        """The home rows when doctor stands at a registry root, Claude Code's tree stood in for."""
        mod = "aipass.aipass.apps.modules.doctor"
        registry = root / "PROJ_REGISTRY.json"
        registry.write_text("{}", encoding="utf-8")
        with (
            patch(f"{mod}._find_registry", return_value=registry),
            patch(f"{mod}._configured_aipass_home", return_value=configured),
            patch(f"{mod}._check_global_aipass_home", return_value=[]),
        ):
            rows = check_identity()
        return [r for r in rows if r.label in ("AIPASS_HOME", "AIPASS_HOME split", "AIPASS_HOME pair")]

    @staticmethod
    def _aipass_tree(path):
        (path / "src" / "aipass").mkdir(parents=True)
        return path

    @staticmethod
    def _external_project(path, names_home):
        (path / ".claude").mkdir(parents=True)
        settings = {"env": {"AIPASS_HOME": str(names_home)}}
        (path / ".claude" / "settings.local.json").write_text(json.dumps(settings), encoding="utf-8")
        return path

    def test_an_external_project_on_the_global_tree_is_no_split(self, tmp_path) -> None:
        tree = self._aipass_tree(tmp_path / "AIPass")
        project = self._external_project(tmp_path / "Vera", tree)

        rows = self._run_at_registry(project, str(tree))

        assert [(r.label, r.glyph, r.detail) for r in rows] == [("AIPASS_HOME", GLYPH_PASS, str(tree))]

    def test_an_external_project_on_another_tree_is_still_a_split(self, tmp_path) -> None:
        tree = self._aipass_tree(tmp_path / "AIPass")
        other = self._aipass_tree(tmp_path / "AIPass2")
        project = self._external_project(tmp_path / "Vera", other)

        rows = self._run_at_registry(project, str(tree))

        (split,) = [r for r in rows if r.label == "AIPASS_HOME split"]
        assert split.glyph == GLYPH_FAIL
        assert str(other) in split.detail and str(tree) in split.detail

    def test_an_aipass_tree_under_another_trees_settings_is_a_split(self, tmp_path) -> None:
        tree = self._aipass_tree(tmp_path / "AIPass")
        checkout = self._aipass_tree(tmp_path / "AIPass2")
        self._external_project(checkout, tree)

        rows = self._run_at_registry(checkout, str(tree))

        (split,) = [r for r in rows if r.label == "AIPASS_HOME split"]
        assert split.glyph == GLYPH_FAIL
        assert str(checkout) in split.detail

    def test_split_brain_is_an_error(self, tmp_path) -> None:
        """Two different trees is a real fault, not an advisory."""
        a, b = tmp_path / "tree1", tmp_path / "tree2"
        a.mkdir()
        b.mkdir()

        rows = self._run(str(a), str(b))

        assert len(rows) == 1
        assert rows[0].glyph == GLYPH_FAIL

    def test_split_brain_names_both_trees(self, tmp_path) -> None:
        """The human needs to see WHICH two trees, not just that they differ."""
        a, b = tmp_path / "tree1", tmp_path / "tree2"
        a.mkdir()
        b.mkdir()

        rows = self._run(str(a), str(b))

        assert "tree1" in rows[0].detail and "tree2" in rows[0].detail
        assert rows[0].remediation

    def test_agreement_emits_nothing(self, tmp_path) -> None:
        """Silent when correct — doctor already prints both values."""
        tmp_path.joinpath("tree").mkdir()
        same = str(tmp_path / "tree")

        assert self._run(same, same) == []

    def test_trailing_slash_is_not_a_split(self, tmp_path) -> None:
        """Cosmetic path differences must not raise a false alarm."""
        tree = tmp_path / "tree"
        tree.mkdir()

        assert self._run(str(tree), str(tree) + "/") == []

    def test_symlinked_same_tree_is_not_a_split(self, tmp_path) -> None:
        """Same real directory reached two ways is one tree."""
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)

        assert self._run(str(real), str(link)) == []

    def test_a_pair_that_cannot_be_compared_is_one_warn_row(self, tmp_path) -> None:
        """A home that cannot be resolved is one WARN row saying so, never silence or a traceback.

        Silence reads as agreement. resolve on a symlink loop raises RuntimeError up to 3.12
        and answers on 3.13, so the test asks inside itself which row follows.
        Mutant: the catch narrowed to OSError -> red on 3.10 to 3.12 (RuntimeError escapes).
        Mutant: the catch answers [] again -> red at the row assert.
        """
        log = logging.getLogger(__name__)
        other = tmp_path / "tree"
        other.mkdir()
        loop = tmp_path / "loop"
        expected = ("AIPASS_HOME split", GLYPH_FAIL)  # no loop, or resolve answers it: two different trees
        try:
            loop.symlink_to("loop2")
            (tmp_path / "loop2").symlink_to("loop")
        except OSError as exc:
            log.info("the platform refused the symlink (%s): the pair differs and is compared", exc)
        else:
            try:
                loop.resolve()
            except (OSError, RuntimeError) as exc:
                log.info("resolve raised on the loop (%s): the pair cannot be compared", exc)
                expected = ("AIPASS_HOME pair", GLYPH_WARN)

        rows = self._run(str(loop), str(other))

        assert [(r.label, r.glyph) for r in rows] == [expected]

    def test_missing_either_value_emits_nothing(self, tmp_path) -> None:
        """Nothing to compare is not a disagreement — the other rows own that."""
        assert self._run("", str(tmp_path)) == []
        assert self._run(str(tmp_path), "") == []
        assert self._run("", "") == []


class TestSharedSkillsRows:
    """The Scaffold group's skills rows and their --fix, through run_doctor; every other group answers nothing."""

    @pytest.fixture(autouse=True)
    def _every_other_edge(self, monkeypatch, tmp_path) -> None:
        mod = "aipass.aipass.apps.modules.doctor"
        for name in ("_check_system", "check_identity", "_check_community", "_check_structure", "_check_sandbox"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.check_provider_manifest", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.reconcile_stale_deny", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.fix_provider_settings", lambda *_a, **_kw: [])
        monkeypatch.setattr(f"{mod}.check_wire_verify", lambda: [])
        monkeypatch.setattr(f"{mod}._fix_owner_seating", lambda: [])
        monkeypatch.setattr(f"{mod}._check_owner_seating", lambda: [])
        self.root = tmp_path / "proj"
        self.root.mkdir()
        registry = self.root / "PROJ_REGISTRY.json"
        registry.write_text(json.dumps({"metadata": {"id": "p"}, "branches": []}), encoding="utf-8")
        monkeypatch.setattr(f"{mod}._find_registry", lambda: registry)
        self.printed: dict = {}

        def _record(groups):
            self.printed.update(groups)
            return 0, 0, 0

        monkeypatch.setattr(f"{mod}._print_doctor_groups", _record)

    def _skill(self, name: str, frontmatter: str) -> None:
        skill = self.root / ".agents" / "skills" / name / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(f"---\n{frontmatter}---\n\nbody\n", encoding="utf-8")

    def _rows(self, **kwargs) -> dict:
        run_doctor(**kwargs)
        return {r.label: r for r in self.printed["Scaffold"]}

    def test_named_skills_behind_a_link_pass_both_rows(self) -> None:
        self._skill("prep", "name: prep\ndescription: wrap up\n")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "skills").symlink_to("../.agents/skills", target_is_directory=True)

        rows = self._rows()

        assert rows["shared skills"].glyph == GLYPH_PASS
        assert rows["shared skills"].detail == "1 in .agents/skills, each named and described"
        assert rows["skills link"].glyph == GLYPH_PASS
        assert rows["skills link"].detail == ".claude/skills -> .agents/skills"

    def test_a_skill_with_an_empty_description_and_a_missing_link_warn_with_the_cure(self) -> None:
        self._skill("prep", "name: prep\ndescription:  \n")

        rows = self._rows()

        assert rows["shared skills"].glyph == GLYPH_WARN
        assert rows["shared skills"].detail == "no name or description: prep"
        assert rows["skills link"].glyph == GLYPH_WARN
        assert rows["skills link"].detail == ".claude/skills missing: Claude Code sees none"
        assert rows["skills link"].remediation.startswith("Run: aipass doctor --fix")
        assert "git config core.symlinks true" in rows["skills link"].remediation
        assert "writes a copy that will not follow .agents/skills" in rows["skills link"].remediation

    def test_a_copied_skills_folder_warns_that_it_will_not_follow(self) -> None:
        self._skill("prep", "name: prep\ndescription: wrap up\n")
        (self.root / ".claude" / "skills" / "prep").mkdir(parents=True)

        row = self._rows()["skills link"]

        assert row.glyph == GLYPH_WARN
        assert row.detail == ".claude/skills is a copy, not a link: it will not follow .agents/skills"
        assert "git config core.symlinks true" in row.remediation

    def test_fix_links_the_folder_and_retires_an_unedited_legacy_prep(self) -> None:
        self._skill("prep", "name: prep\ndescription: wrap up\n")
        legacy = self.root / ".claude" / "commands" / "prep.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(sc.prep_md(), encoding="utf-8")

        before = self._rows()
        after = self._rows(fix=True)

        assert before["legacy prep"].glyph == GLYPH_WARN
        assert before["legacy prep"].remediation == "Run: aipass doctor --fix"
        assert (self.root / ".claude" / "skills").resolve() == (self.root / ".agents" / "skills").resolve()
        assert not legacy.exists()
        assert (legacy.parent / "prep(disabled).md").read_text(encoding="utf-8") == sc.prep_md()
        assert after["skills link"].glyph == GLYPH_PASS
        assert "legacy prep" not in after
        fixes = [r.detail for r in self.printed["Scaffold"] if r.label == "skills fix"]
        assert fixes == [
            "Linked .claude/skills -> ../.agents/skills",
            "Wrote .claude/commands/codex.md",
            "Wrote .codex/skills/claude/SKILL.md",
            "Retired .claude/commands/prep.md -> prep(disabled).md: .agents/skills/prep/SKILL.md replaces it",
        ]

    def test_fix_leaves_an_edited_legacy_prep_and_says_whose_it_is(self) -> None:
        self._skill("prep", "name: prep\ndescription: wrap up\n")
        legacy = self.root / ".claude" / "commands" / "prep.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("# my own prep\n", encoding="utf-8")

        rows = self._rows(fix=True)

        assert legacy.read_text(encoding="utf-8") == "# my own prep\n"
        assert rows["legacy prep"].glyph == GLYPH_WARN
        assert "is edited, so it is yours and kept" in rows["legacy prep"].detail

    def test_a_missing_switch_file_is_named_with_both_cures(self) -> None:
        command = self.root / ".claude" / "commands" / "codex.md"
        command.parent.mkdir(parents=True)
        command.write_text(sc.codex_command_md(), encoding="utf-8")

        row = self._rows()["provider switch"]

        assert row.glyph == GLYPH_WARN
        assert row.detail == "missing .codex/skills/claude/SKILL.md: the chat cannot switch CLI here"
        assert row.remediation == f"Run: aipass doctor --fix, or 'aipass init update {self.root}'"

    def test_fix_writes_the_missing_switch_file_and_leaves_an_edited_one(self) -> None:
        skill = self.root / ".codex" / "skills" / "claude" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# my own switch\n", encoding="utf-8")

        rows = self._rows(fix=True)

        assert (self.root / ".claude" / "commands" / "codex.md").read_text(encoding="utf-8") == sc.codex_command_md()
        assert skill.read_text(encoding="utf-8") == "# my own switch\n"
        assert rows["provider switch"].glyph == GLYPH_PASS


class TestInstructionShadowRows:
    """The Structure group's instruction shadow row and its --fix, through run_doctor; every other group answers nothing."""

    @pytest.fixture(autouse=True)
    def _every_other_edge(self, monkeypatch, tmp_path) -> None:
        mod = "aipass.aipass.apps.modules.doctor"
        for name in ("_check_system", "check_identity", "_check_community", "_check_scaffold", "_check_sandbox"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.check_provider_manifest", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.reconcile_stale_deny", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.fix_provider_settings", lambda *_a, **_kw: [])
        monkeypatch.setattr(f"{mod}.check_wire_verify", lambda: [])
        monkeypatch.setattr(f"{mod}._fix_owner_seating", lambda: [])
        monkeypatch.setattr(f"{mod}._check_owner_seating", lambda: [])
        monkeypatch.setattr(f"{mod}._fix_shared_skills", lambda: [])
        monkeypatch.setattr(f"{mod}._detect_aipass_home", lambda: None)
        self.root = tmp_path / "proj"
        (self.root / ".claude").mkdir(parents=True)
        (self.root / "PROJ_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        monkeypatch.chdir(self.root)
        monkeypatch.setattr(f"{mod}._shadow_root", lambda: self.root)
        self.printed: dict = {}

        def _record(groups):
            self.printed.update(groups)
            return 0, 0, 0

        monkeypatch.setattr(f"{mod}._print_doctor_groups", _record)

    def _write(self, rel: str, text: str) -> None:
        (self.root / rel).write_text(text, encoding="utf-8")

    def _rows(self, **kwargs) -> dict:
        run_doctor(**kwargs)
        return {r.label: r for r in self.printed["Structure"] if "shadow" in r.label}

    def test_a_root_claude_md_with_other_text_fails_naming_the_rename(self) -> None:
        self._write("CLAUDE.md", "# old seed\n")

        row = self._rows()["instruction shadow: CLAUDE.md"]

        shadow = self.root / "CLAUDE.md"
        assert row.glyph == GLYPH_FAIL
        assert row.detail == "Claude Code reads it, not AGENTS.md; texts differ, copying it over is the owner's call"
        assert row.remediation == f"mv '{shadow}' '{shadow}(disabled)', or aipass doctor --fix (renames only)"

    def test_a_dot_claude_copy_of_agents_md_fails_and_says_the_texts_are_equal(self) -> None:
        self._write(".claude/CLAUDE.md", "# agents\n")

        row = self._rows()["instruction shadow: .claude/CLAUDE.md"]

        assert row.glyph == GLYPH_FAIL
        assert row.detail == "Claude Code reads it, not AGENTS.md; texts equal, the rename is the whole fix"

    def test_only_disabled_claude_files_pass(self) -> None:
        self._write("CLAUDE.md(disabled)", "# old seed\n")

        rows = self._rows()

        assert list(rows) == ["instruction shadow"]
        assert rows["instruction shadow"].glyph == GLYPH_PASS

    def test_a_claude_md_with_no_agents_md_beside_it_is_no_shadow_and_is_left(self) -> None:
        (self.root / "AGENTS.md").rename(self.root / "AGENTS.md(disabled)")
        self._write("CLAUDE.md", "# the only file\n")

        rows = self._rows(fix=True)

        assert rows["instruction shadow"].glyph == GLYPH_PASS
        assert (self.root / "CLAUDE.md").read_text(encoding="utf-8") == "# the only file\n"

    def test_fix_renames_every_shadow_and_a_second_run_passes(self) -> None:
        self._write("CLAUDE.md", "# old seed\n")
        self._write(".claude/CLAUDE.local.md", "# local\n")

        fixed = self._rows(fix=True)
        again = self._rows()

        assert not (self.root / "CLAUDE.md").exists()
        assert (self.root / "CLAUDE.md(disabled)").read_text(encoding="utf-8") == "# old seed\n"
        assert (self.root / ".claude" / "CLAUDE.local.md(disabled)").read_text(encoding="utf-8") == "# local\n"
        assert (self.root / "AGENTS.md").read_text(encoding="utf-8") == "# agents\n"
        assert "instruction shadow: CLAUDE.md" not in fixed
        assert fixed["instruction shadow"].glyph == GLYPH_PASS
        assert fixed["shadow fix"].glyph == GLYPH_PASS
        assert list(again) == ["instruction shadow"]
        assert again["instruction shadow"].glyph == GLYPH_PASS

    def test_fix_reports_each_rename(self) -> None:
        self._write("CLAUDE.md", "# old seed\n")
        self._write(".claude/CLAUDE.md", "# culture\n")

        run_doctor(fix=True)

        assert [r.detail for r in self.printed["Structure"] if r.label == "shadow fix"] == [
            "Renamed CLAUDE.md -> CLAUDE.md(disabled)",
            "Renamed .claude/CLAUDE.md -> CLAUDE.md(disabled)",
        ]

    def test_fix_never_overwrites_an_existing_disabled_file(self) -> None:
        self._write("CLAUDE.md", "# newer\n")
        self._write("CLAUDE.md(disabled)", "# older\n")

        rows = self._rows(fix=True)

        assert (self.root / "CLAUDE.md").read_text(encoding="utf-8") == "# newer\n"
        assert (self.root / "CLAUDE.md(disabled)").read_text(encoding="utf-8") == "# older\n"
        assert rows["instruction shadow: CLAUDE.md"].glyph == GLYPH_FAIL
        assert rows["shadow fix"].glyph == GLYPH_WARN
        assert rows["shadow fix"].detail == "Left CLAUDE.md: CLAUDE.md(disabled) already exists beside it"

    def test_fix_leaves_the_claude_files_of_a_root_that_is_home(self) -> None:
        self._write(".claude/CLAUDE.md", "# the user's own memory\n")

        with _home_at(self.root):
            rows = self._rows(fix=True)

        assert (self.root / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") == "# the user's own memory\n"
        assert rows["shadow fix"].detail == (
            "Left .claude/CLAUDE.md: the project root holds $HOME, whose CLAUDE files are the user's"
        )

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need a Windows privilege")
    def test_fix_leaves_a_claude_folder_that_links_outside_the_root(self, tmp_path) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "CLAUDE.md").write_text("# not this project's\n", encoding="utf-8")
        (self.root / ".claude").rename(self.root / "unused")
        (self.root / ".claude").symlink_to(elsewhere, target_is_directory=True)

        rows = self._rows(fix=True)

        assert (elsewhere / "CLAUDE.md").read_text(encoding="utf-8") == "# not this project's\n"
        assert rows["shadow fix"].detail == "Left .claude/CLAUDE.md: its folder resolves outside the project root"

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need a Windows privilege")
    def test_a_claude_md_linked_to_agents_md_is_one_file_and_passes(self) -> None:
        (self.root / "CLAUDE.md").symlink_to("AGENTS.md")

        rows = self._rows()

        assert list(rows) == ["instruction shadow"]
        assert rows["instruction shadow"].glyph == GLYPH_PASS
