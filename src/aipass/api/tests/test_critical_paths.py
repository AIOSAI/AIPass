# =================== AIPass ====================
# Name: test_critical_paths.py
# Description: Critical path tests for API branch core functions
# Version: 1.0.0
# Created: 2026-03-31
# Modified: 2026-03-31
# =============================================

"""
Critical path tests for the API branch.

Covers the 4 core functions that form the API request pipeline:

1. get_api_key() - Key retrieval from config JSON and secrets file
2. validate_key() - Key format validation per provider rules
3. get_response() - Main API call orchestrator
4. extract_response() - Response content extraction

All external dependencies are mocked. File-based tests use tmp_path.
"""

import json
from unittest.mock import patch, MagicMock


# =============================================
# 1. get_api_key() tests
# =============================================


class TestGetApiKey:
    """Tests for get_api_key() — key retrieval from config and secrets sources."""

    @patch("aipass.api.apps.handlers.auth.keys.json_handler")
    @patch("aipass.api.apps.handlers.auth.keys.API_JSON_DIR")
    def test_key_from_config_json(self, mock_api_json_dir, mock_jh, tmp_path):
        """Key found in api_connect_config.json is returned after validation."""
        from aipass.api.apps.handlers.auth.keys import get_api_key

        config_path = tmp_path / "api_connect_config.json"
        config_data = {
            "config": {
                "providers": {"openrouter": {"api_key": "sk-or-v1-NOTREAL-test-000000000000000000000000000000000000"}}
            }
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        mock_api_json_dir.__truediv__ = lambda self, name: tmp_path / name

        result = get_api_key("openrouter")
        # do not add real api kets here
        assert result == "sk-or-v1-NOTREAL-test-000000000000000000000000000000000000"

        mock_jh.log_operation.assert_called_once()

    @patch("aipass.api.apps.handlers.auth.keys.json_handler")
    @patch("aipass.api.apps.handlers.auth.keys.API_JSON_DIR")
    def test_key_from_secrets_file(self, mock_api_json_dir, mock_jh, tmp_path):
        """Key found in ~/.secrets/aipass/.env when config has no key."""
        from aipass.api.apps.handlers.auth.keys import get_api_key

        # Config file exists but has no key for openrouter
        config_path = tmp_path / "api_connect_config.json"
        config_data = {"config": {"providers": {}}}
        config_path.write_text(json.dumps(config_data), encoding="utf-8")
        mock_api_json_dir.__truediv__ = lambda self, name: tmp_path / name

        # Create secrets file
        secrets_dir = tmp_path / ".secrets" / "aipass"
        secrets_dir.mkdir(parents=True)
        env_file = secrets_dir / ".env"
        env_file.write_text(
            "OPENROUTER_API_KEY=sk-or-v1-NOTREAL-test-00000000000000000000000000\n",
            encoding="utf-8",
        )

        with patch("aipass.api.apps.handlers.auth.keys.Path") as mock_path_cls:
            # Path.home() should return tmp_path so secrets resolve there
            mock_path_cls.home.return_value = tmp_path
            result = get_api_key("openrouter")

        assert result == "sk-or-v1-NOTREAL-test-00000000000000000000000000"

    @patch("aipass.api.apps.handlers.auth.keys.json_handler")
    @patch("aipass.api.apps.handlers.auth.keys.API_JSON_DIR")
    def test_no_key_found_returns_none(self, mock_api_json_dir, mock_jh, tmp_path):
        """Returns None when no key exists in any source."""
        from aipass.api.apps.handlers.auth.keys import get_api_key

        # Config file with no providers
        config_path = tmp_path / "api_connect_config.json"
        config_data = {"config": {"providers": {}}}
        config_path.write_text(json.dumps(config_data), encoding="utf-8")
        mock_api_json_dir.__truediv__ = lambda self, name: tmp_path / name

        # No secrets file exists
        with patch("aipass.api.apps.handlers.auth.keys.Path") as mock_path_cls:
            mock_home = tmp_path / "nonexistent_home"
            mock_path_cls.home.return_value = mock_home
            result = get_api_key("openrouter")

        assert result is None

    @patch("aipass.api.apps.handlers.auth.keys.json_handler")
    @patch("aipass.api.apps.handlers.auth.keys.API_JSON_DIR")
    def test_invalid_key_format_returns_none(self, mock_api_json_dir, mock_jh, tmp_path):
        """Key exists in config but fails validation (wrong prefix) returns None."""
        from aipass.api.apps.handlers.auth.keys import get_api_key

        config_path = tmp_path / "api_connect_config.json"
        config_data = {"config": {"providers": {"openrouter": {"api_key": "INVALID-PREFIX-key-that-is-long-enough"}}}}
        config_path.write_text(json.dumps(config_data), encoding="utf-8")
        mock_api_json_dir.__truediv__ = lambda self, name: tmp_path / name

        # No secrets file fallback
        with patch("aipass.api.apps.handlers.auth.keys.Path") as mock_path_cls:
            mock_path_cls.home.return_value = tmp_path / "no_home"
            result = get_api_key("openrouter")

        assert result is None


# =============================================
# 2. validate_key() tests
# =============================================


class TestValidateKey:
    """Tests for validate_key() — key format validation per provider rules."""

    def test_valid_openrouter_key(self):
        """Valid openrouter key with correct prefix and length passes."""
        from aipass.api.apps.handlers.auth.keys import validate_key

        key = "sk-or-v1-NOTREAL-test-000000000000000000000000000000000000"
        assert validate_key(key, "openrouter") is True

    def test_key_too_short(self):
        """Key shorter than min_length fails validation."""
        from aipass.api.apps.handlers.auth.keys import validate_key

        key = "sk-or-v1-short"
        assert len(key) < 20
        assert validate_key(key, "openrouter") is False

    def test_wrong_prefix(self):
        """Key with wrong prefix for provider fails validation."""
        from aipass.api.apps.handlers.auth.keys import validate_key

        key = "sk-wrong-prefix-but-long-enough-to-pass-length"
        assert validate_key(key, "openrouter") is False

    def test_empty_key(self):
        """Empty string key fails validation."""
        from aipass.api.apps.handlers.auth.keys import validate_key

        assert validate_key("", "openrouter") is False

    def test_none_key(self):
        """None key fails validation."""
        from aipass.api.apps.handlers.auth.keys import validate_key

        assert validate_key(None, "openrouter") is False  # type: ignore[arg-type]

    def test_generic_provider_no_prefix_required(self):
        """Generic provider only checks min_length, no prefix required."""
        from aipass.api.apps.handlers.auth.keys import validate_key

        key = "any-key-that-is-long-enough"
        assert validate_key(key, "unknown_provider") is True

    def test_generic_provider_too_short(self):
        """Generic provider rejects keys shorter than 10 chars."""
        from aipass.api.apps.handlers.auth.keys import validate_key

        assert validate_key("short", "unknown_provider") is False


# =============================================
# 3. get_response() tests
# =============================================


MODULE = "aipass.api.apps.handlers.openrouter.client"


class TestGetResponse:
    """Tests for get_response() — main API call orchestrator."""

    @patch(f"{MODULE}.track_usage")
    @patch(f"{MODULE}.extract_response")
    @patch(f"{MODULE}.make_api_request")
    @patch(f"{MODULE}.get_cached_client")
    @patch(f"{MODULE}.get_api_key")
    @patch(f"{MODULE}.ensure_caller_config")
    @patch(f"{MODULE}.get_caller_info")
    def test_successful_call(
        self,
        mock_caller_info,
        mock_ensure,
        mock_get_key,
        mock_get_client,
        mock_make_req,
        mock_extract,
        mock_track,
    ):
        """Full successful pipeline: detect caller, get key, make request, extract, track."""
        from aipass.api.apps.handlers.openrouter.client import get_response

        mock_caller_info.return_value = {"caller_name": "test-branch"}
        mock_get_key.return_value = "FAKE-sk-or-v1-testkey"
        mock_get_client.return_value = MagicMock()
        mock_make_req.return_value = MagicMock()
        mock_extract.return_value = {
            "content": "Hello, world!",
            "id": "gen-abc123",
            "model": "anthropic/claude-3.5-sonnet",
        }

        result = get_response("What is Python?", model="anthropic/claude-3.5-sonnet")

        assert result is not None
        assert result["content"] == "Hello, world!"
        assert result["id"] == "gen-abc123"
        mock_track.assert_called_once()

    @patch(f"{MODULE}.get_api_key")
    @patch(f"{MODULE}.ensure_caller_config")
    @patch(f"{MODULE}.get_caller_info")
    def test_no_model_returns_none(self, mock_caller_info, mock_ensure, mock_get_key):
        """Missing model parameter returns None without making API call."""
        from aipass.api.apps.handlers.openrouter.client import get_response

        mock_caller_info.return_value = {"caller_name": "test"}

        result = get_response("What is Python?", model=None)

        assert result is None
        mock_get_key.assert_not_called()

    @patch(f"{MODULE}.get_api_key")
    @patch(f"{MODULE}.ensure_caller_config")
    @patch(f"{MODULE}.get_caller_info")
    def test_no_api_key_returns_none(self, mock_caller_info, mock_ensure, mock_get_key):
        """No API key available returns None."""
        from aipass.api.apps.handlers.openrouter.client import get_response

        mock_caller_info.return_value = {"caller_name": "test"}
        mock_get_key.return_value = None

        result = get_response("What is Python?", model="anthropic/claude-3.5-sonnet")

        assert result is None


# =============================================
# 4. extract_response() tests
# =============================================


class TestExtractResponse:
    """Tests for extract_response() — response content extraction from OpenAI objects."""

    def test_valid_response(self):
        """Extracts content, id, and model from a well-formed response."""
        from aipass.api.apps.handlers.openrouter.client import extract_response

        choice = MagicMock()
        choice.message.content = "The answer is 42."
        choice.finish_reason = "stop"

        response = MagicMock()
        response.choices = [choice]
        response.id = "gen-xyz789"
        response.model = "anthropic/claude-3.5-sonnet"

        result = extract_response(response)

        assert result is not None
        assert result["content"] == "The answer is 42."
        assert result["id"] == "gen-xyz789"
        assert result["model"] == "anthropic/claude-3.5-sonnet"

    def test_none_response(self):
        """None response returns None."""
        from aipass.api.apps.handlers.openrouter.client import extract_response

        assert extract_response(None) is None

    def test_response_no_choices(self):
        """Response with empty choices list returns None."""
        from aipass.api.apps.handlers.openrouter.client import extract_response

        response = MagicMock()
        response.choices = []

        assert extract_response(response) is None

    def test_response_no_content(self):
        """Response with choice but no content returns None."""
        from aipass.api.apps.handlers.openrouter.client import extract_response

        choice = MagicMock()
        choice.message.content = None

        response = MagicMock()
        response.choices = [choice]
        response.id = "gen-empty"
        response.model = "test/model"

        assert extract_response(response) is None

    def test_response_missing_message(self):
        """Response choice without message attribute returns None."""
        from aipass.api.apps.handlers.openrouter.client import extract_response

        choice = MagicMock(spec=[])  # No attributes at all
        response = MagicMock()
        response.choices = [choice]

        assert extract_response(response) is None
