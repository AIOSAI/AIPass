# =================== AIPass ====================
# Name: test_integrations_manager.py
# Description: Tests for integrations_manager command handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/integrations_manager.py, the integrations command handler."""

# Tests for integrations_manager.py -- handle_command, _run_list, _run_call,
# print_introspection, print_help.
#
# Existing test_integrations.py covers bridge, registry, fetch_contracts,
# call_contract. This file covers the remaining uncovered functions.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that integrations_manager.py parses and imports
# seedgo: no-test-needed(covered_elsewhere) — fetch_contracts and call_contract, tests/test_integrations.py
# seedgo: no-test-needed(covered_elsewhere) — the bridge registry itself, tests/test_bridge_module.py

import pytest
from unittest.mock import patch, MagicMock

from aipass.api.apps.modules.integrations_manager import (
    _run_call,
    _run_list,
    handle_command,
    print_help,
    print_introspection,
)

_IM = "aipass.api.apps.modules.integrations_manager"


# =============================================
# handle_command tests
# =============================================


class TestHandleCommand:
    """Tests for integrations_manager.handle_command()."""

    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_wrong_command_returns_false(
        self,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
    ) -> None:
        """Non-integrations command returns False."""
        result = handle_command("status", [])
        assert result is False

    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_help_flag_returns_true(
        self,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--help flag triggers print_help and returns True."""
        result = handle_command("integrations", ["--help"])
        assert result is True
        assert "USAGE:" in capsys.readouterr().out

    @patch(f"{_IM}.json_handler", autospec=True)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_no_args_shows_introspection(
        self,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
        mock_jh: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No args triggers introspection and returns True."""
        result = handle_command("integrations", [])
        assert result is True
        assert "integrations call <name>" in capsys.readouterr().out
        mock_jh.log_operation.assert_called_once_with("integrations_introspection", {})

    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_unknown_subcommand_exits(
        self,
        mock_error: MagicMock,
        _mock_header: MagicMock,
    ) -> None:
        """Unknown subcommand calls error() and raises SystemExit."""
        with pytest.raises(SystemExit):
            handle_command("integrations", ["bogus"])
        mock_error.assert_called_once()

    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    @patch(f"{_IM}.registry", autospec=True)
    @patch(f"{_IM}.list_contracts", return_value=[])
    @patch(f"{_IM}.get_contracts", return_value={"contracts": [], "count": 0, "success": True})
    def test_list_subcommand_exits(
        self,
        _mock_get: MagicMock,
        _mock_list: MagicMock,
        _mock_registry: MagicMock,
        _mock_error: MagicMock,
        _mock_header: MagicMock,
    ) -> None:
        """list subcommand loads drivers and calls sys.exit."""
        with pytest.raises(SystemExit) as exc_info:
            handle_command("integrations", ["list"])
        assert exc_info.value.code == 0

    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.error", new_callable=MagicMock)
    def test_call_without_name_exits_1(
        self,
        mock_error: MagicMock,
        _mock_header: MagicMock,
    ) -> None:
        """call subcommand without contract name shows error and exits 1."""
        with pytest.raises(SystemExit) as exc_info:
            handle_command("integrations", ["call"])
        assert exc_info.value.code == 1
        mock_error.assert_called_once()


# =============================================
# _run_list tests
# =============================================


class TestRunList:
    """Tests for integrations_manager._run_list()."""

    @patch(f"{_IM}.header", new_callable=MagicMock)
    @patch(f"{_IM}.get_contracts", return_value={"contracts": [], "count": 0, "success": True})
    @patch(f"{_IM}.list_contracts", return_value=[])
    def test_no_contracts(
        self,
        _mock_list: MagicMock,
        _mock_get: MagicMock,
        _mock_header: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Empty contracts list prints 'No integrations configured.'."""
        result = _run_list()
        assert result == 0

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
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """With contracts, prints each name and returns 0."""
        result = _run_list()
        assert result == 0
        # Each contract name is printed
        full_output = capsys.readouterr().out
        assert "alpha" in full_output
        assert "beta" in full_output


# =============================================
# _run_call tests
# =============================================


class TestRunCall:
    """Tests for integrations_manager._run_call()."""

    @patch(f"{_IM}.error", new_callable=MagicMock)
    @patch(f"{_IM}.resolve", return_value=None)
    def test_contract_not_found(
        self,
        _mock_resolve: MagicMock,
        mock_error: MagicMock,
    ) -> None:
        """Unresolved contract calls error() and returns 1."""
        result = _run_call("missing", [])
        assert result == 1
        mock_error.assert_called_once()

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
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Successful call returns 0 and prints result."""
        mock_resolve.return_value = MagicMock()

        result = _run_call("mycontract", ["arg1"])
        assert result == 0

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
    ) -> None:
        """Failed driver returns 1 and calls error()."""
        mock_resolve.return_value = MagicMock()

        result = _run_call("failing", [])
        assert result == 1
        mock_error.assert_called_once()


# =============================================
# print_introspection / print_help tests
# =============================================


class TestPrintFunctions:
    """Tests for print_introspection and print_help."""

    @patch(f"{_IM}.json_handler", autospec=True)
    @patch(f"{_IM}.header", new_callable=MagicMock)
    def test_print_introspection(
        self,
        _mock_header: MagicMock,
        _mock_jh: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """print_introspection prints the subcommands it offers."""
        print_introspection()
        out = capsys.readouterr().out
        assert "integrations list" in out
        assert "integrations call <name>" in out

    @patch(f"{_IM}.header", new_callable=MagicMock)
    def test_print_help(
        self,
        _mock_header: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """print_help prints the usage lines."""
        print_help()
        out = capsys.readouterr().out
        assert "USAGE:" in out
        assert "drone @api integrations list" in out


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
        with pytest.raises(SystemExit):
            handle_command("integrations", ["call", "publish_devto", "help"])

        mock_call.assert_called_once_with("publish_devto", ["help"])
        mock_help.assert_not_called()
