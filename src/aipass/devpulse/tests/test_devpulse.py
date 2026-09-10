# =================== AIPass ====================
# Name: test_devpulse.py
# Description: Tests for devpulse.py CLI routing, introspection, and resilience
# Version: 1.0.0
# Created: 2026-05-15
# Modified: 2026-05-15
# =============================================

"""Tests for devpulse.py — entry point CLI routing and module discovery."""

from types import SimpleNamespace
from unittest.mock import patch, MagicMock


from aipass.devpulse.apps import devpulse as devpulse_module
from aipass.devpulse.apps.modules import release_notify as release_notify_module


class TestCLIRouting:
    """CLI routing through _handle_command and main()."""

    def test_help_flag(self):
        """--help flag returns True."""
        result = devpulse_module._handle_command("--help", [])
        assert result is True

    def test_short_help(self):
        """-h flag returns True."""
        result = devpulse_module._handle_command("-h", [])
        assert result is True

    def test_help_word(self):
        """help word returns True."""
        result = devpulse_module._handle_command("help", [])
        assert result is True

    def test_version_flag(self):
        """--version flag returns True."""
        result = devpulse_module._handle_command("--version", [])
        assert result is True

    def test_version_short(self):
        """-V flag returns True."""
        result = devpulse_module._handle_command("-V", [])
        assert result is True

    def test_unknown_command_returns_false(self, capsys):
        """Unrecognized command returns False AND names the token on stderr.

        Patrick's unknown-argument ruling (fleet sweep 2026-09-07): fail
        non-zero and say which token was refused. Until 09-07 devpulse
        returned False with nothing printed — exit 1, empty stderr.
        """
        result = devpulse_module._handle_command("nonexistent_unknown_command", [])
        assert result is False
        err = capsys.readouterr().err
        assert "Unknown command: nonexistent_unknown_command" in err
        assert "--help" in err

    def test_unknown_flag_is_refused_by_name(self, capsys):
        """An unknown flag is refused like an unknown verb — named, not swallowed."""
        result = devpulse_module._handle_command("--definitely-not-a-flag", [])
        assert result is False
        assert "Unknown command: --definitely-not-a-flag" in capsys.readouterr().err

    def test_unknown_command_offers_a_close_match(self, capsys):
        """A near-miss of a real module name gets a did-you-mean."""
        result = devpulse_module._handle_command("watchdg", [])
        assert result is False
        assert "Did you mean: watchdog?" in capsys.readouterr().err

    def test_a_module_that_raises_is_reported_by_name_not_as_unknown(self, capsys):
        """A module exception names the module and the exception, never "Unknown command".

        Measured 2026-09-08: `compass query "opt-in"` raised
        sqlite3.OperationalError inside the module; route_command logged it
        and fell through to "Unknown command: compass / Did you mean: compass?"
        — handled=False, the real message in a log nobody reads.
        """

        def _raise(command, args):
            raise RuntimeError("no such column: in")

        broken = SimpleNamespace(__name__="aipass.devpulse.apps.modules.compass", handle_command=_raise)
        result = devpulse_module.route_command("compass", ["query", "opt-in"], [broken])
        assert result is True
        err = capsys.readouterr().err
        assert "compass failed on 'compass': RuntimeError: no such column: in" in err
        assert "Unknown command" not in err
        assert "Did you mean" not in err

    @patch.object(devpulse_module, "print_help")
    def test_print_help_called_on_help_flag(self, mock_print_help):
        """--help invokes print_help."""
        devpulse_module._handle_command("--help", [])
        mock_print_help.assert_called_once()

    @patch.object(devpulse_module, "print_introspection")
    def test_no_args_triggers_print_introspection(self, mock_introspection):
        """No args triggers print_introspection via main()."""
        with patch("sys.argv", ["devpulse"]):
            devpulse_module.main()
        mock_introspection.assert_called_once()

    @patch.object(devpulse_module, "print_introspection")
    def test_print_introspection_output(self, mock_introspection):
        """main() returns 0 when print_introspection runs."""
        mock_introspection.return_value = None
        with patch("sys.argv", ["devpulse"]):
            result = devpulse_module.main()
        assert result == 0


class TestModuleDiscovery:
    """discover_modules() finds modules with handle_command."""

    def test_discover_modules_returns_list(self):
        """Returns the four command modules that live in apps/modules/."""
        result = devpulse_module.discover_modules()
        names = {mod.__name__.rsplit(".", 1)[-1] for mod in result}
        assert {"watchdog", "compass", "feedback", "admin_grant"} <= names

    def test_discovered_modules_have_handle_command(self):
        """Each discovered module exposes handle_command."""
        modules = devpulse_module.discover_modules()
        assert modules, "discovery found nothing - the loop below would check nothing"
        assert all(callable(getattr(mod, "handle_command", None)) for mod in modules)


class TestErrorResilience:
    """Graceful handling of edge cases."""

    def test_route_command_catches_module_errors(self, capsys):
        """Module exceptions are caught, reported by name, and count as handled.

        Rewritten 2026-09-08: this pinned ``False`` - the fall-through that
        rendered a module crash as "Unknown command". The crash is now the
        module's failure (True, exit 2 through resolve_exit), named on stderr.
        """
        bad_module = MagicMock(__name__="bad_module")
        bad_module.handle_command.side_effect = Exception("boom")
        result = devpulse_module.route_command("test", [], [bad_module])
        assert result is True
        err = capsys.readouterr().err
        assert "bad_module failed on 'test': Exception: boom" in err
        assert "Unknown command" not in err

    def test_empty_file_modules_dir(self, tmp_path):
        """discover_modules handles empty_file in modules directory."""
        empty = tmp_path / "empty.py"
        empty.write_text("")
        with patch.object(devpulse_module, "MODULES_DIR", tmp_path):
            result = devpulse_module.discover_modules()
        assert result == []

    def test_handle_command_with_empty_args(self):
        """--help with empty args list succeeds."""
        result = devpulse_module.handle_command("--help", [])
        assert result is True


class TestHandleCommandGuard:
    """handle_command cross-branch security guard."""

    def test_handle_command_returns_bool(self):
        """handle_command always returns a bool."""
        result = devpulse_module.handle_command("--help", [])
        assert isinstance(result, bool)
        assert result is True

    def test_handle_command_unknown_returns_false(self, capsys):
        """Unknown commands return False through the guard, and say so."""
        result = devpulse_module.handle_command("bogus_invalid_command", [])
        assert result is False
        assert "bogus_invalid_command" in capsys.readouterr().err


class TestReleaseNotifyRouting:
    """release-notify routing — a question never becomes a send (DPLAN-0335 leg 1).

    The command mails every project manager on the machine. Every pin here is
    about the paths that must NOT reach the sender: help, a refused flag, a
    token that is not a version, and --dry-run.
    """

    def test_both_spellings_route_to_the_same_work(self):
        """The module file is release_notify.py; Patrick types release-notify."""
        with patch.object(release_notify_module, "_notify", return_value=True) as work:
            for spelling in ("release-notify", "release_notify"):
                assert release_notify_module.handle_command(spelling, ["v2.8.4"]) is True
        assert work.call_count == 2
        assert work.call_args.args == ("2.8.4", False, False)

    def test_help_anywhere_explains_and_never_sends(self, capsys):
        """A help flag in ANY position explains — it does not enumerate or send."""
        with patch.object(release_notify_module, "_notify") as work:
            assert release_notify_module.handle_command("release-notify", ["v2.8.4", "--help"]) is True
        work.assert_not_called()
        assert "release-notify" in capsys.readouterr().out

    def test_unknown_flag_is_refused_by_name(self, capsys):
        """An unrecognised flag names itself and nothing is sent."""
        with patch.object(release_notify_module, "_notify") as work:
            assert release_notify_module.handle_command("release-notify", ["v2.8.4", "--bogus"]) is True
        work.assert_not_called()
        assert "Unknown flag: --bogus" in capsys.readouterr().err

    def test_a_token_that_is_not_a_version_is_refused_by_name(self, capsys):
        """release-notify banana is refused, not sent as v-banana."""
        with patch.object(release_notify_module, "_notify") as work:
            assert release_notify_module.handle_command("release-notify", ["banana"]) is True
        work.assert_not_called()
        assert "Not a version: banana" in capsys.readouterr().err

    def test_dry_run_sends_nothing_reads_no_stamp_and_prints_the_body(self, capsys):
        """--dry-run is a preview: no mail, no commons post, no state file touched."""
        discovery = {
            "roots": ["/somewhere/Vera-Studio"],
            "managers": [{"address": "@vera", "name": "VERA", "passport": "/somewhere/passport.json", "root": "/x"}],
            "skipped": [{"path": "/somewhere/else/passport.json", "reason": "citizen_class is builder, not manager"}],
        }
        with (
            patch.object(release_notify_module, "discover_managers", return_value=discovery),
            patch.object(release_notify_module, "changelog_headline", return_value=["what shipped"]),
            patch.object(release_notify_module, "send_email", side_effect=AssertionError("dry run sent mail")),
            patch.object(release_notify_module, "post_commons", side_effect=AssertionError("dry run posted")),
            patch.object(release_notify_module, "load_state", side_effect=AssertionError("dry run read state")),
            patch.object(release_notify_module, "record_notified", side_effect=AssertionError("dry run wrote state")),
        ):
            assert release_notify_module.handle_command("release-notify", ["v2.8.4", "--dry-run"]) is True
        out = capsys.readouterr().out
        assert "@vera" in out
        assert "citizen_class is builder, not manager" in out
        assert "https://github.com/AIOSAI/AIPass/releases/tag/v2.8.4" in out
        assert "`" not in out
