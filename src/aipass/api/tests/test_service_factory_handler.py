# =================== AIPass ====================
# Name: test_service_factory_handler.py
# Description: Tests for Google API service factory handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""
Tests for google.service_factory -- Google API service object factory.

Tests:
- build_service: unavailable, auth failure, success, build exception
- build_thread_safe_service: unavailable, cred failures, expired creds, success
"""

from unittest.mock import patch, MagicMock

_SF = "aipass.api.apps.handlers.google.service_factory"


# =============================================
# build_service tests
# =============================================


class TestBuildService:
    """Tests for service_factory.build_service()."""

    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", False)
    def test_google_libs_not_available_returns_none(self) -> None:
        """When google libs are not installed, returns None."""
        from aipass.api.apps.handlers.google.service_factory import build_service

        result = build_service("drive", "v3")
        assert result is None

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_auth_not_available_returns_none(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """When auth module reports unavailable, returns None."""
        from aipass.api.apps.handlers.google.service_factory import build_service

        mock_auth.is_available.return_value = False

        result = build_service("drive", "v3")
        assert result is None

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_auth_fails_returns_none(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """When authenticate returns None, returns None."""
        from aipass.api.apps.handlers.google.service_factory import build_service

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
        from aipass.api.apps.handlers.google.service_factory import build_service

        mock_creds = MagicMock()
        mock_auth.is_available.return_value = True
        mock_auth.authenticate.return_value = mock_creds
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        result = build_service("drive", "v3")

        assert result is mock_service
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)

    @patch(f"{_SF}.logger", autospec=True)
    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_build_exception_returns_none(
        self,
        mock_auth: MagicMock,
        mock_build: MagicMock,
        _mock_logger: MagicMock,
    ) -> None:
        """When build() raises, returns None and logs error."""
        from aipass.api.apps.handlers.google.service_factory import build_service

        mock_auth.is_available.return_value = True
        mock_auth.authenticate.return_value = MagicMock()
        mock_build.side_effect = RuntimeError("build failed")

        result = build_service("drive", "v3")

        assert result is None
        _mock_logger.error.assert_called_once()


# =============================================
# build_thread_safe_service tests
# =============================================


class TestBuildThreadSafeService:
    """Tests for service_factory.build_thread_safe_service()."""

    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", False)
    def test_not_available_returns_none(self) -> None:
        """When google libs unavailable, returns None."""
        from aipass.api.apps.handlers.google.service_factory import (
            build_thread_safe_service,
        )

        result = build_thread_safe_service("drive", "v3")
        assert result is None

    @patch(f"{_SF}.build")
    @patch(f"{_SF}.auth", autospec=True)
    @patch(f"{_SF}.GOOGLE_BUILD_AVAILABLE", True)
    def test_load_credentials_fails_returns_none(self, mock_auth: MagicMock, _mock_build: MagicMock) -> None:
        """When load_credentials returns None, returns None."""
        from aipass.api.apps.handlers.google.service_factory import (
            build_thread_safe_service,
        )

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
        from aipass.api.apps.handlers.google.service_factory import (
            build_thread_safe_service,
        )

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
        from aipass.api.apps.handlers.google.service_factory import (
            build_thread_safe_service,
        )

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
    def test_success_returns_service(self, mock_auth: MagicMock, mock_build: MagicMock) -> None:
        """Valid creds produce a service object."""
        from aipass.api.apps.handlers.google.service_factory import (
            build_thread_safe_service,
        )

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
