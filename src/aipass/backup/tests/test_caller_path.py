# =================== META ====================
# Name: test_caller_path.py
# Description: Tests for caller-CWD path resolution across user-facing commands
# Version: 1.0.4
# Created: 2026-08-08
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/path/caller.py and caller-CWD resolution."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/path/ and modules/share, register, status parse and import
# seedgo: no-test-needed(documentation) — that functions like resolve_caller_path, run_share carry docstrings
# seedgo: no-test-needed(stdlib) — Path.resolve() and pathlib behavior

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.backup.apps.handlers.drive import share as share_handler
from aipass.backup.apps.handlers.path.caller import caller_cwd, resolve_caller_path
from aipass.backup.apps.modules import register as register_mod
from aipass.backup.apps.modules import share as share_mod
from aipass.backup.apps.modules import status as status_mod
from aipass.backup.apps.modules.register import resolve_project


def _arguments(func, call) -> dict:
    """Bind a recorded call to func's signature, so an oracle reads a parameter by name."""
    return inspect.signature(func).bind(*call.args, **call.kwargs).arguments


class TestResolveCallerPath:
    """The shared helper — relative re-anchored, absolute untouched."""

    def test_relative_path_resolves_in_caller_dir_not_process_cwd(self, tmp_path: Path, monkeypatch) -> None:
        """A relative path lands in the caller's dir, not the process CWD."""
        caller = tmp_path / "some_project"
        caller.mkdir()
        process_cwd = tmp_path / "process_cwd"
        process_cwd.mkdir()
        monkeypatch.chdir(process_cwd)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        resolved = resolve_caller_path("docs/notes.md")

        assert resolved == (caller / "docs" / "notes.md").resolve()
        assert Path.cwd() not in resolved.parents

    def test_absolute_path_ignores_caller_dir(self, tmp_path: Path, monkeypatch) -> None:
        """Absolute input behaves exactly like Path(x).resolve() — caller dir ignored."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "elsewhere"))
        target = tmp_path / "abs" / "file.txt"

        assert resolve_caller_path(str(target)) == target.resolve()
        assert resolve_caller_path(target) == Path(target).resolve()

    def test_unset_caller_env_resolves_against_process_cwd(self, tmp_path: Path, monkeypatch) -> None:
        """Without the env var (direct invocation), process CWD is the caller."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

        assert resolve_caller_path("rel.txt") == (tmp_path / "rel.txt").resolve()

    def test_empty_caller_env_means_process_cwd_not_root(self, tmp_path: Path, monkeypatch) -> None:
        """An empty AIPASS_CALLER_CWD is treated as unset, not as '/'."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_CALLER_CWD", "")

        assert caller_cwd() == tmp_path.resolve()

    def test_caller_cwd_returns_the_exported_dir(self, tmp_path: Path, monkeypatch) -> None:
        """caller_cwd() returns exactly what drone exported."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        assert caller_cwd() == Path(str(tmp_path))


class TestShareUsesCallerCwd:
    """share — a relative file argument is uploaded from the caller's dir."""

    def _run(self, file_arg: str):
        """Run run_share with Drive fully mocked; return the local_file share_file saw."""
        client = MagicMock()
        client.authenticate.return_value = True
        share_file = MagicMock(return_value={"success": True, "link": "https://x", "file_id": "1", "error": None})

        with (
            patch("aipass.backup.apps.handlers.drive.client.DriveClient", return_value=client),
            patch("aipass.backup.apps.handlers.drive.share.share_file", share_file),
        ):
            share_mod.run_share(file_arg)

        return _arguments(share_handler.share_file, share_file.call_args)["local_file"]

    def test_share_relative_path_uploads_from_caller_dir_not_backup_dir(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """`share docs/x.md` once resolved into backup's own dir and failed "Not a file"."""
        caller = tmp_path / "project"
        (caller / "docs").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))
        expected = str((caller / "docs" / "file.md").resolve())

        seen = self._run("docs/file.md")

        out, err = capsys.readouterr()
        assert seen == expected
        assert f"Uploading {expected}..." in out
        assert "Shared (restricted): https://x" in out
        assert out.splitlines()[-1] == "https://x"
        assert err == ""

    def test_share_absolute_path_uploads_unchanged(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """Absolute input reaches the handler unchanged — no behaviour drift."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "irrelevant"))
        target = tmp_path / "real.md"

        seen = self._run(str(target))

        out, err = capsys.readouterr()
        assert seen == str(target.resolve())
        assert f"Uploading {target.resolve()}..." in out
        assert "Shared (restricted): https://x" in out
        assert err == ""


class TestRegisterUsesCallerCwd:
    """register — the silent failure: `register .` would register backup's own dir."""

    def test_relative_project_dir_resolves_in_caller_tree(self, tmp_path: Path, monkeypatch) -> None:
        """A relative dir resolves in the caller's tree."""
        caller = tmp_path / "workspace"
        (caller / "myproj").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        assert resolve_project("myproj") == str((caller / "myproj").resolve())

    def test_dot_means_caller_dir_not_backup_branch_dir(self, tmp_path: Path, monkeypatch) -> None:
        """`.` means the caller's directory — not backup's branch directory."""
        caller = tmp_path / "workspace"
        caller.mkdir()
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        assert resolve_project(".") == str(caller.resolve())

    def test_register_relative_path_scaffolds_and_hands_registry_the_caller_project_not_backup_dir(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """handle_command scaffolds .backup/ in the caller's project."""
        caller = tmp_path / "workspace"
        (caller / "myproj").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))
        expected = str((caller / "myproj").resolve())

        with patch.object(register_mod, "register_project", MagicMock()) as reg:
            register_mod.handle_command("register", ["myproj"])

        out, err = capsys.readouterr()
        assert _arguments(register_mod.register_project, reg.call_args)["path"] == expected
        assert (caller / "myproj" / ".backup").is_dir()
        assert "Registered: myproj" in out
        assert f"Path: {expected}" in out
        assert f"Backup dir: {Path(expected) / '.backup'}" in out
        assert err == ""

    def test_name_keys_the_registry_by_the_given_name_not_the_directory_name(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        """--name is the registry key and the line the user reads back; without it the dir name is."""
        # The registry key is the whole point of the flag: it is what `@shortname`
        # resolves against later. Both rows below register the SAME directory and
        # differ only by the flag, so a parse that drops --name collapses the
        # first row onto the second.
        caller = tmp_path / "workspace"
        (caller / "myproj").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        with patch.object(register_mod, "register_project", MagicMock()) as reg:
            assert register_mod.handle_command("register", ["myproj", "--name", "shortname"]) is True
            assert register_mod.handle_command("register", ["myproj"]) is True

        bound = [_arguments(register_mod.register_project, dispatched) for dispatched in reg.call_args_list]
        registered = [arguments["name"] for arguments in bound]
        paths = {arguments["path"] for arguments in bound}
        out, err = capsys.readouterr()
        assert registered == ["shortname", "myproj"], f"--name did not reach the registry: {registered!r}"
        assert paths == {str((caller / "myproj").resolve())}, f"--name moved the path too: {paths!r}"
        assert "Registered: shortname" in out
        assert "Registered: myproj" in out
        assert err == ""


class TestStatusUsesCallerCwd:
    """status — a relative path used to report on backup's own branch dir."""

    def test_status_relative_path_reports_on_caller_project_not_backup_dir(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """The status report is read from, and names, the caller's project."""
        caller = tmp_path / "workspace"
        (caller / "myproj" / ".backup").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))
        expected = str((caller / "myproj").resolve())

        status_mod.handle_command("status", ["myproj"])

        out, err = capsys.readouterr()
        assert "Backup Status: myproj" in out
        assert f"Path:         {expected}" in out
        assert "Run: backup register" not in out
        assert err == ""


# =============================================
