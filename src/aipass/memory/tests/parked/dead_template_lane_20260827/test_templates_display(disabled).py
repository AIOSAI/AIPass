# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_templates_display.py
# Date: 2026-04-26
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for templates module display functions -- line coverage.

Covers: from aipass.memory.apps.modules.templates import handle_command
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers: build the full mock graph that templates.py needs at import time
# ---------------------------------------------------------------------------


def _prepare_templates_mocks(monkeypatch):
    mock_panel = MagicMock()
    rich_panel_mod = MagicMock()
    rich_panel_mod.Panel = mock_panel
    monkeypatch.setitem(sys.modules, "rich.panel", rich_panel_mod)
    monkeypatch.setitem(sys.modules, "rich", MagicMock())

    mock_console = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    cli_modules_mod = MagicMock()
    cli_modules_mod.console = mock_console
    cli_modules_mod.error = mock_error
    cli_modules_mod.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules_mod)

    mock_memory_files = MagicMock()
    mock_memory_files.read_memory_file_data = MagicMock(return_value=None)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)

    mock_pusher = MagicMock()
    mock_pusher.push_templates = MagicMock(
        return_value={
            "success": True,
            "branches_scanned": 5,
            "branches_updated": 2,
            "files_modified": 3,
            "changes": [],
            "errors": [],
        }
    )
    mock_pusher.get_template_status = MagicMock(
        return_value={
            "version": "2.0.0",
            "last_push": "2026-03-20",
            "local_template_exists": True,
            "observations_template_exists": True,
            "templates_dir": "/tmp/templates",
            "last_push_branches": [],
        }
    )
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.templates.pusher", mock_pusher)

    mock_differ = MagicMock()
    mock_differ.diff_template_vs_branch = MagicMock(
        return_value={
            "local": [],
            "observations": [],
            "errors": [],
        }
    )
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.templates.differ", mock_differ)

    mock_spawn_pusher = MagicMock()
    mock_spawn_pusher.push_to_spawn_templates = MagicMock(
        return_value={
            "success": True,
            "template_sets_found": [],
            "template_sets_updated": 0,
            "files_modified": 0,
            "changes": [],
        }
    )
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.templates.spawn_pusher", mock_spawn_pusher)

    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.templates",
        MagicMock(pusher=mock_pusher, differ=mock_differ, spawn_pusher=mock_spawn_pusher),
    )

    return {
        "console": mock_console,
        "error": mock_error,
        "warning": mock_warning,
        "pusher": mock_pusher,
        "differ": mock_differ,
        "spawn_pusher": mock_spawn_pusher,
        "memory_files": mock_memory_files,
    }


def _import_templates(monkeypatch):
    mocks = _prepare_templates_mocks(monkeypatch)
    sys.modules.pop("aipass.memory.apps.modules.templates", None)
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "templates"):
        delattr(parent, "templates")
    from aipass.memory.apps.modules import templates

    return templates, mocks


# ===========================================================================
# Tests: print_help
# ===========================================================================


class TestPrintHelp:
    """Tests for print_help -- outputs usage panel and command list."""

    def test_print_help_outputs_usage(self, monkeypatch) -> None:
        """print_help calls console.print multiple times for usage info."""
        templates, mocks = _import_templates(monkeypatch)

        templates.print_help()

        # Lines 192-209: 7+ console.print calls (blank lines + panel + usage lines)
        assert mocks["console"].print.call_count >= 7


# ===========================================================================
# Tests: print_introspection
# ===========================================================================


class TestPrintIntrospection:
    """Tests for print_introspection -- displays module identity, handlers, subcommands."""

    def test_introspection_with_handlers(self, monkeypatch) -> None:
        """With discovered handlers, prints handler listing and subcommands."""
        templates, mocks = _import_templates(monkeypatch)

        fake_handlers = {
            "json": ["json_handler.py", "memory_files.py"],
            "templates": ["pusher.py", "differ.py"],
        }
        monkeypatch.setattr(templates, "_discover_handlers", lambda: fake_handlers)

        templates.print_introspection()

        # Should print handler dirs and subcommand list
        assert mocks["console"].print.call_count >= 10

    def test_introspection_no_handlers(self, monkeypatch) -> None:
        """With no handlers found, prints 'No handlers found' message."""
        templates, mocks = _import_templates(monkeypatch)

        monkeypatch.setattr(templates, "_discover_handlers", lambda: {})

        templates.print_introspection()

        # Should still print subcommands and hints even with no handlers
        assert mocks["console"].print.call_count >= 8


# ===========================================================================
# Tests: _display_push_results
# ===========================================================================


class TestDisplayPushResults:
    """Tests for _display_push_results -- formats push_templates() handler result."""

    def test_push_results_success_with_changes(self, monkeypatch) -> None:
        """Success with changes list, not dry_run -- displays change details."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": True,
            "branches_scanned": 5,
            "branches_updated": 2,
            "files_modified": 3,
            "changes": [
                {
                    "branch": "CLI",
                    "file": "local.json",
                    "changes": ["added field_x", "added field_y"],
                },
            ],
            "errors": [],
        }

        templates._display_push_results(result, dry_run=False)

        # Verify console.print was called (panel, summary, changes, final status)
        assert mocks["console"].print.call_count >= 8

    def test_push_results_success_no_changes(self, monkeypatch) -> None:
        """Success with no changes -- displays 'up to date' message."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": True,
            "branches_scanned": 5,
            "branches_updated": 0,
            "files_modified": 0,
            "changes": [],
            "errors": [],
        }

        templates._display_push_results(result, dry_run=False)

        # Should hit the 'All branches are up to date' and 'No updates needed' paths
        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "up to date" in joined or "No updates needed" in joined

    def test_push_results_dry_run_with_changes(self, monkeypatch) -> None:
        """dry_run=True with changes -- shows DRY RUN label and 'would be updated'."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": True,
            "branches_scanned": 5,
            "branches_updated": 2,
            "files_modified": 3,
            "changes": [
                {"branch": "CLI", "file": "local.json", "changes": ["added field"]},
            ],
            "errors": [],
        }

        templates._display_push_results(result, dry_run=True)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "DRY RUN" in joined

    def test_push_results_failure(self, monkeypatch) -> None:
        """success=False with errors -- displays failure message and errors."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": False,
            "branches_scanned": 0,
            "branches_updated": 0,
            "files_modified": 0,
            "changes": [],
            "errors": ["Registry not found", "Permission denied"],
        }

        templates._display_push_results(result, dry_run=False)

        # error() should be called for each error plus the failure header
        assert mocks["error"].call_count >= 2

    def test_push_results_with_errors(self, monkeypatch) -> None:
        """success=True but errors list non-empty -- shows both success summary and errors."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": True,
            "branches_scanned": 5,
            "branches_updated": 2,
            "files_modified": 3,
            "changes": [
                {"branch": "CLI", "file": "local.json", "changes": ["added field"]},
            ],
            "errors": ["Branch ALPHA: permission denied"],
        }

        templates._display_push_results(result, dry_run=False)

        # error() called for the error entry
        assert mocks["error"].call_count >= 1
        # console.print still used for summary
        assert mocks["console"].print.call_count >= 8


# ===========================================================================
# Tests: _display_spawn_push_results
# ===========================================================================


class TestDisplaySpawnPushResults:
    """Tests for _display_spawn_push_results -- formats spawn template push results."""

    def test_spawn_push_failure(self, monkeypatch) -> None:
        """success=False with errors -- calls error() for each."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": False,
            "errors": ["Spawn dir not found", "Template missing"],
        }

        templates._display_spawn_push_results(result, dry_run=False)

        assert mocks["error"].call_count >= 2

    def test_spawn_push_up_to_date(self, monkeypatch) -> None:
        """success=True, files_modified=0, no changes -- prints 'up to date'."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": True,
            "template_sets_found": ["set_a"],
            "template_sets_updated": 0,
            "files_modified": 0,
            "changes": [],
        }

        templates._display_spawn_push_results(result, dry_run=False)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "up to date" in joined

    def test_spawn_push_with_changes(self, monkeypatch) -> None:
        """success=True, files_modified>0, changes present -- prints update details."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": True,
            "template_sets_found": ["set_a", "set_b"],
            "template_sets_updated": 1,
            "files_modified": 2,
            "changes": [
                {"template_set": "set_a", "file": "local.json", "action": "updated"},
                {"template_set": "set_a", "file": "obs.json", "action": "created"},
            ],
        }

        templates._display_spawn_push_results(result, dry_run=False)

        # Should print summary line + change detail lines
        assert mocks["console"].print.call_count >= 3

    def test_spawn_push_dry_run(self, monkeypatch) -> None:
        """dry_run=True with changes -- uses 'would update' phrasing."""
        templates, mocks = _import_templates(monkeypatch)

        result = {
            "success": True,
            "template_sets_found": ["set_a"],
            "template_sets_updated": 1,
            "files_modified": 1,
            "changes": [
                {"template_set": "set_a", "file": "local.json", "action": "updated"},
            ],
        }

        templates._display_spawn_push_results(result, dry_run=True)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "would update" in joined


# ===========================================================================
# Tests: _display_diff_results
# ===========================================================================


class TestDisplayDiffResults:
    """Tests for _display_diff_results -- calls differ handler, displays per-branch results."""

    def _make_branches(self, tmp_path: Path, names: list[str]) -> list[dict]:
        """Create branch dicts with real temp directories."""
        branches = []
        for name in names:
            branch_dir = tmp_path / name.lower()
            branch_dir.mkdir(parents=True, exist_ok=True)
            branches.append(
                {
                    "name": name,
                    "path": str(branch_dir),
                    "status": "active",
                }
            )
        return branches

    def test_diff_all_branches_no_diffs(self, tmp_path: Path, monkeypatch) -> None:
        """All branches up to date -- shows 'up to date' for each and summary."""
        templates, mocks = _import_templates(monkeypatch)

        branches = self._make_branches(tmp_path, ["CLI", "MEMORY"])
        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: branches)
        monkeypatch.setattr(
            templates,
            "diff_template_vs_branch",
            lambda path: {"local": [], "observations": [], "errors": []},
        )

        templates._display_diff_results(None)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "up to date" in joined.lower()

    def test_diff_with_diffs(self, tmp_path: Path, monkeypatch) -> None:
        """Branches have local/obs diffs -- displays diff entries and warning."""
        templates, mocks = _import_templates(monkeypatch)

        branches = self._make_branches(tmp_path, ["CLI", "MEMORY"])
        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: branches)

        def fake_diff(path: str) -> dict:
            """Return fake diff result with local and observations diffs."""
            return {
                "local": [{"file": "local.json", "additions": ["field_x"]}],
                "observations": [{"file": "observations.json", "removals": ["old_field"]}],
                "errors": [],
            }

        monkeypatch.setattr(templates, "diff_template_vs_branch", fake_diff)

        templates._display_diff_results(None)

        # warning() called because branches have diffs
        assert mocks["warning"].call_count >= 1

    def test_diff_specific_branch(self, tmp_path: Path, monkeypatch) -> None:
        """branch_name filter applied -- only diffs the named branch."""
        templates, mocks = _import_templates(monkeypatch)

        branches = self._make_branches(tmp_path, ["CLI", "MEMORY", "DRONE"])
        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: branches)
        monkeypatch.setattr(
            templates,
            "diff_template_vs_branch",
            lambda path: {"local": [], "observations": [], "errors": []},
        )

        templates._display_diff_results("CLI")

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "CLI" in joined

    def test_diff_branch_not_found(self, tmp_path: Path, monkeypatch) -> None:
        """Filtered branch not in registry -- displays error."""
        templates, mocks = _import_templates(monkeypatch)

        branches = self._make_branches(tmp_path, ["CLI", "MEMORY"])
        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: branches)

        templates._display_diff_results("NONEXISTENT")

        assert mocks["error"].call_count >= 1

    def test_diff_registry_load_fails(self, monkeypatch) -> None:
        """_load_branches_from_registry returns None -- displays error."""
        templates, mocks = _import_templates(monkeypatch)

        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: None)

        templates._display_diff_results(None)

        assert mocks["error"].call_count >= 1

    def test_diff_branch_path_missing(self, tmp_path: Path, monkeypatch) -> None:
        """Branch path doesn't exist on disk -- displays error and increments error count."""
        templates, mocks = _import_templates(monkeypatch)

        branches = [
            {"name": "GHOST", "path": str(tmp_path / "nonexistent_dir"), "status": "active"},
        ]
        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: branches)

        templates._display_diff_results(None)

        # error() called for missing path
        assert mocks["error"].call_count >= 1

    def test_diff_handler_exception(self, tmp_path: Path, monkeypatch) -> None:
        """diff_template_vs_branch raises exception -- caught and error displayed."""
        templates, mocks = _import_templates(monkeypatch)

        branches = self._make_branches(tmp_path, ["CLI"])
        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: branches)
        monkeypatch.setattr(
            templates,
            "diff_template_vs_branch",
            MagicMock(side_effect=RuntimeError("handler exploded")),
        )

        templates._display_diff_results(None)

        assert mocks["error"].call_count >= 1

    def test_diff_handler_returns_errors(self, tmp_path: Path, monkeypatch) -> None:
        """Diff result has errors list -- errors displayed per branch."""
        templates, mocks = _import_templates(monkeypatch)

        branches = self._make_branches(tmp_path, ["CLI"])
        monkeypatch.setattr(templates, "_load_branches_from_registry", lambda: branches)
        monkeypatch.setattr(
            templates,
            "diff_template_vs_branch",
            lambda path: {"local": [], "observations": [], "errors": ["file not readable"]},
        )

        templates._display_diff_results(None)

        # error() called for the error entry
        assert mocks["error"].call_count >= 1


# ===========================================================================
# Tests: _display_file_diffs
# ===========================================================================


class TestDisplayFileDiffs:
    """Tests for _display_file_diffs -- displays individual file diff entries."""

    def test_file_diffs_additions(self, monkeypatch) -> None:
        """Entries with additions -- prints green + lines."""
        templates, mocks = _import_templates(monkeypatch)

        file_diffs = [
            {"file": "local.json", "additions": ["field_a", "field_b"]},
        ]

        templates._display_file_diffs(file_diffs)

        # One file header line + two addition lines
        assert mocks["console"].print.call_count >= 3

    def test_file_diffs_removals(self, monkeypatch) -> None:
        """Entries with removals -- prints red - lines."""
        templates, mocks = _import_templates(monkeypatch)

        file_diffs = [
            {"file": "local.json", "removals": ["old_field"]},
        ]

        templates._display_file_diffs(file_diffs)

        assert mocks["console"].print.call_count >= 2

    def test_file_diffs_modifications(self, monkeypatch) -> None:
        """Entries with modifications -- prints yellow ~ lines."""
        templates, mocks = _import_templates(monkeypatch)

        file_diffs = [
            {"file": "local.json", "modifications": ["changed_field"]},
        ]

        templates._display_file_diffs(file_diffs)

        assert mocks["console"].print.call_count >= 2

    def test_file_diffs_empty(self, monkeypatch) -> None:
        """Empty list -- no console.print calls."""
        templates, mocks = _import_templates(monkeypatch)

        templates._display_file_diffs([])

        assert mocks["console"].print.call_count == 0


# ===========================================================================
# Tests: _display_status
# ===========================================================================


class TestDisplayStatus:
    """Tests for _display_status -- displays template status info."""

    def test_status_templates_exist(self, monkeypatch) -> None:
        """local + obs templates found -- shows 'found' labels."""
        templates, mocks = _import_templates(monkeypatch)

        status = {
            "version": "2.0.0",
            "last_push": "2026-03-20",
            "local_template_exists": True,
            "observations_template_exists": True,
            "templates_dir": "/tmp/templates",
            "last_push_branches": [],
        }

        templates._display_status(status)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "found" in joined
        assert "2.0.0" in joined

    def test_status_templates_missing(self, monkeypatch) -> None:
        """Templates not found -- shows 'MISSING' labels."""
        templates, mocks = _import_templates(monkeypatch)

        status = {
            "version": None,
            "last_push": None,
            "local_template_exists": False,
            "observations_template_exists": False,
            "templates_dir": "/tmp/templates",
            "last_push_branches": [],
        }

        templates._display_status(status)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "MISSING" in joined

    def test_status_with_pushed_branches(self, monkeypatch) -> None:
        """last_push_branches has entries -- shows branch count and names."""
        templates, mocks = _import_templates(monkeypatch)

        status = {
            "version": "2.0.0",
            "last_push": "2026-03-20",
            "local_template_exists": True,
            "observations_template_exists": True,
            "templates_dir": "/tmp/templates",
            "last_push_branches": ["CLI", "MEMORY", "DRONE"],
        }

        templates._display_status(status)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "3" in joined
        assert "CLI" in joined

    def test_status_many_branches(self, monkeypatch) -> None:
        """>8 pushed branches -- display is truncated with '... (+N more)'."""
        templates, mocks = _import_templates(monkeypatch)

        branch_names = [f"BRANCH_{i}" for i in range(12)]
        status = {
            "version": "2.0.0",
            "last_push": "2026-03-20",
            "local_template_exists": True,
            "observations_template_exists": True,
            "templates_dir": "/tmp/templates",
            "last_push_branches": branch_names,
        }

        templates._display_status(status)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "+4 more" in joined
        assert "12" in joined

    def test_status_no_pushed_branches(self, monkeypatch) -> None:
        """Empty last_push_branches -- shows 'none'."""
        templates, mocks = _import_templates(monkeypatch)

        status = {
            "version": "2.0.0",
            "last_push": "2026-03-20",
            "local_template_exists": True,
            "observations_template_exists": True,
            "templates_dir": "/tmp/templates",
            "last_push_branches": [],
        }

        templates._display_status(status)

        call_args_list = [str(c) for c in mocks["console"].print.call_args_list]
        joined = " ".join(call_args_list)
        assert "none" in joined
