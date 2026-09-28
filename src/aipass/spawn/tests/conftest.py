# =================== AIPass ====================
# Name: conftest.py
# Description: Shared test fixtures for spawn test suite
# Version: 1.2.1
# Created: 2026-03-07
# Modified: 2026-09-28
# =============================================

"""Shared test fixtures for spawn test suite."""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aipass.spawn.apps.handlers.file_ops as file_ops
from aipass.cli.apps.modules import display


# ---------------------------------------------------------------------------
# Live registry tripwire — no test reads or writes AIPASS_REGISTRY.json
# ---------------------------------------------------------------------------


def _find_registry_path() -> Path:
    """Locate AIPASS_REGISTRY.json from the spawn branch."""
    return Path(__file__).resolve().parents[4] / "AIPASS_REGISTRY.json"


@pytest.fixture(autouse=True, scope="session")
def _live_registry_is_never_written():
    """Fail the session if any test moved the live AIPASS_REGISTRY.json.

    This used to be a backup-and-restore (_protect_registry). A restore is a
    repair, not a seal: a run killed midway left whatever a test had written,
    and copy2 put the old mtime back, so a rewrite of equal bytes never showed.
    Every test now hands the product a tmp_path registry (DPLAN-0354 leg 2).
    This fixture only watches: sha256 and mtime before, the same after. On a
    move it puts the bytes back so the fleet keeps its citizens, and fails.
    """
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


# ---------------------------------------------------------------------------
# Shipped-template guard — a test run must write NOTHING into templates/
# ---------------------------------------------------------------------------


# What the template-tree walks below never enter. dropbox and .archive are
# sandboxes: nothing looks into one (spawn's decision, DPLAN-0354 leg 3). Both
# names come from seedgo's SOURCE_SKIP_DIRS
# (seedgo/apps/handlers/aipass_standards/skip_dirs.py), copied rather than
# imported: seedgo's handlers package guards cross-branch imports at import
# time. Not the whole list either: it also names .spawn, .trinity, docs, tools,
# logs and artifacts, which are shipped template content these guards exist to
# watch — .spawn/.template_registry.json above all (PR #745).
_WALK_SKIP_DIRS = frozenset({"__pycache__", "dropbox", ".archive"})


def _shipped_templates_root() -> Path:
    """The template tree spawn ships, as it sits in the repo."""
    return Path(__file__).resolve().parents[1] / "templates"


def _template_tree_stats(root: Path | None = None) -> dict[str, tuple[int, int]]:
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
    root = root if root is not None else _shipped_templates_root()
    if not root.is_dir():
        return {}

    stats: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _WALK_SKIP_DIRS]
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            info = os.stat(full)
            stats[os.path.relpath(full, root)] = (info.st_size, info.st_mtime_ns)
    return stats


def _template_snapshot(root: Path) -> dict[Path, bytes]:
    """Bytes per file under root — what the session net puts back.

    Parts are read relative to root, so a checkout that itself sits under a
    directory named like a sandbox is still walked.
    """
    return {
        path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not _WALK_SKIP_DIRS.intersection(path.relative_to(root).parts)
    }


@pytest.fixture(autouse=True, scope="session")
def _restore_shipped_templates():
    """Session net: put the shipped template tree back if anything wrote to it.

    The per-test guard below names the culprit; this one makes sure a suite that
    fails does not also leave the working tree dirty for the next reader.
    """
    snapshot = _template_snapshot(_shipped_templates_root())

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

    display.header() lazy-loads the real trigger behind _TRIGGER_LOADED and
    fires cli_header_displayed through _TRIGGER; the bus probe (2026-09-27)
    counted 12 such fires reaching the real bus from spawn's suite. Autouse, so
    no test can forget it, and no file of cli is touched: _TRIGGER_LOADED=True
    stops the lazy import, _TRIGGER is the recorder (spawn's decision,
    DPLAN-0354 leg 3). tests/test_conftest_fixtures.py pins it.
    """
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

    MEASURED by @memory and reproduced by @seedgo (2026-08-30): the previous
    spelling, ``patch("aipass.prax.logger")``, reached NOTHING. ``file_ops``
    does ``from aipass.prax.apps.modules.logger import system_logger as logger``
    at import, so the object is copied into its globals before any fixture runs
    — and ``aipass/prax/__init__.py`` copies it once more one level up. Patching
    at or above ``aipass.prax`` is always upstream of a copy already taken, so
    every test using this fixture was talking to a mock nobody consults while
    the real SystemLogger kept writing into @prax's live state directory.

    The rule underneath: THE LAST DOT MUST BE RESOLVED AT CALL TIME. So the
    patch names the CONSUMING module. ``tests/test_conftest_fixtures.py`` pins
    that this fixture reaches ``file_ops.logger`` by object identity, so a
    future rename cannot silently return it to a mock that mocks nothing.
    """
    with patch("aipass.spawn.apps.handlers.file_ops.logger") as m:
        yield m


@pytest.fixture
def mock_json_handler():
    """Mock json_handler.log_operation at the call site in file_ops.

    Uses patch.object on the module reference held by file_ops to avoid
    stale-reference issues when other test suites reload json_handler.
    """
    with patch.object(file_ops.json_handler, "log_operation") as m:
        m.return_value = True
        yield m


@pytest.fixture(autouse=True)
def _isolate_spawn_json(tmp_path, monkeypatch) -> Path:
    """Auto-isolate spawn_json directory to prevent test pollution.

    The redirect is the AIPASS_TEST_LOG_DIR seam (DPLAN-0325). spawn's shim
    binds the fleet's one json service, which recomputes its directory on every
    call from that variable — so there is no ``_JSON_DIR`` and no ``_handler``
    left to patch, and setting the variable here, long after import, still
    takes effect. The previous spelling patched both and would now raise
    AttributeError on every test in the suite.

    Returns:
        The directory the handler writes into for this test.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    return tmp_path / "spawn" / "spawn_json"
