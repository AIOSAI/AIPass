# =================== AIPass ====================
# Name: test_import_isolation.py
# Description: Pins against sys.modules poisoning of the handlers.json package
# Version: 1.1.0
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""Tests for tests/conftest.py's handlers/json stand-in and the suite's sys.modules evictions."""

# Two facts poison lazy submodule imports: a package stand-in with no __path__, and a bare
# sys.modules eviction that outlives its test. xdist ordering decides when they meet, so both
# are pinned at the source; the failure surfaces far away as a wrong count.

# The declared pass — what is NOT tested here, and what covers it instead:

import re
import sys
from pathlib import Path

import pytest


_TESTS = Path(__file__).resolve().parent
_PACKAGE = "aipass.memory.apps.handlers.json"

# The name is captured so an unrelated leaf module is not charged to the package.
_LITERAL_EVICTION = re.compile(r"(?<!monkeypatch\.)(?:sys\.modules\.pop\(|del sys\.modules\[)\s*\"([^\"]+)\"")

# Through a variable the target is unknowable from the line, so the lookback decides.
_VARIABLE_EVICTION = re.compile(r"(?<!monkeypatch\.)(?:sys\.modules\.pop\(|del sys\.modules\[)\s*[A-Za-z_]")

# Covers `for` / `if name.startswith(...)` / `del`.
_LOOKBACK = 3


def _scan_lines(lines: list[str]) -> list[int]:
    """1-based line numbers where a bare eviction targets the impersonated package."""
    hits = []
    for index, line in enumerate(lines):
        literal = _LITERAL_EVICTION.search(line)
        if literal:
            if literal.group(1).startswith(_PACKAGE):
                hits.append(index + 1)
            continue
        if _VARIABLE_EVICTION.search(line):
            window = lines[max(0, index - _LOOKBACK) : index + 1]
            if any(_PACKAGE in earlier for earlier in window):
                hits.append(index + 1)
    return hits


def _bare_evictions_of_the_package() -> list[str]:
    """Every live test file's bare evictions of the package; this file is skipped (it quotes both forms)."""
    offenders = []
    for path in sorted(_TESTS.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        offenders += [f"{path.name}:{number}: {lines[number - 1].strip()}" for number in _scan_lines(lines)]
    return offenders


class TestTheStandInIsAnHonestPackage:
    """Impersonating a package means answering ``__path__`` like one."""

    def test_the_stand_in_carries_a_path(self):
        """The autouse fixture is active right now — this reads what it installed."""
        package = sys.modules.get(_PACKAGE)
        assert package is not None, "conftest no longer installs a stand-in at all"
        assert hasattr(package, "__path__"), (
            f"the stand-in at {_PACKAGE} is a {type(package).__name__} with no __path__ — "
            "submodule imports under it cannot resolve, and the failure will surface far "
            "from here as somebody else's wrong answer"
        )

    def test_the_path_points_at_the_real_package_directory(self):
        """A ``__path__`` that resolves nowhere would satisfy the check above and nothing else."""
        package = sys.modules[_PACKAGE]
        real = _TESTS.parent / "apps" / "handlers" / "json"
        assert [Path(entry).resolve() for entry in package.__path__] == [real]
        assert (real / "memory_files.py").is_file(), "the directory the stand-in points at has no memory_files"

    def test_a_submodule_resolves_through_the_stand_in(self):
        """A submodule resolves through the stand-in via the same ``__import__`` a ``from`` import runs."""
        reached = __import__(f"{_PACKAGE}.memory_files", fromlist=["read_memory_file_data"])
        assert callable(reached.read_memory_file_data)
        assert reached.__name__ == f"{_PACKAGE}.memory_files"

    def test_the_mock_still_shadows_the_real_json_handler(self):
        """Carrying ``__path__`` must not quietly un-mock what the suite mocks."""
        from aipass.memory.apps.handlers.json import json_handler

        assert json_handler.log_operation("isolation-probe") is True
        assert type(json_handler).__name__ == "MagicMock"


class TestNobodyEvictsThePackageOneWay:
    """Guaranteed cleanup, enforced at the source; scoped to the impersonated package, not leaf modules."""

    def test_no_live_test_file_evicts_the_package_without_monkeypatch(self):
        assert not _bare_evictions_of_the_package(), (
            "bare sys.modules eviction of the impersonated package — use "
            "monkeypatch.delitem(sys.modules, name, raising=False) so the real module comes "
            "back at teardown:\n  " + "\n  ".join(_bare_evictions_of_the_package())
        )

    def test_the_scan_sees_the_prefix_loop_form_not_just_the_literal_name(self):
        """A prefix-loop eviction (name on the ``if`` line, ``del`` below) is seen, not just the literal."""
        loop = [
            "        for name in list(sys.modules):",
            '            if name.startswith("aipass.memory.apps.handlers.json"):',
            "                del sys.modules[name]",
        ]
        assert _scan_lines(loop) == [3], "the prefix-loop eviction is invisible to the scanner"

        literal = ['    sys.modules.pop("aipass.memory.apps.handlers.json", None)']
        assert _scan_lines(literal) == [1]

        safe = [
            '    for name in ("aipass.memory.apps.handlers.json",):',
            "        monkeypatch.delitem(sys.modules, name, raising=False)",
        ]
        assert _scan_lines(safe) == [], "monkeypatch.delitem must not be reported"

        unrelated = ['    sys.modules.pop("aipass.memory.apps.handlers.archive.indexer", None)']
        assert _scan_lines(unrelated) == [], "leaf-module pops are out of scope, not silently in it"

    def test_every_stand_in_installed_at_the_package_name_carries_a_path(self):
        """Every stand-in installed at the package name must be a package (a per-file check, not per call site)."""
        installs = re.compile(r"setitem\(sys\.modules,\s*\"" + re.escape(_PACKAGE) + r"\"\s*,\s*(\w+)\s*\)")
        offenders = []
        for path in sorted(_TESTS.glob("test_*.py")) + [_TESTS / "conftest.py"]:
            source = path.read_text(encoding="utf-8")
            for variable in set(installs.findall(source)):
                if f"{variable}.__path__" not in source:
                    offenders.append(f"{path.name}: {variable} is installed at {_PACKAGE} with no __path__")
        assert offenders == [], "package stand-ins that are not packages:\n  " + "\n  ".join(offenders)

    # Package stand-ins with no __path__, listed not fixed: several shadow their subtree on purpose,
    # so a blanket __path__ breaks tests. support_*.py is scanned because moved stand-ins land there.
    KNOWN_BARE_PACKAGE_STAND_INS = {
        "conftest.py::aipass.prax.apps.modules",
        "test_rollover.py::aipass.memory.apps.handlers",
        "test_rollover.py::aipass.memory.apps.handlers.cli",
        "test_rollover.py::aipass.memory.apps.handlers.intake",
        "test_rollover.py::aipass.memory.apps.handlers.monitor",
        "test_rollover.py::aipass.memory.apps.handlers.rollover",
        "test_rollover_pipeline.py::aipass.memory.apps.handlers.monitor",
        "test_rollover_pipeline.py::aipass.memory.apps.handlers.rollover",
        "test_rollover_pipeline_extraction.py::aipass.memory.apps.handlers.monitor",
        "test_rollover_pipeline_extraction.py::aipass.memory.apps.handlers.tracking",
        "support_symbolic_extras.py::aipass.memory.apps.handlers.vector",
    }

    def _bare_package_stand_ins(self):
        installs = re.compile(r"setitem\(sys\.modules,\s*\"([\w.]+)\"\s*,\s*([\w.]+)\s*\)")
        found_all = set()
        scanned = sorted(_TESTS.glob("test_*.py")) + sorted(_TESTS.glob("support_*.py")) + [_TESTS / "conftest.py"]
        for path in scanned:
            source = path.read_text(encoding="utf-8")
            found = installs.findall(source)
            names = {name for name, _ in found}
            for name, variable in found:
                impersonates_package = any(o != name and o.startswith(name + ".") for o in names)
                if impersonates_package and f"{variable}.__path__" not in source:
                    found_all.add(f"{path.name}::{name}")
        return found_all

    def test_no_new_package_stand_in_arrives_without_a_path(self):
        """No new package stand-in (a name the same file installs children under) arrives without __path__."""
        new = self._bare_package_stand_ins() - self.KNOWN_BARE_PACKAGE_STAND_INS
        assert new == set(), "new package stand-in with no __path__:\n  " + "\n  ".join(sorted(new))

    def test_the_inventory_does_not_outlive_what_it_inventories(self):
        """A stale allow-list is how a fixed thing stays 'known broken' forever."""
        stale = self.KNOWN_BARE_PACKAGE_STAND_INS - self._bare_package_stand_ins()
        assert stale == set(), "fixed — remove from KNOWN_BARE_PACKAGE_STAND_INS:\n  " + "\n  ".join(sorted(stale))

    @pytest.mark.parametrize("name", ["test_config_loader"])
    def test_the_converted_fixtures_still_use_delitem(self, name):
        """Named one by one: a fixture reverting to a bare pop is a silent relapse."""
        source = (_TESTS / f"{name}.py").read_text(encoding="utf-8")
        assert "monkeypatch.delitem(sys.modules" in source, f"{name}.py no longer restores what it evicts"
