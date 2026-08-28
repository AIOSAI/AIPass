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


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports to avoid live dependencies."""
    import sys

    # Mock prax logger
    mock_logger = MagicMock()
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
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
        if not (root / registry_scope.CORE_REGISTRY).is_file():
            pytest.skip(f"no {registry_scope.CORE_REGISTRY} at {root} -- live-state guard skipped")
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
