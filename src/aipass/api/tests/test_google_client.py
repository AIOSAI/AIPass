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

from unittest.mock import patch, MagicMock

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
def test_handle_command_returns_false_no_args(_warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, _console):
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
def test_handle_command_help_gate(_warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, mock_console):
    """handle_command prints help when args=['google', '--help'] and returns True."""
    from aipass.api.apps.modules import google_client

    result = google_client.handle_command("validate", ["google", "--help"])

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
def test_get_drive_service_delegates(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console):
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
def test_get_google_service_standard(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console):
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
def test_get_google_service_thread_safe(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console):
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
def test_get_google_service_libs_not_available(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_get_google_service_auth_failure(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth, _console):
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
def test_validate_google_true(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_validate_google_false(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_validate_google_with_scopes(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_authenticate_google_success(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_authenticate_google_failure(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_reauth_google_success(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_reauth_google_failure(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_api_call_with_retry_delegates(_warn, _err, _succ, _hdr, _json, mock_retry, _factory, _auth, _console):
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
def test_is_ssl_error_delegates(_warn, _err, _succ, _hdr, _json, mock_retry, _factory, _auth, _console):
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
def test_cmd_validate_libs_not_available(_warn, mock_err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_cmd_validate_no_client_secret(_warn, mock_err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_cmd_validate_valid_creds(_warn, _err, mock_succ, _hdr, mock_json, _retry, _factory, mock_auth, _console):
    """_cmd_validate shows success when credentials are valid."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.validate_credentials.return_value = True

    google_client._cmd_validate()

    mock_succ.assert_called_once_with("Google credentials are valid")
    mock_json.log_operation.assert_called_once_with("google_validate", {"status": "valid"})
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
def test_cmd_validate_invalid_creds(mock_warn, _err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, mock_console):
    """_cmd_validate shows warning when credentials are invalid."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.validate_credentials.return_value = False

    google_client._cmd_validate()

    mock_warn.assert_called_once_with("No valid Google credentials found")
    mock_json.log_operation.assert_called_once_with("google_validate", {"status": "invalid"})
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
def test_cmd_reauth_libs_not_available(_warn, mock_err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
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
def test_cmd_reauth_success(_warn, _err, mock_succ, _hdr, mock_json, _retry, _factory, mock_auth, _console):
    """_cmd_reauth shows success when reauth returns credentials."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.reauth.return_value = MagicMock()

    google_client._cmd_reauth()

    mock_succ.assert_called_once_with("Google re-authentication successful")
    mock_json.log_operation.assert_called_once_with("google_reauth", {"status": "success"})
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
def test_cmd_reauth_failure(_warn, mock_err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, _console):
    """_cmd_reauth shows error when reauth returns None."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.return_value = True
    mock_auth.CLIENT_SECRET_PATH.exists.return_value = True
    mock_auth.reauth.return_value = None

    google_client._cmd_reauth()

    mock_err.assert_called_once_with("Google re-authentication failed")
    mock_json.log_operation.assert_called_once_with("google_reauth", {"status": "failed"})
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
def test_handle_command_propagates_exception(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, _console):
    """handle_command re-raises exceptions from downstream handlers."""
    from aipass.api.apps.modules import google_client

    mock_auth.is_available.side_effect = RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        google_client.handle_command("validate", ["google"])


# =============================================
# auth.py — load_credentials tests
# =============================================

# Base patch path for auth module
_AUTH = "aipass.api.apps.handlers.google.auth"


@patch(f"{_AUTH}.json_handler")
@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.CREDS_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_success(mock_creds_path, mock_creds_cls, mock_json):
    """load_credentials() returns Credentials when file exists and loads ok."""
    from aipass.api.apps.handlers.google.auth import load_credentials

    mock_creds_path.exists.return_value = True
    mock_creds_obj = MagicMock()
    mock_creds_cls.from_authorized_user_file.return_value = mock_creds_obj

    result = load_credentials()

    assert result is mock_creds_obj
    mock_creds_cls.from_authorized_user_file.assert_called_once_with(
        str(mock_creds_path),
        ["https://www.googleapis.com/auth/drive.file"],
    )
    mock_json.log_operation.assert_called_once_with("credentials_loaded", {"source": str(mock_creds_path)})


@patch(f"{_AUTH}.json_handler")
@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.CREDS_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_custom_scopes(mock_creds_path, mock_creds_cls, mock_json):
    """load_credentials() uses custom scopes when provided."""
    from aipass.api.apps.handlers.google.auth import load_credentials

    mock_creds_path.exists.return_value = True
    custom_scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    mock_creds_cls.from_authorized_user_file.return_value = MagicMock()

    load_credentials(scopes=custom_scopes)

    mock_creds_cls.from_authorized_user_file.assert_called_once_with(
        str(mock_creds_path),
        custom_scopes,
    )


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", False)
def test_load_credentials_libs_unavailable():
    """load_credentials() returns None when Google libs are not installed."""
    from aipass.api.apps.handlers.google.auth import load_credentials

    result = load_credentials()

    assert result is None


@patch(f"{_AUTH}.CREDS_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_no_file(mock_creds_path):
    """load_credentials() returns None when creds file does not exist."""
    from aipass.api.apps.handlers.google.auth import load_credentials

    mock_creds_path.exists.return_value = False

    result = load_credentials()

    assert result is None


@patch(f"{_AUTH}.logger")
@patch(f"{_AUTH}.json_handler")
@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.CREDS_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_exception(mock_creds_path, mock_creds_cls, mock_json, mock_logger):
    """load_credentials() returns None and logs error on exception."""
    from aipass.api.apps.handlers.google.auth import load_credentials

    mock_creds_path.exists.return_value = True
    mock_creds_cls.from_authorized_user_file.side_effect = ValueError("corrupt file")

    result = load_credentials()

    assert result is None
    mock_logger.error.assert_called_once()
    mock_json.log_operation.assert_not_called()


# =============================================
# auth.py — refresh_credentials tests
# =============================================


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.Request")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_success(mock_request_cls, mock_save):
    """refresh_credentials() returns True and saves when refresh succeeds."""
    from aipass.api.apps.handlers.google.auth import refresh_credentials

    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = "tok_refresh"

    result = refresh_credentials(mock_creds)

    assert result is True
    mock_creds.refresh.assert_called_once_with(mock_request_cls())
    mock_save.assert_called_once_with(mock_creds)


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", False)
def test_refresh_credentials_libs_unavailable():
    """refresh_credentials() returns False when Google libs are not installed."""
    from aipass.api.apps.handlers.google.auth import refresh_credentials

    result = refresh_credentials(MagicMock())

    assert result is False


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_none_creds():
    """refresh_credentials() returns False when creds is None."""
    from aipass.api.apps.handlers.google.auth import refresh_credentials

    result = refresh_credentials(None)

    assert result is False


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_not_expired():
    """refresh_credentials() returns False when creds are not expired."""
    from aipass.api.apps.handlers.google.auth import refresh_credentials

    mock_creds = MagicMock()
    mock_creds.expired = False
    mock_creds.refresh_token = "tok_refresh"

    result = refresh_credentials(mock_creds)

    assert result is False


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_no_refresh_token():
    """refresh_credentials() returns False when no refresh token exists."""
    from aipass.api.apps.handlers.google.auth import refresh_credentials

    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = None

    result = refresh_credentials(mock_creds)

    assert result is False


@patch(f"{_AUTH}.logger")
@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.Request")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_exception(mock_request_cls, mock_save, mock_logger):
    """refresh_credentials() returns False on refresh exception."""
    from aipass.api.apps.handlers.google.auth import refresh_credentials

    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = "tok_refresh"
    mock_creds.refresh.side_effect = RuntimeError("network error")

    result = refresh_credentials(mock_creds)

    assert result is False
    mock_save.assert_not_called()
    mock_logger.error.assert_called_once()


# =============================================
# auth.py — run_oauth_flow tests
# =============================================


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.InstalledAppFlow")
@patch(f"{_AUTH}.CLIENT_SECRET_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_success(mock_secret_path, mock_flow_cls, mock_save):
    """run_oauth_flow() returns credentials after successful OAuth flow."""
    from aipass.api.apps.handlers.google.auth import run_oauth_flow, DEFAULT_SCOPES

    mock_secret_path.exists.return_value = True
    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_flow_cls.from_client_secrets_file.return_value = mock_flow
    mock_flow.run_local_server.return_value = mock_creds

    result = run_oauth_flow()

    assert result is mock_creds
    mock_flow_cls.from_client_secrets_file.assert_called_once_with(
        str(mock_secret_path),
        DEFAULT_SCOPES["drive"],
    )
    mock_flow.run_local_server.assert_called_once_with(port=0, open_browser=True)
    mock_save.assert_called_once_with(mock_creds)


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.InstalledAppFlow")
@patch(f"{_AUTH}.CLIENT_SECRET_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_custom_params(mock_secret_path, mock_flow_cls, mock_save):
    """run_oauth_flow() passes custom scopes, port, and open_browser."""
    from aipass.api.apps.handlers.google.auth import run_oauth_flow

    mock_secret_path.exists.return_value = True
    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_flow_cls.from_client_secrets_file.return_value = mock_flow
    mock_flow.run_local_server.return_value = mock_creds
    custom_scopes = ["https://www.googleapis.com/auth/calendar"]

    result = run_oauth_flow(scopes=custom_scopes, port=8085, open_browser=False)

    assert result is mock_creds
    mock_flow_cls.from_client_secrets_file.assert_called_once_with(
        str(mock_secret_path),
        custom_scopes,
    )
    mock_flow.run_local_server.assert_called_once_with(port=8085, open_browser=False)


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", False)
def test_run_oauth_flow_libs_unavailable():
    """run_oauth_flow() returns None when Google libs are not installed."""
    from aipass.api.apps.handlers.google.auth import run_oauth_flow

    result = run_oauth_flow()

    assert result is None


@patch(f"{_AUTH}.CLIENT_SECRET_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_no_client_secret(mock_secret_path):
    """run_oauth_flow() returns None when client secret file is missing."""
    from aipass.api.apps.handlers.google.auth import run_oauth_flow

    mock_secret_path.exists.return_value = False

    result = run_oauth_flow()

    assert result is None


@patch(f"{_AUTH}.logger")
@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.InstalledAppFlow")
@patch(f"{_AUTH}.CLIENT_SECRET_PATH")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_exception(mock_secret_path, mock_flow_cls, mock_save, mock_logger):
    """run_oauth_flow() returns None and logs error on exception."""
    from aipass.api.apps.handlers.google.auth import run_oauth_flow

    mock_secret_path.exists.return_value = True
    mock_flow_cls.from_client_secrets_file.side_effect = OSError("bad secret file")

    result = run_oauth_flow()

    assert result is None
    mock_save.assert_not_called()
    mock_logger.error.assert_called_once()
