"""Tests for report_formatter — backup result formatting and display."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_result(
    *,
    files_checked: int = 10,
    files_copied: int = 5,
    files_added: int = 0,
    files_skipped: int = 3,
    files_deleted: int = 0,
    errors: int = 0,
    error_details: list[str] | None = None,
    warnings: list[str] | None = None,
    critical_errors: list[str] | None = None,
    mode: str = "snapshot",
) -> MagicMock:
    """Build a MagicMock that looks like a BackupResult."""
    result = MagicMock()
    result.files_checked = files_checked
    result.files_copied = files_copied
    result.files_added = files_added
    result.files_skipped = files_skipped
    result.files_deleted = files_deleted
    result.errors = errors
    result.error_details = error_details or []
    result.warnings = warnings or []
    result.critical_errors = critical_errors or []
    result.mode = mode
    result.start_time = datetime.datetime.now()
    return result


def _make_mode_config(name: str = "Snapshot") -> dict:
    return {"name": name}


def _noop_filter(skipped: dict) -> dict:
    return {"directories": [], "files": []}


class TestDisplayBackupResults:
    """display_backup_results logs results without raising."""

    def test_successful_backup_logs_ok(self):
        """Successful backup with no errors or warnings logs OK status."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        result = _make_result()
        mode_config = _make_mode_config()
        skipped: dict[str, list[str]] = {"directories": [], "files": []}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result, mode_config, Path("/tmp/backup"), skipped, _noop_filter
            )

        mock_jh.log_operation.assert_called_once_with("report_formatted")

    def test_critical_errors_show_failed_status(self):
        """Backup with critical errors triggers FAILED status path."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        result = _make_result(
            errors=1,
            critical_errors=["disk full"],
        )
        skipped: dict[str, list[str]] = {"directories": [], "files": []}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh, patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.logger"
        ) as mock_logger:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result, _make_mode_config(), Path("/tmp/b"), skipped, _noop_filter
            )

        # Should have logged at least one error call with the critical error text
        error_calls = [str(c) for c in mock_logger.error.call_args_list]
        assert any("disk full" in c for c in error_calls)

    def test_non_critical_errors_show_completed_with_errors(self):
        """Non-critical errors trigger COMPLETED WITH ERRORS path."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        result = _make_result(
            errors=2,
            error_details=["perm denied on a.txt", "perm denied on b.txt"],
        )
        skipped: dict[str, list[str]] = {"directories": [], "files": []}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh, patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.logger"
        ) as mock_logger:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result, _make_mode_config(), Path("/tmp/b"), skipped, _noop_filter
            )

        info_texts = [str(c) for c in mock_logger.info.call_args_list]
        assert any("COMPLETED WITH ERRORS" in t for t in info_texts)

    def test_warnings_path(self):
        """Warnings without errors trigger COMPLETED WITH WARNINGS."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        result = _make_result(warnings=["symlink skipped"])
        skipped: dict[str, list[str]] = {"directories": [], "files": []}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh, patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.logger"
        ) as mock_logger:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result, _make_mode_config(), Path("/tmp/b"), skipped, _noop_filter
            )

        info_texts = [str(c) for c in mock_logger.info.call_args_list]
        assert any("COMPLETED WITH WARNINGS" in t for t in info_texts)

    def test_dry_run_uses_would_language(self):
        """Dry-run mode uses 'Would copy' phrasing."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        result = _make_result()
        skipped: dict[str, list[str]] = {"directories": [], "files": []}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh, patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.logger"
        ) as mock_logger:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result,
                _make_mode_config(),
                Path("/tmp/b"),
                skipped,
                _noop_filter,
                dry_run=True,
            )

        info_texts = [str(c) for c in mock_logger.info.call_args_list]
        assert any("Would copy" in t for t in info_texts)

    def test_tracked_skipped_items_displayed(self):
        """When filter returns tracked items, they appear in the log."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        result = _make_result()
        skipped: dict[str, list[str]] = {
            "directories": [".git"],
            "files": ["secret.env"],
        }

        def filter_fn(items: dict) -> dict:
            return {"directories": [".git"], "files": ["secret.env"]}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh, patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.logger"
        ) as mock_logger:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result, _make_mode_config(), Path("/tmp/b"), skipped, filter_fn
            )

        info_texts = [str(c) for c in mock_logger.info.call_args_list]
        assert any("NOTABLE SKIPPED" in t for t in info_texts)

    def test_no_skipped_items_message(self):
        """When nothing is skipped, logs 'No items were skipped.'."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        result = _make_result()
        skipped: dict[str, list[str]] = {"directories": [], "files": []}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh, patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.logger"
        ) as mock_logger:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result, _make_mode_config(), Path("/tmp/b"), skipped, _noop_filter
            )

        info_texts = [str(c) for c in mock_logger.info.call_args_list]
        assert any("No items were skipped" in t for t in info_texts)

    def test_error_details_capped_at_ten(self):
        """Only first 10 error details are logged, rest summarised."""
        from aipass.backup.apps.handlers.reporting.report_formatter import (
            display_backup_results,
        )

        details = [f"error {i}" for i in range(15)]
        result = _make_result(errors=15, error_details=details)
        skipped: dict[str, list[str]] = {"directories": [], "files": []}

        with patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.json_handler"
        ) as mock_jh, patch(
            "aipass.backup.apps.handlers.reporting.report_formatter.logger"
        ) as mock_logger:
            mock_jh.log_operation = MagicMock()
            display_backup_results(
                result, _make_mode_config(), Path("/tmp/b"), skipped, _noop_filter
            )

        info_texts = [str(c) for c in mock_logger.info.call_args_list]
        assert any("5 more errors" in t for t in info_texts)
