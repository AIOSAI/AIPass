# =================== AIPass ====================
# META DATA HEADER
# Name: tests/conftest.py
# Description: Shared pytest fixtures for trigger tests
# Created: 2025-11-08
# Modified: 2026-10-17
# Version: 1.5.1
# Category: trigger/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.5.1 (2026-10-10): Spawn-template temp_test_dir and sample_test_data removed; no live test requested them
#   - v1.5.0 (2026-10-08): Escalation lane fixtures moved from test_escalation.py; log_watcher_infrastructure
#     moved from test_log_watcher.py (its _mock_infrastructure); both at the oversize_test_file splits
#   - v1.4.0 (2026-09-27): Template C1/C2 fixtures - pinned console width, command state reset
#   - v1.3.0 (2026-09-12): Autouse catch-up state isolation (DPLAN-0339 step 2c)
#   - v1.2.0 (2026-08-08): Autouse resync of parent-package attrs after sys.modules surgery (CI xdist red)
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for trigger tests"""

import os
import tempfile

# Must be set before any prax import, or the logger initializes against live logs.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import pytest
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock

# Imported while the real config is in place, so the suite shares one escalation module, not a mock-configured copy.
from aipass.trigger.apps.handlers import escalation as _escalation
from aipass.trigger.apps.handlers.json import config_loader as _config_loader
from aipass.trigger.apps.config import trail_logger
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers.events import startup as _startup
from aipass.trigger.apps.handlers import error_registry, escalation, medic_state
from aipass.trigger.apps.handlers.events import error_detected
import aipass.trigger.apps.handlers.json.config_loader as config_loader
import aipass.trigger.apps.handlers.log_watcher as lw
from aipass.cli.apps.modules import display

# .archive/ holds verbatim disposal copies that must never be collected.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(scope="session")
def escalation_sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-wide stand-in for trigger_json/ and its custom_config/."""
    return tmp_path_factory.mktemp("escalation_sandbox")


@pytest.fixture(autouse=True)
def isolate_escalation_state(monkeypatch: pytest.MonkeyPatch, escalation_sandbox: Path) -> Generator[None, None, None]:
    """Keep the escalation lane off live state for every test in the suite.

    error/warning handlers record into the lane before any gate; the mail callback is reset so no digest goes."""
    state_file = escalation_sandbox / "escalation_state.json"
    state_file.unlink(missing_ok=True)
    monkeypatch.setattr(_escalation, "STATE_FILE", state_file)
    monkeypatch.setattr(_escalation, "logger", trail_logger(escalation_sandbox / "escalation.jsonl"))
    monkeypatch.setattr(_escalation, "_send_email", None)
    monkeypatch.setattr(_config_loader, "CONFIG_PATH", escalation_sandbox / "custom_config" / "trigger.config.json")
    monkeypatch.setattr(_config_loader, "logger", trail_logger(escalation_sandbox / "config_loader.jsonl"))
    _escalation._config_cache = (0.0, None)
    yield
    _escalation._config_cache = (0.0, None)


@pytest.fixture(autouse=True)
def isolate_catchup_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the error catch-up off live trigger_json/error_catchup.json.

    Any prax WARNING fires `startup`, whose catch-up would eat the live recovery window; no env seam reaches it.
    Suites run from another branch never load this conftest and still write the live file.
    """
    mod = _startup
    sandbox = tmp_path / "_catchup_sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "CATCHUP_STATE_FILE", sandbox / "error_catchup.json")
    monkeypatch.setattr(mod, "LEGACY_CATCHUP_STATE_FILE", sandbox / "trigger_data.json")
    monkeypatch.setattr(mod, "SUPPRESSED_LOG", sandbox / "medic_suppressed.jsonl")
    monkeypatch.setattr(mod, "logger", trail_logger(sandbox / "startup_handler.jsonl"))


@pytest.fixture(autouse=True)
def _resync_module_attrs() -> Generator[None, None, None]:
    """Keep parent-package attributes honest after sys.modules surgery.

    Teardown restores sys.modules but not the parent's attribute, so patches land on a twin (xdist-order red)."""
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


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def header_off_the_live_bus(monkeypatch: pytest.MonkeyPatch) -> list:
    """cli's header fires cli_header_displayed on the trigger it loaded once.

    A first live fire runs the real setup_handlers and wires the live mail adapter, so a recorder stands in."""
    fired: list = []
    recorder = types.SimpleNamespace(fire=lambda event, **data: fired.append((event, data)))
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return fired


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect trigger's json writes into a temp dir.

    Does NOT cover apps/config.py's own atomic writes; fixtures that address it redirect those."""
    # Own subdirectory: a seam AT tmp_path creates tmp_path/trigger/ and collides with tests' own dirs.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def cfg() -> Dict[str, Any]:
    """Operator settings the lane runs on — tests mutate this dict, never a live file."""
    return {
        "enabled": True,
        "digest_recipient": "@digest-inbox",
        "warning_threshold": 3,
        "error_threshold": 3,
        "window_minutes": 60,
        "cooldown_minutes": 60,
        "warning_age_hours": 24,
        "rollup_hours": 24,
        "sample_lines": 3,
        "max_signatures": 500,
        "escalate_suppressed": False,
        "watch_branch_log_warnings": True,
        "ignore_branches": [],
    }


@pytest.fixture
def lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cfg: Dict[str, Any]):
    """The escalation handler, wired to a tmp state file and the cfg fixture.

    Real lock and writes on purpose: a mocked lock once hid a self-deadlock."""
    monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
    monkeypatch.setattr(escalation, "logger", trail_logger(tmp_path / "escalation.jsonl"))
    monkeypatch.setattr(escalation, "get_config", lambda: cfg)
    monkeypatch.setattr(escalation, "_send_email", None)
    # Left real, the aged lane writes rows into the live error registry.
    monkeypatch.setattr(escalation, "_registry_report", lambda **kwargs: {})
    escalation._config_cache = (0.0, None)
    # Reset on the way out too: monkeypatch restores the registry path but not this cache.
    escalation._branch_names_cache = (0.0, None)
    yield escalation
    escalation._config_cache = (0.0, None)
    escalation._branch_names_cache = (0.0, None)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch, lane) -> List[Dict[str, Any]]:
    """Capture digest emails instead of sending them."""
    box: List[Dict[str, Any]] = []

    def _send(**kwargs: Any) -> bool:
        box.append(kwargs)
        return True

    monkeypatch.setattr(lane, "_send_email", _send)
    return box


@pytest.fixture
def medic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """Registry + medic state describing an error medic is still handling itself."""

    suppressed: set = set()
    switches = {"medic_enabled": True}
    monkeypatch.setattr(error_registry, "is_suppressed", lambda fingerprint: fingerprint in suppressed)
    monkeypatch.setattr(error_registry, "get_dispatch_count", lambda fingerprint: 0)
    monkeypatch.setattr(medic_state, "is_enabled", lambda: switches["medic_enabled"])
    monkeypatch.setattr(medic_state, "get_muted_branches", lambda: [])
    branch_registry = tmp_path / "AIPASS_REGISTRY.json"
    branches = [{"email": "@flow"}, {"email": "@memory"}]
    branch_registry.write_text(json.dumps({"branches": branches}), encoding="utf-8")
    monkeypatch.setattr(error_detected, "BRANCH_REGISTRY_FILE", branch_registry)

    return SimpleNamespace(
        branch_registry=branch_registry,
        registry=error_registry,
        state=medic_state,
        dispatcher=error_detected,
        suppressed=suppressed,
        switches=switches,
    )


# Not autouse: the log watcher test files opt in through pytestmark.


@pytest.fixture
def log_watcher_infrastructure(monkeypatch, tmp_path):
    """Replace every door the watcher opens onto live state, on the real module."""
    monkeypatch.setattr(lw, "logger", MagicMock())

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(lw, "json_handler", mock_json_handler)

    fake_trigger_root = tmp_path / "fake_trigger_root"
    fake_trigger_root.mkdir()
    monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", fake_trigger_root / "trigger_data.json")
    monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "fake_aipass_pkg")
    monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")

    # Both the import-time binding and the lazy fallback import answer from this recorder.
    registry_answer = MagicMock(return_value={"is_new": True, "count": 1, "id": "abc123"})
    monkeypatch.setattr(lw, "registry_report", registry_answer)
    monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)
    monkeypatch.setattr(error_registry, "report", registry_answer)

    monkeypatch.setattr(config_loader, "section", MagicMock(return_value={}))

    monkeypatch.setattr(lw, "WatchdogObserver", MagicMock())

    monkeypatch.setattr(lw, "_branch_log_observer", None)
    monkeypatch.setattr(lw, "_active_watcher", None)
    monkeypatch.setattr(lw, "_seen_error_hashes", set())
    monkeypatch.setattr(lw, "_fallback_error_counts", {})
    monkeypatch.setattr(lw, "_data_dirty", False)
    monkeypatch.setattr(lw, "_last_flush_time", 0.0)
    monkeypatch.setattr(lw, "_branch_names_cache", (0.0, ()))
    monkeypatch.setattr(lw, "_fire_event", None)
    monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, True))
