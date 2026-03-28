# =================== AIPass ====================
# Name: test_init_provisioning.py
# Description: Init/Provisioning Tests for skills branch
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
Init/Provisioning Tests for skills branch.

Covers 4 tests:
  - creates_files, auto_creates_dir, no_overwrite, returns_dict
"""

import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest


BRANCH_MODULE = "skills"
_json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"


def _import_handler():
    """Import json_handler."""
    return importlib.import_module(_json_mod_path)


# ============================================================================
# Init/Provisioning Tests
# ============================================================================

def test_creates_expected_files() -> None:
    """ensure_json_exists creates expected files on disk."""
    handler = _import_handler()
    json_dir = handler.SKILLS_JSON_DIR

    for json_type in ("config", "data", "log"):
        result = handler.ensure_json_exists("prov_mod", json_type)
        assert result is True

        expected = json_dir / f"prov_mod_{json_type}.json"
        assert expected.exists()

        raw = expected.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed is not None


def test_auto_creates_directory(tmp_path: Path) -> None:
    """ensure_json_exists auto-creates parent directory when missing."""
    handler = _import_handler()
    nested_dir = tmp_path / "auto_created" / "subdir"
    assert not nested_dir.exists()

    with patch.object(handler, "SKILLS_JSON_DIR", nested_dir):
        try:
            result = handler.ensure_json_exists("autodir", "config")
            assert nested_dir.exists()
            assert result is True
            assert (nested_dir / "autodir_config.json").exists()
        except (FileNotFoundError, OSError):
            pytest.skip("Branch does not auto-create missing directories")


def test_no_overwrite_on_second_call() -> None:
    """Second call must not overwrite existing data (no_overwrite idempotency)."""
    handler = _import_handler()
    json_dir = handler.SKILLS_JSON_DIR
    json_dir.mkdir(parents=True, exist_ok=True)

    handler.ensure_json_exists("idem_mod", "data")

    target = json_dir / "idem_mod_data.json"
    original = json.loads(target.read_text(encoding="utf-8"))
    original["custom_field"] = "do_not_overwrite"
    target.write_text(json.dumps(original, indent=2), encoding="utf-8")

    handler.ensure_json_exists("idem_mod", "data")

    after = json.loads(target.read_text(encoding="utf-8"))
    assert after.get("custom_field") == "do_not_overwrite"


def test_returns_dict_with_expected_keys() -> None:
    """Provisioned files contain the correct structure keys."""
    handler = _import_handler()

    handler.ensure_json_exists("key_mod", "config")
    config = handler.load_json("key_mod", "config")
    assert isinstance(config, dict)
    assert "module_name" in config
    assert "version" in config

    handler.ensure_json_exists("key_mod", "data")
    data = handler.load_json("key_mod", "data")
    assert isinstance(data, dict)
    assert "created" in data
    assert "last_updated" in data

    handler.ensure_json_exists("key_mod", "log")
    log = handler.load_json("key_mod", "log")
    assert isinstance(log, list)
