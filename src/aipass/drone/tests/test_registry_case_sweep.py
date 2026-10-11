# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: A case-insensitive filesystem must not widen what counts as a registry
# Version: 1.0.3
# Created: 2026-08-31
# Modified: 2026-09-28
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


# ``*_REGISTRY.json`` is a name, not a spelling the filesystem gets to choose.
#
# THE DEFECT. ``Path.glob`` asks the FILESYSTEM to match. On a case-insensitive
# one — Windows, and macOS by default — ``*_REGISTRY.json`` also matches
# ``*_registry.json``, and this repository is full of files with that ending:
# ``drone_command_registry.json`` beside the drone package, ten
# ``flow_json/*_registry.json`` plan counters, a ``.spawn/.template_registry.json``
# in every branch (pathlib's ``*`` matches dotfiles, unlike the ``glob`` module).
# Windows CI found it as a test red — ``find_registry()`` returned
# ``D:/a/AIPass/AIPass/src/aipass/drone/drone_command_registry.json`` — and the
# red was the smaller half of it.
#
# WHY IT IS NOT COSMETIC. A ``*_REGISTRY.json`` is a project's trust anchor. The
# walks in this tree use it to answer "which installation is this caller a citizen
# of", "what project name goes on their identity", "where is the project root the
# delete lane may write a record into". A plan-id counter answering those is not a
# near miss; it is a different question. And every walk in the tree carried its
# own copy of the glob, so the fix had to land on all of them at once — the same
# species as the dead-cwd sweep, which is why this file is shaped like that one.
#
# THE INSTRUMENT. A case-insensitive filesystem is not available on the Linux box
# this was fixed on, so the fixture below supplies exactly what one returns: the
# directory listing, matched with ``re.IGNORECASE``. That is the state, not a mock
# of the guard — ``registries_in`` is never patched, and the pins run red against
# the unfixed code on every OS rather than only on the runner where it happened to
# show.

# A name that ends with the suffix in the wrong case. Real, tracked, and sitting
# in this branch's own directory — see TestTheDecoyIsLive.
DECOY_NAME = "drone_command_registry.json"

# The naming convention itself, written here rather than read from the product,
# so a product that changed the suffix's case is caught instead of followed.
REGISTRY_SUFFIX = "_REGISTRY.json"


@pytest.fixture()
def case_insensitive_filesystem(monkeypatch):
    """The filesystem's answer folds case, the way NTFS and default APFS do.

    Supplied at ``_registry_candidates`` — the host's untrusted listing — so
    the name check in ``registries_in`` above it runs unpatched, and nothing
    else in the process sees a changed ``Path.glob``.

    Real ``Path.glob`` swallows an unreadable directory; this deliberately does
    not. A walk that cannot read a directory it passes is something a test
    should be told about, not something an instrument should hide.
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

        External projects name the registry after themselves and nothing
        promises the project name is uppercase — matching on the whole filename
        would fence out the citizens the glob was widened for in the first place.
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
    """This is not a hypothetical filesystem property — the bait is checked in.

    If this ever fails because the file was renamed, the filter below it is
    still right; what changed is that the tree stopped demonstrating why.
    """

    def test_the_branch_ships_a_wrong_case_registry_name(self):

        branch_root = Path(drone_apps.__file__).resolve().parent.parent
        decoy = branch_root / DECOY_NAME

        assert decoy.is_file(), f"expected the tracked decoy at {decoy}"
        assert not decoy.name.endswith(REGISTRY_SUFFIX)
        assert decoy.name.lower().endswith(REGISTRY_SUFFIX.lower()), (
            "the decoy no longer ends with the suffix in any case — it is not bait any more"
        )


class TestTheWindowsRedIsReproduced:
    """The exact CI failure, on Linux, with the filesystem property supplied.

    ``test_registry_handler.py::test_the_walk_that_calls_it_reaches_it_at_all``
    failed on Windows because with no cwd the walk starts at this package and
    climbs — and the first directory it passes is the branch root, which holds
    the decoy. Nothing about that depends on the operating system except whether
    the glob matched, so nothing about the pin has to either.
    """

    def test_find_registry_never_returns_a_wrong_case_name(self, no_cwd, case_insensitive_filesystem, monkeypatch):
        """Mutant killed (runner): registries_in's name check removed.

        AIPASS_HOME is unset as on the CI runner: with it set, the home registry
        answers before the package walk ever passes the decoy.
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
    """One reader. The count is a test, for the same reason it is in the cwd sweep.

    Every walk in this tree carried its own ``glob("*_REGISTRY.json")``: the
    entry point, the delete lane, the deletion record, the broker, the git lock,
    the registry resolver, and the caller-identity fallback. Fixing the one
    Windows named would have left six.
    """

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
