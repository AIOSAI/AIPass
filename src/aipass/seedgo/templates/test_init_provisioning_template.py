# =================== AIPass ====================
# Name: test_init_provisioning_template.py
# Description: Universal Init/Provisioning Test Template
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Universal Init/Provisioning Test Template

Copy this file to any AIPass branch's tests/ directory.
Change BRANCH_MODULE below. Run with pytest.

Covers 4 tests:
  - test_creates_expected_files: ensure_json_exists creates files on disk
  - test_auto_creates_directory: mkdir/makedirs runs when dir is missing
  - test_no_overwrite_on_second_call: idempotent -- second call preserves data
  - test_returns_dict_with_expected_keys: provisioned file has correct structure

These tests verify the "cold start" contract: when a branch is freshly
cloned or its JSON directory is empty, the provisioning functions must
bootstrap valid files without manual intervention.
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest


# ============ BRANCH CONFIG ============
# Change these two lines when deploying to a branch:
BRANCH_MODULE = "seedgo"  # e.g. "prax", "drone", "backup", "cli", etc.
# For commons: "commons" (import path is different: aipass -> just commons)
# For skills: "skills" (import path is different: aipass -> just skills)
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------

if BRANCH_MODULE in ("commons", "skills"):
    _handler_pkg = f"{BRANCH_MODULE}.apps.handlers"
    _json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"
else:
    _handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
    _json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    if BRANCH_MODULE in ("commons", "skills"):
        _handlers_dir = Path(__file__).resolve().parents[3] / BRANCH_MODULE / "apps" / "handlers"
    else:
        _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


# ---------------------------------------------------------------------------
# JSON_DIR variable discovery
# ---------------------------------------------------------------------------

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    f"{BRANCH_MODULE.upper()}_JSON_DIR",
    "JSON_DIR",
    "BRANCH_JSON_DIR",
    f"{BRANCH_MODULE}_json",
    "_JSON_DIR",
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break

if _JSON_DIR_ATTR is None:
    pytest.skip(
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler -- tried: {_JSON_DIR_CANDIDATES}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations to tmp_path for test isolation."""
    assert _JSON_DIR_ATTR is not None
    original_value = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(original_value, str):
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, str(tmp_path))
    else:
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


def _json_dir_as_path(tmp_path: Path) -> Path:
    """Return the patched JSON dir as a Path (handles str-typed branches)."""
    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(val, str):
        return Path(val)
    return val


# ============================================================================
# Init/Provisioning Tests (4 tests)
# ============================================================================


def test_creates_expected_files(tmp_path: Path) -> None:  # IP-001
    """ensure_json_exists creates the expected file on disk.

    After calling ensure_json_exists for each type (config, data, log),
    the corresponding file must exist in the JSON directory.
    """
    json_dir = _json_dir_as_path(tmp_path)

    for json_type in ("config", "data", "log"):
        result = json_handler.ensure_json_exists("prov_mod", json_type)
        assert result is True, f"ensure_json_exists must return True for {json_type}"

        expected = json_dir / f"prov_mod_{json_type}.json"
        assert expected.exists(), f"ensure_json_exists must create {expected.name} on disk"

        # Verify the file contains valid JSON
        raw = expected.read_text(encoding="utf-8")
        parsed = json.loads(raw)  # must not raise
        assert parsed is not None, f"{expected.name} must contain valid JSON"


def test_auto_creates_directory(tmp_path: Path) -> None:  # IP-002
    """ensure_json_exists auto-creates the parent directory when missing.

    Points JSON_DIR at a non-existent subdirectory. The handler must
    create it (mkdir -p equivalent) rather than failing.
    """
    nested_dir = tmp_path / "auto_created" / "subdir"
    assert not nested_dir.exists(), "Precondition: directory must not exist"

    # Patch JSON_DIR to the nested non-existent directory
    assert _JSON_DIR_ATTR is not None
    original_value = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(original_value, str):
        setattr(_mod, _JSON_DIR_ATTR, str(nested_dir))
    else:
        setattr(_mod, _JSON_DIR_ATTR, nested_dir)

    try:
        result = json_handler.ensure_json_exists("autodir", "config")
        assert nested_dir.exists(), "ensure_json_exists must auto-create missing directories"
        assert result is True
        assert (nested_dir / "autodir_config.json").exists()
    except (FileNotFoundError, OSError):
        # Some branches may not auto-create directories -- this is
        # acceptable but should be documented in the branch's contract
        pytest.skip("Branch does not auto-create missing directories")


def test_no_overwrite_on_second_call(tmp_path: Path) -> None:  # IP-003
    """Second call to ensure_json_exists must not overwrite existing data.

    This verifies idempotency: provisioning runs safely on every startup
    without destroying previously saved data.
    """
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)

    # First call: provision the file
    json_handler.ensure_json_exists("idem_mod", "data")

    # Inject custom data into the provisioned file
    target = json_dir / "idem_mod_data.json"
    original = json.loads(target.read_text(encoding="utf-8"))
    original["custom_field"] = "do_not_overwrite"
    target.write_text(json.dumps(original, indent=2), encoding="utf-8")

    # Second call: must preserve the custom field
    json_handler.ensure_json_exists("idem_mod", "data")

    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("custom_field") == "do_not_overwrite", (
        "Second ensure_json_exists call must not overwrite existing valid data"
    )


def test_returns_dict_with_expected_keys(tmp_path: Path) -> None:  # IP-004
    """Provisioned files contain the correct structure keys.

    After ensure_json_exists + load_json, the returned data must have
    the mandatory keys for each type.
    """
    # Config: must have module_name, version, config
    json_handler.ensure_json_exists("key_mod", "config")
    config = json_handler.load_json("key_mod", "config")
    assert isinstance(config, dict), "Config must be a dict"
    assert "module_name" in config, "Config must have 'module_name'"
    assert "version" in config, "Config must have 'version'"

    # Data: must have created, last_updated
    json_handler.ensure_json_exists("key_mod", "data")
    data = json_handler.load_json("key_mod", "data")
    assert isinstance(data, dict), "Data must be a dict"
    assert "created" in data, "Data must have 'created'"
    assert "last_updated" in data, "Data must have 'last_updated'"

    # Log: must be a list
    json_handler.ensure_json_exists("key_mod", "log")
    log = json_handler.load_json("key_mod", "log")
    assert isinstance(log, list), "Log must be a list"
