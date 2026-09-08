# =================== AIPass ====================
# Name: test_profile.py
# Description: Tests for aipass profile Phase 3
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-08-27
# =============================================

"""Tests for aipass profile command — Phase 3 (FPLAN-0188)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.aipass.apps.modules.profile import (
    USER_FIELDS,
    get_user_profile,
    handle_command,
    print_help,
    print_introspection,
    save_profile,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tmp_store(tmp_path):
    """Patch BOTH profile paths into tmp_path and yield the store path.

    The legacy path is patched too, not just the store: an unpatched
    _LEGACY_LOCAL_JSON still points at the real .trinity/local.json, so a
    defaults test would read the live profile and pass for the wrong reason.
    """
    store = tmp_path / "aipass_json" / "user_profile.json"
    store.parent.mkdir(parents=True)
    legacy = tmp_path / ".trinity" / "local.json"
    legacy.parent.mkdir(parents=True)
    with patch("aipass.aipass.apps.modules.profile._PROFILE_JSON", store):
        with patch("aipass.aipass.apps.modules.profile._LEGACY_LOCAL_JSON", legacy):
            yield store


@pytest.fixture
def tmp_legacy(tmp_store):
    """Return the patched legacy local.json path alongside the store."""
    from aipass.aipass.apps.modules import profile as profile_mod

    return profile_mod._LEGACY_LOCAL_JSON


@pytest.fixture
def tmp_store_with_data(tmp_store):
    """Pre-populate the store with a full profile."""
    data = {"profile": {f: f"test_{f}" for f in USER_FIELDS}}
    tmp_store.write_text(json.dumps(data))
    return tmp_store


# =============================================================================
# TestLiveStoreIsolation
# =============================================================================


class TestLiveStoreIsolation:
    """The suite must never write the branch's real profile store."""

    def test_store_path_is_not_the_live_branch_file(self) -> None:
        """conftest's autouse guard has redirected both profile paths."""
        from aipass.aipass.apps.modules import profile as profile_mod

        live_store = profile_mod._BRANCH_ROOT / "aipass_json" / "user_profile.json"
        live_legacy = profile_mod._BRANCH_ROOT / ".trinity" / "local.json"
        assert profile_mod._PROFILE_JSON != live_store
        assert profile_mod._LEGACY_LOCAL_JSON != live_legacy

    def test_unmocked_save_lands_in_the_temp_store(self, isolate_profile_store) -> None:
        """A save with no local patching writes under the guard's temp dir."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "IsolationProbe"})
        written = isolate_profile_store / "user_profile.json"
        assert json.loads(written.read_text())["profile"]["name"] == "IsolationProbe"


# =============================================================================
# TestGetUserProfile
# =============================================================================


class TestWriteDurability:
    """The two behaviours the hand-rolled writer carried, kept after the refactor.

    Both tests force a REAL failure inside json_handler.write_json (its retried
    replace raises) rather than stubbing write_json to False -- stubbing the
    handler would measure only this module's signalling and would pass even if
    the underlying save stopped being atomic.
    """

    @staticmethod
    def _fail_the_replace():
        """Patch the handler's replace step to raise, as a full disk would."""
        return patch(
            "aipass.prax.apps.handlers.json.json_service._replace_with_retry",
            side_effect=OSError("no space left on device"),
        )

    def test_oserror_mid_write_leaves_the_store_byte_intact(self, tmp_store) -> None:
        """A failed save must not half-write or truncate the previous profile."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Original", "os": "Linux"})
        before = tmp_store.read_bytes()

        with self._fail_the_replace():
            with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                with pytest.raises(OSError):
                    save_profile({"name": "Replacement", "os": "Windows"})

        assert tmp_store.read_bytes() == before
        assert get_user_profile()["name"] == "Original"

    def test_failed_write_leaves_no_temp_file_behind(self, tmp_store) -> None:
        """The handler unlinks its own temp file on the failure path."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Original"})

        with self._fail_the_replace():
            with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                with pytest.raises(OSError):
                    save_profile({"name": "Replacement"})

        leftovers = [p.name for p in tmp_store.parent.iterdir() if p.name != tmp_store.name]
        assert leftovers == []

    def test_write_failure_raises_instead_of_answering_false(self, tmp_store) -> None:
        """json_handler answers False; save_profile must not pass that off as success."""
        with self._fail_the_replace():
            with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                with pytest.raises(OSError):
                    save_profile({"name": "Doomed"})

    def test_trigger_fires_on_write_failure(self, tmp_store) -> None:
        """The write-failure event fires under its true name, with the payload kept.

        Renamed from ``file_deleted`` on 2026-09-07: the event fires on a failed
        write, never on a deletion. @trigger delivers the old name as a
        deprecated alias for one release, so this asserts the NEW name -- the
        alias is trigger's contract to keep, not a second name for this module
        to emit.
        """
        with patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger:
            with self._fail_the_replace():
                with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                    with pytest.raises(OSError):
                        save_profile({"name": "Doomed"})

        mock_trigger.fire.assert_called_once()
        event, kwargs = mock_trigger.fire.call_args[0][0], mock_trigger.fire.call_args[1]
        assert event == "profile_write_failed"
        assert event != "file_deleted"
        assert kwargs["reason"] == "write_failure_cleanup"
        assert kwargs["path"] == str(tmp_store)

    def test_successful_save_fires_nothing(self, tmp_store) -> None:
        """The counterfactual: without it the fire-test could pass on any call."""
        with patch("aipass.trigger.apps.modules.core.trigger") as mock_trigger:
            with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                save_profile({"name": "Fine"})

        mock_trigger.fire.assert_not_called()

    def test_module_does_no_direct_file_operations(self) -> None:
        """The seedgo modules rule, pinned here so it cannot regress silently.

        Line 81's mkdir was the CI blocker on PR 743; json.dump sat behind it in
        the same writer and would have surfaced as the next failure once the
        mkdir went, because the audit reports only the first violation it finds.
        """
        from aipass.aipass.apps.modules import profile as profile_mod

        source = Path(profile_mod.__file__).read_text(encoding="utf-8")
        body = [line for line in source.splitlines() if line.strip() and not line.strip().startswith("#")]
        for forbidden in (".mkdir(", ".write_text(", ".read_text(", "json.dump(", "json.load("):
            offenders = [line.strip() for line in body if forbidden in line]
            assert offenders == [], f"{forbidden} -> {offenders}"


class TestRoundTrip:
    """A save must survive its own log_operation call."""

    def test_save_then_read_round_trips(self, tmp_store) -> None:
        """Real json_handler, no mocks: the store is not clobbered by logging.

        Red before the rename off profile_data.json -- ensure_module_jsons
        regenerated that name as its own managed "data" file and the profile
        came back as {created, last_updated}.
        """
        save_profile({f: f"kept_{f}" for f in USER_FIELDS})
        assert get_user_profile()["name"] == "kept_name"
        assert json.loads(tmp_store.read_text())["profile"]["os"] == "kept_os"

    def test_store_name_is_outside_the_managed_triplet(self) -> None:
        """The filename must not collide with <module>_{config,data,log}.json."""
        from aipass.aipass.apps.modules import profile as profile_mod

        assert profile_mod._PROFILE_FILENAME not in (
            "profile_config.json",
            "profile_data.json",
            "profile_log.json",
        )


class TestGetUserProfile:
    def test_creates_defaults_when_no_file(self, tmp_store) -> None:
        """Returns default None-filled profile when local.json absent."""
        result = get_user_profile()
        assert set(result.keys()) == set(USER_FIELDS)
        assert all(v is None for v in result.values())

    def test_reads_existing_profile(self, tmp_store_with_data) -> None:
        """Returns stored values when user section exists."""
        result = get_user_profile()
        assert result["name"] == "test_name"
        assert result["os"] == "test_os"

    def test_creates_profile_section_if_missing(self, tmp_store) -> None:
        """Writes defaults to disk when the profile key is absent."""
        tmp_store.write_text(json.dumps({"other": "data"}))
        result = get_user_profile()
        assert all(v is None for v in result.values())
        stored = json.loads(tmp_store.read_text())
        assert "profile" in stored

    def test_adopts_legacy_user_section(self, tmp_store, tmp_legacy) -> None:
        """A pre-1.1.0 local.json "user" section is read when the store is absent."""
        tmp_legacy.write_text(json.dumps({"sessions": [], "user": {"name": "Bob", "os": "Linux"}}))
        result = get_user_profile()
        assert result["name"] == "Bob"
        assert result["os"] == "Linux"
        assert result["shell"] is None
        assert json.loads(tmp_store.read_text())["profile"]["name"] == "Bob"

    def test_legacy_local_json_is_never_written(self, tmp_store, tmp_legacy) -> None:
        """Reading and saving leave local.json byte-identical -- .trinity is not ours."""
        original = json.dumps({"sessions": [1, 2, 3], "user": {"name": "Bob"}})
        tmp_legacy.write_text(original)
        get_user_profile()
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Changed"})
        assert tmp_legacy.read_text() == original

    def test_store_wins_over_legacy(self, tmp_store, tmp_legacy) -> None:
        """Once the store exists the legacy section is ignored, not merged."""
        tmp_store.write_text(json.dumps({"profile": {"name": "Store"}}))
        tmp_legacy.write_text(json.dumps({"user": {"name": "Legacy"}}))
        assert get_user_profile()["name"] == "Store"

    def test_returns_empty_dict_on_corrupt_file(self, tmp_store) -> None:
        """Gracefully handles corrupt JSON."""
        tmp_store.write_text("NOT JSON")
        result = get_user_profile()
        assert isinstance(result, dict)

    def test_all_user_fields_present(self, tmp_store) -> None:
        """All USER_FIELDS keys are present in returned profile."""
        result = get_user_profile()
        for field in USER_FIELDS:
            assert field in result


# =============================================================================
# TestSaveProfile
# =============================================================================


class TestSaveProfile:
    def test_saves_profile_to_disk(self, tmp_store) -> None:
        """Profile dict is written to user section of local.json."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "user", "os": "Linux"})
        stored = json.loads(tmp_store.read_text())
        assert stored["profile"]["name"] == "user"

    def test_save_replaces_whole_profile(self, tmp_store) -> None:
        """The store holds only the profile -- a save is a full replace."""
        tmp_store.write_text(json.dumps({"profile": {"name": "Old", "os": "Linux"}}))
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Bob"})
        stored = json.loads(tmp_store.read_text())
        assert stored["profile"] == {"name": "Bob"}

    def test_logs_operation(self, tmp_store) -> None:
        """json_handler.log_operation is called on save."""
        mock_jh = MagicMock()
        with patch("aipass.aipass.apps.modules.profile.json_handler", mock_jh):
            save_profile({"name": "Test"})
        mock_jh.log_operation.assert_called_once()

    def test_creates_parent_dirs(self, tmp_path) -> None:
        """Missing aipass_json/ directory is created on write."""
        deep_path = tmp_path / "a" / "b" / "aipass_json" / "user_profile.json"
        with patch("aipass.aipass.apps.modules.profile._PROFILE_JSON", deep_path):
            with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
                save_profile({"name": "Test"})
        assert deep_path.exists()


# =============================================================================
# TestPrintIntrospection
# =============================================================================


class TestPrintIntrospection:
    def test_does_not_raise(self, tmp_store) -> None:
        """print_introspection renders through the REAL console without raising.

        KEPT, not merged, on 2026-09-07 (DPLAN-0323 contested band). It was
        proposed as redundant against test_outputs_field_names below, and it is
        not: that sibling PATCHES the console, so Rich never renders and a
        malformed markup tag reaches nothing. This test does not patch, so it is
        the only place real Rich rendering of this function is exercised.

        Mutation-proved before the ruling: closing the tag as
        `[bold cyan]aipass profile[/nonexistent_style_mutation]` fails THIS test
        and leaves the sibling green. Merging would have deleted the only
        coverage of a whole class of defect.
        """
        print_introspection()

    def test_outputs_field_names(self, tmp_store, capsys) -> None:
        """print_introspection reaches console.print.

        Docstring corrected 2026-09-07: it claimed all USER_FIELDS appear in the
        output, which this never checked -- the console is a MagicMock here, so
        nothing is rendered to check. Named for what it actually pins.
        """
        with patch("aipass.aipass.apps.modules.profile.console") as mock_console:
            print_introspection()
        assert mock_console.print.called


# =============================================================================
# TestPrintHelp
# =============================================================================


class TestPrintHelp:
    def test_prints_something(self) -> None:
        """print_help calls console.print at least once.

        Absorbed the sibling `test_does_not_raise` on 2026-09-07 (DPLAN-0323
        contested band, MERGE). Mutation-checked: making print_help raise killed
        both tests identically -- same console patch, same call -- so this one
        subsumed it.
        """
        with patch("aipass.aipass.apps.modules.profile.console") as mock_console:
            print_help()
        assert mock_console.print.called


# =============================================================================
# TestHandleCommand
# =============================================================================


class TestHandleCommand:
    def test_wrong_command_returns_false(self) -> None:
        """Non-profile commands are not handled."""
        assert handle_command("doctor", []) is False
        assert handle_command("init", ["run"]) is False

    def test_no_args_calls_introspection(self, tmp_store) -> None:
        """'profile' with no args shows the profile (runs the command)."""
        with patch("aipass.aipass.apps.modules.profile.print_introspection") as mock_pi:
            result = handle_command("profile", [])
        assert result is True
        mock_pi.assert_called_once()

    def test_info_flag_calls_introspection(self, tmp_store) -> None:
        """--info flag calls print_introspection."""
        with patch("aipass.aipass.apps.modules.profile.print_introspection") as mock_pi:
            result = handle_command("profile", ["--info"])
        assert result is True
        mock_pi.assert_called_once()

    def test_help_flag_returns_true(self) -> None:
        """--help flag is handled."""
        with patch("aipass.aipass.apps.modules.profile.print_help"):
            assert handle_command("profile", ["--help"]) is True

    def test_h_flag_returns_true(self) -> None:
        """-h flag is handled."""
        with patch("aipass.aipass.apps.modules.profile.print_help"):
            assert handle_command("profile", ["-h"]) is True

    def test_help_word_returns_true(self) -> None:
        """'help' subcommand is handled."""
        with patch("aipass.aipass.apps.modules.profile.print_help"):
            assert handle_command("profile", ["help"]) is True

    def test_set_valid_field(self, tmp_store) -> None:
        """'set name user' stores value and returns True."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            result = handle_command("profile", ["set", "name", "user"])
        assert result is True
        stored = json.loads(tmp_store.read_text())
        assert stored["profile"]["name"] == "user"

    def test_set_invalid_field_returns_true(self, tmp_store) -> None:
        """Setting an unknown field returns True (handled with error msg)."""
        with patch("aipass.aipass.apps.modules.profile.console"):
            result = handle_command("profile", ["set", "INVALID_FIELD", "val"])
        assert result is True

    def test_set_missing_value_returns_true(self) -> None:
        """'set name' without value returns True (error shown)."""
        with patch("aipass.aipass.apps.modules.profile.console"):
            result = handle_command("profile", ["set", "name"])
        assert result is True

    def test_clear_confirmed(self, tmp_store) -> None:
        """'clear' with 'aipass' confirmation resets profile."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            with patch("builtins.input", return_value="aipass"):
                with patch("aipass.aipass.apps.modules.profile.console"):
                    result = handle_command("profile", ["clear"])
        assert result is True
        stored = json.loads(tmp_store.read_text())
        assert all(v is None for v in stored["profile"].values())

    def test_clear_cancelled(self, tmp_store) -> None:
        """A wrong confirmation clears nothing, so it must not exit 0.

        Rewritten 2026-09-07 (FPLAN-0492 wave 6). This asserted `result is True`
        -- the assertion that PINNED the defect: the user asked for a clear, the
        clear did not happen, and the command reported success anyway.
        """
        before = tmp_store.read_text() if tmp_store.exists() else None
        with patch("builtins.input", return_value="nope"):
            with patch("aipass.aipass.apps.modules.profile.console"):
                with pytest.raises(SystemExit) as exc:
                    handle_command("profile", ["clear"])

        assert exc.value.code == 1
        assert (tmp_store.read_text() if tmp_store.exists() else None) == before

    def test_clear_keyboard_interrupt(self, tmp_store) -> None:
        """Ctrl-C during clear leaves the profile intact and refuses non-zero."""
        before = tmp_store.read_text() if tmp_store.exists() else None
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with patch("aipass.aipass.apps.modules.profile.console"):
                with pytest.raises(SystemExit) as exc:
                    handle_command("profile", ["clear"])

        assert exc.value.code == 1
        assert (tmp_store.read_text() if tmp_store.exists() else None) == before

    def test_clear_eof_error(self, tmp_store) -> None:
        """A PIPED clear has no stdin to confirm on: refuse, never report success.

        This is the row canary's sweep named directly -- `aipass profile clear`
        in a pipe hit EOFError, printed Cancelled and exited 0 while the profile
        sat untouched, so a script could not tell a clear from a no-op.
        """
        before = tmp_store.read_text() if tmp_store.exists() else None
        with patch("builtins.input", side_effect=EOFError):
            with patch("aipass.aipass.apps.modules.profile.console"):
                with pytest.raises(SystemExit) as exc:
                    handle_command("profile", ["clear"])

        assert exc.value.code == 1
        assert (tmp_store.read_text() if tmp_store.exists() else None) == before

    def test_clear_confirmed_still_exits_zero(self, tmp_store) -> None:
        """The counterfactual: the real clear path must NOT have become a refusal."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            with patch("builtins.input", return_value="aipass"):
                with patch("aipass.aipass.apps.modules.profile.console"):
                    assert handle_command("profile", ["clear"]) is True

    def test_unknown_subcommand_shows_help(self) -> None:
        """Unrecognised subcommand falls through to help (returns True)."""
        with patch("aipass.aipass.apps.modules.profile.print_help") as mock_help:
            result = handle_command("profile", ["bogus"])
        assert result is True
        mock_help.assert_called_once()
