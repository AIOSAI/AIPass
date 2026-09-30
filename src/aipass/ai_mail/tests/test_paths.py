# =================== AIPass ====================
# Name: test_paths.py
# Description: Tests for shared path utilities
# Version: 1.0.1
# Created: 2026-04-03
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/paths.py -- repo root discovery and project root resolution."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — find_project_root(), not driven here: tests/test_registry_case_sweep.py

import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.paths as mod
from aipass.ai_mail.apps.handlers.paths import find_project_root


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


# --- find_project_root tests --------------------------------------------


def test_find_project_root_finds_registry(tmp_path):
    """Returns directory containing *_REGISTRY.json."""
    project = tmp_path / "projects" / "myproj"
    deep = project / "src" / "pkg"
    deep.mkdir(parents=True)
    (project / "MYPROJ_REGISTRY.json").write_text("{}", encoding="utf-8")

    assert find_project_root(deep) == project


def test_find_project_root_finds_host_registry(tmp_path):
    """Returns host repo root when AIPASS_REGISTRY.json is the first hit."""
    host = tmp_path / "repo"
    branch = host / "src" / "aipass" / "branch"
    branch.mkdir(parents=True)
    (host / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    assert find_project_root(branch) == host


def test_find_project_root_stops_at_first_registry(tmp_path):
    """Nested project registry is found before the host registry."""
    host = tmp_path / "repo"
    project = host / "projects" / "inner"
    deep = project / "src"
    deep.mkdir(parents=True)
    (host / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    (project / "INNER_REGISTRY.json").write_text("{}", encoding="utf-8")

    assert find_project_root(deep) == project


def test_find_project_root_none_when_no_registry(tmp_path):
    """Returns None when no *_REGISTRY.json is found anywhere."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)

    assert find_project_root(deep) is None


def test_find_project_root_at_start_dir(tmp_path):
    """Returns start dir itself when it contains the registry."""
    (tmp_path / "PROJ_REGISTRY.json").write_text("{}", encoding="utf-8")

    assert find_project_root(tmp_path) == tmp_path
