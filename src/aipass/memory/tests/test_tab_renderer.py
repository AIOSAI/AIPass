# =================== AIPass ====================
# Name: test_tab_renderer.py
# Description: Tests for tab_renderer handler (FPLAN-0285)
# Version: 1.1.0
# Created: 2026-06-25
# Modified: 2026-09-15
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
  7. The todos tab: pad size, backlog file, next #N from pad + backlog (DPLAN-0345).
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
    """Drop cached module so each test gets a fresh import.

    A bare ``sys.modules.pop`` here is one-way: the eviction outlives the
    test and every later test in the same process inherits it. That is how
    two receipt tests in test_trinity_standard.py went red on one worker,
    on one interpreter, on one run, on a commit that changed version
    strings only -- this file evicted the real handlers.json package, and
    the next lazy submodule import landed on conftest's stand-in instead.
    ``monkeypatch.delitem`` gives the same fresh import and puts the real
    module back at teardown, so the eviction cannot escape the test.
    """
    stale = [name for name in sys.modules if "tab_renderer" in name]
    stale += ["aipass.memory.apps.handlers.json", "aipass.memory.apps.handlers.json.json_handler"]
    for name in stale:
        monkeypatch.delitem(sys.modules, name, raising=False)
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
        assert tab.endswith("value ≤200 chars · draft to 160 ⟧")

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
        assert tab.endswith("summary ≤300 chars · draft to 240 ⟧")

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
        assert tab.endswith("note ≤300 chars · draft to 240 ⟧")

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
# 4. render_tab — todos (a pad that rolls to a backlog FILE, DPLAN-0345)
# ===========================================================================

PAD_ROLLOVER_CFG = {
    "defaults": {"local": {"todos": {"count": 7}}},
    "per_branch": {"devpulse": {"local": {"todos": {"count": 4}}}},
}


def _backlog_file(path: Path, numbers: list) -> Path:
    """A backlog document holding one record per original number."""
    entries = [{"rolled": "r", "reason": "overflow", "entry": {"number": number}} for number in numbers]
    path.write_text(
        json.dumps({"document_metadata": {"managed_by": "memory", "branch": "memory"}, "entries": entries}),
        encoding="utf-8",
    )
    return path


class TestRenderTabTodos:
    def test_the_pad_size_and_caps_come_from_config(self):
        mod = _get_module()
        tab = mod.render_tab(
            "todos", PAD_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG, "memory", {"branch_dir": "memory", "next_number": 12}
        )
        assert tab == (
            "⟦ pad of 7 · oldest roll to .backup/todo/memory/backlog.json · task ≤150 chars · draft to 120 · next #12 ⟧"
        )

    def test_the_pad_size_honours_per_branch(self):
        mod = _get_module()
        tab = mod.render_tab(
            "todos", PAD_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG, "devpulse", {"branch_dir": "devpulse", "next_number": 1}
        )
        assert tab.startswith("⟦ pad of 4 · oldest roll to .backup/todo/devpulse/backlog.json · ")

    def test_without_branch_context_the_tab_says_unknown_not_a_number(self):
        mod = _get_module()
        tab = mod.render_tab("todos", PAD_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG, "memory")
        assert tab == (
            "⟦ pad of 7 · oldest roll to .backup/todo/<branch>/backlog.json · task ≤150 chars · draft to 120 · next #? ⟧"
        )

    def test_no_configured_pad_size_says_nothing_rolls(self):
        mod = _get_module()
        tab = mod.render_tab(
            "todos", SAMPLE_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG, "memory", {"branch_dir": "memory", "next_number": 3}
        )
        assert tab == "⟦ no pad size configured — nothing rolls · task ≤150 chars · draft to 120 · next #3 ⟧"

    def test_the_tab_carries_numbers_only(self):
        """Prose is the template's; the RULE sentence and the old literal never come back."""
        mod = _get_module()
        tab = mod.render_tab("todos", PAD_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG, "memory")
        assert "RULE: DELETE" not in tab
        assert "cap ~10" not in tab
        assert "rollover OFF" not in tab
        assert tab.endswith("⟧")


class TestTodoContext:
    def test_next_number_is_the_highest_on_pad_or_in_backlog_plus_one(self, tmp_path):
        mod = _get_module()
        state = mod.todo_roll.read_backlog(_backlog_file(tmp_path / "backlog.json", [30, "31"]))

        ctx = mod.todo_context("memory", [{"number": 4}, {"number": True}, "note"], state)

        assert ctx == {"branch_dir": "memory", "next_number": 31}

    def test_an_empty_pad_and_no_backlog_start_at_one(self, tmp_path):
        mod = _get_module()
        state = mod.todo_roll.read_backlog(tmp_path / "absent.json")
        assert mod.todo_context("memory", [], state) == {"branch_dir": "memory", "next_number": 1}

    def test_an_unusable_backlog_gives_no_number(self, tmp_path):
        mod = _get_module()
        bad = tmp_path / "backlog.json"
        bad.write_text("[1, 2]", encoding="utf-8")
        assert mod.todo_context("memory", [], mod.todo_roll.read_backlog(bad))["next_number"] is None

    def test_a_pad_that_is_not_a_list_gives_no_number(self, tmp_path):
        mod = _get_module()
        state = mod.todo_roll.read_backlog(tmp_path / "absent.json")
        assert mod.todo_context("memory", {"a": 1}, state)["next_number"] is None

    def test_no_branch_gives_no_context(self):
        mod = _get_module()
        assert mod.todo_context(None, []) == {"branch_dir": None, "next_number": None}

    def test_refresh_names_the_branch_directory_and_derives_the_number(self, tmp_path, monkeypatch):
        """The registry name (backup) is not the directory (backup_dir); the backlog follows the directory."""
        mod = _get_module()
        seen = []

        def backlog_for(branch_dir, backup_root=None):
            seen.append(branch_dir)
            return _backlog_file(tmp_path / "backlog.json", [9])

        monkeypatch.setattr(mod.todo_roll, "backlog_path_for", backlog_for)
        trinity = tmp_path / "backup_dir" / ".trinity"
        trinity.mkdir(parents=True)
        local = trinity / "local.json"
        local.write_text(
            json.dumps({"todos": [{"number": 6}], "key_learnings": [], "sessions": []}),
            encoding="utf-8",
        )

        ok, err = mod._refresh_local("backup", local, PAD_ROLLOVER_CFG, SAMPLE_ENTRY_LIMITS_CFG)

        assert ok, err
        assert seen == ["backup_dir"]
        meta = json.loads(local.read_text(encoding="utf-8"))["todos_meta"]
        assert meta.startswith(
            "⟦ pad of 7 · oldest roll to .backup/todo/backup_dir/backlog.json · task ≤150 chars"
            " · draft to 120 · next #10 ⟧ "
        )


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
        assert local_data["todos_meta"].startswith(
            "⟦ no pad size configured — nothing rolls · task ≤150 chars · draft to 120 · next #"
        )
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

        assert tabs["TODOS_META"].endswith("· next #? ⟧")
        assert "rollover ON" in tabs["KEY_LEARNINGS_META"]
        assert "rollover ON" in tabs["SESSIONS_META"]
        assert "rollover ON" in tabs["OBSERVATIONS_META"]
        assert "{{" not in tabs["TODOS_META"]

    def test_a_named_branch_directory_reaches_the_todos_tab(self, tmp_path, monkeypatch):
        mod = _get_module()
        monkeypatch.setattr(
            mod.todo_roll, "backlog_path_for", lambda branch_dir, backup_root=None: tmp_path / "no.json"
        )
        mock_config = {"rollover": PAD_ROLLOVER_CFG, "entry_limits": SAMPLE_ENTRY_LIMITS_CFG}
        with patch("aipass.memory.apps.handlers.json.config_loader.load", return_value=mock_config):
            tabs = mod.render_all_meta_tabs(branch_dir="newborn")

        assert tabs["TODOS_META"] == (
            "⟦ pad of 7 · oldest roll to .backup/todo/newborn/backlog.json · task ≤150 chars · draft to 120 · next #1 ⟧"
        )

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
        assert tab.endswith("summary ≤300 chars · draft to 240 ⟧")
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
