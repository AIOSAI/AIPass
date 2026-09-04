# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests that memory's shim is wired to the fleet json service
# Version: 2.0.0
# Created: 2026-09-03
# Modified: 2026-09-03
# =============================================

"""Tests for memory's JSON handler shim.

Only the WIRING is tested here: that this branch's shim binds the fleet's one
json service (DPLAN-0325), that it lands in this branch's json directory, and
that it adds nothing of its own. The service's BEHAVIOUR - defaults, validation,
provisioning, rotation, durability - is pinned once for all branches by
seedgo's cross-branch contract, and is deliberately not re-tested per branch.

What this file used to hold is subsumed there: it built its own handler over a
tmp dir and pinned the shared library's internals, so it could pass against a
shim that was wired to nothing.

Redirection is the ``AIPASS_TEST_LOG_DIR`` seam that ``mock_infrastructure``
sets. The shim has no attributes to patch, and that is the point.
"""

import pytest

from aipass.prax import json_handler as json_service
from aipass.memory.apps.handlers.json import json_handler


BOUND_NAMES = (
    "read_json",
    "write_json",
    "validate_json_structure",
    "get_json_path",
    "ensure_json_exists",
    "ensure_module_jsons",
    "load_json",
    "save_json",
    "log_operation",
)


# =============================================================================
# SHIM WIRING
# =============================================================================


def test_get_path_returns_path_under_branch_json_dir(mock_infrastructure):
    """get_json_path returns a Path, and it lands in the redirected sandbox."""
    result = json_handler.get_json_path("probe", "config")

    assert result.parent == mock_infrastructure
    assert result.name == "probe_config.json"


def test_shim_reexports_every_documented_name():
    """The shim must expose the full service surface, not a subset."""
    expected = BOUND_NAMES + ("InvalidDocument", "WriteFailed")
    missing = [name for name in expected if not hasattr(json_handler, name)]

    assert missing == [], f"shim is missing re-exports: {missing}"


@pytest.mark.parametrize("name", BOUND_NAMES)
def test_every_public_name_is_a_bound_method_of_the_service(name):
    """It BINDS, never wraps.

    A wrapper would add a stack frame, and the service names the calling module
    from frame 2 - so every entry memory logged would be attributed to the
    wrapper's own file instead of the caller's.
    """
    bound = getattr(json_handler, name)

    assert bound.__func__ is getattr(json_service.JsonHandle, name)
    assert isinstance(bound.__self__, json_service.JsonHandle)


def test_the_exceptions_are_the_services_own():
    """A caller catching memory's InvalidDocument catches the service's."""
    assert json_handler.InvalidDocument is json_service.InvalidDocument
    assert json_handler.WriteFailed is json_service.WriteFailed


def test_the_shim_is_bound_to_this_branch():
    """for_module derived memory's root from the shim's own __file__."""
    assert json_handler.get_json_path.__self__.branch_root.name == "memory"


def test_the_shim_carries_nothing_else():
    """Byte-identical in every branch by design - anything added here is drift."""
    public = {name for name in vars(json_handler) if not name.startswith("_")}

    assert public == set(json_handler.__all__) | {"json_handler"}
