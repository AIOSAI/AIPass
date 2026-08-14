# =================== AIPass ====================
# Name: test_integrations_manager.py
# Description: Tests for integrations_manager command handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""
Tests for integrations_manager.py -- handle_command, _run_list, _run_call,
print_introspection, print_help.

Existing test_integrations.py covers bridge, registry, fetch_contracts,
call_contract. This file covers the remaining uncovered functions.
"""

import pytest
from unittest.mock import patch, MagicMock

_IM = "aipass.api.apps.modules.integrations_manager"


# =============================================
# handle_command tests
# =============================================


class TestHandleCommand:
    """Tests for integrations_manager.handle_command()."""

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_wrong_command_returns_false(
        self,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
        _mock_console: MagicMock,
    ) -> None:
        """Non-integrations command returns False."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        result = handle_command("status", [])
        assert result is False

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_help_flag_returns_true(
        self,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
        _mock_console: MagicMock,
    ) -> None:
        """--help flag triggers print_help and returns True."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        result = handle_command("integrations", ["--help"])
        assert result is True

    @patch(f"{_IM}.json_handler")
    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_no_args_shows_introspection(
        self,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
        _mock_console: MagicMock,
        _mock_jh: MagicMock,
    ) -> None:
        """No args triggers introspection and returns True."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        result = handle_command("integrations", [])
        assert result is True

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_unknown_subcommand_exits(
        self,
        mock_error: MagicMock,
        _mock_header: MagicMock,
        _mock_console: MagicMock,
    ) -> None:
        """Unknown subcommand calls error() and raises SystemExit."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        with pytest.raises(SystemExit):
            handle_command("integrations", ["bogus"])
        mock_error.assert_called_once()

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    @patch(f"{_IM}.registry")
    @patch(f"{_IM}.list_contracts", return_value=[])
    @patch(f"{_IM}.get_contracts", return_value={"contracts": [], "count": 0, "success": True})
    def test_list_subcommand_exits(
        self,
        _mock_get: MagicMock,
        _mock_list: MagicMock,
        _mock_registry: MagicMock,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
        _mock_console: MagicMock,
    ) -> None:
        """list subcommand loads drivers and calls sys.exit."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        with pytest.raises(SystemExit) as exc_info:
            handle_command("integrations", ["list"])
        assert exc_info.value.code == 0

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_call_without_name_exits_1(
        self,
        mock_error: MagicMock,
        _mock_header: MagicMock,
        _mock_console: MagicMock,
    ) -> None:
        """call subcommand without contract name shows error and exits 1."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        with pytest.raises(SystemExit) as exc_info:
            handle_command("integrations", ["call"])
        assert exc_info.value.code == 1
        mock_error.assert_called_once()


# =============================================
# _run_list tests
# =============================================


class TestRunList:
    """Tests for integrations_manager._run_list()."""

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.get_contracts", return_value={"contracts": [], "count": 0, "success": True})
    @patch(f"{_IM}.list_contracts", return_value=[])
    def test_no_contracts(
        self,
        _mock_list: MagicMock,
        _mock_get: MagicMock,
        _mock_header: MagicMock,
        mock_console: MagicMock,
    ) -> None:
        """Empty contracts list prints 'No integrations configured.'."""
        from aipass.api.apps.modules.integrations_manager import _run_list

        result = _run_list()
        assert result == 0

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(
        f"{_IM}.get_contracts",
        return_value={"contracts": ["alpha", "beta"], "count": 2, "success": True},
    )
    @patch(f"{_IM}.list_contracts", return_value=["alpha", "beta"])
    def test_with_contracts(
        self,
        _mock_list: MagicMock,
        _mock_get: MagicMock,
        _mock_header: MagicMock,
        mock_console: MagicMock,
    ) -> None:
        """With contracts, prints each name and returns 0."""
        from aipass.api.apps.modules.integrations_manager import _run_list

        result = _run_list()
        assert result == 0
        # Each contract name is printed
        printed = [str(c) for c in mock_console.print.call_args_list]
        full_output = " ".join(printed)
        assert "alpha" in full_output
        assert "beta" in full_output


# =============================================
# _run_call tests
# =============================================


class TestRunCall:
    """Tests for integrations_manager._run_call()."""

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    @patch(f"{_IM}.resolve", return_value=None)
    def test_contract_not_found(
        self,
        _mock_resolve: MagicMock,
        mock_error: MagicMock,
        _mock_console: MagicMock,
    ) -> None:
        """Unresolved contract calls error() and returns 1."""
        from aipass.api.apps.modules.integrations_manager import _run_call

        result = _run_call("missing", [])
        assert result == 1
        mock_error.assert_called_once()

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    @patch(
        f"{_IM}.invoke",
        return_value={"success": True, "result": "done", "error": None},
    )
    @patch(f"{_IM}.resolve")
    def test_success(
        self,
        mock_resolve: MagicMock,
        _mock_invoke: MagicMock,
        _mock_error: MagicMock,
        mock_console: MagicMock,
    ) -> None:
        """Successful call returns 0 and prints result."""
        from aipass.api.apps.modules.integrations_manager import _run_call

        mock_resolve.return_value = MagicMock()

        result = _run_call("mycontract", ["arg1"])
        assert result == 0

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    @patch(
        f"{_IM}.invoke",
        return_value={"success": False, "result": None, "error": "boom"},
    )
    @patch(f"{_IM}.resolve")
    def test_driver_failure(
        self,
        mock_resolve: MagicMock,
        _mock_invoke: MagicMock,
        mock_error: MagicMock,
        _mock_console: MagicMock,
    ) -> None:
        """Failed driver returns 1 and calls error()."""
        from aipass.api.apps.modules.integrations_manager import _run_call

        mock_resolve.return_value = MagicMock()

        result = _run_call("failing", [])
        assert result == 1
        mock_error.assert_called_once()


# =============================================
# print_introspection / print_help tests
# =============================================


class TestPrintFunctions:
    """Tests for print_introspection and print_help."""

    @patch(f"{_IM}.json_handler")
    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    def test_print_introspection(
        self,
        _mock_header: MagicMock,
        mock_console: MagicMock,
        _mock_jh: MagicMock,
    ) -> None:
        """print_introspection runs without error and prints output."""
        from aipass.api.apps.modules.integrations_manager import print_introspection

        print_introspection()
        assert mock_console.print.called

    @patch(f"{_IM}.console", new_callable=MagicMock)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    def test_print_help(
        self,
        _mock_header: MagicMock,
        mock_console: MagicMock,
    ) -> None:
        """print_help runs without error and prints output."""
        from aipass.api.apps.modules.integrations_manager import print_help

        print_help()
        assert mock_console.print.called


class TestTrailingHelpDoesNotDispatch:
    """A help flag must never dispatch a contract.

    api.py's entry guard only inspects the first arg after the command, so
    `integrations call publish_devto --help` reaches handle_command with
    args[0] == "call". Dispatching there runs a live publishing driver from
    what the user typed as a help probe.
    """

    @patch(f"{_IM}.print_help", new_callable=MagicMock)
    @patch(f"{_IM}._run_call", new_callable=MagicMock)
    @patch(f"{_IM}._ensure_loaded", new_callable=MagicMock)
    def test_call_with_trailing_help_does_not_run_contract(
        self,
        _mock_loaded: MagicMock,
        mock_call: MagicMock,
        mock_help: MagicMock,
    ) -> None:
        """`integrations call <contract> --help` prints help, dispatches nothing."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        assert handle_command("integrations", ["call", "publish_devto", "--help"]) is True

        mock_call.assert_not_called()
        mock_help.assert_called_once()

    @patch(f"{_IM}.print_help", new_callable=MagicMock)
    @patch(f"{_IM}._run_list", new_callable=MagicMock)
    @patch(f"{_IM}._ensure_loaded", new_callable=MagicMock)
    def test_list_with_trailing_help_shows_help(
        self,
        _mock_loaded: MagicMock,
        mock_list: MagicMock,
        mock_help: MagicMock,
    ) -> None:
        """`integrations list --help` prints help instead of listing."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        assert handle_command("integrations", ["list", "--help"]) is True

        mock_list.assert_not_called()
        mock_help.assert_called_once()

    @patch(f"{_IM}.print_help", new_callable=MagicMock)
    @patch(f"{_IM}._run_call", new_callable=MagicMock)
    @patch(f"{_IM}._ensure_loaded", new_callable=MagicMock)
    def test_contract_args_named_help_still_dispatch(
        self,
        _mock_loaded: MagicMock,
        mock_call: MagicMock,
        mock_help: MagicMock,
    ) -> None:
        """A bare `help` is a contract argument, not a flag."""
        from aipass.api.apps.modules.integrations_manager import handle_command

        with pytest.raises(SystemExit):
            handle_command("integrations", ["call", "publish_devto", "help"])

        mock_call.assert_called_once_with("publish_devto", ["help"])
        mock_help.assert_not_called()
