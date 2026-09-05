# =================== AIPass ====================
# Name: test_import_isolation.py
# Description: Pins against sys.modules poisoning of the handlers.json package
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""The suite is allowed to mock the world. It is not allowed to leave it broken.

WHAT HAPPENED (PR 743, run on ab9a1721 — a commit whose only diff was version
strings). Two receipt tests in ``test_trinity_standard.py`` failed on ubuntu
3.13, on that run only, having passed 3.13 one run earlier and 3.10/3.11/3.12 on
that same run::

    assert (0, ['memory/local.json: No module named
    aipass.memory.apps.handlers.json.memory_files -
    aipass.memory.apps.handlers.json is not a package']) == (1, [])

Read precisely, that message says the import machinery found SOMETHING at the
name ``aipass.memory.apps.handlers.json`` that has no ``__path__`` — a module
object standing where a package belongs. Two independent facts had to line up:

1. ``conftest._mock_infrastructure`` (autouse, so it is active in every test in
   this suite) installed a bare ``MagicMock`` at that PACKAGE name. A MagicMock
   does not answer ``__path__``, so any lazy ``from ...handlers.json.<sub>
   import x`` executed inside a test could not resolve the submodule — unless
   the submodule was already cached in ``sys.modules``, which is what made this
   invisible for months.

2. NINE test files evicted the real package from ``sys.modules`` with a bare
   ``pop``/``del`` and never put it back. A bare pop is one-way: the eviction
   outlives the test and every later test in the same process inherits it. Once
   the cache was cold, the next lazy import landed on fact 1.

   Nine, not the four a first grep showed — the grep was truncated. The count
   is stated here because it is the whole argument for pinning at the source
   rather than fixing the file that happened to be named in the CI log.

``tab_renderer._refresh_one_file`` reports an import failure the same way it
reports a bad file — as a per-file error — so the whole thing surfaced as a
wrong COUNT pointing at the receipt renderer, which is not where the defect was.

The trigger was ORDER, not code, and xdist decides order by packing tests into
workers differently run to run. ``test_trinity_standard.py`` passed standalone
because a sibling test higher in the file happened to re-import ``memory_files``
on its way out and warmed the cache for the receipt tests below it.

Both facts are fixed and both are pinned here.
"""

import re
import sys
from pathlib import Path

import pytest


_TESTS = Path(__file__).resolve().parent
_PACKAGE = "aipass.memory.apps.handlers.json"

# A bare eviction naming its target outright: `sys.modules.pop("<name>"` or
# `del sys.modules["<name>"]`. The name is captured so an unrelated leaf module
# is not charged to the package just for sitting near it.
_LITERAL_EVICTION = re.compile(r"(?<!monkeypatch\.)(?:sys\.modules\.pop\(|del sys\.modules\[)\s*\"([^\"]+)\"")

# The same thing through a variable — `del sys.modules[name]` in a loop. The
# target is unknowable from the line, so the lookback below decides.
_VARIABLE_EVICTION = re.compile(r"(?<!monkeypatch\.)(?:sys\.modules\.pop\(|del sys\.modules\[)\s*[A-Za-z_]")

# How far above a VARIABLE eviction the package name may sit and still be taken
# as its target. Three lines covers `for` / `if name.startswith(...)` / `del`.
_LOOKBACK = 3


def _scan_lines(lines: list[str]) -> list[int]:
    """1-based line numbers where a bare eviction targets the impersonated package.

    Two forms, judged differently on purpose. A literal is judged on the name it
    actually names — proximity does not make ``...handlers.rollover.extractor``
    an eviction of ``...handlers.json``. A variable eviction names nothing, so
    it is judged on the window above it, which is the only place the target can
    be written.
    """
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
    """Every live test file's bare evictions of the package, as reportable strings.

    This file is skipped: it quotes both eviction forms as sample text to prove
    the scanner sees them, and a scanner that flagged its own fixtures would be
    reporting itself forever. Said out loud rather than filtered quietly — the
    logic it would otherwise cover is exercised directly by ``_scan_lines``.
    """
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
        """The property that actually matters, exercised the way the renderer does it.

        ``__import__(..., fromlist=[...])`` is exactly what the bytecode for
        ``from X.memory_files import read_memory_file_data`` runs, so this fails
        for the same reason the renderer would rather than for a similar one.
        """
        reached = __import__(f"{_PACKAGE}.memory_files", fromlist=["read_memory_file_data"])
        assert callable(reached.read_memory_file_data)
        assert reached.__name__ == f"{_PACKAGE}.memory_files"

    def test_the_mock_still_shadows_the_real_json_handler(self):
        """Carrying ``__path__`` must not quietly un-mock what the suite mocks.

        A set attribute wins over a submodule import in ``from X import y``, so
        the mock is still what every test gets — if that ever stops being true
        the suite starts doing real disk I/O and this says so first.
        """
        from aipass.memory.apps.handlers.json import json_handler

        assert json_handler.log_operation("isolation-probe") is True
        assert type(json_handler).__name__ == "MagicMock"


class TestNobodyEvictsThePackageOneWay:
    """Guaranteed cleanup, enforced at the source so the next one cannot arrive quietly.

    Scoped to names under the impersonated package — the exact class that
    produced the CI red. REPORTED, NOT FIXED, and deliberately out of scope for
    a CI unblock: roughly a dozen other test files bare-pop LEAF modules
    (``...handlers.archive.indexer``, ``...modules.symbolic``, and others).
    Those leak an eviction too, but their parents are real packages, so a later
    import re-resolves and no wrong answer follows. Same shape, different blast
    radius; it is @devpulse's call whether that gets its own pass.
    """

    def test_no_live_test_file_evicts_the_package_without_monkeypatch(self):
        assert not _bare_evictions_of_the_package(), (
            "bare sys.modules eviction of the impersonated package — use "
            "monkeypatch.delitem(sys.modules, name, raising=False) so the real module comes "
            "back at teardown:\n  " + "\n  ".join(_bare_evictions_of_the_package())
        )

    def test_the_scan_sees_the_prefix_loop_form_not_just_the_literal_name(self):
        """The shape that hid the second poisoner, checked against the scanner itself.

        ``test_trinity_standard.py`` evicted by PREFIX — ``del sys.modules[name]``
        inside a loop over everything starting with the package name. The literal
        package string is on the ``if`` line; the eviction is two lines below it.
        A scan demanding both on ONE line calls that file clean, and calling it
        clean is exactly the reading that let it survive.

        So the scanner carries a lookback window, and this drives real source
        text through it rather than asserting the regex in isolation — a regex
        that matches proves nothing about the function that has to use it.
        """
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
        """Thirteen places install a stand-in at that name. All thirteen must be packages.

        Conftest's is the one that was live when CI went red, but it is not the
        only one: twelve more sit in individual test modules, each installing a
        MagicMock at the PACKAGE name for the duration of one test. Those are
        monkeypatched, so they cannot leak — they are a hazard only for a lazy
        submodule import inside their own test, which is precisely the shape
        that stayed invisible here until worker packing changed.

        A per-FILE check: it confirms the file assigns ``__path__`` on the name
        it installs, not that it does so on every path through the file. Stated
        rather than implied — the finer check would need an AST walk per call
        site, and the coarse one already fails the moment a new bare MagicMock
        arrives.
        """
        installs = re.compile(r"setitem\(sys\.modules,\s*\"" + re.escape(_PACKAGE) + r"\"\s*,\s*(\w+)\s*\)")
        offenders = []
        for path in sorted(_TESTS.glob("test_*.py")) + [_TESTS / "conftest.py"]:
            source = path.read_text(encoding="utf-8")
            for variable in set(installs.findall(source)):
                if f"{variable}.__path__" not in source:
                    offenders.append(f"{path.name}: {variable} is installed at {_PACKAGE} with no __path__")
        assert not offenders, "package stand-ins that are not packages:\n  " + "\n  ".join(offenders)

    # Measured 2026-08-30. Every stand-in installed at a name this suite ALSO
    # installs children under — i.e. impersonating a package — while carrying no
    # __path__. Sixteen of them. They are listed rather than fixed because the
    # mechanical fix (assign __path__) broke 41 tests in one pass: several of
    # these shadow their whole subtree ON PURPOSE, and telling them apart is a
    # per-file reading, not a sed. Named so a SEVENTEENTH cannot arrive quietly.
    KNOWN_BARE_PACKAGE_STAND_INS = {
        "conftest.py::aipass.prax.apps.modules",
        "test_orchestrator_exec.py::aipass.memory.apps.handlers.monitor",
        "test_orchestrator_exec.py::aipass.memory.apps.handlers.tracking",
        "test_rollover.py::aipass.memory.apps.handlers",
        "test_rollover.py::aipass.memory.apps.handlers.cli",
        "test_rollover.py::aipass.memory.apps.handlers.intake",
        "test_rollover.py::aipass.memory.apps.handlers.monitor",
        "test_rollover.py::aipass.memory.apps.handlers.rollover",
        "test_rollover_pipeline.py::aipass.memory.apps.handlers.monitor",
        "test_rollover_pipeline.py::aipass.memory.apps.handlers.rollover",
        "test_rollover_pipeline.py::aipass.memory.apps.handlers.tracking",
        "test_symbolic.py::aipass.memory.apps.handlers.symbolic",
        "test_symbolic_cli.py::aipass.memory.apps.handlers.symbolic",
        "test_symbolic_extras.py::aipass.memory.apps.handlers.vector",
        "test_symbolic_module.py::aipass.memory.apps.handlers.symbolic",
    }

    def _bare_package_stand_ins(self):
        installs = re.compile(r"setitem\(sys\.modules,\s*\"([\w.]+)\"\s*,\s*([\w.]+)\s*\)")
        found_all = set()
        for path in sorted(_TESTS.glob("test_*.py")) + [_TESTS / "conftest.py"]:
            source = path.read_text(encoding="utf-8")
            found = installs.findall(source)
            names = {name for name, _ in found}
            for name, variable in found:
                impersonates_package = any(o != name and o.startswith(name + ".") for o in names)
                if impersonates_package and f"{variable}.__path__" not in source:
                    found_all.add(f"{path.name}::{name}")
        return found_all

    def test_no_NEW_package_stand_in_arrives_without_a_path(self):
        """The rule above was written for one package. The defect had seventeen.

        `aipass.prax` was a bare MagicMock in conftest, six lines above the json
        stand-in that carries `__path__` and a paragraph explaining why it must.
        One package learned the lesson; the other sat beside it, because the pin
        named a CONSTANT instead of a SHAPE. Widening the shape found fourteen
        more in six other files.

        `aipass.prax` is fixed. The rest are inventoried above, not swept: they
        are a real backlog and this test says so out loud rather than passing as
        if the suite were clean. What it defends is the edge — a new one cannot
        be added without either fixing it or consciously adding a line here.

        A name counts as a PACKAGE when the same file also installs something
        beneath it, so a package added tomorrow is covered without editing this.
        """
        new = self._bare_package_stand_ins() - self.KNOWN_BARE_PACKAGE_STAND_INS
        assert not new, "new package stand-in with no __path__:\n  " + "\n  ".join(sorted(new))

    def test_the_inventory_does_not_outlive_what_it_inventories(self):
        """A stale allow-list is how a fixed thing stays 'known broken' forever."""
        stale = self.KNOWN_BARE_PACKAGE_STAND_INS - self._bare_package_stand_ins()
        assert not stale, "fixed — remove from KNOWN_BARE_PACKAGE_STAND_INS:\n  " + "\n  ".join(sorted(stale))

    @pytest.mark.parametrize("name", ["test_tab_renderer", "test_config_loader"])
    def test_the_converted_fixtures_still_use_delitem(self, name):
        """Named one by one: a fixture reverting to a bare pop is a silent relapse.

        test_json_handler was a third here until DPLAN-0325: its old fixture
        evicted the json package to reimport the shared handler. The shim wiring
        test that replaced it evicts nothing - it measures the live service off
        the AIPASS_TEST_LOG_DIR seam - so there is nothing left to restore, and
        it dropped off this list rather than carrying a delitem it does not use.
        """
        source = (_TESTS / f"{name}.py").read_text(encoding="utf-8")
        assert "monkeypatch.delitem(sys.modules" in source, f"{name}.py no longer restores what it evicts"
