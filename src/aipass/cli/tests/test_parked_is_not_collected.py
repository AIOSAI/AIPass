#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_parked_is_not_collected.py
# Description: The parked directory contributes no tests, and can be proven to
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

"""The park stays parked (archive doctrine, 2026-08-18).

`tests/parked/` holds `scaffold(disabled).py` — the spawn/seedgo template's
scaffold smoke test, which never ran in this branch and was moved here rather
than deleted (DPLAN-0304 item 4). It lives there because `.archive/` is
Patrick's disposal zone, cleaned without warning, so nothing durable may sit
in one.

WHY THIS FILE EXISTS. A park protected only by a naming habit is protected
until someone renames a file into it. @memory found that a `test_`-prefixed
file is collected regardless of an added `(disabled)` suffix (2026-08-19) —
so the directory carries a real barrier (`collect_ignore_glob` in its own
conftest) and this file is what notices when either the barrier or the
reason for it stops being true. Deliberately NOT a check that the conftest
exists: a test asserting a file is present passes while its contents do
nothing. These run collection and read the answer.
"""

import subprocess
import sys
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
PARKED_DIR = TESTS_DIR / "parked"


def _collect(target: Path) -> subprocess.CompletedProcess:
    """Ask pytest what it would run, without running anything."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "--collect-only", "-q"],
        cwd=str(TESTS_DIR.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestTheParkStaysParked:
    """One directory, zero tests, and a reason that outlives the filename."""

    def test_the_park_exists_and_holds_something_worth_keeping(self) -> None:
        """Vacuity floor: an empty directory would pass everything below."""
        assert PARKED_DIR.is_dir(), "tests/parked/ is gone — the scaffold park went with it"

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
        """The failure @memory hit, run against MY directory rather than assumed.

        A park protected only by its filenames is protected until someone
        renames one. This drops a file that WOULD be collected anywhere else
        into the park, proves the barrier still answers zero, and removes it —
        so the guarantee is about the directory, not about today's names.
        """
        intruder = PARKED_DIR / "test_intruder_from_the_barrier_pin.py"
        assert not intruder.exists(), "leftover from a previous run — remove it by hand"

        intruder.write_text("def test_would_be_collected_anywhere_else():\n    assert True\n", encoding="utf-8")
        try:
            parked_result = _collect(PARKED_DIR)

            # The same bytes somewhere with no barrier, so the file itself is
            # proven collectable and the zero above is the barrier's doing.
            control = tmp_path / "test_intruder_from_the_barrier_pin.py"
            control.write_text(intruder.read_text(encoding="utf-8"), encoding="utf-8")
            control_result = _collect(control)
        finally:
            intruder.unlink()

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
