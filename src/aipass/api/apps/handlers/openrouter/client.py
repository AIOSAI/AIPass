# =================== AIPass ====================
# Name: client.py
# Description: OpenRouter Client Handler
# Version: 3.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================
# pyright: reportInvalidTypeForm=false, reportOptionalCall=false

"""
OpenRouter Client Handler

Business logic for OpenRouter API client creation and request execution.
OpenRouter API client creation and request execution.

Functions:
- get_response() - Main API call with tracking integration
- create_client() - Create OpenAI SDK client configured for OpenRouter
- make_api_request() - Execute API request and handle errors
- extract_response() - Extract text and metadata from API response

Configuration:
- base_url: https://openrouter.ai/api/v1
- Uses OpenAI SDK with OpenRouter endpoint
- Supports all 323+ OpenRouter models
- Connection pooling via client caching

Standards:
- Uses prax logger for output (NO print() or console.print())
- Uses logger.info() for system logging
- Integrates with auth/keys, caller detection, usage tracking handlers
- Standalone functions (no classes)
- Complete error handling with graceful failures
"""

# INFRASTRUCTURE IMPORT PATTERN

# Standard library imports
import time
from typing import Optional, Dict, List, Any

# Logging
from aipass.prax import logger

# OpenAI SDK for OpenRouter compatibility
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError as e:
    logger.error(f"OpenAI SDK not available. Install with: pip install openai: {e}")
    OpenAI = None  # type: ignore[assignment,misc]
    OPENAI_AVAILABLE = False

# Handler imports
from aipass.api.apps.handlers.auth.keys import get_api_key
from aipass.api.apps.handlers.openrouter.caller import get_caller_info
from aipass.api.apps.handlers.openrouter.provision import ensure_caller_config
from aipass.api.apps.handlers.usage.tracking import track_usage

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# =============================================
# CONFIGURATION
# =============================================

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 30
# NOTE: No default model - callers must specify their own model from their branch config

# HTTP headers for OpenRouter
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://aipass.local",
    "X-Title": "AIPass API Client"
}

# Client cache for connection pooling
_client_cache: Dict[str, OpenAI] = {}
MAX_CACHED_CLIENTS = 5

# =============================================
# CLIENT CREATION
# =============================================

def create_client(api_key: str, base_url: str = OPENROUTER_BASE_URL, timeout: int = DEFAULT_TIMEOUT) -> Optional[OpenAI]:
    """
    Create OpenAI SDK client configured for OpenRouter.

    Args:
        api_key: OpenRouter API key
        base_url: OpenRouter base URL (default: https://openrouter.ai/api/v1)
        timeout: Request timeout in seconds (default: 30)

    Returns:
        OpenAI client instance or None on failure

    Example:
        >>> api_key = get_api_key("openrouter")
        >>> client = create_client(api_key)
        >>> if client:
        ...     # Use client for requests
    """
    if not OPENAI_AVAILABLE:
        logger.error("OpenAI SDK not installed. Run: pip install openai")
        return None

    if not api_key:
        logger.error("API key required for client creation")
        return None

    try:
        # Create OpenAI client with OpenRouter configuration
        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            default_headers=OPENROUTER_HEADERS
        )

        logger.info(f"Created OpenRouter client - base_url: {base_url}, timeout: {timeout}s")
        json_handler.log_operation("client_initialized", {"base_url": base_url, "timeout": timeout})
        return client

    except Exception as e:
        logger.error(f"Error creating OpenRouter client: {e}")
        return None


def get_cached_client(api_key: str, base_url: str = OPENROUTER_BASE_URL, timeout: int = DEFAULT_TIMEOUT) -> Optional[OpenAI]:
    """
    Get cached OpenAI client or create new one if not cached.
    Implements connection pooling for better performance.

    Args:
        api_key: OpenRouter API key
        base_url: OpenRouter base URL
        timeout: Request timeout in seconds

    Returns:
        OpenAI client instance or None on failure

    Note:
        Cache is limited to MAX_CACHED_CLIENTS (5) to prevent memory growth.
        Oldest clients are removed when cache is full.
    """
    global _client_cache

    # Check if we have a cached client for this API key
    if api_key in _client_cache:
        cached_client = _client_cache[api_key]
        # Verify cached client is still valid
        if cached_client and cached_client.api_key == api_key:
            logger.info("Using cached OpenRouter client")
            return cached_client

    # Create new client
    client = create_client(api_key, base_url, timeout)

    if not client:
        return None

    # Cache the client (limit cache size)
    if len(_client_cache) >= MAX_CACHED_CLIENTS:
        # Remove oldest client (first key in dict)
        oldest_key = next(iter(_client_cache))
        del _client_cache[oldest_key]
        logger.info(f"Removed oldest cached client - cache limit: {MAX_CACHED_CLIENTS}")

    _client_cache[api_key] = client
    logger.info("Cached new OpenRouter client")

    return client


# =============================================
# API REQUEST EXECUTION
# =============================================

def make_api_request(client: OpenAI, messages: List[Dict], model: str, retries: int = 1, **kwargs) -> Optional[Any]:
    """
    Execute API request via OpenRouter with retry logic.

    Args:
        client: OpenAI client instance
        messages: Chat messages in OpenAI format [{"role": "user", "content": "..."}]
        model: Model identifier (e.g., "anthropic/claude-3.5-sonnet")
        retries: Number of retries on failure (default: 1, so 2 total attempts)
        **kwargs: Additional OpenAI API parameters (temperature, max_tokens, etc.)

    Returns:
        OpenAI response object or None on failure
    """
    if not client or not messages or not model:
        logger.warning(f"make_api_request() called with missing params — client={bool(client)}, messages={bool(messages)}, model={bool(model)}")
        return None

    api_params = {
        "model": model,
        "messages": messages,
        **kwargs
    }

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
                logger.info(f"API request failed for {model} (attempt {attempt + 1}/{1 + retries}): {e} — retrying in {delay:.0f}s")
                time.sleep(delay)

    logger.error(f"API request failed for {model} after {1 + retries} attempts: {last_error}")
    return None


def extract_response(response: Any) -> Optional[Dict[str, Any]]:
    """
    Extract text content and metadata from API response.

    Args:
        response: OpenAI response object

    Returns:
        Dict with 'content' (str), 'id' (str), 'model' (str) or None on failure

    Example:
        >>> response = make_api_request(client, messages, model)
        >>> data = extract_response(response)
        >>> if data:
        ...     print(data['content'])
        ...     track_usage(caller, data['id'], data['model'], api_key)
    """
    if not response:
        return None

    try:
        # Validate response structure
        if not hasattr(response, 'choices') or not response.choices:
            logger.warning("Response missing 'choices' or choices is empty")
            return None

        if not hasattr(response.choices[0], 'message'):
            logger.warning("Response choice missing 'message' attribute")
            return None

        # Extract content
        content = response.choices[0].message.content

        if not content:
            logger.warning("Response has no content")
            return None

        # Extract metadata
        result = {
            "content": content,
            "id": response.id if hasattr(response, 'id') else None,
            "model": response.model if hasattr(response, 'model') else None,
            "finish_reason": response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else None
        }

        logger.info(f"Extracted response - length: {len(content)} chars, id: {result['id']}")
        return result

    except Exception as e:
        logger.error(f"Failed to extract response: {e}")
        return None


# =============================================
# MAIN API CALL
# =============================================

def get_response(prompt: str, caller: Optional[str] = None, model: Optional[str] = None, **kwargs) -> Optional[Dict[str, Any]]:
    """
    Main API call - get response from OpenRouter with full tracking integration.

    This is the primary entry point that integrates all handlers:
    - Detects caller automatically if not provided
    - Retrieves API key via auth/keys handler
    - Creates/caches client
    - Makes API request
    - Extracts response
    - Tracks usage via usage/tracking handler

    Args:
        prompt: User prompt text
        caller: Module making the request (auto-detected if not provided)
        model: Model to use (required - caller must provide from branch config)
        **kwargs: Additional OpenAI API parameters

    Returns:
        Dict with 'content', 'id', 'model' or None on failure

    Example:
        >>> response = get_response("What is Python?", caller="cli", model="anthropic/claude-3.5-sonnet")
        >>> if response:
        ...     print(response['content'])
    """
    # Step 1: Detect caller if not provided
    if not caller:
        caller_info = get_caller_info()
        if caller_info and caller_info.get("caller_name"):
            caller = caller_info["caller_name"]
            logger.info(f"Auto-detected caller: {caller}")
        else:
            logger.warning("Could not detect caller - using 'unknown'")
            caller = "unknown"

    # Step 1b: Ensure caller has config (auto-provision if missing)
    try:
        ensure_caller_config(caller)
    except Exception as e:
        logger.warning(f"Caller config provisioning failed (non-blocking): {e}")

    # Step 2: Require model from caller - no defaults
    if not model:
        logger.error("No model specified.")
        logger.warning("Callers must provide their own model via branch config (e.g., flow_json/openrouter_config.json)")
        return None

    # Step 3: Get API key
    api_key = get_api_key("openrouter")
    if not api_key:
        logger.error("No OpenRouter API key available")
        return None

    # Step 4: Get or create client
    client = get_cached_client(api_key)
    if not client:
        return None

    # Step 5: Convert prompt to messages format
    messages = [{"role": "user", "content": prompt}]

    # Step 6: Make API request
    response = make_api_request(client, messages, model, **kwargs)
    if not response:
        return None

    # Step 7: Extract response
    result = extract_response(response)
    if not result:
        return None

    # Step 8: Track usage (if response has ID)
    if result.get("id"):
        try:
            track_usage(result["id"], caller if caller else "unknown", model, api_key)
        except Exception as e:
            logger.warning(f"Usage tracking failed: {e}")

    logger.info(f"Successfully got response - caller: {caller}, model: {model}, length: {len(result['content'])} chars")
    return result


# =============================================
# CLEANUP
# =============================================

def get_cache_stats() -> Dict[str, Any]:
    """
    Get statistics about the client cache.

    Returns:
        Dict with cache size and keys
    """
    return {
        "cached_clients": len(_client_cache),
        "max_cache_size": MAX_CACHED_CLIENTS,
        "cache_keys": list(_client_cache.keys())
    }
