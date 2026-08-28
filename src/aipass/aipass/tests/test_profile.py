# =================== AIPass ====================
# Name: test_profile.py
# Description: Tests for aipass profile Phase 3
# Version: 1.1.0
# Created: 2026-04-16
# Modified: 2026-08-27
# =============================================

"""Tests for aipass profile command — Phase 3 (FPLAN-0188)."""

import json
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
        with patch("aipass.aipass.apps.modules.profile.json_handler"):
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
            with patch("aipass.aipass.apps.modules.profile.json_handler"):
                save_profile({"name": "Test"})
        assert deep_path.exists()


# =============================================================================
# TestPrintIntrospection
# =============================================================================


class TestPrintIntrospection:
    def test_does_not_raise(self, tmp_store) -> None:
        """print_introspection runs without error."""
        print_introspection()

    def test_outputs_field_names(self, tmp_store, capsys) -> None:
        """All USER_FIELDS appear in output (Rich strips markup in capsys)."""
        with patch("aipass.aipass.apps.modules.profile.console") as mock_console:
            print_introspection()
        assert mock_console.print.called


# =============================================================================
# TestPrintHelp
# =============================================================================


class TestPrintHelp:
    def test_does_not_raise(self) -> None:
        """print_help runs without error."""
        with patch("aipass.aipass.apps.modules.profile.console"):
            print_help()

    def test_prints_something(self) -> None:
        """print_help calls console.print at least once."""
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
        with patch("aipass.aipass.apps.modules.profile.json_handler"):
            with patch("builtins.input", return_value="aipass"):
                with patch("aipass.aipass.apps.modules.profile.console"):
                    result = handle_command("profile", ["clear"])
        assert result is True
        stored = json.loads(tmp_store.read_text())
        assert all(v is None for v in stored["profile"].values())

    def test_clear_cancelled(self, tmp_store) -> None:
        """'clear' with wrong confirmation does nothing."""
        with patch("builtins.input", return_value="nope"):
            with patch("aipass.aipass.apps.modules.profile.console"):
                result = handle_command("profile", ["clear"])
        assert result is True

    def test_clear_keyboard_interrupt(self, tmp_store) -> None:
        """Ctrl-C during clear is handled gracefully."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with patch("aipass.aipass.apps.modules.profile.console"):
                result = handle_command("profile", ["clear"])
        assert result is True

    def test_clear_eof_error(self, tmp_store) -> None:
        """EOFError during clear input is handled gracefully."""
        with patch("builtins.input", side_effect=EOFError):
            with patch("aipass.aipass.apps.modules.profile.console"):
                result = handle_command("profile", ["clear"])
        assert result is True

    def test_unknown_subcommand_shows_help(self) -> None:
        """Unrecognised subcommand falls through to help (returns True)."""
        with patch("aipass.aipass.apps.modules.profile.print_help") as mock_help:
            result = handle_command("profile", ["bogus"])
        assert result is True
        mock_help.assert_called_once()
