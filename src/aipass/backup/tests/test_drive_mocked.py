# =================== META ====================
# Name: test_drive_mocked.py
# Description: Tests for the drive_* command modules, the settings verb and the suite-wide Drive seal
# Version: 2.0.4
# Created: 2026-06-12
# Modified: 2026-10-16
# =============================================

"""Tests for apps/modules/drive_*.py and settings.py, and the Drive seal on apps/handlers/drive/client.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the six modules imported below parse; ruff parses, it does not import
# seedgo: no-test-needed(documentation) — that each module's public functions carry docstrings
# seedgo: no-test-needed(constant) — the [bold cyan]/[yellow] styling in print_introspection(); tests read plain text
# seedgo: no-test-needed(stdlib) — the win32 preamble's os.environ.setdefault and stream reconfigure

import json
from pathlib import Path

import pytest

from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.project import registry
from aipass.backup.apps.modules import drive_check, drive_clear, drive_stats, drive_sync, settings

# What is not pinned here, and where it is. Two run_* verbs reach a REAL Google
# account: run_drive_check builds a DriveClient (drive_check.py:58-62) and
# run_drive_sync authenticates one (drive_sync.py:104-105). run_drive_clear
# overwrites the local tracker for real (handlers/drive/tracker.py:192-206),
# run_drive_stats only reads it (drive_stats.py:55-65), and settings has no run_*.
# Every test below that passes an argument a run_* could act on first replaces
# that run_* with a recorder; for the two that dial, conftest's autouse
# sealed_google_edge stands behind the recorder (TestSuiteWideDriveSeal).
# The run_* pipelines run against a mocked Drive client in test_drive_pipeline.py.
# The project_root routes of drive_sync and drive_stats (drive_sync's --note and
# --project included) and settings' NotImplementedError on any argument other
# than help, --help or -h are pinned in test_cli_routing.py.
#
# The consoles are NOT mocked, and do not need to be: aipass.cli.apps.modules.console
# IS display.CONSOLE, a real Rich console printing to sys.stdout, and error()/warning()
# write to display.err_console on sys.stderr — capsys reads both, and conftest.py
# already pins both widths to 200 for the session.


# ---------------------------------------------------------------------------
# the seal itself — what stands between this file and the real account
# ---------------------------------------------------------------------------


class TestSuiteWideDriveSeal:
    """Pins the harness, not the product: conftest's autouse sealed_google_edge, proven from inside THIS file."""

    def test_the_oauth_flow_is_refused_rather_than_dialled(self) -> None:
        """Reaching for Drive auth from this file raises instead of authenticating."""
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
        """No args is introspection: it names drive_sync and its three handlers, on stdout only."""
        assert drive_sync.handle_command(drive_sync.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "drive_sync Module" in out
        assert "Handlers: drive/client, drive/upload, drive/tracker" in out
        assert err == ""

    # `is False`, not a bool check: a module that answered True to every verb
    # would swallow every other module's command. Printing nothing is half the
    # claim: a module that declines must also stay silent, or the router's next
    # candidate prints under this one's output.
    def test_drive_sync_declines_a_verb_that_is_not_its_own(self, capsys) -> None:
        """An unclaimed verb returns False, silently, so the router keeps asking."""
        assert drive_sync.handle_command("nonexistent", []) is False

        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""


# ---------------------------------------------------------------------------
# drive_check — the module whose run verb is a live auth
# ---------------------------------------------------------------------------


class TestDriveCheckRouting:
    """`drone @backup drive_check ...` — which arguments reach the connectivity check."""

    def test_no_args_names_the_module_instead_of_running_the_connectivity_check(self, capsys) -> None:
        """No args is introspection; it must not print the check's own verdict lines."""
        assert drive_check.handle_command(drive_check.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "drive_check Module" in out
        assert "Handlers: drive/client, drive/test" in out
        assert "Drive connectivity test" not in out
        assert err == ""

    def test_a_command_that_is_not_drive_check_is_declined_silently(self, capsys) -> None:
        """An unclaimed command returns False and prints nothing, so the router keeps asking."""
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
        """No args is introspection: it names drive_stats and the tracker handler, on stdout only."""
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
    # handle_command past the recorder. conftest's autouse sealed_google_edge
    # stands behind the recorder, so a route that slips past it raises instead
    # of dialling (TestSuiteWideDriveSeal above is the pin on that).
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
# settings — one live key, and a deferred UI that must never look like it worked
# ---------------------------------------------------------------------------


class TestSettingsStub:
    """`drone @backup settings ...` — the two routes that answer, and what they say."""

    def test_no_args_names_the_one_live_key_and_the_deferred_ui(self, capsys) -> None:
        """No args is introspection: drive_sync is live, the UI awaits Phase 3, on stdout only."""
        assert settings.handle_command(settings.PRIMARY_COMMAND, []) is True

        out, err = capsys.readouterr()
        assert "settings Module" in out
        assert "drive_sync on|off is live; the settings UI awaits Phase 3" in out
        assert err == ""

    def test_a_help_flag_is_answered_rather_than_refused(self, capsys) -> None:
        """--help prints the usage line instead of raising the refusal."""
        assert settings.handle_command(settings.PRIMARY_COMMAND, ["--help"]) is True

        out, err = capsys.readouterr()
        assert "settings Module" in out
        assert "Usage: settings drive_sync on|off <project_path|@name>" in out
        assert err == ""

    def test_introspection_is_not_recorded_as_a_stub_invocation(self, capsys, monkeypatch) -> None:
        """No args is a look, not a use: the audit trail must stay empty on this route."""
        logged: list = []
        monkeypatch.setattr(settings.trail, "log_operation", lambda name, payload: logged.append(name))

        assert settings.handle_command(settings.PRIMARY_COMMAND, []) is True

        assert logged == []
        assert "settings Module" in capsys.readouterr().out


def _settings(argv: list[str]) -> int:
    """Run `backup settings ...` through the real entry point."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.argv", ["backup", "settings", *argv])
        return entry.main()


def _store(root: Path, config: dict | None = None) -> Path:
    """A project with a .backup/ store and, when given, a config document."""
    (root / ".backup").mkdir(parents=True)
    if config is not None:
        (root / ".backup" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _config(root: Path) -> dict:
    """The project's config document as written on disk."""
    return json.loads((root / ".backup" / "config.json").read_text(encoding="utf-8"))


class TestSettingsDriveSync:
    """`settings drive_sync on|off <project_path|@name>` writes the one live key."""

    def test_on_writes_true_keeps_the_other_keys_and_prints_the_new_value(self, tmp_path, capsys) -> None:
        project = _store(tmp_path / "proj", {"max_versions": 3, "drive_sync": False})

        assert _settings(["drive_sync", "on", str(project)]) == 0

        assert _config(project) == {"max_versions": 3, "drive_sync": True}
        out, err = capsys.readouterr()
        assert f"drive_sync: on ({project})" in out
        assert err == ""

    def test_off_through_a_registered_name_writes_false(self, tmp_path, monkeypatch, capsys) -> None:
        monkeypatch.setattr(registry, "REGISTRY_PATH", tmp_path / "project_registry.json")
        project = _store(tmp_path / "proj", {"drive_sync": True})
        registry.register_project("proj", str(project))

        assert _settings(["drive_sync", "off", "@proj"]) == 0

        assert _config(project) == {"drive_sync": False}
        assert "drive_sync: off" in capsys.readouterr().out

    def test_a_store_with_no_config_gets_only_the_key_not_every_default(self, tmp_path) -> None:
        project = _store(tmp_path / "proj")

        assert _settings(["drive_sync", "on", str(project)]) == 0

        assert _config(project) == {"drive_sync": True}

    @pytest.mark.parametrize("argv", [["drive_sync", "maybe", "<p>"], ["drive_sync", "on"], ["drive_sync"]])
    def test_a_malformed_drive_sync_line_is_refused_and_writes_nothing(self, argv, tmp_path, capsys) -> None:
        project = _store(tmp_path / "proj", {"drive_sync": False})
        argv = [str(project) if arg == "<p>" else arg for arg in argv]

        assert _settings(argv) == 2

        assert _config(project) == {"drive_sync": False}
        out, err = capsys.readouterr()
        assert "Usage: settings drive_sync on|off <project_path|@name>" in err
        assert "drive_sync: " not in out

    def test_a_project_without_a_store_is_refused_and_no_store_is_created(self, tmp_path, capsys) -> None:
        project = tmp_path / "bare"
        project.mkdir()

        assert _settings(["drive_sync", "on", str(project)]) == 2

        assert not (project / ".backup").exists()
        assert "No backup store" in capsys.readouterr().err

    def test_a_trailing_help_flag_explains_and_writes_nothing(self, tmp_path, capsys) -> None:
        project = _store(tmp_path / "proj", {"drive_sync": False})

        assert settings.handle_command(settings.PRIMARY_COMMAND, ["drive_sync", "on", str(project), "--help"]) is True

        assert _config(project) == {"drive_sync": False}
        assert "Usage: settings drive_sync on|off" in capsys.readouterr().out

    def test_an_unresolvable_project_is_refused(self, tmp_path, capsys) -> None:
        assert _settings(["drive_sync", "on", str(tmp_path / "missing")]) == 2

        assert "Cannot resolve project" in capsys.readouterr().err

    def test_any_other_key_still_fails_honestly(self, tmp_path, capsys) -> None:
        project = _store(tmp_path / "proj", {"drive_sync": False})

        assert _settings(["max_versions", "5", str(project)]) == 1

        assert _config(project) == {"drive_sync": False}
        assert "settings failed" in capsys.readouterr().err


# =============================================
