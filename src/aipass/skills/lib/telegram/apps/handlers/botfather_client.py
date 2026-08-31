# =================== AIPass ====================
# Name: botfather_client.py
# Description: Telethon-based BotFather automation client
# Version: 1.0.0
# Created: 2026-06-15
# Modified: 2026-06-15
# =============================================

"""
BotFather Automation Client

Automates Telegram bot creation by driving a conversation with @BotFather
using Telethon (user-account MTProto client). This replaces the manual
"go to BotFather, create a bot, paste the token" workflow.

Flow:
  1. Connect to Telegram as the user account (pre-authenticated session)
  2. Send /newbot to @BotFather
  3. Provide display name and username
  4. Parse the bot token from BotFather's success response
  5. Return token + metadata for bot_factory.py to complete registration

Requirements:
  - Telethon 1.42.0+ installed
  - One-time manual phone auth to create .telethon.session file
  - API credentials stored in the @api secrets store (telethon_config)
"""

# Standard library
import asyncio
import re
import time
from pathlib import Path
from typing import Any, Optional

# Logging
from aipass.prax import logger

# JSON handler (seedgo standard)
from aipass.skills.apps.handlers.json import json_handler  # noqa: F401

# Sibling imports
from .config import _get_secret

# Third party (Telethon) — runtime-imported in methods to avoid Pyright issues
TELETHON_AVAILABLE = False
try:
    import telethon as _telethon_check  # noqa: F401  # type: ignore[import-untyped]

    TELETHON_AVAILABLE = True
    del _telethon_check
except ImportError:
    # NOT logged here. A WARNING emitted at module import fires once per
    # import, and an absent optional dependency is one condition however many
    # times it is observed: ten imports produced ten identical warnings and an
    # escalation. The report moved to first USE, deduped, where it names
    # something a caller actually tried to do.
    pass

# =============================================
# CONSTANTS
# =============================================

SESSION_PATH = Path.home() / ".secrets" / "aipass" / "telegram" / ".telethon"  # Telethon appends .session automatically

BOTFATHER_USERNAME = "BotFather"
BOT_TOKEN_PATTERN = re.compile(r"\d+:[A-Za-z0-9_-]+")

# Timeouts
MESSAGE_TIMEOUT = 30  # seconds to wait for BotFather response
MAX_USERNAME_ATTEMPTS = 3


# =============================================
# CONFIG LOADER
# =============================================


def _load_telethon_config() -> dict:
    """
    Load Telethon API credentials from the @api secrets store.

    Expected format:
        {"api_id": 12345, "api_hash": "abc123..."}

    Returns:
        Dict with "api_id" (int) and "api_hash" (str).

    Raises:
        RuntimeError: If config is missing, incomplete, or unreadable.
    """
    config = _get_secret("telethon_config")
    if config is None:
        raise RuntimeError(
            "Telethon config not found in secrets store (telegram/telethon_config). "
            "Set it with: drone @api set-secret telegram telethon_config "
            '\'{"api_id": ..., "api_hash": "..."}\''
        )

    api_id = config.get("api_id")
    api_hash = config.get("api_hash")

    if not api_id or not api_hash:
        raise RuntimeError("Telethon config incomplete — missing api_id or api_hash (telegram/telethon_config)")

    try:
        config["api_id"] = int(api_id)
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"Telethon config api_id is not a valid integer: {e}") from e

    config["api_hash"] = str(api_hash)

    logger.info("Telethon config loaded successfully")
    return config


# =============================================
# SETUP CHECK
# =============================================


_TELETHON_WARNED = False


def _warn_telethon_missing_once() -> None:
    """Report an absent Telethon once per process, at first use.

    The condition is a property of the environment, not of the call, so
    repeating it per caller tells a reader nothing new and escalates on volume
    alone.
    """
    global _TELETHON_WARNED
    if _TELETHON_WARNED:
        return
    _TELETHON_WARNED = True
    logger.warning("Telethon not installed — BotFather automation unavailable")


def check_telethon_setup() -> tuple[bool, str]:
    """
    Check whether Telethon is ready for BotFather automation.

    Verifies:
    1. Telethon library is importable
    2. Telethon config exists in secrets store with valid credentials
    3. .telethon.session exists (phone auth already completed)

    Returns:
        (True, "ready") if everything is in place.
        (False, "reason") with a human-readable explanation of what is missing.
    """
    if not TELETHON_AVAILABLE:
        _warn_telethon_missing_once()
        return (False, "Telethon library not installed. Run: pip install telethon")

    try:
        _load_telethon_config()
    except RuntimeError as e:
        logger.warning("Telethon setup check failed: %s", e)
        return (False, str(e))

    # Telethon creates session files with .session extension
    session_file = Path(str(SESSION_PATH) + ".session")
    if not session_file.exists():
        return (
            False,
            f"Telethon session not found at {session_file}. Run one-time phone auth first.",
        )

    return (True, "ready")


# =============================================
# HELPER FUNCTIONS
# =============================================


def _format_display_name(branch_name: str) -> str:
    """
    Convert a branch_name to a BotFather display name.

    Examples:
        "dev_central" -> "AIPass Dev Central"
        "flow"        -> "AIPass Flow"
        "vera"        -> "AIPass Vera"

    Args:
        branch_name: AIPass branch name (snake_case).

    Returns:
        Display name string.
    """
    title = branch_name.replace("_", " ").title()
    return f"AIPass {title}"


def _format_username(branch_name: str, suffix: int = 0) -> str:
    """
    Generate a BotFather username from a branch name.

    Examples:
        ("dev_central", 0) -> "aipass_dev_central_bot"
        ("dev_central", 1) -> "aipass_dev_central_1_bot"
        ("dev_central", 2) -> "aipass_dev_central_2_bot"

    Args:
        branch_name: AIPass branch name (snake_case).
        suffix: Numeric suffix for retries (0 = no suffix).

    Returns:
        Username string ending in _bot.
    """
    if suffix == 0:
        return f"aipass_{branch_name}_bot"
    return f"aipass_{branch_name}_{suffix}_bot"


# =============================================
# BOTFATHER CLIENT
# =============================================


class BotFatherClient:
    """
    Telethon-based client that automates bot creation via @BotFather.

    Uses an authenticated user session to send commands to BotFather
    and parse the resulting bot token.

    Usage:
        client = BotFatherClient(api_id=12345, api_hash="abc...")
        result = await client.create_bot("dev_central")
        # result = {"token": "123:ABC", "username": "aipass_dev_central_bot", "display_name": "AIPass Dev Central"}
    """

    def __init__(self, api_id: int, api_hash: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._client: Any = None

    async def connect(self) -> bool:
        """
        Connect to Telegram using the existing session file.

        The session file must already exist from a prior manual phone auth.
        This method will NOT prompt for phone/code input.

        Returns:
            True if connected and authorized, False otherwise.
        """
        try:
            from telethon import TelegramClient as _TelegramClient  # type: ignore[import-untyped]

            self._client = _TelegramClient(
                str(SESSION_PATH),
                self._api_id,
                self._api_hash,
            )
            await self._client.connect()

            if not await self._client.is_user_authorized():
                logger.warning("Telethon session exists but is not authorized. Re-run phone auth.")
                await self._client.disconnect()
                self._client = None
                return False

            me = await self._client.get_me()
            if me:
                logger.info(
                    "Connected to Telegram as: %s (id=%s)",
                    getattr(me, "first_name", "?"),
                    getattr(me, "id", "?"),
                )
            else:
                logger.info("Connected to Telegram (could not resolve self)")

            return True

        except Exception as e:
            logger.warning("Failed to connect to Telegram: %s", e)
            self._client = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from Telegram gracefully."""
        if self._client:
            try:
                await self._client.disconnect()
                logger.info("Disconnected from Telegram")
            except Exception as e:
                logger.warning("Error during disconnect: %s", e)
            finally:
                self._client = None

    async def _send_and_wait(self, entity: Any, message: str) -> Optional[str]:
        """
        Send a message to BotFather and wait for a response.

        Handles FloodWaitError by sleeping for the required duration and retrying once.

        Args:
            entity: The BotFather entity to send to.
            message: The text message to send.

        Returns:
            BotFather's response text, or None on timeout/error.
        """
        if not self._client:
            logger.warning("_send_and_wait called without active client")
            return None

        from telethon.errors import FloodWaitError as _FloodWaitError  # type: ignore[import-untyped]
        from telethon.errors import RPCError as _RPCError  # type: ignore[import-untyped]

        try:
            await self._client.send_message(entity, message)
            logger.info("Sent to BotFather: %s", message)
        except _FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning("FloodWaitError: waiting %d seconds before retry", wait_seconds)
            await asyncio.sleep(wait_seconds)
            try:
                await self._client.send_message(entity, message)
                logger.info("Sent to BotFather (after flood wait): %s", message)
            except Exception as retry_err:
                logger.warning("Failed to send after flood wait: %s", retry_err)
                return None
        except _RPCError as e:
            logger.warning("RPC error sending to BotFather: %s", e)
            return None
        except Exception as e:
            logger.warning("Unexpected error sending to BotFather: %s", e)
            return None

        # Wait for BotFather's response
        deadline = time.monotonic() + MESSAGE_TIMEOUT
        # Brief pause to let BotFather process
        await asyncio.sleep(1.5)

        try:
            while time.monotonic() < deadline:
                # Get the most recent messages from BotFather
                messages = await self._client.get_messages(entity, limit=1)
                if not messages:
                    await asyncio.sleep(1.0)
                    continue
                # get_messages returns a list-like object
                msg_list = list(messages)
                if msg_list:
                    latest = msg_list[0]
                    # Check that this message is FROM BotFather (not our own)
                    if getattr(latest, "out", True) is False and getattr(latest, "text", None):
                        response_text: str = latest.text
                        logger.info("BotFather response received (%d chars)", len(response_text))
                        return response_text

                # Poll interval
                await asyncio.sleep(1.0)

            logger.warning("Timeout waiting for BotFather response (after %ds)", MESSAGE_TIMEOUT)
            return None

        except Exception as e:
            logger.warning("Error reading BotFather response: %s", e)
            return None

    async def create_bot(self, branch_name: str) -> Optional[dict]:
        """
        Create a new Telegram bot via @BotFather conversation.

        Conversation flow:
          1. /newbot
          2. Display name (e.g., "AIPass Dev Central")
          3. Username (e.g., "aipass_dev_central_bot")
          4. Parse token from success response

        If the username is taken, retries with numeric suffixes up to MAX_USERNAME_ATTEMPTS.

        Args:
            branch_name: AIPass branch name (e.g., "dev_central", "flow").

        Returns:
            Dict with "token", "username", "display_name" on success.
            None on any failure.
        """
        if not self._client:
            logger.warning("create_bot called without active connection")
            return None

        display_name = _format_display_name(branch_name)

        # Resolve BotFather entity
        try:
            botfather = await self._client.get_entity(BOTFATHER_USERNAME)
            logger.info("Resolved BotFather entity: %s", getattr(botfather, "id", "?"))
        except Exception as e:
            logger.warning("Failed to resolve @BotFather entity: %s", e)
            return None

        # Step 1: Send /newbot
        response = await self._send_and_wait(botfather, "/newbot")
        if not response:
            logger.warning("BotFather did not respond to /newbot")
            return None

        # BotFather should ask for a name
        if "name" not in response.lower():
            logger.warning("Unexpected BotFather response to /newbot: %s", response[:200])
            return None

        logger.info("BotFather asked for bot name")

        # Step 2: Send display name
        response = await self._send_and_wait(botfather, display_name)
        if not response:
            logger.warning("BotFather did not respond to display name")
            return None

        # BotFather should ask for a username
        if "username" not in response.lower():
            logger.warning("Unexpected BotFather response to display name: %s", response[:200])
            return None

        logger.info("BotFather asked for username")

        # Step 3: Try usernames with incrementing suffix
        for attempt in range(MAX_USERNAME_ATTEMPTS):
            username = _format_username(branch_name, suffix=attempt)
            logger.info(
                "Trying username: %s (attempt %d/%d)",
                username,
                attempt + 1,
                MAX_USERNAME_ATTEMPTS,
            )

            response = await self._send_and_wait(botfather, username)
            if not response:
                logger.warning("BotFather did not respond to username '%s'", username)
                return None

            # Check if the username was accepted (token in response)
            token_match = BOT_TOKEN_PATTERN.search(response)
            if token_match:
                token = token_match.group()
                logger.info(
                    "Bot created successfully: @%s (token: %s...%s)",
                    username,
                    token[:8],
                    token[-4:],
                )
                json_handler.log_operation("bot_created", {"username": username, "branch": branch_name})
                return {
                    "token": token,
                    "username": username,
                    "display_name": display_name,
                }

            # Username taken - BotFather says "Sorry" or mentions "already"
            if "sorry" in response.lower() or "already" in response.lower() or "taken" in response.lower():
                logger.info("Username '%s' is taken, trying next", username)
                continue

            # Unexpected response
            logger.warning(
                "Unexpected BotFather response for username '%s': %s",
                username,
                response[:200],
            )
            return None

        logger.warning(
            "All %d username attempts exhausted for branch '%s'",
            MAX_USERNAME_ATTEMPTS,
            branch_name,
        )
        return None


# =============================================
# SYNCHRONOUS WRAPPER
# =============================================


def create_bot_via_botfather(branch_name: str) -> Optional[dict]:
    """
    Synchronous wrapper to create a Telegram bot via BotFather automation.

    This is the main entry point for stdlib-based callers (e.g., base_bot.py).
    Loads config, connects via Telethon, drives the BotFather conversation,
    and returns the result.

    Args:
        branch_name: AIPass branch name (e.g., "dev_central").

    Returns:
        Dict with "token", "username", "display_name" on success.
        None on any failure (config missing, connection failed, BotFather error, etc.).
    """
    # Pre-flight checks — fail loud so callers see the real reason
    ready, reason = check_telethon_setup()
    if not ready:
        raise RuntimeError(f"Telethon setup failed: {reason}")

    config = _load_telethon_config()

    api_id = config["api_id"]
    api_hash = config["api_hash"]

    # Run the async flow
    client = BotFatherClient(api_id, api_hash)
    result = None

    async def _run() -> Optional[dict]:
        connected = await client.connect()
        if not connected:
            return None
        try:
            return await client.create_bot(branch_name)
        finally:
            await client.disconnect()

    try:
        # Handle the case where an event loop is already running
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.info("No running event loop — will use asyncio.run()")
            loop = None

        if loop and loop.is_running():
            # We're inside an existing event loop (unlikely for our stdlib callers,
            # but handle gracefully). Create a new loop in a thread.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _run())
                result = future.result(timeout=120)
        else:
            result = asyncio.run(_run())

    except Exception as e:
        logger.warning("create_bot_via_botfather failed: %s", e)
        return None

    if result:
        logger.info(
            "Bot created via BotFather: @%s for branch '%s'",
            result.get("username"),
            branch_name,
        )
    else:
        logger.warning("Bot creation via BotFather failed for branch '%s'", branch_name)

    return result
