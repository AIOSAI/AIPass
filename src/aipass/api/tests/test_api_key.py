# =================== AIPass ====================
# Name: test_api_key.py
# Description: Tests for API Key Management Module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Tests for api_key.py — API key management module.

Tests:
- handle_command routing for all known commands
- handle_command returns False for unknown commands
- Help gate triggers print_help
- Introspection gate triggers print_introspection for no-args
- get_key success/failure paths
- validate_key valid/invalid/no-key paths
- init_env existing/create paths
- list_providers workflow
- json_handler.log_operation called on valid commands
"""

from unittest.mock import patch, MagicMock, call
from pathlib import Path

import pytest

from aipass.api.apps.modules import api_key


# =============================================
# Shared patch decorator — suppresses all CLI output
# =============================================

PATCH_CONSOLE = "aipass.api.apps.modules.api_key.console"
PATCH_HEADER = "aipass.api.apps.modules.api_key.header"
PATCH_SUCCESS = "aipass.api.apps.modules.api_key.success"
PATCH_ERROR = "aipass.api.apps.modules.api_key.error"
PATCH_WARNING = "aipass.api.apps.modules.api_key.warning"
PATCH_JSON_HANDLER = "aipass.api.apps.modules.api_key.json_handler"
PATCH_KEYS = "aipass.api.apps.modules.api_key.keys"
PATCH_ENV = "aipass.api.apps.modules.api_key.env"
PATCH_PROVIDER = "aipass.api.apps.modules.api_key.provider"


# =============================================
# handle_command — routing tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_JSON_HANDLER)
def test_handle_command_returns_false_for_unknown_command(mock_jh, mock_header, mock_console):
    """Unknown command should return False without logging."""
    result = api_key.handle_command("unknown", [])

    assert result is False
    mock_jh.log_operation.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_JSON_HANDLER)
@patch(PATCH_KEYS)
def test_handle_command_routes_get_key(mock_keys, mock_jh, mock_error, mock_success, mock_header, mock_console):
    """get-key command should route to get_key with args."""
    mock_keys.get_api_key.return_value = "sk-test1234567890abcdef"

    result = api_key.handle_command("get-key", ["openrouter"])

    assert result is True
    mock_keys.get_api_key.assert_called_once_with("openrouter")


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_JSON_HANDLER)
@patch(PATCH_KEYS)
def test_handle_command_routes_validate(mock_keys, mock_jh, mock_error, mock_success, mock_header, mock_console):
    """validate command should route to validate_key with args."""
    mock_keys.get_api_key.return_value = "sk-test1234567890abcdef"
    mock_keys.validate_key.return_value = True

    result = api_key.handle_command("validate", ["openrouter"])

    assert result is True
    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_keys.validate_key.assert_called_once_with("sk-test1234567890abcdef", "openrouter")


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_JSON_HANDLER)
def test_handle_command_routes_list_providers(mock_jh, mock_header, mock_console):
    """list-providers command should route to list_providers."""
    result = api_key.handle_command("list-providers", [])

    assert result is True
    mock_header.assert_called_once_with("Available Providers")


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_JSON_HANDLER)
@patch(PATCH_ENV)
def test_handle_command_routes_init(mock_env, mock_jh, mock_error, mock_success, mock_header, mock_console):
    """init command should route to init_env."""
    with patch("aipass.api.apps.modules.api_key.Path") as mock_path_cls:
        mock_env_path = MagicMock()
        mock_env_path.exists.return_value = True
        mock_path_cls.home.return_value.__truediv__ = MagicMock(return_value=mock_env_path)
        # Simpler: just mock the whole Path.home() chain
        mock_path_cls.home.return_value = MagicMock()
        mock_path_cls.home.return_value.__truediv__ = MagicMock()
        mock_home = MagicMock()
        mock_secrets = MagicMock()
        mock_aipass = MagicMock()
        mock_env_path = MagicMock()
        mock_env_path.exists.return_value = True
        mock_home.__truediv__ = MagicMock(return_value=mock_secrets)
        mock_secrets.__truediv__ = MagicMock(return_value=mock_aipass)
        mock_aipass.__truediv__ = MagicMock(return_value=mock_env_path)
        mock_path_cls.home.return_value = mock_home

        result = api_key.handle_command("init", [])

    assert result is True


# =============================================
# handle_command — gate tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_JSON_HANDLER)
def test_handle_command_help_gate(mock_jh, mock_header, mock_console):
    """--help arg should trigger print_help and return True without logging."""
    result = api_key.handle_command("get-key", ["--help"])

    assert result is True
    # Help gate fires before log_operation
    mock_jh.log_operation.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_JSON_HANDLER)
def test_handle_command_help_gate_short_flag(mock_jh, mock_header, mock_console):
    """Short -h flag should also trigger help gate."""
    result = api_key.handle_command("validate", ["-h"])

    assert result is True
    mock_jh.log_operation.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_JSON_HANDLER)
@patch(PATCH_KEYS)
def test_handle_command_get_key_no_args_defaults_to_openrouter(
    mock_keys, mock_jh, mock_error, mock_success, mock_header, mock_console
):
    """get-key with no args should execute with default provider 'openrouter'."""
    mock_keys.get_api_key.return_value = "sk-or-test-key-123"

    result = api_key.handle_command("get-key", [])

    assert result is True
    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_header.assert_called_with("Get API Key - openrouter")


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_JSON_HANDLER)
@patch(PATCH_KEYS)
def test_handle_command_validate_no_args_defaults_to_openrouter(
    mock_keys, mock_jh, mock_error, mock_success, mock_header, mock_console
):
    """validate with no args should execute with default provider 'openrouter'."""
    mock_keys.get_api_key.return_value = "sk-or-test-key-123"
    mock_keys.validate_key.return_value = True

    result = api_key.handle_command("validate", [])

    assert result is True
    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_header.assert_called_with("Validate API Key - openrouter")


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_JSON_HANDLER)
def test_handle_command_list_providers_standalone(mock_jh, mock_header, mock_console):
    """list-providers should work without args and not hit introspection gate."""
    result = api_key.handle_command("list-providers", [])

    assert result is True
    # Should call "Available Providers" header, not introspection
    mock_header.assert_called_with("Available Providers")


# =============================================
# get_key tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_KEYS)
def test_get_key_success(mock_keys, mock_error, mock_success, mock_header, mock_console):
    """Successful key retrieval should call success()."""
    mock_keys.get_api_key.return_value = "sk-test1234567890abcdef"

    api_key.get_key(["openrouter"])

    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_success.assert_called_once_with("API key retrieved for openrouter")
    mock_error.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_KEYS)
def test_get_key_failure(mock_keys, mock_error, mock_success, mock_header, mock_console):
    """Failed key retrieval (None returned) should call error()."""
    mock_keys.get_api_key.return_value = None

    api_key.get_key(["openrouter"])

    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_error.assert_called_once_with("Failed to retrieve API key for openrouter")
    mock_success.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_KEYS)
def test_get_key_default_provider(mock_keys, mock_error, mock_success, mock_header, mock_console):
    """Empty args list should default to 'openrouter' provider."""
    mock_keys.get_api_key.return_value = "sk-test1234567890abcdef"

    api_key.get_key([])

    mock_keys.get_api_key.assert_called_once_with("openrouter")


# =============================================
# validate_key tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_KEYS)
def test_validate_key_valid(mock_keys, mock_error, mock_success, mock_header, mock_console):
    """Valid key should call success()."""
    mock_keys.get_api_key.return_value = "sk-test1234567890abcdef"
    mock_keys.validate_key.return_value = True

    api_key.validate_key(["openrouter"])

    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_keys.validate_key.assert_called_once_with("sk-test1234567890abcdef", "openrouter")
    mock_success.assert_called_once_with("API key for openrouter is valid")
    mock_error.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_KEYS)
def test_validate_key_no_key(mock_keys, mock_error, mock_success, mock_header, mock_console):
    """No key found should call error() and skip validation."""
    mock_keys.get_api_key.return_value = None

    api_key.validate_key(["openrouter"])

    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_keys.validate_key.assert_not_called()
    mock_error.assert_called_once_with("No API key found for openrouter")
    mock_success.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_KEYS)
def test_validate_key_invalid(mock_keys, mock_error, mock_success, mock_header, mock_console):
    """Invalid key should call error()."""
    mock_keys.get_api_key.return_value = "sk-test1234567890abcdef"
    mock_keys.validate_key.return_value = False

    api_key.validate_key(["openrouter"])

    mock_keys.get_api_key.assert_called_once_with("openrouter")
    mock_keys.validate_key.assert_called_once_with("sk-test1234567890abcdef", "openrouter")
    mock_error.assert_called_once_with("API key for openrouter is invalid")
    mock_success.assert_not_called()


# =============================================
# init_env tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_ENV)
def test_init_env_already_exists(mock_env, mock_error, mock_success, mock_header, mock_console):
    """Existing env file should call success() and skip creation."""
    with patch("aipass.api.apps.modules.api_key.Path") as mock_path_cls:
        mock_env_path = MagicMock()
        mock_env_path.exists.return_value = True

        mock_home = MagicMock()
        mock_secrets = MagicMock()
        mock_aipass_dir = MagicMock()
        mock_home.__truediv__ = MagicMock(return_value=mock_secrets)
        mock_secrets.__truediv__ = MagicMock(return_value=mock_aipass_dir)
        mock_aipass_dir.__truediv__ = MagicMock(return_value=mock_env_path)
        mock_path_cls.home.return_value = mock_home

        api_key.init_env()

    mock_success.assert_called_once()
    assert "already exists" in mock_success.call_args[0][0]
    mock_env.create_env_template.assert_not_called()
    mock_error.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_ENV)
def test_init_env_creates_template(mock_env, mock_error, mock_success, mock_header, mock_console):
    """Missing env file should call create_env_template and success() on True."""
    mock_env.create_env_template.return_value = True

    with patch("aipass.api.apps.modules.api_key.Path") as mock_path_cls:
        mock_env_path = MagicMock()
        mock_env_path.exists.return_value = False

        mock_home = MagicMock()
        mock_secrets = MagicMock()
        mock_aipass_dir = MagicMock()
        mock_home.__truediv__ = MagicMock(return_value=mock_secrets)
        mock_secrets.__truediv__ = MagicMock(return_value=mock_aipass_dir)
        mock_aipass_dir.__truediv__ = MagicMock(return_value=mock_env_path)
        mock_path_cls.home.return_value = mock_home

        api_key.init_env()

    mock_env.create_env_template.assert_called_once()
    mock_success.assert_called_once()
    assert "template created" in mock_success.call_args[0][0]
    mock_error.assert_not_called()


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_ENV)
def test_init_env_create_failure(mock_env, mock_error, mock_success, mock_header, mock_console):
    """Failed template creation should call error()."""
    mock_env.create_env_template.return_value = False

    with patch("aipass.api.apps.modules.api_key.Path") as mock_path_cls:
        mock_env_path = MagicMock()
        mock_env_path.exists.return_value = False

        mock_home = MagicMock()
        mock_secrets = MagicMock()
        mock_aipass_dir = MagicMock()
        mock_home.__truediv__ = MagicMock(return_value=mock_secrets)
        mock_secrets.__truediv__ = MagicMock(return_value=mock_aipass_dir)
        mock_aipass_dir.__truediv__ = MagicMock(return_value=mock_env_path)
        mock_path_cls.home.return_value = mock_home

        api_key.init_env()

    mock_env.create_env_template.assert_called_once()
    mock_error.assert_called_once_with("Failed to create environment template")
    mock_success.assert_not_called()


# =============================================
# list_providers tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
def test_list_providers_prints_header(mock_header, mock_console):
    """list_providers should print 'Available Providers' header."""
    api_key.list_providers()

    mock_header.assert_called_once_with("Available Providers")


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
def test_list_providers_prints_openrouter(mock_header, mock_console):
    """list_providers should print openrouter as an available provider."""
    api_key.list_providers()

    # Check that console.print was called with the openrouter provider line
    print_calls = [str(c) for c in mock_console.print.call_args_list]
    found = any("openrouter" in c for c in print_calls)
    assert found, f"Expected 'openrouter' in console output, got: {print_calls}"


# =============================================
# log_operation tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_JSON_HANDLER)
def test_handle_command_logs_operation(mock_jh, mock_header, mock_console):
    """Valid command should call json_handler.log_operation with command context."""
    api_key.handle_command("list-providers", [])

    mock_jh.log_operation.assert_called_once_with(
        "api_key_list-providers",
        {"command": "list-providers"},
    )


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
@patch(PATCH_SUCCESS)
@patch(PATCH_ERROR)
@patch(PATCH_JSON_HANDLER)
@patch(PATCH_KEYS)
def test_handle_command_logs_operation_for_get_key(mock_keys, mock_jh, mock_error, mock_success, mock_header, mock_console):
    """get-key command should log api_key_get-key operation."""
    mock_keys.get_api_key.return_value = "sk-test1234567890abcdef"

    api_key.handle_command("get-key", ["openrouter"])

    mock_jh.log_operation.assert_called_once_with(
        "api_key_get-key",
        {"command": "get-key"},
    )


# =============================================
# print_introspection tests
# =============================================


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
def test_print_introspection_shows_header(mock_header, mock_console):
    """print_introspection should display the module header."""
    api_key.print_introspection()

    mock_header.assert_called_once_with("API Key Module Introspection")


@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
def test_print_introspection_shows_handlers(mock_header, mock_console):
    """print_introspection should list connected handlers."""
    api_key.print_introspection()

    print_calls = [str(c) for c in mock_console.print.call_args_list]
    found_keys = any("auth.keys" in c for c in print_calls)
    found_env = any("auth.env" in c for c in print_calls)
    found_provider = any("config.provider" in c for c in print_calls)
    assert found_keys, "Expected auth.keys handler listed"
    assert found_env, "Expected auth.env handler listed"
    assert found_provider, "Expected config.provider handler listed"


# =============================================
# handle_command — exception propagation
# =============================================


@patch(PATCH_KEYS)
@patch(PATCH_JSON_HANDLER)
@patch(PATCH_CONSOLE)
@patch(PATCH_HEADER)
def test_handle_command_propagates_exception(mock_header, mock_console, mock_jh, mock_keys):
    """handle_command re-raises exceptions from downstream handlers."""
    mock_keys.get_api_key.side_effect = RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        api_key.handle_command("get-key", ["openrouter"])


# =============================================
# get_key_from_config tests (auth.keys handler)
# =============================================

from aipass.api.apps.handlers.auth import keys as auth_keys


class TestGetKeyFromConfig:
    """Tests for auth.keys.get_key_from_config()."""

    def test_returns_key_from_valid_config(self, tmp_path, monkeypatch):
        """Valid config JSON should return the API key string."""
        import json

        config_dir = tmp_path / "api_json"
        config_dir.mkdir()
        config_file = config_dir / "api_connect_config.json"
        config_file.write_text(json.dumps({
            "config": {
                "providers": {
                    "openrouter": {"api_key": "sk-or-test-key-abc123"}
                }
            }
        }), encoding="utf-8")

        monkeypatch.setattr(auth_keys, "API_JSON_DIR", config_dir)

        result = auth_keys.get_key_from_config("openrouter")
        assert result == "sk-or-test-key-abc123"

    def test_returns_none_when_config_file_missing(self, tmp_path, monkeypatch):
        """Missing config file should return None."""
        config_dir = tmp_path / "api_json"
        config_dir.mkdir()
        monkeypatch.setattr(auth_keys, "API_JSON_DIR", config_dir)

        result = auth_keys.get_key_from_config("openrouter")
        assert result is None

    def test_returns_none_when_provider_not_in_config(self, tmp_path, monkeypatch):
        """Config exists but provider not listed should return None."""
        import json

        config_dir = tmp_path / "api_json"
        config_dir.mkdir()
        config_file = config_dir / "api_connect_config.json"
        config_file.write_text(json.dumps({
            "config": {
                "providers": {
                    "openai": {"api_key": "sk-openai-key-123"}
                }
            }
        }), encoding="utf-8")

        monkeypatch.setattr(auth_keys, "API_JSON_DIR", config_dir)

        result = auth_keys.get_key_from_config("openrouter")
        assert result is None

    def test_returns_none_when_api_key_empty(self, tmp_path, monkeypatch):
        """Provider present but api_key is empty string should return None."""
        import json

        config_dir = tmp_path / "api_json"
        config_dir.mkdir()
        config_file = config_dir / "api_connect_config.json"
        config_file.write_text(json.dumps({
            "config": {
                "providers": {
                    "openrouter": {"api_key": ""}
                }
            }
        }), encoding="utf-8")

        monkeypatch.setattr(auth_keys, "API_JSON_DIR", config_dir)

        result = auth_keys.get_key_from_config("openrouter")
        assert result is None

    def test_returns_none_when_config_missing_config_key(self, tmp_path, monkeypatch):
        """JSON file without 'config' top-level key should return None."""
        import json

        config_dir = tmp_path / "api_json"
        config_dir.mkdir()
        config_file = config_dir / "api_connect_config.json"
        config_file.write_text(json.dumps({"other": "data"}), encoding="utf-8")

        monkeypatch.setattr(auth_keys, "API_JSON_DIR", config_dir)

        result = auth_keys.get_key_from_config("openrouter")
        assert result is None

    @patch("aipass.api.apps.handlers.auth.keys.logger")
    def test_returns_none_on_invalid_json(self, mock_logger, tmp_path, monkeypatch):
        """Malformed JSON should return None and log error."""
        config_dir = tmp_path / "api_json"
        config_dir.mkdir()
        config_file = config_dir / "api_connect_config.json"
        config_file.write_text("not valid json {{{", encoding="utf-8")

        monkeypatch.setattr(auth_keys, "API_JSON_DIR", config_dir)

        result = auth_keys.get_key_from_config("openrouter")
        assert result is None
        mock_logger.error.assert_called_once()

    def test_reads_different_providers(self, tmp_path, monkeypatch):
        """Should retrieve keys for different provider names."""
        import json

        config_dir = tmp_path / "api_json"
        config_dir.mkdir()
        config_file = config_dir / "api_connect_config.json"
        config_file.write_text(json.dumps({
            "config": {
                "providers": {
                    "openrouter": {"api_key": "sk-or-key"},
                    "openai": {"api_key": "sk-openai-key"},
                    "anthropic": {"api_key": "sk-ant-key"},
                }
            }
        }), encoding="utf-8")

        monkeypatch.setattr(auth_keys, "API_JSON_DIR", config_dir)

        assert auth_keys.get_key_from_config("openrouter") == "sk-or-key"
        assert auth_keys.get_key_from_config("openai") == "sk-openai-key"
        assert auth_keys.get_key_from_config("anthropic") == "sk-ant-key"


# =============================================
# get_validation_rules tests (auth.keys handler)
# =============================================


class TestGetValidationRulesAuthKeys:
    """Tests for auth.keys.get_validation_rules()."""

    def test_openrouter_rules(self):
        """openrouter should have prefix 'sk-or-' and min_length 20."""
        rules = auth_keys.get_validation_rules("openrouter")
        assert rules["prefix"] == "sk-or-"
        assert rules["min_length"] == 20

    def test_openai_rules(self):
        """openai should have prefix 'sk-' and min_length 20."""
        rules = auth_keys.get_validation_rules("openai")
        assert rules["prefix"] == "sk-"
        assert rules["min_length"] == 20

    def test_anthropic_rules(self):
        """anthropic should have prefix 'sk-ant-' and min_length 20."""
        rules = auth_keys.get_validation_rules("anthropic")
        assert rules["prefix"] == "sk-ant-"
        assert rules["min_length"] == 20

    def test_unknown_provider_falls_back_to_generic(self):
        """Unknown provider should fall back to generic rules."""
        rules = auth_keys.get_validation_rules("unknown_provider")
        assert rules["min_length"] == 10
        assert "prefix" not in rules

    def test_generic_rules_directly(self):
        """Requesting 'generic' should return generic rules."""
        rules = auth_keys.get_validation_rules("generic")
        assert rules["min_length"] == 10
        assert "prefix" not in rules

    def test_return_type_is_dict(self):
        """All providers should return a dict."""
        for provider in ["openrouter", "openai", "anthropic", "generic", "nonexistent"]:
            rules = auth_keys.get_validation_rules(provider)
            assert isinstance(rules, dict)
