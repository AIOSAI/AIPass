# =================== META ====================
# Name: test_module_isolation.py
# Description: Regression pair for the sys.modules/parent-attr desync class
# Version: 1.0.1
# Created: 2026-08-08
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/drive/client.py resolving through a re-imported parent package."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the drive package parses and imports
# seedgo: no-test-needed(documentation) — docstrings on module and class attributes
# seedgo: no-test-needed(stdlib) — importlib.import_module and mock.patch behavior

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# The defect this pair pins (CI-only xdist red). Fixtures like
# test_drive_pipeline's _fresh_import evict submodules from sys.modules and
# re-import them under mocked dependencies. patch.dict restores the sys.modules
# DICT afterwards but never the parent package's ATTRIBUTE, which keeps pointing
# at a throwaway twin - one that can lack submodule attributes entirely (they
# resolved to sys.modules mocks during its import). mock.patch then walks the
# stale attribute and dies with AttributeError: module '...drive' has no
# attribute 'client' even though a clean import works - but only when an unlucky
# xdist worker ran a polluter before a victim, so serial runs never see it.
# _resync_module_attrs heals the desync after every test; this pair recreates the
# failure shape deterministically. Order within one file is guaranteed, and
# loadscope keeps a file on one worker.
# Version note: Python 3.12+ mock resolves patch targets with
# pkgutil.resolve_name (sys.modules truth, self-healing), so the un-fixed red
# only shows on 3.10/3.11, whose mock walks parent attributes and retries getattr
# on the stale object. The final coherence assert in test_b holds the repair
# honest on every version.

DRIVE_PKG = "aipass.backup.apps.handlers.drive"


class TestStaleParentAttrHealed:
    """First test poisons like _fresh_import; second must still patch clean."""

    def test_a_manufacture_the_desync(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        # only at teardown, which runs after this assert.
        assert twin is not None
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

    def test_b_string_patch_resolves_after_repair(self) -> None:
        """CI's failing shape: mock.patch by dotted string must find drive.client."""
        with patch(f"{DRIVE_PKG}.client.DriveClient") as mocked:
            assert mocked is not None

        # And the module graph is coherent again: attribute is sys.modules truth.
        client_mod = importlib.import_module(f"{DRIVE_PKG}.client")
        drive_pkg = importlib.import_module(DRIVE_PKG)
        assert drive_pkg.client is client_mod


# =============================================
