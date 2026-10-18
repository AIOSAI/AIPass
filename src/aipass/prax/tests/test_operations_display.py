# =================== AIPass ====================
# Name: test_operations_display.py
# Description: Unit tests for the dashboard display and command handlers
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for the display and command handlers of apps/modules/dashboard.py."""

# conftest's _dashboard_quiet doubles the dashboard module's logger and json service per test.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — refresh_all_dashboards, covered by tests/test_operations_refresh.py

import json

import pytest

from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument
from aipass.prax.tests.support_test_operations import _load_dashboard_module, _Screen

pytestmark = pytest.mark.usefixtures("_dashboard_quiet")


class TestPrintStatus:
    """Tests for print_status -- CLI status display."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    def test_prints_branch_dashboard_status(self, tmp_path, monkeypatch):
        """Status prints the branch count and one exists/missing line per branch."""
        mod = _load_dashboard_module()

        branch1 = tmp_path / "flow"
        branch1.mkdir()
        (branch1 / "DASHBOARD.local.json").write_text("{}", encoding="utf-8")
        branch2 = tmp_path / "ai_mail"
        branch2.mkdir()

        monkeypatch.setattr(mod, "get_branch_paths", lambda: [branch1, branch2])

        mod.print_status()

        printed = self._screen.read().printed
        assert "Dashboard Status (2 branches)" in printed
        assert "  flow: exists" in printed
        assert "  ai_mail: missing" in printed
        assert self._screen.read().errors == []

    def test_handles_error_loading_branches(self, monkeypatch):
        """get_branch_paths blowing up prints the reason via error() and returns before the table."""
        mod = _load_dashboard_module()

        def raise_error():
            """Simulate registry load failure."""
            raise RuntimeError("registry not found")

        monkeypatch.setattr(mod, "get_branch_paths", raise_error)

        mod.print_status()

        self._screen.assert_one_error("Error loading branches: registry not found")
        assert self._screen.read().printed == []


class TestPrintTemplate:
    """Tests for print_template -- CLI template display."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    def test_prints_template_without_error(self):
        """The block printed under the heading round-trips back to DASHBOARD_TEMPLATE."""
        mod = _load_dashboard_module()

        mod.print_template()

        screen = self._screen.read()
        assert "Dashboard Template Structure" in screen.printed
        block = screen.out.split("=" * 50 + "\n", 1)[1]
        assert json.loads(block) == mod.DASHBOARD_TEMPLATE


class TestDashboardPrintIntrospection:
    """Tests for print_introspection -- CLI module info display."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    def test_introspection_lists_template_sections(self):
        """Introspection runs and names every section of the template."""
        mod = _load_dashboard_module()
        mod.print_introspection()

        printed = self._screen.read().printed
        assert len(printed) > 3
        for section in mod.DASHBOARD_TEMPLATE["sections"]:
            assert any(section in line for line in printed), f"section {section} not listed"


class TestDashboardPrintHelp:
    """Tests for print_help -- CLI help output."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    def test_help_lists_commands(self):
        """Help runs and names every subcommand the dispatch table accepts."""
        mod = _load_dashboard_module()
        mod.print_help()

        printed = self._screen.read().printed
        assert len(printed) > 5
        for command in ("status", "template", "refresh", "push-template", "diff-template", "template-status"):
            assert any(line.strip().startswith(command) for line in printed), f"{command} not documented"


class TestDashboardHandleCommand:
    """Tests for handle_command -- command routing."""

    def test_returns_false_for_non_dashboard_command(self):
        """handle_command returns False for commands other than 'dashboard'."""
        mod = _load_dashboard_module()
        assert mod.handle_command("monitor", []) is False

    def test_no_args_calls_print_introspection(self):
        """Bare 'dashboard' with no args shows introspection."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "print_introspection") as mock_intro:
            result = mod.handle_command("dashboard", [])
            assert result is True
            mock_intro.assert_called_once()

    def test_help_flag_calls_print_help(self):
        """--help flag shows help and returns True."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        for flag in ("--help", "-h", "help"):
            with _patch.object(mod, "print_help") as mock_help:
                result = mod.handle_command("dashboard", [flag])
                assert result is True
                mock_help.assert_called_once()

    def test_status_subcommand(self):
        """'status' subcommand dispatches to print_status."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "print_status") as mock_status:
            result = mod.handle_command("dashboard", ["status"])
            assert result is True
            mock_status.assert_called_once()

    def test_template_subcommand(self):
        """'template' subcommand dispatches to print_template."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "print_template") as mock_tmpl:
            result = mod.handle_command("dashboard", ["template"])
            assert result is True
            mock_tmpl.assert_called_once()

    def test_refresh_subcommand(self):
        """'refresh' subcommand dispatches to _handle_refresh."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_refresh") as mock_refresh:
            result = mod.handle_command("dashboard", ["refresh"])
            assert result is True
            mock_refresh.assert_called_once_with([])

    def test_refresh_subcommand_passes_args(self):
        """'refresh' subcommand forwards trailing args."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_refresh") as mock_refresh:
            mod.handle_command("dashboard", ["refresh", "--all"])
            mock_refresh.assert_called_once_with(["--all"])

    def test_push_template_subcommand(self):
        """'push-template' subcommand dispatches to _handle_push_template."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_push_template") as mock_push:
            result = mod.handle_command("dashboard", ["push-template"])
            assert result is True
            mock_push.assert_called_once_with([])

    def test_diff_template_subcommand(self):
        """'diff-template' subcommand dispatches to _handle_diff_template."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_diff_template") as mock_diff:
            result = mod.handle_command("dashboard", ["diff-template"])
            assert result is True
            mock_diff.assert_called_once_with([])

    def test_template_status_subcommand(self):
        """'template-status' subcommand dispatches to _handle_template_status."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_template_status") as mock_ts:
            result = mod.handle_command("dashboard", ["template-status"])
            assert result is True
            mock_ts.assert_called_once()

    def test_unknown_subcommand_shows_help(self):
        """Unknown subcommand is refused by name instead of printing help and exiting 0."""
        mod = _load_dashboard_module()

        with pytest.raises(UnknownArgument) as refusal:
            mod.handle_command("dashboard", ["bogus"])

        assert refusal.value.verb == "dashboard"
        assert refusal.value.token == "bogus"


class TestHandleRefresh:
    """Tests for _handle_refresh -- refresh command handler."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    def test_refresh_all(self, monkeypatch):
        """--all reports the updated count and never marks the command failed."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "refresh_all_dashboards",
            lambda: {"status": "success", "branches_updated": 3},
        )

        mod.handle_command("dashboard", ["refresh", "--all"])

        printed = self._screen.read().printed
        assert "Refreshing all branch dashboards..." in printed
        assert "Refreshed 3 branches" in printed
        assert self._screen.read().errors == []

    def test_refresh_all_partial(self, monkeypatch):
        """A partial refresh reports through error(), not warning() -- stale branches fail the command."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "refresh_all_dashboards",
            lambda: {
                "status": "partial",
                "branches_updated": 2,
                "branches_failed": 1,
                "errors": ["branch X failed"],
            },
        )

        mod.handle_command("dashboard", ["refresh", "--all"])

        assert "Refreshing all branch dashboards..." in self._screen.read().printed
        # error(), not warning(): only error() sets the failure flag main() reads
        # for its exit code, so a partial refresh must not exit 0.
        assert self._screen.read().errors == [
            "Refreshed 2 branches, 1 failed",
            "branch X failed",
        ]
        assert self._screen.read().warnings == []

    def test_refresh_all_failure(self, monkeypatch):
        """A failed refresh reports the headline and every error through error()."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "refresh_all_dashboards",
            lambda: {
                "status": "error",
                "branches_updated": 0,
                "branches_failed": 3,
                "errors": ["total failure"],
            },
        )

        mod.handle_command("dashboard", ["refresh", "--all"])

        assert "Refreshing all branch dashboards..." in self._screen.read().printed
        assert self._screen.read().errors == ["Refresh failed", "total failure"]

    def test_refresh_specific_branch_success(self, tmp_path, monkeypatch):
        """@branch names the resolved branch in both the progress and the result line."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(mod, "_resolve_branch_path", lambda ref: tmp_path / "flow")
        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "success", "branch": "FLOW"},
        )

        mod.handle_command("dashboard", ["refresh", "@flow"])

        printed = self._screen.read().printed
        assert "Refreshing FLOW dashboard..." in printed
        assert "Refreshed FLOW" in printed
        assert self._screen.read().errors == []

    def test_refresh_specific_branch_failure(self, tmp_path, monkeypatch):
        """A failed single-branch refresh reports the handler's reason through error()."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(mod, "_resolve_branch_path", lambda ref: tmp_path / "flow")
        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "error", "error": "disk full"},
        )

        mod.handle_command("dashboard", ["refresh", "@flow"])

        assert "Refreshing FLOW dashboard..." in self._screen.read().printed
        self._screen.assert_one_error("Failed: disk full")

    def test_refresh_specific_branch_not_found(self, monkeypatch):
        """An unresolvable @branch reports the lookup failure and never starts a refresh."""
        mod = _load_dashboard_module()

        def _raise(ref):
            """Simulate branch not found."""
            raise FileNotFoundError("not found in registry")

        monkeypatch.setattr(mod, "_resolve_branch_path", _raise)

        mod.handle_command("dashboard", ["refresh", "@ghost"])

        self._screen.assert_one_error("not found in registry")
        assert self._screen.read().printed == []

    def test_refresh_cwd_success(self, tmp_path, monkeypatch):
        """No args names the CWD directory, uppercased, as the branch being refreshed."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        # _handle_refresh walks UP from cwd for a marker; planting one here stops the walk
        # at tmp_path instead of an ancestor's .aipass the test never built.
        (tmp_path / "DASHBOARD.local.json").write_text("{}", encoding="utf-8")
        # The caller's directory outranks the process cwd; under drone it is set.
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "success", "branch": "PRAX"},
        )
        with _patch("pathlib.Path.cwd", return_value=tmp_path):
            mod.handle_command("dashboard", ["refresh"])

        printed = self._screen.read().printed
        assert f"Refreshing {tmp_path.name.upper()} dashboard..." in printed
        assert "Refreshed PRAX" in printed
        assert self._screen.read().errors == []

    def test_refresh_cwd_failure(self, tmp_path, monkeypatch):
        """A failed CWD refresh reports the handler's reason through error()."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        # See test_refresh_cwd_success: the marker keeps the ancestor walk
        # inside the sandbox this test built, and the caller's directory is unset.
        (tmp_path / "DASHBOARD.local.json").write_text("{}", encoding="utf-8")
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "error", "error": "no dashboard"},
        )
        with _patch("pathlib.Path.cwd", return_value=tmp_path):
            mod.handle_command("dashboard", ["refresh"])

        assert f"Refreshing {tmp_path.name.upper()} dashboard..." in self._screen.read().printed
        self._screen.assert_one_error("Failed: no dashboard")

    def test_bare_refresh_refreshes_the_callers_branch_not_prax(self, tmp_path, monkeypatch):
        """drone runs prax with cwd at prax, so the caller's branch comes from AIPASS_CALLER_CWD."""
        from unittest.mock import patch as _patch

        mod = _load_dashboard_module()
        prax, flow = tmp_path / "prax", tmp_path / "flow"
        for branch in (prax, flow):
            (branch / "apps").mkdir(parents=True)
            (branch / "DASHBOARD.local.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(flow / "apps"))
        refreshed: list = []
        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: refreshed.append(bp) or {"status": "success", "branch": bp.name.upper()},
        )

        with _patch("pathlib.Path.cwd", return_value=prax):
            mod.handle_command("dashboard", ["refresh"])

        assert refreshed == [flow]
        assert "Refreshed FLOW" in self._screen.read().printed

    def test_bare_refresh_with_no_caller_directory_refuses_by_name(self, monkeypatch):
        """No caller variable and a deleted cwd: say how to name the branch, refresh nothing."""
        from unittest.mock import patch as _patch

        mod = _load_dashboard_module()
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        refreshed: list = []
        monkeypatch.setattr(mod, "refresh_single_dashboard", lambda bp: refreshed.append(bp))

        with _patch("pathlib.Path.cwd", side_effect=FileNotFoundError("deleted")):
            mod.handle_command("dashboard", ["refresh"])

        assert refreshed == []
        self._screen.assert_one_error(
            "No caller directory, so no branch to refresh. Name it: drone @prax dashboard refresh @branch"
        )


class TestCallerDir:
    """_caller_dir -- where the caller stands, which under drone is not the process cwd."""

    @pytest.mark.parametrize("value", ["", None], ids=["empty", "unset"])
    def test_an_empty_or_unset_variable_falls_back_to_the_process_cwd(self, tmp_path, monkeypatch, value):
        """An empty AIPASS_CALLER_CWD is absence: Path('') would name wherever the process stands."""
        from unittest.mock import patch as _patch

        mod = _load_dashboard_module()
        if value is None:
            monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        else:
            monkeypatch.setenv("AIPASS_CALLER_CWD", value)

        seen: list = []

        def _record(ref, caller=None):
            seen.append(caller)
            return tmp_path / "flow"

        # The caller directory is what refresh hands the resolver.
        monkeypatch.setattr(mod, "resolve_branch_path", _record)
        monkeypatch.setattr(mod, "refresh_single_dashboard", lambda bp: {"status": "success", "branch": "FLOW"})

        with _patch("pathlib.Path.cwd", return_value=tmp_path):
            mod.handle_command("dashboard", ["refresh", "@flow"])

        assert seen == [tmp_path]


class TestDashboardMain:
    """Tests for main -- CLI entry point."""

    def test_main_no_args(self, monkeypatch):
        """No args shows introspection."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr("sys.argv", ["dashboard"])
        with _patch.object(mod, "print_introspection") as mock_intro:
            mod.main()
        mock_intro.assert_called_once_with()

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_main_help_flag(self, monkeypatch, flag):
        """Both help aliases show help and route nowhere else."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr("sys.argv", ["dashboard", flag])
        with (
            _patch.object(mod, "print_help") as mock_help,
            _patch.object(mod, "handle_command") as mock_hc,
        ):
            mod.main()

        mock_help.assert_called_once()
        mock_hc.assert_not_called()

    def test_main_valid_command(self, monkeypatch):
        """Valid command delegates to handle_command."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr("sys.argv", ["dashboard", "dashboard", "status"])
        with _patch.object(mod, "handle_command", return_value=True) as mock_hc:
            mod.main()
        mock_hc.assert_called_once_with("dashboard", ["status"])

    def test_main_unknown_command(self, monkeypatch):
        """Unknown command shows error and help."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr("sys.argv", ["dashboard", "bogus"])
        with (
            _patch.object(mod, "handle_command", return_value=False),
            _patch.object(mod, "print_help") as mock_help,
            _patch.object(mod, "error") as mock_error,
        ):
            mod.main()
        mock_help.assert_called_once_with()
        mock_error.assert_called_once_with("Unknown command: bogus")
