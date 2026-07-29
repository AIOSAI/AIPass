# =================== AIPass ====================
# Name: base_bot.py
# Description: BaseBot class for Telegram multi-bot architecture
# Version: 1.4.2
# Created: 2026-02-24
# Modified: 2026-07-28
# =============================================

"""
BaseBot - Foundation class for AIPass Telegram multi-bot architecture.

Each AIPass branch gets its own dedicated Telegram bot. BaseBot is both a
runnable bot (for the base @aipass_bot) AND the template all branch bots inherit.

Stdlib-only implementation using urllib for Telegram API. No python-telegram-bot
dependency. Follows the same polling/tmux injection pattern as direct_chat.py.

Flow:
  User sends Telegram message
  -> BaseBot receives it via getUpdates long-polling
  -> If /command -> handle via telegram_standards, reply, return
  -> If /new -> kill tmux session, reply, return
  -> Else -> ensure tmux session exists (running Claude)
  -> Send "Processing..." message
  -> Write pending file for Stop hook coordination
  -> Start heartbeat thread (updates "Processing..." with elapsed time)
  -> Inject message into tmux session via send-keys
  -> Claude processes and hits Stop event
  -> Stop hook reads pending file, extracts response, sends to Telegram

Usage:
    bot = BaseBot(
        bot_id="dev_central",
        bot_token="123:ABC",
        work_dir=Path("/path/to/branch/work_dir"),
        bot_name="AIPass Dev Central Bot",
        allowed_user_ids=[7235222625],
    )
    sys.exit(bot.run())
"""

# =============================================
# IMPORTS (stdlib only)
# =============================================

import argparse
import atexit
import json
import os
import re
import signal
import subprocess
import sys
import threading
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Logging
from aipass.prax import logger

# JSON handler (seedgo standard)
from aipass.skills.apps.handlers.json import json_handler  # noqa: F401

# =============================================
# SIBLING IMPORTS
# =============================================

from .telegram_standards import (  # noqa: F401
    parse_command,
    handle_standard_command,
    STANDARD_COMMANDS,
    build_welcome_text,
    build_help_text,
    build_status_text,
    PROCESSING_MSG,
)
from .file_handler import (
    detect_file_type,
    build_file_prompt,
)
from .bot_factory import (
    create_bot,
    launch_mirror_session,  # noqa: F401
    set_bot_commands,
    start_service,  # noqa: F401
    validate_branch,
    validate_token,
)
from .telegram_standards import build_botfather_commands

from .bot_registry import (
    list_bots as registry_list_bots,
    get_bot_by_branch,
)
from .log_streamer import LogStreamer

# Optional — botfather_client may not be ported yet
_BOTFATHER_AVAILABLE = False
try:
    from .botfather_client import (
        create_bot_via_botfather,
        check_telethon_setup,
    )

    _BOTFATHER_AVAILABLE = True
except ImportError:
    logger.info("botfather_client not available — automated bot creation disabled")

    def create_bot_via_botfather(branch_name: str) -> dict | None:  # type: ignore[misc]
        """Stub: botfather_client not ported yet."""
        return None

    def check_telethon_setup() -> tuple[bool, str]:  # type: ignore[misc]
        """Stub: botfather_client not ported yet."""
        return False, "botfather_client not available"


# =============================================
# MODULE-LEVEL CONSTANTS
# =============================================

CC_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
PENDING_DIR = Path.home() / ".aipass" / "telegram_pending"
PENDING_TTL = 3600  # 1 hour
TELEGRAM_CHAR_LIMIT = 4096
RATE_LIMIT_MESSAGES = 5
RATE_LIMIT_WINDOW = 60
POLL_TIMEOUT = 30
SEND_KEYS_DELAY = 0.5
HEARTBEAT_INTERVAL = 30  # seconds
STREAM_INTERVAL = 2  # seconds between streaming edits
CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")
MIRROR_SESSION_TYPE = "interactive-mirror"
TEMP_DIR = Path(tempfile.gettempdir()) / "telegram_uploads"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
NETWORK_BACKOFF_INIT = 1  # seconds
NETWORK_BACKOFF_CAP = 60  # seconds
NETWORK_LOG_INTERVAL = 300  # 5 minutes between offline summary lines
STARTUP_RETRY_CAP_SECONDS = 180  # ~3 minutes of backoff before failing loud


class _NetworkPollError(Exception):
    """Raised by poll_updates when a network-class error occurs (DNS, connection, socket)."""


def _is_network_error(exc: Exception) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, OSError):
        return True
    reason_str = str(reason) if reason else str(exc)
    for pattern in (
        "Name or service not known",
        "getaddrinfo",
        "Temporary failure",
        "Network is unreachable",
        "No route to host",
        "Connection refused",
        "Connection reset",
        "Connection timed out",
    ):
        if pattern in reason_str:
            return True
    return False


def _is_routine_read_timeout(exc: Exception) -> bool:
    return "timed out" in str(exc) and "read operation" in str(getattr(exc, "reason", exc))


def _extract_retry_after(exc: HTTPError, default: int = 30) -> int:
    """Read Telegram's retry_after (seconds) from a 429 response body, falling back to default."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except Exception as parse_err:
        logger.info("Cannot parse 429 error body: %s", parse_err)
        return default
    return body.get("parameters", {}).get("retry_after", default)


# =============================================
# BaseBot CLASS
# =============================================


class BaseBot:
    """
    Base Telegram bot for AIPass multi-bot architecture.

    Both a runnable bot (for the base @aipass_bot) and the template that
    all branch bots inherit from. Uses stdlib urllib for Telegram API,
    tmux for Claude sessions, and a heartbeat thread for progress updates.
    """

    def __init__(
        self,
        bot_id: str,
        bot_token: str,
        work_dir: Path,
        bot_name: str = "AIPass Bot",
        allowed_user_ids: Optional[list[int]] = None,
        custom_commands: Optional[dict] = None,
        branch_name: Optional[str] = None,
        shared_session: Optional[str] = None,
        attach_only: bool = False,
        stream: bool = False,
    ) -> None:
        """
        Initialize BaseBot.

        Args:
            bot_id: Unique identifier for this bot (e.g., "dev_central")
            bot_token: Telegram bot API token
            work_dir: Working directory for the tmux Claude session
            bot_name: Display name shown in /start and /status
            allowed_user_ids: List of Telegram user IDs allowed to use the bot.
                              Empty list or None means allow all.
            custom_commands: Dict of bot-specific commands in telegram_standards format
            branch_name: Branch name for log streaming (None = no streaming, e.g. base bot)
            shared_session: tmux session name to inject into instead of creating own session.
                            When set, the bot attaches to an existing session (e.g., the user's
                            running Claude Code session). Falls back to own session if not found.
        """
        self.bot_id = bot_id
        self.bot_token = bot_token
        self.work_dir = Path(work_dir)
        self.bot_name = bot_name
        self.allowed_user_ids = allowed_user_ids or []
        self.custom_commands = custom_commands or {}
        # branch_name may already be set by subclass (e.g. BranchPlugin) before super().__init__
        if not hasattr(self, "branch_name"):
            self.branch_name = branch_name

        self._current_sender_name: str = "User"

        self.session_name = f"telegram-{bot_id}"
        self.pending_file = PENDING_DIR / f"bot-{bot_id}.json"

        # Shared-session mode: inject into an existing tmux session instead of creating own
        self._shared_session_name = shared_session
        self._using_shared_session = False
        self._attach_only = attach_only
        self._stream = stream
        self._mirror_mapping_written = False
        self._last_transcript_path: str | None = None
        self._config_chat_id: int | None = None
        self._active_session_id: str | None = None
        self._active_transcript_path: Path | None = None

        self.state = {
            "running": True,
            "message_count": 0,
            "start_time": time.time(),
            "conversation_start": time.time(),
            "last_message_time": 0.0,
        }

        self._health = {
            "started_at": None,
            "last_message_at": None,
            "messages_received": 0,
            "messages_failed": 0,
            "errors": 0,
        }

        self._rate_limit_tracker: dict[int, list] = {}
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_gen: int = 0

        # Conversation state for /create flow (keyed by chat_id)
        self._create_state: dict[int, dict] = {}
        self._create_state_ttl = 300  # 5 minutes

        # Log streamer (started on first message when branch_name is set)
        self._log_streamer: Optional[LogStreamer] = None
        self._active_chat_id: Optional[int] = None

        # Monitor streamer (system-wide, persisted across restarts)
        self._monitor_streamer: Optional[LogStreamer] = None

        # Lock file
        self._lock_file = Path.home() / ".aipass" / "telegram_bots" / f".{bot_id}.lock"

        # Offset file
        self._offset_file = Path.home() / ".aipass" / "telegram_bots" / f"{bot_id}_offset.json"

    # =============================================
    # MAIN ENTRY POINT
    # =============================================

    def run(self) -> int:
        """
        Main entry point. Start polling and process messages.

        Returns:
            0 on clean exit, 1 on error
        """
        logger.info("=" * 60)
        logger.info("%s starting (bot_id=%s)", self.bot_name, self.bot_id)

        # Verify connection
        if not self._verify_connection_with_retry():
            logger.error("Startup health check FAILED - cannot reach Telegram API")
            return 1

        logger.info("Connected to Telegram API")
        self._health["started_at"] = datetime.now().isoformat()
        json_handler.log_operation("bot_started", {"bot_id": self.bot_id})

        # Set Telegram command menu (idempotent, runs once per startup)
        self._set_command_menu()

        # Boot-start monitor if a subscription was persisted
        self._boot_monitor()

        # Check for existing lock (prevents duplicate pollers for the same bot_id).
        # Return 0 (not 1) so systemd Restart=on-failure does not restart-loop.
        if self._check_lock():
            logger.error("Another instance of bot-%s is already running — exiting cleanly", self.bot_id)
            return 0
        self._create_lock()

        # Signal handlers
        signal.signal(signal.SIGTERM, self._shutdown_handler)
        signal.signal(signal.SIGINT, self._shutdown_handler)
        atexit.register(self._cleanup)

        # Ensure pending directory
        PENDING_DIR.mkdir(parents=True, exist_ok=True)

        # Clean stale pending file
        self.clean_stale_pending()

        # Load offset
        offset = self._load_offset()
        logger.info("Starting poll loop (offset=%d)", offset)

        # General retry backoff (non-network errors)
        retry_delay = 5
        max_retry_delay = 60

        # Network-error state tracking
        net_backoff = NETWORK_BACKOFF_INIT
        net_offline_since: float | None = None
        net_suppressed = 0
        net_last_summary: float = 0.0

        while self.state["running"]:
            try:
                updates = self.poll_updates(offset)

                # Reset general backoff on successful poll
                retry_delay = 5

                # Network recovery
                if net_offline_since is not None:
                    elapsed = time.time() - net_offline_since
                    mins = int(elapsed / 60)
                    logger.info(
                        "Telegram reachable again after %dm, %d attempts suppressed",
                        mins,
                        net_suppressed,
                    )
                    net_offline_since = None
                    net_suppressed = 0
                    net_backoff = NETWORK_BACKOFF_INIT

                for update in updates:
                    if not self.state["running"]:
                        break

                    # Advance offset BEFORE processing so a consumed update
                    # (rate-limited, rejected, or erroring) never pins the offset.
                    new_offset = update.get("update_id", 0) + 1
                    if new_offset > offset:
                        offset = new_offset
                        self._save_offset(offset)

                    self.process_update(update)

            except _NetworkPollError as e:
                self._health["errors"] = self._health.get("errors", 0) + 1
                now = time.time()
                if net_offline_since is None:
                    net_offline_since = now
                    net_suppressed = 0
                    net_last_summary = now
                    logger.warning("Telegram unreachable, backing off: %s", e)
                else:
                    net_suppressed += 1
                    if now - net_last_summary >= NETWORK_LOG_INTERVAL:
                        mins = int((now - net_offline_since) / 60)
                        logger.warning(
                            "Still offline (%dm), %d attempts suppressed",
                            mins,
                            net_suppressed,
                        )
                        net_last_summary = now
                time.sleep(net_backoff)
                net_backoff = min(net_backoff * 2, NETWORK_BACKOFF_CAP)
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received")
                break
            except Exception as e:
                self._health["errors"] = self._health.get("errors", 0) + 1
                logger.error("Error in poll loop: %s: %s", type(e).__name__, e)
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

        logger.info("Poll loop exited")
        return 0

    # =============================================
    # TELEGRAM API (stdlib urllib)
    # =============================================

    def verify_connection(self, timeout: int = 15) -> bool:
        """
        Verify connection to Telegram API by calling getMe.

        Args:
            timeout: Connection timeout in seconds

        Returns:
            True if connection succeeded
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
        try:
            req = Request(url)
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("ok"):
                bot_info = data.get("result", {})
                logger.info("Telegram API OK - @%s", bot_info.get("username", "unknown"))
                return True

            logger.warning("Telegram API rejected: %s", data.get("description", "unknown"))
            return False

        except URLError as e:
            logger.warning("Telegram API connection failed: %s", e)
            return False
        except Exception as e:
            logger.warning("Telegram API health check error: %s", e)
            return False

    def _verify_connection_with_retry(self) -> bool:
        """
        Retry the startup health check with exponential backoff.

        Absorbs a boot-time DNS/network race (systemd's network-online.target
        can resolve before DNS is actually usable) in-process instead of
        exiting 1 into a systemd restart storm. Mirrors the poll loop's
        _NetworkPollError backoff. A real, sustained outage still fails loud
        via the caller once STARTUP_RETRY_CAP_SECONDS is exhausted.
        """
        if self.verify_connection():
            return True

        backoff = NETWORK_BACKOFF_INIT
        elapsed = 0.0
        attempt = 1

        while elapsed < STARTUP_RETRY_CAP_SECONDS:
            logger.warning("Startup health check failed (attempt %d) — retrying in %ds", attempt, backoff)
            time.sleep(backoff)
            elapsed += backoff
            attempt += 1

            if self.verify_connection():
                logger.info("Startup health check recovered after %d retries (%ds)", attempt - 1, int(elapsed))
                return True

            backoff = min(backoff * 2, NETWORK_BACKOFF_CAP)

        return False

    def poll_updates(self, offset: int) -> list:
        """
        Long-poll Telegram for new updates via getUpdates.

        Args:
            offset: Update offset to avoid reprocessing

        Returns:
            List of update dicts
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?offset={offset}&timeout={POLL_TIMEOUT}"

        try:
            req = Request(url)
            with urlopen(req, timeout=POLL_TIMEOUT + 10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not data.get("ok"):
                logger.error("Telegram API error: %s", data.get("description", "unknown"))
                return []

            return data.get("result", [])

        except URLError as e:
            if _is_routine_read_timeout(e):
                return []
            if _is_network_error(e):
                raise _NetworkPollError(str(e)) from e
            if isinstance(e, HTTPError) and (e.code >= 500 or e.code == 409):
                raise _NetworkPollError(str(e)) from e
            if isinstance(e, HTTPError) and e.code == 429:
                retry = _extract_retry_after(e)
                logger.warning("Poll rate-limited (429) — backing off %ds", retry)
                time.sleep(retry)
                return []
            logger.error("Poll error: %s", e)
            return []
        except (ConnectionError, OSError) as e:
            if _is_routine_read_timeout(e):
                return []
            raise _NetworkPollError(str(e)) from e
        except Exception as e:
            logger.error("Unexpected poll error: %s", e)
            return []

    def send_message(self, chat_id: int, text: str, reply_to: Optional[int] = None) -> dict | None:
        """
        Send a message via Telegram sendMessage API.

        Args:
            chat_id: Target chat ID
            text: Message text
            reply_to: Optional message ID to reply to

        Returns:
            Parsed JSON response dict (contains message_id), or None on failure
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload: dict = {
            "chat_id": chat_id,
            "text": text,
        }
        if reply_to is not None:
            payload["reply_to_message_id"] = reply_to

        for attempt in range(3):
            try:
                data = json.dumps(payload).encode("utf-8")
                req = Request(url, data=data, headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read().decode("utf-8"))

                if result.get("ok"):
                    return result.get("result")
                else:
                    logger.warning(
                        "sendMessage failed (attempt %d): %s",
                        attempt + 1,
                        result.get("description", "unknown"),
                    )
            except Exception as e:
                logger.warning("sendMessage error (attempt %d): %s", attempt + 1, e)

            if attempt < 2:
                time.sleep(1.0 * (2**attempt))

        logger.error("sendMessage failed after 3 attempts")
        self._health["messages_failed"] = self._health.get("messages_failed", 0) + 1
        return None

    def edit_message(self, chat_id: int, message_id: int, text: str) -> bool:
        """
        Edit a message via Telegram editMessageText API.

        Args:
            chat_id: Chat ID containing the message
            message_id: ID of the message to edit
            text: New text for the message

        Returns:
            True if edit succeeded
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(url, data=data, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            return result.get("ok", False)

        except Exception as e:
            logger.warning("editMessageText error: %s", e)
            return False

    # =============================================
    # UPDATE PROCESSING
    # =============================================

    def process_update(self, update: dict) -> None:
        """
        Process a single Telegram update.

        Routes to command handling, message handling, or file handling
        based on update contents.

        Args:
            update: Telegram update dict
        """
        message = update.get("message")
        if not message:
            return

        text = message.get("text", "")
        chat = message.get("chat", {})
        chat_id = chat.get("id", 0)
        from_user = message.get("from", {})
        user_id = from_user.get("id", 0)
        username = from_user.get("username", "unknown")
        self._current_sender_name = from_user.get("first_name", "User")
        _ = message.get("message_id", 0)  # Available for future use

        # Start log streamer on first valid message (if branch has a name)
        if self._active_chat_id is None and chat_id:
            self._active_chat_id = chat_id
            self._write_mirror_mapping()
            if self.branch_name is not None and self._log_streamer is None:
                pref = self._load_logs_preference()
                pref_mode = pref.get("mode", "all") if pref else "all"
                if pref_mode != "off":
                    self._log_streamer = LogStreamer(self.bot_token, chat_id, self.branch_name, level_filter=pref_mode)
                    self._log_streamer.start()
                    logger.info("Log streamer started for branch: %s (mode=%s)", self.branch_name, pref_mode)

        # Allowlist check
        if not self.is_user_allowed(user_id):
            logger.warning("Blocked message from unauthorized user_id: %s (@%s)", user_id, username)
            return

        # Rate limit check
        if not self.check_rate_limit(user_id):
            logger.warning("Rate limited user_id: %s", user_id)
            self.send_message(chat_id, "Rate limit exceeded. Please wait before sending more messages.")
            return

        # Health tracking
        self._health["last_message_at"] = datetime.now().isoformat()
        self._health["messages_received"] = self._health.get("messages_received", 0) + 1

        # Check for file uploads (photo/document)
        photo_list = message.get("photo")
        document = message.get("document")

        if photo_list or document:
            self.handle_file(chat_id, message)
            return

        # Check if user is in /create flow (awaiting token paste)
        if chat_id in self._create_state and text and not text.startswith("/"):
            self._handle_create_token(chat_id, text)
            return

        # Command handling
        if text:
            parsed = parse_command(text)
            if parsed is not None:
                handled = self._dispatch_command(chat_id, parsed)  # type: ignore[attr-defined]
                if handled:
                    return
                # Not a standard command - fall through to regular message processing

        # Regular message handling
        if text:
            self.handle_message(chat_id, text, message)
        else:
            logger.info("Ignoring unsupported message type")

    def _dispatch_command(self, chat_id: int, parsed: tuple) -> bool:
        """
        Dispatch a parsed command to the appropriate handler.

        Extracted from process_update to reduce nesting depth.

        Args:
            chat_id: Telegram chat ID
            parsed: Tuple of (cmd_name, cmd_args) from parse_command

        Returns:
            True if command was handled (caller should return), False to fall through.
        """
        cmd_name, cmd_args = parsed

        # /logs command — session log stream control
        if cmd_name == "logs":
            self._handle_logs_command(chat_id, cmd_args)
            return True

        # /monitor command — system-wide log subscription
        if cmd_name == "monitor":
            self._handle_monitor_command(chat_id, cmd_args)
            return True

        # /create and /cancel — base bot only (branch bots must not spawn bots)
        if cmd_name in ("create", "cancel") and self.branch_name is not None:
            return False

        if cmd_name == "create":
            self._handle_create_command(chat_id, cmd_args)
            return True

        if cmd_name == "cancel":
            if chat_id in self._create_state:
                del self._create_state[chat_id]
                self.send_message(chat_id, "Bot creation cancelled.")
            else:
                self.send_message(chat_id, "Nothing to cancel.")
            return True

        # Compute conversation uptime (resets on /new) and daemon uptime (since boot)
        conv_elapsed = time.time() - self.state.get("conversation_start", self.state["start_time"])
        conv_h, conv_rem = divmod(int(conv_elapsed), 3600)
        conv_m, conv_s = divmod(conv_rem, 60)
        uptime_str = f"{conv_h}h {conv_m}m {conv_s}s"

        daemon_elapsed = time.time() - self.state["start_time"]
        d_h, d_rem = divmod(int(daemon_elapsed), 3600)
        d_m, d_s = divmod(d_rem, 60)
        daemon_uptime_str = f"{d_h}h {d_m}m {d_s}s"

        # Merge custom commands from constructor and hook
        merged_commands = {**self.custom_commands, **self.get_custom_commands()}

        # /status — enhance with registry info
        if cmd_name == "status":
            status_text = build_status_text(
                session_name=self.session_name,
                branch_name=self.bot_id,
                uptime=uptime_str,
                message_count=self.state.get("message_count"),
                chat_id=chat_id,
                daemon_uptime=daemon_uptime_str,
            )
            registry_text = self._build_registry_status()
            if registry_text:
                status_text += f"\n\n{registry_text}"
            self.send_message(chat_id, status_text)
            logger.info("Handled /status command")
            return True

        result = handle_standard_command(
            command=cmd_name,
            session_name=self.session_name,
            branch_name=self.bot_id,
            bot_name=self.bot_name,
            custom_commands=merged_commands or None,
            chat_id=chat_id,
            message_count=self.state.get("message_count"),
            uptime=uptime_str,
        )

        if result is not None:
            if isinstance(result, tuple):
                action, response_text = result
                if action == "new":
                    self._kill_tmux_session()
                    self.state["message_count"] = 0
                    self.state["conversation_start"] = time.time()
                    self.send_message(chat_id, response_text)
                    logger.info("Handled /new command - session killed, counters reset")
            else:
                self.send_message(chat_id, result)
                logger.info("Handled /%s command", cmd_name)
            return True

        return False

    # =============================================
    # MESSAGE HANDLING
    # =============================================

    def handle_message(self, chat_id: int, text: str, message: dict) -> None:
        """
        Handle a regular text message.

        Pre-processes via on_message hook, ensures tmux session, writes
        pending file, starts heartbeat, and injects into tmux.

        Args:
            chat_id: Telegram chat ID
            text: Message text
            message: Full message dict
        """
        message_id = message.get("message_id", 0)

        # Hook: pre-process message text
        prompt = self.on_message(text)

        # Track message
        self.state["message_count"] = self.state.get("message_count", 0) + 1
        self.state["last_message_time"] = time.time()

        logger.info("Processing message (msg_id=%d)", message_id)

        # Ensure tmux session
        if not self.ensure_tmux_session():
            logger.error("Cannot process message - no live session to mirror")
            branch = self.branch_name or self.work_dir.name
            self.send_message(
                chat_id,
                f"⚠️ No live Claude session found for branch '{branch}'.\n"
                "Start a Claude session in the branch directory first.",
            )
            return

        # Inbound reliability: clean stale pending + finalize stranded placeholder
        self._finalize_superseded_pending(message_id)

        # Send processing indicator
        processing_result = self.send_message(chat_id, PROCESSING_MSG)
        processing_msg_id = processing_result.get("message_id") if processing_result else None

        # Write pending file
        if not self.write_pending_file(chat_id, message_id, processing_msg_id, injected_prompt=prompt):
            logger.error("Failed to write pending file")
            self.send_message(chat_id, "Internal error writing pending file.")
            return

        # Start heartbeat
        if processing_msg_id:
            self._start_heartbeat(chat_id, processing_msg_id)

        # Inject into tmux
        if not self.inject_message(prompt):
            logger.error("Failed to inject message into tmux")
            self._stop_heartbeat()
            self.pending_file.unlink(missing_ok=True)
            self.send_message(chat_id, "Failed to send message to Claude session.")
            return

        logger.info("Message processed successfully (msg_id=%d)", message_id)

    def handle_file(self, chat_id: int, message: dict) -> None:
        """
        Handle file uploads (photos and documents).

        Downloads the file via Telegram API, detects type, builds prompt,
        then follows the same flow as handle_message.

        Args:
            chat_id: Telegram chat ID
            message: Full message dict containing photo or document
        """
        message_id = message.get("message_id", 0)
        caption = message.get("caption", "")
        photo_list = message.get("photo")
        document = message.get("document")

        file_id = None
        filename = None

        if photo_list:
            # Use highest quality photo (last in array)
            best_photo = photo_list[-1]
            file_id = best_photo.get("file_id", "")
            logger.info(
                "Photo from user (file_id=%s, caption=%s)",
                file_id[:20] if file_id else "none",
                caption[:50] if caption else "none",
            )
        elif document:
            file_id = document.get("file_id", "")
            filename = document.get("file_name", "")
            file_size = document.get("file_size", 0)
            logger.info("Document from user: %s (%d bytes)", filename, file_size)

            if file_size > MAX_FILE_SIZE:
                self.send_message(
                    chat_id,
                    f"File too large ({file_size // 1024}KB). Max is 10MB.",
                )
                return

        if not file_id:
            return

        # Download file via Telegram API
        file_path = self._download_file(file_id, filename)
        if not file_path:
            self.send_message(chat_id, "Failed to download file. Try again?")
            return

        # Detect type and build prompt
        file_type = detect_file_type(file_path)
        prompt = build_file_prompt(file_path, file_type, caption=caption or None, sender_name=self._current_sender_name)

        # Hook: pre-process
        prompt = self.on_message(prompt)

        # Track message
        self.state["message_count"] = self.state.get("message_count", 0) + 1
        self.state["last_message_time"] = time.time()

        # Ensure tmux session
        if not self.ensure_tmux_session():
            logger.error("Cannot process file - no live session to mirror")
            branch = self.branch_name or self.work_dir.name
            self.send_message(
                chat_id,
                f"⚠️ No live Claude session found for branch '{branch}'.\n"
                "Start a Claude session in the branch directory first.",
            )
            if file_type == "text":
                file_path.unlink(missing_ok=True)
            return

        # Inbound reliability: clean stale pending + finalize stranded placeholder
        self._finalize_superseded_pending(message_id)

        # Send processing indicator
        processing_result = self.send_message(chat_id, f"Processing {file_type} file...")
        processing_msg_id = processing_result.get("message_id") if processing_result else None

        # Write pending file
        if not self.write_pending_file(chat_id, message_id, processing_msg_id, injected_prompt=prompt):
            logger.error("Failed to write pending file for file upload")
            self.send_message(chat_id, "Internal error writing pending file.")
            return

        # Clean up text files immediately (content is inline in prompt)
        if file_type == "text":
            file_path.unlink(missing_ok=True)

        # Start heartbeat
        if processing_msg_id:
            self._start_heartbeat(chat_id, processing_msg_id)

        # Inject into tmux
        if not self.inject_message(prompt):
            logger.error("Failed to inject file message into tmux")
            self._stop_heartbeat()
            self.pending_file.unlink(missing_ok=True)
            self.send_message(chat_id, "Failed to send file to Claude session.")
            return

        logger.info("File processed successfully (msg_id=%d)", message_id)

    def _download_file(self, file_id: str, filename: Optional[str] = None) -> Optional[Path]:
        """
        Download a file from Telegram via getFile API + urllib.

        Args:
            file_id: Telegram file_id from the message
            filename: Optional original filename

        Returns:
            Path to the downloaded file, or None on failure
        """
        # Step 1: Get file info
        url = f"https://api.telegram.org/bot{self.bot_token}/getFile?file_id={file_id}"
        try:
            with urlopen(Request(url), timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error("getFile API failed: %s", e)
            return None

        if not data.get("ok"):
            logger.error("getFile error: %s", data.get("description", "unknown"))
            return None

        file_info = data.get("result", {})
        file_path_remote = file_info.get("file_path", "")
        file_size = file_info.get("file_size", 0)

        if not file_path_remote:
            logger.error("No file_path in getFile response")
            return None

        if file_size > MAX_FILE_SIZE:
            logger.warning("File too large: %d bytes (max %d)", file_size, MAX_FILE_SIZE)
            return None

        # Step 2: Download
        download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path_remote}"

        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        if filename:
            safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in Path(filename).name)
        else:
            ext = Path(file_path_remote).suffix or ".jpg"
            safe_name = f"{uuid.uuid4()}{ext}"

        dest = TEMP_DIR / safe_name

        try:
            with urlopen(Request(download_url), timeout=30) as resp:
                dest.write_bytes(resp.read())
            logger.info("Downloaded file to %s (%d bytes)", dest, file_size)
            return dest
        except Exception as e:
            logger.error("File download failed: %s", e)
            return None

    # =============================================
    # /CREATE CHAT COMMAND
    # =============================================

    def _handle_create_command(self, chat_id: int, args: str) -> None:
        """
        Handle /create chat @branch — automated or manual bot creation.

        If Telethon is configured, creates the bot via BotFather automatically.
        Otherwise, falls back to the manual token-paste flow.

        Args:
            chat_id: Telegram chat ID
            args: Command arguments (e.g., "chat dev_central" or "chat @dev_central")
        """
        # Parse args: /create chat <branch_name>
        parts = args.strip().split()

        if len(parts) < 2 or parts[0].lower() != "chat":
            self.send_message(
                chat_id,
                "Usage: /create chat <branch_name>\n\nExample: /create chat dev_central",
            )
            return

        branch_name = parts[1].lstrip("@").lower()

        # Validate branch exists
        branch_info = validate_branch(branch_name)
        if not branch_info:
            self.send_message(
                chat_id,
                f"Branch '@{branch_name}' not found in registry.\n\nCheck available branches and try again.",
            )
            return

        # Check if branch already has a bot
        existing = get_bot_by_branch(branch_name)
        if existing:
            self.send_message(
                chat_id,
                f"Branch '@{branch_name}' already has a bot: "
                f"@{existing.get('username', '?')} (bot_id={existing.get('bot_id')})",
            )
            return

        branch_path = branch_info.get("path", "")

        # Check if Telethon automation is available
        telethon_ready, telethon_reason = check_telethon_setup()

        if telethon_ready:
            # Automated flow — create bot via BotFather + register in one step
            self._handle_create_automated(chat_id, branch_name, branch_path)
        else:
            # Manual fallback — ask user to paste a BotFather token
            logger.info(
                "Telethon not ready (%s), falling back to manual token flow",
                telethon_reason,
            )
            self._create_state[chat_id] = {
                "branch_name": branch_name,
                "branch_path": branch_path,
                "started_at": time.time(),
            }
            self.send_message(
                chat_id,
                f"Branch @{branch_name} found at {branch_path}.\n\n"
                f"⚠️ BotFather automation unavailable: {telethon_reason}\n"
                "Falling back to manual token flow.\n\n"
                "Paste the BotFather token for the new bot.\n"
                "(Get one from @BotFather → /newbot)\n\n"
                "/cancel to abort.",
            )
            logger.info(
                "/create chat: branch @%s validated, awaiting token from chat %d",
                branch_name,
                chat_id,
            )

    def _handle_create_automated(self, chat_id: int, branch_name: str, branch_path: str) -> None:
        """
        Fully automated bot creation via Telethon BotFather client.

        Creates the bot with @BotFather, then registers it via bot_factory.

        Args:
            chat_id: Telegram chat ID
            branch_name: Branch name (e.g., "dev_central")
            branch_path: Branch working directory path
        """
        self.send_message(
            chat_id,
            f"Creating bot for @{branch_name} via BotFather...\nThis takes a few seconds.",
        )

        # Step 1: Create bot via BotFather automation
        bf_result = create_bot_via_botfather(branch_name)
        if not bf_result:
            self.send_message(
                chat_id,
                f"BotFather automation failed for @{branch_name}.\n"
                "Check system logs. You can retry or use manual token mode:\n"
                "Paste a BotFather token to create manually.",
            )
            # Fall back to manual mode
            self._create_state[chat_id] = {
                "branch_name": branch_name,
                "branch_path": branch_path,
                "started_at": time.time(),
            }
            return

        bot_token = bf_result["token"]
        bot_username = bf_result["username"]
        display_name = bf_result["display_name"]

        logger.info(
            "BotFather created @%s for branch @%s, registering...",
            bot_username,
            branch_name,
        )

        # Step 2: Register via bot_factory (validate, write config, registry, systemd)
        result = create_bot(
            bot_id=branch_name,
            bot_token=bot_token,
            branch_name=branch_name,
            work_dir=branch_path,
            bot_name=display_name,
            allowed_user_ids=self.allowed_user_ids,
        )

        if not result:
            self.send_message(
                chat_id,
                f"Bot @{bot_username} was created in BotFather but registration failed.\n"
                f"Token: (check system logs)\n"
                "Run /create chat again or register manually.",
            )
            return

        auto_started = result.get("auto_started", False)
        status_line = (
            "Bot is running!"
            if auto_started
            else (f"Start it with:\nsystemctl --user start telegram-bot@{branch_name}")
        )

        self.send_message(
            chat_id,
            f"Bot created for @{branch_name}!\n\n"
            f"Username: @{bot_username}\n"
            f"Display name: {display_name}\n"
            f"Bot ID: {branch_name}\n"
            f"Work dir: {branch_path}\n"
            f"Service: telegram-bot@{branch_name}\n\n"
            f"{status_line}",
        )

        logger.info(
            "/create: bot @%s created automatically for branch @%s (started=%s)",
            bot_username,
            branch_name,
            auto_started,
        )

    def _handle_create_token(self, chat_id: int, text: str) -> None:
        """
        Handle token paste — step 2: validate token and create bot.

        Args:
            chat_id: Telegram chat ID
            text: The token text pasted by the user
        """
        state = self._create_state.get(chat_id)
        if not state:
            return

        # Check state TTL
        if time.time() - state.get("started_at", 0) > self._create_state_ttl:
            del self._create_state[chat_id]
            self.send_message(chat_id, "Create session expired. Start again with /create chat <branch>.")
            return

        branch_name = state["branch_name"]
        branch_path = state["branch_path"]
        bot_token = text.strip()

        # Basic token format check
        if ":" not in bot_token or len(bot_token) < 20:
            self.send_message(
                chat_id,
                "That doesn't look like a valid bot token.\n"
                "Format: 123456789:ABCdefGHIjklMNO_pqr\n\n"
                "Paste the token from @BotFather, or /cancel to abort.",
            )
            return

        # Clean up state before the potentially slow API calls
        del self._create_state[chat_id]

        self.send_message(chat_id, f"Validating token and creating @{branch_name} bot...")

        # Validate the token via Telegram getMe
        bot_info = validate_token(bot_token)
        if not bot_info:
            self.send_message(
                chat_id,
                "Token validation failed. The token may be invalid or expired.\n"
                "Get a fresh token from @BotFather and try /create chat again.",
            )
            return

        bot_username = bot_info.get("username", "unknown")

        # Create the bot via bot_factory
        result = create_bot(
            bot_id=branch_name,
            bot_token=bot_token,
            branch_name=branch_name,
            work_dir=branch_path,
            allowed_user_ids=self.allowed_user_ids,
        )

        if not result:
            self.send_message(
                chat_id,
                f"Bot creation failed for @{branch_name}. Check system logs.",
            )
            return

        self.send_message(
            chat_id,
            f"Bot created for @{branch_name}!\n\n"
            f"Username: @{bot_username}\n"
            f"Bot ID: {branch_name}\n"
            f"Work dir: {branch_path}\n"
            f"Service: telegram-bot@{branch_name}\n\n"
            f"Start it with:\n"
            f"systemctl --user start telegram-bot@{branch_name}",
        )

        logger.info(
            "/create: bot @%s created for branch @%s",
            bot_username,
            branch_name,
        )

    def _build_registry_status(self) -> str:
        """
        Build registry info string for /status display.

        Returns:
            Formatted string showing registered bots, or empty string if none.
        """
        try:
            bots = registry_list_bots()
        except Exception as e:
            logger.warning("Failed to list bots from registry: %s", e)
            return ""

        if not bots:
            return "Registered Bots: none"

        lines = [f"Registered Bots: {len(bots)}"]
        for bot in bots:
            bot_id = bot.get("bot_id", "?")
            username = bot.get("username", "?")
            status = bot.get("status", "?")
            branch = bot.get("branch_name") or "base"
            lines.append(f"  {bot_id} (@{username}) - {branch} - {status}")

        return "\n".join(lines)

    # =============================================
    # TEXT CHUNKING
    # =============================================

    def chunk_text(self, text: str, limit: int = TELEGRAM_CHAR_LIMIT) -> list[str]:
        """
        Split text into chunks for Telegram's message character limit.

        Uses smart breaking: tries sentence boundaries, then paragraphs,
        then newlines, then spaces, and finally hard breaks.

        Args:
            text: The full text to chunk
            limit: Maximum characters per chunk (default 4096)

        Returns:
            List of text chunks, each within the limit
        """
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            chunk = remaining[:limit]

            # Try to break at sentence boundary
            best_break = -1
            for i in range(len(chunk) - 1, max(0, len(chunk) - 500), -1):
                if chunk[i] in ".!?" and (i + 1 >= len(chunk) or chunk[i + 1] in " \n"):
                    best_break = i + 1
                    break

            # Try double newline
            if best_break == -1:
                newline_pos = chunk.rfind("\n\n")
                if newline_pos > limit // 2:
                    best_break = newline_pos + 2

            # Try single newline
            if best_break == -1:
                newline_pos = chunk.rfind("\n")
                if newline_pos > limit // 2:
                    best_break = newline_pos + 1

            # Try space
            if best_break == -1:
                space_pos = chunk.rfind(" ")
                if space_pos > limit // 2:
                    best_break = space_pos + 1

            # Hard break
            if best_break == -1:
                best_break = limit

            chunks.append(remaining[:best_break].rstrip())
            remaining = remaining[best_break:].lstrip()

        return chunks

    # =============================================
    # SECURITY
    # =============================================

    def is_user_allowed(self, user_id: int) -> bool:
        """
        Check if a user ID is in the allowlist.

        Args:
            user_id: Telegram user ID

        Returns:
            True if allowed (or allowlist empty)
        """
        if not self.allowed_user_ids:
            return True
        return user_id in self.allowed_user_ids

    def check_rate_limit(self, user_id: int) -> bool:
        """
        Check if user is within rate limits using a sliding window.

        Args:
            user_id: Telegram user ID

        Returns:
            True if within limits, False if rate limited
        """
        current_time = time.time()

        if user_id not in self._rate_limit_tracker:
            self._rate_limit_tracker[user_id] = []

        # Prune old timestamps
        self._rate_limit_tracker[user_id] = [
            ts for ts in self._rate_limit_tracker[user_id] if current_time - ts < RATE_LIMIT_WINDOW
        ]

        if len(self._rate_limit_tracker[user_id]) >= RATE_LIMIT_MESSAGES:
            return False

        self._rate_limit_tracker[user_id].append(current_time)
        return True

    # =============================================
    # TMUX SESSION MANAGEMENT
    # =============================================

    def ensure_tmux_session(self) -> bool:
        """
        Ensure a tmux session is available for message injection.

        Resolution order:
        1. Central presence pointer (.ai_central/PRESENCE.central.json)
        2. Explicit shared_session from config
        3. Already-running own tmux session (transitional)

        The bot NEVER spawns its own Claude brain — it is a thin relay that
        follows the live session via the presence pointer (FPLAN-0289 P2).

        Returns:
            True if session is ready
        """
        # Strategy 1: CC-native session discovery (DPLAN-0226)
        cc_session = self._discover_cc_session()
        if cc_session:
            tmux_target = self._find_tmux_pane_by_cwd()
            if tmux_target:
                self.session_name = tmux_target
                self._using_shared_session = True
                self._active_session_id = cc_session.get("sessionId")
                self._active_transcript_path = self._resolve_cc_transcript_path(cc_session)
                logger.info(
                    "CC-native discovery: session '%s' (PID %d) → tmux '%s'",
                    cc_session.get("name", "?"),
                    cc_session.get("pid", 0),
                    tmux_target,
                )
                self._write_mirror_mapping()
                return True
            logger.warning(
                "CC session found (PID %d) but no matching tmux pane",
                cc_session.get("pid", 0),
            )

        # Strategy 2: explicit shared-session from config
        if self._shared_session_name:
            try:
                result = subprocess.run(
                    ["tmux", "has-session", "-t", self._shared_session_name],
                    capture_output=True,
                )
                if result.returncode == 0:
                    self.session_name = self._shared_session_name
                    self._using_shared_session = True
                    logger.info(
                        "Shared session '%s' found — injecting into existing session",
                        self._shared_session_name,
                    )
                    self._write_mirror_mapping()
                    return True
                else:
                    logger.warning(
                        "Shared session '%s' not found",
                        self._shared_session_name,
                    )
            except FileNotFoundError:
                logger.warning("tmux not found while checking shared session '%s'", self._shared_session_name)

        # Strategy 3: already-running own tmux session (transitional — pre-existing sessions only)
        if self._tmux_session_exists():
            return True

        # PRESENCE GUARD: bot never spawns its own Claude brain (FPLAN-0289 P2).
        # Legacy AIPASS_SESSION_TYPE=telegram own-session spawn RETIRED.
        # The bot is a thin relay — it follows the presence pointer or an
        # explicit shared_session. Start a Claude session in the branch first.
        logger.error(
            "No live session to mirror — presence pointer empty, no shared session. "
            "Start a Claude session in the branch directory first."
        )
        return False

    def inject_message(self, text: str) -> bool:
        """
        Inject a message into the tmux session via send-keys.

        Uses -l flag for literal text (no shell interpretation),
        followed by Enter to submit.

        Args:
            text: The message text to inject

        Returns:
            True if injection succeeded
        """
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", self.session_name, "-l", text],
                check=True,
                capture_output=True,
            )
            time.sleep(SEND_KEYS_DELAY)
            subprocess.run(
                ["tmux", "send-keys", "-t", self.session_name, "Enter"],
                check=True,
                capture_output=True,
            )
            logger.info("Message injected into tmux session")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to inject message: %s",
                e.stderr.decode() if e.stderr else str(e),
            )
            return False

    def _tmux_session_exists(self) -> bool:
        """Check if the tmux session exists."""
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", self.session_name],
                capture_output=True,
            )
            return result.returncode == 0
        except FileNotFoundError:
            logger.warning("tmux not found — is it installed?")
            return False

    def _kill_tmux_session(self) -> bool:
        """Kill the tmux session. Protects shared sessions from being killed."""
        # Shared-session protection: never kill a session we don't own
        if self._using_shared_session:
            logger.info(
                "Shared session '%s' — detaching instead of killing",
                self.session_name,
            )
            self._using_shared_session = False
            self.session_name = f"telegram-{self.bot_id}"
            return True

        if not self._tmux_session_exists():
            logger.info("tmux session '%s' not running, nothing to kill", self.session_name)
            return True

        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", self.session_name],
                check=True,
                capture_output=True,
            )
            logger.info("Killed tmux session '%s'", self.session_name)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to kill tmux session '%s': %s",
                self.session_name,
                e.stderr.decode() if e.stderr else str(e),
            )
            return False

    # =============================================
    # PENDING FILE MANAGEMENT
    # =============================================

    def write_pending_file(
        self,
        chat_id: int,
        message_id: int,
        processing_message_id: Optional[int] = None,
        injected_prompt: str = "",
    ) -> bool:
        """
        Write the pending file for Stop hook coordination.

        Args:
            chat_id: Telegram chat ID
            message_id: Original message's Telegram message ID
            processing_message_id: ID of the "Processing..." message to edit

        Returns:
            True if written successfully
        """
        PENDING_DIR.mkdir(parents=True, exist_ok=True)

        transcript_line_after = self._get_transcript_line_count()

        pending_data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "bot_token": self.bot_token,
            "bot_id": self.bot_id,
            "work_dir": str(self.work_dir),
            "session_name": self.session_name,
            "processing_message_id": processing_message_id,
            "timestamp": time.time(),
            "transcript_line_after": transcript_line_after,
            "transcript_path": str(self._active_transcript_path) if self._active_transcript_path else None,
            "session_id": self._active_session_id,
        }
        if injected_prompt:
            pending_data["injected_prompt"] = injected_prompt
        if self._stream:
            pending_data["streaming"] = True

        try:
            self.pending_file.write_text(
                json.dumps(pending_data, indent=2),
                encoding="utf-8",
            )
            logger.info("Pending file written for message %d", message_id)
            return True
        except OSError as e:
            logger.error("Failed to write pending file: %s", e)
            return False

    def clean_stale_pending(self) -> None:
        """Remove stale pending file if older than PENDING_TTL and tmux session dead."""
        if not self.pending_file.exists():
            return
        try:
            age = time.time() - self.pending_file.stat().st_mtime
            if age > PENDING_TTL and not self._tmux_session_exists():
                self.pending_file.unlink()
                logger.info("Cleaned stale pending file (%.0fs old)", age)
        except OSError as e:
            logger.warning("Failed to clean stale pending file: %s", e)

    def _finalize_superseded_pending(self, new_message_id: int) -> None:
        """Clean stale pending and finalize stranded placeholder on overwrite."""
        self.clean_stale_pending()
        if not self.pending_file.exists():
            return
        try:
            prev = json.loads(self.pending_file.read_text(encoding="utf-8"))
            if not prev.get("delivered"):
                prev_id = prev.get("message_id", "?")
                logger.warning(
                    "Overwriting undelivered pending (msg_id=%s) with new message %d",
                    prev_id,
                    new_message_id,
                )
                prev_proc_id = prev.get("processing_message_id")
                prev_chat_id = prev.get("chat_id")
                if prev_proc_id and prev_chat_id:
                    self.edit_message(
                        prev_chat_id,
                        prev_proc_id,
                        "⏭ Superseded by newer message",
                    )
        except (json.JSONDecodeError, OSError):
            pass

    def _resolve_active_transcript(self) -> tuple[str | None, int]:
        """Identify the ACTIVE Claude JSONL transcript and return its path and line count.

        Prefers the CC-native transcript path when available (set by CC session
        discovery in ensure_tmux_session). Falls back to PID-based fd scanning
        and mtime heuristic.
        """
        # Strategy 0: CC-native transcript path (set by _discover_cc_session)
        if self._active_transcript_path and self._active_transcript_path.exists():
            return str(self._active_transcript_path), self._count_file_lines(self._active_transcript_path)

        slug = str(self.work_dir).replace("\\", "-").replace("/", "-")
        projects_dir = Path.home() / ".claude" / "projects" / slug
        if not projects_dir.exists():
            return None, 0

        jsonl_files = list(projects_dir.glob("*.jsonl"))
        if not jsonl_files:
            return None, 0

        # Strategy 1: find the JSONL open by a child of the tmux pane
        pane_pid = self._get_tmux_pane_pid()
        if pane_pid:
            target_names = {f.name for f in jsonl_files}
            found = self._find_open_jsonl(pane_pid, projects_dir, target_names)
            if found:
                return str(found), self._count_file_lines(found)

        # Strategy 2: most recently modified JSONL, but only if touched < 5 min ago
        now = time.time()
        recent = sorted(
            ((f, f.stat().st_mtime) for f in jsonl_files),
            key=lambda x: x[1],
            reverse=True,
        )
        if recent and (now - recent[0][1]) < 300:
            return str(recent[0][0]), self._count_file_lines(recent[0][0])

        return None, 0

    def _find_open_jsonl(self, pane_pid: int, projects_dir: Path, target_names: set[str]) -> Path | None:
        """Scan /proc fd links for descendant PIDs to find an open JSONL in *projects_dir*."""
        child_pids = self._get_descendant_pids(pane_pid)
        for pid in child_pids:
            match = self._scan_pid_fds(pid, projects_dir, target_names)
            if match:
                return match
        return None

    @staticmethod
    def _scan_pid_fds(pid: int, projects_dir: Path, target_names: set[str]) -> Path | None:
        """Check /proc/<pid>/fd/ for an open JSONL matching *target_names*."""
        fd_dir = Path(f"/proc/{pid}/fd")
        try:
            entries = list(fd_dir.iterdir())
        except OSError as e:
            logger.info("Cannot list fds for pid %d: %s", pid, e)
            return None
        for fd in entries:
            try:
                target = fd.resolve()
            except OSError as e:
                logger.info("Cannot resolve fd %s: %s", fd.name, e)
                continue
            if target.parent == projects_dir and target.name in target_names:
                return target
        return None

    def _get_tmux_pane_pid(self) -> int | None:
        """Get the shell PID of the first pane in the current tmux session."""
        try:
            result = subprocess.run(
                ["tmux", "list-panes", "-t", self.session_name, "-F", "#{pane_pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip().split("\n")[0])
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
            logger.info("Could not get tmux pane PID: %s", e)
        return None

    @staticmethod
    def _get_descendant_pids(parent_pid: int) -> list[int]:
        """Walk /proc to collect all descendant PIDs of *parent_pid*."""
        children: dict[int, list[int]] = {}
        try:
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    stat_text = (entry / "stat").read_text(encoding="utf-8")
                    ppid = int(stat_text.split(") ")[1].split()[1])
                    children.setdefault(ppid, []).append(int(entry.name))
                except (OSError, IndexError, ValueError) as e:
                    logger.info("Skipping /proc/%s/stat: %s", entry.name, e)
                    continue
        except OSError as e:
            logger.info("Cannot scan /proc for descendant PIDs: %s", e)
            return []
        result: list[int] = []
        queue = children.get(parent_pid, [])[:]
        while queue:
            pid = queue.pop()
            result.append(pid)
            queue.extend(children.get(pid, []))
        return result

    @staticmethod
    def _count_file_lines(path: Path) -> int:
        """Count newline-delimited lines in *path*."""
        try:
            text = path.read_text(encoding="utf-8").strip()
            return len(text.split("\n")) if text else 0
        except OSError as e:
            logger.warning("Could not read transcript for line count: %s", e)
            return 0

    def _get_transcript_line_count(self) -> int:
        """Count lines in the active JSONL transcript (compat shim)."""
        _, count = self._resolve_active_transcript()
        return count

    # =============================================
    # CC-NATIVE SESSION DISCOVERY (DPLAN-0226)
    # =============================================

    def _discover_cc_session(self) -> dict | None:
        """Discover the active CC session for this bot's branch.

        Enumerates ~/.claude/sessions/<pid>.json, filters by cwd matching
        this bot's work_dir, confirms PID alive. Returns the latest session
        (by startedAt) or None. CC keeps these current across /resume and
        deletes on exit, so re-binding is automatic.
        """
        if not CC_SESSIONS_DIR.is_dir():
            return None
        target_cwd = str(self.work_dir.resolve())
        best = None
        for f in CC_SESSIONS_DIR.iterdir():
            if not f.name.endswith(".json") or not f.stem.isdigit():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.info("Failed to read CC session file %s: %s", f, exc)
                continue
            session_cwd = data.get("cwd", "")
            if not session_cwd:
                continue
            if str(Path(session_cwd).resolve()) != target_cwd:
                continue
            pid = data.get("pid")
            if not pid or not self._is_pid_alive(pid):
                continue
            if best is None or data.get("startedAt", 0) > best.get("startedAt", 0):
                best = data
        return best

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process with the given PID exists. Cross-platform."""
        if pid <= 1:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel32.OpenProcess.restype = wintypes.HANDLE
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    return False
                try:
                    exit_code = wintypes.DWORD()
                    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
                    if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return False
                    return exit_code.value == 259
                finally:
                    kernel32.CloseHandle(handle)
            except Exception as exc:
                logger.info("PID %d Windows check failed (assuming alive): %s", pid, exc)
                return True
        else:
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                logger.info("PID %d not found (dead)", pid)
                return False
            except PermissionError:
                logger.info("PID %d exists but permission denied — treating as alive", pid)
                return True
            except OSError as exc:
                logger.info("PID %d liveness check failed: %s — treating as dead", pid, exc)
                return False

    def _find_tmux_pane_by_cwd(self) -> str | None:
        """Find a tmux session with a pane whose CWD matches this bot's work_dir."""
        try:
            result = subprocess.run(
                ["tmux", "list-panes", "-a", "-F", "#{session_name}:#{pane_current_path}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None
            target = str(self.work_dir.resolve())
            for line in result.stdout.strip().split("\n"):
                if ":" not in line:
                    continue
                session_name, pane_path = line.split(":", 1)
                if str(Path(pane_path).resolve()) == target:
                    return session_name
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.info("tmux pane scan failed: %s", exc)
        return None

    @staticmethod
    def _sanitize_path_for_cc(path_str: str) -> str:
        """Sanitize a path for CC projects dir (every non-alphanumeric char becomes '-')."""
        return re.sub(r"[^a-zA-Z0-9]", "-", path_str)

    def _resolve_cc_transcript_path(self, session: dict) -> Path | None:
        """Resolve the transcript JSONL path from a CC session entry."""
        session_id = session.get("sessionId")
        cwd = session.get("cwd", "")
        if not session_id or not cwd:
            return None
        slug = self._sanitize_path_for_cc(cwd)
        transcript = Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"
        if transcript.exists():
            return transcript
        return None

    @staticmethod
    def _extract_assistant_text(entry: dict) -> str | None:
        """Extract text content from a transcript entry if it's an assistant message."""
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            return None
        content = msg.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
        return None

    def _read_transcript_tail(self, n_lines: int = 50) -> str | None:
        """Read the latest assistant text response from the active transcript.

        Scans the last n_lines of the transcript JSONL for the most recent
        assistant message with text content.
        """
        path = self._active_transcript_path
        if not path or not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return None
            lines = text.split("\n")
            tail = lines[-n_lines:] if len(lines) > n_lines else lines
            for line in reversed(tail):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.info("Malformed JSONL line in transcript tail")
                    continue
                result = self._extract_assistant_text(entry)
                if result is not None:
                    return result
        except OSError as exc:
            logger.info("Failed to read transcript tail: %s", exc)
        return None

    # =============================================
    # DORMANT: PRESENCE POINTER (DPLAN-0226)
    # Discovery replaced by CC-native ~/.claude/sessions.
    # Guard half (presence_gate) stays LIVE in @hooks.
    # Kept per Patrick's directive — do not delete.
    # =============================================

    # def _find_presence_file(self) -> Path | None:
    #     """Locate .ai_central/PRESENCE.central.json by walking up from work_dir."""
    #     current = self.work_dir.resolve()
    #     for _ in range(20):
    #         candidate = current / ".ai_central" / "PRESENCE.central.json"
    #         if candidate.exists():
    #             return candidate
    #         if current.parent == current:
    #             break
    #         current = current.parent
    #     return None
    #
    # def _read_presence_pointer(self) -> dict | None:
    #     """Read the central presence pointer for this bot's branch."""
    #     presence_file = self._find_presence_file()
    #     if presence_file is None:
    #         return None
    #     try:
    #         data = json.loads(presence_file.read_text(encoding="utf-8"))
    #     except (json.JSONDecodeError, OSError):
    #         return None
    #     branch = self.branch_name or self.work_dir.name
    #     entry = data.get(branch)
    #     if not entry:
    #         return None
    #     pid = entry.get("pid")
    #     if pid is None:
    #         return None
    #     try:
    #         os.kill(pid, 0)
    #     except ProcessLookupError:
    #         return None
    #     except PermissionError:
    #         pass
    #     except OSError:
    #         return None
    #     return entry
    #
    # def _find_tmux_for_presence(self, entry: dict) -> str | None:
    #     """Find the tmux session for a presence entry."""
    #     handle = entry.get("attach_handle", "")
    #     if handle:
    #         try:
    #             result = subprocess.run(
    #                 ["tmux", "has-session", "-t", handle],
    #                 capture_output=True,
    #                 timeout=5,
    #             )
    #             if result.returncode == 0:
    #                 return handle
    #         except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
    #             pass
    #     work_dir = entry.get("work_dir", "")
    #     if not work_dir:
    #         return None
    #     try:
    #         result = subprocess.run(
    #             ["tmux", "list-panes", "-a", "-F",
    #              "#{session_name}:#{pane_current_path}"],
    #             capture_output=True, text=True, timeout=5,
    #         )
    #         if result.returncode != 0:
    #             return None
    #         target = str(Path(work_dir).resolve())
    #         for line in result.stdout.strip().split("\n"):
    #             if ":" not in line:
    #                 continue
    #             session_name, pane_path = line.split(":", 1)
    #             if str(Path(pane_path).resolve()) == target:
    #                 return session_name
    #     except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
    #         pass
    #     return None

    def _write_mirror_mapping(self) -> None:
        """Write persistent mirror mapping file per THE CONTRACT (TDPLAN-0009).

        Written at first successful attach AND rewritten whenever the active
        transcript changes (session restart).  @hooks reads this every turn
        to find the chat_id and cursor for mirror delivery.
        """
        if not self._attach_only:
            return

        chat_id = self._active_chat_id or getattr(self, "_config_chat_id", None)
        if chat_id is None:
            return

        transcript_path, line_count = self._resolve_active_transcript()

        if self._mirror_mapping_written:
            if transcript_path == self._last_transcript_path:
                return
            logger.info(
                "Transcript changed (%s → %s) — rewriting mirror mapping",
                self._last_transcript_path,
                transcript_path,
            )

        mapping_dir = Path.home() / ".aipass" / "telegram_bots"
        mapping_dir.mkdir(parents=True, exist_ok=True)
        mapping_file = mapping_dir / f"bot-{self.bot_id}.json"

        mapping = {
            "chat_id": chat_id,
            "bot_token": self.bot_token,
            "session_name": self.session_name,
            "work_dir": str(self.work_dir),
            "mirror": True,
            "transcript_line_after": line_count,
        }

        try:
            mapping_file.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
            self._mirror_mapping_written = True
            self._last_transcript_path = transcript_path
            logger.info("Mirror mapping written: %s (cursor=%d)", mapping_file, line_count)
        except OSError as e:
            logger.error("Failed to write mirror mapping: %s", e)

    # =============================================
    # HEARTBEAT THREAD
    # =============================================

    def _start_heartbeat(self, chat_id: int, processing_msg_id: int) -> None:
        """
        Start a background thread that updates the "Processing..." message.

        In batch mode (default): edits with elapsed time every 30s.
        In stream mode: tails transcript and edits with live content every 2s.

        Args:
            chat_id: Chat ID where the processing message was sent
            processing_msg_id: Message ID of the "Processing..." message
        """
        self._stop_heartbeat()  # Ensure no stale thread
        self._heartbeat_stop.clear()
        self._heartbeat_gen += 1
        gen = self._heartbeat_gen

        def _heartbeat_loop():
            start = time.time()

            # Streaming mode (FPLAN-0297): live transcript tail
            if self._stream and self._active_transcript_path:
                self._streaming_loop(chat_id, processing_msg_id, start, gen)
                return

            # Batch mode (default): elapsed-time updates
            while not self._heartbeat_stop.is_set():
                self._heartbeat_stop.wait(HEARTBEAT_INTERVAL)
                if self._heartbeat_stop.is_set():
                    break

                # Stop if response has been delivered or tmux died
                if self._is_pending_delivered():
                    break
                if not self._tmux_session_exists():
                    break
                if self._heartbeat_gen != gen:
                    break

                elapsed = time.time() - start
                elapsed_str = self._format_elapsed(elapsed)
                if self._is_pending_delivered() or self._heartbeat_gen != gen:
                    break
                self.edit_message(chat_id, processing_msg_id, f"Processing... ({elapsed_str})")

        self._heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name=f"heartbeat-{self.bot_id}")
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        """Signal the heartbeat thread to stop and wait for it."""
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)
        self._heartbeat_thread = None

    def _is_pending_delivered(self) -> bool:
        """Check if the pending file has been marked as delivered by @hooks."""
        if not self.pending_file.exists():
            return True
        try:
            data = json.loads(self.pending_file.read_text(encoding="utf-8"))
            return bool(data.get("delivered"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read pending file %s: %s", self.pending_file, e)
            return False

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """
        Format elapsed seconds as human-readable string.

        Args:
            seconds: Elapsed time in seconds

        Returns:
            Formatted string like "30s", "1m 0s", "2m 30s"
        """
        total = int(seconds)
        if total < 60:
            return f"{total}s"
        minutes, secs = divmod(total, 60)
        return f"{minutes}m {secs}s"

    # =============================================
    # STREAMING EDIT-IN-PLACE (FPLAN-0297)
    # =============================================

    def _streaming_loop(self, chat_id: int, msg_id: int, start_time: float, gen: int) -> None:
        """Stream transcript content into the processing message via edit-in-place."""
        path = self._active_transcript_path
        try:
            byte_offset = path.stat().st_size if path else 0
        except OSError as exc:
            logger.info("Cannot stat transcript for streaming: %s", exc)
            byte_offset = 0

        buffer = ""
        last_sent = ""
        current_msg_id = msg_id
        retry_after_until = 0.0

        while not self._heartbeat_stop.is_set():
            self._heartbeat_stop.wait(STREAM_INTERVAL)
            if self._heartbeat_stop.is_set():
                break
            if self._heartbeat_gen != gen:
                break
            if self._is_pending_delivered():
                break
            if not self._tmux_session_exists():
                break

            new_entries, byte_offset = self._tail_transcript_bytes(path, byte_offset)
            new_text = self._format_stream_entries(new_entries)
            if new_text:
                buffer += new_text

            if self._is_pending_delivered() or self._heartbeat_gen != gen:
                break

            if not buffer:
                elapsed = time.time() - start_time
                placeholder = f"Processing... ({self._format_elapsed(elapsed)})"
                now = time.time()
                if placeholder != last_sent and now >= retry_after_until:
                    if self._is_pending_delivered() or self._heartbeat_gen != gen:
                        break
                    ok, retry = self._stream_edit(chat_id, current_msg_id, placeholder)
                    retry_after_until = now + retry if retry > 0 else retry_after_until
                    last_sent = placeholder if ok else last_sent
                continue

            if buffer == last_sent:
                continue

            now = time.time()
            if now < retry_after_until:
                continue

            if self._is_pending_delivered() or self._heartbeat_gen != gen:
                break

            if len(buffer) > TELEGRAM_CHAR_LIMIT:
                break_at = buffer.rfind("\n", 0, TELEGRAM_CHAR_LIMIT)
                if break_at < TELEGRAM_CHAR_LIMIT // 2:
                    break_at = TELEGRAM_CHAR_LIMIT
                final_chunk = buffer[:break_at].rstrip()
                self._stream_edit(chat_id, current_msg_id, final_chunk)
                buffer = buffer[break_at:].lstrip()
                initial = buffer[:TELEGRAM_CHAR_LIMIT] or "..."
                result = self.send_message(chat_id, initial)
                if result:
                    current_msg_id = result.get("message_id", current_msg_id)
                last_sent = initial
                continue

            ok, retry = self._stream_edit(chat_id, current_msg_id, buffer)
            if retry > 0:
                retry_after_until = now + retry
            if ok:
                last_sent = buffer

    def _tail_transcript_bytes(self, path: Path | None, byte_offset: int) -> tuple[list[dict], int]:
        """Incrementally tail a JSONL transcript from byte_offset."""
        if not path:
            return [], byte_offset
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                file_size = f.tell()
                if file_size <= byte_offset:
                    return [], byte_offset
                f.seek(byte_offset)
                new_bytes = f.read()
        except OSError as exc:
            logger.info("Cannot read transcript for streaming tail: %s", exc)
            return [], byte_offset

        last_newline = new_bytes.rfind(b"\n")
        if last_newline == -1:
            return [], byte_offset

        complete = new_bytes[: last_newline + 1]
        entries = []
        for line_bytes in complete.split(b"\n"):
            line_str = line_bytes.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue
            try:
                entries.append(json.loads(line_str))
            except json.JSONDecodeError:
                logger.info("Malformed JSONL line in streaming tail")

        return entries, byte_offset + len(complete)

    @staticmethod
    def _format_content_block(block: dict) -> str | None:
        """Map a single transcript content block to plain-text display."""
        if not isinstance(block, dict):
            return None
        btype = block.get("type", "")
        if btype == "text":
            text = block.get("text", "")
            return text if text.strip() else None
        if btype == "thinking":
            return "Thinking..."
        if btype == "tool_use":
            return f"Running {block.get('name', 'tool')}..."
        return None

    @staticmethod
    def _format_stream_entries(entries: list[dict]) -> str:
        """Block-map transcript entries to plain-text streaming content."""
        parts: list[str] = []
        for entry in entries:
            if entry.get("isSidechain"):
                continue
            msg = entry.get("message", {})
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if isinstance(content, str):
                if content.strip():
                    parts.append(content)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                mapped = BaseBot._format_content_block(block)
                if mapped is not None:
                    parts.append(mapped)
        if not parts:
            return ""
        return "\n".join(parts) + "\n"

    def _stream_edit(self, chat_id: int, message_id: int, text: str) -> tuple[bool, float]:
        """Edit a message with 429/not-modified handling for streaming.

        Returns (success, retry_after_seconds). retry_after > 0 means rate-limited.
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(url, data=data, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            return result.get("ok", False), 0.0
        except HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception as parse_err:
                logger.info("Cannot parse stream edit error body: %s", parse_err)
                body = {}
            if e.code == 429:
                retry = body.get("parameters", {}).get("retry_after", 30)
                logger.info("Stream edit 429 — backing off %ds", retry)
                return False, float(retry)
            if e.code == 400 and "not modified" in body.get("description", ""):
                return True, 0.0
            logger.warning("Stream edit HTTP %d: %s", e.code, body.get("description", ""))
            return False, 0.0
        except Exception as e:
            logger.warning("Stream edit error: %s", e)
            return False, 0.0

    # =============================================
    # OVERRIDABLE HOOKS
    # =============================================

    def on_message(self, text: str) -> str:
        """
        Hook: pre-process message text before tmux injection.

        Override in subclasses to modify the prompt sent to Claude.

        Args:
            text: Raw message text

        Returns:
            Processed text to inject into tmux
        """
        return text

    def on_response(self, text: str) -> str:
        """
        Hook: post-process response text before sending to Telegram.

        Override in subclasses to modify Claude's response.

        Args:
            text: Raw response text from Claude

        Returns:
            Processed text to send to Telegram
        """
        return text

    def _set_command_menu(self) -> None:
        """Set the Telegram command menu via setMyCommands on startup."""
        merged_commands = {**self.custom_commands, **self.get_custom_commands()}
        commands = build_botfather_commands(custom_commands=merged_commands or None)
        if self.bot_token:
            ok = set_bot_commands(self.bot_token, commands)
            if ok:
                logger.info("Command menu set (%d commands)", len(commands))
            else:
                logger.warning("Failed to set command menu")

    # =============================================
    # /MONITOR — SYSTEM-WIDE LOG SUBSCRIPTION
    # =============================================

    def _handle_monitor_command(self, chat_id: int, args: str) -> None:
        """Route /monitor subcommands: on, all, off, status."""
        subcmd = args.strip().lower().split()[0] if args.strip() else ""

        if subcmd == "on":
            self._monitor_subscribe(chat_id, mode="default")
        elif subcmd == "all":
            self._monitor_subscribe(chat_id, mode="all")
        elif subcmd == "off":
            self._monitor_unsubscribe(chat_id)
        elif subcmd == "status":
            self._monitor_status(chat_id)
        else:
            self.send_message(
                chat_id,
                "/monitor on \u2014 errors & warnings\n"
                "/monitor all \u2014 everything (firehose)\n"
                "/monitor off \u2014 unsubscribe\n"
                "/monitor status \u2014 current state",
            )

    def _monitor_subscribe(self, chat_id: int, mode: str) -> None:
        """Subscribe this chat to the system-wide log monitor."""
        # Stop any existing monitor streamer
        if self._monitor_streamer is not None:
            self._monitor_streamer.stop()
            self._monitor_streamer = None

        # Persist subscription
        if not self._save_monitor_subscription(chat_id, mode):
            self.send_message(chat_id, "Failed to save monitor subscription.")
            return

        # Start streamer
        self._monitor_streamer = LogStreamer(
            self.bot_token,
            chat_id,
            branch_name="monitor",
            system_wide=True,
            level_filter=mode,
        )
        self._monitor_streamer.start()

        mode_label = "errors & warnings" if mode == "default" else "all levels (firehose)"
        self.send_message(
            chat_id,
            f"Monitor subscribed: {mode_label}\n\n/monitor off to unsubscribe\n/monitor all for firehose mode",
        )
        logger.info("Monitor subscribed: chat_id=%s, mode=%s", chat_id, mode)

    def _monitor_unsubscribe(self, chat_id: int) -> None:
        """Unsubscribe from the system-wide log monitor."""
        if self._monitor_streamer is not None:
            self._monitor_streamer.stop()
            self._monitor_streamer = None

        self._clear_monitor_subscription()
        self.send_message(chat_id, "Monitor unsubscribed. No more log alerts.")
        logger.info("Monitor unsubscribed: chat_id=%s", chat_id)

    def _monitor_status(self, chat_id: int) -> None:
        """Show current monitor subscription status."""
        sub = self._load_monitor_subscription()
        if not sub or not sub.get("chat_id"):
            self.send_message(chat_id, "Monitor: not subscribed.\n\n/monitor on to start.")
            return

        sub_chat = sub["chat_id"]
        mode = sub.get("mode", "default")
        mode_label = "errors & warnings" if mode == "default" else "all levels (firehose)"
        is_this_chat = "(this chat)" if sub_chat == chat_id else f"(chat {sub_chat})"
        running = self._monitor_streamer is not None and self._monitor_streamer._running
        state = "streaming" if running else "paused"

        self.send_message(
            chat_id,
            f"Monitor: {state}\nMode: {mode_label}\nTarget: {is_this_chat}",
        )

    def _boot_monitor(self) -> None:
        """Start the monitor streamer from persisted subscription on boot."""
        sub = self._load_monitor_subscription()
        if not sub or not sub.get("chat_id"):
            return

        chat_id = sub["chat_id"]
        mode = sub.get("mode", "default")

        self._monitor_streamer = LogStreamer(
            self.bot_token,
            chat_id,
            branch_name="monitor",
            system_wide=True,
            level_filter=mode,
        )
        self._monitor_streamer.start()
        logger.info("Boot-started monitor streamer (chat_id=%s, mode=%s)", chat_id, mode)

    def _monitor_subscription_file(self) -> Path:
        """Return path to the local monitor subscription file."""
        return Path.home() / ".aipass" / "telegram_bots" / f".{self.bot_id}_monitor.json"

    def _load_monitor_subscription(self) -> dict | None:
        """Load monitor subscription from local state file."""
        sub_file = self._monitor_subscription_file()
        if not sub_file.exists():
            return None
        try:
            data = json.loads(sub_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("chat_id"):
                return data
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load monitor subscription: %s", e)
            return None

    def _save_monitor_subscription(self, chat_id: int, mode: str) -> bool:
        """Persist monitor subscription to local state file."""
        sub_file = self._monitor_subscription_file()
        try:
            sub_file.parent.mkdir(parents=True, exist_ok=True)
            sub_file.write_text(
                json.dumps({"chat_id": chat_id, "mode": mode}, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError as e:
            logger.error("Failed to save monitor subscription: %s", e)
            return False

    def _clear_monitor_subscription(self) -> bool:
        """Clear persisted monitor subscription."""
        sub_file = self._monitor_subscription_file()
        try:
            sub_file.unlink(missing_ok=True)
            return True
        except OSError as e:
            logger.error("Failed to clear monitor subscription: %s", e)
            return False

    # =============================================
    # /LOGS — SESSION LOG STREAM CONTROL
    # =============================================

    def _handle_logs_command(self, chat_id: int, args: str) -> None:
        """Route /logs subcommands: on, off, errors, status."""
        if self.branch_name is None:
            self.send_message(chat_id, "Not available — this bot has no branch log stream.")
            return

        subcmd = args.strip().lower().split()[0] if args.strip() else ""

        if subcmd == "on":
            self._logs_start(chat_id, mode="all")
        elif subcmd == "off":
            self._logs_stop(chat_id)
        elif subcmd == "errors":
            self._logs_start(chat_id, mode="default")
        elif subcmd == "status":
            self._logs_status(chat_id)
        else:
            self.send_message(
                chat_id,
                "/logs on — full log stream\n"
                "/logs errors — warnings & errors only\n"
                "/logs off — stop streaming\n"
                "/logs status — current state",
            )

    def _logs_start(self, chat_id: int, mode: str) -> None:
        """Start or restart the session log streamer with the given mode."""
        if self._log_streamer is not None:
            self._log_streamer.stop()
            self._log_streamer = None

        if not self._save_logs_preference(chat_id, mode):
            self.send_message(chat_id, "Failed to save logs preference.")
            return

        self._log_streamer = LogStreamer(
            self.bot_token,
            chat_id,
            self.branch_name,  # type: ignore[arg-type]  # guarded by _handle_logs_command
            level_filter=mode,
        )
        self._log_streamer.start()

        mode_label = "all levels" if mode == "all" else "errors & warnings"
        self.send_message(
            chat_id,
            f"Log streaming: {mode_label}\n\n/logs off to stop\n/logs errors for filtered mode",
        )
        logger.info("Log streaming started: chat_id=%s, mode=%s, branch=%s", chat_id, mode, self.branch_name)

    def _logs_stop(self, chat_id: int) -> None:
        """Stop the session log streamer."""
        if self._log_streamer is not None:
            self._log_streamer.stop()
            self._log_streamer = None

        self._save_logs_preference(chat_id, "off")
        self.send_message(chat_id, "Log streaming stopped.\n\n/logs on to resume.")
        logger.info("Log streaming stopped: chat_id=%s, branch=%s", chat_id, self.branch_name)

    def _logs_status(self, chat_id: int) -> None:
        """Show current log streaming status."""
        pref = self._load_logs_preference()
        running = self._log_streamer is not None and self._log_streamer._running

        if not running:
            mode_info = ""
            if pref and pref.get("mode") == "off":
                mode_info = " (disabled)"
            self.send_message(chat_id, f"Log streaming: stopped{mode_info}\n\n/logs on to start.")
            return

        mode = pref.get("mode", "all") if pref else "all"
        mode_label = "all levels" if mode == "all" else "errors & warnings"
        self.send_message(
            chat_id,
            f"Log streaming: active\nMode: {mode_label}\nBranch: {self.branch_name}",
        )

    def _logs_preference_file(self) -> Path:
        """Return path to the local logs preference file."""
        return Path.home() / ".aipass" / "telegram_bots" / f".{self.bot_id}_logs.json"

    def _load_logs_preference(self) -> dict | None:
        """Load logs preference from local state file."""
        pref_file = self._logs_preference_file()
        if not pref_file.exists():
            return None
        try:
            data = json.loads(pref_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load logs preference: %s", e)
            return None

    def _save_logs_preference(self, chat_id: int, mode: str) -> bool:
        """Persist logs preference to local state file."""
        pref_file = self._logs_preference_file()
        try:
            pref_file.parent.mkdir(parents=True, exist_ok=True)
            pref_file.write_text(
                json.dumps({"chat_id": chat_id, "mode": mode}, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError as e:
            logger.error("Failed to save logs preference: %s", e)
            return False

    def get_custom_commands(self) -> dict:
        """
        Hook: return additional bot-specific commands.

        Override in subclasses to add custom commands to /help and /start.
        Base implementation includes /create and /cancel for bot management.

        Returns:
            Dict of commands in telegram_standards format
        """
        commands = {
            "monitor": {
                "description": "Subscribe to system-wide log alerts — /monitor on, off, all, status",
                "menu_text": "Log monitor",
            },
        }
        if self.branch_name is not None:
            commands["logs"] = {
                "description": "Control branch log streaming — /logs on, off, errors, status",
                "menu_text": "Log streaming",
            }
        if self.branch_name is None:
            commands["create"] = {
                "description": "Create a Telegram bot for a branch — e.g. /create chat devpulse",
                "menu_text": "New branch bot",
            }
            commands["cancel"] = {
                "description": "Cancel an in-progress /create",
                "menu_text": "Cancel create",
            }
        return commands

    # =============================================
    # LOCK FILE MANAGEMENT
    # =============================================

    def _create_lock(self) -> None:
        """Write PID to lock file."""
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_file.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "started": datetime.now().isoformat(),
                        "session": self.session_name,
                        "bot_id": self.bot_id,
                    }
                ),
                encoding="utf-8",
            )
            logger.info("Lock file created: %s", self._lock_file)
        except OSError as e:
            logger.error("Failed to create lock file: %s", e)

    def _remove_lock(self) -> None:
        """Delete the lock file."""
        try:
            if self._lock_file.exists():
                self._lock_file.unlink()
                logger.info("Lock file removed")
        except OSError as e:
            logger.error("Failed to remove lock file: %s", e)

    def _check_lock(self) -> bool:
        """
        Check if another instance of this bot is running.

        Verifies both PID liveness AND that the process is actually this bot.
        Handles PID reuse: if the PID is alive but belongs to a different
        process, the lock is treated as stale and cleaned.

        Returns:
            True if another live instance holds the lock, False otherwise
        """
        if not self._lock_file.exists():
            return False

        try:
            lock_data = json.loads(self._lock_file.read_text(encoding="utf-8"))
            pid = lock_data.get("pid", 0)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Stale or corrupt lock file, removing: %s", e)
            self._lock_file.unlink(missing_ok=True)
            return False

        if not pid:
            return False

        if not self._is_pid_alive(pid):
            logger.info("Cleaning stale lock (PID %d is dead)", pid)
            self._lock_file.unlink(missing_ok=True)
            return False

        # PID is alive — verify it's actually this bot (not PID reuse)
        if sys.platform != "win32":
            try:
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
                cmd_str = cmdline.decode("utf-8", errors="replace").replace("\x00", " ")
                if f"--bot-id {self.bot_id}" not in cmd_str:
                    logger.info("Cleaning stale lock (PID %d is alive but not bot-%s)", pid, self.bot_id)
                    self._lock_file.unlink(missing_ok=True)
                    return False
            except OSError:
                logger.info("Could not read /proc/%d/cmdline — trusting PID liveness check", pid)

        return True

    # =============================================
    # SIGNAL HANDLING
    # =============================================

    def _shutdown_handler(self, signum, _frame) -> None:
        """Handle SIGTERM/SIGINT for clean shutdown."""
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Received %s, shutting down...", sig_name)
        self.state["running"] = False

    def _cleanup(self) -> None:
        """Clean up resources on exit."""
        if self._monitor_streamer is not None:
            self._monitor_streamer.stop()
            self._monitor_streamer = None
        if self._log_streamer is not None:
            self._log_streamer.stop()
            self._log_streamer = None
        self._stop_heartbeat()
        self._remove_lock()
        logger.info("Bot stopped")

    # =============================================
    # OFFSET PERSISTENCE
    # =============================================

    def _load_offset(self) -> int:
        """Load the last processed update offset from disk."""
        if not self._offset_file.exists():
            return 0
        try:
            with open(self._offset_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("offset", 0)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load offset file, starting from 0: %s", e)
            return 0

    def _save_offset(self, offset: int) -> None:
        """Persist the current update offset to disk."""
        self._offset_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._offset_file, "w", encoding="utf-8") as f:
                json.dump({"offset": offset, "updated": datetime.now().isoformat()}, f)
        except OSError as e:
            logger.error("Failed to save offset: %s", e)


# =============================================
# CLI ENTRY POINT
# =============================================

_BOT_CLASSES = {
    "scheduler": ".scheduler_bot:SchedulerBot",
    "prax_monitor": ".prax_monitor_bot:PraxMonitorBot",
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AIPass Telegram Bot")
    parser.add_argument("--bot-id", required=True, help="Bot identifier")
    args = parser.parse_args()

    from .config import load_bot_config

    config = load_bot_config(args.bot_id)
    if not config:
        print(f"No config found for bot_id={args.bot_id}")
        sys.exit(1)

    bot_cls = BaseBot
    if args.bot_id in _BOT_CLASSES:
        mod_name, cls_name = _BOT_CLASSES[args.bot_id].rsplit(":", 1)
        import importlib

        mod = importlib.import_module(mod_name, package=__package__)
        bot_cls = getattr(mod, cls_name)

    bot = bot_cls(
        bot_id=args.bot_id,
        bot_token=config["bot_token"],
        work_dir=Path(config.get("work_dir", str(Path.home()))),
        bot_name=config.get("bot_name", "AIPass Bot"),
        allowed_user_ids=config.get("allowed_user_ids", []),
        branch_name=config.get("branch_name"),
        shared_session=config.get("shared_session"),
        attach_only=config.get("attach_only", False),
        stream=config.get("stream", False),
    )

    if config.get("chat_id"):
        bot._config_chat_id = config["chat_id"]

    sys.exit(bot.run())
