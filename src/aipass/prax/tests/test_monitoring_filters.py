# =================== AIPass ====================
# Name: test_monitoring_filters.py
# Description: Unit tests for monitoring_filters.py
# Version: 1.2.0
# Created: 2026-03-24
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/monitoring/monitoring_filters.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the HIGHLIGHT_PATTERNS entries beyond those the get_priority() tests sample

from aipass.prax.apps.handlers.monitoring.monitoring_filters import (
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


class TestShortIgnoreNamesMatchWholeSegments:
    """lib/bin/env/build/dist/install hide only a folder of that exact name, never a name containing them."""

    def test_a_name_containing_lib_or_env_is_monitored(self, tmp_path):
        assert should_monitor(tmp_path / "robin" / "notes.txt") is True
        assert should_monitor(tmp_path / "seven" / "environment" / "notes.txt") is True
        assert should_monitor(tmp_path / "rebuild" / "distance" / "notes.txt") is True

    def test_the_exact_folder_is_still_ignored(self, tmp_path):
        for folder in ("lib", "bin", "env", "build", "dist", "install"):
            assert should_monitor(tmp_path / folder / "notes.txt") is False, folder
