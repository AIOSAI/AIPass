# =================== AIPass ====================
# META DATA HEADER
# Name: tests/conftest.py
# Description: Shared pytest fixtures for trigger tests
# Created: 2025-11-08
# Modified: 2026-10-10
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

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
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

# Imported here, while the REAL aipass.trigger.apps.config is still in place,
# so the whole suite shares ONE escalation module. Handlers reach the lane with
# `from aipass.trigger.apps.handlers import escalation`, which reuses whatever
# is already imported — without this, the first test file to mock the config
# module would leave a mock-configured copy (MagicMock file lock, stale tmp
# paths) cached for every test that follows.
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

# Never discover out of .archive/: it holds verbatim disposal copies (the old
# handler's tests, the lane's template routing suite) that must not be collected
# or rglob-walked into dotted module names (DPLAN-0325, spec 4c).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(scope="session")
def escalation_sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-wide stand-in for trigger_json/ and its custom_config/."""
    return tmp_path_factory.mktemp("escalation_sandbox")


@pytest.fixture(autouse=True)
def isolate_escalation_state(monkeypatch: pytest.MonkeyPatch, escalation_sandbox: Path) -> Generator[None, None, None]:
    """Keep the escalation lane off live state for every test in the suite.

    handle_error_detected and handle_warning_logged record into the lane before
    any dispatch gate, so any test that fires one of those events would
    otherwise count into the real trigger_json/escalation_state.json and read —
    or, when it is missing, regenerate — the operator's trigger.config.json.
    setup_handlers() also wires a live email callback into the lane; it is
    reset here so no test can send a digest.

    Tests that need their own state file or config simply patch over these.
    """
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

    THE LEAK THIS CLOSES (@ai_mail, 2026-09-10, found with sys.addaudithook on
    os.rename): any test whose code logs a prax WARNING writes the REAL
    error_catchup.json. prax's logger fires `startup` on the first log line of
    a process, that event is wired to handle_startup, and the catch-up saves
    its state through apps/config.py's own atomic write — the layer
    mock_infrastructure below documents as NOT covered by the json seam,
    because CATCHUP_STATE_FILE is a module constant built off TRIGGER_JSON_DIR
    and no environment variable reaches it.

    That is worse than a dirty file. last_scan_timestamp is a single shared
    value, so a test run eats the recovery window the live watcher service
    exists to cover (DPLAN-0339 step 2, row 12).

    Bound by a top-level import since 2026-09-28 (fleet green leg 3): no test
    in this suite deletes and re-imports the startup module any more, so the
    one copy imported here is the one every handler reaches.

    NOT a full cure: a suite running from ANOTHER branch's directory never
    loads this conftest, so @ai_mail's own reproduction still writes the live
    file. That needs a read-time seam on TRIGGER_JSON_DIR itself, which is a
    change to a shared constant and carries its own plan.
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

    Several fixtures in this suite delete a submodule from sys.modules and
    re-import it fresh to load it under mocked dependencies. monkeypatch and
    patch.dict restore the sys.modules DICT at teardown, but never the parent
    package's ATTRIBUTE, which keeps pointing at the throwaway twin. The next
    test then resolves two different objects for one dotted name — `from pkg
    import sub` and mock.patch walk the stale attribute while importlib walks
    sys.modules — so patches land on an object the code under test never sees.
    Only surfaces when an unlucky xdist worker runs a polluting module before
    a victim (CI-only red: escalation's medic gates read an unpatched
    medic_state twin after test_medic_state ran first).

    After every test: point parent attributes back at the sys.modules entry,
    and drop attributes whose module was evicted from sys.modules entirely so
    the next import performs a clean load.
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


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def header_off_the_live_bus(monkeypatch: pytest.MonkeyPatch) -> list:
    """cli's header fires cli_header_displayed on the trigger it loaded once.

    display keeps that trigger in _TRIGGER behind _TRIGGER_LOADED, so any test
    printing through the real header would fire on the live bus. Its handler
    was retired in leg 4 (2026-09-29), yet this stays: the first fire of a
    process runs the real setup_handlers, which wires the live mail adapter
    into three handler modules. Set here for every test, to a recorder: the
    api cure of 2026-09-27, chosen by this branch in leg 3.
    """
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

    autouse=True on purpose: trigger's handler is a shim that binds the fleet
    json service (DPLAN-0325), whose names write into the real trigger_json/
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here — after import — still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Note this does NOT cover apps/config.py, which owns its own atomic write
    path (replace_with_retry, read_text_with_retry, the platform file lock) and
    is redirected by the fixtures that address it directly. That layer is
    trigger's own and the sweep deliberately left it alone.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/trigger/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


# ---------------------------------------------------------------------------
# The escalation lane, shared by test_escalation.py and test_escalation_digest.py
# ---------------------------------------------------------------------------


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

    The real file lock and real atomic writes run here on purpose: a mocked
    lock has already hidden a self-deadlock in this branch once.
    """
    monkeypatch.setattr(escalation, "STATE_FILE", tmp_path / "escalation_state.json")
    monkeypatch.setattr(escalation, "logger", trail_logger(tmp_path / "escalation.jsonl"))
    monkeypatch.setattr(escalation, "get_config", lambda: cfg)
    monkeypatch.setattr(escalation, "_send_email", None)
    # The aged lane opens a registry row. Left real, that wrote into the LIVE
    # trigger_json/error_registry.json on every run: by 2026-09-24 two test
    # messages sat there at count 151 and 51. Tests that care patch over this.
    monkeypatch.setattr(escalation, "_registry_report", lambda **kwargs: {})
    escalation._config_cache = (0.0, None)
    # Reset on the way OUT too: a test that points BRANCH_REGISTRY_FILE at a tmp
    # registry leaves the compiled pattern behind, and monkeypatch restores the
    # path but not the cache — the next test would sign against a stale citizen
    # list that no longer matches any file on disk.
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
    """Registry + medic state describing an error medic is still handling itself.

    The lane reaches each of these through a lazy import that resolves out of
    sys.modules at call time, so the module objects imported at the top of
    this file are the ones patched here and the ones the lane reads.
    """

    # Answers that depend on what the lane asks: a test suppresses a fingerprint
    # by adding it to `suppressed`, and turns medic off through `switches`.
    suppressed: set = set()
    switches = {"medic_enabled": True}
    monkeypatch.setattr(error_registry, "is_suppressed", lambda fingerprint: fingerprint in suppressed)
    monkeypatch.setattr(error_registry, "get_dispatch_count", lambda fingerprint: 0)
    monkeypatch.setattr(medic_state, "is_enabled", lambda: switches["medic_enabled"])
    monkeypatch.setattr(medic_state, "get_muted_branches", lambda: [])
    # The real registry lookup, reading a tmp_path registry file.
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


# ---------------------------------------------------------------------------
# The branch log watcher, shared by test_log_watcher.py, test_log_watcher_rotation.py
# and test_log_watcher_state.py. Not autouse: it was autouse inside the one file it
# lived in, and each of those three files keeps that by naming it in pytestmark, so
# no other test file starts running it.
# ---------------------------------------------------------------------------


@pytest.fixture
def log_watcher_infrastructure(monkeypatch, tmp_path):
    """Replace every door the watcher opens onto live state, on the real module.

    The module is imported once, at the top. Each outward function and every
    path constant it writes is set here and put back by monkeypatch; the
    module-level state a fresh import used to reset is reset here too.
    """
    monkeypatch.setattr(lw, "logger", MagicMock())

    # log_operation appends to the LIVE trigger logs/.
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(lw, "json_handler", mock_json_handler)

    # Built under tmp_path so every trigger_data.json flush the product makes
    # lands in this test's own directory, never the live watcher positions.
    fake_trigger_root = tmp_path / "fake_trigger_root"
    fake_trigger_root.mkdir()
    monkeypatch.setattr(lw, "TRIGGER_DATA_FILE", fake_trigger_root / "trigger_data.json")
    monkeypatch.setattr(lw, "AIPASS_PKG_ROOT", tmp_path / "fake_aipass_pkg")
    monkeypatch.setattr(lw, "SYSTEM_LOGS_DIR", tmp_path / "system_logs")

    # -- error registry: the import-time binding and the lazy fallback import
    # both answer from this recorder, never the LIVE registry.
    registry_answer = MagicMock(return_value={"is_new": True, "count": 1, "id": "abc123"})
    monkeypatch.setattr(lw, "registry_report", registry_answer)
    monkeypatch.setattr(lw, "_REGISTRY_AVAILABLE", True)
    monkeypatch.setattr(error_registry, "report", registry_answer)

    # -- the operator switch for WARNING capture: read lazily per line.
    monkeypatch.setattr(config_loader, "section", MagicMock(return_value={}))

    # -- watchdog: no real observer is ever armed over a directory.
    monkeypatch.setattr(lw, "WatchdogObserver", MagicMock())

    # -- module state a fresh import used to start from.
    monkeypatch.setattr(lw, "_branch_log_observer", None)
    monkeypatch.setattr(lw, "_active_watcher", None)
    monkeypatch.setattr(lw, "_seen_error_hashes", set())
    monkeypatch.setattr(lw, "_fallback_error_counts", {})
    monkeypatch.setattr(lw, "_data_dirty", False)
    monkeypatch.setattr(lw, "_last_flush_time", 0.0)
    monkeypatch.setattr(lw, "_branch_names_cache", (0.0, ()))
    monkeypatch.setattr(lw, "_fire_event", None)
    monkeypatch.setattr(lw, "_warning_capture_cache", (0.0, True))
