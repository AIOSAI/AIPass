# =================== META ====================
# Name: test_module_isolation.py
# Description: drive/client.py resolving through a re-imported parent package (ordered pair)
# Version: 1.0.4
# Created: 2026-08-08
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/drive/client.py resolving through a re-imported parent package."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file under handlers/drive/ parses and lints clean
# seedgo: no-test-needed(documentation) — docstrings on module and class attributes

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# The defect this pair pins (CI-only xdist red). A test that evicts submodules
# from sys.modules and re-imports them under mocked dependencies leaves the
# parent package's ATTRIBUTE on a throwaway twin: patch.dict restores the
# sys.modules DICT, nothing restores the attribute, and the twin can lack
# submodule attributes entirely (they resolved to sys.modules mocks during its
# import). A dotted mock.patch that walks the stale attribute then dies with
# AttributeError: module '...drive' has no attribute 'client', but only when an
# xdist worker ran a polluter before a victim. No other file in this suite does
# that surgery in this process today (test_dead_cwd_imports.py:190-191 evicts
# aipass.backup inside a child interpreter); test_a does it on purpose.
# conftest's autouse _resync_module_attrs heals the desync after every test.
# test_b runs second because pytest collects a class in definition order, and
# CI's --dist loadscope keeps the class on one worker.
# Version note: Python 3.12+ mock resolves patch targets with
# pkgutil.resolve_name (sys.modules truth), so the stale attribute breaks a
# dotted patch only on 3.10/3.11, whose mock walks parent attributes. test_b
# walks the parent attributes itself, so it goes red without the heal on every
# version — because test_a evicts with monkeypatch.delitem (line 54), whose undo
# puts the real modules back while the parent attribute stays on the twin.

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

        # The twin imported under a mocked client never gained a .client attr,
        # and patch.dict's exit evicted the whole drive subtree again. Sanity:
        # the desync is real at this point — the conftest fixture repairs it
        # only at teardown, which runs after this assert. share names
        # DriveClient only under TYPE_CHECKING, so the twin bound nothing from
        # the mocked client: the missing .client below is the parent attr alone.
        assert "DriveClient" not in vars(twin)
        assert f"{DRIVE_PKG}.client" not in sys.modules

        # The desync itself, which is what this test manufactures: one dotted
        # name, two answers. The parent package's ATTRIBUTE still holds the
        # throwaway twin that the import inside the block bound there, while
        # sys.modules — the truth importlib reads — carries no entry for that
        # name at all, because patch.dict restored the DICT and nothing
        # restored the attribute. If patch.dict ever unwound the attribute too,
        # or an eager repair ran before teardown, the first assert goes red and
        # the pair stops meaning anything.
        parent_pkg = sys.modules[DRIVE_PKG.rpartition(".")[0]]
        assert parent_pkg.drive is twin_pkg
        assert DRIVE_PKG not in sys.modules

        # And the twin is the damaged object, not merely a second copy: it has
        # no .client attribute, so the parent-attribute walk that pre-3.12
        # mock.patch performs lands on the AttributeError CI reported.
        assert not hasattr(twin_pkg, "client")

    def test_b_dotted_patch_reaches_the_real_client_through_the_healed_parent(self) -> None:
        """CI's failing shape: the parent-attribute walk must land on the class mock.patch replaced."""
        parent_pkg = importlib.import_module(DRIVE_PKG.rpartition(".")[0])
        with patch(f"{DRIVE_PKG}.client.DriveClient") as mocked:
            # The walk 3.10/3.11 mock.patch performs; on an unhealed twin .client is absent.
            assert parent_pkg.drive.client.DriveClient is mocked

        # And the parent attribute is sys.modules truth again, not test_a's twin.
        assert parent_pkg.drive is sys.modules[DRIVE_PKG]


# =============================================
