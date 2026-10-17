# =================== AIPass ====================
# Name: client.py
# Description: OpenRouter Client Handler
# Version: 3.1.1
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false

"""OpenRouter Client Handler"""

import time
from typing import Optional, Dict, List, Any

from aipass.prax import logger

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError as e:
    logger.error(f"OpenAI SDK not available. Install with: pip install openai: {e}")
    OpenAI = None  # type: ignore[assignment,misc]
    OPENAI_AVAILABLE = False

from aipass.api.apps.handlers.auth.keys import get_api_key
from aipass.api.apps.handlers.openrouter.caller import get_caller_info
from aipass.api.apps.handlers.openrouter.provision import ensure_caller_config
from aipass.api.apps.handlers.usage.tracking import track_usage

from aipass.api.apps.handlers.json import json_handler

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 30
# No default model: callers name their own model from their branch config.

OPENROUTER_HEADERS = {"HTTP-Referer": "https://aipass.local", "X-Title": "AIPass API Client"}

_client_cache: Dict[str, OpenAI] = {}
MAX_CACHED_CLIENTS = 5


class OpenRouterUnavailable(Exception):
    """The SDK refused to build a client, or a response could not be read.

    Raised instead of None, which read the same as "no key" or "empty reply"; make_call shows the reason.
    """


def create_client(
    api_key: str, base_url: str = OPENROUTER_BASE_URL, timeout: int = DEFAULT_TIMEOUT
) -> Optional[OpenAI]:
    """Create OpenAI SDK client configured for OpenRouter."""
    if not OPENAI_AVAILABLE:
        logger.error("OpenAI SDK not installed. Run: pip install openai")
        return None

    if not api_key:
        logger.error("API key required for client creation")
        return None

    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, default_headers=OPENROUTER_HEADERS)

        logger.info(f"Created OpenRouter client - base_url: {base_url}, timeout: {timeout}s")
        json_handler.log_operation("client_initialized", {"base_url": base_url, "timeout": timeout})
        return client

    except Exception as e:
        raise OpenRouterUnavailable(f"OpenRouter client could not be created: {e}") from e


def get_cached_client(
    api_key: str, base_url: str = OPENROUTER_BASE_URL, timeout: int = DEFAULT_TIMEOUT
) -> Optional[OpenAI]:
    """Get cached OpenAI client or create new one if not cached."""
    global _client_cache

    if api_key in _client_cache:
        cached_client = _client_cache[api_key]
        if cached_client and cached_client.api_key == api_key:
            logger.info("Using cached OpenRouter client")
            return cached_client

    client = create_client(api_key, base_url, timeout)

    if not client:
        return None

    if len(_client_cache) >= MAX_CACHED_CLIENTS:
        oldest_key = next(iter(_client_cache))
        del _client_cache[oldest_key]
        logger.info(f"Removed oldest cached client - cache limit: {MAX_CACHED_CLIENTS}")

    _client_cache[api_key] = client
    logger.info("Cached new OpenRouter client")

    return client


def make_api_request(client: OpenAI, messages: List[Dict], model: str, retries: int = 1, **kwargs) -> Optional[Any]:
    """Execute API request via OpenRouter with retry logic."""
    if not client or not messages or not model:
        logger.warning(
            f"make_api_request() called with missing params — "
            f"client={bool(client)}, messages={bool(messages)}, model={bool(model)}"
        )
        return None

    api_params = {"model": model, "messages": messages, **kwargs}

    last_error = None
    for attempt in range(1 + retries):
        try:
            response = client.chat.completions.create(**api_params)
            if attempt > 0:
                logger.info(f"API request succeeded on retry {attempt} for model {model}")
            return response
        except Exception as e:
            last_error = e
            if attempt < retries:
                delay = 1.0 * (attempt + 1)  # 1s, 2s, ...
                logger.info(
                    f"API request failed for {model} (attempt {attempt + 1}/{1 + retries}): "
                    f"{e} — retrying in {delay:.0f}s"
                )
                time.sleep(delay)

    logger.error(f"API request failed for {model} after {1 + retries} attempts: {last_error}")
    return None


def extract_response(response: Any) -> Optional[Dict[str, Any]]:
    """Extract text content and metadata from API response."""
    if not response:
        return None

    try:
        if not hasattr(response, "choices") or not response.choices:
            logger.warning("Response missing 'choices' or choices is empty")
            return None

        if not hasattr(response.choices[0], "message"):
            logger.warning("Response choice missing 'message' attribute")
            return None

        content = response.choices[0].message.content

        if not content:
            logger.warning("Response has no content")
            return None

        finish_reason = response.choices[0].finish_reason if hasattr(response.choices[0], "finish_reason") else None
        result = {
            "content": content,
            "id": response.id if hasattr(response, "id") else None,
            "model": response.model if hasattr(response, "model") else None,
            "finish_reason": finish_reason,
        }

        if finish_reason == "content_filter":
            logger.warning("Response was truncated or blocked by content filter")

        logger.info(f"Extracted response - length: {len(content)} chars, id: {result['id']}")
        return result

    except Exception as e:
        raise OpenRouterUnavailable(f"OpenRouter response could not be read: {e}") from e


def get_response(
    prompt: str, caller: Optional[str] = None, model: Optional[str] = None, **kwargs
) -> Optional[Dict[str, Any]]:
    """
    Main API call - get response from OpenRouter with full tracking integration.

    OpenRouterUnavailable and KeyUnavailable propagate so the caller can show the reason.
    """
    if not caller:
        caller_info = get_caller_info()
        if caller_info and caller_info.get("caller_name"):
            caller = caller_info["caller_name"]
            logger.info(f"Auto-detected caller: {caller}")
        else:
            logger.warning("Could not detect caller - using 'unknown'")
            caller = "unknown"

    try:
        ensure_caller_config(caller)
    except Exception as e:
        logger.warning(f"Caller config provisioning failed (non-blocking): {e}")

    if not model:
        logger.error("No model specified.")
        logger.warning(
            "Callers must provide their own model via branch config (e.g., flow_json/openrouter_config.json)"
        )
        return None

    api_key = get_api_key("openrouter")
    if not api_key:
        logger.error("No OpenRouter API key available")
        return None

    client = get_cached_client(api_key)
    if not client:
        return None

    messages = [{"role": "user", "content": prompt}]

    response = make_api_request(client, messages, model, **kwargs)
    if not response:
        return None

    result = extract_response(response)
    if not result:
        return None

    if result.get("id"):
        try:
            track_usage(result["id"], caller if caller else "unknown", model, api_key)
        except Exception as e:
            logger.warning(f"Usage tracking failed: {e}")

    logger.info(f"Successfully got response - caller: {caller}, model: {model}, length: {len(result['content'])} chars")
    return result


def get_cache_stats() -> Dict[str, Any]:
    """
    Get statistics about the client cache.

    Never the cache's keys: they are raw API keys.
    """
    return {
        "cached_clients": len(_client_cache),
        "max_cache_size": MAX_CACHED_CLIENTS,
    }
