"""Tests for BackupResult data model — state mutations and initialization contracts."""

import datetime
from unittest.mock import MagicMock, patch


class TestBackupResultInitContract:
    """BackupResult initializes with correct default state."""

    def test_all_counters_start_at_zero(self):
        """All file counters initialize to 0."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        assert result.files_checked == 0
        assert result.files_copied == 0
        assert result.files_added == 0
        assert result.files_skipped == 0
        assert result.files_deleted == 0
        assert result.errors == 0

    def test_lists_start_empty(self):
        """All list attributes initialize empty."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        assert result.error_details == []
        assert result.warnings == []
        assert result.critical_errors == []

    def test_success_starts_true(self):
        """success defaults to True."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        assert result.success is True

    def test_start_time_is_datetime(self):
        """start_time is a datetime instance."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        assert isinstance(result.start_time, datetime.datetime)

    def test_backup_path_starts_as_empty_string(self):
        """backup_path defaults to empty string."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        assert result.backup_path == ""
        assert isinstance(result.backup_path, str)

    def test_mode_starts_as_empty_string(self):
        """mode defaults to empty string."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        assert result.mode == ""
        assert isinstance(result.mode, str)


class TestBackupResultAddErrorContract:
    """add_error increments errors and tracks details."""

    def test_increments_error_count(self):
        """Each add_error call increments errors by 1."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_error("first error")
        assert result.errors == 1

        result.add_error("second error")
        assert result.errors == 2

    def test_appends_to_error_details(self):
        """Error message is appended to error_details list."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_error("test error message")

        assert len(result.error_details) == 1
        assert result.error_details[0] == "test error message"

    def test_non_critical_preserves_success(self):
        """Non-critical error does not change success to False."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_error("minor issue", is_critical=False)

        assert result.success is True
        assert result.critical_errors == []

    def test_critical_error_sets_success_false(self):
        """Critical error sets success to False."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_error("fatal problem", is_critical=True)

        assert result.success is False

    def test_critical_error_appends_to_critical_list(self):
        """Critical error message is appended to critical_errors list."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_error("fatal problem", is_critical=True)

        assert len(result.critical_errors) == 1
        assert result.critical_errors[0] == "fatal problem"

    def test_critical_also_in_error_details(self):
        """Critical errors also appear in the general error_details list."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_error("both lists", is_critical=True)

        assert "both lists" in result.error_details
        assert "both lists" in result.critical_errors


class TestBackupResultAddWarningContract:
    """add_warning appends to warnings list without affecting errors."""

    def test_appends_to_warnings(self):
        """Warning message is appended to warnings list."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_warning("potential issue")

        assert len(result.warnings) == 1
        assert result.warnings[0] == "potential issue"

    def test_does_not_increment_errors(self):
        """Warnings do not affect the errors counter."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_warning("just a warning")

        assert result.errors == 0

    def test_does_not_affect_success(self):
        """Warnings do not change the success flag."""
        from aipass.backup.apps.handlers.models import backup_models

        with patch.object(backup_models, "json_handler", MagicMock()):
            result = backup_models.BackupResult()

        result.add_warning("warning")

        assert result.success is True
