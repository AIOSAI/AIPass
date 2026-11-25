# =================== AIPass ====================
# Name: test_doctor_home.py
# Description: Tests for doctor's home, seating, preflight, citizen-count, skills, shadow, smoke, registry, scope rows
# Version: 1.13.0
# Created: 2026-10-08
# Modified: 2026-11-24
# =============================================

"""Tests for apps/modules/doctor.py and _doctor_smoke.py: home, seating, preflight, drone, skills, shadows, smoke."""
# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that every module this file imports parses and imports

import json
import logging
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from aipass.aipass.apps.handlers.ui.progress import (
    GLYPH_FAIL,
    GLYPH_PASS,
    GLYPH_WARN,
)
from aipass.aipass.apps.handlers.structure_scan.structure_scanner import check_gitignore_coverage
from aipass.aipass.apps.modules.doctor import (
    CheckResult,
    check_identity,
    handle_command,
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
        self.home = tmp_path / "home"
        self.home.mkdir()
        registry = self.home / "AIPASS_REGISTRY.json"
        registry.write_text(json.dumps({"branches": [{"name": "vera"}]}), encoding="utf-8")
        mod = "aipass.aipass.apps.modules.doctor"
        monkeypatch.setattr(f"{mod}._find_registry", lambda: registry)
        monkeypatch.setattr(f"{mod}._check_global_aipass_home", lambda: [])
        monkeypatch.setattr(f"{mod}._configured_aipass_home", lambda: "")
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        monkeypatch.chdir(self.home)

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

    def test_an_empty_check_output_with_exit_zero_warns_not_passes(self):
        """Mutant: the rc-0 empty branch returns PASS "clean (no details)" again -> red."""
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", return_value=mock_proc):
            results = self._owner_rows()
        assert [(r.label, r.glyph) for r in results] == [("owner", GLYPH_WARN)]
        assert "printed nothing" in results[0].detail
        assert "sync-registry --check" in results[0].remediation

    def test_outside_any_project_the_check_runs_in_aipass_home(self, tmp_path, monkeypatch):
        """Mutant: subprocess.run without cwd=root (the caller's cwd) -> red."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("AIPASS_HOME", str(self.home))
        check_json = json.dumps({"clean": True, "owner": "vera", "owner_uid": "8fb38c96", "issues": []})
        seen: list = []

        def _run(cmd, **kw):
            seen.append(kw.get("cwd"))
            return MagicMock(returncode=0, stdout=check_json, stderr="")

        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", side_effect=_run):
            results = self._owner_rows()
        assert seen == [self.home]
        assert [r.glyph for r in results] == [GLYPH_PASS]

    def test_with_no_project_and_no_aipass_home_the_row_warns_and_names_the_fix(self, tmp_path, monkeypatch):
        """Mutant: the no-root guard dropped, the check runs in a bare dir -> red (run is called)."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        with patch("aipass.aipass.apps.modules.doctor.subprocess.run", side_effect=AssertionError("ran")):
            results = self._owner_rows()
        assert [(r.label, r.glyph) for r in results] == [("owner", GLYPH_WARN)]
        assert "no AIPASS_HOME" in results[0].detail
        assert "export AIPASS_HOME" in results[0].remediation


class TestFixOwnerSeating:
    """Tests for owner/identity repair via sync-registry --fix.

    Through run_doctor(fix=True): the other groups and the live-settings fix steps answer nothing.
    """

    @pytest.fixture(autouse=True)
    def _every_other_edge(self, tmp_path, monkeypatch) -> None:
        mod = "aipass.aipass.apps.modules.doctor"
        (tmp_path / "AIPASS_REGISTRY.json").write_text('{"branches": []}', encoding="utf-8")
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        monkeypatch.chdir(tmp_path)
        for name in ("_check_system", "check_identity", "_check_community", "_check_structure", "_check_scaffold"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
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
        """A fix that exits 0 shows the re-check's row (here a clean --check), not its own tick."""
        mock_proc = MagicMock(returncode=0, stdout='{"clean": true, "issues": []}', stderr="")
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

    def test_a_clean_seat_is_not_repaired_and_keeps_its_check_row(self):
        """A fresh install's seatless --fix hit spawn's seat gate on a seat nobody needed to repair."""
        clean = CheckResult("owner", GLYPH_PASS, "@owner OK (seated, uid 12345678)", "")
        with (
            patch("aipass.aipass.apps.modules.doctor.check_identity", return_value=[clean]),
            patch("aipass.aipass.apps.modules.doctor.subprocess.run") as run,
        ):
            results = self._fix_rows()
        assert run.call_count == 0
        assert results == [clean]

    def test_a_defective_seat_is_repaired_and_spawns_refusal_stays_an_error_row(self):
        unseated = CheckResult("owner/unseated", GLYPH_FAIL, "no owner seated", "Run 'aipass doctor --fix'")
        refusal = "sync-registry --fix runs for real from @spawn or the verified admin seat only (caller unknown)"
        with (
            patch("aipass.aipass.apps.modules.doctor.check_identity", return_value=[unseated]),
            patch(
                "aipass.aipass.apps.modules.doctor.subprocess.run",
                return_value=MagicMock(returncode=1, stdout="", stderr=refusal),
            ) as run,
        ):
            results = self._fix_rows()
        assert run.call_args.args[0] == ["drone", "@spawn", "sync-registry", "--fix"]
        assert [(r.label, r.glyph, r.detail) for r in results] == [("owner fix", GLYPH_FAIL, refusal[:120])]


class TestFixRestoresALostPassport:
    """doctor --fix restores a citizen's lost passport through spawn's door, before the owner repair runs."""

    REINSTALL = "Run the installer again: ./aipass install (rebuilds the environment, keeps personal files)"

    @pytest.fixture(autouse=True)
    def _a_citizen_without_its_passport(self, tmp_path, monkeypatch) -> None:
        mod = "aipass.aipass.apps.modules.doctor"
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        monkeypatch.chdir(tmp_path)
        for name in ("_check_system", "_check_community", "_check_scaffold", "check_wire_verify"):
            monkeypatch.setattr(f"{mod}.{name}", lambda: [])
        monkeypatch.setattr(f"{mod}._check_services", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.check_provider_manifest", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}.reconcile_stale_deny", lambda **_kw: [])
        monkeypatch.setattr(f"{mod}._detect_aipass_home", lambda: str(tmp_path / "home"))
        lost = [CheckResult("owner/owner_passport_missing", GLYPH_FAIL, "x", "")]
        monkeypatch.setattr(f"{mod}.check_identity", lambda: lost)
        self.citizen = tmp_path / "src" / "devpulse"
        self.passport = self.citizen / ".trinity" / "passport.json"
        self.registry = tmp_path / "AIPASS_REGISTRY.json"
        rows = {"branches": [{"name": "devpulse", "path": "src/devpulse"}]}
        self.registry.write_text(json.dumps(rows), encoding="utf-8")
        self.kept = {
            self.citizen / ".trinity" / "local.json": '{"sessions": []}',
            self.citizen / ".trinity" / "observations.json": '{"observations": []}',
            self.citizen / "artifacts" / "birth_certificate.json": '{"born": "2026-04-16"}',
            self.citizen / ".ai_mail.local" / "inbox.json": '{"messages": []}',
        }
        for path, text in self.kept.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.seat_saw_passport: list = []
        seated = [CheckResult("owner", GLYPH_PASS, "ok", "")]
        monkeypatch.setattr(
            f"{mod}._check_owner_seating", lambda: self.seat_saw_passport.append(self.passport.exists()) or seated
        )
        self.owner_repairs: list = []
        monkeypatch.setattr(f"{mod}._fix_owner_seating", lambda: self.owner_repairs.append(1) or [])
        self.printed: dict = {}
        monkeypatch.setattr(f"{mod}._print_doctor_groups", lambda groups: self.printed.update(groups) or (0, 0, 0))

    def _restored_rows(self, restore) -> list:
        with patch("aipass.spawn.restore_citizen", side_effect=restore) as door:
            run_doctor(fix=True)
        self.door = door
        rows = self.printed["Structure"]
        return [(r.glyph, r.detail, r.remediation) for r in rows if r.label == "registry: devpulse"]

    def _write_passport(self, *_args) -> list:
        self.passport.write_text('{"branch_info": {"branch_name": "devpulse"}}', encoding="utf-8")
        return ["passport.json(seed)"]

    def test_a_restore_names_what_it_wrote_and_the_seat_check_sees_it_before_any_owner_repair(self) -> None:
        before = self.registry.read_bytes()

        rows = self._restored_rows(self._write_passport)

        assert rows == [(GLYPH_PASS, "passport restored: passport.json(seed)", "")]
        assert self.door.call_args.args == ("devpulse", self.registry)
        assert self.seat_saw_passport == [True]
        assert self.owner_repairs == []
        assert self.registry.read_bytes() == before
        assert {path: path.read_text(encoding="utf-8") for path in self.kept} == self.kept

    def test_a_restore_that_raises_fails_naming_the_installer(self) -> None:
        rows = self._restored_rows(FileNotFoundError("devpulse carries no seed"))

        assert rows == [(GLYPH_FAIL, "passport not restored: devpulse carries no seed", self.REINSTALL)]

    def test_a_restore_that_leaves_the_passport_unreadable_fails_naming_the_installer(self) -> None:
        rows = self._restored_rows(lambda *_a: ["passport.json(seed)"])

        detail = "passport restored: passport.json(seed); still not readable"
        assert rows == [(GLYPH_FAIL, detail, self.REINSTALL)]

    def test_a_project_citizen_with_no_seed_is_sent_to_a_backup_not_the_installer(self) -> None:
        """The installer rebuilds the AIPass tree's own citizens only: for a project it cannot help."""
        project = self.registry.with_name("FINCH_REGISTRY.json")
        project.write_bytes(self.registry.read_bytes())
        self.registry.unlink()

        rows = self._restored_rows(FileNotFoundError("devpulse carries no seed"))

        backup = (
            "No passport vault was written while the passport existed: restore .trinity/passport.json from a backup"
        )
        assert rows == [(GLYPH_FAIL, "passport not restored: devpulse carries no seed", backup)]

    def _a_seedless_citizen(self) -> Path:
        """A core citizen 'flow' with a readable passport and no seed, listed beside devpulse."""
        flow = self.registry.parent / "src" / "flow"
        (flow / ".trinity").mkdir(parents=True)
        (flow / ".trinity" / "passport.json").write_text('{"citizenship": {"residency": "core"}}', encoding="utf-8")
        rows = json.loads(self.registry.read_text(encoding="utf-8"))
        rows["branches"].append({"name": "flow", "path": "src/flow"})
        self.registry.write_text(json.dumps(rows), encoding="utf-8")
        return flow / ".aipass" / "passport.vault.json"

    def _stub_export(self, monkeypatch, seed: Path, refusal: str = "") -> None:
        """spawn's export-vault command: writes the vault, or prints its refusal the way its receipt does."""
        real = subprocess.run
        self.exports: list = []

        def export(cmd, **kwargs):
            if cmd[:3] != ["drone", "@spawn", "export-vault"]:
                return real(cmd, **kwargs)
            self.exports.append(cmd)
            self.events.append("seed")
            if refusal:
                printed = f"1 passport vault(s) could not be exported:\n    flow: {refusal}\n"
                return subprocess.CompletedProcess(cmd, 1, "", printed)
            seed.parent.mkdir(parents=True, exist_ok=True)
            seed.write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "Written: 1\n", "")

        monkeypatch.setattr("subprocess.run", export)

    def test_fix_writes_a_missing_seed_before_passports_are_restored_and_the_owner_is_seated(self, monkeypatch) -> None:
        seed = self._a_seedless_citizen()
        self.events: list = []
        self._stub_export(monkeypatch, seed)
        seated = [CheckResult("owner", GLYPH_PASS, "ok", "")]
        monkeypatch.setattr(
            "aipass.aipass.apps.modules.doctor._check_owner_seating", lambda: self.events.append("seat") or seated
        )

        self._restored_rows(lambda *a: self.events.append("restore") or self._write_passport())

        flow = [(r.glyph, r.detail, r.remediation) for r in self.printed["Structure"] if r.label == "registry: flow"]
        assert flow == [(GLYPH_PASS, f"vault written: {seed}", "")]
        root = str(self.registry.parent)
        assert self.exports == [["drone", "@spawn", "export-vault", "--confirm", "--root", root, "--only", "flow"]]
        assert self.events == ["seed", "restore", "seat"]

    def test_a_seed_spawn_refuses_fails_carrying_spawn_reason_verbatim(self, monkeypatch) -> None:
        seed = self._a_seedless_citizen()
        self.events = []
        reason = "live passport is not a valid 2.0.0 passport: branch_info: missing key 'branch_name'"
        self._stub_export(monkeypatch, seed, refusal=reason)

        self._restored_rows(self._write_passport)

        flow = [(r.glyph, r.detail, r.remediation) for r in self.printed["Structure"] if r.label == "registry: flow"]
        assert flow == [(GLYPH_FAIL, f"vault not written: {reason}", "")]
        assert not seed.exists()


class TestRunDoctorPreflight:
    """run_doctor_preflight: the install's doctor --fix, returning the groups and their counts."""

    def test_returns_the_groups_after_the_fix_and_their_counts(self) -> None:
        """Mutant: the counts dropped for (0, 0, 0) -> red. Mutant: yes not passed on -> red."""
        groups = {
            "System": [CheckResult("python", GLYPH_PASS, "3.12", "")],
            "Services": [
                CheckResult("hooks", GLYPH_WARN, "2 hook(s) missing", "aipass doctor --fix"),
                CheckResult("wire verify", GLYPH_FAIL, "verify failed", ""),
            ],
        }
        with patch("aipass.aipass.apps.modules.doctor._compute_doctor_groups", return_value=groups) as compute:
            assert run_doctor_preflight(yes=True) == (groups, (1, 1, 1))
        compute.assert_called_once_with(fix=True, door="install", yes=True, install=True)


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

    def test_no_routed_names_is_a_warn_not_a_pass(self) -> None:
        """Mutant: an empty `drone systems` read as PASS "ok" -> red."""
        row = self._run("", ["drone"])

        assert (row.glyph, row.detail) == (GLYPH_WARN, "drone systems listed no agents")

    def test_a_group_that_raises_is_one_fail_row_and_the_run_goes_on(self) -> None:
        """Mutant: the group's try removed -> the whole run raises -> red."""
        mod = "aipass.aipass.apps.modules.doctor"
        printed: dict = {}

        def _record(groups):
            printed.update(groups)
            return 0, 0, 1

        with (
            patch(f"{mod}._check_system", side_effect=RuntimeError("RAM unreadable: psutil failed")),
            patch(f"{mod}.check_identity", return_value=[]),
            patch(f"{mod}._check_services", return_value=[]),
            patch(f"{mod}._check_community", return_value=[]),
            patch(f"{mod}._check_structure", return_value=[]),
            patch(f"{mod}._check_scaffold", return_value=[]),
            patch(f"{mod}._print_doctor_groups", side_effect=_record),
        ):
            assert run_doctor() == 1
        assert printed["System"] == [
            CheckResult("system", GLYPH_FAIL, "could not run: RAM unreadable: psutil failed", "Repair what it names")
        ]
        assert printed["Scaffold"] == []


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
        for name in ("_check_system", "check_identity", "_check_community", "_check_structure"):
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

    def test_no_aipass_home_is_a_fail_row_and_the_template_compares_never_pass(self) -> None:
        (self.root / ".aipass").mkdir()
        (self.root / ".aipass" / "tier0_kernel.md").write_text("# kernel\n", encoding="utf-8")
        (self.root / ".aipass" / "hooks.json").write_text("{}\n", encoding="utf-8")

        with patch("aipass.aipass.apps.modules.doctor._detect_aipass_home", return_value=None):
            rows = self._rows()

        assert (rows["aipass home"].glyph, rows["aipass home"].detail) == (GLYPH_FAIL, "not found")
        assert rows["aipass home"].remediation == "Set AIPASS_HOME=/path/to/AIPass"
        assert "tier0_kernel.md" not in rows
        assert "hooks handlers" not in rows

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
        assert "writes a copy that will not follow .agents/skills" in rows["skills link"].remediation

    def test_a_copied_skills_folder_warns_that_it_will_not_follow(self) -> None:
        self._skill("prep", "name: prep\ndescription: wrap up\n")
        (self.root / ".claude" / "skills" / "prep").mkdir(parents=True)

        row = self._rows()["skills link"]

        assert row.glyph == GLYPH_WARN
        assert row.detail == ".claude/skills is a copy, not a link: it will not follow .agents/skills"

    def test_fix_links_the_missing_skills_folder(self) -> None:
        self._skill("prep", "name: prep\ndescription: wrap up\n")

        after = self._rows(fix=True)

        assert (self.root / ".claude" / "skills").resolve() == (self.root / ".agents" / "skills").resolve()
        assert after["skills link"].glyph == GLYPH_PASS
        fixes = [r.detail for r in self.printed["Scaffold"] if r.label == "skills fix"]
        assert fixes == ["Linked .claude/skills -> ../.agents/skills"]

    def test_a_missing_switch_file_is_named_with_both_cures(self) -> None:
        command = self.root / ".claude" / "commands" / "codex.md"
        command.parent.mkdir(parents=True)
        command.write_text(sc.codex_command_md(), encoding="utf-8")

        row = self._rows()["provider switch"]

        assert row.glyph == GLYPH_WARN
        missing = ".codex/skills/claude/SKILL.md, .claude/commands/opencode.md, .codex/skills/opencode/SKILL.md, "
        missing += ".opencode/commands/claude.md, .opencode/commands/codex.md, .opencode/commands/memo.md, "
        missing += ".opencode/commands/prep.md, .opencode/commands/compass.md"
        assert row.detail == f"missing {missing}: the chat cannot switch CLI here"
        assert row.remediation == f"Run 'aipass init update {self.root}'"

    def test_fix_writes_no_switch_file_and_still_links_the_skills(self) -> None:
        self._skill("prep", "name: prep\ndescription: wrap up\n")
        skill = self.root / ".codex" / "skills" / "claude" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# my own switch\n", encoding="utf-8")

        rows = self._rows(fix=True)

        assert not (self.root / ".claude" / "commands" / "codex.md").exists()
        assert not (self.root / ".opencode").exists()
        assert skill.read_text(encoding="utf-8") == "# my own switch\n"
        assert (self.root / ".claude" / "skills").resolve() == (self.root / ".agents" / "skills").resolve()
        assert rows["skills link"].glyph == GLYPH_PASS
        assert rows["provider switch"].glyph == GLYPH_WARN
        assert rows["provider switch"].detail.startswith(
            "missing .claude/commands/codex.md, .claude/commands/opencode.md"
        )


class TestInstructionShadowRows:
    """The Structure group's instruction shadow row and its --fix, through run_doctor; other groups answer nothing."""

    @pytest.fixture(autouse=True)
    def _every_other_edge(self, monkeypatch, tmp_path) -> None:
        mod = "aipass.aipass.apps.modules.doctor"
        for name in ("_check_system", "check_identity", "_check_community", "_check_scaffold"):
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

    def test_fix_leaves_a_claude_folder_that_links_outside_the_root(self, tmp_path) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "CLAUDE.md").write_text("# not this project's\n", encoding="utf-8")
        (self.root / ".claude").rename(self.root / "unused")
        (self.root / ".claude").symlink_to(elsewhere, target_is_directory=True)

        rows = self._rows(fix=True)

        assert (elsewhere / "CLAUDE.md").read_text(encoding="utf-8") == "# not this project's\n"
        assert rows["shadow fix"].detail == "Left .claude/CLAUDE.md: its folder resolves outside the project root"

    def test_a_claude_md_linked_to_agents_md_is_one_file_and_passes(self) -> None:
        (self.root / "CLAUDE.md").symlink_to("AGENTS.md")

        rows = self._rows()

        assert list(rows) == ["instruction shadow"]
        assert rows["instruction shadow"].glyph == GLYPH_PASS


class TestGitignoreCoverageRows:
    """The Structure group's gitignore coverage row, through run_doctor in a real repo under tmp_path."""

    root: Path
    printed: dict
    _every_other_edge = TestInstructionShadowRows._every_other_edge
    _write = TestInstructionShadowRows._write

    def _track(self, *rels: str) -> None:
        for rel in rels:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            self._write(rel, "state\n")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "-f", *rels], cwd=self.root, check=True)

    def _rows(self, **kwargs) -> dict:
        run_doctor(**kwargs)
        return {r.label: r for r in self.printed["Structure"] if r.label.startswith("gitignore coverage")}

    def test_tracked_runtime_folders_and_the_registry_fail_one_row_each_with_the_untrack_line(self) -> None:
        self._track(".chroma/db.sqlite3", ".chroma/idx/a.bin", "src/p/vera/docs.local/n.md", "src/p/vera/README.md")
        subprocess.run(["git", "add", "-f", "PROJ_REGISTRY.json"], cwd=self.root, check=True)

        rows = self._rows(fix=True)

        assert sorted(rows) == [
            "gitignore coverage: .chroma",
            "gitignore coverage: PROJ_REGISTRY.json",
            "gitignore coverage: src/p/vera/docs.local",
        ]
        chroma = rows["gitignore coverage: .chroma"]
        assert (chroma.glyph, chroma.detail) == (GLYPH_FAIL, "2 tracked file(s) one installation writes")
        assert chroma.remediation.startswith("drone @git untrack --recursive .chroma (files stay on disk)")
        assert rows["gitignore coverage: PROJ_REGISTRY.json"].remediation.startswith("drone @git untrack PROJ_")
        assert (self.root / ".chroma" / "db.sqlite3").is_file()

    def test_a_tracked_file_gone_from_disk_and_a_project_file_pass(self) -> None:
        self._track("dropbox/gone.md", "src/p/vera/apps/vera.py")
        (self.root / "dropbox" / "gone.md").rename(self.root / "gone.md(disabled)")

        rows = self._rows()

        assert list(rows) == ["gitignore coverage"]
        assert (rows["gitignore coverage"].glyph, rows["gitignore coverage"].detail) == (
            GLYPH_PASS,
            "no runtime file tracked",
        )

    def test_the_aipass_source_tree_is_not_measured_its_templates_ship_tracked(self) -> None:
        self._track("src/aipass/spawn/templates/citizen/dropbox/README.md", "pyproject.toml")

        rows = self._rows()

        assert list(rows) == ["gitignore coverage"]
        assert rows["gitignore coverage"].detail.startswith("not measured: the AIPass source tree")

    def test_a_project_nested_in_a_parent_repo_reads_the_index_of_the_repo_that_holds_it(self) -> None:
        self._track("src/aipass/README.md")
        (self.root / ".gitignore").write_text(".spawn/\n*_REGISTRY.json\n", encoding="utf-8")
        nested = self.root / "projects" / "finch"
        for rel in ("FINCH_REGISTRY.json", "src/finch/finch/.spawn/meta.json"):
            (nested / rel).parent.mkdir(parents=True, exist_ok=True)
            (nested / rel).write_text("state\n", encoding="utf-8")

        assert check_gitignore_coverage(nested) == [("gitignore coverage", GLYPH_PASS, "no runtime file tracked", "")]

        subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
        subprocess.run(["git", "add", "-f", "FINCH_REGISTRY.json"], cwd=nested, check=True)

        assert [row[:3] for row in check_gitignore_coverage(nested)] == [
            ("gitignore coverage: FINCH_REGISTRY.json", GLYPH_FAIL, "1 tracked file(s) one installation writes")
        ]

    def test_a_folder_that_is_no_repository_passes_with_nothing_tracked(self) -> None:
        rows = self._rows()

        assert rows["gitignore coverage"].detail == "not a git repository: nothing tracked"
        assert check_gitignore_coverage(self.root) == [
            ("gitignore coverage", GLYPH_PASS, "not a git repository: nothing tracked", "")
        ]


class TestDoctorSmoke:
    """aipass doctor --smoke through handle_command: hooks' smoke door is the edge, the groups answer nothing."""

    PAYLOAD = [
        {"provider": "claude", "status": "pass", "why": "ack read", "session_id": "s1", "elapsed_ms": 2400},
        {"provider": "codex", "status": "skip", "why": "not logged in", "session_id": "", "elapsed_ms": 0},
    ]

    @pytest.fixture(autouse=True)
    def _edges(self, monkeypatch) -> None:
        mod = "aipass.aipass.apps.modules.doctor"
        self.calls: list = []
        self.printed: dict = {}
        self.answer = MagicMock(returncode=0, stdout=json.dumps(self.PAYLOAD), stderr="")

        def _run(argv, **_kw):
            self.calls.append(argv)
            return self.answer

        def _record(groups):
            self.printed.update(groups)
            return 0, 0, sum(r.glyph == GLYPH_FAIL for rows in groups.values() for r in rows)

        monkeypatch.setattr("aipass.aipass.apps.modules._doctor_smoke.subprocess.run", _run)
        monkeypatch.setattr(f"{mod}._compute_doctor_groups", lambda **_kw: {"Services": []})
        monkeypatch.setattr(f"{mod}._print_doctor_groups", _record)

    def _smoke_rows(self) -> dict:
        return {r.label: r for r in self.printed["Services"] if r.label.startswith("smoke")}

    def test_the_default_run_never_calls_hooks_smoke(self) -> None:
        assert handle_command("doctor", []) is True

        assert self.calls == []
        assert self._smoke_rows() == {}

    def test_pass_and_skip_are_check_rows_with_the_time_and_the_reason(self) -> None:
        assert handle_command("doctor", ["--smoke"]) is True

        assert self.calls == [["drone", "@hooks", "smoke", "--json"]]
        rows = self._smoke_rows()
        assert (rows["smoke claude"].glyph, rows["smoke claude"].detail) == (GLYPH_PASS, "pass (2.4 s)")
        assert (rows["smoke codex"].glyph, rows["smoke codex"].detail) == (GLYPH_PASS, "skip (not logged in)")

    def test_a_fail_is_a_cross_row_with_hooks_why_and_exits_one(self) -> None:
        failed = {"provider": "opencode", "status": "fail", "why": "no hook nonce ack", "session_id": "s3"}
        self.answer = MagicMock(returncode=1, stdout=json.dumps([failed]), stderr="")

        with pytest.raises(SystemExit) as exit_info:
            handle_command("doctor", ["--smoke", "--model", "opencode=openai/gpt-6.1-sol"])

        assert exit_info.value.code == 1
        assert self.calls == [["drone", "@hooks", "smoke", "--json", "--model", "opencode=openai/gpt-6.1-sol"]]
        row = self._smoke_rows()["smoke opencode"]
        assert (row.glyph, row.detail) == (GLYPH_FAIL, "fail: no hook nonce ack")
        assert row.remediation == "Run: drone @hooks smoke --provider opencode"

    def test_unreadable_hooks_output_is_one_cross_row_not_a_pass(self) -> None:
        self.answer = MagicMock(returncode=2, stdout="Traceback", stderr="")

        with pytest.raises(SystemExit):
            handle_command("doctor", ["--smoke"])

        assert [(r.label, r.glyph, r.detail) for r in self._smoke_rows().values()] == [
            ("smoke", GLYPH_FAIL, "no result array (exit 2)")
        ]

    def test_json_prints_hooks_objects_as_given_and_runs_no_group(self, capsys) -> None:
        assert handle_command("doctor", ["--smoke", "--json"]) is True

        out, _err = capsys.readouterr()
        assert json.loads(out) == self.PAYLOAD
        assert self.printed == {}

    def test_json_exits_one_when_a_provider_fails(self) -> None:
        self.answer = MagicMock(returncode=1, stdout=json.dumps([{"provider": "codex", "status": "fail"}]), stderr="")

        with pytest.raises(SystemExit) as exit_info:
            handle_command("doctor", ["--smoke", "--json"])

        assert exit_info.value.code == 1

    def test_smoke_never_runs_with_fix(self, capsys) -> None:
        with pytest.raises(SystemExit):
            handle_command("doctor", ["--smoke", "--fix"])

        _out, err = capsys.readouterr()
        assert "never runs with --fix" in err
        assert self.calls == [] and self.printed == {}


class TestDoctorRowsJson:
    """aipass doctor --fix --rows-json PATH: the install's health check, its non-PASS rows and counts as JSON."""

    MOD = "aipass.aipass.apps.modules.doctor"

    def test_the_rows_file_holds_the_counts_and_each_non_pass_row_plain(self, tmp_path, monkeypatch) -> None:
        """Mutants: PASS rows kept; severity inverted; markup kept in detail -> each red."""
        groups = {
            "System": [CheckResult("python", GLYPH_PASS, "3.12", "")],
            "Services": [
                CheckResult("wire verify", GLYPH_FAIL, "[red]2 orphan entries[/red]", "drone @hooks verify"),
                CheckResult("hooks", GLYPH_WARN, "2 hook(s) missing", "aipass doctor --fix"),
            ],
        }
        monkeypatch.setattr(f"{self.MOD}.run_doctor_preflight", lambda **_kw: (groups, (1, 1, 1)))
        rows_file = tmp_path / "home" / ".aipass" / "install_doctor_rows.json"

        assert handle_command("doctor", ["--fix", "--rows-json", str(rows_file)]) is True

        assert json.loads(rows_file.read_text(encoding="utf-8")) == {
            "counts": {"pass": 1, "warn": 1, "error": 1},
            "rows": [
                {"group": "Services", "label": "wire verify", "severity": "error", "detail": "2 orphan entries",
                 "remediation": "drone @hooks verify"},
                {"group": "Services", "label": "hooks", "severity": "warning", "detail": "2 hook(s) missing",
                 "remediation": "aipass doctor --fix"},
            ],
        }  # fmt: skip

    def test_rows_json_without_fix_is_refused_with_2_and_writes_nothing(self, tmp_path, capsys) -> None:
        """Mutant: the --fix guard dropped -> the doctor runs and writes the file -> red."""
        rows_file = tmp_path / "rows.json"
        with patch(f"{self.MOD}.run_doctor_preflight") as preflight, pytest.raises(SystemExit) as exc:
            handle_command("doctor", ["--rows-json", str(rows_file)])

        assert exc.value.code == 2
        preflight.assert_not_called()
        assert not rows_file.exists()
        assert "run it with --fix" in capsys.readouterr().err

    @pytest.mark.parametrize("yes", [True, False])
    def test_yes_alone_reaches_the_rows_writer(self, yes, tmp_path, monkeypatch) -> None:
        """B07: --non-interactive is not this route's flag. Mutants: --yes not read; --non-interactive read -> red."""
        calls: list = []
        monkeypatch.setattr(f"{self.MOD}.write_preflight_rows", lambda *a, **kw: calls.append((a, kw)))
        rows_file = tmp_path / "rows.json"

        handle_command("doctor", ["--fix", "--rows-json", str(rows_file), "--non-interactive", *(["--yes"] * yes)])

        assert calls == [((rows_file,), {"yes": yes})]


_DOCTOR = "aipass.aipass.apps.modules.doctor"


class TestOneLinePerFact:
    """A damaged registry, hooks.json or trust list is one row naming the real fault; the report states its scope."""

    @staticmethod
    def _identity(tmp_path, registry_text: str, hooks_text: str | None = None) -> list:
        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text(registry_text, encoding="utf-8")
        if hooks_text is not None:
            (tmp_path / ".aipass").mkdir()
            (tmp_path / ".aipass" / "hooks.json").write_text(hooks_text, encoding="utf-8")
        with patch(f"{_DOCTOR}._find_registry", return_value=registry):
            return check_identity()

    @staticmethod
    def _rows(results, *labels) -> list:
        return [(r.label, r.glyph, r.detail, r.remediation) for r in results if r.label in labels]

    @pytest.mark.parametrize("text", ["", "[]", "{not json"])
    def test_an_unreadable_registry_is_one_fail_row_naming_doctor_fix(self, tmp_path, text) -> None:
        rows = self._rows(self._identity(tmp_path, text), "registry", "registry valid")
        assert [(label, glyph) for label, glyph, _d, _r in rows] == [("registry", GLYPH_FAIL)]
        assert rows[0][3] == "Run 'aipass doctor --fix'"

    def test_a_registry_without_branches_has_no_pass_row_beside_its_fail(self, tmp_path) -> None:
        rows = self._rows(self._identity(tmp_path, '{"metadata": {}}'), "registry", "registry valid")
        assert [(label, glyph, detail) for label, glyph, detail, _r in rows] == [
            ("registry", GLYPH_FAIL, "missing 'branches' key")
        ]

    def test_a_good_registry_is_one_row_with_no_validity_claim_beside_it(self, tmp_path) -> None:
        """A duplicate row is the owner checks' finding: no '✓ registry valid' contradicts it."""
        rows = self._rows(self._identity(tmp_path, '{"branches": [{"name": "A"}]}'), "registry", "registry valid")
        assert rows == [("registry", GLYPH_PASS, "1 branches", "")]

    @pytest.mark.parametrize("text", ["", "{torn"])
    def test_an_unreadable_hooks_json_is_a_fail_never_present(self, tmp_path, text) -> None:
        rows = self._rows(self._identity(tmp_path, '{"branches": []}', hooks_text=text), "hooks.json")
        assert len(rows) == 1
        assert rows[0][1] == GLYPH_FAIL
        assert rows[0][2].startswith("unreadable")

    def test_an_enrolled_project_whose_folder_is_gone_is_flagged_naming_prune(self, tmp_path, monkeypatch) -> None:
        gone = tmp_path / "deleted_project"
        enrolled = {"projects": {str(gone): {}, str(tmp_path): {}}}
        monkeypatch.setattr(f"{_DOCTOR}.read_trust_registry", lambda: enrolled)
        rows = self._rows(self._identity(tmp_path, '{"branches": []}'), "trust")
        assert rows == [("trust", GLYPH_WARN, f"enrolled project gone: {gone}", "Run 'aipass trust prune'")]

    def test_a_trust_list_of_live_projects_adds_no_row(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(f"{_DOCTOR}.read_trust_registry", lambda: {"projects": {str(tmp_path): {}}})
        assert self._rows(self._identity(tmp_path, '{"branches": []}'), "trust") == []

    def test_drone_failing_on_a_corrupt_registry_names_the_registry_not_the_install(self, tmp_path, monkeypatch):
        registry = tmp_path / "TEST_REGISTRY.json"
        registry.write_text("", encoding="utf-8")
        printed: dict = {}
        for name in ("_check_system", "check_identity", "_check_community", "_check_structure"):
            monkeypatch.setattr(f"{_DOCTOR}.{name}", lambda: [])
        for name in ("_check_scaffold", "check_wire_verify", "check_admin_lane"):
            monkeypatch.setattr(f"{_DOCTOR}.{name}", lambda: [])
        monkeypatch.setattr(f"{_DOCTOR}.check_provider_manifest", lambda **_kw: [])
        monkeypatch.setattr(f"{_DOCTOR}.reconcile_stale_deny", lambda **_kw: [])
        monkeypatch.setattr(f"{_DOCTOR}._find_registry", lambda: registry)
        monkeypatch.setattr(f"{_DOCTOR}.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        with patch(f"{_DOCTOR}._print_doctor_groups", side_effect=lambda g: printed.update(g) or (0, 0, 0)):
            run_doctor()
        drone = [(r.glyph, r.detail, r.remediation) for r in printed["Services"] if r.label == "drone"]
        assert drone == [(GLYPH_FAIL, f"exit non-zero: {registry.name} unreadable", "Run 'aipass doctor --fix'")]

    @pytest.mark.parametrize("root", [None, "project"])
    def test_the_report_states_its_scope_first(self, tmp_path, monkeypatch, capsys, root) -> None:
        """From outside a project the Structure checks do not run: a clean count must not read as a clean project."""
        project = tmp_path if root else None
        monkeypatch.setattr(f"{_DOCTOR}.find_project_root", lambda _cwd: project)
        monkeypatch.setattr(f"{_DOCTOR}._compute_doctor_groups", lambda **_kw: {})
        run_doctor()
        out = " ".join(capsys.readouterr().out.split())
        if root:
            assert f"scope: project {tmp_path}" in out
        else:
            assert f"scope: no project at {os.getcwd()}: the project's registry, mailbox, hooks" in out

    @pytest.mark.parametrize("root", [None, "project"])
    def test_outside_a_project_the_project_rows_do_not_count_and_inside_they_do(
        self, tmp_path, monkeypatch, capsys, root
    ) -> None:
        """A fresh install's first doctor from $HOME: no registry or ai_mail error, exit from machine rows only.

        Mutant: the outside-a-project filter dropped -> 2 errors outside -> red.
        """
        groups = {
            "System": [CheckResult("python", GLYPH_PASS, "3.12", "")],
            "Identity": [CheckResult("registry", GLYPH_FAIL, "not found", "Run 'aipass init'")],
            "Community": [CheckResult("ai_mail", GLYPH_FAIL, "not found", "Run 'aipass init'")],
            "Structure": [CheckResult("project root", GLYPH_WARN, "not detected", "")],
        }
        monkeypatch.setattr(f"{_DOCTOR}.find_project_root", lambda _cwd: tmp_path if root else None)
        monkeypatch.setattr(f"{_DOCTOR}._compute_doctor_groups", lambda **_kw: groups)

        errors = run_doctor()
        out = " ".join(capsys.readouterr().out.split())

        assert errors == (2 if root else 0)
        assert ("ai_mail" in out, "not detected" in out) == ((True, True) if root else (False, False))
