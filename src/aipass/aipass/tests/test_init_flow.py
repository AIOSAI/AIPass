# =================== AIPass ====================
# Name: test_init_flow.py
# Description: Tests for aipass init — scaffold, update, agent routes
# Version: 2.2.1
# Created: 2026-04-16
# Modified: 2026-11-24
# =============================================

"""Tests for apps/modules/init_flow.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that init_flow.py parses and imports

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.handlers.init.bootstrap import init_project
from aipass.aipass.apps.modules.init_flow import (
    handle_command,
    print_help,
)

_MOD = "aipass.aipass.apps.modules.init_flow"


class TestPrintHelp:
    def test_calls_console_print(self, capsys: pytest.CaptureFixture[str]) -> None:
        """print_help outputs via console.print.

        Mutant: the "init update --dry-run" usage line renamed to --preview reddens this.
        """
        print_help()
        out, _err = capsys.readouterr()
        assert "aipass init update --dry-run" in out


class TestHandleCommand:
    def test_wrong_command_returns_false(self) -> None:
        """Non-init commands are not handled."""
        assert handle_command("doctor", []) is False
        assert handle_command("profile", ["set", "name", "X"]) is False

    def test_no_args_scaffolds_cwd(self) -> None:
        """'init' with no args scaffolds the current folder — the usage line's default."""
        with patch("aipass.aipass.apps.modules.init_flow._handle_init_scaffold", return_value=0) as mock_scaffold:
            with pytest.raises(SystemExit) as exc_info:
                handle_command("init", [])
        assert exc_info.value.code == 0
        mock_scaffold.assert_called_once_with([])

    def test_info_flag_calls_introspection(self) -> None:
        """--info flag calls print_introspection."""
        with patch("aipass.aipass.apps.modules.init_flow.print_introspection") as mock_intro:
            result = handle_command("init", ["--info"])
        assert result is True
        mock_intro.assert_called_once()

    def test_help_flag(self) -> None:
        """--help flag routes to print_help."""
        with patch("aipass.aipass.apps.modules.init_flow.print_help") as mock_help:
            result = handle_command("init", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    def test_h_flag(self) -> None:
        """-h routes to print_help."""
        with patch("aipass.aipass.apps.modules.init_flow.print_help") as mock_help:
            result = handle_command("init", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    def test_positional_args_treated_as_scaffold_target(self) -> None:
        """Positional args are treated as target path for scaffold."""
        with patch("aipass.aipass.apps.modules.init_flow._handle_init_scaffold", return_value=0) as mock_scaffold:
            with pytest.raises(SystemExit) as exc_info:
                handle_command("init", ["test-proj"])
        assert exc_info.value.code == 0
        mock_scaffold.assert_called_once_with(["test-proj"])

    def test_a_target_is_scaffolded_from_inside_an_agent_branch(self, tmp_path, monkeypatch) -> None:
        """The branch guard reads the target, so `init <target>` works from a citizen's seat."""
        seat = tmp_path / "seat"
        (seat / ".trinity").mkdir(parents=True)
        (seat / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        monkeypatch.chdir(seat)
        with patch("aipass.aipass.apps.modules.init_flow._handle_init_scaffold", return_value=0) as mock_scaffold:
            with pytest.raises(SystemExit) as exc_info:
                handle_command("init", [str(tmp_path / "proj")])
        assert exc_info.value.code == 0
        mock_scaffold.assert_called_once_with([str(tmp_path / "proj")])

    def test_a_flag_after_the_target_is_refused_and_nothing_is_scaffolded(self, tmp_path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            handle_command("init", [str(tmp_path / "demo"), "--dry-run"])

        assert exc_info.value.code == 1
        _out, err = capsys.readouterr()
        assert "takes no flags (got --dry-run)" in " ".join(err.split())
        assert not (tmp_path / "demo").exists()

    def test_retired_run_is_refused_and_nothing_is_scaffolded(self, tmp_path, monkeypatch, capsys) -> None:
        """`init run` names the retired guided setup; it must not scaffold a project called ./run.

        Mutant: the `args[0] == "run"` refusal removed -> exit 0 and ./run scaffolded -> red.
        """
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            handle_command("init", ["run"])

        assert exc_info.value.code == 1
        _out, err = capsys.readouterr()
        assert "'aipass init run' was retired" in " ".join(err.split())
        assert not (tmp_path / "run").exists()


_MOD_UPDATE = "aipass.aipass.apps.modules.init_flow"
# The owner check runs in install's _check_and_fix_owner, so its lines print through install's success.
_MOD_INSTALL = "aipass.aipass.apps.modules.install"


def _init_update(args: list[str]) -> int:
    """Run `aipass init update <args>` through the command and return its exit code.

    The command's router ends in sys.exit with the handler's answer, so the
    code a shell sees is read off the SystemExit, not the private handler.
    """
    with pytest.raises(SystemExit) as exit_info:
        handle_command("init", ["update", *args])
    code = exit_info.value.code
    assert isinstance(code, int)
    return code


class TestInitUpdateRegistrySync:
    """Tests for owner/identity check+fix in `aipass init update`.

    Git-auth provisioning is stubbed: it needs a real project on disk and has its own suite below.
    """

    def test_clean_check_prints_ok(self, tmp_path: Path) -> None:
        """Clean --check (exit 0) prints 'Owner/identity OK.' and skips --fix."""
        check_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch("subprocess.run", return_value=check_proc) as mock_run,
            patch(f"{_MOD_INSTALL}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "--check" in args
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)
        ok_calls = [c for c in mock_success.call_args_list if "Owner/identity OK" in str(c)]
        assert len(ok_calls) == 1

    def test_issues_trigger_fix(self, tmp_path: Path) -> None:
        """Non-zero --check triggers --fix; success prints reconciled."""
        check_proc = MagicMock(returncode=1, stdout="", stderr="")
        fix_proc = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(
                "subprocess.run",
                side_effect=[check_proc, fix_proc],
            ) as mock_run,
            patch(f"{_MOD_INSTALL}.success") as mock_success,
            patch(f"{_MOD_INSTALL}.warning"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0
        assert mock_run.call_count == 2
        fix_args = mock_run.call_args_list[1][0][0]
        assert "--fix" in fix_args
        reconciled = [c for c in mock_success.call_args_list if "reconciled" in str(c)]
        assert len(reconciled) == 1

    def test_fix_failure_degrades_silently(self, tmp_path: Path) -> None:
        """Non-zero --fix exit degrades gracefully (no crash)."""
        check_proc = MagicMock(returncode=1, stdout="", stderr="")
        fix_proc = MagicMock(returncode=1, stdout="", stderr="")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch(
                "subprocess.run",
                side_effect=[check_proc, fix_proc],
            ),
            patch(f"{_MOD_UPDATE}.warning"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0

    def test_sync_missing_drone_degrades_silently(self, tmp_path: Path) -> None:
        """FileNotFoundError (no drone binary) degrades gracefully."""
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch("subprocess.run", side_effect=FileNotFoundError("drone not found")),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0

    def test_sync_timeout_degrades_silently(self, tmp_path: Path) -> None:
        """subprocess.TimeoutExpired degrades gracefully."""
        import subprocess as _sp

        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch("subprocess.run", side_effect=_sp.TimeoutExpired(cmd="drone", timeout=30)),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])
        assert rc == 0


class TestInitUpdateGitAuth:
    """Tests for git-auth provisioning wired into `aipass init update`."""

    @staticmethod
    def _project(root: Path, citizen_class: str = "builder") -> None:
        """Write a minimal external project whose owner is one flip from git."""
        (root / "DEMO_REGISTRY.json").write_text(
            json.dumps(
                {
                    "metadata": {"id": "abc-123"},
                    "branches": [{"name": "VERA", "path": "src/demo/vera", "owner": True}],
                }
            ),
            encoding="utf-8",
        )
        passport = root / "src" / "demo" / "vera" / ".trinity" / "passport.json"
        passport.parent.mkdir(parents=True)
        passport.write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "VERA"},
                    "identity": {"citizen_class": citizen_class},
                    "citizenship": {"registry_id": "abc-123"},
                }
            ),
            encoding="utf-8",
        )

    def test_update_provisions_git_auth_after_sync(self, tmp_path: Path) -> None:
        """The class flip lands, and it runs AFTER sync-registry (which may migrate it)."""
        self._project(tmp_path)
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])

        assert rc == 0
        passport = json.loads(
            (tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json").read_text(encoding="utf-8")
        )
        assert passport["identity"]["citizen_class"] == "manager"
        assert any("Verified against all four" in str(c) for c in mock_success.call_args_list)

    def test_update_reports_honest_no_op(self, tmp_path: Path) -> None:
        """An already-provisioned owner is reported as nothing to repair, not as a repair."""
        self._project(tmp_path, citizen_class="manager")
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])

        assert rc == 0
        assert any("nothing to repair" in str(c) for c in mock_success.call_args_list)

    def test_refusal_exits_nonzero_and_names_the_fix(self, tmp_path: Path) -> None:
        """No citizen marked owner — update refuses instead of guessing one."""
        (tmp_path / "DEMO_REGISTRY.json").write_text(
            json.dumps({"metadata": {"id": "abc-123"}, "branches": [{"name": "VERA", "path": "src/demo/vera"}]}),
            encoding="utf-8",
        )
        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": []},
            ),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.success"),
            patch(f"{_MOD_UPDATE}.cli_error") as mock_error,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path)])

        assert rc == 1
        assert any('"owner": true' in str(c) for c in mock_error.call_args_list)

    def test_dry_run_plans_the_scaffold_and_writes_nothing(self, tmp_path: Path) -> None:
        """--dry-run touches nothing: the plan is computed with apply=False, no sync-registry.

        The pin is that update_project is CALLED and told not to write, not skipped.
        """
        self._project(tmp_path)
        passport_path = tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json"
        before = passport_path.read_text(encoding="utf-8")

        with (
            patch(
                "aipass.aipass.apps.handlers.init.bootstrap.update_project",
                return_value={"updated_files": [], "already_current": [], "pending": False},
            ) as mock_update,
            patch("subprocess.run") as mock_run,
            patch(f"{_MOD_UPDATE}.success") as mock_success,
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path), "--dry-run"])

        assert rc == 0
        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs["apply"] is False
        mock_run.assert_not_called()
        assert passport_path.read_text(encoding="utf-8") == before
        assert any("would repair" in str(c) for c in mock_success.call_args_list)

    def test_dry_run_exits_2_when_the_scaffold_is_behind(self, tmp_path: Path) -> None:
        """Exit 2 is the "there is a plan to read" signal; 0 means nothing to do.

        A manager (or a script) has to tell those apart without parsing output,
        so the code is the contract, not the text.
        """
        self._project(tmp_path)
        plan = {"updated_files": [], "already_current": [], "pending": True}

        with (
            patch("aipass.aipass.apps.handlers.init.bootstrap.update_project", return_value=plan),
            patch("subprocess.run") as mock_run,
            patch(f"{_MOD_UPDATE}.success"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(tmp_path), "--dry-run"])

        assert rc == 2
        mock_run.assert_not_called()

    @staticmethod
    def _stamp_behind_scaffold(root: Path) -> Path:
        """A real scaffold under tmp_path whose only drift is the version stamp.

        Built by the real init, never copied from a live project, so the door
        is exercised end to end — the plan is computed by the real handler.
        """
        target = root / "proj"
        target.mkdir()
        init_project(target, project_name="stamp")
        manifest_path = target / ".aipass" / "scaffold_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["aipass_version"] = "0.0.1"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return target

    @staticmethod
    def _squashed(text: str) -> str:
        """The channel with every whitespace run removed: Rich folds long paths at the width."""
        return "".join(text.split())

    def test_stamp_only_dry_run_says_no_go_is_needed_and_still_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The preview names the apply as the next move, not a request.

        Exit stays 2: the stamp IS pending, and 2 keeps meaning "there is a plan".
        Mutant: "so no go is needed" cut to "so no go" reddens this.
        """
        target = self._stamp_behind_scaffold(tmp_path)
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run"])

        assert rc == 2
        out, _err = capsys.readouterr()
        printed = self._squashed(out)
        assert self._squashed("Stamp only: no file would change, so no go is needed") in printed
        assert self._squashed(f"Run: aipass init update {target}") in printed
        assert self._squashed("Apply needs the owner's or devpulse's go") not in printed

    def test_a_dry_run_prints_each_gitignore_line_the_merge_would_add_brackets_and_all(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "proj"
        target.mkdir()
        init_project(target, project_name="lines")
        (target / ".gitignore").write_text("logs/\n", encoding="utf-8")
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run"])

        assert rc == 2
        out, _err = capsys.readouterr()
        assert "+ .chroma/" in out
        assert "+ *.py[cod]" in out
        assert "+ logs/" not in out
        assert (target / ".gitignore").read_text(encoding="utf-8") == "logs/\n"

    def test_a_plan_that_writes_a_file_still_asks_for_the_go(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """One file write in the plan and the preview still asks for the go.

        Mutant: "devpulse's go" cut to "devpulse" in the preview line reddens this.
        """
        target = self._stamp_behind_scaffold(tmp_path)
        (target / ".agents" / "skills" / "prep" / "SKILL.md").write_text("# mine\n", encoding="utf-8")
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run"])

        assert rc == 2
        out, _err = capsys.readouterr()
        printed = self._squashed(out)
        assert self._squashed("Apply needs the owner's or devpulse's go") in printed
        assert self._squashed("no go is needed") not in printed

    def test_json_carries_stamp_only_for_a_managers_agent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A manager's agent reads the key, never the prose.

        Mutant: the plan's "stamp_only" key renamed reddens this.
        """
        target = self._stamp_behind_scaffold(tmp_path)
        capsys.readouterr()
        with patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0):
            rc = _init_update([str(target), "--dry-run", "--json"])

        assert rc == 2
        out, _err = capsys.readouterr()
        emitted = json.loads(out)
        assert emitted["stamp_only"] is True
        assert emitted["pending"] is True

    def test_applying_stamp_only_prints_the_stamp_as_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The receipt reports what happened: after apply the stamp is written,
        not pending — the one word that would have been a lie in the receipt.
        Mutant: `state = "pending"` on both branches reddens this."""
        target = self._stamp_behind_scaffold(tmp_path)
        capsys.readouterr()
        with (
            patch(f"{_MOD_UPDATE}._run_git_auth_provisioning", return_value=0),
            patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
            patch(f"{_MOD_UPDATE}.success"),
            patch(f"{_MOD_UPDATE}.json_handler", autospec=True),
        ):
            rc = _init_update([str(target)])

        assert rc == 0
        out, _err = capsys.readouterr()
        stamp_lines = [line for line in out.splitlines() if line.strip().startswith("stamp ")]
        assert len(stamp_lines) == 1
        assert stamp_lines[0].rstrip().endswith("written")
        assert "0.0.1 →" in stamp_lines[0]

    def test_json_flag_emits_the_plan_as_parseable_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--json prints the plan document itself, not a rendered table.

        Stdout is exactly ONE JSON document with git-auth provisioning really running:
        its prose goes to stderr, so a manager's agent parsing stdout never meets it.
        Mutant: console.print_json swapped for console.print reddens this.
        Mutant: the --json redirect aimed at sys.stdout instead of sys.stderr reddens this.
        Mutant: the redirect removed -> red at the raw-text assert, before json.loads.
        """
        self._project(tmp_path)
        plan = {
            "project_name": "DEMO",
            "pending": True,
            "files": [{"path": ".aipass/tier0_kernel.md", "action": "update", "reason": "unmodified"}],
            "handlers": [{"name": "testwrite_gate", "action": "add"}],
        }

        with (
            patch("aipass.aipass.apps.handlers.init.bootstrap.update_project", return_value=plan),
            patch("subprocess.run") as mock_run,
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("init", ["update", str(tmp_path), "--dry-run", "--json"])

        assert exit_info.value.code == 2
        mock_run.assert_not_called()
        out, err = capsys.readouterr()
        # On the raw text first, so a plan printed to stdout dies at an assert, not in json.loads.
        assert "Git authorization (owner-tier)" not in out
        emitted = json.loads(out)
        assert emitted["files"][0]["action"] == "update"
        assert emitted["handlers"][0]["name"] == "testwrite_gate"
        assert "Git authorization (owner-tier)" in err
        assert "would repair" in err

    def test_json_alone_refuses_and_writes_nothing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A seat read the help's 'the same plan, machine-readable' as a preview and --json applied the update.

        Mutant: the refusal removed -> update_project runs with apply=True, red at assert_not_called.
        """
        self._project(tmp_path)
        with (
            patch("aipass.aipass.apps.handlers.init.bootstrap.update_project") as update,
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("init", ["update", str(tmp_path), "--json"])

        assert exit_info.value.code == 1
        update.assert_not_called()
        out, err = capsys.readouterr()
        assert "aipass init update --dry-run --json" in " ".join(f"{out} {err}".split())

    def test_an_unknown_flag_is_refused_with_help_and_nothing_runs(self, tmp_path: Path, capsys) -> None:
        """X15: update ran with an unknown flag silently dropped."""
        with (
            patch("aipass.aipass.apps.handlers.init.bootstrap.update_project") as update,
            pytest.raises(SystemExit) as exit_info,
        ):
            handle_command("init", ["update", str(tmp_path), "--dryrun"])

        assert exit_info.value.code == 1
        update.assert_not_called()
        out, err = capsys.readouterr()
        assert "--dryrun" in f"{out}{err}" and "USAGE:" in out

    def test_agent_without_a_src_package_says_which_path_it_falls_back_to(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """A50: the fallback to src/<name> was silent."""
        monkeypatch.chdir(tmp_path)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as run, pytest.raises(SystemExit):
            handle_command("init", ["agent", "scout"])

        assert run.call_args[0][0] == ["drone", "@spawn", "create", "src/scout"]
        assert "No src package found, using src/scout" in " ".join(capsys.readouterr().out.split())

    def test_help_offers_json_only_with_dry_run(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_help()
        lines = [" ".join(line.split()) for line in capsys.readouterr().out.splitlines() if "--json" in line]
        assert lines == [lines[0]] and lines[0].startswith("aipass init update --dry-run --json")
        assert "write nothing" in lines[0]
