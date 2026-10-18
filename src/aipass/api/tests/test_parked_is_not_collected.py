# =================== AIPass ====================
# Name: test_parked_is_not_collected.py
# Description: The parked directory contributes no tests, and can be proven to
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-10-17
# =============================================

"""Tests for tests/parked/conftest.py, the barrier that keeps the park out of collection."""

# tests/parked/ must survive a clone but never run (.archive/ gets cleaned); a
# name is no barrier, so these run collection rather than check the conftest.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the parked capture-lane file still parses; ruff lints the park, pytest does not

import subprocess
import sys
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
PARKED_DIR = TESTS_DIR / "parked"


def _collect(target: Path) -> subprocess.CompletedProcess:
    """Ask pytest what it would run, without running anything."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "--collect-only", "-q", "-p", "no:randomly"],
        cwd=str(TESTS_DIR.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


class TestTheParkStaysParked:
    """One directory, zero tests, and a reason that outlives the filename."""

    def test_the_park_exists_and_holds_something_worth_keeping(self) -> None:
        """Vacuity floor: an empty directory would pass everything below."""
        assert PARKED_DIR.is_dir(), "tests/parked/ is gone — the capture-lane seed went with it"

        parked = [path for path in PARKED_DIR.glob("*.py") if path.name != "conftest.py"]

        assert parked, "nothing is parked — the tests below are measuring an empty room"

    def test_collecting_the_park_finds_no_tests(self) -> None:
        """The whole point, asked of pytest rather than inferred from a name."""
        result = _collect(PARKED_DIR)

        # Exit 5 is "no tests collected", which is the answer this file wants.
        assert result.returncode == 5, (
            f"the park collected something (exit {result.returncode}):\n{result.stdout[-2000:]}"
        )

    def test_the_barrier_holds_even_against_a_test_named_file(self, tmp_path: Path) -> None:
        """The failure @memory hit, run against MY barrier rather than assumed."""
        park = tmp_path / "parked"
        park.mkdir()
        (park / "conftest.py").write_bytes((PARKED_DIR / "conftest.py").read_bytes())
        intruder_text = "def test_would_be_collected_anywhere_else():\n    assert True\n"
        (park / "test_intruder_from_the_barrier_pin.py").write_text(intruder_text, encoding="utf-8")
        parked_result = _collect(park)

        control = tmp_path / "test_intruder_from_the_barrier_pin.py"
        control.write_text(intruder_text, encoding="utf-8")
        control_result = _collect(control)

        assert control_result.returncode == 0, (
            f"the control file was not collected either — this test proves nothing:\n{control_result.stdout[-2000:]}"
        )
        assert parked_result.returncode == 5, (
            f"a test_-named file WAS collected from the park:\n{parked_result.stdout[-2000:]}"
        )

    def test_the_park_explains_itself(self) -> None:
        """A park with no README is a directory nobody dares delete or revive."""
        readme = PARKED_DIR / "README.md"

        assert readme.is_file()

        prose = readme.read_text(encoding="utf-8")
        assert "archive" in prose.lower(), "the README no longer says why this is not an .archive/"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
