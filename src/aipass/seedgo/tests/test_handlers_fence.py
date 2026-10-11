# =================== AIPass ====================
# Name: test_handlers_fence.py
# Description: The handlers fence: a foreign importer is refused, kin and the modules door pass (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/__init__.py, the fence, in a fresh interpreter per case."""

# A foreign importer of aipass.seedgo.apps.handlers is refused at import time;
# kin and the modules door pass. The refusal banner's prose beyond the caller
# line is not asserted.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/__init__.py parses and imports

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.seedgo.tests import support_fence

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
        filenames resolved against a cwd inside this branch and read as kin, so a
        foreign line that did not spell the handlers was let through. The cwd here
        is the branch root; the verdicts are the ones the tmp cwd gives."""
        answer = _probe(foreign_seat, shape, KIN_PROBE.parents[1])
        assert answer.startswith(("DENIED", "REFUSED")), answer
        if answer.startswith("DENIED"):
            named = "sibling" if shape == "sibling" else "foreign"
            assert f"Caller branch: {named}" in answer, answer


class TestKinAndTheDoorPass:
    """This branch's own files import freely, the standard library and pytest are
    transport between them and the fence, and the modules door is open to all."""

    @pytest.mark.parametrize("shape", ["pkg", "deep", "dyn", "chain", "mock"])
    def test_the_branch_itself_is_allowed(self, tmp_path, shape):
        """The probe run from its own seat under this branch; mock is the 2026-04-25
        shape (mock.patch imports from unittest/mock.py and pkgutil.py)."""
        assert _probe(KIN_PROBE, shape, tmp_path) == "ALLOWED"

    def test_the_modules_door_is_open_to_a_foreign_branch(self, foreign_seat, tmp_path):
        """A foreign seat importing this branch's modules, which import the handlers
        on its behalf: kin asked, so the fence lets it through."""
        assert _probe(foreign_seat, "door", tmp_path) == "ALLOWED"

    def test_the_apps_package_does_not_import_its_handlers(self):
        """The 2026-04-25 line. With it, every foreign import sees this branch's own
        apps/__init__.py as the caller and the fence is decorative."""
        apps_init = KIN_PROBE.parents[1] / "apps" / "__init__.py"
        source = apps_init.read_text(encoding="utf-8")
        assert "import handlers" not in source, source
