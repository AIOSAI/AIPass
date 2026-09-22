# =================== META ====================
# Name: test_drive_mocked.py
# Description: Tests for the four drive_* command modules and the settings stub
# Version: 2.0.0
# Created: 2026-06-12
# Modified: 2026-09-22
# =============================================

"""Tests for apps/modules/drive_sync.py, drive_check.py, drive_stats.py, drive_clear.py and settings.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module under apps/modules/ parses and imports
# seedgo: no-test-needed(documentation) — that each module's public functions carry docstrings
# seedgo: no-test-needed(constant) — the Rich colour tags the introspection lines carry; capsys strips them
# seedgo: no-test-needed(stdlib) — the win32 preamble's os.environ.setdefault and stream reconfigure

from aipass.backup.apps.modules import drive_check, drive_clear, drive_stats, drive_sync, settings

# MEASURED, and the reason every routing test below stops at the no-args route.
# These modules reach a REAL Google account one positional argument in.
# drive_check is the sharp one: the bottom of its handle_command is
# ``run_drive_check()`` as the DEFAULT branch, not a usage line, so any
# unrecognised first ARGUMENT is a live Drive auth (the module's own 2026-08-13
# comment records that `drive_check foo --help` used to do exactly that).
# drive_sync, drive_stats and drive_clear take args[0] as a project root and run.
# So the tests here pass [] or a command the module does not own; the run_*
# pipelines are exercised against a mocked Drive client in test_drive_pipeline.py
# (run_drive_sync) and test_cli_routing.py (the route, with run_* patched out).
# settings is the one module that answers an argument without touching Drive: it
# raises NotImplementedError, deliberately (refusal sweep 2026-09-07).
#
# The consoles are NOT mocked, and do not need to be: aipass.cli.apps.modules.console
# IS display.CONSOLE, a real Rich console printing to sys.stdout, and error()/warning()
# write to display.err_console on sys.stderr — capsys reads both, and conftest.py
# already pins both widths to 200 for the session.


# ---------------------------------------------------------------------------
# drive_sync — the routing a user actually types
# ---------------------------------------------------------------------------


class TestDriveSyncRouting:
    """`drone @backup drive_sync ...` — what the router does before the upload."""

    def test_no_args_names_the_module_and_the_handlers_it_drives(self, capsys) -> None:
        assert drive_sync.handle_command(drive_sync.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "drive_sync Module" in out
        assert "Handlers: drive/client, drive/upload, drive/tracker" in out
        assert err == ""

    # The type alone said nothing: True is a bool too, and a module that answered
    # True to every verb would have passed the old isinstance-only pin while
    # swallowing every other module's command. That exact bug was live in
    # display.py once (see test_cli_routing TestUnknownCommandNotSwallowed).
    # Printing nothing is half the claim: a module that declines must also stay
    # silent, or the router's next candidate prints under this one's output.
    def test_drive_sync_declines_a_verb_that_is_not_its_own(self, capsys) -> None:
        """An unclaimed verb returns False, silently, so the router keeps asking."""
        assert drive_sync.handle_command("nonexistent", []) is False

        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""


# ---------------------------------------------------------------------------
# drive_check — the module whose default branch is a live auth
# ---------------------------------------------------------------------------


class TestDriveCheckRouting:
    """`drone @backup drive_check ...` — the two routes that do not reach Drive."""

    def test_no_args_names_the_module_instead_of_running_the_connectivity_check(self, capsys) -> None:
        """No args is introspection; it must not print the check's own verdict lines."""
        assert drive_check.handle_command(drive_check.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "drive_check Module" in out
        assert "Handlers: drive/client, drive/test" in out
        assert "Drive connectivity test" not in out
        assert err == ""

    def test_a_verb_that_is_not_ours_is_declined_before_the_default_branch_is_reached(self, capsys) -> None:
        """The command guard is the only thing standing between an unknown verb and a live auth."""
        assert drive_check.handle_command("invalid_type", []) is False

        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""


# ---------------------------------------------------------------------------
# drive_stats — tracker statistics
# ---------------------------------------------------------------------------


class TestDriveStatsRouting:
    """`drone @backup drive_stats ...` — the route before a tracker is read."""

    def test_no_args_names_the_module_and_the_tracker_handler(self, capsys) -> None:
        assert drive_stats.handle_command(drive_stats.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "drive_stats Module" in out
        assert "Handlers: drive/tracker" in out
        assert err == ""


# ---------------------------------------------------------------------------
# drive_clear — the destructive one
# ---------------------------------------------------------------------------


class TestDriveClearRouting:
    """`drone @backup drive_clear ...` — the route before a tracker is deleted."""

    def test_no_args_names_the_module_and_says_the_clear_needs_force(self, capsys) -> None:
        """A destructive command's introspection has to say so; this is where a user reads it."""
        assert drive_clear.handle_command(drive_clear.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "drive_clear Module" in out
        assert "Handlers: drive/tracker (requires --force)" in out
        assert err == ""


# ---------------------------------------------------------------------------
# settings — a deferred command that must never look like it worked
# ---------------------------------------------------------------------------


class TestSettingsStub:
    """`drone @backup settings ...` — the two routes that answer, and what they say."""

    def test_no_args_names_the_module_as_a_stub_rather_than_an_opened_ui(self, capsys) -> None:
        assert settings.handle_command(settings.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "settings Module" in out
        assert "stub scaffold, awaiting Phase 3 implementation" in out
        assert err == ""

    def test_a_help_flag_is_answered_rather_than_refused(self, capsys) -> None:
        """Every other argument raises NotImplementedError; --help is the exception that describes it."""
        assert settings.handle_command(settings.PRIMARY_COMMAND, ["--help"]) is True

        out, err = capsys.readouterr()
        assert "settings Module" in out
        assert "Planned handlers: ui/settings_window" in out
        assert err == ""

    def test_introspection_is_not_recorded_as_a_stub_invocation(self, capsys, monkeypatch) -> None:
        """No args is a look, not a use: the audit trail must stay empty on this route."""
        logged: list = []
        monkeypatch.setattr(settings.trail, "log_operation", lambda name, payload: logged.append(name))

        assert settings.handle_command(settings.PRIMARY_COMMAND, []) is True

        assert logged == []
        assert "settings Module" in capsys.readouterr().out


# =============================================
