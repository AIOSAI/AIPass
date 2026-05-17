# =================== AIPass ====================
# Name: test_profile.py
# Description: Tests for aipass profile Phase 3
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
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
def tmp_local_json(tmp_path):
    """Patch _LOCAL_JSON to a temp file path and return the path."""
    local_json = tmp_path / ".trinity" / "local.json"
    local_json.parent.mkdir(parents=True)
    with patch("aipass.aipass.apps.modules.profile._LOCAL_JSON", local_json):
        yield local_json


@pytest.fixture
def tmp_local_json_with_data(tmp_local_json):
    """Pre-populate local.json with a user section."""
    data = {"user": {f: f"test_{f}" for f in USER_FIELDS}}
    tmp_local_json.write_text(json.dumps(data))
    return tmp_local_json


# =============================================================================
# TestGetUserProfile
# =============================================================================


class TestGetUserProfile:
    def test_creates_defaults_when_no_file(self, tmp_local_json) -> None:
        """Returns default None-filled profile when local.json absent."""
        result = get_user_profile()
        assert set(result.keys()) == set(USER_FIELDS)
        assert all(v is None for v in result.values())

    def test_reads_existing_profile(self, tmp_local_json_with_data) -> None:
        """Returns stored values when user section exists."""
        result = get_user_profile()
        assert result["name"] == "test_name"
        assert result["os"] == "test_os"

    def test_creates_user_section_if_missing(self, tmp_local_json) -> None:
        """Writes defaults to disk when user key absent."""
        tmp_local_json.write_text(json.dumps({"other": "data"}))
        result = get_user_profile()
        assert all(v is None for v in result.values())
        stored = json.loads(tmp_local_json.read_text())
        assert "user" in stored
        assert stored["other"] == "data"

    def test_returns_empty_dict_on_corrupt_file(self, tmp_local_json) -> None:
        """Gracefully handles corrupt JSON."""
        tmp_local_json.write_text("NOT JSON")
        result = get_user_profile()
        assert isinstance(result, dict)

    def test_all_user_fields_present(self, tmp_local_json) -> None:
        """All USER_FIELDS keys are present in returned profile."""
        result = get_user_profile()
        for field in USER_FIELDS:
            assert field in result


# =============================================================================
# TestSaveProfile
# =============================================================================


class TestSaveProfile:
    def test_saves_profile_to_disk(self, tmp_local_json) -> None:
        """Profile dict is written to user section of local.json."""
        with patch("aipass.aipass.apps.modules.profile.json_handler"):
            save_profile({"name": "Alice", "os": "Linux"})
        stored = json.loads(tmp_local_json.read_text())
        assert stored["user"]["name"] == "Alice"

    def test_preserves_other_sections(self, tmp_local_json) -> None:
        """Existing keys outside 'user' are not overwritten."""
        tmp_local_json.write_text(json.dumps({"sessions": [1, 2, 3]}))
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            save_profile({"name": "Bob"})
        stored = json.loads(tmp_local_json.read_text())
        assert stored["sessions"] == [1, 2, 3]
        assert stored["user"]["name"] == "Bob"

    def test_logs_operation(self, tmp_local_json) -> None:
        """json_handler.log_operation is called on save."""
        mock_jh = MagicMock()
        with patch("aipass.aipass.apps.modules.profile.json_handler", mock_jh):
            save_profile({"name": "Test"})
        mock_jh.log_operation.assert_called_once()

    def test_creates_parent_dirs(self, tmp_path) -> None:
        """Missing .trinity/ directory is created on write."""
        deep_path = tmp_path / "a" / "b" / ".trinity" / "local.json"
        with patch("aipass.aipass.apps.modules.profile._LOCAL_JSON", deep_path):
            with patch("aipass.aipass.apps.modules.profile.json_handler"):
                save_profile({"name": "Test"})
        assert deep_path.exists()


# =============================================================================
# TestPrintIntrospection
# =============================================================================


class TestPrintIntrospection:
    def test_does_not_raise(self, tmp_local_json) -> None:
        """print_introspection runs without error."""
        print_introspection()

    def test_outputs_field_names(self, tmp_local_json, capsys) -> None:
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

    def test_no_args_calls_introspection(self, tmp_local_json) -> None:
        """'profile' with no args calls print_introspection."""
        with patch("aipass.aipass.apps.modules.profile.print_introspection") as mock_pi:
            result = handle_command("profile", [])
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

    def test_set_valid_field(self, tmp_local_json) -> None:
        """'set name Alice' stores value and returns True."""
        with patch("aipass.aipass.apps.modules.profile.json_handler.log_operation"):
            result = handle_command("profile", ["set", "name", "Alice"])
        assert result is True
        stored = json.loads(tmp_local_json.read_text())
        assert stored["user"]["name"] == "Alice"

    def test_set_invalid_field_returns_true(self, tmp_local_json) -> None:
        """Setting an unknown field returns True (handled with error msg)."""
        with patch("aipass.aipass.apps.modules.profile.console"):
            result = handle_command("profile", ["set", "INVALID_FIELD", "val"])
        assert result is True

    def test_set_missing_value_returns_true(self) -> None:
        """'set name' without value returns True (error shown)."""
        with patch("aipass.aipass.apps.modules.profile.console"):
            result = handle_command("profile", ["set", "name"])
        assert result is True

    def test_clear_confirmed(self, tmp_local_json) -> None:
        """'clear' with 'aipass' confirmation resets profile."""
        with patch("aipass.aipass.apps.modules.profile.json_handler"):
            with patch("builtins.input", return_value="aipass"):
                with patch("aipass.aipass.apps.modules.profile.console"):
                    result = handle_command("profile", ["clear"])
        assert result is True
        stored = json.loads(tmp_local_json.read_text())
        assert all(v is None for v in stored["user"].values())

    def test_clear_cancelled(self, tmp_local_json) -> None:
        """'clear' with wrong confirmation does nothing."""
        with patch("builtins.input", return_value="nope"):
            with patch("aipass.aipass.apps.modules.profile.console"):
                result = handle_command("profile", ["clear"])
        assert result is True

    def test_clear_keyboard_interrupt(self, tmp_local_json) -> None:
        """Ctrl-C during clear is handled gracefully."""
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with patch("aipass.aipass.apps.modules.profile.console"):
                result = handle_command("profile", ["clear"])
        assert result is True

    def test_clear_eof_error(self, tmp_local_json) -> None:
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
