# =================== AIPass ====================
# Name: test_openrouter_client.py
# Description: Tests for OpenRouter client module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Tests for openrouter_client.py — OpenRouter client module orchestration.

Tests:
- handle_command routing for test, call, models, status, unknown
- Help gate (--help) and introspection gate (no-args on "call")
- log_operation called on every valid command
- test_connection success / no-key / API-failure paths
- list_models success / no-key / --all limiter
- check_status with key / without key
- get_response delegation to client handler
"""

from unittest.mock import patch, MagicMock, call

import pytest

from aipass.api.apps.modules.openrouter_client import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection


# Base set of patches applied to every test via the module-level prefix
_MOD = "aipass.api.apps.modules.openrouter_client"


# =============================================
# handle_command — routing
# =============================================


@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_returns_false_for_unknown(mock_console, mock_header, mock_jh):
    """handle_command returns False when the command is not recognised."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("unknown", [])

    assert result is False
    mock_jh.log_operation.assert_not_called()


@patch(f"{_MOD}.test_connection")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_routes_test(mock_console, mock_header, mock_jh, mock_test):
    """handle_command('test', []) delegates to test_connection()."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("test", [])

    assert result is True
    mock_test.assert_called_once()


@patch(f"{_MOD}.list_models")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_routes_models(mock_console, mock_header, mock_jh, mock_list):
    """handle_command('models', []) delegates to list_models()."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("models", [])

    assert result is True
    mock_list.assert_called_once_with([])


@patch(f"{_MOD}.check_status")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_routes_status(mock_console, mock_header, mock_jh, mock_status):
    """handle_command('status', []) delegates to check_status()."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("status", [])

    assert result is True
    mock_status.assert_called_once()


@patch(f"{_MOD}.make_call")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_routes_call(mock_console, mock_header, mock_jh, mock_call):
    """handle_command('call', ['hello']) delegates to make_call with args."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("call", ["hello"])

    assert result is True
    mock_call.assert_called_once_with(["hello"])


# =============================================
# handle_command — gates
# =============================================


@patch(f"{_MOD}.print_help")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_help_gate(mock_console, mock_header, mock_jh, mock_help):
    """--help flag triggers print_help and returns True without logging."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("test", ["--help"])

    assert result is True
    mock_help.assert_called_once()
    mock_jh.log_operation.assert_not_called()


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_call_no_args_executes(mock_console, mock_header, mock_jh, mock_error):
    """'call' with no args should execute (show error), not show introspection."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("call", [])

    assert result is True
    mock_error.assert_called()
    assert "Prompt required" in mock_error.call_args[0][0]


# =============================================
# handle_command — logging
# =============================================


@patch(f"{_MOD}.test_connection")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_logs_operation(mock_console, mock_header, mock_jh, mock_test):
    """Valid commands log their operation via json_handler.log_operation."""
    from aipass.api.apps.modules import openrouter_client

    openrouter_client.handle_command("test", [])

    mock_jh.log_operation.assert_called_once_with(
        "openrouter_test", {"command": "test"}
    )


# =============================================
# test_connection
# =============================================


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_test_connection_success(mock_console, mock_header, mock_keys, mock_models, mock_success):
    """Successful connection prints success with model count."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    mock_models.fetch_models_from_api.return_value = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]

    openrouter_client.test_connection()

    mock_models.fetch_models_from_api.assert_called_once_with("sk-or-test-key")
    mock_success.assert_called_once()
    assert "3 models" in mock_success.call_args[0][0]


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_test_connection_success_no_error(mock_console, mock_header, mock_keys, mock_models, mock_success, mock_error):
    """Successful connection must not call error()."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    mock_models.fetch_models_from_api.return_value = [{"id": "m1"}]

    openrouter_client.test_connection()

    mock_error.assert_not_called()


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_test_connection_no_key(mock_console, mock_header, mock_keys, mock_error):
    """Missing API key triggers error with diagnosis."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "No key found in env"

    openrouter_client.test_connection()

    mock_keys.diagnose_key.assert_called_once_with("openrouter")
    mock_error.assert_called_once_with("No key found in env")


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_test_connection_no_key_no_success(mock_console, mock_header, mock_keys, mock_error, mock_success):
    """Missing API key path must not call success()."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "No key found in env"

    openrouter_client.test_connection()

    mock_success.assert_not_called()


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_test_connection_api_failure_no_success(mock_console, mock_header, mock_keys, mock_models, mock_error, mock_success):
    """API failure path must not call success()."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    mock_models.fetch_models_from_api.return_value = None

    openrouter_client.test_connection()

    mock_success.assert_not_called()


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_test_connection_api_failure(mock_console, mock_header, mock_keys, mock_models, mock_error):
    """API returning None triggers connection-failed error."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    mock_models.fetch_models_from_api.return_value = None

    openrouter_client.test_connection()

    mock_error.assert_called_once()
    assert "failed" in mock_error.call_args[0][0].lower()


# =============================================
# list_models
# =============================================


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_success(mock_console, mock_header, mock_keys, mock_models, mock_success):
    """Successful model listing prints success and table rows."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    fake_models = [
        {
            "id": f"provider/model-{i}",
            "context_length": 128000,
            "pricing": {"prompt": "0.001", "completion": "0.002"},
        }
        for i in range(3)
    ]
    mock_models.fetch_models_from_api.return_value = fake_models

    openrouter_client.list_models([])

    mock_success.assert_called_once()
    assert "3 models" in mock_success.call_args[0][0]
    # Header row + separator + 3 data rows = at least 5 console.print calls after header
    assert mock_console.print.call_count >= 5


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_success_no_error(mock_console, mock_header, mock_keys, mock_models, mock_success, mock_error):
    """Successful model listing must not call error()."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    mock_models.fetch_models_from_api.return_value = [
        {"id": "p/m", "context_length": 4096, "pricing": {"prompt": "0", "completion": "0"}}
    ]

    openrouter_client.list_models([])

    mock_error.assert_not_called()


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_no_key_no_success(mock_console, mock_header, mock_keys, mock_error, mock_success):
    """Missing API key on list_models must not call success()."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "Key not set"

    openrouter_client.list_models([])

    mock_success.assert_not_called()


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_no_key(mock_console, mock_header, mock_keys, mock_error):
    """Missing API key triggers error with diagnosis."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "Key not set"

    openrouter_client.list_models([])

    mock_error.assert_called_once_with("Key not set")


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_limits_to_10(mock_console, mock_header, mock_keys, mock_models, mock_success):
    """Without --all flag, only 10 models are displayed from a larger list."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    fake_models = [
        {
            "id": f"provider/model-{i}",
            "context_length": 4096,
            "pricing": {"prompt": "0", "completion": "0"},
        }
        for i in range(25)
    ]
    mock_models.fetch_models_from_api.return_value = fake_models

    openrouter_client.list_models([])

    # Count data rows: calls that contain a model ID pattern
    data_row_calls = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "provider/model-" in c.args[0]
    ]
    assert len(data_row_calls) == 10

    # Should show "Showing 10 of 25" truncation notice
    all_output = " ".join(
        str(c) for c in mock_console.print.call_args_list
    )
    assert "10 of 25" in all_output


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_all_flag_shows_everything(mock_console, mock_header, mock_keys, mock_models, mock_success):
    """With --all flag, all models are displayed."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test-key"
    fake_models = [
        {
            "id": f"provider/model-{i}",
            "context_length": 4096,
            "pricing": {"prompt": "0", "completion": "0"},
        }
        for i in range(25)
    ]
    mock_models.fetch_models_from_api.return_value = fake_models

    openrouter_client.list_models(["--all"])

    data_row_calls = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "provider/model-" in c.args[0]
    ]
    assert len(data_row_calls) == 25


# =============================================
# check_status
# =============================================


@patch(f"{_MOD}.client")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_check_status_with_key(mock_console, mock_header, mock_keys, mock_client):
    """When API key exists, status shows masked key and cache stats."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-v1-abcdefgh12345678"
    mock_client.get_cache_stats.return_value = {"cached_clients": 2, "max_cache_size": 5}

    openrouter_client.check_status()

    all_output = " ".join(str(c) for c in mock_console.print.call_args_list)
    # Key should be shown as masked
    assert "sk-or-v1" in all_output
    assert "5678" in all_output
    # "yes" for key configured
    assert "yes" in all_output
    # Cache stats shown
    assert "2/5" in all_output


@patch(f"{_MOD}.client")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_check_status_no_key(mock_console, mock_header, mock_keys, mock_client):
    """When API key is missing, status shows 'no' and diagnosis."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "OPENROUTER_API_KEY not set"
    mock_client.get_cache_stats.return_value = {"cached_clients": 0, "max_cache_size": 5}

    openrouter_client.check_status()

    all_output = " ".join(str(c) for c in mock_console.print.call_args_list)
    assert "no" in all_output
    assert "OPENROUTER_API_KEY not set" in all_output


# =============================================
# get_response — delegation
# =============================================


@patch(f"{_MOD}.client")
def test_get_response_delegates_to_handler(mock_client):
    """get_response passes through to client.get_response and returns its result."""
    from aipass.api.apps.modules import openrouter_client

    mock_client.get_response.return_value = {
        "content": "Hello!",
        "id": "gen-123",
        "model": "anthropic/claude-3.5-sonnet",
    }

    result = openrouter_client.get_response(
        "Hi there",
        caller="flow",
        model="anthropic/claude-3.5-sonnet",
        temperature=0.5,
    )

    mock_client.get_response.assert_called_once_with(
        "Hi there",
        "flow",
        "anthropic/claude-3.5-sonnet",
        temperature=0.5,
    )
    assert result is not None
    assert result["content"] == "Hello!"
    assert result["model"] == "anthropic/claude-3.5-sonnet"


@patch(f"{_MOD}.client")
def test_get_response_returns_none_on_failure(mock_client):
    """get_response returns None when client handler returns None."""
    from aipass.api.apps.modules import openrouter_client

    mock_client.get_response.return_value = None

    result = openrouter_client.get_response("fail prompt", caller="test")

    assert result is None


# =============================================
# list_models — context formatting
# =============================================


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_formats_million_context(mock_console, mock_header, mock_keys, mock_models, mock_success):
    """Context length >= 1M formatted as 'XM'."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test"
    mock_models.fetch_models_from_api.return_value = [
        {"id": "big/model", "context_length": 2_000_000, "pricing": {"prompt": "0", "completion": "0"}}
    ]

    openrouter_client.list_models([])

    data_rows = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "big/model" in c.args[0]
    ]
    assert len(data_rows) == 1
    assert "2M" in data_rows[0].args[0]


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_formats_thousand_context(mock_console, mock_header, mock_keys, mock_models, mock_success):
    """Context length >= 1k formatted as 'Xk'."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test"
    mock_models.fetch_models_from_api.return_value = [
        {"id": "med/model", "context_length": 128_000, "pricing": {"prompt": "0.01", "completion": "0.02"}}
    ]

    openrouter_client.list_models([])

    data_rows = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "med/model" in c.args[0]
    ]
    assert len(data_rows) == 1
    assert "128k" in data_rows[0].args[0]


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_formats_free_pricing(mock_console, mock_header, mock_keys, mock_models, mock_success):
    """Models with zero pricing show 'free'."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test"
    mock_models.fetch_models_from_api.return_value = [
        {"id": "free/model", "context_length": 4096, "pricing": {"prompt": "0", "completion": "0"}}
    ]

    openrouter_client.list_models([])

    data_rows = [
        c for c in mock_console.print.call_args_list
        if c.args and isinstance(c.args[0], str) and "free/model" in c.args[0]
    ]
    assert len(data_rows) == 1
    assert "free" in data_rows[0].args[0]


# =============================================
# make_call — stub behaviour
# =============================================


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_make_call_no_model_shows_error(mock_console, mock_header, mock_error):
    """make_call without --model shows error."""
    from aipass.api.apps.modules import openrouter_client

    openrouter_client.make_call(["What is AI?"])

    mock_error.assert_called_once()
    assert "Model required" in mock_error.call_args[0][0]


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_call_no_args_shows_error(mock_console, mock_header, mock_jh, mock_error):
    """call with no args should show error, not introspection."""
    from aipass.api.apps.modules import openrouter_client

    result = openrouter_client.handle_command("call", [])

    assert result is True
    mock_error.assert_called_once()
    assert "Prompt required" in mock_error.call_args[0][0]


# =============================================
# list_models — error on fetch failure
# =============================================


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.models")
@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_list_models_fetch_failure(mock_console, mock_header, mock_keys, mock_models, mock_error):
    """When fetch_models_from_api returns None, error is shown."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.return_value = "sk-or-test"
    mock_models.fetch_models_from_api.return_value = None

    openrouter_client.list_models([])

    mock_error.assert_called_once()
    assert "fetch" in mock_error.call_args[0][0].lower()


# =============================================
# handle_command — exception propagation
# =============================================


@patch(f"{_MOD}.keys")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.console")
def test_handle_command_propagates_exception(mock_console, mock_header, mock_jh, mock_keys):
    """handle_command re-raises exceptions from downstream handlers."""
    from aipass.api.apps.modules import openrouter_client

    mock_keys.get_api_key.side_effect = RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        openrouter_client.handle_command("test", [])


# =============================================
# create_client() — handler-level tests
# =============================================

_CLIENT_MOD = "aipass.api.apps.handlers.openrouter.client"


@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", False)
def test_create_client_returns_none_when_sdk_unavailable():
    """create_client returns None when OpenAI SDK is not installed."""
    from aipass.api.apps.handlers.openrouter.client import create_client

    result = create_client("sk-or-test-key")

    assert result is None


@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_returns_none_for_empty_key():
    """create_client returns None when api_key is empty string."""
    from aipass.api.apps.handlers.openrouter.client import create_client

    assert create_client("") is None


@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_returns_none_for_none_key():
    """create_client returns None when api_key is None."""
    from aipass.api.apps.handlers.openrouter.client import create_client

    assert create_client(None) is None  # type: ignore[arg-type]


@patch(f"{_CLIENT_MOD}.json_handler")
@patch(f"{_CLIENT_MOD}.OpenAI")
@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_success(mock_openai_cls, mock_jh):
    """create_client returns an OpenAI client instance on success."""
    from aipass.api.apps.handlers.openrouter.client import create_client, OPENROUTER_HEADERS

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    result = create_client("sk-or-valid-key", base_url="https://openrouter.ai/api/v1", timeout=30)

    assert result is mock_client
    mock_openai_cls.assert_called_once_with(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-valid-key",
        timeout=30,
        default_headers=OPENROUTER_HEADERS,
    )


@patch(f"{_CLIENT_MOD}.json_handler")
@patch(f"{_CLIENT_MOD}.OpenAI")
@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_custom_timeout(mock_openai_cls, mock_jh):
    """create_client passes custom timeout to OpenAI constructor."""
    from aipass.api.apps.handlers.openrouter.client import create_client

    mock_openai_cls.return_value = MagicMock()

    create_client("sk-or-key", timeout=60)

    assert mock_openai_cls.call_args[1]["timeout"] == 60


@patch(f"{_CLIENT_MOD}.OpenAI")
@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_returns_none_on_exception(mock_openai_cls):
    """create_client returns None when OpenAI constructor raises."""
    from aipass.api.apps.handlers.openrouter.client import create_client

    mock_openai_cls.side_effect = RuntimeError("connection refused")

    result = create_client("sk-or-key")

    assert result is None
