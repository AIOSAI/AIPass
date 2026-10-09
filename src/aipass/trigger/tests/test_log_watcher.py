# =================== META ====================
# Name: test_log_watcher.py
# Description: Unit tests for the branch log watcher's parsing, detection and line pipeline
# Version: 1.5.0
# Created: 2026-04-03
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/log_watcher.py — parsing, detection and the line pipeline that fires events."""

# File reading and rotation live in test_log_watcher_rotation.py, and the
# persisted state and lifecycle in test_log_watcher_state.py, since the
# oversize_test_file split (2026-10-08). The live-state doors are closed by
# conftest's log_watcher_infrastructure, which this file names in pytestmark.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the centralized system_logs watcher, in test_watchers_log_watcher.py

import hashlib
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import aipass.trigger.apps.handlers.error_registry as error_registry
import aipass.trigger.apps.handlers.json.config_loader as config_loader
import aipass.trigger.apps.handlers.log_watcher as lw
from aipass.trigger.tests.support_log_watcher import _BRANCH_LOG_PATH, _SYNTHETIC_HOME

pytestmark = pytest.mark.usefixtures("log_watcher_infrastructure")


# A second synthetic root, beside support_log_watcher's _SYNTHETIC_HOME, for a
# path outside every known tree: an input under test, not a location.
_SYNTHETIC_ELSEWHERE = PurePosixPath("/synthetic/elsewhere")


# ---------------------------------------------------------------------------
# Tests -- generate_error_hash
# ---------------------------------------------------------------------------


class TestGenerateErrorHash:
    """Tests for generate_error_hash pure function."""

    def test_deterministic(self):
        """Same inputs always produce the same hash."""
        h1 = lw.generate_error_hash("mod_a", "something broke")
        h2 = lw.generate_error_hash("mod_a", "something broke")
        assert h1 == h2

    def test_length_is_8(self):
        """Hash is exactly 8 characters long."""
        h = lw.generate_error_hash("module", "message")
        assert len(h) == 8

    def test_different_inputs_different_hashes(self):
        """Different module/message combos produce different hashes."""
        h1 = lw.generate_error_hash("mod_a", "error one")
        h2 = lw.generate_error_hash("mod_b", "error two")
        assert h1 != h2

    def test_matches_md5_prefix(self):
        """Hash matches the first 8 chars of MD5(module:message)."""
        expected = hashlib.md5("mymod:mymsg".encode()).hexdigest()[:8]
        assert lw.generate_error_hash("mymod", "mymsg") == expected


# ---------------------------------------------------------------------------
# Tests -- detect_branch_from_path
# ---------------------------------------------------------------------------


class TestDetectBranchFromPath:
    """Tests for detect_branch_from_path."""

    def test_standard_branch_logs_path(self):
        """Detects branch from src/aipass/<branch>/logs/file.log pattern."""
        path = str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow_planner.log")
        assert lw.detect_branch_from_path(path) == "FLOW"

    def test_system_logs_mapped_file(self):
        """Uses SYSTEM_LOGS_BRANCH_MAP for known filenames."""
        path = str(lw.SYSTEM_LOGS_DIR / "telegram_bridge.log")
        assert lw.detect_branch_from_path(path) == "API"

    def test_system_logs_prefix_match(self):
        """Matches prefix against known branch prefixes for system_logs files."""
        path = str(lw.SYSTEM_LOGS_DIR / "seedgo_audit.log")
        assert lw.detect_branch_from_path(path) == "SEEDGO"

    def test_system_logs_exact_stem_match(self):
        """Matches when stem equals a known prefix exactly."""
        path = str(lw.SYSTEM_LOGS_DIR / "prax.log")
        assert lw.detect_branch_from_path(path) == "PRAX"

    def test_unknown_path_returns_unknown(self):
        """Returns UNKNOWN for paths that do not match any pattern."""
        assert lw.detect_branch_from_path(str(_SYNTHETIC_ELSEWHERE / "some" / "random" / "path.log")) == "UNKNOWN"

    def test_failure_raises_instead_of_answering_unknown(self):
        """A path it cannot read raises; it is not filed under the UNKNOWN branch.

        UNKNOWN is a real answer (a log outside every known tree), so a
        failure returned as UNKNOWN fired an error_detected event for a branch
        nobody owns. The caller, _process_log_line, contains the raise and
        skips that one line (test_outer_exception_handler_catches_unexpected).
        Mutant run: `Path(log_path or "")` (a swallowed failure) reddens this.
        """
        unreadable: Any = None
        with pytest.raises(TypeError):
            lw.detect_branch_from_path(unreadable)


# ---------------------------------------------------------------------------
# Tests -- parse_prax_log_line
# ---------------------------------------------------------------------------


class TestParsePraxLogLine:
    """Tests for parse_prax_log_line."""

    def test_pipe_format_error(self):
        """Parses pipe-separated ERROR line correctly."""
        line = "2026-03-01 12:00:00.123 | my_module | ERROR | Something failed"
        result = lw.parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "ERROR"
        assert result["module"] == "my_module"
        assert result["message"] == "Something failed"
        assert "2026-03-01" in result["timestamp"]

    def test_pipe_format_critical(self):
        """Parses pipe-separated CRITICAL line correctly."""
        line = "2026-03-01 12:00:00.123 | core | CRITICAL | Fatal error"
        result = lw.parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "CRITICAL"

    def test_pipe_format_info_returns_none(self):
        """INFO level lines are not returned (only ERROR/CRITICAL)."""
        line = "2026-03-01 12:00:00.123 | my_module | INFO | All good"
        assert lw.parse_prax_log_line(line) is None

    def test_pipe_format_warning_returns_none(self):
        """WARNING level lines are not returned."""
        line = "2026-03-01 12:00:00.123 | my_module | WARNING | Watch out"
        assert lw.parse_prax_log_line(line) is None

    def test_dash_format_error(self):
        """Parses dash-separated ERROR line (Python logging format)."""
        line = "2026-02-10 15:12:29,460 - telegram_bridge - ERROR - Connection lost"
        result = lw.parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "ERROR"
        assert result["module"] == "telegram_bridge"
        assert result["message"] == "Connection lost"

    def test_malformed_line_returns_none(self):
        """Malformed line that does not match any format returns None."""
        assert lw.parse_prax_log_line("just some random text") is None

    def test_empty_line_returns_none(self):
        """Empty line returns None."""
        assert lw.parse_prax_log_line("") is None

    def test_failure_raises_instead_of_answering_none(self):
        """A line it cannot read raises; None means "not an error line".

        Returning None on a failure made the line look like an ordinary
        INFO line. The callers, _process_log_line and _process_warning_line,
        contain the raise and skip that one line
        (test_outer_exception_handler_catches_unexpected,
        test_unexpected_failure_is_contained).
        Mutant run: `if log_line is None: return None` ahead of the parse reddens this.
        """
        unreadable: Any = None
        with pytest.raises(TypeError):
            lw.parse_prax_log_line(unreadable)


# ---------------------------------------------------------------------------
# Tests -- is_stale_entry
# ---------------------------------------------------------------------------


class TestIsStaleEntry:
    """Tests for is_stale_entry."""

    def test_recent_timestamp_not_stale(self):
        """A timestamp within the threshold is NOT stale."""
        now = datetime.now()
        recent = now - timedelta(seconds=10)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw.is_stale_entry(ts) is False

    def test_old_timestamp_is_stale(self):
        """A timestamp well beyond the threshold IS stale."""
        old = datetime.now() - timedelta(seconds=600)
        ts = old.strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw.is_stale_entry(ts) is True

    def test_unparseable_timestamp_returns_true(self):
        """An unparseable timestamp is treated as stale."""
        assert lw.is_stale_entry("not-a-timestamp") is True

    def test_comma_microsecond_format(self):
        """Python logging format with comma microseconds is parsed correctly."""
        recent = datetime.now() - timedelta(seconds=5)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S,") + "123"
        assert lw.is_stale_entry(ts) is False


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._should_process
# ---------------------------------------------------------------------------


class TestShouldProcess:
    """Tests for BranchLogWatcher._should_process."""

    def test_log_file_in_branch_dir_accepted(self):
        """.log file inside /aipass/branch/logs/ is accepted."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log")) is True

    def test_txt_file_rejected(self):
        """.txt file is rejected even if in the right directory."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "notes.txt")) is False

    def test_excluded_file_rejected(self):
        """Excluded log files (e.g. dispatch.log) are rejected."""
        watcher = lw.BranchLogWatcher()
        assert (
            watcher._should_process(str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "dispatch.log")) is False
        )

    def test_system_logs_accepted(self):
        """Log file inside /system_logs/ is accepted."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_HOME / "system_logs" / "prax.log")) is True

    def test_random_log_outside_known_dirs_rejected(self):
        """Log file outside branch and system_logs dirs is rejected."""
        watcher = lw.BranchLogWatcher()
        assert watcher._should_process(str(_SYNTHETIC_ELSEWHERE / "random" / "output.log")) is False


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._process_log_line
# ---------------------------------------------------------------------------


class TestProcessLogLine:
    """Tests for BranchLogWatcher._process_log_line."""

    def test_fires_event_on_new_error(self):
        """Fires error_detected event for a new ERROR line via registry path."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | my_module | ERROR | Database connection failed"
        log_path = str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log")

        watcher._process_log_line(line, log_path)

        fire.assert_called_once()
        call_args = fire.call_args
        assert call_args[0][0] == "error_detected"
        assert call_args[1]["message"] == "Database connection failed"

    def test_skips_semantic_exclusion_patterns(self):
        """Lines matching semantic exclusion patterns are skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | handler | ERROR | Processed error error_hash=abc123"
        watcher._process_log_line(line, str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log"))

        fire.assert_not_called()

    def test_skips_stale_entries(self):
        """Lines with stale timestamps are skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{old} | mod | ERROR | Old error"
        watcher._process_log_line(line, str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log"))

        fire.assert_not_called()

    def test_skips_non_error_lines(self):
        """INFO-level lines are not processed (parse returns None)."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        line = f"{now} | mod | INFO | All good"
        watcher._process_log_line(line, str(_SYNTHETIC_HOME / "src" / "aipass" / "flow" / "logs" / "flow.log"))

        fire.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- is_stale_entry (additional format coverage)
# ---------------------------------------------------------------------------


class TestIsStaleEntryFormats:
    """Additional format coverage for is_stale_entry."""

    def test_iso_format_with_microseconds_fresh(self):
        """ISO format with microseconds: T separator and dot microseconds."""
        recent = datetime.now() - timedelta(seconds=5)
        ts = recent.strftime("%Y-%m-%dT%H:%M:%S.%f")
        assert lw.is_stale_entry(ts) is False

    def test_iso_format_simple_stale(self):
        """ISO format without microseconds, stale timestamp."""
        old = datetime.now() - timedelta(seconds=600)
        ts = old.strftime("%Y-%m-%dT%H:%M:%S")
        assert lw.is_stale_entry(ts) is True

    def test_simple_format_no_microseconds_fresh(self):
        """Simple YYYY-MM-DD HH:MM:SS format, fresh."""
        recent = datetime.now() - timedelta(seconds=2)
        ts = recent.strftime("%Y-%m-%d %H:%M:%S")
        assert lw.is_stale_entry(ts) is False

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped before parsing."""
        recent = datetime.now() - timedelta(seconds=5)
        ts = "  " + recent.strftime("%Y-%m-%d %H:%M:%S.%f") + "  "
        assert lw.is_stale_entry(ts) is False

    def test_empty_string_returns_true(self):
        """Empty string is unparseable and treated as stale."""
        assert lw.is_stale_entry("") is True


# ---------------------------------------------------------------------------
# Tests -- detect_branch_from_path (additional edge cases)
# ---------------------------------------------------------------------------


class TestDetectBranchFromPathEdgeCases:
    """Additional edge cases for detect_branch_from_path."""

    def test_pycache_directory_ignored(self):
        """__pycache__ after aipass/ is not treated as a branch."""
        path = str(_SYNTHETIC_HOME / "src" / "aipass" / "__pycache__" / "logs" / "something.log")
        assert lw.detect_branch_from_path(path) == "UNKNOWN"

    def test_system_logs_unknown_file(self):
        """Unknown file in system_logs returns UNKNOWN."""
        path = str(lw.SYSTEM_LOGS_DIR / "completely_random.log")
        assert lw.detect_branch_from_path(path) == "UNKNOWN"

    def test_multiple_aipass_segments(self):
        """First valid aipass/branch/logs/ match wins."""
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "trigger" / "logs" / "inner.log")
        assert lw.detect_branch_from_path(path) == "TRIGGER"

    def test_aipass_without_logs_subdir(self):
        """aipass/branch without /logs/ segment returns UNKNOWN."""
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "drone" / "core.log")
        assert lw.detect_branch_from_path(path) == "UNKNOWN"

    def test_system_logs_ai_mail_prefix(self):
        """Multi-word prefix (ai_mail) is matched correctly."""
        path = str(lw.SYSTEM_LOGS_DIR / "ai_mail_delivery.log")
        assert lw.detect_branch_from_path(path) == "AI_MAIL"


# ---------------------------------------------------------------------------
# Tests -- parse_prax_log_line (additional edge cases)
# ---------------------------------------------------------------------------


class TestParsePraxLogLineEdgeCases:
    """Additional edge cases for parse_prax_log_line."""

    def test_dash_format_critical(self):
        """Dash format with CRITICAL level is accepted."""
        line = "2026-04-26 10:00:00,100 - core - CRITICAL - System down"
        result = lw.parse_prax_log_line(line)
        assert result is not None
        assert result["level"] == "CRITICAL"
        assert result["module"] == "core"
        assert result["message"] == "System down"

    def test_dash_format_info_returns_none(self):
        """Dash format with INFO level returns None."""
        line = "2026-04-26 10:00:00,100 - core - INFO - All is well"
        assert lw.parse_prax_log_line(line) is None

    def test_pipe_format_too_few_parts(self):
        """Pipe format with fewer than 4 parts returns None."""
        line = "2026-04-26 10:00:00 | only_two_parts"
        assert lw.parse_prax_log_line(line) is None

    def test_dash_format_too_few_parts(self):
        """Dash format with fewer than 4 parts returns None."""
        line = "2026-04-26 - module_only"
        assert lw.parse_prax_log_line(line) is None

    def test_pipe_format_warning_level_returns_none(self):
        """Pipe format with WARNING level (not error) returns None."""
        line = "2026-04-26 10:00:00 | mod | WARNING | caution"
        assert lw.parse_prax_log_line(line) is None

    def test_dash_format_debug_level_returns_none(self):
        """Dash format with DEBUG level returns None."""
        line = "2026-04-26 10:00:00,100 - mod - DEBUG - tracing"
        assert lw.parse_prax_log_line(line) is None


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._should_process (additional edge cases)
# ---------------------------------------------------------------------------


class TestShouldProcessEdgeCases:
    """Additional edge cases for BranchLogWatcher._should_process."""

    def test_excluded_file_case_insensitive(self):
        """Exclusion matching is case-insensitive."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "DISPATCH.LOG")
        assert watcher._should_process(path) is False

    def test_non_log_extension_py(self):
        """.py file is rejected."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "handler.py")
        assert watcher._should_process(path) is False

    def test_excluded_trigger_log_watcher(self):
        """trigger_log_watcher.log is excluded (self-referential)."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "trigger" / "logs" / "trigger_log_watcher.log")
        assert watcher._should_process(path) is False

    def test_excluded_medic_suppressed(self):
        """medic_suppressed.jsonl is excluded."""
        watcher = lw.BranchLogWatcher()
        path = str(Path(_SYNTHETIC_HOME) / "src" / "aipass" / "flow" / "logs" / "medic_suppressed.jsonl")
        assert watcher._should_process(path) is False


# ---------------------------------------------------------------------------
# Tests -- BranchLogWatcher._process_log_line (deeper coverage)
# ---------------------------------------------------------------------------


class TestProcessLogLineDeeper:
    """Deeper coverage for BranchLogWatcher._process_log_line."""

    def _make_error_line(self, message: str = "Something broke") -> str:
        """Build a fresh ERROR line with current timestamp."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        return f"{now} | test_mod | ERROR | {message}"

    def test_semantic_exclusion_fingerprint(self):
        """Line containing 'fingerprint' in message is skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Error with fingerprint=xyz789")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_semantic_exclusion_registry_id(self):
        """Line containing 'registry_id' in message is skipped."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Logged with registry_id=r001")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_registry_path_fires_event_with_registry_data(self, monkeypatch):
        """Registry available: fires event with registry metadata."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)

        mock_report = MagicMock(
            return_value={
                "is_new": True,
                "count": 1,
                "id": "reg123",
                "fingerprint": "fp456",
                "first_seen": "2026-04-26",
                "last_seen": "2026-04-26",
            }
        )
        monkeypatch.setattr(lw, "registry_report", mock_report)

        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("DB connection lost")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["branch"] == "FLOW"
        assert call_kwargs["message"] == "DB connection lost"
        assert call_kwargs["registry_id"] == "reg123"
        assert call_kwargs["fingerprint"] == "fp456"
        assert call_kwargs["count"] == 1

    def test_registry_report_exception_falls_to_fallback(self, monkeypatch):
        """Registry report raises: falls through to fallback path."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)

        monkeypatch.setattr(lw, "registry_report", MagicMock(side_effect=RuntimeError("registry down")))

        # The lazy fallback reaches the registry and it fails too: the
        # watcher is left with its own local count.
        monkeypatch.setattr(error_registry, "report", MagicMock(side_effect=ImportError("registry gone")))
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Fallback triggered")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["message"] == "Fallback triggered"
        assert call_kwargs["count"] == 1

    def test_fallback_lazy_import_succeeds(self, monkeypatch):
        """Fallback path: lazy import succeeds, fires event."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", False)

        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Lazy import works")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        call_kwargs = fire.call_args[1]
        assert call_kwargs["message"] == "Lazy import works"

    def test_local_count_tracking_increments(self, monkeypatch):
        """Local count path: repeated errors increment counter."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)
        monkeypatch.setattr(lw, "registry_report", MagicMock(side_effect=RuntimeError("registry down")))

        monkeypatch.setattr(error_registry, "report", MagicMock(side_effect=ImportError("registry gone")))
        watcher = lw.BranchLogWatcher()
        line = self._make_error_line("Repeated failure")
        watcher._process_log_line(line, _BRANCH_LOG_PATH)
        watcher._process_log_line(line, _BRANCH_LOG_PATH)

        assert fire.call_count == 2
        second_call = fire.call_args_list[1][1]
        assert second_call["count"] == 2

    def test_outer_exception_handler_catches_unexpected(self):
        """Outer try/except catches unexpected errors without raising."""
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        with patch.object(
            lw,
            "parse_prax_log_line",
            side_effect=TypeError("boom"),
        ):
            watcher._process_log_line("any line", str(_SYNTHETIC_ELSEWHERE / "any" / "path.log"))

        fire.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- WARNING capture for the escalation lane (DPLAN-0283 WS-A)
# ---------------------------------------------------------------------------


def _set_warning_capture(lw, enabled: bool, monkeypatch) -> MagicMock:
    """Answer the operator config the way a real config_loader would.

    config_loader is imported lazily inside _warning_capture_enabled, so the
    answer is configured on the mocked handlers.json package and the 60s TTL
    cache is dropped.
    """
    section = MagicMock(return_value={"watch_branch_log_warnings": enabled})
    monkeypatch.setattr(config_loader, "section", section)
    monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, True))
    return section


def _warning_line(message: str = "Queue depth at 91%", module: str = "watcher", level: str = "WARNING") -> str:
    """Build a fresh prax-format WARNING line."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    return f"{now} | {module} | {level} | {message}"


class TestLevelConstants:
    """The two level sets the parser is driven with."""

    def test_error_levels(self):
        """CRITICAL rides with ERROR — both mean something broke."""
        assert lw.ERROR_LEVELS == ("ERROR", "CRITICAL")

    def test_warning_levels_include_the_short_alias(self):
        """Loggers emit both WARNING and WARN; missing WARN would drop half the lines."""
        assert lw.WARNING_LEVELS == ("WARNING", "WARN")

    def test_the_two_sets_do_not_overlap(self):
        """A line can never be counted as both an error and a warning."""
        assert not set(lw.ERROR_LEVELS) & set(lw.WARNING_LEVELS)


class TestParsePraxLogLineLevels:
    """The parser takes the levels it should accept as an argument."""

    def test_warning_parsed_with_warning_levels(self):
        """A WARNING line parses when WARNING_LEVELS is passed."""
        parsed = lw.parse_prax_log_line(_warning_line(), levels=lw.WARNING_LEVELS)
        assert parsed is not None
        assert parsed["level"] == "WARNING"
        assert parsed["module"] == "watcher"
        assert parsed["message"] == "Queue depth at 91%"

    def test_warn_alias_parsed(self):
        """The WARN spelling parses the same way."""
        parsed = lw.parse_prax_log_line(_warning_line(level="WARN"), levels=lw.WARNING_LEVELS)
        assert parsed is not None
        assert parsed["level"] == "WARN"

    def test_python_dash_format_warning_parsed(self):
        """Python logging format is supported for warnings too."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")
        parsed = lw.parse_prax_log_line(f"{now} - watcher - WARNING - Queue depth", levels=lw.WARNING_LEVELS)
        assert parsed is not None
        assert parsed["level"] == "WARNING"
        assert parsed["message"] == "Queue depth"

    def test_error_is_not_a_warning(self):
        """An ERROR line is not collected by the warning lane."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        assert lw.parse_prax_log_line(f"{now} | mod | ERROR | boom", levels=lw.WARNING_LEVELS) is None

    def test_default_levels_still_ignore_warnings(self):
        """The default stays ERROR-only, so the error path is unchanged."""
        assert lw.parse_prax_log_line(_warning_line()) is None


class TestProcessWarningLine:
    """WARNING lines feed the escalation lane and nothing else.

    They never enter the error registry and never dispatch anyone — before
    this path existed, a branch warning was read by nothing at all.
    """

    def test_fires_warning_logged(self, monkeypatch):
        """A fresh WARNING line fires the event with the lane's fields."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        line = _warning_line()

        watcher._process_warning_line(line, _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "warning_logged"
        kwargs = fire.call_args[1]
        assert kwargs["branch"] == "FLOW"
        assert kwargs["module_name"] == "watcher"
        assert kwargs["level"] == "WARNING"
        assert kwargs["message"] == "Queue depth at 91%"
        assert kwargs["log_file"] == _BRANCH_LOG_PATH
        assert kwargs["raw_line"] == line

    def test_warn_alias_fires(self, monkeypatch):
        """WARN is the same signal as WARNING."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line(level="WARN"), _BRANCH_LOG_PATH)

        assert fire.call_args[0][0] == "warning_logged"

    def test_info_fires_nothing(self, monkeypatch):
        """INFO is not a failure signal — the lane must not count it."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_warning_line(f"{now} | mod | INFO | All good", _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_stale_warning_fires_nothing(self, monkeypatch):
        """A replayed rotation must not re-count old warnings."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_warning_line(f"{old} | watcher | WARNING | Queue depth at 91%", _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_semantic_exclusion_fires_nothing(self, monkeypatch):
        """A line ABOUT an error artifact is not new signal."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line("Retrying error_hash=abc123"), _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_capture_disabled_by_config_fires_nothing(self, monkeypatch):
        """An operator can switch branch-log warning reading off entirely."""
        _set_warning_capture(lw, False, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_not_called()

    def test_capture_enabled_by_config_fires(self, monkeypatch):
        """Positive control for the switch: the identical line fires when it is on.

        Mutant: the event renamed error_detected.
        """
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_warning_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "warning_logged"

    def test_unexpected_failure_is_contained(self, monkeypatch):
        """The watcher must survive a warning it cannot parse."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        with patch.object(lw, "parse_prax_log_line", side_effect=TypeError("boom")):
            watcher._process_warning_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_not_called()


class TestWarningCaptureEnabled:
    """Reading the switch runs per log line, so it is cached and fails open."""

    def test_reads_the_operator_setting(self, monkeypatch):
        """False in the config means false here."""
        _set_warning_capture(lw, False, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        lw.BranchLogWatcher()._process_log_line(_warning_line(), _BRANCH_LOG_PATH)
        fire.assert_not_called()

    def test_answer_is_cached_between_lines(self, monkeypatch):
        """A config file read per log line would put file IO on the hot path."""
        section = _set_warning_capture(lw, True, monkeypatch)
        lw.set_event_callback(MagicMock())
        watcher = lw.BranchLogWatcher()

        for n in range(3):
            watcher._process_log_line(_warning_line(f"Queue depth at 9{n}%"), _BRANCH_LOG_PATH)

        section.assert_called_once_with("escalation")

    def test_unreadable_config_keeps_capture_on(self, monkeypatch):
        """Fails OPEN: losing the count silently is the failure the lane exists to stop."""
        monkeypatch.setattr(config_loader, "section", MagicMock(side_effect=OSError("disk gone")))
        monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, False))
        fire = MagicMock()
        lw.set_event_callback(fire)

        lw.BranchLogWatcher()._process_log_line(_warning_line(), _BRANCH_LOG_PATH)

        assert fire.call_args[0][0] == "warning_logged"

    def test_missing_key_defaults_to_on(self, monkeypatch):
        """A config predating this setting still watches warnings."""
        monkeypatch.setattr(config_loader, "section", MagicMock(return_value={}))
        monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, False))
        fire = MagicMock()
        lw.set_event_callback(fire)

        lw.BranchLogWatcher()._process_log_line(_warning_line(), _BRANCH_LOG_PATH)

        assert fire.call_args[0][0] == "warning_logged"


class TestProcessLogLineRoutesWarnings:
    """One entry point routes a line to the error path or the warning path."""

    def test_warning_line_reaches_the_warning_path(self, monkeypatch):
        """A WARNING line falls through the ERROR parse into warning_logged."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()

        watcher._process_log_line(_warning_line(), _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "warning_logged"

    def test_error_line_still_takes_the_error_path(self, monkeypatch):
        """The error path is unchanged: an ERROR line never becomes a warning."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_log_line(f"{now} | my_module | ERROR | Database connection failed", _BRANCH_LOG_PATH)

        fire.assert_called_once()
        assert fire.call_args[0][0] == "error_detected"

    def test_info_line_reaches_neither_path(self, monkeypatch):
        """INFO is dropped by both parsers."""
        _set_warning_capture(lw, True, monkeypatch)
        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        watcher._process_log_line(f"{now} | mod | INFO | All good", _BRANCH_LOG_PATH)

        fire.assert_not_called()


# ---------------------------------------------------------------------------
# Tests -- system_logs twins (double-processing, devpulse e9d92ed2)
# ---------------------------------------------------------------------------


def _dual_write_tree(tmp_path, branch: str, module: str):
    """Build the tree prax actually produces: the same line in two files.

    Returns (branch_log, system_log), both real files under tmp_path.
    """
    branch_log = tmp_path / "aipass" / branch / "logs" / f"{module}.log"
    branch_log.parent.mkdir(parents=True, exist_ok=True)
    branch_log.touch()
    system_log = tmp_path / "system_logs" / f"{branch}_{module}.log"
    system_log.parent.mkdir(parents=True, exist_ok=True)
    system_log.touch()
    return branch_log, system_log


def _point_at_tree(lw, monkeypatch, tmp_path) -> None:
    """Aim the watcher's roots at a temp tree and drop the branch-name cache."""
    monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "aipass")
    monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")
    monkeypatch.setattr(lw, "_branch_names_cache", (0.0, ()))


class TestSystemLogTwinIsNotProcessedTwice:
    """Prax writes every branch line to BOTH the branch's own logs/ dir and
    system_logs/<branch>_<module>.log, and this watcher schedules both trees.
    One physical line was therefore counted twice — once attributed by
    directory, once by a filename guess.

    Live evidence (2026-08-14): escalation signatures 0249c13b4d64 (HOOKS,
    src/aipass/hooks/logs/edit_gate.log) and 690de8d87cdc (UNKNOWN,
    system_logs/hooks_edit_gate.log) hold the SAME three sample lines with
    consecutive sequence numbers 8514/8515 — one reader, two files. Reported
    by devpulse in e9d92ed2. Measured: 230 of 243 system_logs files are
    twin-backed.
    """

    def test_dual_written_system_log_is_skipped(self, monkeypatch, tmp_path):
        """The system_logs copy is dropped when its branch twin exists."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        _, system_log = _dual_write_tree(tmp_path, "hooks", "edit_gate")
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(system_log)) is False

    def test_the_branch_copy_is_the_one_kept(self, monkeypatch, tmp_path):
        """The attributed copy keeps being read — coverage is not lost."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        branch_log, _ = _dual_write_tree(tmp_path, "hooks", "edit_gate")
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(branch_log)) is True

    def test_system_log_without_a_twin_is_still_watched(self, monkeypatch, tmp_path):
        """A real system-level log — no branch writes it — stays watched."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        orphan = tmp_path / "system_logs" / "telegram-bot-api.log"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.touch()
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(orphan)) is True

    def test_multi_word_branch_name_resolves_its_twin(self, monkeypatch, tmp_path):
        """ai_mail_dispatch_monitor.log resolves to ai_mail, not 'ai'."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        _, system_log = _dual_write_tree(tmp_path, "ai_mail", "dispatch_monitor")
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(system_log)) is False

    def test_same_name_without_a_real_twin_file_is_not_skipped(self, monkeypatch, tmp_path):
        """A branch dir alone is not enough — the twin FILE must exist."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        (tmp_path / "aipass" / "hooks" / "logs").mkdir(parents=True)
        system_log = tmp_path / "system_logs" / "hooks_edit_gate.log"
        system_log.parent.mkdir(parents=True, exist_ok=True)
        system_log.touch()
        watcher = lw.BranchLogWatcher()

        assert watcher._should_process(str(system_log)) is True

    def test_one_line_written_to_both_files_fires_once(self, monkeypatch, tmp_path):
        """The regression itself: prax's dual write yields ONE event."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        _set_warning_capture(lw, True, monkeypatch)
        branch_log, system_log = _dual_write_tree(tmp_path, "hooks", "edit_gate")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{now} | captured_edit_gate | WARNING | [HOOKS] edit_gate: todos over limit (11/10)\n"
        branch_log.write_text(line, encoding="utf-8")
        system_log.write_text(line, encoding="utf-8")

        fire = MagicMock()
        lw.set_event_callback(fire)
        watcher = lw.BranchLogWatcher()
        for path in (branch_log, system_log):
            watcher.on_modified(SimpleNamespace(is_directory=False, src_path=str(path)))

        assert fire.call_count == 1
        assert fire.call_args.kwargs["branch"] == "HOOKS"


class TestSystemLogAttributionComesFromTheLiveTree:
    """The branch prefixes were a hardcoded list of 11 names while the tree
    held 17 branches. Every system_logs file belonging to one of the missing
    six (@hooks, @backup, @commons, @daemon, @skills, @aipass) was attributed
    to UNKNOWN — the fault was the list, not the log.
    """

    def test_unlisted_branch_attributes_from_the_tree(self, monkeypatch, tmp_path):
        """hooks/ exists on disk, so hooks_*.log is HOOKS — never UNKNOWN."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        (tmp_path / "aipass" / "hooks").mkdir(parents=True)
        path = str(tmp_path / "system_logs" / "hooks_edit_gate.log")

        assert lw.detect_branch_from_path(path) == "HOOKS"

    def test_non_citizen_still_reports_unknown(self, monkeypatch, tmp_path):
        """UNKNOWN keeps its meaning: nobody in the tree owns this log."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        (tmp_path / "aipass" / "hooks").mkdir(parents=True)
        path = str(tmp_path / "system_logs" / "marketstand_listings.log")

        assert lw.detect_branch_from_path(path) == "UNKNOWN"

    def test_static_prefixes_are_a_floor_not_a_ceiling(self, monkeypatch, tmp_path):
        """An unreadable tree falls back to the static list instead of UNKNOWN."""
        _point_at_tree(lw, monkeypatch, tmp_path)
        path = str(tmp_path / "system_logs" / "seedgo_audit.log")

        assert lw.detect_branch_from_path(path) == "SEEDGO"


# ---------------------------------------------------------------------------
# Tests -- path classification is separator-agnostic (Windows CI, 70a10016)
# ---------------------------------------------------------------------------


class TestLogPathClassificationOnBothPlatforms:
    """`_should_process` classified paths with `"/logs/" in file_path`, so every
    Windows path — `...\\aipass\\hooks\\logs\\edit_gate.log` — fell through to
    "foreign" and was dropped. Four tests went red on the first honest Windows
    CI run (devpulse, 70a10016, 2026-08-18).

    A separator string test cannot be fixed by normalising on one platform and
    hoping; the classifier takes a PurePath, so these cases prove BOTH flavours
    from either runner.
    """

    def test_windows_branch_log_is_a_branch_log(self):
        """The exact path shape Windows CI reported."""
        from pathlib import PureWindowsPath

        path = PureWindowsPath(r"C:\p\AIPass\src\aipass\hooks\logs\edit_gate.log")
        assert lw.classify_log_path(path) == "branch"

    def test_posix_branch_log_is_a_branch_log(self):
        """The same answer from the other separator."""
        from pathlib import PurePosixPath

        path = PurePosixPath("/p/AIPass/src/aipass/hooks/logs/edit_gate.log")
        assert lw.classify_log_path(path) == "branch"

    def test_windows_system_log_is_a_system_log(self):
        """system_logs/ is recognised through backslashes too."""
        from pathlib import PureWindowsPath

        path = PureWindowsPath(r"C:\p\AIPass\system_logs\telegram-bot-api.log")
        assert lw.classify_log_path(path) == "system"

    def test_posix_system_log_is_a_system_log(self):
        """Same, forward slashes."""
        from pathlib import PurePosixPath

        assert lw.classify_log_path(PurePosixPath("/p/system_logs/x.log")) == "system"

    def test_unrelated_path_is_foreign_on_both(self):
        """A log outside both trees stays foreign, either separator."""
        from pathlib import PureWindowsPath

        assert lw.classify_log_path(PureWindowsPath(r"C:\tmp\random\output.log")) == "foreign"
        assert lw.classify_log_path(_SYNTHETIC_ELSEWHERE / "random" / "output.log") == "foreign"

    def test_aipass_without_a_logs_dir_is_not_a_branch_log(self):
        """Both components are required, not either."""
        from pathlib import PureWindowsPath

        path = PureWindowsPath(r"C:\p\src\aipass\drone\core.log")
        assert lw.classify_log_path(path) == "foreign"
