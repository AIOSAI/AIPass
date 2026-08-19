# =================== AIPass ====================
# Name: test_tab_renderer.py
# Description: Tests for tab_renderer handler (FPLAN-0285)
# Version: 1.0.0
# Created: 2026-06-25
# Modified: 2026-06-25
# =============================================

"""
Tests for the tab_renderer handler.

Covers:
  1. render_tab() — correct strings for each section type.
  2. render_tab() — per-branch overrides from config.
  3. render_tab() — fallback to defaults when branch not in per_branch.
  4. _reorder_keys() — canonical key ordering.
  5. refresh_all_tabs() — reads config and writes tabs (mocked I/O).
  6. Key ordering verification after tab insertion.
"""

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_tab_renderer(monkeypatch):
    """Drop cached module so each test gets a fresh import."""
    for mod_name in list(sys.modules):
        if "tab_renderer" in mod_name:
            sys.modules.pop(mod_name, None)
    # Also clear json sub-modules that conftest replaces with MagicMock
    sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.json_handler", None)
    yield


def _get_module():
    """Import and return the tab_renderer module."""
    return importlib.import_module(
        "aipass.memory.apps.handlers.tracking.tab_renderer",
    )


# ---------------------------------------------------------------------------
# Shared config fixtures
# ---------------------------------------------------------------------------

SAMPLE_ROLLOVER_CFG = {
    "defaults": {
        "local": {
            "sessions": {"count": 15},
            "key_learnings": {"count": 15},
        },
        "observations": {
            "observations": {"count": 15},
        },
    },
    "per_branch": {
        "devpulse": {
            "local": {
                "sessions": {"count": 20},
                "key_learnings": {"count": 25},
            },
            "observations": {
                "observations": {"count": 30},
            },
        },
    },
}

SAMPLE_ENTRY_LIMITS_CFG = {
    "entry_types": {
        "key_learnings": {"field": "value", "max_chars": 200},
        "sessions": {"field": "summary", "max_chars": 300},
        "todos": {"field": "task", "max_chars": 150},
        "observations": {"field": "note", "max_chars": 300},
    },
}


# ===========================================================================
# 1. render_tab — key_learnings (rollover ON)
# ===========================================================================


class TestRenderTabKeyLearnings:
    def test_default_branch(self):
        mod = _get_module()
        tab = mod.render_tab(
            "key_learnings",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "memory",
        )
        assert tab.startswith("⟦")
        assert tab.endswith("⟧")
        assert "rollover ON" in tab
        assert "keep 15" in tab
        assert "value ≤20" in tab  # ≤200

    def test_per_branch_override(self):
        mod = _get_module()
        tab = mod.render_tab(
            "key_learnings",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "devpulse",
        )
        assert "keep 25" in tab


# ===========================================================================
# 2. render_tab — sessions (rollover ON)
# ===========================================================================


class TestRenderTabSessions:
    def test_sessions_default(self):
        mod = _get_module()
        tab = mod.render_tab(
            "sessions",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "memory",
        )
        assert "rollover ON" in tab
        assert "keep 15" in tab
        assert "summary" in tab
        assert "≤30" in tab  # ≤300

    def test_sessions_per_branch(self):
        mod = _get_module()
        tab = mod.render_tab(
            "sessions",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "devpulse",
        )
        assert "keep 20" in tab


# ===========================================================================
# 3. render_tab — observations (rollover ON)
# ===========================================================================


class TestRenderTabObservations:
    def test_observations_default(self):
        mod = _get_module()
        tab = mod.render_tab(
            "observations",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "memory",
        )
        assert "rollover ON" in tab
        assert "keep 15" in tab
        assert "note" in tab

    def test_observations_per_branch(self):
        mod = _get_module()
        tab = mod.render_tab(
            "observations",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "devpulse",
        )
        assert "keep 30" in tab


# ===========================================================================
# 4. render_tab — todos (rollover OFF, static shape)
# ===========================================================================


class TestRenderTabTodos:
    def test_todos_static(self):
        mod = _get_module()
        tab = mod.render_tab(
            "todos",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "memory",
        )
        assert "rollover OFF" in tab
        assert "cap ~10 entries" in tab
        assert "task ≤15" in tab  # ≤150
        assert "RULE: DELETE" in tab
        assert "BAU" in tab

    def test_todos_ignores_per_branch_rollover(self):
        """Todos are always rollover OFF regardless of per_branch config."""
        mod = _get_module()
        tab = mod.render_tab(
            "todos",
            SAMPLE_ROLLOVER_CFG,
            SAMPLE_ENTRY_LIMITS_CFG,
            "devpulse",
        )
        assert "rollover OFF" in tab


# ===========================================================================
# 5. _reorder_keys — canonical key ordering
# ===========================================================================


class TestReorderKeys:
    def test_local_key_order(self):
        mod = _get_module()
        data = {
            "sessions": [],
            "document_metadata": {},
            "todos": [],
            "key_learnings": [],
            "extra_field": "preserved",
        }
        ordered = mod._reorder_keys(data, mod._LOCAL_KEY_ORDER)
        keys = list(ordered.keys())
        assert keys[0] == "document_metadata"
        # todos before key_learnings before sessions
        assert keys.index("todos") < keys.index("key_learnings")
        assert keys.index("key_learnings") < keys.index("sessions")
        # extra_field at the end
        assert keys[-1] == "extra_field"

    def test_observations_key_order(self):
        mod = _get_module()
        data = {
            "observations": [],
            "document_metadata": {},
            "guidelines": {},
            "observations_meta": "tab",
        }
        ordered = mod._reorder_keys(data, mod._OBSERVATIONS_KEY_ORDER)
        keys = list(ordered.keys())
        assert keys == [
            "document_metadata",
            "guidelines",
            "observations_meta",
            "observations",
        ]

    def test_meta_before_array(self):
        """Meta key must appear immediately before its corresponding array."""
        mod = _get_module()
        data = {
            "document_metadata": {},
            "todos": [],
            "todos_meta": "tab-todos",
            "key_learnings": [],
            "key_learnings_meta": "tab-kl",
            "sessions": [],
            "sessions_meta": "tab-sessions",
        }
        ordered = mod._reorder_keys(data, mod._LOCAL_KEY_ORDER)
        keys = list(ordered.keys())
        # Each *_meta must be immediately before its array
        assert keys.index("todos_meta") + 1 == keys.index("todos")
        assert keys.index("key_learnings_meta") + 1 == keys.index(
            "key_learnings",
        )
        assert keys.index("sessions_meta") + 1 == keys.index("sessions")


# ===========================================================================
# 6. refresh_all_tabs — integration with mocked I/O
# ===========================================================================


class TestRefreshAllTabs:
    def _make_local_data(self):
        return {
            "document_metadata": {"document_type": "session_history"},
            "todos": [{"task": "test"}],
            "key_learnings": [],
            "sessions": [],
        }

    def _make_obs_data(self):
        return {
            "document_metadata": {
                "document_type": "collaboration_patterns",
            },
            "guidelines": {},
            "observations": [],
        }

    def test_writes_tabs_to_files(self, tmp_path):
        """refresh_all_tabs reads config, walks branches, writes tabs."""
        mod = _get_module()

        # Set up branch dir with .trinity files
        branch_dir = tmp_path / "src" / "aipass" / "test_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)

        local_path = trinity / "local.json"
        obs_path = trinity / "observations.json"
        local_path.write_text(
            json.dumps(self._make_local_data(), indent=2),
            encoding="utf-8",
        )
        obs_path.write_text(
            json.dumps(self._make_obs_data(), indent=2),
            encoding="utf-8",
        )

        # Mock registry to return our test branch
        mock_branches = [
            {"name": "test_branch", "path": str(branch_dir)},
        ]

        def mock_get_path(branch, mem_type):
            p = Path(branch["path"]) / ".trinity" / f"{mem_type}.json"
            return p if p.exists() else None

        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }

        with (
            patch(
                "aipass.memory.apps.handlers.json.config_loader.load",
                return_value=mock_config,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._read_registry",
                return_value=mock_branches,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._get_memory_file_path",
                side_effect=mock_get_path,
            ),
        ):
            result = mod.refresh_all_tabs()

        assert result["success"] is True
        assert result["updated"] == 2  # local + observations

        # Verify local.json has tabs
        local_data = json.loads(local_path.read_text(encoding="utf-8"))
        assert "todos_meta" in local_data
        assert "key_learnings_meta" in local_data
        assert "sessions_meta" in local_data
        assert "rollover OFF" in local_data["todos_meta"]
        assert "rollover ON" in local_data["key_learnings_meta"]
        assert "rollover ON" in local_data["sessions_meta"]

        # Verify observations.json has tab
        obs_data = json.loads(obs_path.read_text(encoding="utf-8"))
        assert "observations_meta" in obs_data
        assert "rollover ON" in obs_data["observations_meta"]

    def test_key_order_after_refresh(self, tmp_path):
        """After refresh, keys are in canonical order."""
        mod = _get_module()

        branch_dir = tmp_path / "src" / "aipass" / "ordered_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)

        local_path = trinity / "local.json"
        local_path.write_text(
            json.dumps(self._make_local_data(), indent=2),
            encoding="utf-8",
        )

        obs_path = trinity / "observations.json"
        obs_path.write_text(
            json.dumps(self._make_obs_data(), indent=2),
            encoding="utf-8",
        )

        mock_branches = [
            {"name": "ordered_branch", "path": str(branch_dir)},
        ]

        def mock_get_path(branch, mem_type):
            p = Path(branch["path"]) / ".trinity" / f"{mem_type}.json"
            return p if p.exists() else None

        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }

        with (
            patch(
                "aipass.memory.apps.handlers.json.config_loader.load",
                return_value=mock_config,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._read_registry",
                return_value=mock_branches,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._get_memory_file_path",
                side_effect=mock_get_path,
            ),
        ):
            mod.refresh_all_tabs()

        local_data = json.loads(local_path.read_text(encoding="utf-8"))
        keys = list(local_data.keys())
        expected_prefix = [
            "document_metadata",
            "todos_meta",
            "todos",
            "key_learnings_meta",
            "key_learnings",
            "sessions_meta",
            "sessions",
        ]
        assert keys[: len(expected_prefix)] == expected_prefix

    def test_empty_registry(self):
        """refresh_all_tabs returns early if no branches in registry."""
        mod = _get_module()

        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }

        with (
            patch(
                "aipass.memory.apps.handlers.json.config_loader.load",
                return_value=mock_config,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._read_registry",
                return_value=[],
            ),
        ):
            result = mod.refresh_all_tabs()

        assert result["success"] is True
        assert result["updated"] == 0
        assert "No branches" in result.get("message", "")

    def test_no_templates_updated_key(self, tmp_path):
        """refresh_all_tabs result dict has no templates_updated key (literal-baking removed)."""
        mod = _get_module()
        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }
        with (
            patch(
                "aipass.memory.apps.handlers.json.config_loader.load",
                return_value=mock_config,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._read_registry",
                return_value=[],
            ),
        ):
            result = mod.refresh_all_tabs()
        assert "templates_updated" not in result

    def test_missing_file_skipped(self, tmp_path):
        """Branch with missing .trinity files is skipped, not errored."""
        mod = _get_module()

        branch_dir = tmp_path / "src" / "aipass" / "empty_branch"
        branch_dir.mkdir(parents=True)
        # No .trinity directory at all

        mock_branches = [
            {"name": "empty_branch", "path": str(branch_dir)},
        ]

        def mock_get_path(branch, mem_type):
            p = Path(branch["path"]) / ".trinity" / f"{mem_type}.json"
            return p if p.exists() else None

        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }

        with (
            patch(
                "aipass.memory.apps.handlers.json.config_loader.load",
                return_value=mock_config,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._read_registry",
                return_value=mock_branches,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._get_memory_file_path",
                side_effect=mock_get_path,
            ),
        ):
            result = mod.refresh_all_tabs()

        assert result["success"] is True
        assert result["skipped"] == 2  # local + observations
        assert result["updated"] == 0


# ===========================================================================
# 8. render_all_meta_tabs — public API for spawn
# ===========================================================================


class TestRenderAllMetaTabs:
    def test_returns_four_keys(self):
        mod = _get_module()
        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }
        with patch(
            "aipass.memory.apps.handlers.json.config_loader.load",
            return_value=mock_config,
        ):
            tabs = mod.render_all_meta_tabs()

        assert set(tabs.keys()) == {
            "TODOS_META",
            "KEY_LEARNINGS_META",
            "SESSIONS_META",
            "OBSERVATIONS_META",
        }

    def test_values_are_rendered_strings(self):
        mod = _get_module()
        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }
        with patch(
            "aipass.memory.apps.handlers.json.config_loader.load",
            return_value=mock_config,
        ):
            tabs = mod.render_all_meta_tabs()

        assert "rollover OFF" in tabs["TODOS_META"]
        assert "rollover ON" in tabs["KEY_LEARNINGS_META"]
        assert "rollover ON" in tabs["SESSIONS_META"]
        assert "rollover ON" in tabs["OBSERVATIONS_META"]
        assert "{{" not in tabs["TODOS_META"]

    def test_uses_defaults_not_per_branch(self):
        mod = _get_module()
        mock_config = {
            "rollover": SAMPLE_ROLLOVER_CFG,
            "entry_limits": SAMPLE_ENTRY_LIMITS_CFG,
        }
        with patch(
            "aipass.memory.apps.handlers.json.config_loader.load",
            return_value=mock_config,
        ):
            tabs = mod.render_all_meta_tabs()

        assert "keep 15" in tabs["KEY_LEARNINGS_META"]
        assert "keep 15" in tabs["SESSIONS_META"]


# ===========================================================================
# 8. The tab must state what the ENGINE enforces (DPLAN-0302 finding 2)
# ===========================================================================


class TestTabAgreesWithTheEngine:
    """The banner is written INTO an agent's memory file, where it reads as an
    instruction about that agent's own limits. A tab that names a number the
    engine does not enforce is a lie in the one place an agent trusts.

    render_tab used to carry its own lookup: a per-branch-DICT fallback rather
    than the per-FILE-KEY rule detector._should_rollover applies, plus a
    hard-coded ``count`` default of 15. Both are pinned dead here, with
    config_loader.resolve_limits — the shared resolver, itself pinned against
    the detector in test_config_verbs.py — as the oracle.
    """

    @staticmethod
    def _engine_count(rollover_cfg, branch, section):
        from aipass.memory.apps.handlers.json.config_loader import resolve_limits

        return resolve_limits(rollover_cfg, branch)[section]["count"]

    def test_per_branch_entry_missing_its_file_block_falls_back_like_the_engine(self):
        """A per_branch entry with no ``local`` block must inherit the DEFAULT,
        not a hard-coded 15 — the drift that made this class necessary."""
        mod = _get_module()
        cfg = {
            "defaults": {
                "local": {"sessions": {"count": 25, "auto_compact_cap": 3}, "key_learnings": {"count": 25}},
                "observations": {"observations": {"count": 25}},
            },
            # Entry exists, but carries no "local" block at all.
            "per_branch": {"victim": {"observations": {"observations": {"count": 25}}, "_note": "x"}},
        }
        tab = mod.render_tab("sessions", cfg, SAMPLE_ENTRY_LIMITS_CFG, "victim")

        assert self._engine_count(cfg, "victim", "sessions") == 25
        assert "keep 25" in tab
        assert "keep 15" not in tab

    def test_no_limit_anywhere_names_no_number(self):
        """When nothing is configured the engine enforces nothing, so the tab
        must not invent a count."""
        mod = _get_module()
        cfg = {
            "defaults": {"observations": {"observations": {"count": 15}}},
            "per_branch": {"victim": {"observations": {"observations": {"count": 15}}}},
        }
        tab = mod.render_tab("sessions", cfg, SAMPLE_ENTRY_LIMITS_CFG, "victim")

        assert self._engine_count(cfg, "victim", "sessions") is None
        assert "no entry limit configured" in tab
        assert "keep" not in tab

    @pytest.mark.parametrize("section", ["sessions", "key_learnings", "observations"])
    def test_override_matches_the_engine(self, section):
        mod = _get_module()
        tab = mod.render_tab(section, SAMPLE_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG, "devpulse")
        assert f"keep {self._engine_count(SAMPLE_ROLLOVER_CFG, 'devpulse', section)}" in tab

    @pytest.mark.parametrize("section", ["sessions", "key_learnings", "observations"])
    def test_unconfigured_branch_matches_the_engine(self, section):
        """A branch with no per_branch entry at all — the common case for a
        freshly spawned citizen before the first push."""
        mod = _get_module()
        tab = mod.render_tab(section, SAMPLE_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG, "newborn")
        assert f"keep {self._engine_count(SAMPLE_ROLLOVER_CFG, 'newborn', section)}" in tab

    def test_renderer_holds_no_count_literal_of_its_own(self):
        """Guard the fix itself: the resolution belongs to config_loader now.
        A re-introduced ``count`` fallback in this file is the bug coming back."""
        import inspect

        src = inspect.getsource(_get_module().render_tab)
        assert 'get("count", ' not in src
        assert "resolve_limits" in src
