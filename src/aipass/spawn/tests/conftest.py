"""Shared test fixtures for spawn test suite."""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Registry backup/restore — prevents test ghost entries in AIPASS_REGISTRY.json
# ---------------------------------------------------------------------------


def _find_registry_path() -> Path:
    """Locate AIPASS_REGISTRY.json from the spawn branch."""
    return Path(__file__).resolve().parents[4] / "AIPASS_REGISTRY.json"


@pytest.fixture(autouse=True, scope="session")
def _protect_registry(tmp_path_factory):
    """Backup AIPASS_REGISTRY.json before the test session, restore after.

    Prevents tests that call spawn_agent/grant_passport without a
    registry_path override from permanently polluting the real registry.

    The backup lives under pytest's tmp dir, never beside the real registry:
    writing it into the repo root meant a crashed or killed suite orphaned an
    AIPASS_REGISTRY.json.test_backup there (flagged by @backup, APLAN-0007).
    """
    reg = _find_registry_path()
    backup = tmp_path_factory.mktemp("registry_backup") / "AIPASS_REGISTRY.json.test_backup"

    if reg.exists():
        shutil.copy2(reg, backup)

    yield

    if backup.exists():
        shutil.copy2(backup, reg)
        backup.unlink()


# ---------------------------------------------------------------------------
# Shipped-template guard — a test run must write NOTHING into templates/
# ---------------------------------------------------------------------------


def _shipped_templates_root() -> Path:
    """The template tree spawn ships, as it sits in the repo."""
    return Path(__file__).resolve().parents[1] / "templates"


def _template_tree_stats() -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) per file under templates/ — cheap enough to run per test.

    stat, not bytes: the failure this guards is a WRITE, and a write that
    happens to produce identical content is still a test reaching into the
    shipped tree. Bytes alone missed exactly that for months — a no-change
    regenerate only moved metadata.last_updated, which was identical whenever
    the run fell on the same UTC day as the committed date (PR #745).

    os.walk + os.stat rather than Path.rglob: this runs twice per test, and the
    pathlib version cost ~17ms a call against ~3.7ms here — 26s of suite time
    for the same answer.
    """
    root = _shipped_templates_root()
    if not root.is_dir():
        return {}

    stats: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            info = os.stat(full)
            stats[os.path.relpath(full, root)] = (info.st_size, info.st_mtime_ns)
    return stats


@pytest.fixture(autouse=True, scope="session")
def _restore_shipped_templates():
    """Session net: put the shipped template tree back if anything wrote to it.

    The per-test guard below names the culprit; this one makes sure a suite that
    fails does not also leave the working tree dirty for the next reader.
    """
    root = _shipped_templates_root()
    snapshot = {
        path: path.read_bytes() for path in root.rglob("*") if path.is_file() and "__pycache__" not in path.parts
    }

    yield

    for path, original in snapshot.items():
        if path.exists() and path.read_bytes() != original:
            path.write_bytes(original)


@pytest.fixture(autouse=True)
def _shipped_templates_are_read_only():
    """Fail any test that writes into the shipped template tree.

    Spawn's own templates are source, not scratch. A test that regenerates,
    copies into or otherwise touches templates/ is either missing a tmp_path
    redirect or has found a real escape in the code under test — both are bugs,
    and both used to surface only as a mystery diff in someone's git status.
    """
    before = _template_tree_stats()

    yield

    after = _template_tree_stats()
    touched = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    assert not touched, (
        "this test wrote into the SHIPPED template tree: "
        + ", ".join(touched)
        + " — redirect the template lookup into tmp_path, or fix the code path that escaped it"
    )


@pytest.fixture
def sample_data():
    """Pre-populated JSON test data for spawn operations."""
    return {
        "metadata": {"version": "1.0.0", "created": "2026-03-27"},
        "files": {"F001": {"path": "test.py", "hash": "abc123"}},
        "directories": {"D001": {"path": "apps/"}},
    }


@pytest.fixture
def mock_infrastructure(tmp_path):
    """Mock filesystem structure mimicking a spawned branch."""
    branch = tmp_path / "test_branch"
    for d in ["apps/modules", "apps/handlers", ".trinity", ".aipass"]:
        (branch / d).mkdir(parents=True)
    passport = {
        "branch_info": {"branch_name": "test_branch"},
        "identity": {"citizen_class": "specialist"},
    }
    (branch / ".trinity" / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
    return branch


@pytest.fixture
def mock_logger():
    """Mock aipass.prax logger for testing log calls."""
    with patch("aipass.prax.logger") as m:
        yield m


@pytest.fixture
def mock_json_handler():
    """Mock json_handler.log_operation at the call site in file_ops.

    Uses patch.object on the module reference held by file_ops to avoid
    stale-reference issues when other test suites reload json_handler.
    """
    import aipass.spawn.apps.handlers.file_ops as _fo

    with patch.object(_fo.json_handler, "log_operation") as m:
        m.return_value = True
        yield m


@pytest.fixture(autouse=True)
def _isolate_spawn_json(tmp_path):
    """Auto-isolate spawn_json directory to prevent test pollution."""
    import aipass.spawn.apps.handlers.json.json_handler as _jh

    iso_dir = tmp_path / "spawn_json"
    with patch.object(_jh, "_JSON_DIR", iso_dir), patch.object(_jh._handler, "_json_dir", iso_dir):
        yield
