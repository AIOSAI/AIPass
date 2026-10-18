# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: A case-insensitive filesystem must not widen what counts as a registry
# Version: 1.0.3
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/router_handler.py registries_in and every *_REGISTRY.json walk under apps/."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

import fnmatch
import re
from pathlib import Path

import pytest

from aipass.drone.apps.handlers import registry_handler, router_handler
from aipass.drone.apps.handlers.router_handler import registries_in
import aipass.drone.apps as drone_apps
from aipass.drone.tests import conftest as drone_conftest


# Path.glob lets a case-insensitive filesystem (Windows, default macOS) match *_registry.json
# for *_REGISTRY.json, and a registry is a project's trust anchor. The fixture supplies that
# folded listing; registries_in is never patched, so the pins red on every OS.

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
    """The state Windows CI was in when it hit this: the walk starts from the package."""

    def gone():
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(router_handler, "_working_directory", gone)
    yield


class TestTheFilterIsInPython:
    """``str.endswith`` is case-sensitive on every platform. The glob is not."""

    def test_a_wrong_case_name_is_not_a_registry(self, tmp_path, case_insensitive_filesystem):
        (tmp_path / DECOY_NAME).write_text("{}", encoding="utf-8")

        assert registries_in(tmp_path) == [], (
            "a lowercase-suffixed file was served as a registry — on a case-insensitive "
            "filesystem the glob matched it and nothing checked the name afterwards"
        )

    def test_an_exact_case_registry_still_resolves(self, tmp_path, case_insensitive_filesystem):
        """The positive control. A filter that drops everything passes the test above."""
        real = tmp_path / "AIPASS_REGISTRY.json"
        real.write_text("{}", encoding="utf-8")
        (tmp_path / DECOY_NAME).write_text("{}", encoding="utf-8")

        assert registries_in(tmp_path) == [real]

    def test_the_stem_case_is_not_constrained(self, tmp_path, case_insensitive_filesystem):
        """Only the SUFFIX is the convention; mutant killed: the product's suffix constant lower-cased.

        External projects name the registry after themselves, in any case.
        """
        odd = tmp_path / f"vera-studio{REGISTRY_SUFFIX}"
        odd.write_text("{}", encoding="utf-8")

        assert registries_in(tmp_path) == [odd]

    def test_the_answer_is_sorted(self, tmp_path):
        """Two registries in one directory must resolve the same way every run."""
        for name in ("ZULU_REGISTRY.json", "ALPHA_REGISTRY.json"):
            (tmp_path / name).write_text("{}", encoding="utf-8")

        assert [p.name for p in registries_in(tmp_path)] == ["ALPHA_REGISTRY.json", "ZULU_REGISTRY.json"]

    def test_an_absent_directory_is_empty_not_an_error(self, tmp_path):
        assert registries_in(tmp_path / "nope") == []


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


class TestTheWindowsRedIsReproduced:
    """The exact CI failure, on Linux: with no cwd the walk first passes the branch root's decoy."""

    def test_find_registry_never_returns_a_wrong_case_name(self, no_cwd, case_insensitive_filesystem, monkeypatch):
        """Mutant killed (runner): registries_in's name check removed.

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
    """One reader: every registry walk routes through registries_in; a private glob is case-widened."""

    _CALL = re.compile(r"r?glob\(\s*f?[\"'][^\"']*_registry\.json", re.IGNORECASE)

    def test_no_walk_globs_for_a_registry_outside_the_one_reader(self):

        root = Path(drone_apps.__file__).parent
        offenders = []
        for source in drone_conftest.python_sources(root):
            if source.name == "router_handler.py":
                continue  # registries_in() itself — the one sanctioned glob
            for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if self._CALL.search(code):
                    offenders.append(f"{source.relative_to(root)}:{number}")

        assert offenders == [], (
            "registry globs outside registries_in() — each one is case-widened on "
            "Windows and macOS: " + ", ".join(offenders)
        )
