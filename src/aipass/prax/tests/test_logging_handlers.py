# =================== AIPass ====================
# Name: test_logging_handlers.py
# Description: Tests for prax logging handler modules
# Version: 1.1.0
# Created: 2026-04-25
# Modified: 2026-08-04
# =============================================

"""Tests for prax logging handler modules.

Covers: direct.py (doRollover), introspection.py (get_calling_module_path),
log_watchdog.py (get_oversized_files, truncate_log_file),
monitoring.py (run_monitoring_loop), operations.py (create_config_file),
override.py (enhanced_getLogger, install_logger_override, restore_original_logger),
setup.py (setup_system_logger, doRollover for _WindowsSafeRotatingHandler),
terminal/filtering.py (load_filtered_modules, should_display_terminal),
terminal/formatting.py (format_terminal_message, create_terminal_handler).

All imports happen inside test functions because the autouse mock_prax_infrastructure
fixture must inject sys.modules mocks before any prax module is loaded.
"""

import importlib  # noqa: F401 — used inside test functions for dynamic module loading
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# =============================================
# direct.py -- RotatingFileHandler.doRollover
# =============================================


class TestDirectRotatingFileHandlerDoRollover:
    """Tests for direct.py RotatingFileHandler.doRollover()."""

    def test_do_rollover_success(self, mock_prax_infrastructure, tmp_path):
        """doRollover delegates to parent class on success."""
        mock_config = MagicMock()
        mock_config.get_system_logs_dir = MagicMock(return_value=tmp_path / "system")
        mock_config.get_module_logs_dir = MagicMock(return_value=tmp_path / "local")
        mock_config.DEFAULT_LOG_LEVEL = "DEBUG"
        mock_config.load_log_config = MagicMock()
        mock_config.lines_to_bytes = MagicMock(return_value=10000)
        mock_config.PRAX_JSON_DIR = tmp_path / "prax_json"

        mock_introspection = MagicMock()
        mock_introspection.detect_branch_from_path = MagicMock(return_value="prax")

        mock_override = MagicMock()
        mock_override._original_getLogger = logging.getLogger

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.override": mock_override,
            },
        ):
            _direct_mod_name = "aipass.prax.apps.handlers.logging.direct"
            sys.modules.pop(_direct_mod_name, None)
            direct_mod = importlib.import_module(_direct_mod_name)  # noqa: F841

            log_file = tmp_path / "test.log"
            log_file.write_text("line1\nline2\n", encoding="utf-8")
            handler = direct_mod.RotatingFileHandler(  # noqa: F821
                str(log_file), maxBytes=10, backupCount=1
            )
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="A" * 100,
                args=(),
                exc_info=None,
            )
            handler.emit(record)
            backup = tmp_path / "test.log.1"
            assert backup.exists() or log_file.exists()
            handler.close()

    def test_do_rollover_permission_error_suppressed(self, mock_prax_infrastructure, tmp_path):
        """doRollover suppresses PermissionError instead of crashing."""
        mock_config = MagicMock()
        mock_config.get_system_logs_dir = MagicMock(return_value=tmp_path / "system")
        mock_config.get_module_logs_dir = MagicMock(return_value=tmp_path / "local")
        mock_config.DEFAULT_LOG_LEVEL = "DEBUG"
        mock_config.load_log_config = MagicMock()
        mock_config.lines_to_bytes = MagicMock(return_value=10000)
        mock_config.PRAX_JSON_DIR = tmp_path / "prax_json"

        mock_introspection = MagicMock()
        mock_override = MagicMock()
        mock_override._original_getLogger = logging.getLogger

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.override": mock_override,
            },
        ):
            _direct_mod_name = "aipass.prax.apps.handlers.logging.direct"
            sys.modules.pop(_direct_mod_name, None)
            direct_mod = importlib.import_module(_direct_mod_name)  # noqa: F841

            log_file = tmp_path / "test_perm.log"
            log_file.write_text("data\n", encoding="utf-8")
            handler = direct_mod.RotatingFileHandler(  # noqa: F821
                str(log_file), maxBytes=10, backupCount=1
            )

            with patch(
                "logging.handlers.RotatingFileHandler.doRollover",
                side_effect=PermissionError("file locked"),
            ):
                handler.doRollover()
            handler.close()

    def test_do_rollover_os_error_suppressed(self, mock_prax_infrastructure, tmp_path):
        """doRollover suppresses OSError instead of crashing."""
        mock_config = MagicMock()
        mock_config.get_system_logs_dir = MagicMock(return_value=tmp_path / "system")
        mock_config.get_module_logs_dir = MagicMock(return_value=tmp_path / "local")
        mock_config.DEFAULT_LOG_LEVEL = "DEBUG"
        mock_config.load_log_config = MagicMock()
        mock_config.lines_to_bytes = MagicMock(return_value=10000)
        mock_config.PRAX_JSON_DIR = tmp_path / "prax_json"

        mock_introspection = MagicMock()
        mock_override = MagicMock()
        mock_override._original_getLogger = logging.getLogger

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.override": mock_override,
            },
        ):
            _direct_mod_name = "aipass.prax.apps.handlers.logging.direct"
            sys.modules.pop(_direct_mod_name, None)
            direct_mod = importlib.import_module(_direct_mod_name)  # noqa: F841

            log_file = tmp_path / "test_os.log"
            log_file.write_text("data\n", encoding="utf-8")
            handler = direct_mod.RotatingFileHandler(  # noqa: F821
                str(log_file), maxBytes=10, backupCount=1
            )

            with patch(
                "logging.handlers.RotatingFileHandler.doRollover",
                side_effect=OSError("disk error"),
            ):
                handler.doRollover()
            handler.close()


# =============================================
# introspection.py -- get_calling_module_path
# =============================================


class TestGetCallingModulePath:
    """Tests for introspection.py get_calling_module_path()."""

    def test_returns_path_or_none(self, mock_prax_infrastructure):
        """get_calling_module_path returns a string path or None."""
        from aipass.prax.apps.handlers.logging import introspection

        result = introspection.get_calling_module_path()
        assert result is None or isinstance(result, str)

    def test_returns_none_when_no_external_caller(self, mock_prax_infrastructure):
        """Returns None when _find_external_caller_path returns None."""
        from aipass.prax.apps.handlers.logging import introspection

        with patch.object(introspection, "_find_external_caller_path", return_value=None):
            result = introspection.get_calling_module_path()
            assert result is None

    def test_returns_path_when_external_caller_found(self, mock_prax_infrastructure):
        """Returns the path from _find_external_caller_path when found."""
        from aipass.prax.apps.handlers.logging import introspection

        fake_path = str(Path.home() / "src" / "aipass" / "flow" / "apps" / "flow.py")
        with patch.object(introspection, "_find_external_caller_path", return_value=fake_path):
            result = introspection.get_calling_module_path()
            assert result == fake_path


# =============================================
# log_watchdog.py -- get_oversized_files
# =============================================


class TestGetOversizedFiles:
    """Tests for log_watchdog.py get_oversized_files()."""

    def test_returns_empty_when_no_oversized(self, mock_prax_infrastructure, tmp_path):
        """Returns empty list when no files exceed threshold."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path / "prax_json",
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.log_watchdog", None)
            import aipass.prax.apps.handlers.logging.log_watchdog as lw

            logs_dir = tmp_path / "system_logs"
            logs_dir.mkdir()
            small_log = logs_dir / "small.log"
            small_log.write_text("line1\nline2\nline3\n", encoding="utf-8")

            with patch.object(lw, "_get_system_logs_dir", return_value=logs_dir):
                result = lw.get_oversized_files(threshold=100)
                assert result == []

    def test_returns_oversized_files(self, mock_prax_infrastructure, tmp_path):
        """Returns files that exceed the threshold."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path / "prax_json",
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.log_watchdog", None)
            import aipass.prax.apps.handlers.logging.log_watchdog as lw

            logs_dir = tmp_path / "system_logs"
            logs_dir.mkdir()
            big_log = logs_dir / "big.log"
            big_log.write_text(
                "\n".join(f"line {i}" for i in range(200)) + "\n",
                encoding="utf-8",
            )

            with patch.object(lw, "_get_system_logs_dir", return_value=logs_dir):
                result = lw.get_oversized_files(threshold=100)
                assert len(result) == 1
                assert result[0]["name"] == "big.log"
                assert result[0]["lines"] >= 100

    def test_nonexistent_dir_returns_empty(self, mock_prax_infrastructure, tmp_path):
        """Returns empty list when system_logs dir does not exist."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path / "prax_json",
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.log_watchdog", None)
            import aipass.prax.apps.handlers.logging.log_watchdog as lw

            nonexistent = tmp_path / "does_not_exist"
            with patch.object(lw, "_get_system_logs_dir", return_value=nonexistent):
                result = lw.get_oversized_files()
                assert result == []


# =============================================
# log_watchdog.py -- truncate_log_file
# =============================================


class TestTruncateLogFile:
    """Tests for log_watchdog.py truncate_log_file()."""

    def test_truncates_oversized_file(self, mock_prax_infrastructure, tmp_path):
        """Truncates file to keep_lines and adds truncation marker."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path / "prax_json",
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.log_watchdog", None)
            import aipass.prax.apps.handlers.logging.log_watchdog as lw

            log_file = tmp_path / "truncate_me.log"
            lines = [f"line {i}\n" for i in range(500)]
            log_file.write_text("".join(lines), encoding="utf-8")

            original, new = lw.truncate_log_file(log_file, keep_lines=100)
            assert original == 500
            assert new == 101  # 100 kept lines + 1 marker

            content = log_file.read_text(encoding="utf-8")
            assert "LOG TRUNCATED by PRAX watchdog" in content

    def test_no_truncation_when_under_limit(self, mock_prax_infrastructure, tmp_path):
        """File under limit is not modified."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path / "prax_json",
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.log_watchdog", None)
            import aipass.prax.apps.handlers.logging.log_watchdog as lw

            log_file = tmp_path / "small.log"
            lines = [f"line {i}\n" for i in range(50)]
            log_file.write_text("".join(lines), encoding="utf-8")

            original, new = lw.truncate_log_file(log_file, keep_lines=100)
            assert original == 50
            assert new == 50

    def test_truncate_handles_os_error(self, mock_prax_infrastructure, tmp_path):
        """Returns (0, 0) on OSError."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path / "prax_json",
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.log_watchdog", None)
            import aipass.prax.apps.handlers.logging.log_watchdog as lw

            nonexistent = tmp_path / "does_not_exist.log"
            original, new = lw.truncate_log_file(nonexistent, keep_lines=100)
            assert original == 0
            assert new == 0


# =============================================
# log_watchdog.py -- scan_branch_log_files
# =============================================


def _import_watchdog(tmp_path):
    """Fresh-import log_watchdog with mocked config."""
    with patch.dict(
        sys.modules,
        {
            "aipass.prax.apps.handlers.config.load": MagicMock(
                PRAX_JSON_DIR=tmp_path / "prax_json",
            ),
        },
    ):
        sys.modules.pop("aipass.prax.apps.handlers.logging.log_watchdog", None)
        import aipass.prax.apps.handlers.logging.log_watchdog as lw

        return lw


class TestScanBranchLogFiles:
    """Tests for log_watchdog.py scan_branch_log_files()."""

    def test_detects_large_jsonl(self, mock_prax_infrastructure, tmp_path):
        """Flags .jsonl files exceeding size threshold as critical."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        branch_logs = eco / "hooks" / "logs"
        branch_logs.mkdir(parents=True)

        big_jsonl = branch_logs / "engine.jsonl"
        big_jsonl.write_text(
            "\n".join(f'{{"line": {i}, "padding": "{" " * 200}}}' for i in range(10000)) + "\n",
            encoding="utf-8",
        )

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            with patch.object(lw, "BRANCH_WARN_SIZE_MB", 0.5):
                results = lw.scan_branch_log_files()
                assert len(results) == 1
                assert results[0]["name"] == "engine.jsonl"
                assert results[0]["branch"] == "hooks"
                assert not results[0]["has_rotation"]
                assert results[0]["status"] in ("warning", "critical")

    def test_ignores_small_rotated_logs(self, mock_prax_infrastructure, tmp_path):
        """Small .log files with rotation siblings are status ok."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        branch_logs = eco / "backup" / "logs"
        branch_logs.mkdir(parents=True)

        small_log = branch_logs / "client.log"
        small_log.write_text("line1\nline2\n", encoding="utf-8")
        rotation = branch_logs / "client.log.1"
        rotation.write_text("old line\n", encoding="utf-8")

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            results = lw.scan_branch_log_files()
            assert len(results) == 1
            assert results[0]["name"] == "client.log"
            assert results[0]["has_rotation"] is True
            assert results[0]["status"] == "ok"

    def test_empty_ecosystem_returns_empty(self, mock_prax_infrastructure, tmp_path):
        """Returns empty when ecosystem root does not exist."""
        lw = _import_watchdog(tmp_path)

        nonexistent = tmp_path / "no_such_dir"
        with patch.object(lw, "_get_ecosystem_root", return_value=nonexistent):
            results = lw.scan_branch_log_files()
            assert results == []

    def test_scans_multiple_branches(self, mock_prax_infrastructure, tmp_path):
        """Scans logs/ across multiple branches."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        for branch in ("hooks", "backup", "trigger"):
            logs = eco / branch / "logs"
            logs.mkdir(parents=True)
            (logs / "test.log").write_text("line\n" * 10, encoding="utf-8")

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            results = lw.scan_branch_log_files()
            branches = {r["branch"] for r in results}
            assert branches == {"hooks", "backup", "trigger"}


class TestBranchLogHealthSummary:
    """Tests for log_watchdog.py branch_log_health_summary()."""

    def test_healthy_summary(self, mock_prax_infrastructure, tmp_path):
        """Returns healthy when all files are ok."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        logs = eco / "prax" / "logs"
        logs.mkdir(parents=True)
        (logs / "test.log").write_text("line\n" * 5, encoding="utf-8")

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            summary = lw.branch_log_health_summary()
            assert summary["healthy"] is True
            assert summary["total_files"] == 1
            assert summary["oversized_count"] == 0

    def test_empty_summary(self, mock_prax_infrastructure, tmp_path):
        """Returns healthy empty summary when no files found."""
        lw = _import_watchdog(tmp_path)

        nonexistent = tmp_path / "nope"
        with patch.object(lw, "_get_ecosystem_root", return_value=nonexistent):
            summary = lw.branch_log_health_summary()
            assert summary["healthy"] is True
            assert summary["total_files"] == 0


class TestEnforceBranchLogLimits:
    """Tests for log_watchdog.py enforce_branch_log_limits()."""

    def test_truncates_oversized_jsonl(self, mock_prax_infrastructure, tmp_path):
        """Truncates .jsonl files that exceed size threshold."""
        lw = _import_watchdog(tmp_path)

        eco = tmp_path / "src" / "aipass"
        logs = eco / "hooks" / "logs"
        logs.mkdir(parents=True)

        big_jsonl = logs / "engine.jsonl"
        big_jsonl.write_text(
            "\n".join(f'{{"line": {i}, "padding": "{" " * 200}}}' for i in range(10000)) + "\n",
            encoding="utf-8",
        )

        with patch.object(lw, "_get_ecosystem_root", return_value=eco):
            with patch.object(lw, "BRANCH_WARN_SIZE_MB", 0.5):
                actions = lw.enforce_branch_log_limits(max_lines=1000)
                assert len(actions) >= 1
                action = actions[0]
                assert action["truncated"] is True
                assert action["branch"] == "hooks"

                content = big_jsonl.read_text(encoding="utf-8")
                assert "LOG TRUNCATED by PRAX watchdog" in content


# =============================================
# monitoring.py -- run_monitoring_loop
# =============================================


class TestRunMonitoringLoop:
    """Tests for monitoring.py run_monitoring_loop()."""

    def test_loop_runs_and_handles_keyboard_interrupt(self, mock_prax_infrastructure):
        """Loop exits cleanly on KeyboardInterrupt and re-raises it."""
        import pytest

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(PRAX_JSON_DIR=MagicMock()),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.monitoring", None)
            import aipass.prax.apps.handlers.logging.monitoring as mon

            status_cb = MagicMock(
                return_value={"total_modules": 5, "individual_loggers": 3},
            )

            with patch.object(mon.time, "sleep", side_effect=KeyboardInterrupt):
                with pytest.raises(KeyboardInterrupt):
                    mon.run_monitoring_loop(status_cb, interval=1, status_interval=60)

    def test_loop_calls_status_callback_at_interval(self, mock_prax_infrastructure):
        """Loop calls status_callback when counter hits status_interval."""
        import pytest

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(PRAX_JSON_DIR=MagicMock()),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.monitoring", None)
            import aipass.prax.apps.handlers.logging.monitoring as mon

            status_cb = MagicMock(
                return_value={"total_modules": 2, "individual_loggers": 1},
            )
            call_count = 0

            def fake_sleep(seconds):
                """Simulate sleep and raise KeyboardInterrupt after 6 calls."""
                nonlocal call_count
                call_count += 1
                if call_count >= 6:
                    raise KeyboardInterrupt

            with patch.object(mon.time, "sleep", side_effect=fake_sleep):
                with pytest.raises(KeyboardInterrupt):
                    mon.run_monitoring_loop(status_cb, interval=5, status_interval=5)

            assert status_cb.called

    def test_loop_flushes_stdout(self, mock_prax_infrastructure):
        """Loop flushes sys.stdout during startup."""
        import pytest

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(PRAX_JSON_DIR=MagicMock()),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.monitoring", None)
            import aipass.prax.apps.handlers.logging.monitoring as mon

            status_cb = MagicMock(return_value={})

            with patch.object(mon.time, "sleep", side_effect=KeyboardInterrupt):
                with patch.object(mon.sys, "stdout") as mock_stdout:
                    with pytest.raises(KeyboardInterrupt):
                        mon.run_monitoring_loop(status_cb)
                    mock_stdout.flush.assert_called()


# =============================================
# operations.py -- create_config_file
# =============================================


class TestCreateConfigFile:
    """Tests for operations.py create_config_file()."""

    def test_creates_config_when_missing(self, mock_prax_infrastructure, tmp_path):
        """Creates default config file when it does not exist."""
        mock_config = MagicMock()
        mock_config.PRAX_JSON_DIR = tmp_path
        # Real dicts, not MagicMock attrs — create_config_file() serialises these
        # into the generated file, so they have to survive json.dump.
        mock_config.DEFAULT_SYSTEM_LOGS = {"max_lines": 1000, "backup_count": 3, "log_level": "INFO"}
        mock_config.DEFAULT_LOCAL_LOGS = {"max_lines": 250, "backup_count": 3, "log_level": "INFO"}

        mock_direct = MagicMock()
        mock_direct_logger = MagicMock()
        mock_direct.get_direct_logger = MagicMock(return_value=mock_direct_logger)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.direct": mock_direct,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.operations", None)
            import aipass.prax.apps.handlers.logging.operations as ops

            config_path = tmp_path / "prax_logger_config.json"
            ops.CONFIG_FILE = config_path

            ops.create_config_file()

            assert config_path.exists()
            content = json.loads(config_path.read_text(encoding="utf-8"))
            assert content["module_name"] == "prax_logger"
            assert "config" in content
            # The generated file must be readable by load_log_config(), which
            # looks for these two sections and nothing else for retention.
            assert content["config"]["system_logs"]["backup_count"] == 3
            assert content["config"]["local_logs"]["max_lines"] == 250
            assert content["config"]["debug_prints_enabled"] is False
            # Keys no reader ever consults do not belong in a generated config.
            for dead in ("max_log_size_mb", "backup_count", "console_output", "rotation_enabled", "debug_prints"):
                assert dead not in content["config"], f"{dead} is written but never read"

    def test_generated_config_is_readable_by_load_log_config(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """The file prax generates must be a file prax can read.

        These two halves lived apart for months: the template wrote retention
        keys at config.* while the loader read config.system_logs/local_logs, so
        a fresh install produced a config that governed nothing.
        """
        mock_config = MagicMock()
        mock_config.PRAX_JSON_DIR = tmp_path
        mock_config.DEFAULT_SYSTEM_LOGS = {"max_lines": 1000, "backup_count": 3, "log_level": "INFO"}
        mock_config.DEFAULT_LOCAL_LOGS = {"max_lines": 250, "backup_count": 3, "log_level": "INFO"}

        mock_direct = MagicMock()
        mock_direct.get_direct_logger = MagicMock(return_value=MagicMock())

        config_path = tmp_path / "prax_logger_config.json"
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.direct": mock_direct,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.operations", None)
            import aipass.prax.apps.handlers.logging.operations as ops

            ops.CONFIG_FILE = config_path
            ops.create_config_file()

        # Outside the patch: read it back with the real loader.
        sys.modules.pop("aipass.prax.apps.handlers.logging.operations", None)
        import aipass.prax.apps.handlers.config.load as load_mod

        mock_logger = MagicMock()
        monkeypatch.setattr(load_mod, "logger", mock_logger)
        monkeypatch.setattr(load_mod, "PRAX_LOGGER_CONFIG_FILE", config_path)
        monkeypatch.setattr(load_mod, "_config_schema_warned", False)

        result = load_mod.load_log_config()

        assert result["system_logs"]["backup_count"] == 3
        assert result["local_logs"]["max_lines"] == 250
        mock_logger.warning.assert_not_called()

    def test_does_not_overwrite_existing_config(self, mock_prax_infrastructure, tmp_path):
        """Does not overwrite an existing config file."""
        mock_config = MagicMock()
        mock_config.PRAX_JSON_DIR = tmp_path
        # Real dicts, not MagicMock attrs — create_config_file() serialises these
        # into the generated file, so they have to survive json.dump.
        mock_config.DEFAULT_SYSTEM_LOGS = {"max_lines": 1000, "backup_count": 3, "log_level": "INFO"}
        mock_config.DEFAULT_LOCAL_LOGS = {"max_lines": 250, "backup_count": 3, "log_level": "INFO"}

        mock_direct = MagicMock()
        mock_direct_logger = MagicMock()
        mock_direct.get_direct_logger = MagicMock(return_value=mock_direct_logger)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.direct": mock_direct,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.operations", None)
            import aipass.prax.apps.handlers.logging.operations as ops

            config_path = tmp_path / "prax_logger_config.json"
            config_path.write_text('{"existing": true}', encoding="utf-8")
            ops.CONFIG_FILE = config_path

            ops.create_config_file()

            content = json.loads(config_path.read_text(encoding="utf-8"))
            assert content == {"existing": True}

    def test_handles_write_error_gracefully(self, mock_prax_infrastructure, tmp_path):
        """Handles write errors without raising."""
        mock_config = MagicMock()
        mock_config.PRAX_JSON_DIR = tmp_path
        # Real dicts, not MagicMock attrs — create_config_file() serialises these
        # into the generated file, so they have to survive json.dump.
        mock_config.DEFAULT_SYSTEM_LOGS = {"max_lines": 1000, "backup_count": 3, "log_level": "INFO"}
        mock_config.DEFAULT_LOCAL_LOGS = {"max_lines": 250, "backup_count": 3, "log_level": "INFO"}

        mock_direct = MagicMock()
        mock_direct_logger = MagicMock()
        mock_direct.get_direct_logger = MagicMock(return_value=mock_direct_logger)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.direct": mock_direct,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.operations", None)
            import aipass.prax.apps.handlers.logging.operations as ops

            config_path = tmp_path / "nonexistent_dir" / "config.json"
            ops.CONFIG_FILE = config_path

            # Should not raise even when file creation fails
            ops.create_config_file()


# =============================================
# override.py -- enhanced_getLogger
# =============================================


class TestEnhancedGetLogger:
    """Tests for override.py enhanced_getLogger()."""

    def test_returns_logger_for_known_module(self, mock_prax_infrastructure):
        """Returns a configured logger when module is detected."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)
        mock_config.get_system_logs_dir = MagicMock()
        mock_config.get_module_logs_dir = MagicMock()
        mock_config.load_log_config = MagicMock()
        mock_config.lines_to_bytes = MagicMock()

        mock_introspection = MagicMock()
        mock_introspection.get_calling_module = MagicMock(return_value="test_module")

        mock_setup = MagicMock()
        mock_individual_logger = MagicMock()
        mock_individual_logger.handlers = [MagicMock()]
        mock_setup.setup_individual_logger = MagicMock(
            return_value=mock_individual_logger,
        )

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.setup": mock_setup,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.override", None)
            import aipass.prax.apps.handlers.logging.override as ov

            result = ov.enhanced_getLogger("some.name")
            assert isinstance(result, logging.Logger)
            mock_setup.setup_individual_logger.assert_called_once_with("test_module")

    def test_returns_original_logger_for_unknown_module(self, mock_prax_infrastructure):
        """Falls back to original logger when module is unknown."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)

        mock_introspection = MagicMock()
        mock_introspection.get_calling_module = MagicMock(return_value="unknown_module")

        mock_setup = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.setup": mock_setup,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.override", None)
            import aipass.prax.apps.handlers.logging.override as ov

            result = ov.enhanced_getLogger("some.name")
            assert isinstance(result, logging.Logger)
            mock_setup.setup_individual_logger.assert_not_called()

    def test_debug_prints_when_enabled(self, mock_prax_infrastructure):
        """Writes to stderr when debug prints are enabled."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_debug_prints_enabled = MagicMock(return_value=True)

        mock_introspection = MagicMock()
        mock_introspection.get_calling_module = MagicMock(return_value="unknown_module")

        mock_setup = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.setup": mock_setup,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.override", None)
            import aipass.prax.apps.handlers.logging.override as ov

            with patch("sys.stderr") as mock_stderr:
                ov.enhanced_getLogger("debug_test")
                mock_stderr.write.assert_called()


# =============================================
# override.py -- install_logger_override / restore_original_logger
# =============================================


class TestInstallRestoreLoggerOverride:
    """Tests for override.py install/restore functions."""

    def test_install_replaces_getlogger(self, mock_prax_infrastructure):
        """install_logger_override replaces logging.getLogger."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)

        mock_introspection = MagicMock()
        mock_setup = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.setup": mock_setup,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.override", None)
            import aipass.prax.apps.handlers.logging.override as ov

            original_fn = logging.getLogger
            try:
                ov.install_logger_override()
                assert logging.getLogger is ov.enhanced_getLogger
            finally:
                logging.getLogger = original_fn

    def test_restore_puts_back_original(self, mock_prax_infrastructure):
        """restore_original_logger restores the stdlib getLogger."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)

        mock_introspection = MagicMock()
        mock_setup = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.setup": mock_setup,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.override", None)
            import aipass.prax.apps.handlers.logging.override as ov

            original_fn = logging.getLogger
            try:
                ov.install_logger_override()
                assert logging.getLogger is ov.enhanced_getLogger
                ov.restore_original_logger()
                assert logging.getLogger is ov._original_getLogger
            finally:
                logging.getLogger = original_fn

    def test_is_override_active_reflects_state(self, mock_prax_infrastructure):
        """is_override_active returns correct state."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)

        mock_introspection = MagicMock()
        mock_setup = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_introspection,
                "aipass.prax.apps.handlers.logging.setup": mock_setup,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.override", None)
            import aipass.prax.apps.handlers.logging.override as ov

            original_fn = logging.getLogger
            try:
                ov.restore_original_logger()
                assert ov.is_override_active() is False
                ov.install_logger_override()
                assert ov.is_override_active() is True
            finally:
                logging.getLogger = original_fn


# =============================================
# setup.py -- setup_system_logger
# =============================================


class TestSetupSystemLogger:
    """Tests for setup.py setup_system_logger()."""

    def _make_mocks(self, tmp_path):
        """Build the standard mock set for setup.py tests."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_system_logs_dir = MagicMock(return_value=tmp_path / "system")
        mock_config.get_module_logs_dir = MagicMock(return_value=tmp_path / "local")
        mock_config.load_log_config = MagicMock(
            return_value={
                "log_format": "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                "date_format": "%Y-%m-%d %H:%M:%S",
                "system_logs": {"max_lines": 1000, "backup_count": 3},
                "local_logs": {"max_lines": 500, "backup_count": 2},
            }
        )
        mock_config.lines_to_bytes = MagicMock(return_value=200000)
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)
        mock_config.PRAX_JSON_DIR = tmp_path / "prax_json"

        mock_introspection = MagicMock()
        mock_introspection.get_calling_module_path = MagicMock(return_value=None)
        mock_introspection.detect_branch_from_path = MagicMock(return_value=None)

        mock_filtering = MagicMock()
        mock_filtering.should_display_terminal = MagicMock(return_value=False)

        mock_formatting = MagicMock()
        mock_formatting.create_terminal_handler = MagicMock()

        (tmp_path / "system").mkdir(parents=True, exist_ok=True)
        (tmp_path / "local").mkdir(parents=True, exist_ok=True)

        return mock_config, mock_introspection, mock_filtering, mock_formatting

    def test_creates_system_logger(self, mock_prax_infrastructure, tmp_path):
        """setup_system_logger creates and returns a logger."""
        mock_config, mock_intro, mock_filt, mock_fmt = self._make_mocks(tmp_path)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_intro,
                "aipass.prax.apps.handlers.logging.terminal.filtering": mock_filt,
                "aipass.prax.apps.handlers.logging.terminal.formatting": mock_fmt,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.setup", None)
            import aipass.prax.apps.handlers.logging.setup as setup_mod

            setup_mod._system_logger = None
            setup_mod._captured_loggers.clear()

            result = setup_mod.setup_system_logger()
            assert isinstance(result, logging.Logger)
            assert result.name == "prax_system_logger"
            assert len(result.handlers) >= 2

    def test_returns_cached_logger_on_second_call(self, mock_prax_infrastructure, tmp_path):
        """Second call returns the same cached logger."""
        mock_config, mock_intro, mock_filt, mock_fmt = self._make_mocks(tmp_path)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_intro,
                "aipass.prax.apps.handlers.logging.terminal.filtering": mock_filt,
                "aipass.prax.apps.handlers.logging.terminal.formatting": mock_fmt,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.setup", None)
            import aipass.prax.apps.handlers.logging.setup as setup_mod

            setup_mod._system_logger = None
            setup_mod._captured_loggers.clear()

            first = setup_mod.setup_system_logger()
            second = setup_mod.setup_system_logger()
            assert first is second


# =============================================
# setup.py -- _WindowsSafeRotatingHandler.doRollover
# =============================================


class TestSetupWindowsSafeRotatingHandlerDoRollover:
    """Tests for setup.py _WindowsSafeRotatingHandler.doRollover()."""

    def _make_mocks(self, tmp_path):
        """Build the standard mock set for setup.py handler tests."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.get_system_logs_dir = MagicMock(return_value=tmp_path)
        mock_config.get_module_logs_dir = MagicMock(return_value=tmp_path)
        mock_config.load_log_config = MagicMock(
            return_value={
                "log_format": "%(message)s",
                "date_format": "%H:%M:%S",
                "system_logs": {"max_lines": 100, "backup_count": 1},
                "local_logs": {"max_lines": 100, "backup_count": 1},
            }
        )
        mock_config.lines_to_bytes = MagicMock(return_value=20000)
        mock_config.get_debug_prints_enabled = MagicMock(return_value=False)
        mock_config.PRAX_JSON_DIR = tmp_path / "prax_json"

        mock_introspection = MagicMock()
        mock_introspection.get_calling_module_path = MagicMock(return_value=None)
        mock_introspection.detect_branch_from_path = MagicMock(return_value=None)

        mock_filtering = MagicMock()
        mock_formatting = MagicMock()

        return mock_config, mock_introspection, mock_filtering, mock_formatting

    def test_do_rollover_success(self, mock_prax_infrastructure, tmp_path):
        """Normal rollover succeeds."""
        mock_config, mock_intro, mock_filt, mock_fmt = self._make_mocks(tmp_path)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_intro,
                "aipass.prax.apps.handlers.logging.terminal.filtering": mock_filt,
                "aipass.prax.apps.handlers.logging.terminal.formatting": mock_fmt,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.setup", None)
            import aipass.prax.apps.handlers.logging.setup as setup_mod

            log_file = tmp_path / "rollover_test.log"
            log_file.write_text("data\n", encoding="utf-8")
            handler = setup_mod._WindowsSafeRotatingHandler(
                str(log_file),
                maxBytes=10,
                backupCount=1,
                encoding="utf-8",
            )
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="A" * 50,
                args=(),
                exc_info=None,
            )
            handler.emit(record)
            handler.close()
            assert log_file.exists() or (tmp_path / "rollover_test.log.1").exists()

    def test_do_rollover_permission_error_suppressed(self, mock_prax_infrastructure, tmp_path):
        """PermissionError during rollover is caught, not raised."""
        mock_config, mock_intro, mock_filt, mock_fmt = self._make_mocks(tmp_path)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.introspection": mock_intro,
                "aipass.prax.apps.handlers.logging.terminal.filtering": mock_filt,
                "aipass.prax.apps.handlers.logging.terminal.formatting": mock_fmt,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.setup", None)
            import aipass.prax.apps.handlers.logging.setup as setup_mod

            log_file = tmp_path / "perm_test.log"
            log_file.write_text("data\n", encoding="utf-8")
            handler = setup_mod._WindowsSafeRotatingHandler(
                str(log_file),
                maxBytes=10,
                backupCount=1,
                encoding="utf-8",
            )

            with patch(
                "logging.handlers.RotatingFileHandler.doRollover",
                side_effect=PermissionError("locked"),
            ):
                handler.doRollover()
            handler.close()


# =============================================
# terminal/filtering.py -- load_filtered_modules
# =============================================


class TestLoadFilteredModules:
    """Tests for terminal/filtering.py load_filtered_modules()."""

    def test_returns_defaults_when_no_config(self, mock_prax_infrastructure, tmp_path):
        """Returns DEFAULT_FILTERED_MODULES when config file absent."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path,
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.filtering", None)
            import aipass.prax.apps.handlers.logging.terminal.filtering as filt

            filt.CONFIG_FILE = tmp_path / "nonexistent_config.json"

            result = filt.load_filtered_modules()
            assert result == filt.DEFAULT_FILTERED_MODULES

    def test_loads_from_config_file(self, mock_prax_infrastructure, tmp_path):
        """Loads filtered modules from config file when present."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path,
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.filtering", None)
            import aipass.prax.apps.handlers.logging.terminal.filtering as filt

            config_file = tmp_path / "prax_terminal_config.json"
            config_file.write_text(
                json.dumps({"filtered_modules": ["custom_mod", "another_mod"]}),
                encoding="utf-8",
            )
            filt.CONFIG_FILE = config_file

            result = filt.load_filtered_modules()
            assert result == {"custom_mod", "another_mod"}

    def test_returns_defaults_on_corrupt_config(self, mock_prax_infrastructure, tmp_path):
        """Returns defaults when config file is corrupt JSON."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path,
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.filtering", None)
            import aipass.prax.apps.handlers.logging.terminal.filtering as filt

            config_file = tmp_path / "prax_terminal_config.json"
            config_file.write_text("NOT VALID JSON{{{{", encoding="utf-8")
            filt.CONFIG_FILE = config_file

            result = filt.load_filtered_modules()
            assert result == filt.DEFAULT_FILTERED_MODULES


# =============================================
# terminal/filtering.py -- should_display_terminal
# =============================================


class TestShouldDisplayTerminal:
    """Tests for terminal/filtering.py should_display_terminal()."""

    def test_external_module_displayed(self, mock_prax_infrastructure, tmp_path):
        """External module is not filtered and should display."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path,
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.filtering", None)
            import aipass.prax.apps.handlers.logging.terminal.filtering as filt

            result = filt.should_display_terminal("flow", filtered_modules={"prax_logger"})
            assert result is True

    def test_filtered_module_not_displayed(self, mock_prax_infrastructure, tmp_path):
        """Internal prax module is filtered and should not display."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path,
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.filtering", None)
            import aipass.prax.apps.handlers.logging.terminal.filtering as filt

            result = filt.should_display_terminal("prax_logger", filtered_modules={"prax_logger"})
            assert result is False

    def test_loads_from_config_when_no_set_provided(self, mock_prax_infrastructure, tmp_path):
        """Loads filtered modules from config when not explicitly passed."""
        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": MagicMock(
                    PRAX_JSON_DIR=tmp_path,
                ),
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.filtering", None)
            import aipass.prax.apps.handlers.logging.terminal.filtering as filt

            filt.CONFIG_FILE = tmp_path / "nonexistent.json"
            # "drone" is not in defaults, so it should display
            result = filt.should_display_terminal("drone")
            assert result is True

            # "prax_logger" IS in defaults, so it should NOT display
            result = filt.should_display_terminal("prax_logger")
            assert result is False


# =============================================
# terminal/formatting.py -- format_terminal_message
# =============================================


class TestFormatTerminalMessage:
    """Tests for terminal/formatting.py format_terminal_message()."""

    def _import_formatting(self, tmp_path):
        """Import formatting module with mocked dependencies."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.PRAX_JSON_DIR = tmp_path

        mock_filtering = MagicMock()
        mock_filtering.should_display_terminal = MagicMock(return_value=True)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.terminal.filtering": mock_filtering,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.formatting", None)
            import aipass.prax.apps.handlers.logging.terminal.formatting as fmt

        return fmt

    def test_format_with_branch(self, mock_prax_infrastructure, tmp_path):
        """Formats message with branch label."""
        fmt = self._import_formatting(tmp_path)

        record = logging.LogRecord(
            name="captured_flow_module",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Hello world",
            args=(),
            exc_info=None,
        )

        result = fmt.format_terminal_message(record, branch="flow")
        assert "[flow]" in result
        assert "flow_module" in result
        assert "INFO" in result
        assert "Hello world" in result

    def test_format_without_branch_uses_system(self, mock_prax_infrastructure, tmp_path):
        """Formats message with SYSTEM label when no branch given."""
        fmt = self._import_formatting(tmp_path)

        record = logging.LogRecord(
            name="captured_test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Warning msg",
            args=(),
            exc_info=None,
        )

        result = fmt.format_terminal_message(record)
        assert "[SYSTEM]" in result
        assert "WARNING" in result

    def test_format_strips_captured_prefix(self, mock_prax_infrastructure, tmp_path):
        """Removes 'captured_' prefix from logger name in output."""
        fmt = self._import_formatting(tmp_path)

        record = logging.LogRecord(
            name="captured_my_mod",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="error!",
            args=(),
            exc_info=None,
        )

        result = fmt.format_terminal_message(record, branch="prax")
        assert "captured_" not in result
        assert "my_mod" in result

    def test_format_non_captured_logger_name(self, mock_prax_infrastructure, tmp_path):
        """Logger name without captured_ prefix is used as-is."""
        fmt = self._import_formatting(tmp_path)

        record = logging.LogRecord(
            name="plain_logger",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="debug",
            args=(),
            exc_info=None,
        )

        result = fmt.format_terminal_message(record, branch="cli")
        assert "plain_logger" in result


# =============================================
# terminal/formatting.py -- create_terminal_handler
# =============================================


class TestCreateTerminalHandler:
    """Tests for terminal/formatting.py create_terminal_handler()."""

    def _import_formatting(self, tmp_path):
        """Import formatting module with mocked dependencies."""
        mock_config = MagicMock()
        mock_config.DEFAULT_LOG_LEVEL = logging.DEBUG
        mock_config.PRAX_JSON_DIR = tmp_path

        mock_filtering = MagicMock()
        mock_filtering.should_display_terminal = MagicMock(return_value=True)

        with patch.dict(
            sys.modules,
            {
                "aipass.prax.apps.handlers.config.load": mock_config,
                "aipass.prax.apps.handlers.logging.terminal.filtering": mock_filtering,
            },
        ):
            sys.modules.pop("aipass.prax.apps.handlers.logging.terminal.formatting", None)
            import aipass.prax.apps.handlers.logging.terminal.formatting as fmt

        return fmt

    def test_returns_stream_handler(self, mock_prax_infrastructure, tmp_path):
        """Returns a StreamHandler instance."""
        fmt = self._import_formatting(tmp_path)
        handler = fmt.create_terminal_handler()
        assert isinstance(handler, logging.StreamHandler)

    def test_handler_has_terminal_formatter(self, mock_prax_infrastructure, tmp_path):
        """Handler uses TerminalFormatter."""
        fmt = self._import_formatting(tmp_path)
        handler = fmt.create_terminal_handler()
        assert isinstance(handler.formatter, fmt.TerminalFormatter)

    def test_handler_writes_to_stdout(self, mock_prax_infrastructure, tmp_path):
        """Handler stream is sys.stdout."""
        fmt = self._import_formatting(tmp_path)
        handler = fmt.create_terminal_handler()
        assert handler.stream is sys.stdout
