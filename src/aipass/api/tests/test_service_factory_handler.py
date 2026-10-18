# =================== AIPass ====================
# Name: test_service_factory_handler.py
# Description: Tests for Google API service factory handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/google/service_factory.py, the Google API service object factory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — googleapiclient.discovery.build and a live Google service; mocked, no network
# seedgo: no-test-needed(covered_elsewhere) — handlers/google/auth.py credential loading; tests/test_google_client.py

from unittest.mock import patch, MagicMock

import pytest

from aipass.api.apps.handlers.google.auth import GoogleAuthUnavailable

from aipass.api.apps.handlers.google.service_factory import build_service, build_thread_safe_service

_SF = "aipass.api.apps.handlers.google.service_factory"


class TestBuildService:
    """Tests for service_factory.build_service()."""

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", False)
    def test_google_libs_not_available_returns_none(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """Absent libs alone refuse: auth and build would both succeed here."""
        mock_auth.is_available.return_value = True
        mock_auth.authenticate.return_value = MagicMock()

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
    def test_auth_fails_returns_none(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """When authenticate returns None, returns None."""
        mock_auth.is_available.return_value = True
        mock_auth.authenticate.return_value = None

        result = build_service("drive", "v3")
        assert result is None

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
        mock_creds = MagicMock()
        mock_auth.is_available.return_value = True
        mock_auth.authenticate.return_value = mock_creds
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
        mock_auth.authenticate.return_value = MagicMock()
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
