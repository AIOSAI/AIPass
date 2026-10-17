# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for memory tests — write fence, infrastructure stand-ins, live-fleet guards
# Version: 1.3.0
# Created: 2026-03-07
# Modified: 2026-10-17
# Category: memory/tests
# =============================================

"""Shared pytest fixtures for memory tests."""

import os
import tempfile

# Must be set before any prax import, or the logger initialises against the real log dir.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import pytest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Generator
from unittest.mock import MagicMock

# Captured before any mock: the branch json shim binds `from aipass.prax import json_handler`,
# so the prax stand-in below must carry it or a reimport of the json package fails.
from aipass.prax import json_handler as _prax_json_service

# Captured at collection so no test's sys.modules stand-in can shadow it.
from aipass.memory.apps.handlers import write_fence as _write_fence
from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.apps.handlers.templates import trinity_push
from aipass.cli.apps.modules import display
from aipass.memory.tests.support_config_verbs import _real_verbs

# Nothing under .archive/ is a test.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True)
def _the_write_fence_stands_at_pytests_temp_root(tmp_path_factory, monkeypatch):
    """Point the write fence at pytest's base temp dir for every test.

    tmp writes pass and a test that writes the real repo is REFUSED; never cure a trip by widening the fence.
    """
    monkeypatch.setattr(_write_fence, "ROOT", tmp_path_factory.getbasetemp().resolve())


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports to avoid live dependencies."""
    import sys

    mock_logger = MagicMock()
    # A stand-in at a PACKAGE name must answer __path__ (see test_import_isolation.py).
    prax_mod = ModuleType("aipass.prax")
    prax_mod.__path__ = [str(Path(__file__).resolve().parents[2] / "prax")]
    prax_mod.logger = mock_logger  # type: ignore[attr-defined]
    prax_mod.json_handler = _prax_json_service  # type: ignore[attr-defined]
    prax_modules_mod = MagicMock()
    prax_modules_mod.logger = MagicMock()
    prax_modules_mod.logger.get_system_logger = MagicMock(return_value=mock_logger)
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", prax_modules_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_modules_mod.logger)

    # A real module with the real __path__, not a MagicMock: a lazy `from ...handlers.json.<sub>`
    # must resolve, while the set `json_handler` attribute still shadows the submodule.
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = ModuleType("aipass.memory.apps.handlers.json")
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)

    mock_trigger = MagicMock()
    mock_trigger.fire = MagicMock()
    trigger_mod = MagicMock()
    trigger_mod.Trigger = mock_trigger
    monkeypatch.setitem(sys.modules, "aipass.trigger", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)


@pytest.fixture
def live_fleet():
    """The real installation's repo root, or SKIP if this machine has no fleet.

    An empty registry is the absence of a measurement, not a pass. BOTH lanes' roots are checked.
    """
    for root in (registry_scope.REPO_ROOT, trinity_push._REPO_ROOT):
        registry = root / registry_scope.CORE_REGISTRY
        if not registry.is_file():
            pytest.skip(f"no {registry_scope.CORE_REGISTRY} at {root} -- live-state guard skipped")
        if not _registry_branch_rows(registry):
            pytest.skip(f"{registry_scope.CORE_REGISTRY} at {root} has no branch rows -- live-state guard skipped")
    return registry_scope.REPO_ROOT


@pytest.fixture
def live_residents(live_fleet):
    """A repo root that ALSO carries the four resident projects, or SKIP.

    Literal paths read with pathlib, never through the resolver: asking the code under test
    whether its inputs exist would turn every resolver regression into a SKIP.
    """
    expected = (
        "projects/baud/BAUD_REGISTRY.json",
        "projects/earmark/EARMARK_REGISTRY.json",
        "projects/finch/FINCH_REGISTRY.json",
        "projects/aipass-site/AIPASS-SITE_REGISTRY.json",
    )
    missing = [relative for relative in expected if not (live_fleet / relative).is_file()]
    if missing:
        pytest.skip(
            f"{len(missing)} of {len(expected)} resident registries "
            f"not installed at {live_fleet} ({', '.join(missing)}) -- live-state guard skipped"
        )
    return live_fleet


@pytest.fixture
def live_all_tiers(live_residents):
    """A root carrying ALL THREE tiers, each read by hand (never via registry_scope), or SKIP naming the absent tier."""
    anchor = live_residents / registry_scope.DECLARED_ROOTS
    if not anchor.is_file():
        pytest.skip(
            f"no {registry_scope.DECLARED_ROOTS} at {live_residents} "
            f"-- no external tier declared, live-state guard skipped"
        )

    try:
        declared = json.loads(anchor.read_text(encoding="utf-8")).get("roots", [])
    except (OSError, ValueError, AttributeError) as exc:
        pytest.skip(f"unreadable {registry_scope.DECLARED_ROOTS} at {anchor} ({exc}) -- guard skipped")

    if not _an_external_citizen_exists(live_residents, declared):
        pytest.skip(
            f"{registry_scope.DECLARED_ROOTS} declares {len(declared)} root(s) but no reachable "
            f"external citizen -- the third tier is absent, live-state guard skipped"
        )
    return live_residents


def _registry_branch_rows(registry_path):
    """Branch rows in a registry file (list or name-keyed dict), or [] — NEVER an exception."""
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    branches = data.get("branches", [])
    if isinstance(branches, dict):
        return [row for row in branches.values() if isinstance(row, dict)]
    if isinstance(branches, list):
        return [row for row in branches if isinstance(row, dict)]
    return []


def _an_external_citizen_exists(repo_root, declared):
    """True when a declared root really holds a citizen, walked as shallow as the resolver walks."""
    for row in declared:
        if not isinstance(row, dict):
            continue
        raw = row.get("path", "")
        if not raw:
            continue
        root = Path(raw) if Path(raw).is_absolute() else (repo_root / raw)
        if not root.is_dir():
            continue
        for registry in sorted(root.glob("*_REGISTRY.json")):
            for entry in _registry_branch_rows(registry):
                branch_path = entry.get("path", "")
                if branch_path and (root / branch_path / ".trinity" / "passport.json").is_file():
                    return True
    return False


@pytest.fixture
def case_insensitive_filesystem(monkeypatch):
    """Make ``Path.glob`` match the way Windows and macOS match.

    Pins the widened match on Linux, not a skipif; ``fnmatchcase`` because ``fnmatch`` consults the host.
    """
    import fnmatch

    real_glob = Path.glob

    def widened(self, pattern, *args, **kwargs):
        if "**" in pattern:
            return real_glob(self, pattern, *args, **kwargs)
        current = [self]
        for part in pattern.split("/"):
            nxt = []
            for base in current:
                if base.is_dir():
                    nxt.extend(
                        child for child in base.iterdir() if fnmatch.fnmatchcase(child.name.lower(), part.lower())
                    )
            current = nxt
        return iter(sorted(current))

    monkeypatch.setattr(Path, "glob", widened)
    return widened


@pytest.fixture
def case_insensitive_exists(monkeypatch):
    """Make ``Path.exists`` case-fold as Windows does; it only ever ADDS a True, so a global patch is safe."""
    import os as _os

    real_exists = Path.exists

    def folded(self, *args, **kwargs):
        if real_exists(self, *args, **kwargs):
            return True
        try:
            with _os.scandir(self.parent) as entries:
                return any(entry.name.lower() == self.name.lower() for entry in entries)
        except OSError:
            return False

    monkeypatch.setattr(Path, "exists", folded)
    return folded


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture
def verbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real config_loader + rollover module wired to a MINTED config and registry (see :func:`_real_verbs`)."""
    return _real_verbs(tmp_path, monkeypatch)
