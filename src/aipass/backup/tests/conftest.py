# =================== META ====================
# Name: conftest.py
# Description: Backup test configuration -- the json seam, Google seal, console pin and module-attribute resync
# Version: 1.5.0
# Created: 2026-06-12
# Modified: 2026-11-15
# =============================================

"""Backup test configuration -- the json seam, Google seal, console pin and module-attribute resync."""

import os
import tempfile

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import logging
import sys
import types
from pathlib import Path
from typing import Generator, NoReturn
from unittest.mock import MagicMock

import pytest

from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.drive import upload as drive_upload
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.project import registry
from aipass.backup.apps.handlers.schedule import jobs
from aipass.backup.apps.handlers.state import stop_flag
from aipass.ai_mail.apps.modules import door_verified_caller
from aipass.cli.apps.modules import display

BRANCH_MODULE = "aipass.backup"

HANDLER_PKG = f"{BRANCH_MODULE}.apps.handlers"

if HANDLER_PKG not in sys.modules:
    _stub = types.ModuleType(HANDLER_PKG)
    _handlers_dir = Path(__file__).resolve().parents[1] / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]  # type: ignore[attr-defined]
    sys.modules[HANDLER_PKG] = _stub


@pytest.fixture(autouse=True)
def _resync_module_attrs() -> Generator[None, None, None]:
    """Keep parent-package attributes honest after sys.modules surgery.

    patch.dict restores the sys.modules DICT but not the parent package ATTRIBUTE, so a
    re-import under mocks leaves mock.patch (3.10/3.11) walking a stale twin under xdist.
    """
    yield
    snapshot = [(n, m) for n, m in sys.modules.items() if n.startswith("aipass") and m is not None]
    for name, mod in snapshot:
        parent_name, _, leaf = name.rpartition(".")
        if not parent_name:
            continue
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, leaf, mod) is not mod:
            setattr(parent, leaf, mod)
    for pkg_name, pkg in snapshot:
        for attr, value in list(vars(pkg).items()):
            if (
                isinstance(value, types.ModuleType)
                and getattr(value, "__name__", "") == f"{pkg_name}.{attr}"
                and f"{pkg_name}.{attr}" not in sys.modules
            ):
                delattr(pkg, attr)


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect this branch's json writes into a temp dir, and silence logging.

    The seam sits BESIDE tmp_path, never inside it: the sandbox is spelled <seam>/backup/...,
    so inside tmp_path it collides with tests that build backup/ and pollutes counted trees.
    """
    seam = tmp_path.parent / f"{tmp_path.name}_aipass_json_seam"
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(seam))

    logger_names = [
        BRANCH_MODULE,
        "aipass.prax.json",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])

    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def schedule_file(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test's schedule file is temp, beside tmp_path, never in it: tmp_path is often a project root."""
    path = tmp_path_factory.mktemp("daemon") / "schedule.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "branch": "@backup",
                "jobs": [
                    {"id": "wake-test", "enabled": False, "schedule": {"type": "interval", "interval_minutes": 5}}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs, "SCHEDULE_PATH", path)
    return path


@pytest.fixture
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the project registry at a file under tmp_path, never the branch's real one."""
    path = tmp_path / "registry" / "project_registry.json"
    path.parent.mkdir()
    monkeypatch.setattr(registry, "REGISTRY_PATH", path)
    return path


@pytest.fixture(autouse=True)
def verified_seat(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """Every test runs as the verified admin seat; a fence test sets ``caller`` and ``admin`` itself."""
    seat = types.SimpleNamespace(caller="@devpulse", admin=True)
    monkeypatch.setattr(door_verified_caller, "resolve_verified_caller", lambda: seat.caller)
    monkeypatch.setattr(door_verified_caller, "is_verified_admin_caller", lambda: seat.admin)
    return seat


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin the product's consoles to one width: an unpinned Rich console wraps differently per OS."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def clean_stop_state() -> Generator[None, None, None]:
    """A raised stop flag is process-global: under xdist the next class on the worker inherits it."""
    stop_flag.reset_stop_state()
    yield
    stop_flag.reset_stop_state()


def _no_live_google(*args: object, **kwargs: object) -> NoReturn:
    """Stand where Google stands. A test that reaches the wire dies here instead."""
    raise RuntimeError("a test reached the live Google Drive edge")


@pytest.fixture(autouse=True)
def sealed_google_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seal both doors to the real account, and the media reader, before EVERY test.

    Both live calls are module attributes of handlers/drive/client.py, so one patch closes them.
    MEDIA_UPLOAD_AVAILABLE is forced True: CI installs no drive extra, so uploads would fail early.
    """
    monkeypatch.setattr(drive_client, "get_drive_service", _no_live_google)
    monkeypatch.setattr(drive_client, "api_call_with_retry", _no_live_google)
    monkeypatch.setattr(drive_upload, "MediaFileUpload", MagicMock(name="MediaFileUpload"))
    monkeypatch.setattr(drive_upload, "MEDIA_UPLOAD_AVAILABLE", True)
