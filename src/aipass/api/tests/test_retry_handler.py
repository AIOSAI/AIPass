# =================== AIPass ====================
# Name: test_retry_handler.py
# Description: Tests for Google API retry handler with SSL error detection
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-10-05
# =============================================

"""Tests for apps/handlers/google/retry.py, the SSL retry logic."""

# Tests:
# - is_ssl_error: SSLError, BrokenPipeError, ConnectionResetError, ValueError,
#   keyword-based detection
# - api_call_with_retry: first-try success, retry success, exhausted retries,
#   non-SSL immediate raise, rebuild_service_fn invocation

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that retry.py parses and imports
# seedgo: no-test-needed(stdlib) — time.sleep's real delay; the sleep seam gets a recorder, no backoff is waited out
# seedgo: no-test-needed(network) — a real Google call; api_call_with_retry is handed a stand-in request

from __future__ import annotations

import ssl
from unittest.mock import MagicMock

import pytest

from aipass.api.apps.handlers.google.retry import api_call_with_retry, is_ssl_error


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

    def test_success_first_try(self) -> None:
        """Successful execute() on the first attempt returns the result, and nothing waits."""
        request = MagicMock()
        request.execute.return_value = {"files": []}
        waits: list[float] = []

        result = api_call_with_retry(request, max_retries=3, sleep=waits.append)

        assert result == {"files": []}
        request.execute.assert_called_once()
        assert waits == []

    def test_success_after_retry(self) -> None:
        """SSL error on first attempt, success on second, after one wait of 1s."""
        request = MagicMock()
        request.execute.side_effect = [
            ssl.SSLError("transient"),
            {"files": ["a.txt"]},
        ]
        waits: list[float] = []

        result = api_call_with_retry(request, max_retries=3, sleep=waits.append)

        assert result == {"files": ["a.txt"]}
        assert request.execute.call_count == 2
        assert waits == [1]

    def test_exhausted_retries_raises(self) -> None:
        """All retries exhausted re-raises the SSL error, the waits doubling 1, 2, 4.

        The waits are read off the sleep seam rather than a patch of time.sleep,
        which replaced it for every reader in the process (api, fleet green leg 13).
        """
        request = MagicMock()
        request.execute.side_effect = ssl.SSLError("persistent")
        waits: list[float] = []

        with pytest.raises(ssl.SSLError, match="persistent"):
            api_call_with_retry(request, max_retries=3, sleep=waits.append)

        # initial attempt + 3 retries = 4 calls
        assert request.execute.call_count == 4
        assert waits == [1, 2, 4], "the backoff must double, not grow by one"

    def test_non_ssl_error_raises_immediately(self) -> None:
        """Non-SSL exception is raised without retry, and nothing waits."""
        request = MagicMock()
        request.execute.side_effect = ValueError("bad arg")
        waits: list[float] = []

        with pytest.raises(ValueError, match="bad arg"):
            api_call_with_retry(request, max_retries=3, sleep=waits.append)

        request.execute.assert_called_once()
        assert waits == []

    def test_rebuild_service_fn_called(self) -> None:
        """rebuild_service_fn is invoked after each SSL retry; the waits are not this test's subject."""
        request = MagicMock()
        request.execute.side_effect = [
            ssl.SSLError("first"),
            ssl.SSLError("second"),
            {"ok": True},
        ]
        rebuild_fn = MagicMock()

        result = api_call_with_retry(request, max_retries=3, rebuild_service_fn=rebuild_fn, sleep=lambda _seconds: None)

        assert result == {"ok": True}
        assert rebuild_fn.call_count == 2
        # Implied by the result (the third answer comes only from a third call); kept as the
        # line that shows the unconsumed_side_effect row every queued answer is consumed,
        # which the checker does not read from a return (api, fleet green leg 4).
        assert request.execute.call_count == 3
