# =================== AIPass ====================
# Name: conftest.py
# Version: 2.2.0
# Description: Shared pytest fixtures for hooks tests
# Branch: hooks
# Layer: tests
# Created: 2026-05-18
# Modified: 2026-09-18
# =============================================

"""Shared pytest fixtures for hooks tests.

The json redirect is the ``AIPASS_TEST_LOG_DIR`` seam (DPLAN-0325). This
branch's ``json_handler`` binds the fleet's one json service, which resolves
this branch's document directory PER CALL and honours that variable itself —
there is no singleton and no private attribute left to patch.

The variable is armed twice, on purpose. At import, so it is set before any
test runs: the repo-root conftest REFUSES a run that reaches a shim-bound
``log_operation`` with the seam unset, because such a run would write into live
``<branch>_json`` directories, and its autouse fixture runs before this file's.
Then per test by ``mock_infrastructure``, so each test gets its own tmp_path.
"""

import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest

from aipass.hooks.apps.handlers.json import json_handler

collect_ignore_glob = [".archive/*"]


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real hooks_json/
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here — after import — still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def isolated_trust_registry(tmp_path_factory, monkeypatch) -> Path:
    """Keep the trust registry out of the LIVE ~/.aipass/trusted_projects.json.

    REGISTRY_PATH is bound to Path.home() at import. A test that walks into a
    .aipass/hooks.json while that file is absent runs bootstrap(), which WRITES
    it: seedgo's runtime probe (HOME pointed at a throwaway, 2026-09-14) caught
    test_engine's TestErrorResilience creating it. On a dev seat that file is
    the live registry. Tests that exercise the registry patch it on top.

    Returns:
        The sandbox registry path (absent until something writes it).
    """
    trust_registry = importlib.import_module("aipass.hooks.apps.handlers.config.trust_registry")
    sandbox = tmp_path_factory.mktemp("trust_registry") / "trusted_projects.json"
    monkeypatch.setattr(trust_registry, "REGISTRY_PATH", sandbox)
    return sandbox


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_hooks_config() -> dict:
    """Minimal hooks.json config for testing."""
    return {
        "hooks_enabled": True,
        "UserPromptSubmit": {
            "test_hook": {
                "enabled": True,
                "command": "echo 'test output'",
                "matcher": "",
            }
        },
        "PreToolUse": {
            "matcher_hook": {
                "enabled": True,
                "command": "echo 'matched'",
                "matcher": "Edit|Write",
            },
            "disabled_hook": {
                "enabled": False,
                "command": "echo 'should not fire'",
                "matcher": "",
            },
        },
    }


@pytest.fixture
def hooks_config_file(temp_test_dir: Path, sample_hooks_config: dict) -> Path:
    """Creates a .aipass/hooks.json in temp dir."""
    config_dir = temp_test_dir / ".aipass"
    config_dir.mkdir()
    config_file = config_dir / "hooks.json"
    config_file.write_text(json.dumps(sample_hooks_config), encoding="utf-8")
    return config_file


@pytest.fixture
def mock_logger():
    """Mock the prax system logger."""
    with patch("aipass.hooks.apps.modules.engine.logger") as mock:
        yield mock


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for hook execution tests."""
    with patch("aipass.hooks.apps.modules.engine.subprocess.run") as mock:
        yield mock


@pytest.fixture(autouse=True)
def isolated_cadence_state(tmp_path_factory, monkeypatch):
    """Keep per-session cadence/advisory state out of the LIVE seat's files.

    cadence persists throttle state in the system temp dir keyed by
    CLAUDE_CODE_SESSION_ID, so an unisolated run both reads and WRITES the
    state of whatever session is executing the suite — a test could silence a
    real advisory for ten turns, or be silenced by one. Same class of defect as
    the 12 fixture lines this branch put in the production presence_gate.log.

    Tests that exercise cadence itself patch _GUARD_DIR on top of this.
    """
    cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
    monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path_factory.mktemp("cadence_state"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "pytest-session")


@pytest.fixture(autouse=True)
def isolated_diagnostics_state(tmp_path_factory, monkeypatch):
    """Keep the fleet-shared .diagnostics_state.json out of every test.

    The file sits at src/aipass/ and every live session's auto_fix writes it. A test
    whose Edit targets a .py file reached edit_gate's diagnostics block with whatever
    error another branch had open at that moment. Measured 2026-09-18: @memory's
    open import error turned two tests red in one run and green in the next. The
    tests that exercise the state patch STATE_FILE on top of this.
    """
    ds = importlib.import_module("aipass.hooks.apps.modules.diagnostics_state")
    monkeypatch.setattr(ds, "STATE_FILE", tmp_path_factory.mktemp("diagnostics_state") / ".diagnostics_state.json")


@pytest.fixture
def registered_projects(tmp_path: Path) -> dict:
    """AIPass, a project nested inside it, and a sibling Vera Studio, each with a REAL registry.

    The owner's ruling, 2026-09-18 22:17 (devpulse 1d041cfc): who may write whose
    files is read from the registries — branch rows, their paths, the ``owner``
    flag that marks a project's manager. The older fixtures write ``{}``, which
    has no rows to read, so they only ever exercised the path-shape fallback.

        Projects/
          AIPass/        AIPASS_REGISTRY.json   (list shape; devpulse owner, one absolute path)
            src/aipass/{devpulse,hooks,memory,seedgo,spawn,flow}
            src/aipass/flow/flow_json/PLAN_REGISTRY.json   an artifact, not a project
            projects/baud/  BAUD_REGISTRY.json   (nested project, baud owner)
          Vera-Studio/   VERA-STUDIO_REGISTRY.json   (dict shape; VERA owner)
            src/vera_studio/{vera,writer,seedgo}   seedgo here is only a name
    """
    projects = tmp_path / "Projects"
    aipass = projects / "AIPass"
    for name in ("devpulse", "hooks", "memory", "seedgo", "spawn", "flow"):
        (aipass / "src" / "aipass" / name).mkdir(parents=True)
    rows = [{"name": name, "path": f"src/aipass/{name}"} for name in ("HOOKS", "seedgo", "spawn", "flow")]
    rows.append({"name": "memory", "path": str(aipass / "src" / "aipass" / "memory")})
    rows.append({"name": "devpulse", "path": "src/aipass/devpulse", "owner": True, "admin": True})
    (aipass / "AIPASS_REGISTRY.json").write_text(json.dumps({"metadata": {}, "branches": rows}), encoding="utf-8")
    flow_json = aipass / "src" / "aipass" / "flow" / "flow_json"
    flow_json.mkdir()
    (flow_json / "PLAN_REGISTRY.json").write_text(json.dumps({"plans": {}, "next_number": 1}), encoding="utf-8")

    baud = aipass / "projects" / "baud"
    (baud / "src" / "baud" / "baud").mkdir(parents=True)
    baud_rows = [{"name": "baud", "path": "src/baud/baud", "owner": True}]
    (baud / "BAUD_REGISTRY.json").write_text(json.dumps({"metadata": {}, "branches": baud_rows}), encoding="utf-8")

    vera = projects / "Vera-Studio"
    vera_rows = {}
    for name in ("vera", "writer", "seedgo"):
        (vera / "src" / "vera_studio" / name).mkdir(parents=True)
        vera_rows[name.upper()] = {"name": name.upper(), "path": f"src/vera_studio/{name}"}
    vera_rows["VERA"]["owner"] = True
    (vera / "VERA-STUDIO_REGISTRY.json").write_text(
        json.dumps({"metadata": {}, "branches": vera_rows}), encoding="utf-8"
    )

    seat = aipass / "src" / "aipass"
    vera_seat = vera / "src" / "vera_studio"
    return {
        "aipass": aipass,
        "vera": vera,
        "baud": baud,
        "devpulse": str(seat / "devpulse"),
        "hooks": str(seat / "hooks"),
        "memory": str(seat / "memory"),
        "seedgo": str(seat / "seedgo"),
        "spawn": str(seat / "spawn"),
        "flow": str(seat / "flow"),
        "vera_seat": str(vera_seat / "vera"),
        "writer": str(vera_seat / "writer"),
        "vera_seedgo": str(vera_seat / "seedgo"),
        "baud_seat": str(baud / "src" / "baud" / "baud"),
    }
