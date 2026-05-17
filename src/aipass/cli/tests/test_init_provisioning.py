# =================== AIPass ====================
# Name: test_init_provisioning.py
# Description: Init/Provisioning Tests (from seedgo template)
# Version: 1.0.0
# Created: 2026-05-16
# Modified: 2026-05-16
# =============================================

"""Init/Provisioning Tests for CLI branch.

Covers 4 tests:
  - creates_files, auto_creates_dir, no_overwrite, returns_dict
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.cli.apps.handlers.json import json_handler


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations to tmp_path for test isolation."""
    monkeypatch.setattr(json_handler, "JSON_DIR", tmp_path)
    return tmp_path


def test_creates_expected_files(tmp_path: Path) -> None:
    """ensure_json_exists creates expected files on disk."""
    for json_type in ("config", "data", "log"):
        result = json_handler.ensure_json_exists("prov_mod", json_type)
        assert result is True

        expected = tmp_path / f"prov_mod_{json_type}.json"
        assert expected.exists()

        raw = expected.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed is not None


def test_auto_creates_directory(tmp_path: Path) -> None:
    """ensure_json_exists calls mkdir (parents=True) when directory is missing."""
    nested_dir = tmp_path / "auto_created" / "subdir"
    assert not nested_dir.exists()

    with patch.object(json_handler, "JSON_DIR", nested_dir):
        result = json_handler.ensure_json_exists("autodir", "config")

    assert nested_dir.exists(), "makedirs equivalent must create nested directories"
    assert result is True
    assert (nested_dir / "autodir_config.json").exists()


def test_no_overwrite_on_second_call(tmp_path: Path) -> None:
    """Second call must not overwrite existing data (no_clobber contract)."""
    json_handler.ensure_json_exists("idem_mod", "data")

    target = tmp_path / "idem_mod_data.json"
    original = json.loads(target.read_text(encoding="utf-8"))
    original["custom_field"] = "already_exists"
    target.write_text(json.dumps(original, indent=2), encoding="utf-8")

    json_handler.ensure_json_exists("idem_mod", "data")

    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("custom_field") == "already_exists"


def test_returns_dict_with_expected_keys(tmp_path: Path) -> None:
    """Provisioned files contain the correct structure for each json_type."""
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
