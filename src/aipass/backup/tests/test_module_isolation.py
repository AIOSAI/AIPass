# =================== AIPass ====================
# Name: test_module_isolation.py
# Description: Regression pair for the sys.modules/parent-attr desync class
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-08-08
# =============================================

"""Regression tests for the stale parent-attribute class (CI-only xdist red).

Fixtures like test_drive_pipeline's _fresh_import evict submodules from
sys.modules and re-import them under mocked dependencies. patch.dict restores
the sys.modules DICT afterwards but never the parent package's ATTRIBUTE,
which keeps pointing at a throwaway twin — one that can lack submodule
attributes entirely (they resolved to sys.modules mocks during its import).
mock.patch then walks the stale attribute and dies with
``AttributeError: module '...drive' has no attribute 'client'`` even though a
clean import works — but only when an unlucky xdist worker ran a polluter
module before a victim, so serial runs never see it.

conftest._resync_module_attrs heals the desync after every test. This pair
recreates the exact CI failure shape deterministically: the first test
manufactures the desync the way _fresh_import does; the second asserts a
string-target patch works afterwards. Order within one file is guaranteed,
and loadscope keeps a file on one worker.

Version note: Python 3.12+ mock resolves patch targets with
pkgutil.resolve_name (sys.modules truth, self-healing), so the un-fixed red
only shows on 3.10/3.11, whose mock walks parent attributes and retries
getattr on the stale object. The final coherence assert in test_b holds the
repair honest on every version.
"""

import importlib
import sys
from unittest.mock import MagicMock, patch

DRIVE_PKG = "aipass.backup.apps.handlers.drive"


class TestStaleParentAttrHealed:
    """First test poisons like _fresh_import; second must still patch clean."""

    def test_a_manufacture_the_desync(self) -> None:
        """Evict drive*, import a twin with client mocked away — the polluter shape."""
        for key in list(sys.modules.keys()):
            if key.startswith(DRIVE_PKG):
                del sys.modules[key]

        with patch.dict(sys.modules, {f"{DRIVE_PKG}.client": MagicMock()}):
            twin = importlib.import_module(f"{DRIVE_PKG}.share")

        # The twin imported under a mocked client never gained a .client attr,
        # and patch.dict's exit evicted the whole drive subtree again. Sanity:
        # the desync is real at this point — the conftest fixture repairs it
        # only at teardown, which runs after this assert.
        assert twin is not None
        assert f"{DRIVE_PKG}.client" not in sys.modules

    def test_b_string_patch_resolves_after_repair(self) -> None:
        """CI's failing shape: mock.patch by dotted string must find drive.client."""
        with patch(f"{DRIVE_PKG}.client.DriveClient") as mocked:
            assert mocked is not None

        # And the module graph is coherent again: attribute is sys.modules truth.
        client_mod = importlib.import_module(f"{DRIVE_PKG}.client")
        drive_pkg = importlib.import_module(DRIVE_PKG)
        assert drive_pkg.client is client_mod


# =============================================
