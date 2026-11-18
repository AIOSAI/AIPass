# =================== AIPass ====================
# Name: test_handlers_fence.py
# Description: The handlers fence: a foreign importer is refused, kin and the modules door pass (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/__init__.py, the fence, in a fresh interpreter per case, and the package door __init__.py."""

# The refusal banner's prose beyond the caller line is not asserted.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that apps/handlers/__init__.py parses and imports

import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import aipass.skills as door
from aipass.skills.apps.handlers import switch_handler
from aipass.skills.tests import support_fence

KIN_PROBE = Path(support_fence.__file__)
FOREIGN_SHAPES = ["pkg", "deep", "dyn", "chain", "mock", "sibling"]

# Written out by hand, not read from the door: the door's own table must agree with an independent list.
_SCREEN_LOCK = "aipass.skills.lib.screen_lock.handler"
_SYSTEM_STATUS = "aipass.skills.lib.system_status.handler"
# (served name, home module, home name): a contract constant carries its skill's prefix so two skills never collide.
DOOR_NAMES = [
    ("lock_state", _SCREEN_LOCK, "lock_state"),
    ("lock_screen", _SCREEN_LOCK, "lock_screen"),
    ("machine_processes", _SYSTEM_STATUS, "machine_processes"),
    ("machine_vitals", _SYSTEM_STATUS, "machine_vitals"),
    ("SYSTEM_STATUS_REASONS", _SYSTEM_STATUS, "REASONS"),
    ("SYSTEM_STATUS_SECTIONS", _SYSTEM_STATUS, "SECTIONS"),
    ("SYSTEM_STATUS_PSUTIL_RECIPE", _SYSTEM_STATUS, "PSUTIL_RECIPE"),
    ("SCREEN_LOCK_METHOD_LOGINCTL", _SCREEN_LOCK, "METHOD_LOGINCTL"),
    ("SCREEN_LOCK_METHOD_DBUS", _SCREEN_LOCK, "METHOD_DBUS"),
    ("SCREEN_LOCK_REASON_NO_SESSION", _SCREEN_LOCK, "REASON_NO_SESSION"),
    ("SCREEN_LOCK_REASON_NO_READER", _SCREEN_LOCK, "REASON_NO_READER"),
    ("SCREEN_LOCK_REASON_READ_FAILED", _SCREEN_LOCK, "REASON_READ_FAILED"),
]


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
        """Every foreign route (no kin frame, through a kin frame, via mock, a sibling) is refused."""
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
        """The process cwd is not a frame: bootstrap pseudo-filenames must not resolve against it as kin."""
        answer = _probe(foreign_seat, shape, KIN_PROBE.parents[1])
        assert answer.startswith(("DENIED", "REFUSED")), answer
        if answer.startswith("DENIED"):
            named = "sibling" if shape == "sibling" else "foreign"
            assert f"Caller branch: {named}" in answer, answer


class TestKinAndTheDoorPass:
    """This branch's own files import freely (stdlib and pytest are transport), and the modules door is open."""

    @pytest.mark.parametrize("shape", ["pkg", "deep", "dyn", "chain", "mock"])
    def test_the_branch_itself_is_allowed(self, tmp_path, shape):
        """The probe from its own seat is allowed, including via mock.patch (unittest/mock.py, pkgutil.py)."""
        assert _probe(KIN_PROBE, shape, tmp_path) == "ALLOWED"

    def test_the_modules_door_is_open_to_a_foreign_branch(self, foreign_seat, tmp_path):
        """A foreign seat importing this branch's modules passes: the modules (kin) import the handlers."""
        assert _probe(foreign_seat, "door", tmp_path) == "ALLOWED"

    def test_the_apps_package_does_not_import_its_handlers(self):
        """With it, every foreign import sees apps/__init__.py as the caller and the fence is decorative."""
        apps_init = KIN_PROBE.parents[1] / "apps" / "__init__.py"
        source = apps_init.read_text(encoding="utf-8")
        assert "import handlers" not in source, source


class TestTheFrontDoor:
    """src/aipass/skills/__init__.py serves the names another branch imports, each from its home on access."""

    @pytest.mark.parametrize(("served", "home", "name"), DOOR_NAMES)
    def test_every_name_is_the_same_object_as_its_home_s(self, served, home, name):
        assert getattr(door, served) is getattr(importlib.import_module(home), name)

    def test_the_door_serves_exactly_the_imported_names(self):
        assert sorted(door.__all__) == sorted(served for served, _, _ in DOOR_NAMES)

    @pytest.mark.parametrize("name", ["run", "get_actions", "resolve_graphical_session", "machine_vital", "REASONS"])
    def test_an_unknown_name_raises_attribute_error_with_no_fallback(self, name):
        with pytest.raises(AttributeError, match=name):
            getattr(door, name)

    @pytest.mark.parametrize(("served", "home", "name"), DOOR_NAMES)
    def test_a_patch_on_the_home_reaches_a_caller_that_read_the_door_before(self, served, home, name):
        """A door that caches the first answer hands later callers the unpatched name."""
        getattr(door, served)
        sentinel = object()
        with patch.object(importlib.import_module(home), name, sentinel):
            assert getattr(door, served) is sentinel


# Read off the door, not written out: a function served tomorrow without a switch check joins this list and goes red.
# Constants are exempt and told apart by callable(); a function's skill is the lib/<skill>/ segment of its __module__.
SERVED_FUNCTIONS = sorted(name for name in door.__all__ if callable(getattr(door, name)))


class TestOffMeansOffForEveryServedFunction:
    """Every function the door serves refuses while its skill is switched off, running nothing."""

    def test_the_door_serves_at_least_the_four_known_functions(self):
        # The floor: an empty list would make the parametrized test below a silent pass.
        assert {"lock_screen", "lock_state", "machine_processes", "machine_vitals"} <= set(SERVED_FUNCTIONS)

    @pytest.mark.parametrize("served", SERVED_FUNCTIONS)
    def test_a_switched_off_skill_s_function_refuses_and_runs_nothing(self, served):
        function = getattr(door, served)
        skill = function.__module__.split(".")[3]
        switch_handler.set_enabled(skill, False)

        with patch("subprocess.run", side_effect=AssertionError(f"{served} ran a command while off")) as run:
            answer = function()

        assert any(f"Skill '{skill}' is switched OFF" in str(value) for value in answer.values()), answer
        run.assert_not_called()
