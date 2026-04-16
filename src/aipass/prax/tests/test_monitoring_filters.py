# =================== AIPass ====================
# Name: test_monitoring_filters.py
# Description: Unit tests for monitoring_filters.py
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Unit tests for monitoring filter patterns and helper functions.

Tests pure functions: should_monitor, get_priority, get_content_filter,
filter_log_content, and apply_content_filter.
"""

from pathlib import Path


# =============================================
# should_monitor TESTS
# =============================================


class TestShouldMonitor:
    """Tests for should_monitor(path)."""

    def test_python_file_monitored(self):
        """Python .py files should always be monitored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/module.py")) is True

    def test_pycache_ignored(self):
        """__pycache__ directories should be ignored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/__pycache__/module.cpython-311.pyc")) is False

    def test_venv_ignored(self):
        """.venv directories should be ignored (non-ALWAYS files)."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        # Use a .cfg file that is not in ALWAYS patterns
        assert should_monitor(Path("/home/user/project/.venv/pyvenv.cfg")) is False

    def test_git_ignored(self):
        """.git directory should be ignored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/.git/objects/ab/1234")) is False

    def test_system_logs_ignored(self):
        """system_logs directory should be ignored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/system_logs/prax.log")) is False

    def test_dot_local_directory_ignored(self):
        """.local directory should be ignored (exact part match)."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/.local/share/data.txt")) is False

    def test_ai_mail_local_not_ignored(self):
        """.ai_mail.local should NOT be caught by .local ignore rule."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        # .ai_mail.local contains ".local" as a substring but is not the
        # ".local" directory — the part-only check should skip it.
        # The file itself is an .ai_mail.json which is in ALWAYS patterns.
        result = should_monitor(Path("/home/user/project/.ai_mail.local/inbox.ai_mail.json"))
        assert result is True

    def test_always_overrides_ignore_py_in_cache(self):
        """ALWAYS patterns override IGNORE — .py in .cache should be monitored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        # .cache is in IGNORE, but *.py is in ALWAYS (checked first)
        assert should_monitor(Path("/home/user/.cache/script.py")) is True

    def test_claude_json_backup_early_exit(self):
        """.claude.json.backup should be rejected via early exit."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/.claude.json.backup")) is False

    def test_claude_json_tmp_early_exit(self):
        """.claude.json.tmp should be rejected via early exit."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/.claude.json.tmp")) is False

    def test_id_json_always_monitored(self):
        """*.id.json files should always be monitored (ALWAYS pattern)."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/FLOW.id.json")) is True

    def test_readme_always_monitored(self):
        """README.md should always be monitored (ALWAYS pattern)."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/README.md")) is True

    def test_log_files_ignored(self):
        """*.log files should be ignored (IGNORE pattern)."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/output.log")) is False

    def test_templates_always_monitored(self):
        """Paths containing templates/ should always be monitored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/templates/base.html")) is True

    def test_nested_templates_always_monitored(self):
        """Paths under */templates/** should always be monitored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/spawn/templates/builder/conftest.py")) is True

    def test_regular_txt_file_monitored_by_default(self):
        """Files not matching any pattern should be monitored (inclusive default)."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/notes.txt")) is True

    def test_zip_file_ignored(self):
        """Archive files like *.zip should be ignored."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import should_monitor

        assert should_monitor(Path("/home/user/project/archive.zip")) is False


# =============================================
# get_priority TESTS
# =============================================


class TestGetPriority:
    """Tests for get_priority(path, event_type)."""

    def test_id_json_is_critical(self):
        """*.id.json files should have critical priority."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_priority

        result = get_priority(Path("/home/user/FLOW.id.json"), "modified")
        assert result == "critical"

    def test_claude_md_is_critical(self):
        """CLAUDE.md should have critical priority."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_priority

        result = get_priority(Path("/home/user/CLAUDE.md"), "modified")
        assert result == "critical"

    def test_py_deletion_is_high(self):
        """Python file deletion should be high priority."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_priority

        result = get_priority(Path("/home/user/important.py"), "deletion")
        assert result == "high"

    def test_py_creation_is_high(self):
        """Python file creation should be high priority."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_priority

        result = get_priority(Path("/home/user/new_module.py"), "creation")
        assert result == "high"

    def test_local_json_is_medium(self):
        """*.local.json files should have medium priority."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_priority

        result = get_priority(Path("/home/user/session.local.json"), "modified")
        assert result == "medium"

    def test_random_txt_is_low(self):
        """Unmatched files should default to low priority."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_priority

        result = get_priority(Path("/home/user/random.txt"), "modified")
        assert result == "low"

    def test_py_modification_is_medium(self):
        """Python file modification (not creation/deletion) should be medium."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_priority

        result = get_priority(Path("/home/user/utils.py"), "modification")
        assert result == "medium"


# =============================================
# get_content_filter TESTS
# =============================================


class TestGetContentFilter:
    """Tests for get_content_filter(path)."""

    def test_log_file_returns_errors_only(self):
        """*.log files should return errors_only filter config."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_content_filter

        result = get_content_filter(Path("system.log"))
        assert result is not None
        assert result["filter_mode"] == "errors_only"
        assert "ERROR" in result["show_patterns"]

    def test_py_file_returns_none(self):
        """Python files should have no content filter."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_content_filter

        result = get_content_filter(Path("module.py"))
        assert result is None

    def test_data_json_returns_structure_only(self):
        """*_data.json files should return structure_only filter."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_content_filter

        result = get_content_filter(Path("user_data.json"))
        assert result is not None
        assert result["filter_mode"] == "structure_only"

    def test_registry_json_returns_keys_only(self):
        """*_registry.json files should return keys_only filter."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import get_content_filter

        result = get_content_filter(Path("AIPASS_REGISTRY.json"))
        assert result is not None
        assert result["filter_mode"] == "keys_only"


# =============================================
# filter_log_content TESTS
# =============================================


class TestFilterLogContent:
    """Tests for filter_log_content(content, ...)."""

    def test_error_lines_pass_errors_only(self):
        """ERROR lines should pass through errors_only filtering."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        content = "ERROR: something broke"
        result = filter_log_content(content, show_errors=True, show_warnings=False, show_info=False)
        assert result == "ERROR: something broke"

    def test_info_lines_blocked_by_default(self):
        """INFO lines should be blocked when show_info is False (default)."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        content = "INFO: routine message"
        result = filter_log_content(content, show_errors=True, show_warnings=True, show_info=False)
        assert result is None

    def test_warning_lines_pass_by_default(self):
        """WARNING lines should pass through with default settings."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        content = "WARNING: disk space low"
        result = filter_log_content(content)
        assert result == "WARNING: disk space low"

    def test_multiline_filtering(self):
        """Multi-line content should filter each line independently."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        content = "INFO: starting up\nERROR: connection failed\nINFO: retrying\nWARNING: timeout"
        result = filter_log_content(content, show_errors=True, show_warnings=True, show_info=False)
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 2
        assert "ERROR: connection failed" in lines
        assert "WARNING: timeout" in lines

    def test_empty_content_returns_none(self):
        """Empty content should return None."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        result = filter_log_content("")
        assert result is None

    def test_all_filtered_returns_none(self):
        """Content with no matching lines should return None."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        content = "INFO: step 1\nINFO: step 2\nDEBUG: details"
        result = filter_log_content(content, show_errors=True, show_warnings=True, show_info=False)
        assert result is None

    def test_critical_passes_with_errors(self):
        """CRITICAL lines should pass through when show_errors is True."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        content = "CRITICAL: system failure"
        result = filter_log_content(content, show_errors=True, show_warnings=False, show_info=False)
        assert result == "CRITICAL: system failure"

    def test_info_passes_when_enabled(self):
        """INFO lines should pass through when show_info is True."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import filter_log_content

        content = "INFO: all systems go"
        result = filter_log_content(content, show_errors=False, show_warnings=False, show_info=True)
        assert result == "INFO: all systems go"


# =============================================
# apply_content_filter TESTS
# =============================================


class TestApplyContentFilter:
    """Tests for apply_content_filter(path, content, ...)."""

    def test_py_file_returns_original(self):
        """Python files have no filter -- content should be returned unchanged."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import apply_content_filter

        content = "def hello():\n    print('world')"
        result = apply_content_filter(Path("module.py"), content)
        assert result == content

    def test_log_file_filters_errors(self):
        """Log files should apply errors_only filter."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import apply_content_filter

        content = "INFO: booting\nERROR: disk full\nINFO: shutting down"
        result = apply_content_filter(Path("app.log"), content)
        assert result is not None
        assert "ERROR: disk full" in result
        assert "INFO: booting" not in result

    def test_log_file_all_info_returns_none(self):
        """Log files with only INFO lines should return None after filtering."""
        from aipass.prax.apps.handlers.monitoring.monitoring_filters import apply_content_filter

        content = "INFO: step 1\nINFO: step 2"
        result = apply_content_filter(Path("system.log"), content)
        assert result is None
