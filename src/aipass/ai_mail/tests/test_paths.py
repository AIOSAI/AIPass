# =================== AIPass ====================
# Name: test_paths.py
# Description: Tests for shared path utilities
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for paths module -- repo root discovery."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.paths as mod


# --- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_log_operation(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(mod, "json_handler", MagicMock())


# --- find_repo_root tests --------------------------------------------


def test_find_repo_root_finds_registry(tmp_path, monkeypatch):
    """Returns ancestor directory that contains AIPASS_REGISTRY.json."""
    # Build a directory tree: tmp_path/repo/src/pkg/
    repo_dir = tmp_path / "repo"
    pkg_dir = repo_dir / "src" / "pkg"
    pkg_dir.mkdir(parents=True)
    (repo_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    # Patch __file__ so the walk starts inside pkg_dir
    fake_file = pkg_dir / "paths.py"
    fake_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "__file__", str(fake_file))

    result = mod.find_repo_root()
    assert result == repo_dir


def test_find_repo_root_returns_cwd_when_no_registry(tmp_path, monkeypatch):
    """Returns Path.cwd() when no ancestor contains AIPASS_REGISTRY.json."""
    # Use an isolated directory with no registry file anywhere above
    isolated = tmp_path / "nowhere" / "deep"
    isolated.mkdir(parents=True)
    fake_file = isolated / "paths.py"
    fake_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(mod, "__file__", str(fake_file))
    monkeypatch.chdir(tmp_path)

    result = mod.find_repo_root()
    assert result == Path(str(tmp_path))


def test_find_repo_root_finds_registry_at_immediate_parent(tmp_path, monkeypatch):
    """Returns the immediate parent when AIPASS_REGISTRY.json is one level up."""
    parent_dir = tmp_path / "project"
    child_dir = parent_dir / "child"
    child_dir.mkdir(parents=True)
    (parent_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    fake_file = child_dir / "paths.py"
    fake_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "__file__", str(fake_file))

    result = mod.find_repo_root()
    assert result == parent_dir


def test_find_repo_root_finds_registry_in_same_dir(tmp_path, monkeypatch):
    """Returns the directory itself when AIPASS_REGISTRY.json is in the same dir."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    fake_file = tmp_path / "paths.py"
    fake_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "__file__", str(fake_file))

    result = mod.find_repo_root()
    assert result == tmp_path
