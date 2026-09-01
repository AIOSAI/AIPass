# =================== AIPass ====================
# Name: test_registry_case_sweep.py
# Description: A case-insensitive filesystem must not widen what counts as a registry
# Version: 1.0.0
# Created: 2026-08-31
# =============================================

"""``*_REGISTRY.json`` is a name, not a spelling the filesystem gets to choose.

THE DEFECT. ``Path.glob`` asks the FILESYSTEM to match. On a case-insensitive
one — Windows, and macOS by default — ``*_REGISTRY.json`` also matches
``*_registry.json``, and this repository is full of files with that ending:
``drone_command_registry.json`` beside the drone package, ten
``flow_json/*_registry.json`` plan counters, a ``.spawn/.template_registry.json``
in every branch (pathlib's ``*`` matches dotfiles, unlike the ``glob`` module).
Windows CI found it as a test red — ``find_registry()`` returned
``D:/a/AIPass/AIPass/src/aipass/drone/drone_command_registry.json`` — and the
red was the smaller half of it.

WHY IT IS NOT COSMETIC. A ``*_REGISTRY.json`` is a project's trust anchor. The
walks in this tree use it to answer "which installation is this caller a citizen
of", "what project name goes on their identity", "where is the project root the
delete lane may write a record into". A plan-id counter answering those is not a
near miss; it is a different question. And every walk in the tree carried its
own copy of the glob, so the fix had to land on all of them at once — the same
species as the dead-cwd sweep, which is why this file is shaped like that one.

THE INSTRUMENT. A case-insensitive filesystem is not available on the Linux box
this was fixed on, so the fixture below supplies exactly what one returns: the
directory listing, matched with ``re.IGNORECASE``. That is the state, not a mock
of the guard — ``registries_in`` is never patched, and the pins run red against
the unfixed code on every OS rather than only on the runner where it happened to
show.
"""

import fnmatch
import re
from pathlib import Path

import pytest

from aipass.drone.apps.handlers import registry_handler
from aipass.drone.apps.handlers.router_handler import _REGISTRY_SUFFIX, registries_in

# A name that ends with the suffix in the wrong case. Real, tracked, and sitting
# in this branch's own directory — see TestTheDecoyIsLive.
DECOY_NAME = "drone_command_registry.json"


@pytest.fixture()
def case_insensitive_filesystem(monkeypatch):
    """``Path.glob`` folds case, the way NTFS and default APFS do.

    Only single-level patterns are folded — everything with a separator or a
    ``**`` is handed back to the real implementation untouched, because this
    fixture is modelling one filesystem property and not reimplementing glob.

    Real ``Path.glob`` swallows an unreadable directory; this deliberately does
    not. A walk that cannot read a directory it passes is something a test
    should be told about, not something an instrument should hide.
    """
    real_glob = Path.glob

    def folding_glob(self, pattern, *args, **kwargs):
        if "/" in pattern or "\\" in pattern or "**" in pattern:
            return real_glob(self, pattern, *args, **kwargs)
        if not self.is_dir():
            return iter(())
        matcher = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
        return iter([p for p in sorted(self.iterdir()) if matcher.match(p.name)])

    monkeypatch.setattr(Path, "glob", folding_glob)
    return folding_glob


@pytest.fixture()
def no_cwd(monkeypatch):
    """The state Windows CI was in when it hit this: the walk starts from the package."""

    def gone():
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(Path, "cwd", staticmethod(gone))
    yield


class TestTheFilterIsInPython:
    """``str.endswith`` is case-sensitive on every platform. The glob is not."""

    def test_a_wrong_case_name_is_not_a_registry(self, tmp_path, case_insensitive_filesystem):
        (tmp_path / DECOY_NAME).write_text("{}")

        assert registries_in(tmp_path) == [], (
            "a lowercase-suffixed file was served as a registry — on a case-insensitive "
            "filesystem the glob matched it and nothing checked the name afterwards"
        )

    def test_an_exact_case_registry_still_resolves(self, tmp_path, case_insensitive_filesystem):
        """The positive control. A filter that drops everything passes the test above."""
        real = tmp_path / "AIPASS_REGISTRY.json"
        real.write_text("{}")
        (tmp_path / DECOY_NAME).write_text("{}")

        assert registries_in(tmp_path) == [real]

    def test_the_stem_case_is_not_constrained(self, tmp_path, case_insensitive_filesystem):
        """Only the SUFFIX is the convention.

        External projects name the registry after themselves and nothing
        promises the project name is uppercase — matching on the whole filename
        would fence out the citizens the glob was widened for in the first place.
        """
        odd = tmp_path / f"vera-studio{_REGISTRY_SUFFIX}"
        odd.write_text("{}")

        assert registries_in(tmp_path) == [odd]

    def test_the_answer_is_sorted(self, tmp_path):
        """Two registries in one directory must resolve the same way every run."""
        for name in ("ZULU_REGISTRY.json", "ALPHA_REGISTRY.json"):
            (tmp_path / name).write_text("{}")

        assert [p.name for p in registries_in(tmp_path)] == ["ALPHA_REGISTRY.json", "ZULU_REGISTRY.json"]

    def test_an_absent_directory_is_empty_not_an_error(self, tmp_path):
        assert registries_in(tmp_path / "nope") == []


class TestTheDecoyIsLive:
    """This is not a hypothetical filesystem property — the bait is checked in.

    If this ever fails because the file was renamed, the filter below it is
    still right; what changed is that the tree stopped demonstrating why.
    """

    def test_the_branch_ships_a_wrong_case_registry_name(self):
        import aipass.drone.apps as drone_apps

        branch_root = Path(drone_apps.__file__).resolve().parent.parent
        decoy = branch_root / DECOY_NAME

        assert decoy.is_file(), f"expected the tracked decoy at {decoy}"
        assert not decoy.name.endswith(_REGISTRY_SUFFIX)
        assert decoy.name.lower().endswith(_REGISTRY_SUFFIX.lower()), (
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
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        registry_handler.reset_registry_path()
        try:
            found = registry_handler.find_registry()
        finally:
            registry_handler.reset_registry_path()

        assert found.name.endswith(_REGISTRY_SUFFIX), (
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
        import aipass.drone.apps as drone_apps

        root = Path(drone_apps.__file__).parent
        offenders = []
        for source in sorted(root.rglob("*.py")):
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
