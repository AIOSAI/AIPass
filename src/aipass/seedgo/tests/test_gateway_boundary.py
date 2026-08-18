"""Tests for the gateway_boundary standard.

The standard says: a branch may write its OWN storage, and may ask another
branch to write theirs through their door, but may not reach into another
branch's storage and write it by hand.

Every false-positive guard below corresponds to a real fleet measurement made
while calibrating this checker (59 hits -> 1). The guards are the standard.
"""

# =================== META ====================
# Name: test_gateway_boundary.py
# Description: Tests for the gateway boundary standards checker
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import gateway_boundary_check as checker


def _check(tmp_path: Path, source: str, branch: str = "api") -> dict:
    """Run the checker on source planted in a branch-shaped path."""
    target = tmp_path / "src" / "aipass" / branch / "apps" / "handlers" / "mod.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return checker.check_module(str(target), bypass_rules=[])


class TestFiresOnRealViolations:
    def test_writing_another_branchs_owned_file_is_a_violation(self, tmp_path: Path):
        source = (
            "import tempfile\n"
            "from pathlib import Path\n"
            "FLAG = Path(tempfile.gettempdir()) / 'aipass-hooks-muted'\n"
            "def mute():\n"
            "    FLAG.touch()\n"
        )
        result = _check(tmp_path, source)
        assert result["passed"] is False
        assert "hooks" in result["checks"][0]["message"]

    def test_writing_a_private_storage_root_with_no_door_is_a_violation(self, tmp_path: Path):
        source = (
            "from pathlib import Path\n"
            "def stamp(root):\n"
            "    p = Path(root) / '.seedgo' / 'bypass.json'\n"
            "    p.write_text('{}')\n"
        )
        result = _check(tmp_path, source, branch="api")
        assert result["passed"] is False
        assert ".seedgo" in result["checks"][0]["message"]

    def test_violation_is_anchored_on_the_write_not_the_literal(self, tmp_path: Path):
        """The reported line must be where the write happens."""
        source = (
            "import tempfile\n"
            "from pathlib import Path\n"
            "FLAG = Path(tempfile.gettempdir()) / 'aipass-hooks-muted'\n"
            "\n"
            "\n"
            "def mute():\n"
            "    FLAG.touch()\n"
        )
        result = _check(tmp_path, source)
        assert "line 7" in result["checks"][0]["message"]

    def test_taint_propagates_through_a_helper_that_returns_the_path(self, tmp_path: Path):
        source = (
            "from pathlib import Path\n"
            "def _flag(root):\n"
            "    return Path(root) / 'aipass-hooks-muted'\n"
            "def mute(root):\n"
            "    _flag(root).touch()\n"
        )
        result = _check(tmp_path, source)
        assert result["passed"] is False

    def test_score_drops_by_25_per_violation(self, tmp_path: Path):
        source = (
            "from pathlib import Path\n"
            "A = Path('x') / 'aipass-hooks-muted'\n"
            "B = Path('y') / '.seedgo' / 'bypass.json'\n"
            "A.touch()\n"
            "B.write_text('{}')\n"
        )
        result = _check(tmp_path, source)
        assert result["score"] == 50


class TestDoesNotFireOnLegitimateCode:
    """Each of these was a MEASURED false positive during calibration."""

    def test_reading_another_branchs_file_is_not_a_violation(self, tmp_path: Path):
        source = (
            "from pathlib import Path\n"
            "def read(root):\n"
            "    return (Path(root) / '.seedgo' / 'bypass.json').read_text()\n"
        )
        assert _check(tmp_path, source)["passed"] is True

    def test_writing_your_own_storage_is_not_a_violation(self, tmp_path: Path):
        source = (
            "from pathlib import Path\n"
            "def write(root):\n"
            "    (Path(root) / '.seedgo' / 'bypass.json').write_text('{}')\n"
        )
        assert _check(tmp_path, source, branch="seedgo")["passed"] is True

    def test_mentioning_a_foreign_path_while_writing_your_own_is_not_a_violation(self, tmp_path: Path):
        """The write and the foreign path must be the SAME path."""
        source = (
            "from pathlib import Path\n"
            "FOREIGN = Path('.seedgo') / 'bypass.json'\n"
            "def write(root):\n"
            "    (Path(root) / 'mine.json').write_text('{}')\n"
        )
        assert _check(tmp_path, source, branch="api")["passed"] is True

    def test_str_replace_is_not_a_filesystem_write(self, tmp_path: Path):
        """Measured: this alone caused 2 of 10 hits, both pure readers."""
        source = (
            "from pathlib import Path\n"
            "def load(root):\n"
            "    raw = (Path(root) / '.seedgo' / 'bypass.json').read_text()\n"
            "    return raw.replace('$HOME', '/tmp')\n"
        )
        assert _check(tmp_path, source)["passed"] is True

    def test_registry_and_passport_are_read_by_design_not_owned_writes(self, tmp_path: Path):
        """Measured: including these flagged 47 files across 13 branches, all readers."""
        source = (
            "from pathlib import Path\n"
            "def find(root):\n"
            "    p = Path(root) / 'AIPASS_REGISTRY.json'\n"
            "    p.write_text('{}')\n"
        )
        assert _check(tmp_path, source)["passed"] is True

    def test_trinity_is_written_by_every_branch_for_itself(self, tmp_path: Path):
        """Measured: flagged @aipass writing its OWN local.json."""
        source = "from pathlib import Path\nLOCAL = Path('.trinity') / 'local.json'\nLOCAL.write_text('{}')\n"
        assert _check(tmp_path, source)["passed"] is True

    def test_shared_namespaces_are_not_private_storage(self, tmp_path: Path):
        """Measured: .aipass/ and .claude/ produced 4 hits, all legitimate."""
        source = (
            "from pathlib import Path\n"
            "def mine(root):\n"
            "    (Path(root) / '.aipass' / 'skills').mkdir(parents=True, exist_ok=True)\n"
        )
        assert _check(tmp_path, source, branch="skills")["passed"] is True

    def test_a_file_that_routes_through_a_door_is_not_flagged_on_directories(self, tmp_path: Path):
        source = (
            "import subprocess\n"
            "from pathlib import Path\n"
            "def ask(root):\n"
            "    subprocess.run(['drone', '@seedgo', 'audit'])\n"
            "    (Path(root) / '.seedgo' / 'x.json').write_text('{}')\n"
        )
        assert _check(tmp_path, source)["passed"] is True

    def test_tests_are_out_of_scope(self):
        assert checker.APPLIES_TO == "production"


class TestFiresOnTheCaseItWasWrittenFor:
    """Red-first: the standard must name the live violation in api/host/settings.py.

    The aipass-hooks-muted flag write this class originally pinned was CURED the
    same night (2026-08-18): api's hooks lane now routes through the hooksound
    door, so the live file no longer carries it — that species stays pinned by
    the tmp fixtures in TestFiresOnRealViolations. What remains live is the
    settings.local.json hand-write (the documented standing line: no owner door
    exists). When THAT is cured too, this test's premise ends — retire it rather
    than hunting a new live violation to feed it.
    """

    def test_live_api_settings_is_flagged(self):
        target = Path(__file__).resolve().parents[2] / "api" / "apps" / "handlers" / "host" / "settings.py"
        if not target.exists():
            pytest.skip("api host settings.py not present in this checkout")
        result = checker.check_module(str(target), bypass_rules=[])
        assert result["passed"] is False
        messages = " ".join(c["message"] for c in result["checks"])
        assert "settings.local.json" in messages


class TestContractShape:
    def test_returns_the_standard_envelope(self, tmp_path: Path):
        result = _check(tmp_path, "x = 1\n")
        assert result["standard"] == "GATEWAY_BOUNDARY"
        assert set(result) >= {"passed", "checks", "score", "standard"}

    def test_non_python_is_skipped(self, tmp_path: Path):
        target = tmp_path / "notes.md"
        target.write_text("hello", encoding="utf-8")
        assert checker.check_module(str(target), bypass_rules=[])["passed"] is True

    def test_missing_file_fails_honestly(self, tmp_path: Path):
        result = checker.check_module(str(tmp_path / "gone.py"), bypass_rules=[])
        assert result["passed"] is False
        assert result["score"] == 0

    def test_unparseable_source_does_not_crash(self, tmp_path: Path):
        assert _check(tmp_path, "def broken(:\n")["passed"] is True
