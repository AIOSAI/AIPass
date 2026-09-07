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


#: Isolation goes through the fleet seam, not a module attribute.
#:
#: This file used to hunt the handler for API_JSON_DIR / JSON_DIR /
#: BRANCH_JSON_DIR / _JSON_DIR and, finding none, skip ITSELF at module level.
#: Since DPLAN-0325 the handler is a shim over the one prax service, which
#: holds no directory constant at all — so the hunt would have found nothing
#: and this whole suite would have gone quietly dormant, reporting skipped and
#: measuring nothing. The service reads AIPASS_TEST_LOG_DIR on every call, so
#: the redirect is an env var and the suite keeps running.


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations into a temp sandbox for test isolation."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    return _json_dir_as_path(tmp_path)


def _json_dir_as_path(tmp_path: Path) -> Path:
    """The directory the handler writes into right now.

    MEASURED off the handler rather than spelled out: the one service spells
    the sandbox <seam>/<branch>/<branch>_json, so a literal here would drift
    the first time that spelling changes.
    """
    return _mod.get_json_path("probe", "config").parent


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


def test_auto_creates_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_json_exists auto-creates parent directory when missing.

    Pointed at a seam two levels below anything that exists, so the handler
    has to build the whole chain. The redirect is monkeypatched, not a bare
    setattr: the old form assigned the module attribute permanently and left
    the next test in this process pointing at a deleted tmp_path.
    """
    seam = tmp_path / "auto_created" / "subdir"
    assert not seam.exists()

    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(seam))
    nested_dir = _json_dir_as_path(tmp_path)
    assert not nested_dir.exists()

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
