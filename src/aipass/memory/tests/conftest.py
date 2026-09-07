# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2026-03-24
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Shared pytest fixtures for memory tests."""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import pytest
import shutil
from pathlib import Path
from types import ModuleType
from typing import Generator
from unittest.mock import MagicMock

# The fleet's one json service (prax-owned), captured once at collection while
# AIPASS_TEST_LOG_DIR is already set above. The branch shim binds this - it does
# `from aipass.prax import json_handler` - so the prax stand-in in the autouse
# fixture below must carry it, or any test that reimports the json package (the
# _fresh_module pattern) would hit ImportError on a mocked prax (DPLAN-0325).
# It is stdlib-only and resolves its directory per call, so holding it here is
# safe and lets mock_infrastructure measure the true sandbox off the live service.
from aipass.prax import json_handler as _prax_json_service

# The branch shim's own file, so the service can resolve memory's json directory
# the way the shim does, without importing (and caching) the memory json package
# at collection.
_SHIM_FILE = str(Path(__file__).resolve().parents[1] / "apps" / "handlers" / "json" / "json_handler.py")

# Nothing under .archive/ is a test: the old handler and the subsumed tests live
# there as gitignored disposal (DPLAN-0325). Keep pytest from discovering them.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports to avoid live dependencies."""
    import sys

    # Mock prax logger
    mock_logger = MagicMock()
    # A stand-in at a PACKAGE name must answer __path__, exactly as the json
    # stand-in below does and for the same reason. This one sat six lines above
    # that paragraph, unfixed, because the pin naming the rule named a constant
    # instead of a shape — see test_import_isolation.py.
    prax_mod = ModuleType("aipass.prax")
    prax_mod.__path__ = [str(Path(__file__).resolve().parents[2] / "prax")]
    prax_mod.logger = mock_logger  # type: ignore[attr-defined]
    # The branch json shim binds `from aipass.prax import json_handler`; the
    # stand-in must carry it so a fresh shim import under this mock resolves the
    # real, stdlib-only service instead of failing (DPLAN-0325).
    prax_mod.json_handler = _prax_json_service  # type: ignore[attr-defined]
    prax_modules_mod = MagicMock()
    prax_modules_mod.logger = MagicMock()
    prax_modules_mod.logger.get_system_logger = MagicMock(return_value=mock_logger)
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", prax_modules_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_modules_mod.logger)

    # Mock json handler.
    #
    # The PACKAGE name is impersonated by a real module object carrying the
    # real package's __path__ -- deliberately not a MagicMock. A MagicMock has
    # no __path__, so any lazy `from ...handlers.json.<sub> import x` executed
    # while this fixture is active dies with ModuleNotFoundError("...handlers
    # .json is not a package") instead of reaching the submodule.
    #
    # That was invisible for as long as the submodule happened to be cached in
    # sys.modules from an earlier import, and RED the moment some earlier test
    # in the same process evicted it -- which is why it surfaced as two receipt
    # tests failing on ONE interpreter, in ONE xdist worker, on ONE run, with
    # no code change behind it. Order was the trigger; this was the hole.
    #
    # Carrying __path__ lets submodules resolve honestly against the real
    # directory while `json_handler` stays mocked -- the mock still shadows,
    # because a set attribute wins over a submodule import in `from X import y`.
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = ModuleType("aipass.memory.apps.handlers.json")
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)

    # Mock trigger
    mock_trigger = MagicMock()
    mock_trigger.fire = MagicMock()
    trigger_mod = MagicMock()
    trigger_mod.Trigger = mock_trigger
    monkeypatch.setitem(sys.modules, "aipass.trigger", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", trigger_mod)


@pytest.fixture
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect the shim's json writes into a temp dir, and return that dir.

    The DPLAN-0325 shim wiring test (test_json_handler.py) requests this to pin
    that get_json_path lands in the branch's redirected sandbox. Deliberately
    NOT autouse: the whole memory suite runs against the wholesale json_handler
    mock in ``_mock_infrastructure`` above, and only the wiring test wants the
    live service. The service recomputes its directory per call, so setting the
    seam here - after import - still takes effect, and the sandbox is measured
    off the real shim so it cannot drift from what the service does.

    The service spells the sandbox <seam>/<branch>/<branch>_json, so the seam is
    its own subdir of tmp_path rather than tmp_path itself, to avoid colliding
    with a test that builds a directory of the branch's own name.

    Returns:
        The sandbox directory the handler now writes into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    handle = _prax_json_service.for_module(_SHIM_FILE)
    sandbox = handle.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides reusable sample data for general test assertions."""
    return {
        "created": "2026-01-01",
        "last_updated": "2026-01-15",
        "entries": [
            {"id": 1, "name": "alpha", "status": "active"},
            {"id": 2, "name": "beta", "status": "pending"},
        ],
        "metadata": {
            "source": "test_fixture",
            "version": "1.0.0",
        },
    }


@pytest.fixture
def sample_memory_data() -> dict:
    """Provides sample memory file data (v2 schema)."""
    return {
        "document_metadata": {
            "document_type": "session_history",
            "document_name": "TEST.LOCAL",
            "version": "2.0.0",
            "schema_version": "2.0.0",
            "created": "2026-01-01",
            "last_updated": "2026-01-01",
            "managed_by": "TEST",
            "tags": ["test"],
            "limits": {"max_sessions": 20, "max_key_learnings": 25},
            "status": {"health": "healthy", "current_lines": 50},
        },
        "key_learnings": {"test_learning": "This is a test."},
        "sessions": [{"session_number": 1, "date": "2026-01-01", "summary": "Test session", "status": "completed"}],
    }


@pytest.fixture
def sample_registry_data() -> dict:
    """Provides sample AIPASS_REGISTRY.json data."""
    return {
        "branches": [
            {
                "name": "TEST_BRANCH",
                "path": "src/aipass/test_branch",
                "module": "aipass.test_branch",
                "email": "@test_branch",
                "status": "active",
            },
            {
                "name": "MEMORY",
                "path": "src/aipass/memory",
                "module": "aipass.memory",
                "email": "@memory",
                "status": "active",
            },
        ]
    }


@pytest.fixture
def temp_branch(tmp_path, sample_memory_data):
    """Create a minimal branch structure with .trinity/ files."""
    branch_dir = tmp_path / "src" / "aipass" / "test_branch"
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "local.json").write_text(json.dumps(sample_memory_data, indent=2), encoding="utf-8")
    (trinity / "passport.json").write_text(
        json.dumps(
            {
                "branch_info": {"branch_name": "test_branch", "path": "src/aipass/test_branch"},
                "identity": {"role": "test", "purpose": "testing"},
                "citizenship": {"registered": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (trinity / "observations.json").write_text(
        json.dumps({"document_metadata": {"document_type": "collaboration_patterns"}, "observations": []}, indent=2),
        encoding="utf-8",
    )
    return branch_dir


@pytest.fixture
def temp_registry(tmp_path, sample_registry_data):
    """Create a temporary AIPASS_REGISTRY.json."""
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(sample_registry_data, indent=2), encoding="utf-8")
    return registry_path


@pytest.fixture
def live_fleet():
    """The real installation's repo root, or SKIP if this machine has no fleet.

    A handful of tests are valuable precisely because they measure the fleet
    that exists — that the resident projects really are reachable, that
    `backup` resolves to its directory name and not the registry's `BACKUP`.
    Rebuilding those against a synthetic registry would test the parser and
    stop testing the fleet, so they are guarded rather than converted.

    The ground truth is `AIPASS_REGISTRY.json`, which is gitignored: a clean
    CI checkout has no registry and no citizen `.trinity/`, so every fleet
    lane resolves EMPTY there. Empty is not a measurement — it is the absence
    of one, and a test that reports green over it is claiming to have checked
    something it never saw.

    ONE discriminator, one place. Two copies of "is there a fleet here" would
    disagree within a release, and this is a fixture rather than an importable
    helper because a test module importing a sibling by dotted path resolves
    only on a branch-dir rootdir — red on CI's repo-root run, a trap this
    branch has already been caught by once.

    BOTH roots are checked, not one. `registry_scope` and `trinity_push` each
    resolve their own repo root, and the guarded tests are split across the
    two: on a real installation the walk-up finds the same registry for both,
    but a guard that checked only one would report "fleet present" while the
    other lane was blind — the same one-lane-sees-22-the-other-19 asymmetry
    this whole marker was built to close.

    Returns:
        The repo root holding the core registry.
    """
    from aipass.memory.apps.handlers.monitor import registry_scope
    from aipass.memory.apps.handlers.templates import trinity_push

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

    `live_fleet` answers "is aipass installed here". It is not enough for the
    resident assertions, and the Windows e2e lane proved it: that job installs
    aipass from the wheel, so it has a REAL `AIPASS_REGISTRY.json` and the core
    citizens — the guard correctly saw a live installation and let the tests
    run — and then `{earmark, finch, aipass_site, baud} <= names` failed,
    because those four live in `projects/` on ONE machine. "The residents are
    reachable" is a claim about an installation, not about the software.

    So the second discriminator is narrower: are the resident registry FILES
    on disk. Present and unreachable stays RED, which is the whole point.

    MEASURED WITH pathlib, NOT with `resident_registry_paths()`. Asking the
    code under test whether its own inputs exist would turn every regression
    in the resolver into a SKIP — the guard would delete the failure it exists
    to expose. The ground truth has to be read independently of the thing
    being judged.

    THE FOUR PATHS ARE LITERALS HERE, and that is the same argument one step
    further. They used to be read from `registry_scope.RESIDENT_REGISTRIES`,
    which was fine while that tuple was the definition. On 2026-08-28 the
    definition became a glob plus a passport field, and the tuple was deleted;
    reading the new discovery function instead would have handed the guard
    back to the code it guards. So the expected residents are written out
    here, in the guard, where a change to them is a deliberate edit to a test
    fixture rather than a silent consequence of a resolver change.

    Returns:
        The repo root holding the core registry and all four residents.
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
    """A repo root carrying ALL THREE tiers — core, resident AND external — or SKIP.

    `live_fleet` answers "is aipass installed here", `live_residents` adds "are
    the four resident projects on disk". Neither says anything about the
    external tier, and a test asserting on all three needs all three.

    CI on PR#750 is why this exists. A bare ubuntu checkout ships no registry
    and no `AIPASS_ROOTS.json` (both gitignored) and no `projects/`, so every
    tier but core resolves empty — and something in the whole-repo run MINTED a
    core-only registry mid-run. `live_fleet` asked "is there a registry" and
    there was, so the three-tier assertion ran in a one-tier world and reported
    the world's shape as a defect in the record.

    EXISTENCE IS NOT SUFFICIENCY. That is the whole lesson, and it applies to
    each tier separately: a registry can exist with no rows, a roots anchor can
    exist declaring nothing, and a declared root can exist holding no citizen.
    Each of those is a half-present world, and each gets its own reason here so
    a skip on CI names which tier was missing rather than "guard skipped".

    MEASURED WITH pathlib AND json, never through `registry_scope`. Asking the
    resolver whether its own inputs are sufficient would turn every regression
    in it into a SKIP — the guard deleting the failure it exists to expose.
    `declared_roots()` is the code these tests judge; reading the anchor by hand
    is what keeps the guard independent of it. Same argument as the literal
    resident paths above, one tier further out.

    Returns:
        The repo root carrying all three tiers.
    """
    from aipass.memory.apps.handlers.monitor import registry_scope

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
    """Branch rows in a registry file, or an empty list — NEVER an exception.

    A guard that raises is worse than a guard that skips: it turns "this
    machine has no fleet" into a red nobody can act on. Corrupt is absence.

    Both registry shapes are read because both ship: `branches` is a list on
    some registries and a name-keyed dict on others, and a guard that knew only
    one would call half the fleet empty.
    """
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
    """True when some declared root really holds a citizen, read off disk.

    A declaration is not a citizen — `AIPASS_ROOTS.json` can name four sibling
    repositories and every one of them be gone, which on a fresh machine is the
    normal case. The tier is present only if a passport is actually reachable
    through one of them.

    Deliberately shallow, mirroring the walk law the resolver obeys: a
    registry at the root's top level, then that registry's own branches. A
    recursive passport hunt here would make the guard find citizens the code
    under test would refuse to.
    """
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

    THE CONDITION BEING PINNED IS "the glob returned more than the pattern
    spells", not "the test is running on Windows". @drone hit this on the
    Windows CI leg — ``*_REGISTRY.json`` also matched a real lowercase file in
    their tree — and a skipif here would mean the pin only ever fires on the
    one platform where the defect has already shipped. Injecting the widened
    match runs the same code path on the Linux dev box, red-first, before CI.

    The emulation is deliberately literal: split the pattern on ``/``, walk one
    level per part, compare case-folded. ``fnmatchcase`` on lowered strings
    rather than ``fnmatch``, because ``fnmatch`` itself consults the host
    platform and would make this fixture a no-op on the box that needs it most.
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
    """Make ``Path.exists`` answer about a case-folded name, as Windows does.

    @seedgo published this as their own discriminator's blind spot and it is the
    worse half of the pair: ``(dir / "AIPASS_REGISTRY.json").exists()`` reads a
    lowercase file with no glob in the line to warn a reader.

    The emulation only ever ADDS a True — an exact hit still answers exactly —
    so patching it globally cannot break the machinery around the test the way a
    replacement implementation would.
    """
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
