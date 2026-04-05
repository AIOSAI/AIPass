# =================== AIPass ====================
# Name: test_creator.py
# Description: Tests for creator module orchestration layer
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""
Tests for modules/creator.py — thin orchestration layer.

Covers: handle_command (routing, introspection, --help), create_skill
(delegation to handler, Rich output, trigger firing, json logging),
print_introspection.
"""

from unittest.mock import MagicMock, patch

from skills.apps.modules.creator import create_skill, handle_command, print_introspection


# ===================================================================
# 1. handle_command — command routing
# ===================================================================


class TestHandleCommand:
    """Tests for handle_command — CLI routing logic."""

    def test_no_args_shows_introspection(self, capsys):
        result = handle_command("create", [])
        assert result is True
        output = capsys.readouterr().out
        assert "creator Module" in output

    def test_help_flag_shows_introspection(self, capsys):
        result = handle_command("create", ["--help"])
        assert result is True
        output = capsys.readouterr().out
        assert "creator Module" in output

    def test_create_with_valid_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = handle_command("create", ["test-skill"])
        assert result is True

    def test_create_with_handler_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = handle_command("create", ["test-hnd", "--with-handler"])
        assert result is True
        skill_path = tmp_path / ".aipass" / "skills" / "test-hnd"
        assert (skill_path / "handler.py").exists()

    def test_create_with_full_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = handle_command("create", ["test-full", "--full"])
        assert result is True
        skill_path = tmp_path / ".aipass" / "skills" / "test-full"
        assert (skill_path / "apps").is_dir()

    def test_create_invalid_name_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = handle_command("create", ["Bad Name!"])
        assert result is False

    def test_unknown_command_returns_false(self):
        result = handle_command("nonexistent", ["arg"])
        assert result is False


# ===================================================================
# 2. create_skill — module-level wrapper
# ===================================================================


class TestCreateSkillModule:
    """Tests for create_skill module wrapper — delegates + renders output."""

    def test_success_prints_output(self, tmp_path, capsys):
        result = create_skill("print-test", template_type="markdown_only", target_dir=tmp_path)
        assert result["success"] is True
        output = capsys.readouterr().out
        assert "print-test" in output
        assert "markdown_only" in output

    def test_success_returns_handler_result(self, tmp_path):
        result = create_skill("result-test", template_type="markdown_only", target_dir=tmp_path)
        assert result["success"] is True
        assert result["path"] is not None
        assert isinstance(result["files"], list)
        assert result["error"] is None

    def test_failure_does_not_print_success_output(self, capsys):
        result = create_skill("", template_type="markdown_only")
        assert result["success"] is False
        output = capsys.readouterr().out
        assert "Created skill" not in output

    def test_trigger_fired_on_success(self, tmp_path):
        mock_trigger = MagicMock()
        with patch("skills.apps.modules.creator.trigger", mock_trigger):
            create_skill("trigger-test", template_type="markdown_only", target_dir=tmp_path)
        mock_trigger.fire.assert_called_once()
        call_args = mock_trigger.fire.call_args
        assert call_args[0][0] == "skill_created"
        assert call_args[1]["name"] == "trigger-test"

    def test_trigger_not_fired_on_failure(self):
        mock_trigger = MagicMock()
        with patch("skills.apps.modules.creator.trigger", mock_trigger):
            create_skill("", template_type="markdown_only")
        mock_trigger.fire.assert_not_called()

    def test_trigger_none_does_not_crash(self, tmp_path):
        """When trigger is None (import failed), create_skill still works."""
        with patch("skills.apps.modules.creator.trigger", None):
            result = create_skill("no-trigger", template_type="markdown_only", target_dir=tmp_path)
        assert result["success"] is True

    @patch("skills.apps.modules.creator.json_handler")
    def test_json_log_on_success(self, mock_jh, tmp_path):
        create_skill("jlog-test", template_type="markdown_only", target_dir=tmp_path)
        mock_jh.log_operation.assert_called_once()
        call_args = mock_jh.log_operation.call_args
        assert call_args[0][0] == "skill_created"
        assert call_args[0][1]["success"] is True

    @patch("skills.apps.modules.creator.json_handler")
    def test_json_log_on_failure(self, mock_jh):
        create_skill("", template_type="markdown_only")
        mock_jh.log_operation.assert_called_once()
        call_args = mock_jh.log_operation.call_args
        assert call_args[0][1]["success"] is False

    def test_files_listed_in_output(self, tmp_path, capsys):
        create_skill("files-test", template_type="with_handler", target_dir=tmp_path)
        output = capsys.readouterr().out
        assert "SKILL.md" in output
        assert "handler.py" in output


# ===================================================================
# 3. print_introspection — module info display
# ===================================================================


class TestPrintIntrospection:
    """Tests for print_introspection — module self-description."""

    def test_prints_module_name(self, capsys):
        print_introspection()
        output = capsys.readouterr().out
        assert "creator Module" in output

    def test_prints_description(self, capsys):
        print_introspection()
        output = capsys.readouterr().out
        assert "Scaffold" in output

    def test_prints_connected_handlers(self, capsys):
        print_introspection()
        output = capsys.readouterr().out
        assert "creator_handler.py" in output
        assert "template.py" in output
