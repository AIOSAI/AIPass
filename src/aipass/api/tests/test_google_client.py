# =================== AIPass ====================
# Name: test_google_client.py
# Description: Tests for Google API client module
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Tests for google_client.py — Google API Client Module.

Tests:
- handle_command routing: help, introspection, validate, reauth, pass-through
- get_drive_service() delegates to get_google_service()
- get_google_service() standard and thread-safe paths
- get_google_service() error paths: libs missing, auth failure
- validate_google() success and failure
- authenticate_google() success and failure
- reauth_google() success and failure
- api_call_with_retry() delegation
- is_ssl_error() delegation
"""

from unittest.mock import patch, MagicMock, call

import pytest

from aipass.api.apps.modules.google_client import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection


# Base patch path for all mocks in this module
_MOD = "aipass.api.apps.modules.google_client"


# =============================================
# handle_command tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_returns_false_no_args(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, _console
):
    """handle_command returns False when args=[] and command != 'google'."""
    from aipass.api.apps.modules import google_client

    result = google_client.handle_command("validate", [])
    assert result is False


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_returns_false_non_google_provider(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, _console
):
    """handle_command returns False when provider is not 'google'."""
    from aipass.api.apps.modules import google_client

    result = google_client.handle_command("validate", ["openrouter"])
    assert result is False


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_routes_validate_google(
    _warn, _err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, _console
):
    """handle_command routes 'validate' with ['google'] to _cmd_validate."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.validate_credentials.return_value = True

    result = google_client.handle_command("validate", ["google"])

    assert result is True
    mock_auth.validate_credentials.assert_called_once()


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_routes_reauth_google(
    mock_warn, _err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, _console
):
    """handle_command routes 'reauth' with ['google'] to _cmd_reauth."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.reauth.return_value = MagicMock()

    result = google_client.handle_command("reauth", ["google"])

    assert result is True
    mock_auth.reauth.assert_called_once()


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_help_gate(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, mock_console
):
    """handle_command prints help when args=['--help'] and returns True."""
    from aipass.api.apps.modules import google_client

    result = google_client.handle_command("validate", ["--help"])

    assert result is True
    # print_help calls console.print with the argparse output
    mock_console.print.assert_called()


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_google_introspection(
    _warn, _err, _succ, mock_hdr, _json, _retry, _factory, mock_auth, mock_console
):
    """handle_command prints introspection when command='google' and args=[]."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CREDS_PATH.exists.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True

    result = google_client.handle_command("google", [])

    assert result is True
    mock_hdr.assert_called_once_with("Google Client Module Introspection")


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_unknown_command_returns_false(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, _console
):
    """handle_command returns False for unknown commands with 'google' arg."""
    from aipass.api.apps.modules import google_client

    result = google_client.handle_command("deploy", ["google"])
    assert result is False


# =============================================
# get_drive_service tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_drive_service_delegates(
    _warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console
):
    """get_drive_service() delegates to get_google_service('drive', 'v3')."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_service = MagicMock()
    mock_factory.build_service.return_value = mock_service

    result = google_client.get_drive_service()

    mock_factory.build_service.assert_called_once_with("drive", "v3", None)
    assert result is mock_service


# =============================================
# get_google_service tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_standard(
    _warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console
):
    """get_google_service() returns service via build_service when is_available=True."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_service = MagicMock()
    mock_factory.build_service.return_value = mock_service

    result = google_client.get_google_service("calendar", "v3")

    mock_factory.build_service.assert_called_once_with("calendar", "v3", None)
    assert result is mock_service


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_thread_safe(
    _warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console
):
    """get_google_service(thread_safe=True) calls build_thread_safe_service."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_service = MagicMock()
    mock_factory.build_thread_safe_service.return_value = mock_service

    result = google_client.get_google_service("drive", "v3", thread_safe=True)

    mock_factory.build_thread_safe_service.assert_called_once_with("drive", "v3", None)
    assert result is mock_service


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_libs_not_available(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """get_google_service() raises RuntimeError when libraries are not installed."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = False

    with pytest.raises(RuntimeError, match="not installed"):
        google_client.get_google_service()


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_auth_failure(
    _warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console
):
    """get_google_service() raises RuntimeError when build_service returns None."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_factory.build_service.return_value = None

    with pytest.raises(RuntimeError, match="Failed to authenticate"):
        google_client.get_google_service("drive", "v3")


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_with_custom_scopes(
    _warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console
):
    """get_google_service() passes custom scopes through to build_service."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_service = MagicMock()
    mock_factory.build_service.return_value = mock_service
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]

    result = google_client.get_google_service("drive", "v3", scopes=scopes)

    mock_factory.build_service.assert_called_once_with("drive", "v3", scopes)
    assert result is mock_service


# =============================================
# validate_google tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_validate_google_true(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """validate_google() returns True when credentials are valid."""
    from aipass.api.apps.modules import google_client

    mock_auth.validate_credentials.return_value = True

    result = google_client.validate_google()

    assert result is True
    mock_auth.validate_credentials.assert_called_once_with(scopes=None)


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_validate_google_false(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """validate_google() returns False when no valid credentials exist."""
    from aipass.api.apps.modules import google_client

    mock_auth.validate_credentials.return_value = False

    result = google_client.validate_google()

    assert result is False


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_validate_google_with_scopes(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """validate_google() passes scopes to validate_credentials."""
    from aipass.api.apps.modules import google_client

    mock_auth.validate_credentials.return_value = True
    scopes = ["https://www.googleapis.com/auth/calendar"]

    result = google_client.validate_google(scopes=scopes)

    assert result is True
    mock_auth.validate_credentials.assert_called_once_with(scopes=scopes)


# =============================================
# authenticate_google tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_authenticate_google_success(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """authenticate_google() returns True when authenticate returns credentials."""
    from aipass.api.apps.modules import google_client

    mock_auth.authenticate.return_value = MagicMock()

    result = google_client.authenticate_google()

    assert result is True
    mock_auth.authenticate.assert_called_once_with(scopes=None)


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_authenticate_google_failure(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """authenticate_google() returns False when authenticate returns None."""
    from aipass.api.apps.modules import google_client

    mock_auth.authenticate.return_value = None

    result = google_client.authenticate_google()

    assert result is False


# =============================================
# reauth_google tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_reauth_google_success(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """reauth_google() returns True when reauth returns credentials."""
    from aipass.api.apps.modules import google_client

    mock_auth.reauth.return_value = MagicMock()

    result = google_client.reauth_google()

    assert result is True
    mock_auth.reauth.assert_called_once_with(scopes=None)


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_reauth_google_failure(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """reauth_google() returns False when reauth returns None."""
    from aipass.api.apps.modules import google_client

    mock_auth.reauth.return_value = None

    result = google_client.reauth_google()

    assert result is False


# =============================================
# api_call_with_retry tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_api_call_with_retry_delegates(
    _warn, _err, _succ, _hdr, _json, mock_retry, _factory, _auth, _console
):
    """api_call_with_retry() delegates to google_retry.api_call_with_retry."""
    from aipass.api.apps.modules import google_client

    mock_callable = MagicMock()
    mock_retry.api_call_with_retry.return_value = "result"

    result = google_client.api_call_with_retry(mock_callable, retries=3)

    mock_retry.api_call_with_retry.assert_called_once_with(mock_callable, retries=3)
    assert result == "result"


# =============================================
# is_ssl_error tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_is_ssl_error_delegates(
    _warn, _err, _succ, _hdr, _json, mock_retry, _factory, _auth, _console
):
    """is_ssl_error() delegates to google_retry.is_ssl_error."""
    from aipass.api.apps.modules import google_client

    test_error = Exception("SSL handshake failed")
    mock_retry.is_ssl_error.return_value = True

    result = google_client.is_ssl_error(test_error)

    mock_retry.is_ssl_error.assert_called_once_with(test_error)
    assert result is True


# =============================================
# _cmd_validate CLI integration tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_libs_not_available(
    _warn, mock_err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """_cmd_validate shows error when Google libs are not installed."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = False

    google_client._cmd_validate()

    mock_err.assert_called_once()
    assert "not installed" in mock_err.call_args[0][0]


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_no_client_secret(
    _warn, mock_err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """_cmd_validate shows error when client secret file is missing."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = False

    google_client._cmd_validate()

    mock_err.assert_called_once()
    assert "Client secret not found" in mock_err.call_args[0][0]


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_valid_creds(
    _warn, _err, mock_succ, _hdr, mock_json, _retry, _factory, mock_auth, _console
):
    """_cmd_validate shows success when credentials are valid."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.validate_credentials.return_value = True

    google_client._cmd_validate()

    mock_succ.assert_called_once_with("Google credentials are valid")
    mock_json.log_operation.assert_called_once_with(
        "google_validate", {"status": "valid"}
    )
    _err.assert_not_called()


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_invalid_creds(
    mock_warn, _err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, mock_console
):
    """_cmd_validate shows warning when credentials are invalid."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.validate_credentials.return_value = False

    google_client._cmd_validate()

    mock_warn.assert_called_once_with("No valid Google credentials found")
    mock_json.log_operation.assert_called_once_with(
        "google_validate", {"status": "invalid"}
    )
    _succ.assert_not_called()


# =============================================
# _cmd_reauth CLI integration tests
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_reauth_libs_not_available(
    _warn, mock_err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """_cmd_reauth shows error when Google libs are not installed."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = False

    google_client._cmd_reauth()

    mock_err.assert_called_once()
    assert "not installed" in mock_err.call_args[0][0]


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_reauth_success(
    _warn, _err, mock_succ, _hdr, mock_json, _retry, _factory, mock_auth, _console
):
    """_cmd_reauth shows success when reauth returns credentials."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.reauth.return_value = MagicMock()

    google_client._cmd_reauth()

    mock_succ.assert_called_once_with("Google re-authentication successful")
    mock_json.log_operation.assert_called_once_with(
        "google_reauth", {"status": "success"}
    )
    _err.assert_not_called()


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_reauth_failure(
    _warn, mock_err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, _console
):
    """_cmd_reauth shows error when reauth returns None."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.reauth.return_value = None

    google_client._cmd_reauth()

    mock_err.assert_called_once_with("Google re-authentication failed")
    mock_json.log_operation.assert_called_once_with(
        "google_reauth", {"status": "failed"}
    )
    _succ.assert_not_called()


# =============================================
# handle_command — exception propagation
# =============================================


@patch(f"{_MOD}.console")
@patch(f"{_MOD}.google_auth")
@patch(f"{_MOD}.google_factory")
@patch(f"{_MOD}.google_retry")
@patch(f"{_MOD}.json_handler")
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_propagates_exception(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console
):
    """handle_command re-raises exceptions from downstream handlers."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.side_effect = RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        google_client.handle_command("validate", ["google"])
