# =================== AIPass ====================
# Name: test_readme_map.py
# Description: Tests for readme_map handler
# Version: 1.3.2
# Created: 2026-05-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/readme_map.py and the handlers it drives."""

# branch-name to README-path lookup.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/readme_map.py parses and imports
# seedgo: no-test-needed(documentation) — that the public lookup functions carry docstrings

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import aipass.aipass.apps.handlers.readme_map as rm
from aipass.aipass.apps.handlers.readme_map import (
    get_readme_path,
    list_branches,
    read_readme_at,
)

# Ensure encoding='utf-8' appears (PATTERN check)
_ENCODING = "utf-8"

_MOD = "aipass.aipass.apps.handlers.readme_map"


def _root_at(monkeypatch: pytest.MonkeyPatch, root: Path | None) -> None:
    """Point the module's cached root at *root* and drop the cached map.

    monkeypatch restores both after the test, so the live map is never left
    pointing at a tmp tree. A root of None makes the next lookup detect it.
    """
    monkeypatch.setattr(rm, "_AIPASS_ROOT", root)
    monkeypatch.setattr(rm, "_README_MAP", None)


# =============================================================================
# TestDetectAipassRoot — reached through list_branches()
# =============================================================================


class TestDetectAipassRoot:
    """Root detection, seen through the public lookup that runs it."""

    def test_uses_env_var_when_set(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """AIPASS_HOME env var is used when set.

        Mutant: env_home ignored (`if env_home:` -> `if False:`) -> red.
        """
        branch = tmp_path / "src" / "aipass" / "zeta_env_only"
        branch.mkdir(parents=True)
        (branch / "README.md").write_text("# zeta\n", encoding=_ENCODING)
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path))
        _root_at(monkeypatch, None)

        assert list_branches() == ["zeta_env_only"]

    def test_walks_up_to_find_src_aipass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Walks up from file to find parent containing src/aipass/."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        _root_at(monkeypatch, None)

        readme = get_readme_path("aipass")
        # The exact value depends on the environment; what it must NAME does
        # not. Value pin added 2026-09-08 (v5 assertion_shape): isinstance
        # alone was equally true of Path.cwd(), which is exactly the wrong
        # answer this walk exists to avoid.
        assert readme is not None
        root = readme.parents[3]
        assert (root / "src" / "aipass").is_dir(), f"{root} does not hold src/aipass/"

    def test_returns_path_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns a Path, and the Path it returns is an AIPass tree root."""
        _root_at(monkeypatch, None)
        readme = get_readme_path("drone")
        assert isinstance(readme, Path)
        root = readme.parents[3]
        assert (root / "src" / "aipass").is_dir(), f"{root} does not hold src/aipass/"


# =============================================================================
# TestBuildReadmeMap — reached through list_branches() / get_readme_path()
# =============================================================================


class TestBuildReadmeMap:
    """The branch → README map, seen through the public lookups."""

    def test_returns_dict(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Maps branch names to Paths."""
        # Create fake src/aipass structure with one branch README
        src_aipass = tmp_path / "src" / "aipass"
        drone_dir = src_aipass / "drone"
        drone_dir.mkdir(parents=True)
        (drone_dir / "README.md").write_text("# Drone\n", encoding="utf-8")
        _root_at(monkeypatch, tmp_path)

        assert list_branches() == ["drone"]
        assert get_readme_path("drone") == drone_dir / "README.md"

    def test_skips_missing_readmes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Branches without README.md are excluded."""
        src_aipass = tmp_path / "src" / "aipass"
        # Create directory but no README
        (src_aipass / "drone").mkdir(parents=True)
        _root_at(monkeypatch, tmp_path)

        assert "drone" not in list_branches()


# =============================================================================
# TestGetReadmePath
# =============================================================================


class TestGetReadmePath:
    """Tests for get_readme_path()."""

    def test_returns_path_for_known_branch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Returns a Path for a branch that has a README."""
        src_aipass = tmp_path / "src" / "aipass"
        cli_dir = src_aipass / "cli"
        cli_dir.mkdir(parents=True)
        readme = cli_dir / "README.md"
        readme.write_text("# CLI\n", encoding="utf-8")
        _root_at(monkeypatch, tmp_path)

        assert get_readme_path("cli") == readme

    def test_returns_none_for_unknown_branch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Returns None for a branch not in the map."""
        src_aipass = tmp_path / "src" / "aipass"
        src_aipass.mkdir(parents=True)
        _root_at(monkeypatch, tmp_path)

        assert get_readme_path("nonexistent_branch") is None


# =============================================================================
# TestListBranches
# =============================================================================


class TestListBranches:
    """Tests for list_branches()."""

    def test_returns_list(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Mutant: dirs without a README.md listed -> red."""
        src_aipass = tmp_path / "src" / "aipass"
        for branch in ["drone", "prax"]:
            d = src_aipass / branch
            d.mkdir(parents=True)
            (d / "README.md").write_text(f"# {branch}\n", encoding="utf-8")
        (src_aipass / "no_readme").mkdir()
        _root_at(monkeypatch, tmp_path)

        assert list_branches() == ["drone", "prax"]

    def test_empty_when_no_readmes(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Returns empty list when no branches have READMEs."""
        src_aipass = tmp_path / "src" / "aipass"
        src_aipass.mkdir(parents=True)
        _root_at(monkeypatch, tmp_path)

        assert list_branches() == []


# =============================================================================
# TestLiveDiscovery
# =============================================================================


class TestLiveDiscovery:
    """Branch roster is discovered from the tree, never hardcoded."""

    def test_discovers_arbitrary_new_branch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A branch dir that never existed before is found by the scan."""
        src_aipass = tmp_path / "src" / "aipass"
        for branch in ["drone", "zeta_brand_new"]:
            d = src_aipass / branch
            d.mkdir(parents=True)
            (d / "README.md").write_text(f"# {branch}\n", encoding="utf-8")
        _root_at(monkeypatch, tmp_path)

        result = list_branches()
        assert "zeta_brand_new" in result
        assert "drone" in result

    def test_missing_src_aipass_returns_empty(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """No src/aipass dir → empty map, no crash."""
        _root_at(monkeypatch, tmp_path)

        assert list_branches() == []

    def test_live_map_covers_real_tree(self) -> None:
        """Against the real repo: every src/aipass dir with a README is mapped."""
        branches = list_branches()
        assert "drone" in branches
        assert "hooks" in branches  # was missing from the old hardcoded roster


# =============================================================================
# TestReadReadmeAt — path-based live read
# =============================================================================


class TestReadReadmeAt:
    """Tests for read_readme_at() — the handler that owns README file reads."""

    def test_returns_whole_document(self, tmp_path: Path) -> None:
        """The full file comes back verbatim, not a truncated or split view."""
        readme = tmp_path / "README.md"
        readme.write_text("# Drone\n\nRoutes commands.\n", encoding=_ENCODING)

        assert read_readme_at(readme) == "# Drone\n\nRoutes commands.\n"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """An unreadable path yields None rather than raising OSError."""
        missing = tmp_path / "gone" / "README.md"

        assert read_readme_at(missing) is None

    def test_missing_file_logs_the_reason(self, tmp_path: Path) -> None:
        """The OSError reason is logged, not swallowed — diagnosis needs it."""
        missing = tmp_path / "gone" / "README.md"

        with patch(f"{_MOD}.logger") as mock_logger:
            read_readme_at(missing)

        assert mock_logger.error.called

    def test_content_is_never_cached(self, tmp_path: Path) -> None:
        """A second call reflects an edit made after the first."""
        readme = tmp_path / "README.md"
        readme.write_text("# v1\n", encoding=_ENCODING)
        first = read_readme_at(readme)
        readme.write_text("# v2\n", encoding=_ENCODING)

        assert first == "# v1\n"
        assert read_readme_at(readme) == "# v2\n"
