# =================== META ====================
# Name: test_module_isolation.py
# Description: drive/client.py resolving through a re-imported parent package (ordered pair)
# Version: 1.0.4
# Created: 2026-08-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/drive/client.py resolving through a re-imported parent package."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file under handlers/drive/ parses and lints clean
# seedgo: no-test-needed(documentation) — docstrings on module and class attributes

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# Pins the desync where a re-import under mocks leaves the parent attribute on a twin without .client;
# conftest's _resync_module_attrs heals it. test_b must run after test_a, on the same worker.

DRIVE_PKG = "aipass.backup.apps.handlers.drive"


class TestStaleParentAttrHealed:
    """test_a leaves the desync standing; test_b must reach drive.client through the healed parent."""

    def test_a_reimport_under_a_mocked_client_leaves_the_parent_attr_on_a_twin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Evict drive*, import a twin with client mocked away — the polluter shape."""
        for key in list(sys.modules.keys()):
            if key.startswith(DRIVE_PKG):
                monkeypatch.delitem(sys.modules, key, raising=False)

        with patch.dict(sys.modules, {f"{DRIVE_PKG}.client": MagicMock()}):
            twin = importlib.import_module(f"{DRIVE_PKG}.share")
            twin_pkg = sys.modules[DRIVE_PKG]

        assert "DriveClient" not in vars(twin)
        assert f"{DRIVE_PKG}.client" not in sys.modules

        parent_pkg = sys.modules[DRIVE_PKG.rpartition(".")[0]]
        assert parent_pkg.drive is twin_pkg
        assert DRIVE_PKG not in sys.modules

        assert not hasattr(twin_pkg, "client")

    def test_b_dotted_patch_reaches_the_real_client_through_the_healed_parent(self) -> None:
        """CI's failing shape: the parent-attribute walk must land on the class mock.patch replaced."""
        parent_pkg = importlib.import_module(DRIVE_PKG.rpartition(".")[0])
        with patch(f"{DRIVE_PKG}.client.DriveClient") as mocked:
            # The walk 3.10/3.11 mock.patch performs; on an unhealed twin .client is absent.
            assert parent_pkg.drive.client.DriveClient is mocked

        assert parent_pkg.drive is sys.modules[DRIVE_PKG]


# =============================================
