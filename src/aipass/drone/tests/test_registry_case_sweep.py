# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: A case-insensitive filesystem must not widen what counts as a registry
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/registry_name.py, router_handler.py registry_named_entries and every registry walk."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that the module under test parses and imports

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.drone as door
from aipass.drone.apps.handlers import registry_handler, router_handler
from aipass.drone.apps.handlers.router_handler import registry_named_entries
import aipass.drone.apps as drone_apps
from aipass.drone.tests import conftest as drone_conftest


# A case-folding glob matches *_registry.json too; the fixture fakes one, the name check runs unpatched.

# Wrong-case suffix, real and tracked in this branch's directory (TestTheDecoyIsLive).
DECOY_NAME = "drone_command_registry.json"

# Written here, not read from the product, so a product that changes the suffix case is caught.
REGISTRY_SUFFIX = "_REGISTRY.json"


@pytest.fixture()
def case_insensitive_filesystem(monkeypatch):
    """The filesystem's answer folds case, the way NTFS and default APFS do.

    Patched at ``_registry_candidates`` so the name check above it runs unpatched. Unlike
    ``Path.glob`` it does not swallow an unreadable directory: a test should hear of that.
    """
    matcher = re.compile(fnmatch.translate(f"*{REGISTRY_SUFFIX}"), re.IGNORECASE)

    def folding_listing(directory):
        if not directory.is_dir():
            return []
        return [p for p in sorted(directory.iterdir()) if matcher.match(p.name)]

    monkeypatch.setattr(router_handler, "_registry_candidates", folding_listing)
    return folding_listing


@pytest.fixture()
def no_cwd(monkeypatch):
    """No cwd: the walk starts from the package."""

    def gone():
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(router_handler, "_working_directory", gone)
    yield


class TestTheRegistryFilenamePredicate:
    """drone's top file serves is_registry_filename: a name in, a bool out, stdlib only."""

    @pytest.mark.parametrize(
        ("name", "verdict"),
        [
            ("AIPASS_REGISTRY.json", True),
            (f"vera-studio{REGISTRY_SUFFIX}", True),
            (DECOY_NAME, False),
            ("AIPASS_REGISTRY.JSON", False),
            ("AIPASS_REGISTRY.json.bak", False),
        ],
    )
    def test_only_the_exact_case_suffix_is_a_registry_name(self, name, verdict):
        assert door.is_registry_filename(name) is verdict

    def test_importing_it_loads_no_aipass_module_but_the_package_roots_and_nothing_outside_the_stdlib(self, tmp_path):
        script = (
            "import sys\n"
            "before = set(sys.modules)\n"
            "from aipass.drone import is_registry_filename\n"
            "new = set(sys.modules) - before\n"
            "print(sorted(m for m in new if m.split('.')[0] == 'aipass'))\n"
            "print(sorted(m for m in new if m.split('.')[0] not in sys.stdlib_module_names | {'aipass'}))\n"
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
        aipass_modules, outside_stdlib = done.stdout.strip().splitlines()
        assert aipass_modules == str(
            [
                "aipass",
                "aipass.drone",
                "aipass.drone.apps",
                "aipass.drone.apps.handlers",
                "aipass.drone.apps.handlers.registry_name",
            ]
        )
        assert outside_stdlib == "[]"


class TestTheFilterIsInPython:
    """``str.endswith`` is case-sensitive on every platform. The glob is not."""

    def test_a_wrong_case_name_is_not_a_registry(self, tmp_path, case_insensitive_filesystem):
        (tmp_path / DECOY_NAME).write_text("{}", encoding="utf-8")

        assert registry_named_entries(tmp_path) == [], (
            "a lowercase-suffixed file was served as a registry — on a case-insensitive "
            "filesystem the glob matched it and nothing checked the name afterwards"
        )

    def test_an_exact_case_registry_still_resolves(self, tmp_path, case_insensitive_filesystem):
        """The positive control. A filter that drops everything passes the test above."""
        real = tmp_path / "AIPASS_REGISTRY.json"
        real.write_text("{}", encoding="utf-8")
        (tmp_path / DECOY_NAME).write_text("{}", encoding="utf-8")

        assert registry_named_entries(tmp_path) == [real]

    def test_the_stem_case_is_not_constrained(self, tmp_path, case_insensitive_filesystem):
        """Only the SUFFIX is the convention; mutant killed: the product's suffix constant lower-cased.

        External projects name the registry after themselves, in any case.
        """
        odd = tmp_path / f"vera-studio{REGISTRY_SUFFIX}"
        odd.write_text("{}", encoding="utf-8")

        assert registry_named_entries(tmp_path) == [odd]

    def test_the_answer_is_sorted(self, tmp_path):
        """Two registries in one directory must resolve the same way every run."""
        for name in ("ZULU_REGISTRY.json", "ALPHA_REGISTRY.json"):
            (tmp_path / name).write_text("{}", encoding="utf-8")

        assert [p.name for p in registry_named_entries(tmp_path)] == ["ALPHA_REGISTRY.json", "ZULU_REGISTRY.json"]

    def test_an_absent_directory_is_empty_not_an_error(self, tmp_path):
        assert registry_named_entries(tmp_path / "nope") == []


class TestTheDecoyIsLive:
    """This is not a hypothetical filesystem property — the bait is checked in (a rename fails only this)."""

    def test_the_branch_ships_a_wrong_case_registry_name(self):

        branch_root = Path(drone_apps.__file__).resolve().parent.parent
        decoy = branch_root / DECOY_NAME

        assert decoy.is_file(), f"expected the tracked decoy at {decoy}"
        assert not decoy.name.endswith(REGISTRY_SUFFIX)
        assert decoy.name.lower().endswith(REGISTRY_SUFFIX.lower()), (
            "the decoy no longer ends with the suffix in any case — it is not bait any more"
        )


class TestTheCaseFoldedWalkIsReproduced:
    """A case-folding listing with no cwd: the walk first passes the branch root's decoy."""

    def test_find_registry_never_returns_a_wrong_case_name(self, no_cwd, case_insensitive_filesystem, monkeypatch):
        """Mutant killed (runner): registry_named_entries' name check removed.

        AIPASS_HOME is unset: set, the home registry answers before the walk reaches the decoy.
        """
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        registry_handler.reset_registry_path()
        try:
            found = registry_handler.find_registry()
        finally:
            registry_handler.reset_registry_path()

        assert found.name.endswith(REGISTRY_SUFFIX), (
            f"find_registry served {found} — a case-insensitive filesystem widened the walk"
        )


class TestTheSweepIsComplete:
    """One reader: every registry walk routes through registry_named_entries; a private glob is case-widened."""

    _CALL = re.compile(r"r?glob\(\s*f?[\"'][^\"']*_registry\.json", re.IGNORECASE)

    def test_no_walk_globs_for_a_registry_outside_the_one_reader(self):

        root = Path(drone_apps.__file__).parent
        offenders = []
        for source in drone_conftest.python_sources(root):
            if source.name == "router_handler.py":
                continue  # registry_named_entries() itself — the one sanctioned glob
            for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if self._CALL.search(code):
                    offenders.append(f"{source.relative_to(root)}:{number}")

        assert offenders == [], (
            "registry globs outside registry_named_entries() — each one is case-widened on "
            "a case-insensitive filesystem: " + ", ".join(offenders)
        )
