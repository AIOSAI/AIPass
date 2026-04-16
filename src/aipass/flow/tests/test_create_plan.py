"""Tests for create_plan module -- handle_command routing."""

from unittest.mock import patch


# ─── Patch targets ───────────────────────────────────────
_MOD = "aipass.flow.apps.modules.create_plan"


# ─── Helpers ─────────────────────────────────────────────


def _import_handle_command():
    """Import handle_command inside each test so autouse mocks are active."""
    from aipass.flow.apps.modules.create_plan import handle_command

    return handle_command


# ═══════════════════════════════════════════════════════════
# 1. Command != "create" -> returns False
# ═══════════════════════════════════════════════════════════


class TestCommandRouting:
    def test_wrong_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("delete", []) is False

    def test_unrelated_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("close", ["42"]) is False

    def test_empty_command_returns_false(self):
        handle_command = _import_handle_command()
        assert handle_command("", []) is False


# ═══════════════════════════════════════════════════════════
# 2. command == "create" with no args -> introspection
# ═══════════════════════════════════════════════════════════


class TestIntrospection:
    @patch(f"{_MOD}.print_introspection")
    def test_no_args_calls_introspection(self, mock_introspection):
        handle_command = _import_handle_command()
        result = handle_command("create", [])
        assert result is True
        mock_introspection.assert_called_once()

    @patch(f"{_MOD}.print_introspection")
    def test_no_args_does_not_parse(self, mock_introspection):
        """Introspection should not attempt to parse arguments."""
        with patch(f"{_MOD}.parse_create_plan_args") as mock_parse:
            handle_command = _import_handle_command()
            result = handle_command("create", [])
            assert result is True  # Command was handled
            mock_parse.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 3. command == "create" with --help -> help
# ═══════════════════════════════════════════════════════════


class TestHelp:
    @patch(f"{_MOD}.print_help")
    def test_help_flag(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("create", ["--help"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_h_flag(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("create", ["-h"])
        assert result is True
        mock_help.assert_called_once()

    @patch(f"{_MOD}.print_help")
    def test_help_word(self, mock_help):
        handle_command = _import_handle_command()
        result = handle_command("create", ["help"])
        assert result is True
        mock_help.assert_called_once()


# ═══════════════════════════════════════════════════════════
# 4. command == "create" with valid args -> calls create_plan
# ═══════════════════════════════════════════════════════════


class TestValidArgs:
    @patch(f"{_MOD}.display_plan_result", return_value="[green]OK[/green]")
    @patch(f"{_MOD}.create_plan", return_value=(True, 1, ".", "default", ""))
    @patch(f"{_MOD}.get_plan_type", return_value={"prefix": "FPLAN", "digits": 4, "default_template": "default"})
    @patch(f"{_MOD}.parse_create_plan_args", return_value=(".", "My Plan", "flow_plans"))
    def test_valid_args_calls_parse(self, mock_parse, mock_get_type, mock_create, mock_display):
        handle_command = _import_handle_command()
        result = handle_command("create", [".", "My Plan"])
        assert result is True
        mock_parse.assert_called_once_with([".", "My Plan"])

    @patch(f"{_MOD}.display_plan_result", return_value="[green]OK[/green]")
    @patch(f"{_MOD}.create_plan", return_value=(True, 1, ".", "default", ""))
    @patch(f"{_MOD}.get_plan_type", return_value={"prefix": "FPLAN", "digits": 4, "default_template": "default"})
    @patch(f"{_MOD}.parse_create_plan_args", return_value=(".", "My Plan", "flow_plans"))
    def test_valid_args_calls_create_plan(self, mock_parse, mock_get_type, mock_create, mock_display):
        handle_command = _import_handle_command()
        result = handle_command("create", [".", "My Plan"])
        assert result is True  # Command was handled
        mock_create.assert_called_once_with(
            ".",
            "My Plan",
            plan_type_key="flow_plans",
            plan_type_config={"prefix": "FPLAN", "digits": 4, "default_template": "default"},
        )

    @patch(f"{_MOD}.display_plan_result", return_value="[green]OK[/green]")
    @patch(f"{_MOD}.create_plan", return_value=(True, 1, ".", "default", ""))
    @patch(f"{_MOD}.get_plan_type", return_value={"prefix": "FPLAN", "digits": 4, "default_template": "default"})
    @patch(f"{_MOD}.parse_create_plan_args", return_value=(".", "My Plan", "flow_plans"))
    def test_valid_args_calls_display_result(self, mock_parse, mock_get_type, mock_create, mock_display):
        handle_command = _import_handle_command()
        result = handle_command("create", [".", "My Plan"])
        assert result is True  # Command was handled
        mock_display.assert_called_once_with(
            True,
            1,
            ".",
            "default",
            "",
            prefix="FPLAN",
            digits=4,
        )

    @patch(f"{_MOD}.display_plan_result", return_value="[green]OK[/green]")
    @patch(f"{_MOD}.create_plan", return_value=(True, 5, ".", "default", ""))
    @patch(f"{_MOD}.get_plan_type", return_value={"prefix": "DPLAN", "digits": 4, "default_template": "default"})
    @patch(f"{_MOD}.parse_create_plan_args", return_value=(".", "My Plan", "dev_plans"))
    def test_dplan_type_passes_through(self, mock_parse, mock_get_type, mock_create, mock_display):
        """When args include 'dplan', parse_create_plan_args returns dev_plans type key."""
        handle_command = _import_handle_command()
        result = handle_command("create", [".", "My Plan", "dplan"])
        assert result is True
        mock_create.assert_called_once_with(
            ".",
            "My Plan",
            plan_type_key="dev_plans",
            plan_type_config={"prefix": "DPLAN", "digits": 4, "default_template": "default"},
        )


# ═══════════════════════════════════════════════════════════
# 5. Invalid plan type -> error displayed, returns True
# ═══════════════════════════════════════════════════════════


class TestInvalidPlanType:
    @patch(f"{_MOD}.parse_create_plan_args", return_value=(".", "My Plan", "bad_type"))
    @patch(f"{_MOD}.get_plan_type", side_effect=ValueError("Unknown plan type 'bad_type'"))
    def test_invalid_type_returns_true(self, mock_get_type, mock_parse):
        """Invalid plan type is an error but command was still handled."""
        handle_command = _import_handle_command()
        result = handle_command("create", [".", "My Plan", "bad_type"])
        assert result is True

    @patch(f"{_MOD}.cli_error")
    @patch(f"{_MOD}.parse_create_plan_args", return_value=(".", "My Plan", "bad_type"))
    @patch(f"{_MOD}.get_plan_type", side_effect=ValueError("Unknown plan type 'bad_type'"))
    def test_invalid_type_calls_error(self, mock_get_type, mock_parse, mock_cli_error):
        handle_command = _import_handle_command()
        result = handle_command("create", [".", "My Plan", "bad_type"])
        assert result is True  # Command was handled (error displayed)
        mock_cli_error.assert_called_once_with("Unknown plan type 'bad_type'")


# ═══════════════════════════════════════════════════════════
# 6. json_handler.log_operation is called on valid commands
# ═══════════════════════════════════════════════════════════


class TestOperationLogging:
    @patch(f"{_MOD}.display_plan_result", return_value="[green]OK[/green]")
    @patch(f"{_MOD}.create_plan", return_value=(True, 1, ".", "default", ""))
    @patch(f"{_MOD}.get_plan_type", return_value={"prefix": "FPLAN", "digits": 4, "default_template": "default"})
    @patch(f"{_MOD}.parse_create_plan_args", return_value=(".", "My Plan", "flow_plans"))
    @patch(f"{_MOD}.json_handler")
    def test_logs_operation(self, mock_jh, mock_parse, mock_get_type, mock_create, mock_display):
        handle_command = _import_handle_command()
        result = handle_command("create", [".", "My Plan"])
        assert result is True  # Command was handled
        mock_jh.log_operation.assert_called_once_with(
            "plan_created",
            {"command": "create", "args": [".", "My Plan"]},
        )
