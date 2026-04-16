# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: Tests for CLI routing and help output
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""Tests for spawn CLI routing, help output, and introspection."""

from unittest.mock import patch


class TestCliRouting:
    """Tests for spawn.py main() CLI routing."""

    def test_no_args_triggers_introspection(self):
        """main() with no args calls print_introspection."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn"]
            with patch("aipass.spawn.apps.spawn.print_introspection") as mock_intro:
                result = main()
        assert result == 0
        mock_intro.assert_called_once()

    def test_help_flag(self):
        """main() with --help calls print_help."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "--help"]
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_short_help(self):
        """main() with -h calls print_help."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "-h"]
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_help_word(self):
        """main() with 'help' command calls print_help."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "help"]
            with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
                result = main()
        assert result == 0
        mock_help.assert_called_once()

    def test_unknown_command(self):
        """main() with unknown command returns 1."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "nonexistent_command"]
            with patch("aipass.spawn.apps.spawn.error") as mock_error:
                result = main()
        assert result == 1
        mock_error.assert_called_once()

    def test_command_returns_int(self):
        """main() always returns an integer exit code."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn"]
            with patch("aipass.spawn.apps.spawn.print_introspection"):
                result = main()
        assert isinstance(result, int)


class TestCreateHelp:
    """Tests for create --help interception."""

    def test_create_help_flag(self):
        """create --help shows help instead of argparse error."""
        from aipass.spawn.apps.spawn import handle_create

        with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
            result = handle_create(["--help"])
        assert result == 0
        mock_help.assert_called_once()

    def test_create_short_help(self):
        """create -h shows help."""
        from aipass.spawn.apps.spawn import handle_create

        with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
            result = handle_create(["-h"])
        assert result == 0
        mock_help.assert_called_once()

    def test_create_help_with_class(self):
        """create builder --help shows help."""
        from aipass.spawn.apps.spawn import handle_create

        with patch("aipass.spawn.apps.spawn.print_help") as mock_help:
            result = handle_create(["builder", "--help"])
        assert result == 0
        mock_help.assert_called_once()


class TestCreateDryRun:
    """Tests for create --dry-run preview."""

    def test_dry_run_returns_zero(self, tmp_path):
        """--dry-run returns 0 for valid target."""
        from aipass.spawn.apps.spawn import handle_create

        target = str(tmp_path / "drytest")
        with patch("aipass.spawn.apps.spawn.console"), patch("aipass.spawn.apps.spawn.header"):
            result = handle_create([target, "--dry-run"])
        assert result == 0

    def test_dry_run_creates_no_files(self, tmp_path):
        """--dry-run creates nothing on disk."""
        from aipass.spawn.apps.spawn import handle_create

        target = tmp_path / "drytest"
        with patch("aipass.spawn.apps.spawn.console"), patch("aipass.spawn.apps.spawn.header"):
            handle_create([str(target), "--dry-run"])
        assert not target.exists()

    def test_dry_run_existing_target_returns_error(self, tmp_path):
        """--dry-run returns 1 if target already exists."""
        from aipass.spawn.apps.spawn import handle_create

        target = tmp_path / "existing"
        target.mkdir()
        with (
            patch("aipass.spawn.apps.spawn.console"),
            patch("aipass.spawn.apps.spawn.header"),
            patch("aipass.spawn.apps.spawn.error"),
        ):
            result = handle_create([str(target), "--dry-run"])
        assert result == 1


class TestTemplateFlag:
    """Tests for --template flag as class selector."""

    def test_template_flag_selects_class(self, tmp_path):
        """--template birthright creates birthright-class agent."""
        from aipass.spawn.apps.spawn import handle_create

        target = str(tmp_path / "tmpl_test")
        with patch("aipass.spawn.apps.spawn.console"), patch("aipass.spawn.apps.spawn.header"):
            result = handle_create([target, "--template", "birthright"])
        assert result == 0
        # Birthright class: has .trinity but no apps/
        assert (tmp_path / "tmpl_test" / ".trinity").exists()
        assert not (tmp_path / "tmpl_test" / "apps").exists()

    def test_template_flag_overrides_positional_class(self, tmp_path):
        """--template overrides positional class arg."""
        from aipass.spawn.apps.spawn import handle_create

        target = str(tmp_path / "override_test")
        # Positional says builder, flag says birthright
        with patch("aipass.spawn.apps.spawn.console"), patch("aipass.spawn.apps.spawn.header"):
            result = handle_create(["builder", target, "--template", "birthright"])
        assert result == 0
        # --template wins: birthright has no apps/
        assert not (tmp_path / "override_test" / "apps").exists()

    def test_template_flag_unknown_treated_as_path(self, tmp_path):
        """--template with unknown value is treated as path (backward compat)."""
        from aipass.spawn.apps.spawn import handle_create

        target = str(tmp_path / "path_test")
        with patch("aipass.spawn.apps.spawn.console"), patch("aipass.spawn.apps.spawn.error") as mock_error:
            result = handle_create([target, "--template", "/nonexistent/path"])
        assert result == 1
        mock_error.assert_called_once()

    def test_template_flag_dry_run(self, tmp_path):
        """--template works with --dry-run."""
        from aipass.spawn.apps.spawn import handle_create

        target = str(tmp_path / "drytest")
        with patch("aipass.spawn.apps.spawn.console"), patch("aipass.spawn.apps.spawn.header"):
            result = handle_create([target, "--template", "birthright", "--dry-run"])
        assert result == 0
        assert not (tmp_path / "drytest").exists()


class TestPassportHelp:
    """Tests for passport --help interception."""

    def test_passport_help_flag(self):
        """passport --help shows introspection."""
        from aipass.spawn.apps.modules.passport import handle_passport

        with patch("aipass.spawn.apps.modules.passport.print_introspection") as mock:
            result = handle_passport(["--help"])
        assert result == 0
        mock.assert_called_once()

    def test_passport_short_help(self):
        """passport -h shows introspection."""
        from aipass.spawn.apps.modules.passport import handle_passport

        with patch("aipass.spawn.apps.modules.passport.print_introspection") as mock:
            result = handle_passport(["-h"])
        assert result == 0
        mock.assert_called_once()


class TestPrintHelp:
    """Tests for print_help output."""

    def test_print_help_runs(self):
        """print_help executes without error."""
        from aipass.spawn.apps.spawn import print_help

        with patch("aipass.spawn.apps.spawn.console") as mock_console:
            with patch("aipass.spawn.apps.spawn.header"):
                with patch("aipass.spawn.apps.spawn.warning"):
                    print_help()
        assert mock_console.print.called


class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_print_introspection_runs(self):
        """print_introspection executes without error."""
        from aipass.spawn.apps.spawn import print_introspection

        with patch("aipass.spawn.apps.spawn.console") as mock_console:
            print_introspection()
        assert mock_console.print.called

    def test_output_capture(self):
        """Verify print_introspection mentions connected modules."""
        from aipass.spawn.apps.spawn import print_introspection

        calls = []
        with patch("aipass.spawn.apps.spawn.console") as mock_console:
            mock_console.print.side_effect = lambda *a, **kw: calls.append(str(a))
            print_introspection()
        output = " ".join(calls)
        assert "core.py" in output
