# =================== AIPass ====================
# Name: test_monitoring_filters.py
# Description: Unit tests for monitoring_filters.py
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-10-21
# =============================================

"""Tests for apps/handlers/monitoring/monitoring_filters.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the HIGHLIGHT_PATTERNS entries beyond those the get_priority() tests sample
# seedgo: no-test-needed(dead_code) — EVENT_TYPES and DEFAULT_EVENT_TYPES, which no product module reads

from pathlib import Path

from aipass.prax.apps.handlers.monitoring.monitoring_filters import (
    apply_content_filter,
    filter_log_content,
    get_content_filter,
    get_priority,
    should_monitor,
)


class TestShouldMonitorSandboxes:
    """should_monitor(path, root) is False below a dropbox or an .archive under root."""

    def test_a_dropbox_and_an_archive_are_not_monitored_and_the_live_file_is(self, tmp_path):
        root = tmp_path / "eco"
        branch = root / "branch"

        assert should_monitor(branch / "dropbox" / "handed.py", root) is False
        assert should_monitor(branch / ".archive" / "old.py", root) is False
        assert should_monitor(branch / "apps" / "live.py", root) is True

    def test_a_root_inside_a_directory_named_dropbox_still_monitors_its_own_file(self, tmp_path):
        """Compared below the root, never on the whole path; its proof is the whole-path mutant."""
        root = tmp_path / "dropbox" / "eco"

        assert should_monitor(root / "branch" / "apps" / "live.py", root) is True

    def test_a_path_outside_the_root_is_judged_as_before(self, tmp_path):
        assert should_monitor(tmp_path / "elsewhere" / "dropbox" / "module.py", tmp_path / "eco") is True


class TestShouldMonitor:
    """Tests for should_monitor(path)."""

    def test_python_file_monitored(self, tmp_path):
        """Python .py files should always be monitored."""
        assert should_monitor(tmp_path / "project" / "module.py") is True

    def test_pycache_ignored(self, tmp_path):
        """__pycache__ directories should be ignored."""
        assert should_monitor(tmp_path / "project" / "__pycache__" / "module.cpython-311.pyc") is False

    def test_venv_ignored(self, tmp_path):
        """.venv directories should be ignored (non-ALWAYS files)."""
        # A .cfg file, because an ALWAYS pattern would win over IGNORE.
        assert should_monitor(tmp_path / "project" / ".venv" / "pyvenv.cfg") is False

    def test_git_ignored(self, tmp_path):
        """.git directory should be ignored."""
        assert should_monitor(tmp_path / "project" / ".git" / "objects" / "ab" / "1234") is False

    def test_system_logs_ignored(self, tmp_path):
        """system_logs directory should be ignored."""
        assert should_monitor(tmp_path / "project" / "system_logs" / "prax.log") is False

    def test_dot_local_directory_ignored(self, tmp_path):
        """.local directory should be ignored (exact part match)."""
        assert should_monitor(tmp_path / ".local" / "share" / "data.txt") is False

    def test_ai_mail_local_not_ignored(self, tmp_path):
        """.ai_mail.local should NOT be caught by .local ignore rule."""
        result = should_monitor(tmp_path / "project" / ".ai_mail.local" / "inbox.ai_mail.json")
        assert result is True

    def test_always_overrides_ignore_py_in_cache(self, tmp_path):
        """ALWAYS patterns override IGNORE — .py in .cache should be monitored."""
        assert should_monitor(tmp_path / ".cache" / "script.py") is True

    def test_claude_json_backup_early_exit(self, tmp_path):
        """.claude.json.backup should be rejected via early exit."""
        assert should_monitor(tmp_path / "project" / ".claude.json.backup") is False

    def test_claude_json_tmp_early_exit(self, tmp_path):
        """.claude.json.tmp should be rejected via early exit."""
        assert should_monitor(tmp_path / "project" / ".claude.json.tmp") is False

    def test_id_json_always_monitored(self, tmp_path):
        """*.id.json files should always be monitored (ALWAYS pattern)."""
        assert should_monitor(tmp_path / "project" / "FLOW.id.json") is True

    def test_readme_always_monitored(self, tmp_path):
        """README.md should always be monitored (ALWAYS pattern)."""
        assert should_monitor(tmp_path / "project" / "README.md") is True

    def test_log_files_ignored(self, tmp_path):
        """*.log files should be ignored (IGNORE pattern)."""
        assert should_monitor(tmp_path / "project" / "output.log") is False

    def test_templates_always_monitored(self, tmp_path):
        """Paths containing templates/ should always be monitored."""
        assert should_monitor(tmp_path / "project" / "templates" / "base.html") is True

    def test_nested_templates_always_monitored(self, tmp_path):
        """Paths under */templates/** should always be monitored."""
        assert should_monitor(tmp_path / "spawn" / "templates" / "builder" / "conftest.py") is True

    def test_regular_txt_file_monitored_by_default(self, tmp_path):
        """Files not matching any pattern should be monitored (inclusive default)."""
        assert should_monitor(tmp_path / "project" / "notes.txt") is True

    def test_zip_file_ignored(self, tmp_path):
        """Archive files like *.zip should be ignored."""
        assert should_monitor(tmp_path / "project" / "archive.zip") is False


class TestGetPriority:
    """Tests for get_priority(path, event_type)."""

    def test_id_json_is_critical(self, tmp_path):
        """*.id.json files should have critical priority."""

        result = get_priority(tmp_path / "FLOW.id.json", "modified")
        assert result == "critical"

    def test_claude_md_is_critical(self, tmp_path):
        """CLAUDE.md should have critical priority."""

        result = get_priority(tmp_path / "CLAUDE.md", "modified")
        assert result == "critical"

    def test_agents_md_is_critical(self, tmp_path):
        """AGENTS.md carries the same instructions, so the same priority."""

        result = get_priority(tmp_path / "AGENTS.md", "modified")
        assert result == "critical"

    def test_py_deletion_is_high(self, tmp_path):
        """Python file deletion should be high priority."""

        result = get_priority(tmp_path / "important.py", "deletion")
        assert result == "high"

    def test_py_creation_is_high(self, tmp_path):
        """Python file creation should be high priority."""

        result = get_priority(tmp_path / "new_module.py", "creation")
        assert result == "high"

    def test_local_json_is_medium(self, tmp_path):
        """*.local.json files should have medium priority."""

        result = get_priority(tmp_path / "session.local.json", "modified")
        assert result == "medium"

    def test_random_txt_is_low(self, tmp_path):
        """Unmatched files should default to low priority."""

        result = get_priority(tmp_path / "random.txt", "modified")
        assert result == "low"

    def test_py_modification_is_medium(self, tmp_path):
        """Python file modification (not creation/deletion) should be medium."""

        result = get_priority(tmp_path / "utils.py", "modification")
        assert result == "medium"


class TestGetContentFilter:
    """Tests for get_content_filter(path)."""

    def test_log_file_returns_errors_only(self):
        """*.log files should return errors_only filter config."""

        result = get_content_filter(Path("system.log"))
        assert result is not None
        assert result["filter_mode"] == "errors_only"
        assert "ERROR" in result["show_patterns"]

    def test_py_file_returns_none(self):
        """Python files should have no content filter."""

        result = get_content_filter(Path("module.py"))
        assert result is None

    def test_data_json_returns_structure_only(self):
        """*_data.json files should return structure_only filter."""

        result = get_content_filter(Path("user_data.json"))
        assert result is not None
        assert result["filter_mode"] == "structure_only"

    def test_registry_json_returns_keys_only(self):
        """*_registry.json files should return keys_only filter."""

        result = get_content_filter(Path("AIPASS_REGISTRY.json"))
        assert result is not None
        assert result["filter_mode"] == "keys_only"


class TestFilterLogContent:
    """Tests for filter_log_content(content, ...)."""

    def test_error_lines_pass_errors_only(self):
        """ERROR lines should pass through errors_only filtering."""

        content = "ERROR: something broke"
        result = filter_log_content(content, show_errors=True, show_warnings=False, show_info=False)
        assert result == "ERROR: something broke"

    def test_info_lines_blocked_by_default(self):
        """INFO lines should be blocked when show_info is False (default)."""

        content = "INFO: routine message"
        result = filter_log_content(content, show_errors=True, show_warnings=True, show_info=False)
        assert result is None

    def test_warning_lines_pass_by_default(self):
        """WARNING lines should pass through with default settings."""

        content = "WARNING: disk space low"
        result = filter_log_content(content)
        assert result == "WARNING: disk space low"

    def test_multiline_filtering(self):
        """Multi-line content should filter each line independently."""

        content = "INFO: starting up\nERROR: connection failed\nINFO: retrying\nWARNING: timeout"
        result = filter_log_content(content, show_errors=True, show_warnings=True, show_info=False)
        assert result == "ERROR: connection failed\nWARNING: timeout"

    def test_empty_content_returns_none(self):
        """Empty content should return None."""

        result = filter_log_content("")
        assert result is None

    def test_all_filtered_returns_none(self):
        """Content with no matching lines should return None."""

        content = "INFO: step 1\nINFO: step 2\nDEBUG: details"
        result = filter_log_content(content, show_errors=True, show_warnings=True, show_info=False)
        assert result is None

    def test_critical_passes_with_errors(self):
        """CRITICAL lines should pass through when show_errors is True."""

        content = "CRITICAL: system failure"
        result = filter_log_content(content, show_errors=True, show_warnings=False, show_info=False)
        assert result == "CRITICAL: system failure"

    def test_info_passes_when_enabled(self):
        """INFO lines should pass through when show_info is True."""

        content = "INFO: all systems go"
        result = filter_log_content(content, show_errors=False, show_warnings=False, show_info=True)
        assert result == "INFO: all systems go"


class TestApplyContentFilter:
    """Tests for apply_content_filter(path, content, ...)."""

    def test_py_file_returns_original(self):
        """Python files have no filter -- content should be returned unchanged."""

        content = "def hello():\n    print('world')"
        result = apply_content_filter(Path("module.py"), content)
        assert result == content

    def test_log_file_filters_errors(self):
        """Log files should apply errors_only filter."""

        content = "INFO: booting\nERROR: disk full\nINFO: shutting down"
        result = apply_content_filter(Path("app.log"), content)
        assert result == "ERROR: disk full"

    def test_log_file_all_info_returns_none(self):
        """Log files with only INFO lines should return None after filtering."""

        content = "INFO: step 1\nINFO: step 2"
        result = apply_content_filter(Path("system.log"), content)
        assert result is None
