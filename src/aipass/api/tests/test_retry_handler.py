# =================== AIPass ====================
# Name: test_retry_handler.py
# Description: Tests for Google API retry handler with SSL error detection
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/google/retry.py, the SSL retry logic."""

# Tests:
# - is_ssl_error: SSLError, BrokenPipeError, ConnectionResetError, ValueError,
#   keyword-based detection
# - api_call_with_retry: first-try success, retry success, exhausted retries,
#   non-SSL immediate raise, rebuild_service_fn invocation

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that retry.py parses and imports
# seedgo: no-test-needed(stdlib) — time.sleep's real delay; it is patched, the backoff is not waited out
# seedgo: no-test-needed(network) — a real Google call; api_call_with_retry is handed a stand-in request

from __future__ import annotations

import ssl
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.google.retry import api_call_with_retry, is_ssl_error

_RETRY_MOD = "aipass.api.apps.handlers.google.retry"


# =============================================
# is_ssl_error
# =============================================


class TestIsSSLError:
    """Verifies SSL/connection error classification."""

    def test_ssl_error(self) -> None:
        """ssl.SSLError is recognised as an SSL error."""
        exc = ssl.SSLError("handshake failure")
        assert is_ssl_error(exc) is True

    def test_broken_pipe(self) -> None:
        """BrokenPipeError is recognised as an SSL error."""
        assert is_ssl_error(BrokenPipeError()) is True

    def test_connection_reset(self) -> None:
        """ConnectionResetError is recognised as an SSL error."""
        assert is_ssl_error(ConnectionResetError()) is True

    def test_value_error_not_ssl(self) -> None:
        """Plain ValueError is not an SSL error."""
        assert is_ssl_error(ValueError("bad value")) is False

    def test_keyword_in_message(self) -> None:
        """Exception whose message contains an SSL keyword is detected."""
        exc = Exception("DECRYPTION_FAILED_OR_BAD_RECORD_MAC happened")
        assert is_ssl_error(exc) is True

    def test_eof_keyword(self) -> None:
        """Exception message with 'EOF occurred' is detected."""
        exc = Exception("EOF occurred in violation of protocol")
        assert is_ssl_error(exc) is True

    def test_no_keyword_match(self) -> None:
        """Exception without any SSL keywords returns False."""
        exc = Exception("something completely unrelated")
        assert is_ssl_error(exc) is False


# =============================================
# api_call_with_retry
# =============================================


class TestApiCallWithRetry:
    """Verifies retry logic for Google API calls."""

    @patch(f"{_RETRY_MOD}.time.sleep")
    def test_success_first_try(self, mock_sleep: MagicMock) -> None:
        """Successful execute() on the first attempt returns the result."""
        request = MagicMock()
        request.execute.return_value = {"files": []}

        result = api_call_with_retry(request, max_retries=3)

        assert result == {"files": []}
        request.execute.assert_called_once()
        mock_sleep.assert_not_called()

    @patch(f"{_RETRY_MOD}.time.sleep")
    def test_success_after_retry(self, mock_sleep: MagicMock) -> None:
        """SSL error on first attempt, success on second."""
        request = MagicMock()
        request.execute.side_effect = [
            ssl.SSLError("transient"),
            {"files": ["a.txt"]},
        ]

        result = api_call_with_retry(request, max_retries=3)

        assert result == {"files": ["a.txt"]}
        assert request.execute.call_count == 2
        mock_sleep.assert_called_once()

    @patch(f"{_RETRY_MOD}.time.sleep")
    def test_exhausted_retries_raises(self, mock_sleep: MagicMock) -> None:
        """All retries exhausted re-raises the SSL error."""
        request = MagicMock()
        request.execute.side_effect = ssl.SSLError("persistent")

        with pytest.raises(ssl.SSLError, match="persistent"):
            api_call_with_retry(request, max_retries=2)

        # initial attempt + 2 retries = 3 calls
        assert request.execute.call_count == 3

    @patch(f"{_RETRY_MOD}.time.sleep")
    def test_non_ssl_error_raises_immediately(self, mock_sleep: MagicMock) -> None:
        """Non-SSL exception is raised without retry."""
        request = MagicMock()
        request.execute.side_effect = ValueError("bad arg")

        with pytest.raises(ValueError, match="bad arg"):
            api_call_with_retry(request, max_retries=3)

        request.execute.assert_called_once()
        mock_sleep.assert_not_called()

    @patch(f"{_RETRY_MOD}.time.sleep")
    def test_rebuild_service_fn_called(self, mock_sleep: MagicMock) -> None:
        """rebuild_service_fn is invoked after each SSL retry."""
        request = MagicMock()
        request.execute.side_effect = [
            ssl.SSLError("first"),
            ssl.SSLError("second"),
            {"ok": True},
        ]
        rebuild_fn = MagicMock()

        result = api_call_with_retry(request, max_retries=3, rebuild_service_fn=rebuild_fn)

        assert result == {"ok": True}
        assert rebuild_fn.call_count == 2
