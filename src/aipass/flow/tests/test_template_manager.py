# =================== AIPass ====================
# Name: test_template_manager.py
# Description: Unit tests for apps/modules/template_manager.py
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for the template_manager module -- prefix suggestion, command routing."""

import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Module-level patch targets (patch where used, not where defined)
# ---------------------------------------------------------------------------

_MOD = "aipass.flow.apps.modules.template_manager"


# ---------------------------------------------------------------------------
# _suggest_prefix pure-function tests
# ---------------------------------------------------------------------------


class TestSuggestPrefix:
    """Verify _suggest_prefix produces correct prefix strings."""

    def test_testing_gives_tplan(self):
        """'testing' -> 'TPLAN'."""
        from aipass.flow.apps.modules.template_manager import _suggest_prefix

        assert _suggest_prefix("testing") == "TPLAN"

    def test_skills_plans_gives_splan(self):
        """'skills_plans' -> 'SPLAN' (first word before underscore)."""
        from aipass.flow.apps.modules.template_manager import _suggest_prefix

        assert _suggest_prefix("skills_plans") == "SPLAN"

    def test_dev_plans_gives_dplan(self):
        """'dev_plans' -> 'DPLAN'."""
        from aipass.flow.apps.modules.template_manager import _suggest_prefix

        assert _suggest_prefix("dev_plans") == "DPLAN"

    def test_empty_string_returns_xplan(self):
        """Empty string edge case should return 'XPLAN' fallback."""
        from aipass.flow.apps.modules.template_manager import _suggest_prefix

        assert _suggest_prefix("") == "XPLAN"

    def test_single_char_dir(self):
        """Single character directory name should work."""
        from aipass.flow.apps.modules.template_manager import _suggest_prefix

        assert _suggest_prefix("a") == "APLAN"

    def test_uppercase_input(self):
        """Uppercase input first letter stays uppercase."""
        from aipass.flow.apps.modules.template_manager import _suggest_prefix

        assert _suggest_prefix("Flow") == "FPLAN"


# ---------------------------------------------------------------------------
# handle_command routing tests
# ---------------------------------------------------------------------------


class TestHandleCommandRouting:
    """Verify handle_command routes to the correct function for each input."""

    def test_no_args_calls_introspection(self):
        """No args should call print_introspection and return True."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("templates", [])

            mock_intro.assert_called_once()
            assert result is True

    def test_any_command_no_args_calls_introspection(self):
        """Even non-templates commands with no args trigger introspection."""
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("register", [])

            mock_intro.assert_called_once()
            assert result is True

    @pytest.mark.parametrize("help_flag", ["--help", "-h", "help"])
    def test_templates_help_flags(self, help_flag: str):
        """templates with help flags should call print_help."""
        with patch(f"{_MOD}.print_help") as mock_help:
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("templates", [help_flag])

            mock_help.assert_called_once()
            assert result is True

    def test_templates_list_loads_registry_and_displays(self):
        """'templates list' should load registry and display types."""
        mock_registry = {"types": {"flow_plans": {"prefix": "FPLAN"}}}

        with patch(f"{_MOD}.load_registry", return_value=mock_registry) as mock_lr, \
             patch(f"{_MOD}._display_registered_types") as mock_display:
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("templates", ["list"])

            mock_lr.assert_called_once()
            mock_display.assert_called_once_with(mock_registry)
            assert result is True

    # ---- register command ----

    def test_register_no_args_shows_error(self):
        """'register' with insufficient args should show usage error."""
        with patch(f"{_MOD}.error") as mock_error, \
             patch(f"{_MOD}.console"):
            from aipass.flow.apps.modules.template_manager import handle_command

            # Note: empty args triggers introspection gate first,
            # so we pass one arg to get past introspection but still < 2
            result = handle_command("register", ["testing"])

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("Usage:")
            assert result is True

    def test_register_valid_calls_add_type(self):
        """'register testing TPLAN' should call add_type."""
        with patch(f"{_MOD}.add_type", return_value=True) as mock_add, \
             patch(f"{_MOD}.success") as mock_success, \
             patch(f"{_MOD}.console"), \
             patch(f"{_MOD}.json_handler"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("register", ["testing", "TPLAN"])

            mock_add.assert_called_once_with("testing", "TPLAN")
            mock_success.assert_called_once()
            assert result is True

    def test_register_add_type_failure(self):
        """add_type returning False should show error message."""
        with patch(f"{_MOD}.add_type", return_value=False) as mock_add, \
             patch(f"{_MOD}.error") as mock_error, \
             patch(f"{_MOD}.console"), \
             patch(f"{_MOD}.json_handler"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("register", ["testing", "TPLAN"])

            mock_add.assert_called_once_with("testing", "TPLAN")
            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("Failed")
            assert result is True

    def test_register_invalid_prefix_not_uppercase(self):
        """Prefix that is not uppercase should be rejected."""
        with patch(f"{_MOD}.error") as mock_error, \
             patch(f"{_MOD}.console"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("register", ["testing", "bad"])

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("PREFIX")
            assert result is True

    def test_register_invalid_prefix_no_plan_suffix(self):
        """Prefix that doesn't end with PLAN should be rejected."""
        with patch(f"{_MOD}.error") as mock_error, \
             patch(f"{_MOD}.console"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("register", ["testing", "TFIX"])

            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("PREFIX")
            assert result is True

    # ---- unregister command ----

    def test_unregister_no_args_shows_error(self):
        """'unregister' with no dir arg should show usage error.

        Note: empty args hits the introspection gate, so we test that
        unregister with at least one arg but no dir is handled.  Actually,
        looking at the source, unregister checks ``if not args`` *after*
        the introspection gate already caught truly empty args.  So we
        need a different approach: the introspection gate fires when
        args is empty for ANY command.  unregister's own ``if not args``
        is unreachable via handle_command.  Test via route that reaches it.
        """
        # The introspection gate catches empty args before we ever reach
        # the unregister block, so args=[] triggers introspection, not error.
        # We verify that behavior here -- this is correct by design.
        with patch(f"{_MOD}.print_introspection") as mock_intro:
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("unregister", [])

            mock_intro.assert_called_once()
            assert result is True

    def test_unregister_valid_calls_remove_type(self):
        """'unregister testing' should call remove_type."""
        with patch(f"{_MOD}.remove_type", return_value=True) as mock_rm, \
             patch(f"{_MOD}.success") as mock_success, \
             patch(f"{_MOD}.console"), \
             patch(f"{_MOD}.json_handler"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("unregister", ["testing"])

            mock_rm.assert_called_once_with("testing")
            mock_success.assert_called_once()
            assert result is True

    def test_unregister_failure_shows_error(self):
        """remove_type returning False should show error."""
        with patch(f"{_MOD}.remove_type", return_value=False) as mock_rm, \
             patch(f"{_MOD}.error") as mock_error, \
             patch(f"{_MOD}.console"), \
             patch(f"{_MOD}.json_handler"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("unregister", ["testing"])

            mock_rm.assert_called_once_with("testing")
            mock_error.assert_called_once()
            assert mock_error.call_args[0][0].startswith("Failed")
            assert result is True

    # ---- scan command ----

    def test_scan_no_unregistered_dirs(self):
        """scan with all dirs registered should show success message."""
        with patch(f"{_MOD}.scan_unregistered", return_value=[]) as mock_scan, \
             patch(f"{_MOD}.console") as mock_console, \
             patch(f"{_MOD}.json_handler"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("scan", ["run"])

            mock_scan.assert_called_once()
            # Should print "All template directories are registered"
            print_calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("registered" in c for c in print_calls)
            assert result is True

    def test_scan_with_unregistered_dirs(self):
        """scan finding unregistered dirs should list them with suggestions."""
        unregistered = [
            {"dir_name": "testing", "template_count": 2},
            {"dir_name": "skills_plans", "template_count": 1},
        ]

        with patch(f"{_MOD}.scan_unregistered", return_value=unregistered) as mock_scan, \
             patch(f"{_MOD}.warning") as mock_warn, \
             patch(f"{_MOD}.console") as mock_console, \
             patch(f"{_MOD}.json_handler"):
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("scan", ["run"])

            mock_scan.assert_called_once()
            mock_warn.assert_called_once()
            assert "2" in mock_warn.call_args[0][0]  # "Found 2 unregistered..."
            # Should print suggested registration commands
            print_calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("TPLAN" in c for c in print_calls)
            assert any("SPLAN" in c for c in print_calls)
            assert result is True

    # ---- unknown command ----

    def test_unknown_command_returns_false(self):
        """Unrecognized command should return False."""
        from aipass.flow.apps.modules.template_manager import handle_command

        result = handle_command("frobnicate", ["something"])

        assert result is False

    def test_json_handler_called_on_templates_list(self):
        """json_handler.log_operation should be called for templates command."""
        mock_registry = {"types": {}}

        with patch(f"{_MOD}.load_registry", return_value=mock_registry), \
             patch(f"{_MOD}._display_registered_types"), \
             patch(f"{_MOD}.json_handler") as mock_jh:
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("templates", ["list"])

            assert result is True  # Command was handled
            mock_jh.log_operation.assert_called_once_with(
                "templates_listed",
                {"command": "templates", "args": ["list"]},
            )

    def test_json_handler_called_on_scan(self):
        """json_handler.log_operation should be called for scan command."""
        with patch(f"{_MOD}.scan_unregistered", return_value=[]), \
             patch(f"{_MOD}.console"), \
             patch(f"{_MOD}.json_handler") as mock_jh:
            from aipass.flow.apps.modules.template_manager import handle_command

            result = handle_command("scan", ["run"])

            assert result is True  # Command was handled
            mock_jh.log_operation.assert_called_once_with(
                "templates_scanned",
                {"command": "scan"},
            )
