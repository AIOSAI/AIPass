# =================== AIPass ====================
# Name: test_bridge_module.py
# Description: Tests for bridge contract registry module
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/bridge.py, the contract registry."""

# Tests:
# - register + resolve: round-trip registration
# - resolve unknown: returns None
# - list_contracts: sorted listing
# - clear: empties registry
# - print_introspection: with and without contracts
# - handle_command: always returns False

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that bridge.py parses and imports
# seedgo: no-test-needed(help_flag_safety) — drone's --help routing to this module, owned by that standard

from __future__ import annotations

from typing import Any

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

    def test_with_contracts(self, capsys: pytest.CaptureFixture[str], header_fires_nowhere: Any) -> None:
        """Introspection prints registered contract names.
        The title goes through cli's header, which alone fires cli_header_displayed (api, fleet green leg 3).
        Mutant that reddens it: header replaced by a plain print of the same title."""
        register("search", lambda: None)
        register("memory", lambda: None)

        print_introspection()

        out = capsys.readouterr().out
        header_fires_nowhere.fire.assert_called_once_with("cli_header_displayed", title="Bridge — Contract Registry")
        assert "Bridge — Contract Registry" in out
        assert "Registered contracts:" in out
        assert "• memory" in out
        assert "• search" in out
        assert "No contracts registered." not in out

    def test_without_contracts(self, capsys: pytest.CaptureFixture[str], header_fires_nowhere: Any) -> None:
        """Introspection on empty registry says it holds no contracts."""
        print_introspection()

        out = capsys.readouterr().out
        header_fires_nowhere.fire.assert_called_once_with("cli_header_displayed", title="Bridge — Contract Registry")
        assert "Bridge — Contract Registry" in out
        assert "No contracts registered." in out
        assert "Registered contracts:" not in out


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

    def test_returns_false_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help arg returns False and prints nothing."""
        assert handle_command("bridge", ["--help"]) is False
        assert capsys.readouterr().out == ""

    def test_returns_false_arbitrary_args(self) -> None:
        """Arbitrary arguments return False."""
        assert handle_command("bridge", ["status", "--verbose"]) is False
