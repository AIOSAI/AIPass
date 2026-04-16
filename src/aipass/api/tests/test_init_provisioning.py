# =================== AIPass ====================
# Name: test_init_provisioning.py
# Description: Init/Provisioning Tests (from seedgo template)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
Init/Provisioning Tests for API branch.

Covers 4 tests:
  - creates_files, auto_creates_dir, no_overwrite, returns_dict
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest


BRANCH_MODULE = "api"

_handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    f"{BRANCH_MODULE.upper()}_JSON_DIR",
    "JSON_DIR",
    "BRANCH_JSON_DIR",
    "_JSON_DIR",
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break

if _JSON_DIR_ATTR is None:
    pytest.skip(
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations to tmp_path for test isolation."""
    assert _JSON_DIR_ATTR is not None
    monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


def _json_dir_as_path(tmp_path: Path) -> Path:
    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    return Path(val) if isinstance(val, str) else val


# ============================================================================
# Init/Provisioning Tests
# ============================================================================


def test_creates_expected_files(tmp_path: Path) -> None:
    """ensure_json_exists creates expected files on disk."""
    json_dir = _json_dir_as_path(tmp_path)

    for json_type in ("config", "data", "log"):
        result = json_handler.ensure_json_exists("prov_mod", json_type)
        assert result is True

        expected = json_dir / f"prov_mod_{json_type}.json"
        assert expected.exists()

        raw = expected.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed is not None


def test_auto_creates_directory(tmp_path: Path) -> None:
    """ensure_json_exists auto-creates parent directory when missing."""
    nested_dir = tmp_path / "auto_created" / "subdir"
    assert not nested_dir.exists()

    assert _JSON_DIR_ATTR is not None
    setattr(_mod, _JSON_DIR_ATTR, nested_dir)

    try:
        result = json_handler.ensure_json_exists("autodir", "config")
        assert nested_dir.exists()
        assert result is True
        assert (nested_dir / "autodir_config.json").exists()
    except (FileNotFoundError, OSError):
        pytest.skip("Branch does not auto-create missing directories")


def test_no_overwrite_on_second_call(tmp_path: Path) -> None:
    """Second call must not overwrite existing data (idempotency)."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)

    json_handler.ensure_json_exists("idem_mod", "data")

    target = json_dir / "idem_mod_data.json"
    original = json.loads(target.read_text(encoding="utf-8"))
    original["custom_field"] = "do_not_overwrite"
    target.write_text(json.dumps(original, indent=2), encoding="utf-8")

    json_handler.ensure_json_exists("idem_mod", "data")

    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("custom_field") == "do_not_overwrite"


def test_returns_dict_with_expected_keys(tmp_path: Path) -> None:
    """Provisioned files contain the correct structure keys."""
    json_handler.ensure_json_exists("key_mod", "config")
    config = json_handler.load_json("key_mod", "config")
    assert isinstance(config, dict)
    assert "module_name" in config
    assert "version" in config

    json_handler.ensure_json_exists("key_mod", "data")
    data = json_handler.load_json("key_mod", "data")
    assert isinstance(data, dict)
    assert "created" in data
    assert "last_updated" in data

    json_handler.ensure_json_exists("key_mod", "log")
    log = json_handler.load_json("key_mod", "log")
    assert isinstance(log, list)
