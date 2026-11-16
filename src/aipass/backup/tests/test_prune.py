# =================== AIPass ====================
# Name: test_prune.py
# Description: Tests for apps/modules/prune.py and the cleanup/prune handler it drives
# Version: 1.2.0
# Created: 2026-10-16
# Modified: 2026-11-15
# =============================================

"""Tests for apps/modules/prune.py and the cleanup/prune handler it drives."""

# A new file for a new verb (DPLAN-0411 item 8); the gate is open for new test files
# on this build. The snapshot store is built by the real snapshot engine on a tmp_path
# project, so the layout under test is the one the product writes. A retired-lane
# .backup/versioned/ tree is built by hand beside it: prune must never touch it.
#
# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(os_walk_onerror) — _raise_walk_error, the walk's hook for a store directory it cannot list

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.modules import prune
from aipass.backup.apps.modules.snapshot import run_snapshot

#: A file name over 50 characters.
LONG_NAME = "L" * 60 + ".txt"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _files(root: Path) -> set[str]:
    """Every file under root, as posix paths relative to it."""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def backed_up(tmp_path: Path) -> Path:
    """A project with a snapshot store and an old versioned tree, then rules that match part of both."""
    root = tmp_path / "proj"
    _write(root / ".backupignore", ".backup/\n")
    _write(root / "src" / "main.py", "print(1)\n")
    _write(root / "app" / "keep.txt", "keep\n")
    _write(root / "app" / "target" / "debug" / "x.bin", "bb\n")
    _write(root / "app" / "target" / LONG_NAME, "long\n")
    _write(root / "notes.log", "one\n")
    run_snapshot(str(root), show_panels=False)
    # Data left by the retired versioned lane, matched by the new rules: prune leaves it all.
    _write(root / ".backup" / "versioned" / "root" / "notes.log" / "notes.log", "one\n")
    _write(root / ".backup" / "versioned" / "root" / "notes.log" / "notes.log_diffs" / "a.diff", "+two\n")
    _write(root / ".backup" / "versioned" / "app" / "target" / "debug" / "x.bin" / "x.bin", "bb\n")
    _write(root / ".backupignore", ".backup/\napp/target/\n*.log\n")
    return root


class TestPruneDryRun:
    """prune <root> lists what the ignore spec now matches and deletes nothing."""

    def test_a_dry_run_lists_each_store_by_top_level_directory_and_deletes_nothing(
        self, backed_up: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store = backed_up / ".backup"
        before = _files(store)

        assert prune.handle_command("prune", [str(backed_up)]) is True

        out, err = capsys.readouterr()
        lines = out.strip().splitlines()
        assert err == ""
        assert _files(store) == before
        assert lines[-1].startswith("Dry run -- nothing deleted.")
        assert "snapshots/  3 files" in out
        assert "versioned" not in out
        assert any(line.split()[:3] == ["app", "2", "files"] for line in lines)
        assert any(line.split()[:4] == ["(root", "files)", "1", "files"] for line in lines)
        assert "Total: 3 stored paths" in out

    def test_a_whitelisted_path_is_never_listed(self, backed_up: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config_path = backed_up / ".backup" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["whitelist"] = ["*.log"]
        config_path.write_text(json.dumps(config), encoding="utf-8")

        prune.handle_command("prune", [str(backed_up)])

        out, _err = capsys.readouterr()
        assert "(root" not in out
        assert "Total: 2 stored paths" in out


class TestPruneApply:
    """prune <root> --apply removes exactly what the dry run listed."""

    def test_apply_removes_the_matched_copies_and_keeps_every_other_stored_file(
        self, backed_up: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store = backed_up / ".backup"
        versioned_before = _files(store / "versioned")

        assert prune.handle_command("prune", [str(backed_up), "--apply"]) is True

        out, err = capsys.readouterr()
        assert err == ""
        assert out.strip().splitlines()[-1].startswith("Removed 3 stored paths")
        assert {p for p in _files(store / "snapshots")} == {".backupignore", "app/keep.txt", "src/main.py"}
        assert not (store / "snapshots" / "app" / "target").exists()
        # The old version store is never prune's: every file in it survives, matched or not.
        assert _files(store / "versioned") == versioned_before

    def test_apply_writes_one_trail_row_per_removed_path(
        self, backed_up: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        prune.handle_command("prune", [str(backed_up), "--apply"])
        capsys.readouterr()

        rows = [json.loads(line) for line in trail.log_path().read_text(encoding="utf-8").splitlines()]
        removed = sorted((row["lane"], row["rel_path"]) for row in rows if row["operation"] == "prune_removed")
        assert removed == [
            ("snapshots", "app/target/" + LONG_NAME),
            ("snapshots", "app/target/debug/x.bin"),
            ("snapshots", "notes.log"),
        ]


class TestPruneRefusals:
    """What prune refuses, and that a refusal deletes nothing."""

    def test_an_absent_root_exits_non_zero_with_the_reason_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "gone"

        with patch("sys.argv", ["backup", "prune", str(missing)]):
            code = entry.main()

        out, err = capsys.readouterr()
        assert code != 0
        assert out == ""
        assert "Project path is not a directory" in err
        assert missing.name in err

    def test_a_trailing_help_beside_apply_prints_the_usage_and_deletes_nothing(
        self, backed_up: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _files(backed_up / ".backup")

        assert prune.handle_command("prune", [str(backed_up), "--apply", "--help"]) is True

        out, err = capsys.readouterr()
        assert "Usage: prune <project_root|@name> [--apply]" in out
        assert err == ""
        assert _files(backed_up / ".backup") == before

    def test_an_unknown_flag_beside_apply_is_refused_and_deletes_nothing(
        self, backed_up: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _files(backed_up / ".backup")

        assert prune.handle_command("prune", [str(backed_up), "--apply", "--aply"]) is True

        _out, err = capsys.readouterr()
        assert "prune takes one project and --apply" in err
        assert _files(backed_up / ".backup") == before

    def test_apply_from_a_citizen_neither_backup_nor_admin_is_refused_and_deletes_nothing(
        self, backed_up: Path, verified_seat, capsys: pytest.CaptureFixture[str]
    ) -> None:
        verified_seat.caller, verified_seat.admin = "@grow", False
        before = _files(backed_up / ".backup")

        assert prune.handle_command("prune", [str(backed_up), "--apply"]) is True

        out, err = capsys.readouterr()
        assert "Prune refused:" in err and "not @grow" in " ".join(err.split())
        assert out == ""
        assert _files(backed_up / ".backup") == before
        rows = [json.loads(line) for line in trail.log_path().read_text(encoding="utf-8").splitlines()]
        assert [(r["caller"], bool(r["refused"])) for r in rows if r["operation"] == "prune_fence"] == [("@grow", True)]

    def test_apply_from_backups_own_seat_removes_the_matched_copies(
        self, backed_up: Path, verified_seat, capsys: pytest.CaptureFixture[str]
    ) -> None:
        verified_seat.caller, verified_seat.admin = "@backup", False

        prune.handle_command("prune", [str(backed_up), "--apply"])

        out, err = capsys.readouterr()
        assert err == ""
        assert out.strip().splitlines()[-1].startswith("Removed 3 stored paths")

    def test_a_dry_run_from_any_citizen_still_lists(
        self, backed_up: Path, verified_seat, capsys: pytest.CaptureFixture[str]
    ) -> None:
        verified_seat.caller, verified_seat.admin = "@grow", False

        prune.handle_command("prune", [str(backed_up)])

        out, err = capsys.readouterr()
        assert err == ""
        assert "Dry run -- nothing deleted." in out

    def test_a_root_with_no_store_says_there_is_nothing_to_prune(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "bare"
        root.mkdir()

        assert prune.handle_command("prune", [str(root)]) is True

        out, err = capsys.readouterr()
        assert "nothing to prune" in out
        assert err == ""
        assert not (root / ".backup").exists()


# =============================================
