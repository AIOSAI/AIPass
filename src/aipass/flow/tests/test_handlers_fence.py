# =================== AIPass ====================
# Name: test_handlers_fence.py
# Description: The handlers fence and the package top file, flow's one import door
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/__init__.py, the fence, and __init__.py, the door, in a fresh interpreter per case."""

# The refusal banner's prose beyond the caller line is not asserted.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that apps/handlers/__init__.py parses and imports

import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.flow as door
from aipass.flow.tests import support_fence

KIN_PROBE = Path(support_fence.__file__)
FOREIGN_SHAPES = ["pkg", "deep", "dyn", "chain", "mock", "sibling"]

# Written out by hand, not read from the door: the door's own table must agree with an independent list.
DOOR_HOMES = {"aipass.flow.apps.handlers.plan.get_open_plans": ("get_open_plans",)}
DOOR_NAMES = [(home, name) for home, names in DOOR_HOMES.items() for name in names]

# Prints every aipass.flow submodule loaded after the probe's body runs.
_LOADED = "\nprint(json.dumps(sorted(m for m in sys.modules if m.startswith('aipass.flow.'))))"


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


def _fresh(body: str, cwd: Path) -> list[str]:
    """Run *body* in a clean interpreter; answer the flow submodules it left loaded."""
    done = subprocess.run(
        [sys.executable, "-c", "import importlib, json, sys\n" + body + _LOADED],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(cwd),
    )
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1])


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
        """The process cwd is not a frame. Measured 2026-10-08: the bootstrap's pseudo
        filenames read as kin against a branch cwd; here the cwd is the branch root."""
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
        """The probe run from its own seat under this branch; mock is the 2026-04-25
        shape (mock.patch imports from unittest/mock.py and pkgutil.py)."""
        assert _probe(KIN_PROBE, shape, tmp_path) == "ALLOWED"

    def test_the_package_door_is_open_to_a_foreign_branch(self, foreign_seat, tmp_path):
        """A foreign seat reading a name through aipass.flow, which imports the handler
        on its behalf: kin asked, so the fence lets it through."""
        assert _probe(foreign_seat, "door", tmp_path) == "ALLOWED"

    def test_the_apps_package_does_not_import_its_handlers(self):
        """The 2026-04-25 line. With it, every foreign import sees this branch's own
        apps/__init__.py as the caller and the fence is decorative."""
        apps_init = KIN_PROBE.parents[1] / "apps" / "__init__.py"
        source = apps_init.read_text(encoding="utf-8")
        assert "import handlers" not in source, source


class TestTheTopFileIsTheOneDoor:
    """from aipass.flow import <name>: each name from its real home, lazily, never cached."""

    def test_the_public_list_is_exactly_the_hand_written_table(self):
        assert sorted(door.__all__) == sorted(name for _, name in DOOR_NAMES)
        assert set(door.__all__) <= set(dir(door))

    @pytest.mark.parametrize(("home", "name"), DOOR_NAMES)
    def test_every_name_is_the_same_object_as_its_home_s(self, home, name):
        assert getattr(door, name) is getattr(importlib.import_module(home), name)

    @pytest.mark.parametrize("name", ["door_open_plans", "list_plans", "load_registry", "_HOMES_typo"])
    def test_an_unknown_name_raises_attribute_error_with_no_fallback(self, name):
        with pytest.raises(AttributeError, match=name):
            getattr(door, name)

    @pytest.mark.parametrize(("home", "name"), DOOR_NAMES)
    def test_a_patch_on_the_home_reaches_a_caller_that_read_the_door_before(self, monkeypatch, home, name):
        """A door that caches the first answer hands later callers the unpatched name."""
        getattr(door, name)
        sentinel = object()
        monkeypatch.setattr(importlib.import_module(home), name, sentinel)
        assert getattr(door, name) is sentinel

    def test_a_bare_import_loads_nothing_under_apps(self, tmp_path):
        assert _fresh("import aipass.flow", tmp_path) == []

    @pytest.mark.parametrize("home", list(DOOR_HOMES))
    def test_each_name_loads_no_more_than_its_home_alone(self, home, tmp_path):
        """No door_ module, no other home: the door's reach equals a direct import of the home."""
        names = DOOR_HOMES[home]
        through_door = _fresh(f"import aipass.flow as d\nfor n in {names!r}: getattr(d, n)", tmp_path)
        assert through_door == _fresh(f"importlib.import_module({home!r})", tmp_path)
        assert not [m for m in through_door if ".modules" in m]

    def test_a_foreign_branch_passes_the_handlers_fence_through_the_door(self, tmp_path):
        """The fence refuses a foreign importer of handlers; the door is kin acting on its behalf."""
        seat = tmp_path / "aipass" / "foreign" / "probe.py"
        seat.parent.mkdir(parents=True)
        seat.write_text("from aipass.flow import get_open_plans\n", encoding="utf-8")
        loaded = _fresh(f"import runpy\nrunpy.run_path({str(seat)!r}, run_name='__main__')", tmp_path)
        assert "aipass.flow.apps.handlers.plan.get_open_plans" in loaded
