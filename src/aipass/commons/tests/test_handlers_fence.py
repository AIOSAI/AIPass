# =================== AIPass ====================
# Name: test_handlers_fence.py
# Description: The handlers fence: a foreign importer is refused, kin and the modules door pass (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/__init__.py, the fence, in a fresh interpreter per case."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/__init__.py parses and imports

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.commons.tests import support_fence

KIN_PROBE = Path(support_fence.__file__)
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
        """Every import route from a foreign seat is refused, and a DENIED names the caller branch.

        mock is refused inside pkgutil.resolve_name, so it surfaces as AttributeError (REFUSED)."""
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
        """A cwd inside this branch must not make the bootstrap's pseudo filenames read as kin."""
        answer = _probe(foreign_seat, shape, KIN_PROBE.parents[1])
        assert answer.startswith(("DENIED", "REFUSED")), answer
        if answer.startswith("DENIED"):
            named = "sibling" if shape == "sibling" else "foreign"
            assert f"Caller branch: {named}" in answer, answer


class TestKinAndTheDoorPass:
    """This branch's own files import freely, and the modules door is open to all."""

    @pytest.mark.parametrize("shape", ["pkg", "deep", "dyn", "chain", "mock"])
    def test_the_branch_itself_is_allowed(self, tmp_path, shape):
        """The probe run from its own seat is allowed, mock.patch's stdlib frames included."""
        assert _probe(KIN_PROBE, shape, tmp_path) == "ALLOWED"

    def test_the_modules_door_is_open_to_a_foreign_branch(self, foreign_seat, tmp_path):
        """A foreign seat importing this branch's modules gets the handlers through them: kin asked."""
        assert _probe(foreign_seat, "door", tmp_path) == "ALLOWED"

    def test_the_apps_package_does_not_import_its_handlers(self):
        """If apps/__init__.py imported handlers, every foreign import would see kin as the caller."""
        apps_init = KIN_PROBE.parents[1] / "apps" / "__init__.py"
        source = apps_init.read_text(encoding="utf-8")
        assert "import handlers" not in source, source
