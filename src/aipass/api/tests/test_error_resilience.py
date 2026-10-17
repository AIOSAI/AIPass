# =================== AIPass ====================
# Name: test_error_resilience.py
# Description: Error Resilience Tests (from seedgo template)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/json/json_handler.py under missing, corrupt and empty files."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the prax json service that json_handler delegates to; @prax's tests
# seedgo: no-test-needed(ruff) — that apps/handlers/json/json_handler.py parses and imports

import importlib
import json
from pathlib import Path

import pytest


BRANCH_MODULE = "api"

_JSON_MOD_PATH = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

# No sys.modules stub: a file under api/ passes the handlers package's branch guard.
_mod = importlib.import_module(_JSON_MOD_PATH)
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


def test_missing_file(tmp_path: Path) -> None:
    """Loading a non-existent file returns a graceful default, not a crash."""
    json_dir = _json_dir_as_path(tmp_path)
    target = json_dir / "ghost_config.json"
    assert not target.exists()

    result = JSON_HANDLER.load_json("ghost", "config")

    assert isinstance(result, dict)
    assert result["module_name"] == "ghost"
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == result


def test_corrupt_json(tmp_path: Path) -> None:
    """Corrupt JSON on disk is handled gracefully — file is regenerated."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "corrupt_data.json"
    target.write_bytes(b"\x00\x01NOT-JSON{{{broken")

    result = JSON_HANDLER.ensure_json_exists("corrupt", "data")
    assert result is True

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, dict)
    assert "created" in data
    assert "last_updated" in data


def test_empty_file(tmp_path: Path) -> None:
    """An empty file (0 bytes) is handled gracefully."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "empty_log.json"
    target.write_text("", encoding="utf-8")

    result = JSON_HANDLER.ensure_json_exists("empty", "log")
    assert result is True

    raw = target.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert isinstance(data, list)


def test_nonexistent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing parent directory is handled gracefully."""
    seam = tmp_path / "does_not_exist" / "nested"
    assert not seam.exists()

    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(seam))
    json_dir = _json_dir_as_path(tmp_path)
    assert not json_dir.exists()

    result = JSON_HANDLER.ensure_json_exists("nodir", "config")
    assert result is True
    assert json_dir.exists()
    assert (json_dir / "nodir_config.json").exists()
