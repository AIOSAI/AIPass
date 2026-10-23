# =================== AIPass ====================
# Name: test_google_client.py
# Description: Tests for Google API client module
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-10-22
# =============================================

"""Tests for apps/modules/google_client.py and the apps/handlers/google/auth.py it drives."""

# Tests for google_client.py — Google API Client Module.
#
# Tests:
# - handle_command routing: help, introspection, validate, reauth, pass-through
# - get_drive_service() delegates to get_google_service()
# - get_google_service() standard and thread-safe paths
# - get_google_service() error paths: libs missing, auth failure
# - validate_google() success and failure
# - authenticate_google() success and failure
# - reauth_google() success and failure
# - api_call_with_retry() delegation
# - is_ssl_error() delegation

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — build_service() and its thread-safe twin, tests/test_service_factory_handler.py
# seedgo: no-test-needed(covered) — the backoff behind api_call_with_retry(), tests/test_retry_handler.py

import json
from unittest.mock import patch, MagicMock

import pytest
from keyring.errors import KeyringLocked

from aipass.api.apps.handlers.google.auth import DEFAULT_SCOPES, load_credentials, refresh_credentials, run_oauth_flow
from aipass.api.apps.modules import google_client
from aipass.api.apps.modules.google_client import handle_command as _hc  # noqa: F401 — seedgo test_coverage detection


# Base patch path for all mocks in this module
_MOD = "aipass.api.apps.modules.google_client"
IMPORT_HINT = "Put google_client_secret.json in the store, then run: drone @api secrets migrate"
CREDS_DOC = {"token": "gtok-fixture", "refresh_token": "gref-fixture", "client_id": "cid", "client_secret": "cs"}
CLIENT_DOC = {"installed": {"client_id": "cid-fixture", "client_secret": "cs-fixture"}}


# =============================================
# handle_command tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_returns_false_no_args(_warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, capsys):
    """handle_command returns False when args=[] and command != 'google'."""
    result = google_client.handle_command("validate", [])
    assert result is False
    assert capsys.readouterr().out == ""


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_returns_false_non_google_provider(
    _warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, capsys
):
    """handle_command returns False when provider is not 'google'."""
    result = google_client.handle_command("validate", ["openrouter"])
    assert result is False
    assert capsys.readouterr().out == ""


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_routes_reauth_google(
    mock_warn, _err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, capsys
):
    """handle_command routes 'reauth' with ['google'] to _cmd_reauth."""
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = True
    mock_auth.reauth.return_value = MagicMock()

    result = google_client.handle_command("reauth", ["google"])

    assert result is True
    mock_auth.reauth.assert_called_once()
    assert "A browser window may open for Google consent." in capsys.readouterr().out


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_help_gate(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth, capsys):
    """handle_command prints help when args=['google', '--help'] and returns True."""
    result = google_client.handle_command("validate", ["google", "--help"])

    assert result is True
    out = capsys.readouterr().out
    assert "GOOGLE_CLIENT — Google API authentication and service access" in out
    assert "reauth google" in out
    mock_auth.validate_credentials.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_google_introspection(_warn, _err, _succ, mock_hdr, _json, _retry, _factory, mock_auth, capsys):
    """handle_command prints introspection when command='google' and args=[]."""
    mock_auth.is_available.return_value = True
    mock_auth.has_credentials.return_value = True
    mock_auth.has_client_secret.return_value = True

    result = google_client.handle_command("google", [])

    assert result is True
    mock_hdr.assert_called_once_with("Google Client Module Introspection")
    out = capsys.readouterr().out
    assert "Google Libraries: installed" in out
    assert "Credentials: found" in out
    assert "Client Secret: found" in out


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_unknown_command_returns_false(_warn, _err, _succ, _hdr, _json, _retry, _factory, _auth, capsys):
    """handle_command returns False for unknown commands with 'google' arg."""
    result = google_client.handle_command("deploy", ["google"])
    assert result is False
    assert capsys.readouterr().out == ""


# =============================================
# get_drive_service tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_drive_service_delegates(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth):
    """get_drive_service() delegates to get_google_service('drive', 'v3')."""
    mock_auth.is_available.return_value = True
    mock_service = MagicMock()
    mock_factory.build_service.return_value = mock_service

    result = google_client.get_drive_service()

    mock_factory.build_service.assert_called_once_with("drive", "v3", None)
    assert result is mock_service


# =============================================
# get_google_service tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_standard(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth):
    """get_google_service() returns service via build_service when is_available=True."""
    mock_auth.is_available.return_value = True
    mock_service = MagicMock()
    mock_factory.build_service.return_value = mock_service

    result = google_client.get_google_service("calendar", "v3")

    mock_factory.build_service.assert_called_once_with("calendar", "v3", None)
    assert result is mock_service


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_thread_safe(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth):
    """get_google_service(thread_safe=True) calls build_thread_safe_service."""
    mock_auth.is_available.return_value = True
    mock_service = MagicMock()
    mock_factory.build_thread_safe_service.return_value = mock_service

    result = google_client.get_google_service("drive", "v3", thread_safe=True)

    mock_factory.build_thread_safe_service.assert_called_once_with("drive", "v3", None)
    assert result is mock_service


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_libs_not_available(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """get_google_service() raises RuntimeError when libraries are not installed."""
    mock_auth.is_available.return_value = False

    with pytest.raises(RuntimeError, match="not installed"):
        google_client.get_google_service()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_auth_failure(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth):
    """get_google_service() raises RuntimeError when build_service returns None."""
    mock_auth.is_available.return_value = True
    mock_factory.build_service.return_value = None

    with pytest.raises(RuntimeError, match="Failed to authenticate"):
        google_client.get_google_service("drive", "v3")


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_get_google_service_with_custom_scopes(_warn, _err, _succ, _hdr, _json, _retry, mock_factory, mock_auth):
    """get_google_service() passes custom scopes through to build_service."""
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


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_validate_google_true(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """validate_google() returns True when credentials are valid."""
    mock_auth.validate_credentials.return_value = True

    result = google_client.validate_google()

    assert result is True
    mock_auth.validate_credentials.assert_called_once_with(scopes=None)


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_validate_google_false(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """validate_google() returns False when no valid credentials exist."""
    mock_auth.validate_credentials.return_value = False

    result = google_client.validate_google()

    assert result is False


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_validate_google_with_scopes(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """validate_google() passes scopes to validate_credentials."""
    mock_auth.validate_credentials.return_value = True
    scopes = ["https://www.googleapis.com/auth/calendar"]

    result = google_client.validate_google(scopes=scopes)

    assert result is True
    mock_auth.validate_credentials.assert_called_once_with(scopes=scopes)


# =============================================
# authenticate_google tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_authenticate_google_success(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """authenticate_google() returns True when authenticate returns credentials."""
    mock_auth.authenticate.return_value = MagicMock()

    result = google_client.authenticate_google()

    assert result is True
    mock_auth.authenticate.assert_called_once_with(scopes=None)


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_authenticate_google_failure(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """authenticate_google() returns False when authenticate returns None."""
    mock_auth.authenticate.return_value = None

    result = google_client.authenticate_google()

    assert result is False


# =============================================
# reauth_google tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_reauth_google_success(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """reauth_google() returns True when reauth returns credentials."""
    mock_auth.reauth.return_value = MagicMock()

    result = google_client.reauth_google()

    assert result is True
    mock_auth.reauth.assert_called_once_with(scopes=None)


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_reauth_google_failure(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """reauth_google() returns False when reauth returns None."""
    mock_auth.reauth.return_value = None

    result = google_client.reauth_google()

    assert result is False


# =============================================
# api_call_with_retry tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_api_call_with_retry_delegates(_warn, _err, _succ, _hdr, _json, mock_retry, _factory, _auth):
    """
    api_call_with_retry() delegates to google_retry.api_call_with_retry.

    The keyword is max_retries, and this test said `retries` until 2026-09-07.
    It passed for years because the module patch was an unspecced MagicMock
    that accepts any signature: the wrapper is *args/**kwargs, so nothing
    between the test and the real function ever checked the name. Under
    autospec it raises TypeError, which is the drift seedgo's mock_drift rule
    exists to surface — the test was documenting a parameter production does
    not have, and anyone who copied it would have written a TypeError.
    """
    mock_callable = MagicMock()
    mock_retry.api_call_with_retry.return_value = "result"

    result = google_client.api_call_with_retry(mock_callable, max_retries=3)

    mock_retry.api_call_with_retry.assert_called_once_with(mock_callable, max_retries=3)
    assert result == "result"


# =============================================
# is_ssl_error tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_is_ssl_error_delegates(_warn, _err, _succ, _hdr, _json, mock_retry, _factory, _auth):
    """is_ssl_error() delegates to google_retry.is_ssl_error."""
    test_error = Exception("SSL handshake failed")
    mock_retry.is_ssl_error.return_value = True

    result = google_client.is_ssl_error(test_error)

    mock_retry.is_ssl_error.assert_called_once_with(test_error)
    assert result is True


# =============================================
# _cmd_validate CLI integration tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_libs_not_available(_warn, mock_err, _succ, mock_hdr, mock_json, _retry, _factory, mock_auth):
    """validate google shows error when Google libs are not installed."""
    mock_auth.is_available.return_value = False

    assert google_client.handle_command("validate", ["google"]) is True

    mock_hdr.assert_called_once_with("Validate Google Credentials")
    mock_err.assert_called_once_with(
        "Google auth libraries not installed",
        suggestion="pip install google-auth google-auth-oauthlib google-api-python-client",
    )
    mock_auth.validate_credentials.assert_not_called()
    mock_json.log_operation.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_no_client_secret(_warn, mock_err, _succ, _hdr, mock_json, _retry, _factory, mock_auth):
    """validate google shows error when client secret file is missing."""
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = False

    assert google_client.handle_command("validate", ["google"]) is True

    mock_err.assert_called_once_with(
        "Client secret not found",
        suggestion=IMPORT_HINT,
    )
    mock_auth.validate_credentials.assert_not_called()
    mock_json.log_operation.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_valid_creds(_warn, _err, mock_succ, _hdr, mock_json, _retry, _factory, mock_auth):
    """validate google shows success when credentials are valid."""
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = True
    mock_auth.validate_credentials.return_value = True

    assert google_client.handle_command("validate", ["google"]) is True

    # Took over from the retired test_handle_command_routes_validate_google (api, fleet green leg 4).
    mock_auth.validate_credentials.assert_called_once_with()
    mock_succ.assert_called_once_with("Google credentials are valid")
    mock_json.log_operation.assert_called_once_with("google_validate", {"status": "valid"})
    _err.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_invalid_creds(mock_warn, _err, _succ, _hdr, mock_json, _retry, _factory, mock_auth, capsys):
    """validate google shows warning and the reauth hint when credentials are invalid."""
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = True
    mock_auth.validate_credentials.return_value = False

    assert google_client.handle_command("validate", ["google"]) is True

    mock_warn.assert_called_once_with("No valid Google credentials found")
    assert "Run 'drone @api reauth google' to authenticate" in capsys.readouterr().out
    mock_json.log_operation.assert_called_once_with("google_validate", {"status": "invalid"})
    _succ.assert_not_called()


# =============================================
# _cmd_reauth CLI integration tests
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_reauth_libs_not_available(_warn, mock_err, _succ, mock_hdr, mock_json, _retry, _factory, mock_auth):
    """reauth google shows error when Google libs are not installed."""
    mock_auth.is_available.return_value = False

    assert google_client.handle_command("reauth", ["google"]) is True

    mock_hdr.assert_called_once_with("Google Re-Authentication")
    mock_err.assert_called_once_with(
        "Google auth libraries not installed",
        suggestion="pip install google-auth google-auth-oauthlib google-api-python-client",
    )
    mock_auth.reauth.assert_not_called()
    mock_json.log_operation.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_reauth_success(mock_warn, _err, mock_succ, _hdr, mock_json, _retry, _factory, mock_auth, capsys):
    """reauth google shows success when reauth returns credentials."""
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = True
    mock_auth.reauth.return_value = MagicMock()

    assert google_client.handle_command("reauth", ["google"]) is True

    mock_warn.assert_called_once_with("Starting OAuth2 flow...")
    mock_succ.assert_called_once_with("Google re-authentication successful")
    assert "Credentials saved to the entry google/creds" in capsys.readouterr().out
    mock_json.log_operation.assert_called_once_with("google_reauth", {"status": "success"})
    _err.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_reauth_failure(_warn, mock_err, _succ, _hdr, mock_json, _retry, _factory, mock_auth):
    """reauth google shows error when reauth returns None."""
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = True
    mock_auth.reauth.return_value = None

    assert google_client.handle_command("reauth", ["google"]) is True

    mock_err.assert_called_once_with("Google re-authentication failed")
    mock_json.log_operation.assert_called_once_with("google_reauth", {"status": "failed"})
    _succ.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_reauth_shows_the_flow_reason(_warn, mock_err, _succ, _hdr, mock_json, _retry, _factory, mock_auth):
    """reauth google shows the consent flow's own reason."""
    mock_auth.GoogleAuthUnavailable = _GOOGLE_UNAVAILABLE
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = True
    mock_auth.reauth.side_effect = _GOOGLE_UNAVAILABLE("Google OAuth flow failed: port in use")

    assert google_client.handle_command("reauth", ["google"]) is True

    mock_err.assert_called_once_with("Google OAuth flow failed: port in use")
    mock_json.log_operation.assert_called_once_with("google_reauth", {"status": "failed"})
    _succ.assert_not_called()


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_cmd_validate_shows_the_reason(mock_warn, mock_err, _succ, _hdr, mock_json, _retry, _factory, mock_auth):
    """validate google names an unreadable file or a failed refresh instead of "invalid"."""
    mock_auth.GoogleAuthUnavailable = _GOOGLE_UNAVAILABLE
    mock_auth.is_available.return_value = True
    mock_auth.has_client_secret.return_value = True
    mock_auth.validate_credentials.side_effect = _GOOGLE_UNAVAILABLE("Google credential refresh failed: offline")

    assert google_client.handle_command("validate", ["google"]) is True

    mock_err.assert_called_once_with(
        "Google credential refresh failed: offline", suggestion="Run 'drone @api reauth google' to authenticate"
    )
    mock_json.log_operation.assert_called_once_with("google_validate", {"status": "unavailable"})
    mock_warn.assert_not_called()
    _succ.assert_not_called()


# =============================================
# handle_command — exception propagation
# =============================================


@patch(f"{_MOD}.google_auth", autospec=True)
@patch(f"{_MOD}.google_factory", autospec=True)
@patch(f"{_MOD}.google_retry", autospec=True)
@patch(f"{_MOD}.json_handler", autospec=True)
@patch(f"{_MOD}.header")
@patch(f"{_MOD}.success")
@patch(f"{_MOD}.error")
@patch(f"{_MOD}.warning")
def test_handle_command_propagates_exception(_warn, _err, _succ, _hdr, _json, _retry, _factory, mock_auth):
    """handle_command re-raises exceptions from downstream handlers."""
    mock_auth.is_available.side_effect = RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        google_client.handle_command("validate", ["google"])


# =============================================
# auth.py — load_credentials tests
# =============================================

# Base patch path for auth module
_AUTH = "aipass.api.apps.handlers.google.auth"
_GOOGLE_UNAVAILABLE = google_client.google_auth.GoogleAuthUnavailable


@patch(f"{_AUTH}.json_handler", autospec=True)
@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_come_from_the_creds_entry(mock_creds_cls, mock_json, keyring_store):
    """load_credentials() builds Credentials from the entry google/creds, never a file."""
    keyring_store.set_password("aipass", "google/creds", json.dumps(CREDS_DOC))
    mock_creds_obj = MagicMock()
    mock_creds_cls.from_authorized_user_info.return_value = mock_creds_obj

    result = load_credentials()

    assert result is mock_creds_obj
    mock_creds_cls.from_authorized_user_info.assert_called_once_with(
        CREDS_DOC,
        ["https://www.googleapis.com/auth/drive.file"],
    )
    mock_json.log_operation.assert_called_once_with("credentials_loaded", {"source": "google/creds"})


@patch(f"{_AUTH}.json_handler", autospec=True)
@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_custom_scopes(mock_creds_cls, mock_json, keyring_store):
    """load_credentials() uses custom scopes when provided."""
    keyring_store.set_password("aipass", "google/creds", json.dumps(CREDS_DOC))
    custom_scopes = ["https://www.googleapis.com/auth/calendar.readonly"]

    load_credentials(scopes=custom_scopes)

    mock_creds_cls.from_authorized_user_info.assert_called_once_with(CREDS_DOC, custom_scopes)


@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", False)
def test_load_credentials_libs_unavailable(mock_creds_cls, keyring_store):
    """load_credentials() returns None without reading the entry when Google libs are not installed."""
    with patch.object(keyring_store, "get_password") as read:
        assert load_credentials() is None

    read.assert_not_called()
    mock_creds_cls.from_authorized_user_info.assert_not_called()


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_no_entry():
    """load_credentials() returns None when the entry google/creds does not exist."""
    assert load_credentials() is None


@patch(f"{_AUTH}.json_handler", autospec=True)
@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_load_credentials_exception(mock_creds_cls, mock_json, keyring_store):
    """An entry that does not load raises GoogleAuthUnavailable with the reason, never None."""
    keyring_store.set_password("aipass", "google/creds", json.dumps(CREDS_DOC))
    mock_creds_cls.from_authorized_user_info.side_effect = ValueError("corrupt entry")

    with pytest.raises(_GOOGLE_UNAVAILABLE) as caught:
        load_credentials()

    assert str(caught.value) == "Saved Google credentials could not be loaded: corrupt entry"
    mock_json.log_operation.assert_not_called()


@patch(f"{_AUTH}.Credentials")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_a_locked_keyring_is_a_google_auth_error_for_the_headless_caller(mock_creds_cls, keyring_store):
    """@backup's 05:45 job gets GoogleAuthUnavailable naming the backend, not a consent flow."""
    with patch.object(keyring_store, "get_password", side_effect=KeyringLocked("locked")):
        with pytest.raises(_GOOGLE_UNAVAILABLE) as caught:
            load_credentials()

    assert "DictKeyring" in str(caught.value)


@patch(f"{_AUTH}.Request")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_a_refresh_saves_to_the_creds_entry(mock_request_cls, keyring_store):
    """A refreshed token is written to google/creds through the secrets store, not to a file."""
    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = "tok_refresh"
    mock_creds.to_json.return_value = json.dumps(CREDS_DOC)

    assert refresh_credentials(mock_creds) is True

    assert json.loads(keyring_store.entries[("aipass", "google/creds")]) == CREDS_DOC


# =============================================
# auth.py — refresh_credentials tests
# =============================================


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.Request")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_success(mock_request_cls, mock_save):
    """refresh_credentials() returns True and saves when refresh succeeds."""
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
    result = refresh_credentials(MagicMock())

    assert result is False


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_none_creds():
    """refresh_credentials() returns False when creds is None."""
    result = refresh_credentials(None)

    assert result is False


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_not_expired():
    """refresh_credentials() returns False when creds are not expired."""
    mock_creds = MagicMock()
    mock_creds.expired = False
    mock_creds.refresh_token = "tok_refresh"

    result = refresh_credentials(mock_creds)

    assert result is False


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_no_refresh_token():
    """refresh_credentials() returns False when no refresh token exists."""
    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = None

    result = refresh_credentials(mock_creds)

    assert result is False


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.Request")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_credentials_exception(mock_request_cls, mock_save):
    """A failed refresh raises GoogleAuthUnavailable with the reason.

    It used to answer False, which read the same as "nothing to refresh"
    (api, fleet green leg 10).
    """
    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = "tok_refresh"
    mock_creds.refresh.side_effect = RuntimeError("token revoked")

    with pytest.raises(_GOOGLE_UNAVAILABLE) as caught:
        refresh_credentials(mock_creds)

    assert str(caught.value) == "Google credential refresh failed: token revoked"
    mock_save.assert_not_called()


class _FakeTransportError(Exception):
    """Stands in for google.auth's TransportError, absent where the libraries are."""


@patch(f"{_AUTH}.TransportError", _FakeTransportError)
@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.Request")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_refresh_transport_error_is_named_transient(mock_request_cls, mock_save):
    """A network failure during refresh raises naming itself transient."""
    mock_creds = MagicMock()
    mock_creds.expired = True
    mock_creds.refresh_token = "tok_refresh"
    mock_creds.refresh.side_effect = _FakeTransportError("dns lookup failed")

    with pytest.raises(_GOOGLE_UNAVAILABLE) as caught:
        refresh_credentials(mock_creds)

    assert str(caught.value) == "Google credential refresh failed, transient network error: dns lookup failed"
    mock_save.assert_not_called()


# =============================================
# auth.py — run_oauth_flow tests
# =============================================


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.InstalledAppFlow")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_reads_the_client_config_entry(mock_flow_cls, mock_save, keyring_store):
    """run_oauth_flow() builds the flow from the entry google/client_secret."""
    keyring_store.set_password("aipass", "google/client_secret", json.dumps(CLIENT_DOC))
    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_flow_cls.from_client_config.return_value = mock_flow
    mock_flow.run_local_server.return_value = mock_creds

    result = run_oauth_flow()

    assert result is mock_creds
    mock_flow_cls.from_client_config.assert_called_once_with(CLIENT_DOC, DEFAULT_SCOPES["drive"])
    mock_flow.run_local_server.assert_called_once_with(port=0, open_browser=True)
    mock_save.assert_called_once_with(mock_creds)


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.InstalledAppFlow")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_custom_params(mock_flow_cls, mock_save, keyring_store):
    """run_oauth_flow() passes custom scopes, port, and open_browser."""
    keyring_store.set_password("aipass", "google/client_secret", json.dumps(CLIENT_DOC))
    mock_flow = MagicMock()
    mock_flow_cls.from_client_config.return_value = mock_flow
    custom_scopes = ["https://www.googleapis.com/auth/calendar"]

    run_oauth_flow(scopes=custom_scopes, port=8085, open_browser=False)

    mock_flow_cls.from_client_config.assert_called_once_with(CLIENT_DOC, custom_scopes)
    mock_flow.run_local_server.assert_called_once_with(port=8085, open_browser=False)


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.InstalledAppFlow")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", False)
def test_run_oauth_flow_libs_unavailable(mock_flow_cls, mock_save, keyring_store):
    """run_oauth_flow() returns None without reading the entry when Google libs are not installed."""
    with patch.object(keyring_store, "get_password") as read:
        assert run_oauth_flow() is None

    read.assert_not_called()
    mock_flow_cls.from_client_config.assert_not_called()
    mock_save.assert_not_called()


@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_no_client_secret():
    """run_oauth_flow() returns None when the entry google/client_secret does not exist."""
    assert run_oauth_flow() is None


@patch(f"{_AUTH}._save_credentials")
@patch(f"{_AUTH}.InstalledAppFlow")
@patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
def test_run_oauth_flow_exception(mock_flow_cls, mock_save, keyring_store):
    """A failed consent flow raises GoogleAuthUnavailable with the reason."""
    keyring_store.set_password("aipass", "google/client_secret", json.dumps(CLIENT_DOC))
    mock_flow_cls.from_client_config.side_effect = ValueError("bad client config")

    with pytest.raises(_GOOGLE_UNAVAILABLE) as caught:
        run_oauth_flow()

    assert str(caught.value) == "Google OAuth flow failed: bad client config"
    mock_save.assert_not_called()


def test_the_help_names_the_import_verb_and_no_path(capsys):
    google_client.print_help()

    out = capsys.readouterr().out
    assert "drone @api secrets migrate" in out
    assert ".secrets" not in out
    assert "~/" not in out


@patch(f"{_AUTH}.run_oauth_flow")
@patch(f"{_AUTH}.load_credentials")
def test_reauth_repairs_an_unloadable_file_through_the_flow(mock_load, mock_flow):
    """reauth exists for a corrupt or revoked file: a load that raises still reaches the flow.

    (api, fleet green leg 10)
    """
    mock_load.side_effect = _GOOGLE_UNAVAILABLE("Saved Google credentials could not be loaded: corrupt")
    fresh = MagicMock()
    mock_flow.return_value = fresh

    assert google_client.google_auth.reauth(port=8085, open_browser=False) is fresh
    mock_flow.assert_called_once_with(scopes=None, port=8085, open_browser=False)


def test_the_introspection_reports_each_entry_from_the_store(keyring_store, capsys):
    keyring_store.set_password("aipass", "google/creds", json.dumps(CREDS_DOC))

    assert google_client.handle_command("google", []) is True

    out = capsys.readouterr().out
    assert google_client.google_auth.has_credentials() is True
    assert "Credentials: found" in out
    assert "Client Secret: not configured" in out


def test_the_introspection_names_a_locked_store_as_unavailable(keyring_store, capsys):
    with patch.object(keyring_store, "get_password", side_effect=KeyringLocked("locked")):
        google_client.handle_command("google", [])

    assert "Credentials: unavailable" in capsys.readouterr().out
