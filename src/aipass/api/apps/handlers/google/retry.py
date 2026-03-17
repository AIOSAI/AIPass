# =================== AIPass ====================
# Name: retry.py
# Description: Google API retry logic with SSL error handling
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================

"""
Google API Retry Handler

Provides exponential backoff retry for Google API calls,
with specific handling for transient SSL/connection errors.

Extracted from backup's drive_sync_client.py — generic enough
for any Google API consumer, not just Drive.

Usage:
    from aipass.api.apps.handlers.google.retry import api_call_with_retry

    result = api_call_with_retry(
        service.files().list(q="..."),
        max_retries=3,
        rebuild_service_fn=my_rebuild_fn,
    )
"""

import ssl
import time
from typing import Any, Callable, Optional

# JSON handler
from aipass.api.apps.handlers.json import json_handler


def is_ssl_error(exc: Exception) -> bool:
    """Check if an exception is a transient SSL/connection error.

    Args:
        exc: The caught exception.

    Returns:
        True if the error is a transient SSL/connection issue.
    """
    if isinstance(exc, (ssl.SSLError, BrokenPipeError, ConnectionResetError)):
        return True

    ssl_keywords = (
        "DECRYPTION_FAILED_OR_BAD_RECORD_MAC",
        "WRONG_VERSION_NUMBER",
        "EOF occurred",
        "ssl.SSLError",
        "BrokenPipeError",
        "ConnectionReset",
    )
    msg = str(exc)
    return any(kw in msg for kw in ssl_keywords)


def api_call_with_retry(
    request: Any,
    max_retries: int = 3,
    rebuild_service_fn: Optional[Callable] = None,
) -> Any:
    """Execute a Google API request with exponential backoff on SSL errors.

    Args:
        request: A Google API request object (has .execute() method).
        max_retries: Maximum number of retry attempts.
        rebuild_service_fn: Optional callback to rebuild the service
            on SSL failure (e.g. to get a fresh connection).
            Called with no arguments, return value is ignored.

    Returns:
        The API response.

    Raises:
        The original exception if retries are exhausted or
        the error is not an SSL/connection issue.
    """
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except Exception as e:
            if attempt < max_retries and is_ssl_error(e):
                wait = 2 ** attempt
                json_handler.log_operation("api_retry_attempted", {"attempt": attempt + 1, "wait_seconds": wait})
                time.sleep(wait)
                if rebuild_service_fn:
                    rebuild_service_fn()
                continue
            raise
