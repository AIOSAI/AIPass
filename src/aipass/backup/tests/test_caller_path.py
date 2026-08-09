# =================== AIPass ====================
# Name: test_caller_path.py
# Description: Tests for caller-CWD path resolution across user-facing commands
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-08-08
# =============================================

"""Tests for caller-CWD resolution.

Backup runs as an installed entry point, so ``Path.cwd()`` is backup's own
branch directory. Drone exports ``AIPASS_CALLER_CWD``; every user-supplied
relative path must resolve against that, not against the process CWD.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.backup.apps.handlers.path.caller import caller_cwd, resolve_caller_path


class TestResolveCallerPath:
    """The shared helper — relative re-anchored, absolute untouched."""

    def test_relative_resolves_against_caller_cwd(self, tmp_path: Path, monkeypatch) -> None:
        """A relative path lands in the caller's dir, not the process CWD.

        Regression: `drone @backup share docs.local/drafts/x.md` resolved to
        src/aipass/backup/docs.local/... and failed with "Not a file".
        """
        caller = tmp_path / "some_project"
        caller.mkdir()
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        resolved = resolve_caller_path("docs/notes.md")

        assert resolved == (caller / "docs" / "notes.md").resolve()
        assert Path.cwd() not in resolved.parents

    def test_absolute_path_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        """Absolute input behaves exactly like Path(x).resolve() — caller dir ignored."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "elsewhere"))
        target = tmp_path / "abs" / "file.txt"

        assert resolve_caller_path(str(target)) == target.resolve()
        assert resolve_caller_path(target) == Path(target).resolve()

    def test_falls_back_to_process_cwd(self, monkeypatch) -> None:
        """Without the env var (direct invocation), process CWD is the caller."""
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)

        assert resolve_caller_path("rel.txt") == (Path.cwd() / "rel.txt").resolve()

    def test_empty_env_var_falls_back(self, monkeypatch) -> None:
        """An empty AIPASS_CALLER_CWD is treated as unset, not as '/'."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", "")

        assert caller_cwd() == Path.cwd()

    def test_caller_cwd_reads_env(self, tmp_path: Path, monkeypatch) -> None:
        """caller_cwd() returns exactly what drone exported."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        assert caller_cwd() == Path(str(tmp_path))


class TestShareUsesCallerCwd:
    """share — the reported failure (VERA: relative path -> 'Not a file')."""

    def _run(self, file_arg: str, caller: Path):
        """Run run_share with Drive fully mocked; return the path share_file saw."""
        from aipass.backup.apps.modules import share as share_mod

        client = MagicMock()
        client.authenticate.return_value = True
        share_file = MagicMock(return_value={"success": True, "link": "https://x", "file_id": "1", "error": None})

        with (
            patch("aipass.backup.apps.handlers.drive.client.DriveClient", return_value=client),
            patch("aipass.backup.apps.handlers.drive.share.share_file", share_file),
        ):
            share_mod.run_share(file_arg)

        return share_file.call_args.args[1]

    def test_relative_path_passed_as_caller_absolute(self, tmp_path: Path, monkeypatch) -> None:
        """share_file receives the caller-anchored absolute path, not backup's."""
        caller = tmp_path / "project"
        (caller / "docs").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        seen = self._run("docs/file.md", caller)

        assert seen == str((caller / "docs" / "file.md").resolve())

    def test_absolute_path_passed_through(self, tmp_path: Path, monkeypatch) -> None:
        """Absolute input reaches the handler unchanged — no behaviour drift."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path / "irrelevant"))
        target = tmp_path / "real.md"
        target.write_text("x", encoding="utf-8")

        seen = self._run(str(target), tmp_path)

        assert seen == str(target.resolve())


class TestRegisterUsesCallerCwd:
    """register — the silent failure: `register .` would register backup's own dir."""

    def test_resolve_project_relative_dir(self, tmp_path: Path, monkeypatch) -> None:
        """A relative dir resolves in the caller's tree."""
        from aipass.backup.apps.modules.register import resolve_project

        caller = tmp_path / "workspace"
        (caller / "myproj").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        assert resolve_project("myproj") == str((caller / "myproj").resolve())

    def test_resolve_project_dot(self, tmp_path: Path, monkeypatch) -> None:
        """`.` means the caller's directory — not backup's branch directory."""
        from aipass.backup.apps.modules.register import resolve_project

        caller = tmp_path / "workspace"
        caller.mkdir()
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        assert resolve_project(".") == str(caller.resolve())

    def test_register_command_relative_path(self, tmp_path: Path, monkeypatch) -> None:
        """handle_command scaffolds .backup/ in the caller's project."""
        from aipass.backup.apps.modules import register as register_mod

        caller = tmp_path / "workspace"
        (caller / "myproj").mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        create_dir = MagicMock(return_value=str(caller / "myproj" / ".backup"))
        with (
            patch.object(register_mod, "create_backup_dir", create_dir),
            patch.object(register_mod, "register_project", MagicMock()) as reg,
        ):
            register_mod.handle_command("register", ["myproj"])

        assert reg.call_args.args[1] == str((caller / "myproj").resolve())


class TestStatusUsesCallerCwd:
    """status — a relative path used to report on backup's own branch dir."""

    def test_status_relative_path(self, tmp_path: Path, monkeypatch) -> None:
        """backup_root is asked about the caller's project."""
        from aipass.backup.apps.modules import status as status_mod

        caller = tmp_path / "workspace"
        caller.mkdir()
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller))

        missing = MagicMock()
        missing.exists.return_value = False
        with patch.object(status_mod, "backup_root", MagicMock(return_value=missing)) as root:
            status_mod.handle_command("status", ["myproj"])

        assert root.call_args.args[0] == str((caller / "myproj").resolve())


# =============================================
