"""Tests for the readme handler directory (readme_generator, readme_ops)."""

# =================== META ====================
# Name: test_readme.py
# Description: Unit tests for handlers/readme/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for readme handlers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-imports
    for mod_name in [
        "aipass.seedgo.apps.handlers.readme.readme_generator",
        "aipass.seedgo.apps.handlers.readme.readme_ops",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Tests -- readme_generator.generate_tree_section
# ---------------------------------------------------------------------------


def test_generate_tree_section_nonexistent():
    """generate_tree_section returns empty string for missing directory."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import generate_tree_section

    result = generate_tree_section("/nonexistent/path")
    assert result == ""


def test_generate_tree_section_basic(tmp_path):
    """generate_tree_section produces a fenced code block for a real directory."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "main.py").write_text("# entry\n", encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme.readme_generator import generate_tree_section

    result = generate_tree_section(str(tmp_path))
    assert result.startswith("```")
    assert result.endswith("```")
    assert "apps" in result


def test_generate_tree_section_excludes_pycache(tmp_path):
    """generate_tree_section filters out __pycache__ directories."""
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.cpython-312.pyc").write_text("", encoding="utf-8")
    (tmp_path / "real_file.py").write_text("# code\n", encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme.readme_generator import generate_tree_section

    result = generate_tree_section(str(tmp_path))
    assert "__pycache__" not in result


# ---------------------------------------------------------------------------
# Tests -- readme_generator._should_skip_entry
# ---------------------------------------------------------------------------


def test_should_skip_entry_pycache():
    """_should_skip_entry skips __pycache__."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import _should_skip_entry

    assert _should_skip_entry("__pycache__") is True


def test_should_skip_entry_hidden():
    """_should_skip_entry skips hidden directories (dot-prefixed)."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import _should_skip_entry

    assert _should_skip_entry(".git") is True
    assert _should_skip_entry(".env") is True


def test_should_skip_entry_normal_file():
    """_should_skip_entry does not skip normal files."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import _should_skip_entry

    assert _should_skip_entry("main.py") is False
    assert _should_skip_entry("apps") is False


# ---------------------------------------------------------------------------
# Tests -- readme_generator.generate_modules_section
# ---------------------------------------------------------------------------


def test_generate_modules_section_no_modules(tmp_path):
    """generate_modules_section returns empty string when no modules dir."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import generate_modules_section

    result = generate_modules_section(str(tmp_path))
    assert result == ""


def test_generate_modules_section_with_modules(tmp_path):
    """generate_modules_section lists modules from apps/modules/*.py."""
    modules_dir = tmp_path / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "audit_ops.py").write_text(
        '"""Audit Operations Module"""\ndef run(): pass\n',
        encoding="utf-8",
    )
    (modules_dir / "__init__.py").write_text("", encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme.readme_generator import generate_modules_section

    result = generate_modules_section(str(tmp_path))
    assert "audit_ops" in result
    assert "Audit Operations Module" in result


# ---------------------------------------------------------------------------
# Tests -- readme_generator.generate_last_updated
# ---------------------------------------------------------------------------


def test_generate_last_updated_format():
    """generate_last_updated returns a date string in expected format."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import generate_last_updated

    result = generate_last_updated()
    assert result.startswith("*Last Updated:")
    assert result.endswith("*")


# ---------------------------------------------------------------------------
# Tests -- readme_generator.generate_all_sections
# ---------------------------------------------------------------------------


def test_generate_all_sections_returns_dict(tmp_path):
    """generate_all_sections returns a dict with all section names."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import generate_all_sections

    result = generate_all_sections(str(tmp_path))
    assert isinstance(result, dict)
    for key in ("header", "tree", "modules", "commands", "last_updated"):
        assert key in result


# ---------------------------------------------------------------------------
# Tests -- readme_generator._extract_description_from_content
# ---------------------------------------------------------------------------


def test_extract_description_from_docstring():
    """_extract_description_from_content extracts first docstring line."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import _extract_description_from_content

    content = '"""My cool module\n\nMore details here.\n"""\nx = 1\n'
    assert _extract_description_from_content(content) == "My cool module"


def test_extract_description_from_meta_header():
    """_extract_description_from_content extracts from META Name line."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import _extract_description_from_content

    content = '# Name: mod.py - The Description\n"""Docstring"""\n'
    assert _extract_description_from_content(content) == "The Description"


def test_extract_description_empty():
    """_extract_description_from_content returns empty for bare code."""
    from aipass.seedgo.apps.handlers.readme.readme_generator import _extract_description_from_content

    assert _extract_description_from_content("x = 1\ny = 2\n") == ""
