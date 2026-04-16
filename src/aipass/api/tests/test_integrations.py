# =================== AIPass ====================
# Name: test_integrations.py
# Description: Tests for bridge, registry, and integrations handlers
# Version: 1.0.0
# Created: 2026-04-15
# Modified: 2026-04-15
# =============================================
"""
Tests for DPLAN-0133 Phase 2: bridge + registry + handlers.

Groups:
  TestBridge                — contract registration, resolve, list, clear
  TestRegistry              — auto-discovery walk, empty dir, missing driver, broken import
  TestFetchContracts        — fetch_contracts() happy path and empty
  TestCallContract          — call_contract() happy path, unregistered, args forwarding, exception
"""

import pytest

from aipass.api.apps.modules import bridge, registry
from aipass.api.apps.modules.integrations_manager import fetch_contracts, call_contract


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_bridge():
    """Reset bridge state before and after each test."""
    bridge.clear()
    registry.reset()
    yield
    bridge.clear()
    registry.reset()


# ---------------------------------------------------------------------------
# TestBridge
# ---------------------------------------------------------------------------


class TestBridge:
    def test_register_and_resolve(self):
        """register() then resolve() returns the same callable."""

        def fn():
            """Test fixture."""
            return "result"

        bridge.register("my_contract", fn)
        assert bridge.resolve("my_contract") is fn

    def test_resolve_returns_none_for_unknown(self):
        """resolve() on unregistered name returns None."""
        assert bridge.resolve("nonexistent") is None

    def test_list_contracts_empty(self):
        """list_contracts() on empty registry returns []."""
        assert bridge.list_contracts() == []

    def test_list_contracts_sorted(self):
        """list_contracts() returns sorted names."""
        bridge.register("zebra", lambda: None)
        bridge.register("alpha", lambda: None)
        bridge.register("mango", lambda: None)
        assert bridge.list_contracts() == ["alpha", "mango", "zebra"]

    def test_register_overwrites(self):
        """Registering same name twice replaces the driver."""

        def fn1():
            """First test fixture."""
            return "first"

        def fn2():
            """Second test fixture."""
            return "second"

        bridge.register("dup", fn1)
        bridge.register("dup", fn2)
        assert bridge.resolve("dup") is fn2


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_load_drivers_empty_dir(self, tmp_path):
        """Empty integrations dir → 0 drivers, no error."""
        count = registry.load_drivers(integrations_dir=tmp_path)
        assert count == 0

    def test_load_drivers_skips_missing_driver_py(self, tmp_path):
        """Folder without driver.py is skipped silently."""
        (tmp_path / "myproject").mkdir()
        count = registry.load_drivers(integrations_dir=tmp_path)
        assert count == 0

    def test_load_drivers_loads_valid_driver(self, tmp_path):
        """Valid driver.py with register() hook is loaded and registered."""
        proj = tmp_path / "testproject"
        proj.mkdir()
        (proj / "driver.py").write_text(
            "from aipass.api.apps.modules.bridge import register as br\n"
            "def register():\n"
            "    br('testcontract', lambda: 'hello')\n",
            encoding="utf-8",
        )
        count = registry.load_drivers(integrations_dir=tmp_path)
        assert count == 1
        resolved = bridge.resolve("testcontract")
        assert resolved is not None
        assert resolved() == "hello"

    def test_load_drivers_skips_broken_import(self, tmp_path):
        """Driver with syntax error is skipped; no crash; other drivers still load."""
        bad = tmp_path / "broken"
        bad.mkdir()
        (bad / "driver.py").write_text("this is not valid python !!!", encoding="utf-8")

        good = tmp_path / "good"
        good.mkdir()
        (good / "driver.py").write_text(
            "from aipass.api.apps.modules.bridge import register as br\n"
            "def register():\n"
            "    br('goodcontract', lambda: 'ok')\n",
            encoding="utf-8",
        )

        count = registry.load_drivers(integrations_dir=tmp_path)
        assert count == 1
        assert bridge.resolve("goodcontract") is not None

    def test_load_drivers_nonexistent_dir(self, tmp_path):
        """Non-existent integrations dir → 0, no error."""
        count = registry.load_drivers(integrations_dir=tmp_path / "nope")
        assert count == 0

    def test_load_drivers_no_register_hook(self, tmp_path):
        """Driver without register() still counts as loaded (no crash)."""
        proj = tmp_path / "noregister"
        proj.mkdir()
        (proj / "driver.py").write_text("# no register hook\nPASS = True\n", encoding="utf-8")
        count = registry.load_drivers(integrations_dir=tmp_path)
        assert count == 1


# ---------------------------------------------------------------------------
# TestFetchContracts
# ---------------------------------------------------------------------------


class TestFetchContracts:
    def test_empty_returns_success(self):
        """fetch_contracts() returns success with empty list when bridge is clear."""
        result = fetch_contracts()
        assert result["success"] is True
        assert result["contracts"] == []
        assert result["count"] == 0

    def test_returns_registered_contracts(self):
        """fetch_contracts() returns sorted contracts from bridge."""
        bridge.register("beta", lambda: None)
        bridge.register("alpha", lambda: None)
        result = fetch_contracts()
        assert result["success"] is True
        assert result["contracts"] == ["alpha", "beta"]
        assert result["count"] == 2


# ---------------------------------------------------------------------------
# TestCallContract
# ---------------------------------------------------------------------------


class TestCallContract:
    def test_call_registered_contract(self):
        """call_contract() resolves and invokes registered driver."""
        bridge.register("ping", lambda *a: "pong")
        result = call_contract("ping", [])
        assert result["success"] is True
        assert result["result"] == "pong"

    def test_call_unregistered_returns_failure(self):
        """call_contract() returns failure for unregistered contract."""
        result = call_contract("nope", [])
        assert result["success"] is False
        assert result["error"] is not None
        assert "nope" in result["error"]

    def test_call_passes_args_to_driver(self):
        """call_contract() forwards args to the driver function."""
        received: list = []

        def capturing_driver(*args):
            """Capture forwarded args for assertion."""
            received.extend(args)
            return "done"

        bridge.register("cap", capturing_driver)
        result = call_contract("cap", ["foo", "bar"])
        assert result["success"] is True
        assert received == ["foo", "bar"]

    def test_call_driver_exception_returns_failure(self):
        """call_contract() returns failure dict when driver raises."""

        def broken_driver(*args):
            """Always raises to simulate a broken driver."""
            raise RuntimeError("boom")

        bridge.register("broken", broken_driver)
        result = call_contract("broken", [])
        assert result["success"] is False
        assert result["error"] is not None
        assert "boom" in result["error"]
