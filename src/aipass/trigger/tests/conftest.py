# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.3.0
# Category: trigger/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.3.0 (2026-09-12): Autouse catch-up state isolation (DPLAN-0339 step 2c)
#   - v1.2.0 (2026-08-08): Autouse resync of parent-package attrs after sys.modules surgery (CI xdist red)
#   - v1.1.0 (2026-08-08): Suite-wide escalation lane isolation
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
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

import pytest
import shutil
import sys
import types
from pathlib import Path
from typing import Generator

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

    Resolved through sys.modules rather than a top-level import so the fixture
    patches whichever copy of the module is currently registered — several
    tests in this suite delete it and re-import it under a mocked config.

    NOT a full cure: a suite running from ANOTHER branch's directory never
    loads this conftest, so @ai_mail's own reproduction still writes the live
    file. That needs a read-time seam on TRIGGER_JSON_DIR itself, which is a
    change to a shared constant and carries its own plan.
    """
    import aipass.trigger.apps.handlers.events.startup  # noqa: F401 - registers in sys.modules

    mod = sys.modules["aipass.trigger.apps.handlers.events.startup"]
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


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data

    Customize this fixture for your module's needs
    """
    return {"test_key": "test_value", "sample_data": "example"}


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
