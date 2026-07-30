"""
Multi-Bot Architecture Test Suite

Covers:
- Multi-bot config functions (config.py): load_bot_config, list_bot_configs, validate_bot_config
- Telegram standards (telegram_standards.py): parse_command, handle_standard_command, text builders
- Bot operations (bot_operations.py): parse_create_args, format_bot_details, format_bot_table
"""

from unittest.mock import patch, MagicMock

import pytest

# Modules under test
from aipass.skills.lib.telegram.apps.handlers import config as tg_config
from aipass.skills.lib.telegram.apps.handlers.telegram_standards import (
    STANDARD_COMMANDS,
    PROCESSING_MSG,
    parse_command,
    handle_standard_command,
    build_help_text,
    build_welcome_text,
    build_status_text,
    build_botfather_commands,
)
from aipass.skills.lib.telegram.apps.handlers import bot_operations


# =============================================
# FIXTURES
# =============================================


@pytest.fixture
def valid_bot_config() -> dict:
    """A valid multi-bot config dict."""
    return {
        "bot_id": "dev_central",
        "bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        "bot_name": "AIPass Dev Central Bot",
        "branch_name": "dev_central",
        "work_dir": "/home/aipass/aipass_os/dev_central",
        "allowed_user_ids": [7235222625],
    }


@pytest.fixture
def sample_bots() -> list[dict]:
    """Sample bot registry entries for format tests."""
    return [
        {
            "bot_id": "dev_central",
            "username": "aipass_dev_bot",
            "branch_name": "dev_central",
            "work_dir": "/home/aipass/aipass_os/dev_central",
            "status": "active",
            "service_name": "telegram-bot@dev_central",
        },
        {
            "bot_id": "assistant",
            "username": "aipass_assistant_bot",
            "branch_name": None,
            "work_dir": "/home/aipass",
            "status": "stopped",
            "service_name": "telegram-bot@assistant",
        },
    ]


# =============================================
# 1. CONFIG: load_bot_config
# =============================================


class TestLoadBotConfig:
    """Tests for config.load_bot_config (via _get_secret)."""

    @patch("aipass.skills.lib.telegram.apps.handlers.config._get_secret")
    def test_load_valid_config(self, mock_get_secret: MagicMock, valid_bot_config: dict) -> None:
        """Valid config returned from _get_secret loads correctly."""
        mock_get_secret.return_value = valid_bot_config

        result = tg_config.load_bot_config("dev_central")
        assert result is not None
        assert isinstance(result, dict)
        assert result["bot_id"] == "dev_central"
        assert result["bot_token"] == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        assert result["branch_name"] == "dev_central"
        mock_get_secret.assert_called_once_with("dev_central")

    @patch("aipass.skills.lib.telegram.apps.handlers.config._get_secret")
    def test_load_missing_file(self, mock_get_secret: MagicMock) -> None:
        """Returns None when secret not found."""
        mock_get_secret.return_value = None

        result = tg_config.load_bot_config("nonexistent_bot")
        assert result is None
        mock_get_secret.assert_called_once_with("nonexistent_bot")

    @patch("aipass.skills.lib.telegram.apps.handlers.config._get_secret")
    def test_load_corrupt_json(self, mock_get_secret: MagicMock) -> None:
        """Returns None when _get_secret returns None (e.g., invalid JSON from subprocess)."""
        mock_get_secret.return_value = None

        result = tg_config.load_bot_config("broken")
        assert result is None

    @patch("aipass.skills.lib.telegram.apps.handlers.config._get_secret")
    def test_load_non_dict_json(self, mock_get_secret: MagicMock) -> None:
        """Returns None when _get_secret returns None (non-dict JSON is filtered by _get_secret)."""
        # _get_secret already filters non-dict responses and returns None
        mock_get_secret.return_value = None

        result = tg_config.load_bot_config("array_bot")
        assert result is None


# =============================================
# 2. CONFIG: list_bot_configs
# =============================================


class TestListBotConfigs:
    """Tests for config.list_bot_configs (via in-process secrets API)."""

    @patch("aipass.skills.lib.telegram.apps.handlers.config._api_list_secrets")
    def test_list_returns_bot_ids(self, mock_list: MagicMock) -> None:
        """Returns list of bot_ids from the secrets API."""
        mock_list.return_value = ["dev_central", "assistant", "scheduler"]

        result = tg_config.list_bot_configs()
        assert isinstance(result, list)
        assert "dev_central" in result
        assert "assistant" in result
        assert "scheduler" in result
        assert len(result) == 3
        mock_list.assert_called_once_with("telegram")

    @patch("aipass.skills.lib.telegram.apps.handlers.config._api_list_secrets")
    def test_list_returns_empty_on_failure(self, mock_list: MagicMock) -> None:
        """Returns empty list when the secrets API raises."""
        mock_list.side_effect = RuntimeError("connection failed")

        result = tg_config.list_bot_configs()
        assert result == []

    @patch("aipass.skills.lib.telegram.apps.handlers.config._api_list_secrets")
    def test_list_returns_empty_when_no_secrets(self, mock_list: MagicMock) -> None:
        """Returns empty list when no secrets exist."""
        mock_list.return_value = []

        result = tg_config.list_bot_configs()
        assert result == []

    @patch("aipass.skills.lib.telegram.apps.handlers.config._api_list_secrets")
    def test_list_returns_empty_on_unexpected_error(self, mock_list: MagicMock) -> None:
        """Returns empty list on unexpected exception."""
        mock_list.side_effect = OSError("disk error")

        result = tg_config.list_bot_configs()
        assert result == []


# =============================================
# 3. CONFIG: validate_bot_config
# =============================================


class TestValidateBotConfig:
    """Tests for config.validate_bot_config."""

    def test_valid_config(self, valid_bot_config: dict) -> None:
        """Accepts a complete, valid config."""
        valid, error = tg_config.validate_bot_config(valid_bot_config)
        assert valid is True
        assert error == ""

    def test_minimal_valid_config(self) -> None:
        """Accepts config with only required fields."""
        config = {"bot_id": "test", "bot_token": "123:abc"}
        valid, error = tg_config.validate_bot_config(config)
        assert valid is True
        assert error == ""

    def test_rejects_missing_bot_id(self) -> None:
        """Rejects config without bot_id."""
        config = {"bot_token": "123:abc"}
        valid, error = tg_config.validate_bot_config(config)
        assert valid is False
        assert "bot_id" in error

    def test_rejects_missing_bot_token(self) -> None:
        """Rejects config without bot_token."""
        config = {"bot_id": "test"}
        valid, error = tg_config.validate_bot_config(config)
        assert valid is False
        assert "bot_token" in error

    def test_rejects_non_dict(self) -> None:
        """Rejects non-dict input (list, string, None, etc.)."""
        for bad_input in [["a", "list"], "a string", None, 42, True]:
            valid, error = tg_config.validate_bot_config(bad_input)
            assert valid is False
            assert "dict" in error

    def test_rejects_token_without_colon(self) -> None:
        """Rejects bot_token that does not contain a colon."""
        config = {"bot_id": "test", "bot_token": "no_colon_here"}
        valid, error = tg_config.validate_bot_config(config)
        assert valid is False
        assert "bot_token" in error
        assert "id:hash" in error

    def test_rejects_empty_bot_id(self) -> None:
        """Rejects config where bot_id is empty string."""
        config = {"bot_id": "", "bot_token": "123:abc"}
        valid, error = tg_config.validate_bot_config(config)
        assert valid is False
        assert "bot_id" in error

    def test_rejects_relative_work_dir(self) -> None:
        """Rejects config with a relative work_dir path."""
        config = {
            "bot_id": "test",
            "bot_token": "123:abc",
            "work_dir": "relative/path",
        }
        valid, error = tg_config.validate_bot_config(config)
        assert valid is False
        assert "work_dir" in error

    def test_accepts_null_work_dir(self) -> None:
        """Accepts config where work_dir is explicitly None."""
        config = {"bot_id": "test", "bot_token": "123:abc", "work_dir": None}
        valid, error = tg_config.validate_bot_config(config)
        assert valid is True
        assert error == ""

    def test_rejects_non_list_allowed_user_ids(self) -> None:
        """Rejects config where allowed_user_ids is not a list."""
        config = {
            "bot_id": "test",
            "bot_token": "123:abc",
            "allowed_user_ids": "not_a_list",
        }
        valid, error = tg_config.validate_bot_config(config)
        assert valid is False
        assert "allowed_user_ids" in error


# =============================================
# 4. TELEGRAM STANDARDS: parse_command
# =============================================


class TestParseCommand:
    """Tests for telegram_standards.parse_command."""

    def test_simple_command(self) -> None:
        """Parses /command into (command, '')."""
        result = parse_command("/status")
        assert result is not None
        assert result == ("status", "")

    def test_command_with_bot_mention(self) -> None:
        """Parses /command@botname, stripping the bot mention."""
        result = parse_command("/help@aipass_bridge_bot")
        assert result is not None
        assert result == ("help", "")

    def test_non_command_returns_none(self) -> None:
        """Returns None for text that does not start with /."""
        assert parse_command("hello world") is None
        assert parse_command("") is None
        assert parse_command("not a /command") is None

    def test_command_with_args(self) -> None:
        """Parses /command args into (command, args)."""
        result = parse_command("/new please")
        assert result is not None
        assert result == ("new", "please")

    def test_command_with_multi_word_args(self) -> None:
        """Parses /command with multiple words in args."""
        result = parse_command("/send hello world how are you")
        assert result is not None
        assert result == ("send", "hello world how are you")

    def test_command_with_botname_and_args(self) -> None:
        """Parses /command@bot args correctly."""
        result = parse_command("/start@mybot welcome")
        assert result is not None
        assert result == ("start", "welcome")

    def test_uppercase_command_lowered(self) -> None:
        """Command names are lowercased."""
        result = parse_command("/STATUS")
        assert result is not None
        assert result[0] == "status"

    def test_empty_command_returns_none(self) -> None:
        """Returns None for bare slash."""
        assert parse_command("/") is None

    def test_none_input_returns_none(self) -> None:
        """Returns None for None input."""
        assert parse_command(None) is None  # type: ignore[arg-type]


# =============================================
# 5. TELEGRAM STANDARDS: handle_standard_command
# =============================================


class TestHandleStandardCommand:
    """Tests for telegram_standards.handle_standard_command."""

    def test_start_returns_welcome_text(self) -> None:
        """The 'start' command returns welcome text string."""
        result = handle_standard_command(
            command="start",
            session_name="telegram-assistant",
            branch_name="assistant",
            bot_name="AIPass Assistant Bot",
        )
        assert isinstance(result, str)
        assert "AIPass Assistant Bot" in result
        assert "@assistant" in result

    def test_help_returns_help_text(self) -> None:
        """The 'help' command returns help text string."""
        result = handle_standard_command(
            command="help",
            session_name="telegram-assistant",
            branch_name="assistant",
            bot_name="AIPass Assistant Bot",
        )
        assert isinstance(result, str)
        assert "Available commands:" in result

    def test_new_returns_tuple(self) -> None:
        """The 'new' command returns tuple of ('new', response_text)."""
        result = handle_standard_command(
            command="new",
            session_name="telegram-assistant",
            branch_name="assistant",
            bot_name="AIPass Assistant Bot",
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == "new"
        assert "@assistant" in result[1]
        assert "fresh" in result[1].lower() or "cleared" in result[1].lower()

    @patch("aipass.skills.lib.telegram.apps.handlers.telegram_standards._tmux_session_exists")
    def test_status_returns_status_text(self, mock_tmux: MagicMock) -> None:
        """The 'status' command returns status text string."""
        mock_tmux.return_value = True

        result = handle_standard_command(
            command="status",
            session_name="telegram-assistant",
            branch_name="assistant",
            bot_name="AIPass Assistant Bot",
            chat_id=12345,
            message_count=42,
            uptime="2h 15m",
        )
        assert isinstance(result, str)
        assert "telegram-assistant" in result
        assert "@assistant" in result
        assert "Active" in result

    def test_unknown_command_returns_none(self) -> None:
        """Unknown commands return None."""
        result = handle_standard_command(
            command="nonexistent",
            session_name="telegram-assistant",
            branch_name="assistant",
            bot_name="AIPass Assistant Bot",
        )
        assert result is None

    def test_start_with_custom_commands(self) -> None:
        """Custom commands appear in the welcome text."""
        custom = {
            "deploy": {
                "description": "Deploy to production",
                "menu_text": "Deploy",
            }
        }
        result = handle_standard_command(
            command="start",
            session_name="telegram-assistant",
            branch_name="assistant",
            bot_name="AIPass Assistant Bot",
            custom_commands=custom,
        )
        assert isinstance(result, str)
        assert "/deploy" in result


# =============================================
# 6. TELEGRAM STANDARDS: build_help_text
# =============================================


class TestBuildHelpText:
    """Tests for telegram_standards.build_help_text."""

    def test_includes_all_standard_commands(self) -> None:
        """Help text includes all standard commands."""
        result = build_help_text()
        assert "Available commands:" in result
        for cmd in STANDARD_COMMANDS:
            assert f"/{cmd}" in result

    def test_includes_custom_commands(self) -> None:
        """Help text includes custom commands when provided."""
        custom = {
            "deploy": {
                "description": "Deploy the app",
                "menu_text": "Deploy",
            }
        }
        result = build_help_text(custom_commands=custom)
        assert "/deploy" in result
        assert "Deploy the app" in result

    def test_includes_footer(self) -> None:
        """Help text includes the help footer."""
        result = build_help_text()
        assert "Just send any message to talk to me" in result


# =============================================
# 7. TELEGRAM STANDARDS: build_welcome_text
# =============================================


class TestBuildWelcomeText:
    """Tests for telegram_standards.build_welcome_text."""

    def test_includes_bot_name(self) -> None:
        """Welcome text includes the bot name."""
        result = build_welcome_text(
            bot_name="AIPass Dev Central Bot",
            branch_name="dev_central",
        )
        assert "AIPass Dev Central Bot" in result

    def test_includes_branch_name(self) -> None:
        """Welcome text includes the branch name with @ prefix."""
        result = build_welcome_text(
            bot_name="AIPass Dev Central Bot",
            branch_name="dev_central",
        )
        assert "@dev_central" in result

    def test_includes_commands(self) -> None:
        """Welcome text includes the command list."""
        result = build_welcome_text(
            bot_name="TestBot",
            branch_name="test",
        )
        assert "Available commands:" in result
        for cmd in STANDARD_COMMANDS:
            assert f"/{cmd}" in result


# =============================================
# 8. TELEGRAM STANDARDS: build_status_text
# =============================================


class TestBuildStatusText:
    """Tests for telegram_standards.build_status_text."""

    @patch("aipass.skills.lib.telegram.apps.handlers.telegram_standards._tmux_session_exists")
    def test_active_session(self, mock_tmux: MagicMock) -> None:
        """Active tmux session shows 'Active' state."""
        mock_tmux.return_value = True
        result = build_status_text(
            session_name="telegram-dev_central",
            branch_name="dev_central",
        )
        assert "Active" in result
        assert "@dev_central" in result
        assert "telegram-dev_central" in result

    @patch("aipass.skills.lib.telegram.apps.handlers.telegram_standards._tmux_session_exists")
    def test_inactive_session(self, mock_tmux: MagicMock) -> None:
        """Inactive tmux session shows 'Inactive' state."""
        mock_tmux.return_value = False
        result = build_status_text(
            session_name="telegram-dev_central",
            branch_name="dev_central",
        )
        assert "Inactive" in result

    @patch("aipass.skills.lib.telegram.apps.handlers.telegram_standards._tmux_session_exists")
    def test_optional_fields_included(self, mock_tmux: MagicMock) -> None:
        """Optional fields (uptime, message_count, chat_id) appear when provided."""
        mock_tmux.return_value = True
        result = build_status_text(
            session_name="telegram-test",
            branch_name="test",
            uptime="3h 42m",
            message_count=99,
            chat_id=12345,
        )
        assert "Uptime: 3h 42m" in result
        assert "Messages: 99" in result
        assert "Chat ID: 12345" in result

    @patch("aipass.skills.lib.telegram.apps.handlers.telegram_standards._tmux_session_exists")
    def test_optional_fields_omitted(self, mock_tmux: MagicMock) -> None:
        """Optional fields are not shown when not provided."""
        mock_tmux.return_value = True
        result = build_status_text(
            session_name="telegram-test",
            branch_name="test",
        )
        assert "Uptime" not in result
        assert "Messages" not in result
        assert "Chat ID" not in result


# =============================================
# 9. TELEGRAM STANDARDS: build_botfather_commands
# =============================================


class TestBuildBotfatherCommands:
    """Tests for telegram_standards.build_botfather_commands."""

    def test_returns_correct_format(self) -> None:
        """Returns list of dicts with 'command' and 'description' keys."""
        result = build_botfather_commands()
        assert isinstance(result, list)
        assert len(result) == len(STANDARD_COMMANDS)

        for entry in result:
            assert "command" in entry
            assert "description" in entry
            assert isinstance(entry["command"], str)
            assert isinstance(entry["description"], str)

    def test_uses_menu_text(self) -> None:
        """Uses menu_text (not description) for BotFather description."""
        result = build_botfather_commands()
        command_map = {e["command"]: e["description"] for e in result}
        for cmd, info in STANDARD_COMMANDS.items():
            assert command_map[cmd] == info["menu_text"]

    def test_includes_custom_commands(self) -> None:
        """Custom commands are appended to the list."""
        custom = {
            "deploy": {
                "description": "Deploy to production",
                "menu_text": "Deploy app",
            }
        }
        result = build_botfather_commands(custom_commands=custom)
        assert len(result) == len(STANDARD_COMMANDS) + 1
        commands = [e["command"] for e in result]
        assert "deploy" in commands

    def test_defaults_to_standard_commands(self) -> None:
        """Defaults to STANDARD_COMMANDS when no args provided."""
        result = build_botfather_commands()
        commands = {e["command"] for e in result}
        assert commands == set(STANDARD_COMMANDS.keys())


# =============================================
# 10. TELEGRAM STANDARDS: PROCESSING_MSG constant
# =============================================


class TestConstants:
    """Tests for telegram_standards constants."""

    def test_processing_msg_value(self) -> None:
        """PROCESSING_MSG has expected value."""
        assert PROCESSING_MSG == "Processing..."

    def test_standard_commands_has_required_keys(self) -> None:
        """STANDARD_COMMANDS has start, help, new, status."""
        assert "start" in STANDARD_COMMANDS
        assert "help" in STANDARD_COMMANDS
        assert "new" in STANDARD_COMMANDS
        assert "status" in STANDARD_COMMANDS


# =============================================
# 11. BOT OPERATIONS: parse_create_args
# =============================================


class TestParseCreateArgs:
    """Tests for bot_operations.parse_create_args."""

    def test_minimum_args(self) -> None:
        """Parses bot_id and token from minimum args."""
        result = bot_operations.parse_create_args(["my_bot", "123:abc"])
        assert result is not None
        assert result["bot_id"] == "my_bot"
        assert result["bot_token"] == "123:abc"
        assert result["branch_name"] is None
        assert result["work_dir"] is None

    def test_with_branch_flag(self) -> None:
        """Parses --branch flag."""
        result = bot_operations.parse_create_args(["my_bot", "123:abc", "--branch", "dev_central"])
        assert result is not None
        assert result["branch_name"] == "dev_central"
        assert result["work_dir"] is None

    def test_with_work_dir_flag(self) -> None:
        """Parses --work-dir flag."""
        result = bot_operations.parse_create_args(["my_bot", "123:abc", "--work-dir", "/home/aipass/projects"])
        assert result is not None
        assert result["work_dir"] == "/home/aipass/projects"
        assert result["branch_name"] is None

    def test_with_both_flags(self) -> None:
        """Parses both --branch and --work-dir flags."""
        result = bot_operations.parse_create_args(
            ["my_bot", "123:abc", "--branch", "dev_central", "--work-dir", "/home/aipass"]
        )
        assert result is not None
        assert result["bot_id"] == "my_bot"
        assert result["bot_token"] == "123:abc"
        assert result["branch_name"] == "dev_central"
        assert result["work_dir"] == "/home/aipass"

    def test_insufficient_args_returns_none(self) -> None:
        """Returns None when fewer than 2 args provided."""
        assert bot_operations.parse_create_args([]) is None
        assert bot_operations.parse_create_args(["only_one"]) is None

    def test_ignores_unknown_flags(self) -> None:
        """Unknown flags are skipped without error."""
        result = bot_operations.parse_create_args(["my_bot", "123:abc", "--unknown", "value"])
        assert result is not None
        assert result["bot_id"] == "my_bot"


# =============================================
# 12. BOT OPERATIONS: format_bot_details
# =============================================


class TestFormatBotDetails:
    """Tests for bot_operations.format_bot_details."""

    def test_returns_expected_lines(self, sample_bots: list[dict]) -> None:
        """Returns list of formatted detail lines."""
        result = bot_operations.format_bot_details(sample_bots[0])
        assert isinstance(result, list)
        assert len(result) == 6

        # Check each line contains expected data
        assert "dev_central" in result[0]  # Bot ID
        assert "@aipass_dev_bot" in result[1]  # Username
        assert "dev_central" in result[2]  # Branch
        assert "/home/aipass" in result[3]  # Work Dir
        assert "active" in result[4]  # Status
        assert "telegram-bot@dev_central" in result[5]  # Service

    def test_no_branch_shows_base_bot(self, sample_bots: list[dict]) -> None:
        """Bot with no branch_name shows 'none (base bot)'."""
        result = bot_operations.format_bot_details(sample_bots[1])
        branch_line = result[2]
        assert "none (base bot)" in branch_line

    def test_missing_fields_show_question_mark(self) -> None:
        """Missing fields default to '?'."""
        result = bot_operations.format_bot_details({})
        assert any("?" in line for line in result)

    def test_service_name_fallback(self) -> None:
        """Missing service_name generates default from bot_id."""
        bot = {"bot_id": "custom_bot"}
        result = bot_operations.format_bot_details(bot)
        service_line = result[5]
        assert "telegram-bot@custom_bot" in service_line


# =============================================
# 13. BOT OPERATIONS: format_bot_table
# =============================================


class TestFormatBotTable:
    """Tests for bot_operations.format_bot_table."""

    def test_table_structure(self, sample_bots: list[dict]) -> None:
        """Returns header + separator + rows + total line."""
        result = bot_operations.format_bot_table(sample_bots)
        assert isinstance(result, list)

        # Header, separator, 2 data rows, total = 5 lines
        assert len(result) == 5

        # First line is header with column names
        assert "Bot ID" in result[0]
        assert "Branch" in result[0]
        assert "Username" in result[0]
        assert "Status" in result[0]

        # Second line is separator
        assert "---" in result[1]

        # Last line is total
        assert "Total: 2 bot(s)" in result[-1]

    def test_table_rows_contain_data(self, sample_bots: list[dict]) -> None:
        """Data rows contain bot information."""
        result = bot_operations.format_bot_table(sample_bots)

        # Row for dev_central bot
        assert "dev_central" in result[2]
        assert "@aipass_dev_bot" in result[2]
        assert "active" in result[2]

        # Row for assistant bot (no branch shows "-")
        assert "assistant" in result[3]
        assert "@aipass_assistant_bot" in result[3]

    def test_empty_table(self) -> None:
        """Empty bot list returns header + separator + total."""
        result = bot_operations.format_bot_table([])
        assert len(result) == 3  # header + separator + total
        assert "Total: 0 bot(s)" in result[-1]

    def test_no_branch_shows_dash(self) -> None:
        """Bot with None branch_name shows '-' in table."""
        bots = [{"bot_id": "base", "branch_name": None, "username": "bot", "status": "active"}]
        result = bot_operations.format_bot_table(bots)
        # The data row (index 2) should have "-" for branch
        data_row = result[2]
        # branch_name=None maps to "-" in the table
        assert "-" in data_row


# =============================================
# 14. BOT OPERATIONS: get_status and get_all_bots
# =============================================


class TestGetStatusAndGetAllBots:
    """Tests for bot_operations.get_status and get_all_bots."""

    @patch("aipass.skills.lib.telegram.apps.handlers.bot_operations.get_bot")
    def test_get_status_specific_bot(self, mock_get_bot: MagicMock) -> None:
        """get_status with bot_id delegates to get_bot."""
        mock_get_bot.return_value = {"bot_id": "dev_central", "status": "active"}

        result = bot_operations.get_status("dev_central")
        assert len(result) == 1
        assert result[0]["bot_id"] == "dev_central"
        mock_get_bot.assert_called_once_with("dev_central")

    @patch("aipass.skills.lib.telegram.apps.handlers.bot_operations.get_bot")
    def test_get_status_bot_not_found(self, mock_get_bot: MagicMock) -> None:
        """get_status returns empty list when bot not found."""
        mock_get_bot.return_value = None

        result = bot_operations.get_status("nonexistent")
        assert result == []

    @patch("aipass.skills.lib.telegram.apps.handlers.bot_operations.list_bots")
    def test_get_status_all_bots(self, mock_list_bots: MagicMock) -> None:
        """get_status with no bot_id delegates to list_bots."""
        mock_list_bots.return_value = [
            {"bot_id": "a", "status": "active"},
            {"bot_id": "b", "status": "stopped"},
        ]

        result = bot_operations.get_status()
        assert len(result) == 2
        mock_list_bots.assert_called_once()

    @patch("aipass.skills.lib.telegram.apps.handlers.bot_operations.list_bots")
    def test_get_all_bots(self, mock_list_bots: MagicMock) -> None:
        """get_all_bots delegates to list_bots."""
        expected = [{"bot_id": "x"}, {"bot_id": "y"}]
        mock_list_bots.return_value = expected

        result = bot_operations.get_all_bots()
        assert result == expected
        mock_list_bots.assert_called_once()


# =============================================
# CREATE_BOT -> LOAD_BOT_CONFIG ROUND-TRIP
# =============================================


class TestCreateBotRoundTrip:
    """Prove GAP1 is closed: create_bot persists config that load_bot_config reads."""

    @patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.start_bot_process", return_value=True)
    @patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.enable_service", return_value=True)
    @patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.set_bot_commands", return_value=True)
    @patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.validate_token")
    @patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.ensure_registry")
    def test_create_then_load_roundtrip(
        self,
        mock_ensure_registry,
        mock_validate_token,
        mock_set_commands,
        mock_enable,
        mock_start,
        tmp_path,
        monkeypatch,
    ):
        """After create_bot, load_bot_config returns the persisted config."""
        from aipass.skills.lib.telegram.apps.handlers import bot_factory, config as tg_config

        mock_validate_token.return_value = {"username": "test_bot", "id": 123}

        monkeypatch.setattr(bot_factory, "_BOT_CONFIG_DIR", tmp_path)

        secrets_store = {}

        def fake_set_secret(provider, slug, value, *, as_json=False):
            secrets_store[f"{provider}/{slug}"] = value
            return tmp_path / f"{slug}.json"

        def fake_get_secret(provider, slug, *, as_json=False):
            return secrets_store.get(f"{provider}/{slug}")

        monkeypatch.setattr(bot_factory, "_api_set_secret", fake_set_secret)
        monkeypatch.setattr(tg_config, "_api_get_secret", fake_get_secret)

        monkeypatch.setattr("aipass.skills.lib.telegram.apps.handlers.bot_registry.REGISTRY_DIR", tmp_path / "state")
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.bot_registry.REGISTRY_FILE",
            tmp_path / "state" / "_registry.json",
        )

        result = bot_factory.create_bot(
            bot_id="roundtrip_bot",
            bot_token="111:AAA-test-token",
            branch_name=None,
            allowed_user_ids=[42],
        )
        assert result is not None
        assert result["bot_id"] == "roundtrip_bot"

        loaded = tg_config.load_bot_config("roundtrip_bot")
        assert loaded is not None
        assert loaded["bot_id"] == "roundtrip_bot"
        assert loaded["bot_token"] == "111:AAA-test-token"
        assert loaded["allowed_user_ids"] == [42]

    @patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.validate_token")
    @patch("aipass.skills.lib.telegram.apps.handlers.bot_factory.ensure_registry")
    def test_create_fails_loud_on_set_secret_error(
        self,
        mock_ensure_registry,
        mock_validate_token,
        tmp_path,
        monkeypatch,
    ):
        """create_bot returns None and logs error if set_secret raises."""
        from aipass.skills.lib.telegram.apps.handlers import bot_factory

        mock_validate_token.return_value = {"username": "test_bot", "id": 123}
        monkeypatch.setattr(bot_factory, "_BOT_CONFIG_DIR", tmp_path)

        def failing_set_secret(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(bot_factory, "_api_set_secret", failing_set_secret)

        result = bot_factory.create_bot(
            bot_id="fail_bot",
            bot_token="222:BBB-test-token",
        )
        assert result is None


# =============================================
# COMMAND MENU SYNC + POPULATE TESTS
# =============================================


class TestCommandMenuSync:
    """Verify /help text and Telegram menu use the same single-source command list."""

    def test_menu_and_help_have_same_commands(self):
        """The command names in build_botfather_commands match those in build_help_text."""
        from aipass.skills.lib.telegram.apps.handlers.telegram_standards import (
            build_botfather_commands,
            build_help_text,
        )
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot
        from unittest.mock import MagicMock

        mock_self = MagicMock(spec=BaseBot)
        mock_self.branch_name = None
        custom = BaseBot.get_custom_commands(mock_self)
        menu_commands = build_botfather_commands(custom_commands=custom)
        menu_names = {c["command"] for c in menu_commands}

        help_text = build_help_text(custom_commands=custom)
        help_names = set()
        for line in help_text.split("\n"):
            if line.startswith("/"):
                cmd = line.split(" ")[0].lstrip("/").split("-")[0].strip()
                help_names.add(cmd)

        assert menu_names == help_names

    def test_help_contains_enriched_descriptions(self):
        """The /help text includes the enriched descriptions."""
        from aipass.skills.lib.telegram.apps.handlers.telegram_standards import build_help_text
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot
        from unittest.mock import MagicMock

        mock_self = MagicMock(spec=BaseBot)
        mock_self.branch_name = None
        custom = BaseBot.get_custom_commands(mock_self)
        help_text = build_help_text(custom_commands=custom)

        assert "what this bot is and how to use it" in help_text.lower()
        assert "show every command" in help_text.lower()
        assert "fresh conversation" in help_text.lower()
        assert "branch, uptime" in help_text.lower()
        assert "create a telegram bot" in help_text.lower()
        assert "cancel an in-progress" in help_text.lower()

    def test_help_footer_updated(self):
        """The /help footer uses the enriched text."""
        from aipass.skills.lib.telegram.apps.handlers.telegram_standards import build_help_text

        help_text = build_help_text()
        assert "Just send any message to talk to me" in help_text

    def test_create_bot_uses_single_source(self):
        """create_bot calls set_bot_commands with build_botfather_commands output."""
        from aipass.skills.lib.telegram.apps.handlers import bot_factory
        from aipass.skills.lib.telegram.apps.handlers.telegram_standards import build_botfather_commands

        expected = build_botfather_commands()
        with patch.object(bot_factory, "set_bot_commands") as mock_set:
            with patch.object(bot_factory, "validate_token", return_value={"username": "t", "id": 1}):
                with patch.object(bot_factory, "ensure_registry"):
                    with patch.object(bot_factory, "register_bot", return_value=True):
                        with patch.object(bot_factory, "_api_set_secret", return_value=None):
                            with patch.object(bot_factory, "enable_service"):
                                with patch.object(bot_factory, "start_bot_process", return_value=True):
                                    bot_factory._BOT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                                    bot_factory.create_bot("sync_test", "999:ZZZ-token")

            mock_set.assert_called_once_with("999:ZZZ-token", expected)


class TestBaseBotStartupMenu:
    """Verify base_bot sets command menu on startup."""

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.set_bot_commands", return_value=True)
    def test_set_command_menu_called_on_startup(self, mock_set_commands):
        """_set_command_menu calls set_bot_commands with merged commands."""
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot
        from aipass.skills.lib.telegram.apps.handlers.telegram_standards import build_botfather_commands

        bot = BaseBot.__new__(BaseBot)
        bot.bot_token = "123:ABC"
        bot.custom_commands = {}
        bot.branch_name = None

        bot._set_command_menu()

        mock_set_commands.assert_called_once()
        actual_commands = mock_set_commands.call_args[0][1]
        expected = build_botfather_commands(
            standard_commands=bot._effective_standard_commands(),
            custom_commands=bot.get_custom_commands(),
        )
        assert actual_commands == expected

    @patch("aipass.skills.lib.telegram.apps.handlers.base_bot.set_bot_commands", return_value=True)
    def test_menu_includes_custom_commands(self, mock_set_commands):
        """Menu includes /create and /cancel from get_custom_commands."""
        from aipass.skills.lib.telegram.apps.handlers.base_bot import BaseBot

        bot = BaseBot.__new__(BaseBot)
        bot.bot_token = "123:ABC"
        bot.custom_commands = {}
        bot.branch_name = None

        bot._set_command_menu()

        actual_commands = mock_set_commands.call_args[0][1]
        cmd_names = {c["command"] for c in actual_commands}
        assert "create" in cmd_names
        assert "cancel" in cmd_names
        assert "start" in cmd_names
        assert "help" in cmd_names
