# =================== AIPass ====================
# Name: retry.py
# Description: Google API retry logic with SSL error handling
# Version: 1.1.0
# Created: 2026-03-14
# Modified: 2026-10-17
# =============================================

"""Google API Retry Handler"""

import ssl
import time
from typing import Any, Callable, Optional

from aipass.api.apps.handlers.json import json_handler


def is_ssl_error(exc: Exception) -> bool:
    """Check if an exception is a transient SSL/connection error."""
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
    sleep: Optional[Callable[[float], Any]] = None,
) -> Any:
    """Execute a Google API request with exponential backoff on SSL errors.

    sleep=None looks up time.sleep at the call, so a patch of that name still reaches it.
    """
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except Exception as e:
            if attempt < max_retries and is_ssl_error(e):
                wait = 2**attempt
                json_handler.log_operation("api_retry_attempted", {"attempt": attempt + 1, "wait_seconds": wait})
                (sleep or time.sleep)(wait)
                if rebuild_service_fn:
                    rebuild_service_fn()
                continue
            raise
