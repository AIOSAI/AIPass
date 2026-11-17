# =================== AIPass ====================
# Name: test_handlers_fence.py
# Description: The handlers fence: a foreign importer is refused, kin and the package door pass
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/__init__.py, the fence, and __init__.py, the package door that hands names past it."""

# The refusal banner's prose beyond the caller line is not asserted.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that apps/handlers/__init__.py parses and imports

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.drone as door
from aipass.drone.tests import support_fence

KIN_PROBE = Path(support_fence.__file__)

_APPS = "aipass.drone.apps"
# The public list: each name another branch takes from drone, and the module that defines it.
DOOR_HOMES = {
    **dict.fromkeys(
        ("resolve_branch", "list_branches", "branch_exists", "get_branch_info", "normalize_branch_arg"),
        f"{_APPS}.modules.resolver",
    ),
    **dict.fromkeys(("route_command", "route_all"), f"{_APPS}.modules.router"),
    **dict.fromkeys(("discover_modules", "get_help", "get_system_help"), f"{_APPS}.modules.discovery"),
    "HelpResult": f"{_APPS}.handlers.discovery_handler",
    "CommandResult": f"{_APPS}.handlers.executor",
    **dict.fromkeys(
        ("get_registry_path", "set_registry_path", "reset_registry_path", "resolve_aipass_home"),
        f"{_APPS}.handlers.registry_handler",
    ),
    "create_identified_connection": f"{_APPS}.handlers.broker.client",
    "BrokerDaemon": f"{_APPS}.handlers.broker.daemon",
    **dict.fromkeys(("record_foreign_deletion", "record_gate_refusal"), f"{_APPS}.handlers.deletion_log"),
    **dict.fromkeys(
        (
            "RoutingError",
            "BranchNotFoundError",
            "BranchAlreadyExistsError",
            "InvalidPathError",
            "RegistryError",
            "RegistryNotFoundError",
            "RegistryCorruptError",
            "RegistryPermissionError",
            "CommandExecutionError",
        ),
        f"{_APPS}.handlers.exceptions",
    ),
}
FOREIGN_SHAPES = ["pkg", "deep", "dyn", "chain", "mock", "sibling"]


def _probe(seat: Path, shape: str, cwd: Path) -> str:
    """Run the probe at `seat` in a fresh interpreter; answer its one output line."""
    done = subprocess.run(
        [sys.executable, str(seat), shape],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(cwd),
    )
    assert done.returncode == 0, done.stderr[-600:]
    return done.stdout.strip().splitlines()[-1]


@pytest.fixture
def foreign_seat(tmp_path: Path) -> Path:
    """A copy of the probe under a path whose branch segment reads 'foreign'."""
    seat = tmp_path / "aipass" / "foreign" / "probe.py"
    seat.parent.mkdir(parents=True)
    shutil.copy(KIN_PROBE, seat)
    return seat


@pytest.fixture
def elsewhere_seat(tmp_path: Path) -> Path:
    """A copy of the probe under a path with no branch segment at all."""
    seat = tmp_path / "elsewhere" / "probe.py"
    seat.parent.mkdir(parents=True)
    shutil.copy(KIN_PROBE, seat)
    return seat


class TestAForeignImporterIsRefused:
    """Whatever route it takes, code outside this branch does not get these handlers."""

    @pytest.mark.parametrize("shape", FOREIGN_SHAPES)
    def test_a_foreign_branch_is_refused_and_named(self, foreign_seat, tmp_path, shape):
        """pkg, deep and a dynamic name: refused for importing with no kin frame; chain:
        refused on the line's spelling through a kin frame; mock: refused inside
        pkgutil.resolve_name, which surfaces as AttributeError; sibling: a frame under
        the fleet root beside this branch, foreign even inside site-packages."""
        answer = _probe(foreign_seat, shape, tmp_path)
        assert answer.startswith(("DENIED", "REFUSED")), answer
        if answer.startswith("DENIED"):
            named = "sibling" if shape == "sibling" else "foreign"
            assert f"Caller branch: {named}" in answer, answer

    def test_a_seat_with_no_branch_segment_is_refused_as_unknown(self, elsewhere_seat, tmp_path):
        """A user's script or a project outside any aipass tree is foreign too."""
        answer = _probe(elsewhere_seat, "pkg", tmp_path)
        assert answer == "DENIED Caller branch: unknown", answer

    @pytest.mark.parametrize("shape", FOREIGN_SHAPES)
    def test_the_cwd_inside_this_branch_buys_a_foreign_seat_nothing(self, foreign_seat, shape):
        """The process cwd is not a frame: pseudo filenames resolved against it must not read as kin."""
        answer = _probe(foreign_seat, shape, KIN_PROBE.parents[1])
        assert answer.startswith(("DENIED", "REFUSED")), answer
        if answer.startswith("DENIED"):
            named = "sibling" if shape == "sibling" else "foreign"
            assert f"Caller branch: {named}" in answer, answer


class TestKinAndTheDoorPass:
    """This branch's own files import freely, the standard library and pytest are
    transport between them and the fence, and the package door is open to all."""

    @pytest.mark.parametrize("shape", ["pkg", "deep", "dyn", "chain", "mock"])
    def test_the_branch_itself_is_allowed(self, tmp_path, shape):
        """The probe from its own seat; mock.patch imports from unittest/mock.py and pkgutil.py."""
        assert _probe(KIN_PROBE, shape, tmp_path) == "ALLOWED"

    def test_the_package_door_is_open_to_a_foreign_branch(self, foreign_seat, tmp_path):
        """A foreign seat reading a handler-homed name through aipass.drone: the door is kin, so it passes."""
        assert _probe(foreign_seat, "door", tmp_path) == "ALLOWED"

    def test_the_apps_package_does_not_import_its_handlers(self):
        """With that import, every foreign import sees apps/__init__.py as the caller and passes."""
        apps_init = KIN_PROBE.parents[1] / "apps" / "__init__.py"
        source = apps_init.read_text(encoding="utf-8")
        assert "import handlers" not in source, source


class TestThePackageDoor:
    """aipass.drone hands out the public list lazily, uncached, each name from the module that defines it."""

    def test_the_door_hands_out_exactly_the_public_list(self):
        assert sorted(door.__all__) == sorted(DOOR_HOMES)

    @pytest.mark.parametrize("name", sorted(DOOR_HOMES))
    def test_each_name_is_the_object_its_home_defines(self, name):
        home = DOOR_HOMES[name]
        value = getattr(door, name)
        assert value is getattr(importlib.import_module(home), name)
        assert value.__module__ == home

    def test_an_unknown_name_raises_and_the_old_alias_is_not_handed_out(self):
        with pytest.raises(AttributeError, match="has no attribute 'record_deletion'"):
            getattr(door, "record_deletion")

    @pytest.mark.parametrize("name", sorted(DOOR_HOMES))
    def test_a_patch_on_the_home_reaches_the_next_read_through_the_door(self, monkeypatch, name):
        home = importlib.import_module(DOOR_HOMES[name])
        real = getattr(door, name)
        stand_in = object()
        monkeypatch.setattr(home, name, stand_in)
        assert getattr(door, name) is stand_in
        monkeypatch.undo()
        assert getattr(door, name) is real

    def test_a_bare_import_loads_nothing_under_apps_and_a_name_loads_only_its_home(self, tmp_path):
        script = (
            "import sys, aipass.drone as d\n"
            "bare = sorted(m for m in sys.modules if m.startswith('aipass.drone.apps'))\n"
            "d.RoutingError\n"
            "print(bare, 'aipass.drone.apps.handlers.exceptions' in sys.modules,"
            " 'aipass.drone.apps.handlers.broker.daemon' in sys.modules)\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            cwd=str(tmp_path),
        )
        assert done.returncode == 0, done.stderr[-600:]
        assert done.stdout.strip() == "[] True False"
