# =================== AIPass ====================
# Name: test_openrouter_client.py
# Description: Tests for OpenRouter client module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-09-29
# =============================================

"""Tests for apps/modules/openrouter_client.py and create_client in apps/handlers/openrouter/client.py."""

# Tests for openrouter_client.py — OpenRouter client module orchestration.
#
# Tests:
# - handle_command routing for test, call, models, status, unknown
# - Help gate (--help) and introspection gate (no-args on "call")
# - log_operation called on every valid command
# - test_connection success / no-key / API-failure paths
# - list_models success / no-key / --all limiter
# - check_status with key / without key
# - get_response delegation to client handler

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — OPENROUTER_HEADERS' values; the test compares with the product's constant
# seedgo: no-test-needed(duplicate_test) — detect_caller_from_stack() itself, tests/test_caller_detection.py
# seedgo: no-test-needed(through_the_command) — the real network request behind make_call(), mocked at the edge

from unittest.mock import patch, MagicMock

import pytest

from aipass.api.apps.handlers.openrouter.client import OPENROUTER_HEADERS, create_client
from aipass.api.apps.modules import openrouter_client
from aipass.api.apps.modules.openrouter_client import handle_command
from aipass.api.apps.modules.openrouter_client import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection


# Base set of patches applied to every test via the module-level prefix
_MOD = "aipass.api.apps.modules.openrouter_client"
# The real exception, taken before any test replaces models with an autospec stub,
# whose class attributes are mocks an except clause cannot match (api, fleet green leg 3).
_MODELS_UNAVAILABLE = openrouter_client.models.ModelsUnavailable


# =============================================
# handle_command — routing
# =============================================


@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_returns_false_for_unknown(mock_header, mock_jh, capsys):
    """handle_command returns False when the command is not recognised, and prints nothing."""
    result = openrouter_client.handle_command("unknown", [])

    assert result is False
    mock_jh.log_operation.assert_not_called()
    assert capsys.readouterr() == ("", "")


@patch(f"{_MOD}.test_connection")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_routes_test(mock_header, mock_jh, mock_test):
    """handle_command('test', []) delegates to test_connection()."""
    result = openrouter_client.handle_command("test", [])

    assert result is True
    mock_test.assert_called_once()


@patch(f"{_MOD}.list_models")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_routes_models(mock_header, mock_jh, mock_list):
    """handle_command('models', []) delegates to list_models()."""
    result = openrouter_client.handle_command("models", [])

    assert result is True
    mock_list.assert_called_once_with([])


@patch(f"{_MOD}.check_status")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_routes_status(mock_header, mock_jh, mock_status):
    """handle_command('status', []) delegates to check_status()."""
    result = openrouter_client.handle_command("status", [])

    assert result is True
    mock_status.assert_called_once()


@patch(f"{_MOD}.make_call")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_routes_call(mock_header, mock_jh, mock_call):
    """handle_command('call', ['hello']) delegates to make_call with args."""
    result = openrouter_client.handle_command("call", ["hello"])

    assert result is True
    mock_call.assert_called_once_with(["hello"])


# =============================================
# handle_command — gates
# =============================================


@patch(f"{_MOD}.test_connection")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_help_gate(mock_header, mock_jh, mock_test, capsys):
    """--help flag prints the help screen and returns True without logging or running."""
    result = openrouter_client.handle_command("test", ["--help"])

    out, _err = capsys.readouterr()
    assert result is True
    assert "OPENROUTER_CLIENT" in out
    assert "drone @api test" in out
    mock_test.assert_not_called()
    mock_jh.log_operation.assert_not_called()


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_call_no_args_executes(mock_header, mock_jh, mock_error):
    """'call' with no args should execute (show error), not show introspection."""
    result = openrouter_client.handle_command("call", [])

    assert result is True
    mock_error.assert_called()
    assert "Prompt required" in mock_error.call_args[0][0]


# =============================================
# handle_command — logging
# =============================================


@patch(f"{_MOD}.test_connection")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_logs_operation(mock_header, mock_jh, mock_test):
    """Valid commands log their operation via json_handler.log_operation."""
    openrouter_client.handle_command("test", [])

    mock_jh.log_operation.assert_called_once_with("openrouter_test", {"command": "test"})


# =============================================
# test_connection
# =============================================


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_test_connection_success(mock_header, mock_keys, mock_models, mock_success, mock_error):
    """
    A successful connection reports the model count AND says nothing else.

    MERGED 2026-09-07 (DPLAN-0323 contested band). This file split every happy
    path into a second not-called twin running identical setup;
    `test_test_connection_success_no_error` was this call again for one
    `assert_not_called`. That line came here rather than being deleted with the
    twin: "success was reported" and "no error was ALSO reported" are two
    facts, and a path that printed both would have passed the positive half.
    """
    mock_keys.get_api_key.return_value = "FAKE-sk-or-testkey"
    mock_models.fetch_models_from_api.return_value = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]

    openrouter_client.test_connection()

    mock_models.fetch_models_from_api.assert_called_once_with("FAKE-sk-or-testkey")
    mock_success.assert_called_once()
    assert "3 models" in mock_success.call_args[0][0]
    mock_error.assert_not_called()


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_test_connection_no_key(mock_header, mock_keys, mock_error, mock_success):
    """
    A missing key is diagnosed, reported as an error, and never as a success.

    MERGED 2026-09-07 (DPLAN-0323 contested band): the not-called half was
    `test_test_connection_no_key_no_success`, identical setup for one line.
    """
    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "No key found in env"

    openrouter_client.test_connection()

    mock_keys.diagnose_key.assert_called_once_with("openrouter")
    mock_error.assert_called_once_with("No key found in env")
    mock_success.assert_not_called()


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_test_connection_api_failure(mock_header, mock_keys, mock_models, mock_error, mock_success):
    """
    An unreadable endpoint is reported as a failure with its reason, never as a success.

    MERGED 2026-09-07 (DPLAN-0323 contested band): the not-called half was
    `test_test_connection_api_failure_no_success`, identical setup for one line.
    The fetch now raises instead of returning an empty list (api, fleet green leg 3).
    """
    mock_keys.get_api_key.return_value = "FAKE-sk-or-testkey"
    mock_models.ModelsUnavailable = _MODELS_UNAVAILABLE
    mock_models.fetch_models_from_api.side_effect = _MODELS_UNAVAILABLE("status 503")

    openrouter_client.test_connection()

    mock_error.assert_called_once_with("Connection failed — status 503")
    mock_success.assert_not_called()


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_test_connection_an_endpoint_with_no_models_is_a_success(
    mock_header, mock_keys, mock_models, mock_error, mock_success
):
    """An empty model list is an answer: connection successful with 0 models, no error.

    Green from its first run; its proof is the mutant reporting a failure for an
    empty list (api, fleet green leg 4).
    """
    mock_keys.get_api_key.return_value = "FAKE-sk-or-testkey"
    mock_models.ModelsUnavailable = _MODELS_UNAVAILABLE
    mock_models.fetch_models_from_api.return_value = []

    openrouter_client.test_connection()

    mock_success.assert_called_once_with("Connection successful — 0 models available")
    mock_error.assert_not_called()


# =============================================
# list_models
# =============================================


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_success(mock_header, mock_keys, mock_models, mock_success, mock_error, capsys):
    """
    A successful listing reports the count and rows, and reports no error.

    MERGED 2026-09-07 (DPLAN-0323 contested band): the not-called half was
    `test_list_models_success_no_error`, the same call again for one line.
    """
    mock_keys.get_api_key.return_value = "FAKE-sk-or-testkey"
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

    out, _err = capsys.readouterr()
    mock_success.assert_called_once()
    assert "3 models" in mock_success.call_args[0][0]
    # The table the user reads: its header row and one row per model
    assert "$/prompt" in out
    for i in range(3):
        assert f"provider/model-{i}" in out
    mock_error.assert_not_called()


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_no_key(mock_header, mock_keys, mock_error, mock_success):
    """
    A missing key is reported as an error and never as a success.

    MERGED 2026-09-07 (DPLAN-0323 contested band): the not-called half was
    `test_list_models_no_key_no_success`, identical setup for one line.
    """
    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "Key not set"

    openrouter_client.list_models([])

    mock_error.assert_called_once_with("Key not set")
    mock_success.assert_not_called()


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_limits_to_10(mock_header, mock_keys, mock_models, mock_success, capsys):
    """Without --all flag, only 10 models are displayed from a larger list."""
    mock_keys.get_api_key.return_value = "FAKE-sk-or-testkey"
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

    # Count data rows: printed lines that carry a model ID
    out, _err = capsys.readouterr()
    data_rows = [line for line in out.splitlines() if "provider/model-" in line]
    assert len(data_rows) == 10

    # Should show "Showing 10 of 25" truncation notice
    assert "Showing 10 of 25" in out


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_all_flag_shows_everything(mock_header, mock_keys, mock_models, mock_success, capsys):
    """With --all flag, all models are displayed."""
    mock_keys.get_api_key.return_value = "FAKE-sk-or-testkey"
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

    out, _err = capsys.readouterr()
    data_rows = [line for line in out.splitlines() if "provider/model-" in line]
    assert len(data_rows) == 25
    assert "Showing 10 of" not in out


# =============================================
# check_status
# =============================================


@patch(f"{_MOD}.client", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_check_status_with_key(mock_header, mock_keys, mock_client, capsys):
    """When API key exists, status shows masked key and cache stats."""
    mock_keys.get_api_key.return_value = "sk-or-v1-NOTREAL-test12345678"
    mock_client.get_cache_stats.return_value = {"cached_clients": 2, "max_cache_size": 5}

    openrouter_client.check_status()

    out, _err = capsys.readouterr()
    # Key should be shown as masked: first 8 and last 4 only
    assert "sk-or-v1...5678" in out
    assert "NOTREAL" not in out
    # "yes" for key configured
    assert "Key configured:  yes" in out
    # Cache stats shown
    assert "Cached clients: 2/5" in out


@patch(f"{_MOD}.client", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_check_status_no_key(mock_header, mock_keys, mock_client, capsys):
    """When API key is missing, status warns and shows the diagnosis."""
    mock_keys.get_api_key.return_value = None
    mock_keys.diagnose_key.return_value = "OPENROUTER_API_KEY not set"
    mock_client.get_cache_stats.return_value = {"cached_clients": 0, "max_cache_size": 5}

    openrouter_client.check_status()

    out, err = capsys.readouterr()
    # cli's warning() writes to stderr: pinned there, whole, and absent from stdout
    # (api, fleet green leg 4 - either stream used to pass).
    assert err.splitlines() == ["⚠️  API key not configured"]
    assert "API key not configured" not in out
    assert "Reason:          OPENROUTER_API_KEY not set" in out
    assert "Key configured" not in out


# =============================================
# get_response — delegation
# =============================================


@patch(f"{_MOD}.client", autospec=True)
def test_get_response_delegates_to_handler(mock_client):
    """get_response passes through to client.get_response and returns its result."""
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


@patch(f"{_MOD}.client", autospec=True)
def test_get_response_returns_none_on_failure(mock_client):
    """get_response returns None when client handler returns None."""
    mock_client.get_response.return_value = None

    result = openrouter_client.get_response("fail prompt", caller="test")

    assert result is None


# =============================================
# list_models — context formatting
# =============================================


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_formats_million_context(mock_header, mock_keys, mock_models, mock_success, capsys):
    """Context length >= 1M formatted as 'XM'."""
    mock_keys.get_api_key.return_value = "FAKE-sk-or-test"
    mock_models.fetch_models_from_api.return_value = [
        {"id": "big/model", "context_length": 2_000_000, "pricing": {"prompt": "0", "completion": "0"}}
    ]

    openrouter_client.list_models([])

    out, _err = capsys.readouterr()
    data_rows = [line for line in out.splitlines() if "big/model" in line]
    assert len(data_rows) == 1
    assert data_rows[0].split()[1] == "2M"


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_formats_thousand_context(mock_header, mock_keys, mock_models, mock_success, capsys):
    """Context length >= 1k formatted as 'Xk'."""
    mock_keys.get_api_key.return_value = "FAKE-sk-or-test"
    mock_models.fetch_models_from_api.return_value = [
        {"id": "med/model", "context_length": 128_000, "pricing": {"prompt": "0.01", "completion": "0.02"}}
    ]

    openrouter_client.list_models([])

    out, _err = capsys.readouterr()
    data_rows = [line for line in out.splitlines() if "med/model" in line]
    assert len(data_rows) == 1
    assert data_rows[0].split() == ["med/model", "128k", "$0.01", "$0.02"]


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_formats_free_pricing(mock_header, mock_keys, mock_models, mock_success, capsys):
    """Models with zero pricing show 'free'."""
    mock_keys.get_api_key.return_value = "FAKE-sk-or-test"
    mock_models.fetch_models_from_api.return_value = [
        {"id": "free/model", "context_length": 4096, "pricing": {"prompt": "0", "completion": "0"}}
    ]

    openrouter_client.list_models([])

    out, _err = capsys.readouterr()
    data_rows = [line for line in out.splitlines() if "free/model" in line]
    assert len(data_rows) == 1
    assert data_rows[0].split()[2:] == ["free", "free"]


# =============================================
# make_call — stub behaviour
# =============================================


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.client", autospec=True)
@patch(f"{_MOD}.header")
def test_make_call_no_model_shows_error(mock_header, mock_client, mock_error):
    """make_call without --model shows error and never reaches the client."""
    openrouter_client.make_call(["What is AI?"])

    mock_error.assert_called_once_with(
        "Model required", suggestion='drone @api call "your prompt" --model anthropic/claude-3.5-sonnet'
    )
    mock_client.get_response.assert_not_called()


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_call_no_args_shows_error(mock_header, mock_jh, mock_error):
    """call with no args should show error, not introspection."""
    result = openrouter_client.handle_command("call", [])

    assert result is True
    mock_error.assert_called_once()
    assert "Prompt required" in mock_error.call_args[0][0]


# =============================================
# list_models — error on fetch failure
# =============================================


@patch(f"{_MOD}.error")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_fetch_failure(mock_header, mock_keys, mock_models, mock_error):
    """When fetch_models_from_api raises, the error names the reason (api, fleet green leg 3)."""
    mock_keys.get_api_key.return_value = "FAKE-sk-or-test"
    mock_models.ModelsUnavailable = _MODELS_UNAVAILABLE
    mock_models.fetch_models_from_api.side_effect = _MODELS_UNAVAILABLE("status 503")

    openrouter_client.list_models([])

    mock_models.fetch_models_from_api.assert_called_once_with("FAKE-sk-or-test")
    mock_error.assert_called_once_with("Failed to fetch models — status 503")


@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.models", autospec=True)
@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.header")
def test_list_models_an_endpoint_with_no_models_is_found_zero(
    mock_header, mock_keys, mock_models, mock_error, mock_success
):
    """An empty model list is listed as found 0 models, never as a failure.

    Green from its first run; its proof is the mutant reporting a failure for an
    empty list (api, fleet green leg 4).
    """
    mock_keys.get_api_key.return_value = "FAKE-sk-or-test"
    mock_models.ModelsUnavailable = _MODELS_UNAVAILABLE
    mock_models.fetch_models_from_api.return_value = []

    openrouter_client.list_models([])

    mock_success.assert_called_once_with("Found 0 models")
    mock_error.assert_not_called()


# =============================================
# handle_command — exception propagation
# =============================================


@patch(f"{_MOD}.keys", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
def test_handle_command_propagates_exception(mock_header, mock_jh, mock_keys):
    """handle_command re-raises exceptions from downstream handlers."""
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
    result = create_client("FAKE-sk-or-testkey")

    assert result is None


@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_returns_none_for_empty_key():
    """create_client returns None when api_key is empty string."""
    assert create_client("") is None


@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_returns_none_for_none_key():
    """create_client returns None when api_key is None."""
    assert create_client(None) is None  # type: ignore[arg-type]


@patch(f"{_CLIENT_MOD}.json_handler", autospec=True)
@patch(f"{_CLIENT_MOD}.OpenAI")
@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_success(mock_openai_cls, mock_jh):
    """create_client returns an OpenAI client instance on success."""
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    result = create_client("FAKE-sk-or-validkey", base_url="https://openrouter.ai/api/v1", timeout=30)

    assert result is mock_client
    mock_openai_cls.assert_called_once_with(
        base_url="https://openrouter.ai/api/v1",
        api_key="FAKE-sk-or-validkey",
        timeout=30,
        default_headers=OPENROUTER_HEADERS,
    )


@patch(f"{_CLIENT_MOD}.json_handler", autospec=True)
@patch(f"{_CLIENT_MOD}.OpenAI")
@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_custom_timeout(mock_openai_cls, mock_jh):
    """create_client passes custom timeout to OpenAI constructor."""
    mock_openai_cls.return_value = MagicMock()

    create_client("FAKE-sk-or-key", timeout=60)

    assert mock_openai_cls.call_args[1]["timeout"] == 60


@patch(f"{_CLIENT_MOD}.OpenAI")
@patch(f"{_CLIENT_MOD}.OPENAI_AVAILABLE", True)
def test_create_client_returns_none_on_exception(mock_openai_cls):
    """create_client returns None when OpenAI constructor raises."""
    mock_openai_cls.side_effect = RuntimeError("connection refused")

    result = create_client("FAKE-sk-or-key")

    assert result is None


class TestTrailingHelpDoesNotExecute:
    """A help flag must explain the command, never run it.

    Gating on args[0] only let `models --all --help` and `call "..." --help`
    reach the API-calling paths. Reported by @seedgo via help_flag_safety.
    """

    def test_models_with_flag_and_trailing_help_shows_help(self):
        """`models --all --help` prints help instead of hitting the API."""
        with patch(f"{_MOD}.print_help") as mock_help, patch(f"{_MOD}.list_models") as mock_models:
            assert handle_command("models", ["--all", "--help"]) is True

        mock_models.assert_not_called()
        mock_help.assert_called_once()

    def test_call_with_prompt_and_trailing_help_shows_help(self):
        """`call "prompt" --help` prints help instead of spending a real API call."""
        with patch(f"{_MOD}.print_help") as mock_help, patch(f"{_MOD}.make_call") as mock_call:
            assert handle_command("call", ["explain this", "--help"]) is True

        mock_call.assert_not_called()
        mock_help.assert_called_once()

    def test_prompt_text_containing_help_word_still_executes(self):
        """A bare `help` inside a prompt is content, not a flag."""
        with (
            patch(f"{_MOD}.print_help") as mock_help,
            patch(f"{_MOD}.make_call") as mock_call,
            patch(f"{_MOD}.json_handler", autospec=True),
        ):
            assert handle_command("call", ["how do I get help", "--model", "x"]) is True

        mock_call.assert_called_once_with(["how do I get help", "--model", "x"])
        mock_help.assert_not_called()
