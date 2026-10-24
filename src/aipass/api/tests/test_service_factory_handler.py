# =================== AIPass ====================
# Name: test_service_factory_handler.py
# Description: Tests for Google API service factory handler
# Version: 1.0.1
# Created: 2026-05-12
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/google/service_factory.py, the Google API service object factory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — googleapiclient.discovery.build and a live Google service; mocked, no network
# seedgo: no-test-needed(covered_elsewhere) — handlers/google/auth.py credential loading; tests/test_google_client.py

from typing import Any
from unittest.mock import patch, MagicMock

import json

import pytest

from aipass.api.apps.handlers.google.auth import GoogleAuthUnavailable

from aipass.api.apps.handlers.google.service_factory import build_service, build_thread_safe_service

_SF = "aipass.api.apps.handlers.google.service_factory"
_AUTH = "aipass.api.apps.handlers.google.auth"


class TestBuildService:
    """Tests for service_factory.build_service()."""

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", False)
    def test_google_libs_not_available_returns_none(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """Absent libs alone refuse: auth and build would both succeed here."""
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = MagicMock(expired=False, valid=True)

        result = build_service("drive", "v3")

        assert result is None
        mock_build.assert_not_called()

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_auth_not_available_returns_none(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """When auth module reports unavailable, returns None."""
        mock_auth.is_available.return_value = False

        result = build_service("drive", "v3")
        assert result is None

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_no_saved_creds_raises_naming_reauth(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """No usable saved credentials is a refusal naming the reauth door, never a consent flow."""
        mock_auth.GoogleAuthUnavailable = GoogleAuthUnavailable
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = None

        with pytest.raises(GoogleAuthUnavailable, match="drone @api reauth google"):
            build_service("drive", "v3")
        mock_auth.authenticate.assert_not_called()
        mock_auth.run_oauth_flow.assert_not_called()

    @patch(f"{_SF}.build")
    @patch(f"{_AUTH}.run_oauth_flow")
    @patch(f"{_AUTH}.GOOGLE_AUTH_AVAILABLE", True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_no_creds_with_a_client_secret_raises_and_never_starts_the_flow(
        self, mock_flow: MagicMock, mock_build: MagicMock, keyring_store: Any
    ) -> None:
        """The headless hang: a client secret alone used to open a browser and block on its callback."""
        keyring_store.set_password("aipass", "google/client_secret", json.dumps({"installed": {"client_id": "cid"}}))

        with pytest.raises(GoogleAuthUnavailable, match="drone @api reauth google"):
            build_service("drive", "v3")

        mock_flow.assert_not_called()
        mock_build.assert_not_called()

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_expired_creds_are_refreshed_then_built(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """An expired token with a refresh token is refreshed in place, then built."""
        mock_creds = MagicMock(expired=True, refresh_token="tok", valid=True)
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = mock_creds
        mock_auth.refresh_credentials.return_value = True

        assert build_service("drive", "v3") is mock_build.return_value
        mock_auth.refresh_credentials.assert_called_once_with(mock_creds)

    @patch(f"{_SF}.json_handler", autospec=True)
    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_success_returns_service(
        self,
        mock_auth: MagicMock,
        mock_build: MagicMock,
        _mock_jh: MagicMock,
    ) -> None:
        """Successful auth and build returns service object."""
        mock_creds = MagicMock(expired=False, valid=True)
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = mock_creds
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        result = build_service("drive", "v3")

        assert result is mock_service
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_build_exception_raises_with_the_reason(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """When build() raises, GoogleAuthUnavailable carries its reason."""
        # @backup's DriveClient reads the reason; None told it only "get_drive_service returned None".
        mock_auth.GoogleAuthUnavailable = GoogleAuthUnavailable
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = MagicMock(expired=False, valid=True)
        mock_build.side_effect = RuntimeError("build failed")

        with pytest.raises(GoogleAuthUnavailable) as caught:
            build_service("drive", "v3")

        assert str(caught.value) == "Google drive service could not be built: build failed"


class TestBuildThreadSafeService:
    """Tests for service_factory.build_thread_safe_service()."""

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", False)
    def test_not_available_returns_none(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """Absent libs alone refuse: credentials and build would both succeed here."""
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = MagicMock(expired=False)

        result = build_thread_safe_service("drive", "v3")

        assert result is None
        mock_build.assert_not_called()

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_load_credentials_fails_returns_none(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """When load_credentials returns None, returns None."""
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = None

        result = build_thread_safe_service("drive", "v3")
        assert result is None

    @patch(f"{_SF}.logger", autospec=True)
    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_expired_creds_refresh_fails_returns_none(
        self,
        mock_auth: MagicMock,
        _mock_build: MagicMock,
        _mock_logger: MagicMock,
    ) -> None:
        """When creds expired and refresh fails, returns None."""
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "tok"
        mock_creds.valid = False
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = mock_creds
        mock_auth.refresh_credentials.return_value = False

        result = build_thread_safe_service("drive", "v3")
        assert result is None

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_creds_not_valid_returns_none(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """When creds are not expired but not valid either, returns None."""
        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.refresh_token = None
        mock_creds.valid = False
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = mock_creds

        result = build_thread_safe_service("drive", "v3")
        assert result is None

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_build_exception_raises_with_the_reason(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """When build() raises for a worker thread, GoogleAuthUnavailable carries its reason."""
        # Contract: @backup's _build_thread_service receives this exception.
        mock_auth.GoogleAuthUnavailable = GoogleAuthUnavailable
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = MagicMock(expired=False, valid=True)
        mock_build.side_effect = RuntimeError("ssl handshake")

        with pytest.raises(GoogleAuthUnavailable) as caught:
            build_thread_safe_service("drive", "v3")

        assert str(caught.value) == "Thread-safe Google drive service could not be built: ssl handshake"

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_success_returns_service(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """Valid creds produce a service object."""
        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.valid = True
        mock_auth.is_available.return_value = True
        mock_auth.load_credentials.return_value = mock_creds
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        result = build_thread_safe_service("drive", "v3")

        assert result is mock_service
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)
