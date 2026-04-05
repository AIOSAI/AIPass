"""Tests for system_utils — filesystem operations (ensure_backup_directory, remove_empty_dirs)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_prax(monkeypatch):
    """Inject mock prax logger before any system_utils import."""
    mock_logger = MagicMock()
    mock_prax_mod = MagicMock()
    mock_prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", mock_prax_mod)
    return mock_logger


@pytest.fixture(autouse=True)
def _mock_json_handler(monkeypatch):
    """Inject mock json_handler before any system_utils import."""
    mock_jh = MagicMock()
    mock_jh.log_operation = MagicMock(return_value=True)
    mock_json_init = MagicMock()
    mock_json_init.json_handler = mock_jh
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json", mock_json_init)
    monkeypatch.setitem(sys.modules, "aipass.backup.apps.handlers.json.json_handler", mock_jh)
    return mock_jh


@pytest.fixture(autouse=True)
def _clear_system_utils_module(monkeypatch):
    """Force re-import of system_utils each test to pick up fresh mocks."""
    keys_to_clear = [
        key for key in sys.modules
        if key.startswith("aipass.backup.apps.handlers.utils")
    ]
    for key in keys_to_clear:
        monkeypatch.delitem(sys.modules, key, raising=False)


# ─── ensure_backup_directory ────────────────────────────


class TestEnsureBackupDirectory:
    """Tests for ensure_backup_directory function."""

    def test_ensure_backup_directory_creates_dest(self, tmp_path):
        """is_dynamic=False creates only backup_dest, not backup_path."""
        from aipass.backup.apps.handlers.utils.system_utils import ensure_backup_directory

        backup_dest = tmp_path / "dest"
        backup_path = tmp_path / "dest" / "subdir"

        success, error = ensure_backup_directory(backup_dest, backup_path, is_dynamic=False)

        assert success is True
        assert error is None
        assert backup_dest.exists()
        # backup_path should NOT be created when is_dynamic=False
        assert not backup_path.exists()

    def test_ensure_backup_directory_dynamic_creates_both(self, tmp_path):
        """is_dynamic=True creates both backup_dest and backup_path."""
        from aipass.backup.apps.handlers.utils.system_utils import ensure_backup_directory

        backup_dest = tmp_path / "dest"
        backup_path = tmp_path / "dest" / "subdir"

        success, error = ensure_backup_directory(backup_dest, backup_path, is_dynamic=True)

        assert success is True
        assert error is None
        assert backup_dest.exists()
        assert backup_path.exists()

    def test_ensure_backup_directory_permission_error(self, tmp_path, monkeypatch):
        """PermissionError returns (False, error_message)."""
        from aipass.backup.apps.handlers.utils.system_utils import ensure_backup_directory

        backup_dest = tmp_path / "locked"
        backup_path = tmp_path / "locked" / "sub"

        # Patch _mkdir_writable to raise PermissionError
        monkeypatch.setattr(
            "aipass.backup.apps.handlers.utils.system_utils._mkdir_writable",
            MagicMock(side_effect=PermissionError("no access")),
        )

        success, error_msg = ensure_backup_directory(backup_dest, backup_path, is_dynamic=False)

        assert success is False
        assert isinstance(error_msg, str)
        assert "Permission denied" in error_msg
        assert "no access" in error_msg

    def test_ensure_backup_directory_os_error(self, tmp_path, monkeypatch):
        """OSError returns (False, error_message) with OS error details."""
        from aipass.backup.apps.handlers.utils.system_utils import ensure_backup_directory

        backup_dest = tmp_path / "broken"
        backup_path = tmp_path / "broken" / "sub"

        monkeypatch.setattr(
            "aipass.backup.apps.handlers.utils.system_utils._mkdir_writable",
            MagicMock(side_effect=OSError("disk full")),
        )

        success, error_msg = ensure_backup_directory(backup_dest, backup_path, is_dynamic=False)

        assert success is False
        assert isinstance(error_msg, str)
        assert "OS error" in error_msg
        assert "disk full" in error_msg


# ─── remove_empty_dirs ──────────────────────────────────


class TestRemoveEmptyDirs:
    """Tests for remove_empty_dirs function."""

    def test_remove_empty_dirs_removes_empty(self, tmp_path):
        """Nested empty directories are removed bottom-up."""
        from aipass.backup.apps.handlers.utils.system_utils import remove_empty_dirs

        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        remove_empty_dirs(tmp_path)

        assert not (tmp_path / "a").exists()

    def test_remove_empty_dirs_keeps_nonempty(self, tmp_path):
        """Directories containing files are preserved."""
        from aipass.backup.apps.handlers.utils.system_utils import remove_empty_dirs

        subdir = tmp_path / "keep_me"
        subdir.mkdir()
        (subdir / "data.txt").write_text("important", encoding="utf-8")

        empty_dir = tmp_path / "delete_me"
        empty_dir.mkdir()

        remove_empty_dirs(tmp_path)

        assert subdir.exists()
        assert (subdir / "data.txt").exists()
        assert not empty_dir.exists()

    def test_remove_empty_dirs_handles_error(self, tmp_path, monkeypatch, _mock_prax):
        """Exception during iterdir is caught and logged, no crash."""
        from aipass.backup.apps.handlers.utils.system_utils import remove_empty_dirs

        # Create a real directory so iterdir can be called
        subdir = tmp_path / "problem"
        subdir.mkdir()

        # Monkeypatch iterdir on the top-level path to raise
        original_iterdir = Path.iterdir

        def broken_iterdir(self):
            if self == tmp_path:
                raise RuntimeError("simulated I/O failure")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", broken_iterdir)

        # Should not raise
        remove_empty_dirs(tmp_path)

        # Logger warning was called with the error
        _mock_prax.warning.assert_called_once()
        call_args = _mock_prax.warning.call_args[0][0]
        assert "simulated I/O failure" in call_args
