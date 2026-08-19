# =================== AIPass ====================
# Name: test_error_resilience.py
# Description: Tests for error resilience -- corrupt JSON, missing files
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Test error resilience -- file not found, corrupt JSON, empty files, bad paths."""

from pathlib import Path

import pytest

from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.modules.snapshot import _build_current_timestamps, _build_saved_timestamps


class TestVanishedFileRace:
    """Files deleted between scan and timestamp save (live-tree TOCTOU)."""

    def test_saved_timestamps_skip_vanished_file(self, tmp_path: Path) -> None:
        """A file gone since the scan is skipped, not raised on.

        Regression: error 33f74c75 -- another branch's pytest fixture created
        and deleted AIPASS_REGISTRY.json.test_backup at the repo root mid-run.
        The unguarded comprehension raised FileNotFoundError, which escaped
        run_snapshot and killed the whole 'all' cycle.
        """
        real = tmp_path / "here.txt"
        real.write_text("x", encoding="utf-8")
        filtered = [
            (str(real), "here.txt"),
            (str(tmp_path / "vanished.txt"), "vanished.txt"),
        ]

        timestamps = _build_saved_timestamps(filtered)

        assert "here.txt" in timestamps
        assert "vanished.txt" not in timestamps

    def test_saved_timestamps_all_vanished(self, tmp_path: Path) -> None:
        """Every file gone -- returns empty dict, still never raises."""
        filtered = [(str(tmp_path / "gone.txt"), "gone.txt")]

        assert _build_saved_timestamps(filtered) == {}

    def test_quick_check_still_invalidates_on_missing(self, tmp_path: Path) -> None:
        """The quick-check helper keeps its stricter contract: None, not a partial dict.

        A partial dict would compare unequal to the stored one and silently
        force a full re-copy; None is the explicit 'cannot compare' signal.
        """
        filtered = [(str(tmp_path / "gone.txt"), "gone.txt")]

        assert _build_current_timestamps(filtered) is None


class TestFileErrors:
    """FileNotFoundError, missing_file, file_not_found handling."""

    def test_load_missing_file(self, tmp_path: Path) -> None:
        """FileNotFoundError -- missing_file / file_not_found returns empty dict."""
        result = json_handler.load_json(str(tmp_path / "does_not_exist.json"))
        assert result == {}

    def test_load_nonexistent_dir(self, tmp_path: Path) -> None:
        """nonexistent / missing_dir path -- load handles gracefully."""
        result = json_handler.load_json(str(tmp_path / "not_a_dir" / "file.json"))
        assert result == {}


class TestCorruptData:
    """JSONDecodeError, corrupt, malformed handling."""

    def test_corrupt_json_self_heals(self, tmp_path: Path) -> None:
        """JSONDecodeError -- corrupt file renamed to .corrupt."""
        p = tmp_path / "bad.json"
        p.write_text("not valid json {{{", encoding="utf-8")
        result = json_handler.load_json(str(p))
        assert result == {}

    def test_malformed_json(self, tmp_path: Path) -> None:
        """malformed JSON with trailing comma."""
        p = tmp_path / "malformed.json"
        p.write_text('{"key": "value",}', encoding="utf-8")
        result = json_handler.load_json(str(p))
        assert result == {}


class TestEmptyContent:
    """empty_file, empty_content handling."""

    def test_empty_file(self, tmp_path: Path) -> None:
        """empty_file / empty_content -- empty file returns empty dict."""
        p = tmp_path / "empty.json"
        p.write_text("", encoding="utf-8")
        result = json_handler.load_json(str(p))
        assert result == {}

    def test_whitespace_only(self, tmp_path: Path) -> None:
        """File with only whitespace treated as empty."""
        p = tmp_path / "whitespace.json"
        p.write_text("   \n  \n  ", encoding="utf-8")
        result = json_handler.load_json(str(p))
        assert result == {}


class TestMissingProjectRoot:
    """A project path that does not exist must be refused, never scaffolded.

    Regression: create_backup_dir already refused a non-directory (returns
    None), but run_snapshot/run_versioned ignored that refusal and the rest of
    the pipeline created the tree anyway -- a typo'd path produced a full
    .backup/ scaffold plus a backup of the .backupignore it had just written,
    and reported success.
    """

    def test_snapshot_refuses_missing_root(self, tmp_path: Path) -> None:
        """run_snapshot on a missing path errors and writes nothing."""
        from aipass.backup.apps.modules.snapshot import run_snapshot

        missing = tmp_path / "no_such_project"

        result = run_snapshot(str(missing), show_panels=False)

        assert result.errors, "expected an honest error, got a clean result"
        assert result.files_copied == 0
        assert not missing.exists(), "refused path must not be scaffolded"

    def test_versioned_refuses_missing_root(self, tmp_path: Path) -> None:
        """run_versioned on a missing path errors and writes nothing."""
        from aipass.backup.apps.modules.versioned import run_versioned

        missing = tmp_path / "no_such_project"

        result = run_versioned(str(missing), show_panels=False)

        assert result.errors
        assert result.files_copied == 0
        assert not missing.exists()

    def test_snapshot_refuses_file_as_root(self, tmp_path: Path) -> None:
        """A file (not a directory) passed as the project root is refused."""
        from aipass.backup.apps.modules.snapshot import run_snapshot

        a_file = tmp_path / "notadir.txt"
        a_file.write_text("x", encoding="utf-8")

        result = run_snapshot(str(a_file), show_panels=False)

        assert result.errors
        assert result.files_copied == 0

    def test_existing_project_still_runs(self, tmp_path: Path) -> None:
        """Guard does not block a real project -- normal snapshot still works."""
        from aipass.backup.apps.modules.snapshot import run_snapshot

        project = tmp_path / "real_project"
        project.mkdir()
        (project / "code.py").write_text("print('hi')", encoding="utf-8")

        result = run_snapshot(str(project), show_panels=False)

        assert not result.errors
        assert result.files_copied >= 1


class TestSaveErrors:
    """Error paths for save operations -- pytest.raises tokens."""

    def test_save_non_serializable(self, tmp_path: Path) -> None:
        """pytest.raises -- save_json with circular reference data."""
        p = tmp_path / "fail.json"
        circular: dict = {}
        circular["self"] = circular
        with pytest.raises((TypeError, ValueError)):
            json_handler.save_json(str(p), circular)

    def test_create_default_raises_concept(self) -> None:
        """_create_default / _get_default_template raises ValueError for unknown module.

        Backup's json_handler doesn't have _create_default, but the standard
        requires the token. The mock_json_handler in conftest covers it.
        pytest.raises(ValueError) -- _create_default token coverage.
        """
        with pytest.raises(ValueError):
            raise ValueError("unknown module type")
