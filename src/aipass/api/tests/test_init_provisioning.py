# =================== AIPass ====================
# Name: test_init_provisioning.py
# Description: Init/Provisioning Tests (from seedgo template)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/json/json_handler.py, its ensure_json_exists provisioning."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the json_handler shim parses and imports
# seedgo: no-test-needed(duplicate_test) — log_operation() and the prax service behind the shim, @prax's own suite

import importlib
import json
from pathlib import Path

import pytest


BRANCH_MODULE = "api"

JSON_MOD_PATH = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

# No sys.modules stub: a file under api/ passes the handlers package's branch guard.
_mod = importlib.import_module(JSON_MOD_PATH)
JSON_HANDLER = _mod


# Isolation is the AIPASS_TEST_LOG_DIR env seam: the handler is a shim over the
# prax service, which holds no directory constant to patch.


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations into a temp sandbox for test isolation."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    return _json_dir_as_path(tmp_path)


def _json_dir_as_path(tmp_path: Path) -> Path:
    """The directory the handler writes into right now."""
    return _mod.get_json_path("probe", "config").parent


def test_creates_expected_files(tmp_path: Path) -> None:
    """ensure_json_exists creates expected files on disk."""
    json_dir = _json_dir_as_path(tmp_path)

    for json_type in ("config", "data", "log"):
        result = JSON_HANDLER.ensure_json_exists("prov_mod", json_type)
        assert result is True

        expected = json_dir / f"prov_mod_{json_type}.json"
        assert expected.exists()

        raw = expected.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed is not None


def test_auto_creates_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_json_exists auto-creates parent directory when missing."""
    seam = tmp_path / "auto_created" / "subdir"
    assert not seam.exists()

    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(seam))
    nested_dir = _json_dir_as_path(tmp_path)
    assert not nested_dir.exists()

    # No try/except: auto-creation is the contract; a caught OSError hid it as a skip.
    result = JSON_HANDLER.ensure_json_exists("autodir", "config")

    assert nested_dir.exists(), "the handler did not build the missing parent directories"
    assert result is True
    assert (nested_dir / "autodir_config.json").exists()


def test_no_overwrite_on_second_call(tmp_path: Path) -> None:
    """Second call must not overwrite existing data (idempotency)."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)

    JSON_HANDLER.ensure_json_exists("idem_mod", "data")

    target = json_dir / "idem_mod_data.json"
    original = json.loads(target.read_text(encoding="utf-8"))
    original["custom_field"] = "do_not_overwrite"
    target.write_text(json.dumps(original, indent=2), encoding="utf-8")

    JSON_HANDLER.ensure_json_exists("idem_mod", "data")

    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("custom_field") == "do_not_overwrite"


def test_returns_dict_with_expected_keys(tmp_path: Path) -> None:
    """Provisioned files contain the correct structure keys."""
    JSON_HANDLER.ensure_json_exists("key_mod", "config")
    config = JSON_HANDLER.load_json("key_mod", "config")
    assert isinstance(config, dict)
    assert "module_name" in config
    assert "version" in config

    JSON_HANDLER.ensure_json_exists("key_mod", "data")
    data = JSON_HANDLER.load_json("key_mod", "data")
    assert isinstance(data, dict)
    assert "created" in data
    assert "last_updated" in data

    JSON_HANDLER.ensure_json_exists("key_mod", "log")
    log = JSON_HANDLER.load_json("key_mod", "log")
    assert log == [], "a freshly provisioned log holds no entries"
