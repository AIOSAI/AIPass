# =================== AIPass ====================
# Name: test_bridge_module.py
# Description: Tests for bridge contract registry module
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for apps/modules/bridge.py -- contract registry.

Tests:
- register + resolve: round-trip registration
- resolve unknown: returns None
- list_contracts: sorted listing
- clear: empties registry
- print_introspection: with and without contracts
- handle_command: always returns False
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aipass.api.apps.modules.bridge import (
    clear,
    handle_command,
    list_contracts,
    print_introspection,
    register,
    resolve,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure registry is empty before and after each test."""
    clear()
    yield
    clear()


# =============================================
# register + resolve
# =============================================


class TestRegisterResolve:
    """Verifies contract registration and resolution."""

    def test_register_and_resolve(self) -> None:
        """Registered contract resolves to its driver function."""

        def _driver() -> str:
            return "ok"

        register("search", _driver)
        assert resolve("search") is _driver

    def test_resolve_unknown_returns_none(self) -> None:
        """Unregistered contract resolves to None."""
        assert resolve("nonexistent") is None


# =============================================
# list_contracts
# =============================================


class TestListContracts:
    """Verifies contract listing."""

    def test_empty_registry(self) -> None:
        """Empty registry returns empty list."""
        assert list_contracts() == []

    def test_returns_sorted(self) -> None:
        """Contracts are returned in alphabetical order."""
        register("zebra", lambda: None)
        register("alpha", lambda: None)
        register("middle", lambda: None)

        assert list_contracts() == ["alpha", "middle", "zebra"]


# =============================================
# clear
# =============================================


class TestClear:
    """Verifies registry clearing."""

    def test_clear_empties_registry(self) -> None:
        """After clear(), no contracts remain."""
        register("temp", lambda: None)
        assert list_contracts() == ["temp"]

        clear()
        assert list_contracts() == []


# =============================================
# print_introspection
# =============================================


class TestPrintIntrospection:
    """Verifies introspection output for empty and populated registries."""

    @patch("aipass.api.apps.modules.bridge.console")
    @patch("aipass.api.apps.modules.bridge.header")
    def test_with_contracts(self, mock_header: object, mock_console: object) -> None:
        """Introspection prints registered contract names."""
        register("search", lambda: None)
        register("memory", lambda: None)

        print_introspection()

        mock_header.assert_called_once()  # type: ignore[union-attr]

    @patch("aipass.api.apps.modules.bridge.console")
    @patch("aipass.api.apps.modules.bridge.header")
    def test_without_contracts(self, mock_header: object, mock_console: object) -> None:
        """Introspection on empty registry still runs without error."""
        print_introspection()

        mock_header.assert_called_once()  # type: ignore[union-attr]


# =============================================
# handle_command
# =============================================


class TestHandleCommand:
    """Verifies that handle_command always returns False and stays silent."""

    def test_returns_false_no_args(self) -> None:
        """Empty args list returns False."""
        assert handle_command("bridge", []) is False

    def test_silent_no_args(self, capsys: object) -> None:
        """Bridge owns no commands — a no-arg command must not print its banner.

        Bridge is discovered before the module that owns the command, so any
        output here leaks into every no-arg command's output.
        """
        handle_command("get-key", [])

        assert capsys.readouterr().out == ""  # type: ignore[union-attr]

    def test_silent_help_flag(self, capsys: object) -> None:
        """A --help probe for another module's command must not print bridge's banner."""
        handle_command("get-key", ["--help"])

        assert capsys.readouterr().out == ""  # type: ignore[union-attr]

    def test_returns_false_help_flag(self) -> None:
        """--help arg returns False."""
        with patch("aipass.api.apps.modules.bridge.console"):
            with patch("aipass.api.apps.modules.bridge.header"):
                assert handle_command("bridge", ["--help"]) is False

    def test_returns_false_arbitrary_args(self) -> None:
        """Arbitrary arguments return False."""
        assert handle_command("bridge", ["status", "--verbose"]) is False
