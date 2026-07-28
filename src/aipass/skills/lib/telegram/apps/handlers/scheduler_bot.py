# =================== AIPass ====================
# Name: scheduler_bot.py
# Description: Dedicated Telegram bot for the daemon's job queue — announce/query only
# Version: 1.0.1
# Created: 2026-06-25
# Modified: 2026-07-23
# =============================================

"""
SchedulerBot — a BaseBot subclass for the AIPass Scheduler.

Pure announce/query bot: serves /queue, posts an hourly digest, receives
lifecycle pings from @daemon. Free-text messages do NOT spin up tmux/Claude.
"""

import json
import subprocess
import threading
from typing import Optional

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler

from .base_bot import BaseBot


DIGEST_INTERVAL = 3600.0
QUEUE_CMD = ["drone", "@daemon", "queue", "--json"]


class SchedulerBot(BaseBot):
    """Dedicated scheduler bot — no tmux/Claude, just /queue and hourly digest."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._digest_thread: Optional[threading.Thread] = None
        self._digest_stop = threading.Event()
        self._scheduler_chat_id: Optional[int] = None

    def handle_message(self, chat_id: int, text: str, message: dict) -> None:
        """Reject free-text — this bot only serves commands (no tmux/Claude spawn)."""
        self.send_message(
            chat_id,
            "I'm the scheduler bot — I only handle commands.\nTry /queue or /help",
        )

    def handle_file(self, chat_id: int, message: dict) -> None:
        """Reject files — this bot only serves commands."""
        self.send_message(chat_id, "I don't process files. Try /queue or /help")

    def _dispatch_command(self, chat_id: int, parsed: tuple) -> bool:
        cmd_name, cmd_args = parsed
        if cmd_name == "queue":
            self._handle_queue_command(chat_id)
            return True
        return super()._dispatch_command(chat_id, parsed)

    def get_custom_commands(self) -> dict:
        """Add /queue to the slash-menu alongside the inherited commands."""
        cmds = super().get_custom_commands()
        cmds["queue"] = {
            "description": "Show all scheduled daemon jobs — next fire, status, type",
            "menu_text": "Job queue",
        }
        return cmds

    def _handle_queue_command(self, chat_id: int) -> None:
        """Fetch queue from daemon and send formatted message."""
        json_handler.log_operation("queue_requested", {"chat_id": chat_id})
        queue_data = self._fetch_queue()
        if queue_data is None:
            self.send_message(chat_id, "Failed to fetch queue from daemon.")
            return

        text = self._format_queue(queue_data)
        for chunk in self.chunk_text(text):
            self.send_message(chat_id, chunk)

    def _fetch_queue(self) -> Optional[dict]:
        """Run drone @daemon queue --json and parse the result."""
        try:
            result = subprocess.run(
                QUEUE_CMD,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.warning("queue --json failed (rc=%d): %s", result.returncode, result.stderr)
                return None
            decoder = json.JSONDecoder(strict=False)
            return decoder.decode(result.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to fetch queue: %s", e)
            return None

    @staticmethod
    def _format_queue(data: dict) -> str:
        """Format queue JSON into a readable Telegram message."""
        jobs = data.get("jobs", [])
        count = data.get("count", len(jobs))
        generated = data.get("generated_at", "unknown")

        if not jobs:
            return f"No scheduled jobs.\n\nGenerated: {generated}"

        lines = [f"Scheduled Jobs ({count})\n"]
        for job in jobs:
            owner = job.get("owner", "?")
            job_id = job.get("id", "?")
            enabled = job.get("enabled", False)
            jtype = job.get("type", "?")
            schedule = job.get("schedule_human", "?")
            next_run = job.get("next_run") or "—"
            last_status = job.get("last_status") or "never run"
            last_error = job.get("last_error")
            prompt = job.get("prompt_preview", "")

            status_icon = {
                "success": "✅",
                "failed": "❌",
                "dispatched": "\U0001f535",
            }.get(last_status, "⚪")
            enabled_tag = "" if enabled else " [disabled]"

            lines.append(f"{status_icon} {owner}/{job_id}{enabled_tag}")
            lines.append(f"  Type: {jtype} ({schedule})")
            lines.append(f"  Next: {next_run}")
            lines.append(f"  Last: {last_status}")
            if last_error:
                lines.append(f"  Error: {last_error}")
            if prompt:
                lines.append(f"  Prompt: {prompt[:80]}...")
            lines.append("")

        lines.append(f"Generated: {generated}")
        return "\n".join(lines)

    # =============================================
    # HOURLY DIGEST
    # =============================================

    def start_digest(self, chat_id: int) -> None:
        """Start the hourly digest thread."""
        if self._digest_thread is not None and self._digest_thread.is_alive():
            return
        self._scheduler_chat_id = chat_id
        self._digest_stop.clear()
        self._digest_thread = threading.Thread(
            target=self._digest_loop,
            name="scheduler-digest",
            daemon=True,
        )
        self._digest_thread.start()
        logger.info("Digest thread started (chat_id=%s)", chat_id)

    def stop_digest(self) -> None:
        """Stop the hourly digest thread."""
        self._digest_stop.set()
        if self._digest_thread is not None:
            self._digest_thread.join(timeout=5)
            self._digest_thread = None
        logger.info("Digest thread stopped")

    def _digest_loop(self) -> None:
        """Post a queue digest every hour."""
        while not self._digest_stop.is_set():
            self._digest_stop.wait(DIGEST_INTERVAL)
            if self._digest_stop.is_set():
                break
            self._post_digest()

    def _post_digest(self) -> None:
        """Fetch queue and post digest to the scheduler chat."""
        if self._scheduler_chat_id is None:
            return
        queue_data = self._fetch_queue()
        if queue_data is None:
            logger.warning("Digest skipped: failed to fetch queue")
            return

        text = f"Hourly Queue Digest\n{'=' * 20}\n\n{self._format_queue(queue_data)}"
        delivered = True
        for chunk in self.chunk_text(text):
            if self.send_message(self._scheduler_chat_id, chunk) is None:
                delivered = False

        if delivered:
            logger.info("Hourly digest posted")
        else:
            logger.warning("Hourly digest posting failed for one or more chunks")

    # =============================================
    # LIFECYCLE
    # =============================================

    def run(self) -> int:
        """Run the bot: start the hourly digest, then delegate to the parent poll loop.

        BaseBot.run() owns the full lifecycle (verify, command menu, lock, signal
        handlers, offset tracking, poll loop, cleanup). We only wrap it to start the
        digest thread before the blocking loop and stop it on exit.
        """
        chat_id = getattr(self, "_config_chat_id", None)
        if chat_id:
            self.start_digest(int(chat_id))
        try:
            return super().run()
        finally:
            self.stop_digest()
