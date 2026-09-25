# =================== META ====================
# Name: test_drive_mocked.py
# Description: Tests for the four drive_* command modules and the settings stub
# Version: 2.0.1
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Tests for apps/modules/drive_sync.py, drive_check.py, drive_stats.py, drive_clear.py and settings.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every module under apps/modules/ parses and imports
# seedgo: no-test-needed(documentation) — that each module's public functions carry docstrings
# seedgo: no-test-needed(constant) — the [bold cyan]/[yellow] styling in print_introspection(); tests read plain text
# seedgo: no-test-needed(stdlib) — the win32 preamble's os.environ.setdefault and stream reconfigure

import pytest

from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.modules import drive_check, drive_clear, drive_stats, drive_sync, settings

# MEASURED, and the reason every routing test below stops at the no-args route.
# These modules reach a REAL Google account one positional argument in.
# drive_check WAS the sharp one: the bottom of its handle_command used to be
# ``run_drive_check()`` as the DEFAULT branch, not a usage line, so any
# unrecognised first ARGUMENT was a live Drive auth (the module's own 2026-08-13
# comment records that `drive_check foo --help` used to do exactly that).
# That default branch is gone -- an unknown verb is now refused through error()
# before it can dial -- and the three pins in TestDriveCheckRouting hold it
# shut. The recorder they install is still what keeps THIS file off the network.
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
# the seal itself — what stands between this file and the real account
# ---------------------------------------------------------------------------


class TestSuiteWideDriveSeal:
    """conftest's autouse sealed_google_edge, proven from inside THIS file."""

    def test_the_oauth_flow_is_refused_rather_than_dialled(self) -> None:
        """Reaching for Drive auth from this file raises instead of authenticating.

        Until 2026-09-23 ``sealed_google_edge`` was a file-level autouse fixture
        declared inside test_drive_pipeline.py, so it covered that ONE file. This
        file drives the same four drive_* modules and had no seal of its own: the
        only thing keeping it off the network was each test's own recorder, and a
        route that slipped past a recorder reached the real account BEFORE the
        assertion that would have failed it -- the dial happens first, the red
        arrives after, and the account has already been touched.

        The fixture now lives in conftest.py as suite-wide autouse. This is the
        pin that shows the move reached here: get_drive_service is the OAuth flow
        itself, and calling it inside this file must be a RuntimeError, not a
        round trip. If the fixture is ever moved back, or shadowed by a file-level
        fixture of the same name, this test goes red and names the reason.
        """
        with pytest.raises(RuntimeError, match="live Google Drive edge"):
            drive_client.get_drive_service()

    def test_every_drive_request_is_refused_rather_than_sent(self) -> None:
        """The second door: api_call_with_retry carries every request the client sends."""
        with pytest.raises(RuntimeError, match="live Google Drive edge"):
            drive_client.api_call_with_retry(lambda: None)


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

    # The three pins below are the ARGUMENT guard, not the command guard above.
    # The command guard only screens args the router never sends here; these
    # screen what a user actually types after `drone @backup drive_check`.
    # The recorder on run_drive_check IS the oracle: it is a lambda, so a verb
    # that reaches it records instead of authenticating, and an empty list is
    # the proof that no OAuth round trip was attempted. Never replace it with a
    # bare call-through -- that turns a typo pin into a live Drive auth.

    def test_an_unknown_verb_is_refused_on_stderr_and_never_dials_drive(self, capsys, monkeypatch) -> None:
        """A typo is named back to the user, not answered with a real Google auth."""
        dialled: list = []
        monkeypatch.setattr(drive_check, "run_drive_check", lambda *a, **k: dialled.append((a, k)))

        # True, not False: route_command stops at the first module that claims
        # the command, so returning False here sends the operator the router's
        # own "Unknown command: drive_check" -- naming the command that DOES
        # exist instead of the verb that does not. error() marks the process
        # failed, so True still exits non-zero.
        assert drive_check.handle_command(drive_check.PRIMARY_COMMAND, ["statuss"]) is True

        out, err = capsys.readouterr()
        assert dialled == [], f"an unknown verb reached the Drive auth: {dialled!r}"
        assert "statuss" in err, f"the refusal did not name the bad verb: {err!r}"
        assert "run" in err, f"the refusal did not list the valid verbs: {err!r}"
        assert "Drive connectivity test" not in out

    def test_a_mistyped_flag_is_refused_the_same_way_as_a_mistyped_word(self, capsys, monkeypatch) -> None:
        """`--froce` is one keystroke from `--force` and was a live auth; it must be a refusal."""
        dialled: list = []
        monkeypatch.setattr(drive_check, "run_drive_check", lambda *a, **k: dialled.append((a, k)))

        assert drive_check.handle_command(drive_check.PRIMARY_COMMAND, ["--froce"]) is True

        out, err = capsys.readouterr()
        assert dialled == [], f"a mistyped flag reached the Drive auth: {dialled!r}"
        assert "--froce" in err, f"the refusal did not name the bad flag: {err!r}"
        assert "Drive connectivity test" not in out

    def test_the_run_verb_still_reaches_the_check_after_the_unknown_verb_guard(self, monkeypatch, capsys) -> None:
        """The guard refuses typos, not the one verb that is supposed to work."""
        dialled: list = []
        monkeypatch.setattr(drive_check, "run_drive_check", lambda *a, **k: dialled.append((a, k)))

        assert drive_check.handle_command(drive_check.PRIMARY_COMMAND, ["run"]) is True

        assert dialled == [((), {})], f"the guard swallowed the run verb: {dialled!r}"
        assert capsys.readouterr().err == ""


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

    # --force is the arming switch of the branch's one destructive verb, so it
    # is pinned AT THE SEAM: run_drive_clear is replaced by a recorder, and
    # what the recorder was handed is the flag's whole effect. A call-through
    # would reach clear_all for real, which is why this test never lets
    # handle_command past the recorder. The recorder is the FIRST thing standing
    # between args[0] and a live account; since 2026-09-23 conftest's autouse
    # sealed_google_edge stands behind it for every test in this file too, so a
    # route that slips past the recorder raises instead of dialling
    # (TestSuiteWideDriveSeal above is the pin on that).
    def test_force_arms_the_clear_and_the_same_command_without_it_does_not(
        self,
        tmp_path,
        capsys,
        monkeypatch,
    ) -> None:
        """--force reaches run_drive_clear as force=True; drop the flag and the same args are False."""
        armed: list = []
        monkeypatch.setattr(
            drive_clear,
            "run_drive_clear",
            lambda project_root, force=False: armed.append((project_root, force)),
        )

        assert drive_clear.handle_command(drive_clear.PRIMARY_COMMAND, [str(tmp_path), "--force"]) is True
        assert drive_clear.handle_command(drive_clear.PRIMARY_COMMAND, [str(tmp_path)]) is True

        out, err = capsys.readouterr()
        # Both rows, in order: the ONLY difference between them is the flag, so
        # a parse that hardcodes force -- in either direction -- fails here.
        assert armed == [(str(tmp_path), True), (str(tmp_path), False)], f"the flag did not reach the verb: {armed!r}"
        assert out == "", f"the route printed instead of delegating: {out!r}"
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
