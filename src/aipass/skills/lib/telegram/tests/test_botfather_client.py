"""
Comprehensive pytest tests for botfather_client.py.

Tests cover:
  - _load_telethon_config: secret loading, validation, coercion
  - check_telethon_setup: readiness checks (library, config, session)
  - _format_display_name: branch name -> display name conversion
  - _format_username: branch name + suffix -> username generation
  - BotFatherClient: connect, disconnect, _send_and_wait, create_bot (all mocked)
  - create_bot_via_botfather: sync wrapper end-to-end (mocked)

All Telethon classes and network calls are mocked.
No real Telegram API interaction occurs.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from aipass.skills.lib.telegram.apps.handlers.botfather_client import (
    _load_telethon_config,
    check_telethon_setup,
    _format_display_name,
    _format_username,
    BotFatherClient,
    create_bot_via_botfather,
    BOT_TOKEN_PATTERN,
)


# =============================================
# 1. _load_telethon_config
# =============================================


class TestLoadTelethonConfig:
    """Test _load_telethon_config: secret loading, JSON parsing, validation."""

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._get_secret")
    def test_returns_config_when_valid(self, mock_get_secret):
        """Returns config dict when secret store has valid api_id and api_hash."""
        mock_get_secret.return_value = {"api_id": 12345, "api_hash": "abc123def"}
        result = _load_telethon_config()
        assert result is not None
        assert result["api_id"] == 12345
        assert result["api_hash"] == "abc123def"
        mock_get_secret.assert_called_once_with("telethon_config")

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._get_secret")
    def test_raises_when_secret_missing(self, mock_get_secret):
        """Raises RuntimeError when the secret doesn't exist."""
        mock_get_secret.return_value = None
        import pytest

        with pytest.raises(RuntimeError, match="not found in secrets store"):
            _load_telethon_config()

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._get_secret")
    def test_raises_when_api_id_missing(self, mock_get_secret):
        """Raises RuntimeError when api_id is missing from config."""
        mock_get_secret.return_value = {"api_hash": "abc123def"}
        import pytest

        with pytest.raises(RuntimeError, match="missing api_id or api_hash"):
            _load_telethon_config()

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._get_secret")
    def test_coerces_api_id_from_string(self, mock_get_secret):
        """Coerces api_id to int when provided as a string."""
        mock_get_secret.return_value = {"api_id": "99999", "api_hash": "xyz789"}
        result = _load_telethon_config()
        assert result is not None
        assert result["api_id"] == 99999
        assert isinstance(result["api_id"], int)


# =============================================
# 2. check_telethon_setup
# =============================================


class TestCheckTelethonSetup:
    """Test check_telethon_setup: checks library, config, session file."""

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config")
    def test_returns_ready_when_all_in_place(self, mock_load_config, tmp_path, monkeypatch):
        """Returns (True, 'ready') when Telethon is available, config valid, session exists."""
        monkeypatch.setattr("aipass.skills.lib.telegram.apps.handlers.botfather_client.TELETHON_AVAILABLE", True)
        mock_load_config.return_value = {"api_id": 12345, "api_hash": "abc123"}

        # Create session file at the new path
        session_path = tmp_path / ".telethon"
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.SESSION_PATH",
            session_path,
        )
        session_file = Path(str(session_path) + ".session")
        session_file.write_text("session data", encoding="utf-8")

        ready, reason = check_telethon_setup()
        assert ready is True
        assert reason == "ready"

    def test_returns_false_when_telethon_not_available(self, monkeypatch):
        """Returns (False, ...) when TELETHON_AVAILABLE is False."""
        monkeypatch.setattr("aipass.skills.lib.telegram.apps.handlers.botfather_client.TELETHON_AVAILABLE", False)
        ready, reason = check_telethon_setup()
        assert ready is False
        assert "not installed" in reason.lower() or "telethon" in reason.lower()

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config")
    def test_returns_false_when_config_not_in_secrets(self, mock_load_config, monkeypatch):
        """Returns (False, ...) when secret store has no telethon config."""
        monkeypatch.setattr("aipass.skills.lib.telegram.apps.handlers.botfather_client.TELETHON_AVAILABLE", True)
        mock_load_config.side_effect = RuntimeError(
            "Telethon config not found in secrets store (telegram/telethon_config)"
        )
        ready, reason = check_telethon_setup()
        assert ready is False
        assert "not found" in reason.lower()

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config")
    def test_returns_false_when_config_invalid(self, mock_load_config, monkeypatch):
        """Returns (False, ...) when config exists but is invalid (missing fields)."""
        monkeypatch.setattr("aipass.skills.lib.telegram.apps.handlers.botfather_client.TELETHON_AVAILABLE", True)
        mock_load_config.side_effect = RuntimeError("Telethon config incomplete — missing api_id or api_hash")
        ready, reason = check_telethon_setup()
        assert ready is False
        assert "missing api_id or api_hash" in reason

    @patch("aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config")
    def test_returns_false_when_session_file_missing(self, mock_load_config, tmp_path, monkeypatch):
        """Returns (False, ...) when session file doesn't exist."""
        monkeypatch.setattr("aipass.skills.lib.telegram.apps.handlers.botfather_client.TELETHON_AVAILABLE", True)
        mock_load_config.return_value = {"api_id": 12345, "api_hash": "abc123"}

        session_path = tmp_path / ".telethon"
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.SESSION_PATH",
            session_path,
        )
        # Do NOT create the session file
        ready, reason = check_telethon_setup()
        assert ready is False
        assert "session" in reason.lower()


# =============================================
# 3. _format_display_name
# =============================================


class TestFormatDisplayName:
    """Test _format_display_name: branch name to display name conversion."""

    def test_dev_central(self):
        assert _format_display_name("dev_central") == "AIPass Dev Central"

    def test_flow(self):
        assert _format_display_name("flow") == "AIPass Flow"

    def test_memory_bank(self):
        assert _format_display_name("memory_bank") == "AIPass Memory Bank"

    def test_empty_string(self):
        assert _format_display_name("") == "AIPass "


# =============================================
# 4. _format_username
# =============================================


class TestFormatUsername:
    """Test _format_username: branch name + suffix to username generation."""

    def test_dev_central_no_suffix(self):
        assert _format_username("dev_central", 0) == "aipass_dev_central_bot"

    def test_dev_central_suffix_1(self):
        assert _format_username("dev_central", 1) == "aipass_dev_central_1_bot"

    def test_flow_no_suffix(self):
        assert _format_username("flow", 0) == "aipass_flow_bot"

    def test_flow_suffix_2(self):
        assert _format_username("flow", 2) == "aipass_flow_2_bot"


# =============================================
# 5. BotFatherClient (mocked Telethon)
# =============================================


class TestBotFatherClientConnect:
    """Test BotFatherClient.connect() with mocked Telethon."""

    def test_connect_returns_true_when_authorized(self):
        """connect() returns True when session is authorized."""
        mock_client_instance = AsyncMock()
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.get_me.return_value = MagicMock(first_name="TestUser", id=123)

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client._telethon_check",
            create=True,
        ):
            with patch(
                "telethon.TelegramClient",
                return_value=mock_client_instance,
            ):
                client = BotFatherClient(api_id=12345, api_hash="abc123")
                result = asyncio.run(client.connect())
                assert result is True
                mock_client_instance.connect.assert_awaited_once()
                mock_client_instance.is_user_authorized.assert_awaited_once()

    def test_connect_returns_false_when_not_authorized(self):
        """connect() returns False when session is not authorized."""
        mock_client_instance = AsyncMock()
        mock_client_instance.is_user_authorized.return_value = False

        with patch(
            "telethon.TelegramClient",
            return_value=mock_client_instance,
        ):
            client = BotFatherClient(api_id=12345, api_hash="abc123")
            result = asyncio.run(client.connect())
            assert result is False
            mock_client_instance.disconnect.assert_awaited_once()

    def test_connect_returns_false_on_exception(self):
        """connect() returns False when exception occurs (e.g., session file missing)."""
        with patch(
            "telethon.TelegramClient",
            side_effect=Exception("Session file not found"),
        ):
            client = BotFatherClient(api_id=12345, api_hash="abc123")
            result = asyncio.run(client.connect())
            assert result is False
            assert client._client is None


class TestBotFatherClientDisconnect:
    """Test BotFatherClient.disconnect() with mocked Telethon."""

    def test_disconnect_calls_client_disconnect(self):
        """disconnect() calls client.disconnect()."""
        mock_client_instance = AsyncMock()
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        client._client = mock_client_instance

        asyncio.run(client.disconnect())
        mock_client_instance.disconnect.assert_awaited_once()
        assert client._client is None

    def test_disconnect_handles_error_gracefully(self):
        """disconnect() handles errors without raising."""
        mock_client_instance = AsyncMock()
        mock_client_instance.disconnect.side_effect = Exception("Connection error")
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        client._client = mock_client_instance

        # Should not raise
        asyncio.run(client.disconnect())
        assert client._client is None

    def test_disconnect_noop_when_no_client(self):
        """disconnect() is a no-op when _client is None."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        client._client = None
        # Should not raise
        asyncio.run(client.disconnect())
        assert client._client is None


class TestBotFatherClientSendAndWait:
    """Test BotFatherClient._send_and_wait with mocked Telethon."""

    def _make_client_with_mock(self):
        """Helper to create a BotFatherClient with a mocked Telethon client."""
        mock_telethon = AsyncMock()
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        client._client = mock_telethon
        return client, mock_telethon

    def test_returns_response_text_on_success(self):
        """_send_and_wait returns response text on successful message exchange."""
        client, mock_telethon = self._make_client_with_mock()
        entity = MagicMock()

        # Create a mock message from BotFather (out=False means incoming)
        mock_msg = MagicMock()
        mock_msg.out = False
        mock_msg.text = "Please choose a name for your bot."

        mock_telethon.get_messages.return_value = [mock_msg]

        # Use a real time base so asyncio loop isn't disrupted.
        # MESSAGE_TIMEOUT is 30s; the mock response arrives immediately,
        # so the while-loop condition is satisfied on the first iteration.
        with patch("aipass.skills.lib.telegram.apps.handlers.botfather_client.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(client._send_and_wait(entity, "/newbot"))

        assert result == "Please choose a name for your bot."
        mock_telethon.send_message.assert_awaited_once_with(entity, "/newbot")

    def test_returns_none_on_timeout(self):
        """_send_and_wait returns None when BotFather doesn't respond within timeout."""
        client, mock_telethon = self._make_client_with_mock()
        entity = MagicMock()

        # Return only our own outgoing messages (out=True), so BotFather never "responds"
        mock_msg = MagicMock()
        mock_msg.out = True
        mock_msg.text = "our own message"
        mock_telethon.get_messages.return_value = [mock_msg]

        # Shrink the timeout to 0 so the while-loop exits immediately
        with patch("aipass.skills.lib.telegram.apps.handlers.botfather_client.MESSAGE_TIMEOUT", 0):
            with patch(
                "aipass.skills.lib.telegram.apps.handlers.botfather_client.asyncio.sleep", new_callable=AsyncMock
            ):
                result = asyncio.run(client._send_and_wait(entity, "/newbot"))

        assert result is None

    def test_handles_flood_wait_error(self):
        """_send_and_wait sleeps and retries on FloodWaitError."""
        client, mock_telethon = self._make_client_with_mock()
        entity = MagicMock()

        class MockFloodWaitError(Exception):
            def __init__(self, seconds):
                self.seconds = seconds
                super().__init__(f"Flood wait for {seconds}s")

        class MockRPCError(Exception):
            pass

        # First call raises flood error, retry succeeds
        mock_telethon.send_message.side_effect = [MockFloodWaitError(2), None]

        mock_msg = MagicMock()
        mock_msg.out = False
        mock_msg.text = "Response after flood wait"
        mock_telethon.get_messages.return_value = [mock_msg]

        with patch("aipass.skills.lib.telegram.apps.handlers.botfather_client.asyncio.sleep", new_callable=AsyncMock):
            with patch("telethon.errors.FloodWaitError", MockFloodWaitError, create=True):
                with patch("telethon.errors.RPCError", MockRPCError, create=True):
                    result = asyncio.run(client._send_and_wait(entity, "/newbot"))

        assert result == "Response after flood wait"
        assert mock_telethon.send_message.await_count == 2

    def test_handles_rpc_error(self):
        """_send_and_wait returns None on RPCError."""
        client, mock_telethon = self._make_client_with_mock()
        entity = MagicMock()

        class MockFloodWaitError(Exception):
            def __init__(self, seconds):
                self.seconds = seconds

        class MockRPCError(Exception):
            pass

        mock_telethon.send_message.side_effect = MockRPCError("RPC error")

        with patch("telethon.errors.FloodWaitError", MockFloodWaitError, create=True):
            with patch("telethon.errors.RPCError", MockRPCError, create=True):
                result = asyncio.run(client._send_and_wait(entity, "/newbot"))

        assert result is None

    def test_returns_none_when_client_is_none(self):
        """_send_and_wait returns None when _client is None."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        client._client = None
        entity = MagicMock()

        result = asyncio.run(client._send_and_wait(entity, "/newbot"))
        assert result is None


class TestBotFatherClientCreateBot:
    """Test BotFatherClient.create_bot with mocked _send_and_wait."""

    def test_returns_dict_on_success(self):
        """create_bot returns dict with token, username, display_name on success."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon

        # Mock get_entity to resolve BotFather
        botfather_entity = MagicMock(id=93372553)
        mock_telethon.get_entity.return_value = botfather_entity

        # Mock _send_and_wait for the 3-step conversation
        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Alright, a new bot. How are we going to call it? Please choose a name for your bot."
            elif message == "AIPass Dev Central":
                return "Good. Now let's choose a username for your bot."
            elif message == "aipass_dev_central_bot":
                return "Done! Congratulations on your new bot. Use this token: 123456789:ABCdefGHI_jklMNOpqrSTUvwx"
            return None

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is not None
        assert result["token"] == "123456789:ABCdefGHI_jklMNOpqrSTUvwx"
        assert result["username"] == "aipass_dev_central_bot"
        assert result["display_name"] == "AIPass Dev Central"

    def test_handles_username_taken_retries_with_suffix(self):
        """create_bot retries with numeric suffix when username is taken."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon

        botfather_entity = MagicMock(id=93372553)
        mock_telethon.get_entity.return_value = botfather_entity

        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Alright, a new bot. Please choose a name for your bot."
            elif message == "AIPass Dev Central":
                return "Good. Now let's choose a username."
            elif message == "aipass_dev_central_bot":
                return "Sorry, this username is already taken. Please try something different."
            elif message == "aipass_dev_central_1_bot":
                return "Done! Here is your token: 987654321:ZYXwvuTSR_qpoNMLkji"
            return None

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is not None
        assert result["username"] == "aipass_dev_central_1_bot"
        assert "987654321" in result["token"]

    def test_returns_none_when_newbot_unexpected_response(self):
        """create_bot returns None when /newbot gets unexpected response."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.return_value = MagicMock()

        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Some unexpected response without the word we look for"
            return None

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is None

    def test_returns_none_when_display_name_unexpected_response(self):
        """create_bot returns None when display name gets unexpected response."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.return_value = MagicMock()

        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Please choose a name for your bot."
            elif message == "AIPass Dev Central":
                return "Something unexpected without the keyword we need"
            return None

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is None

    def test_returns_none_after_all_username_attempts_exhausted(self):
        """create_bot returns None when all username attempts are exhausted."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.return_value = MagicMock()

        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Please choose a name for your bot."
            elif message == "AIPass Flow":
                return "Now let's choose a username."
            else:
                # All username attempts taken
                return "Sorry, this username is already taken."

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("flow"))

        assert result is None

    def test_returns_none_when_not_connected(self):
        """create_bot returns None when _client is None."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        client._client = None

        result = asyncio.run(client.create_bot("dev_central"))
        assert result is None

    def test_returns_none_when_newbot_no_response(self):
        """create_bot returns None when BotFather doesn't respond to /newbot."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.return_value = MagicMock()

        async def mock_send_and_wait(entity, message):
            return None  # BotFather never responds

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is None

    def test_returns_none_when_display_name_no_response(self):
        """create_bot returns None when BotFather doesn't respond to display name."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.return_value = MagicMock()

        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Please choose a name for your bot."
            return None  # No response to display name

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is None

    def test_returns_none_when_get_entity_fails(self):
        """create_bot returns None when resolving BotFather entity fails."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.side_effect = Exception("Cannot resolve entity")

        result = asyncio.run(client.create_bot("dev_central"))
        assert result is None

    def test_returns_none_when_username_no_response(self):
        """create_bot returns None when BotFather doesn't respond to username."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.return_value = MagicMock()

        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Please choose a name for your bot."
            elif message == "AIPass Dev Central":
                return "Now let's choose a username."
            elif "aipass_dev_central" in message:
                return None  # No response to username
            return None

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is None

    def test_returns_none_on_unexpected_username_response(self):
        """create_bot returns None on unexpected (non-taken, non-token) username response."""
        client = BotFatherClient(api_id=12345, api_hash="abc123")
        mock_telethon = AsyncMock()
        client._client = mock_telethon
        mock_telethon.get_entity.return_value = MagicMock()

        async def mock_send_and_wait(entity, message):
            if message == "/newbot":
                return "Please choose a name for your bot."
            elif message == "AIPass Dev Central":
                return "Now let's choose a username."
            elif "aipass_dev_central" in message:
                return "Invalid username format. Must end in 'bot'."
            return None

        with patch.object(client, "_send_and_wait", side_effect=mock_send_and_wait):
            result = asyncio.run(client.create_bot("dev_central"))

        assert result is None


# =============================================
# 6. create_bot_via_botfather (sync wrapper)
# =============================================


class TestCreateBotViaBotfather:
    """Test create_bot_via_botfather: the synchronous entry point."""

    def test_raises_when_setup_not_ready(self, monkeypatch):
        """Raises RuntimeError when check_telethon_setup says not ready."""
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.check_telethon_setup",
            lambda: (False, "Telethon not installed"),
        )
        import pytest

        with pytest.raises(RuntimeError, match="Telethon setup failed"):
            create_bot_via_botfather("dev_central")

    def test_raises_when_config_load_fails(self, monkeypatch):
        """Raises RuntimeError when _load_telethon_config raises."""
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.check_telethon_setup",
            lambda: (True, "ready"),
        )

        def _raise():
            raise RuntimeError("Telethon config not found in secrets store (telegram/telethon_config)")

        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config",
            _raise,
        )
        import pytest

        with pytest.raises(RuntimeError, match="not found in secrets store"):
            create_bot_via_botfather("dev_central")

    def test_returns_result_on_success(self, monkeypatch):
        """Returns result dict on successful flow."""
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.check_telethon_setup",
            lambda: (True, "ready"),
        )
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config",
            lambda: {"api_id": 12345, "api_hash": "abc123"},
        )

        expected_result = {
            "token": "111:AAA_bbb",
            "username": "aipass_dev_central_bot",
            "display_name": "AIPass Dev Central",
        }

        mock_client = MagicMock(spec=BotFatherClient)

        async def mock_connect():
            return True

        async def mock_create_bot(branch_name):
            return expected_result

        async def mock_disconnect():
            pass

        mock_client.connect = mock_connect
        mock_client.create_bot = mock_create_bot
        mock_client.disconnect = mock_disconnect

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.BotFatherClient",
            return_value=mock_client,
        ):
            result = create_bot_via_botfather("dev_central")

        assert result is not None
        assert result["token"] == "111:AAA_bbb"
        assert result["username"] == "aipass_dev_central_bot"

    def test_handles_connection_failure(self, monkeypatch):
        """Returns None when connection fails."""
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.check_telethon_setup",
            lambda: (True, "ready"),
        )
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config",
            lambda: {"api_id": 12345, "api_hash": "abc123"},
        )

        mock_client = MagicMock(spec=BotFatherClient)

        async def mock_connect():
            return False

        async def mock_disconnect():
            pass

        mock_client.connect = mock_connect
        mock_client.disconnect = mock_disconnect

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.BotFatherClient",
            return_value=mock_client,
        ):
            result = create_bot_via_botfather("dev_central")

        assert result is None

    def test_handles_botfather_failure(self, monkeypatch):
        """Returns None when BotFather automation fails."""
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.check_telethon_setup",
            lambda: (True, "ready"),
        )
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config",
            lambda: {"api_id": 12345, "api_hash": "abc123"},
        )

        mock_client = MagicMock(spec=BotFatherClient)

        async def mock_connect():
            return True

        async def mock_create_bot(branch_name):
            return None  # BotFather failed

        async def mock_disconnect():
            pass

        mock_client.connect = mock_connect
        mock_client.create_bot = mock_create_bot
        mock_client.disconnect = mock_disconnect

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.BotFatherClient",
            return_value=mock_client,
        ):
            result = create_bot_via_botfather("dev_central")

        assert result is None

    def test_handles_existing_event_loop(self, monkeypatch):
        """Handles the edge case where an event loop is already running."""
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.check_telethon_setup",
            lambda: (True, "ready"),
        )
        monkeypatch.setattr(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client._load_telethon_config",
            lambda: {"api_id": 12345, "api_hash": "abc123"},
        )

        expected_result = {
            "token": "222:BBB_ccc",
            "username": "aipass_flow_bot",
            "display_name": "AIPass Flow",
        }

        mock_client = MagicMock(spec=BotFatherClient)

        async def mock_connect():
            return True

        async def mock_create_bot(branch_name):
            return expected_result

        async def mock_disconnect():
            pass

        mock_client.connect = mock_connect
        mock_client.create_bot = mock_create_bot
        mock_client.disconnect = mock_disconnect

        with patch(
            "aipass.skills.lib.telegram.apps.handlers.botfather_client.BotFatherClient",
            return_value=mock_client,
        ):
            # Simulate an already-running event loop by patching get_running_loop
            # to return a mock loop, which triggers the ThreadPoolExecutor path
            mock_loop = MagicMock()
            mock_loop.is_running.return_value = True

            with patch(
                "aipass.skills.lib.telegram.apps.handlers.botfather_client.asyncio.get_running_loop",
                return_value=mock_loop,
            ):
                result = create_bot_via_botfather("flow")

        assert result is not None
        assert result["token"] == "222:BBB_ccc"


# =============================================
# 7. BOT_TOKEN_PATTERN regex
# =============================================


class TestBotTokenPattern:
    """Test the BOT_TOKEN_PATTERN regex matches valid tokens."""

    def test_matches_standard_token(self):
        match = BOT_TOKEN_PATTERN.search("123456789:ABCdefGHI_jklMNOpqrSTUvwx")
        assert match is not None
        assert match.group() == "123456789:ABCdefGHI_jklMNOpqrSTUvwx"

    def test_matches_token_in_botfather_response(self):
        response = "Done! Use this token to access the HTTP API: 123456789:ABCdef-GHIjkl"
        match = BOT_TOKEN_PATTERN.search(response)
        assert match is not None

    def test_no_match_on_plain_text(self):
        match = BOT_TOKEN_PATTERN.search("Sorry, this username is already taken.")
        assert match is None
