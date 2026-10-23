# =================== AIPass ====================
# Name: conftest.py
# Description: Shared test fixtures for spawn test suite
# Version: 1.3.0
# Created: 2026-03-07
# Modified: 2026-10-22
# =============================================

"""Shared test fixtures for spawn test suite."""

import os
import tempfile

# Must be set before any prax import, or the logger initializes against the live log dir.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aipass.spawn.apps.handlers.file_ops as file_ops
from aipass.cli.apps.modules import display


def _find_registry_path() -> Path:
    """Locate AIPASS_REGISTRY.json from the spawn branch."""
    return Path(__file__).resolve().parents[4] / "AIPASS_REGISTRY.json"


@pytest.fixture(autouse=True, scope="session")
def _live_registry_is_never_written():
    """Fail the session if any test moved the live AIPASS_REGISTRY.json.

    Watches bytes and mtime; on a move it puts the bytes back, then fails."""
    reg = _find_registry_path()
    if not reg.exists():
        yield
        return
    before = reg.read_bytes()
    mtime = reg.stat().st_mtime_ns

    yield

    after = reg.read_bytes() if reg.exists() else b""
    moved = after != before or not reg.exists() or reg.stat().st_mtime_ns != mtime
    if moved:
        reg.write_bytes(before)
        pytest.fail(
            "a test wrote the live AIPASS_REGISTRY.json - hand the product a tmp_path registry",
            pytrace=False,
        )


# Only the root .archive is skipped: templates/citizen/dropbox and .archive are shipped content, watched.
_WALK_SKIP_DIRS = frozenset({"__pycache__"})
_ROOT_ARCHIVE = ".archive"


def _walk_skips(relative_parts: tuple[str, ...]) -> bool:
    """True for a path under templates/.archive or any __pycache__."""
    return bool(relative_parts) and (
        relative_parts[0] == _ROOT_ARCHIVE or bool(_WALK_SKIP_DIRS.intersection(relative_parts))
    )


def _shipped_templates_root() -> Path:
    """The template tree spawn ships, as it sits in the repo."""
    return Path(__file__).resolve().parents[1] / "templates"


def _template_tree_stats(root: Path | None = None) -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) per file under templates/ — cheap enough to run per test.

    stat, not bytes: a write of identical content is still a write. os.walk, not rglob: runs twice per test."""
    root = root if root is not None else _shipped_templates_root()
    if not root.is_dir():
        return {}

    stats: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        at_root = dirpath == str(root)
        dirnames[:] = [
            name for name in dirnames if name not in _WALK_SKIP_DIRS and not (at_root and name == _ROOT_ARCHIVE)
        ]
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            info = os.stat(full)
            stats[os.path.relpath(full, root)] = (info.st_size, info.st_mtime_ns)
    return stats


def _template_snapshot(root: Path) -> dict[Path, bytes]:
    """Bytes per file under root — what the session net puts back."""
    return {
        path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not _walk_skips(path.relative_to(root).parts)
    }


@pytest.fixture(autouse=True, scope="session")
def _restore_shipped_templates():
    """Session net: put the shipped template tree back if anything wrote to it."""
    snapshot = _template_snapshot(_shipped_templates_root())

    yield

    for path, original in snapshot.items():
        if path.exists() and path.read_bytes() != original:
            path.write_bytes(original)


@pytest.fixture(autouse=True)
def _shipped_templates_are_read_only():
    """Fail any test that writes into the shipped template tree."""
    before = _template_tree_stats()

    yield

    after = _template_tree_stats()
    touched = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    assert not touched, (
        "this test wrote into the SHIPPED template tree: "
        + ", ".join(touched)
        + " — redirect the template lookup into tmp_path, or fix the code path that escaped it"
    )


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


class _BusRecorder:
    """Stands where display._TRIGGER stands: records each fire, answers like an idle bus."""

    def __init__(self) -> None:
        self.fired: list[tuple[str, dict[str, Any]]] = []

    def fire(self, event: str, **data: Any) -> dict[str, Any]:
        """Record one fire; nothing is dispatched."""
        self.fired.append((event, data))
        return {"event": event, "handlers": 0, "ran": 0, "failed": 0}


@pytest.fixture(autouse=True)
def cli_trigger_bus(monkeypatch) -> _BusRecorder:
    """Every test's cli header fires into a recorder, never the real trigger bus.

    _TRIGGER_LOADED=True stops display's lazy import of the real trigger."""
    recorder = _BusRecorder()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return recorder


@pytest.fixture(autouse=True)
def clean_command_state():
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture
def mock_logger():
    """Mock the logger that ``file_ops`` actually calls.

    Patch the consuming module: file_ops copied the logger at import, so patching aipass.prax mocks nothing."""
    with patch("aipass.spawn.apps.handlers.file_ops.logger") as m:
        yield m


@pytest.fixture
def mock_json_handler():
    """Mock json_handler.log_operation at the call site in file_ops.

    patch.object on file_ops' own reference survives other suites reloading json_handler."""
    with patch.object(file_ops.json_handler, "log_operation") as m:
        m.return_value = True
        yield m


@pytest.fixture(autouse=True)
def _isolate_spawn_json(tmp_path, monkeypatch) -> Path:
    """Auto-isolate spawn_json directory to prevent test pollution.

    The json service recomputes its dir from AIPASS_TEST_LOG_DIR on every call, so setting it late works."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    # Delete and retire write drone's deletion trail and revoke hooks trust; both owners read these at call time.
    monkeypatch.setenv("AIPASS_DELETION_LOG", str(tmp_path / "deletions.jsonl"))
    monkeypatch.setenv("AIPASS_TRUST_REGISTRY", str(tmp_path / "trusted_projects.json"))
    return tmp_path / "spawn" / "spawn_json"


MACHINE_REGISTRY_ID = "11111111-1111-4111-8111-111111111111"
MACHINE_CITIZEN_ID = "22222222-2222-4222-8222-222222222222"


def make_passport(branch: str = "wanderer") -> dict:
    """A live 2.0 passport, in canonical order — the shape the fleet carries.

    Lives here so test_cli_routing.py still collects when test_passport_seeds.py cannot import."""
    return {
        "document_metadata": {
            "document_type": "branch_identity",
            "document_name": f"{branch}.PASSPORT",
            "version": "2.0.0",
            "schema_version": "2.0.0",
            "created": "2026-03-05",
            "last_updated": "2026-08-28",
            "managed_by": branch,
            "tags": ["identity", "passport", "branch_profile"],
        },
        "branch_info": {
            "branch_name": branch,
            "alias": "",
            "path": f"src/aipass/{branch}",
            "module": f"aipass.{branch}",
            "email": f"@{branch}",
            "created": "2026-03-05",
            "git_branch": "dev",
        },
        "citizenship": {
            "registered": True,
            "residency": "core",
            "registry_id": MACHINE_REGISTRY_ID,
            "citizen_id": MACHINE_CITIZEN_ID,
            "registry_path": ".aipass/registry.json",
            "communications": True,
            "memory": True,
        },
        "identity": {
            "citizen_class": "specialist",
            "role": "wanderer",
            "purpose": "Walks the fleet — an identity worth shipping.",
            "what_i_do": ["Walk", "Report"],
            "what_i_dont_do": ["Guess"],
            "traits": ["curious"],
            "principles": ["Code is truth - fail honestly"],
        },
    }
