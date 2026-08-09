# =================== AIPass ====================
# Name: log_streamer.py
# Description: Stream system log lines to Telegram via batched daemon thread
# Version: 1.1.0
# Created: 2026-02-26
# Modified: 2026-08-09
# =============================================

"""
LogStreamer - Stream system log lines to a Telegram chat.

Runs as a background daemon thread, tailing log files for a specific branch
and batching new lines to send via the Telegram Bot API. Tracks file positions
to only deliver new content, handles file rotation, and discovers new log files
each cycle.

Usage:
    streamer = LogStreamer(bot_token="...", chat_id=123456, branch_name="api")
    streamer.start()
    # ... later ...
    streamer.stop()
"""

# Standard library
import json
import threading
from pathlib import Path
from typing import Dict, List
from urllib.error import URLError
from urllib.request import Request, urlopen

# Logging
from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

BATCH_INTERVAL = 5.0
TELEGRAM_MAX_LENGTH = 4000


def _get_system_logs_dir():
    """Resolve system_logs dir, honoring AIPASS_TEST_LOG_DIR."""
    import os

    test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_dir:
        p = Path(test_dir) / "system"
        p.mkdir(parents=True, exist_ok=True)
        return p
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            d = parent / "system_logs"
            d.mkdir(parents=True, exist_ok=True)
            return d
    return Path.home() / "system_logs"


SYSTEM_LOGS_DIR = _get_system_logs_dir()


# =============================================
# LOG STREAMER
# =============================================


_LEVEL_MARKERS = ("| WARNING |", "| ERROR |", "| CRITICAL |")

# Prax log-source prefixes emitted by the telegram bot processes that host this
# streamer. A system-wide streamer globs every *.log, so without this exclusion
# its own output is inside its own watch scope: one INFO per cycle re-feeds the
# next cycle forever. Prax SystemLogger has no debug() level, so there is no
# "quiet" level to log at — the only safe rule is that bot-emitted lines never
# stream. Covers both process-named captures (captured_bot_<bot_id>) and
# module-named ones (captured_base_bot), since prax derives the name from
# whichever context is live.
_SELF_LOG_SOURCES = (
    "captured_bot_",  # captured_bot_base, captured_bot_prax_monitor, captured_bot_factory, ...
    "captured_base_bot",
    "captured_scheduler_bot",
    "captured_botfather_",
    "captured_log_streamer",
)


def _is_self_log_line(line: str) -> bool:
    """True if this line was emitted by a telegram bot process (this streamer's own host)."""
    parts = line.split(" | ", 2)
    if len(parts) < 3:
        return False
    return parts[1].strip().startswith(_SELF_LOG_SOURCES)


class LogStreamer:
    """Stream system log lines for a branch to Telegram via batched sends."""

    def __init__(
        self,
        bot_token: str,
        chat_id: int,
        branch_name: str,
        system_wide: bool = False,
        level_filter: str = "all",
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.branch_name = branch_name
        self._system_wide = system_wide
        self._level_filter = level_filter

        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.log_positions: Dict[str, int] = {}

        # Initialize positions to end of all existing log files
        self._init_positions()

    # -----------------------------------------
    # POSITION TRACKING
    # -----------------------------------------

    def _get_log_files(self) -> List[Path]:
        """Find log files: all *.log when system_wide, else branch-specific."""
        if not SYSTEM_LOGS_DIR.exists():
            return []
        if self._system_wide:
            return sorted(SYSTEM_LOGS_DIR.glob("*.log"))
        return sorted(SYSTEM_LOGS_DIR.glob(f"{self.branch_name}_*.log"))

    def _filter_lines(self, lines: List[str]) -> List[str]:
        """Drop the bots' own captured output, then apply the level filter.

        Self-exclusion runs first and is unconditional — it holds even at
        level_filter='all', so no INFO (or WARNING) added to this code path by
        anyone can re-enter the stream and feed the loop.
        """
        lines = [ln for ln in lines if not _is_self_log_line(ln)]
        if self._level_filter == "all":
            return lines
        return [ln for ln in lines if any(m in ln for m in _LEVEL_MARKERS)]

    def _init_positions(self) -> None:
        """Set initial positions to end of file so we only tail new lines."""
        for log_file in self._get_log_files():
            file_path = str(log_file)
            try:
                self.log_positions[file_path] = log_file.stat().st_size
            except OSError as e:
                logger.warning("Could not stat %s: %s", file_path, e)
                self.log_positions[file_path] = 0
        logger.info(
            "Initialized positions for %d log files (branch: %s)",
            len(self.log_positions),
            self.branch_name,
        )

    def _read_new_lines(self) -> List[str]:
        """Read new lines from all tracked log files."""
        all_new_lines: List[str] = []

        for log_file in self._get_log_files():
            file_path = str(log_file)

            try:
                current_size = log_file.stat().st_size
            except OSError as e:
                logger.warning("Could not stat %s: %s", file_path, e)
                continue

            last_pos = self.log_positions.get(file_path, 0)

            try:
                # New file discovered mid-run: start from beginning
                if file_path not in self.log_positions:
                    last_pos = 0
                    logger.info("New log file discovered: %s", file_path)

                # File rotation: size shrank, reset to beginning
                if current_size < last_pos:
                    logger.info("File rotation detected: %s", file_path)
                    last_pos = 0

                # Read new content
                if current_size > last_pos:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(last_pos)
                        new_content = f.read()
                        self.log_positions[file_path] = f.tell()

                    lines = new_content.splitlines()
                    if lines:
                        all_new_lines.extend(lines)
                else:
                    # Update position even when nothing new (handles new file registration)
                    self.log_positions[file_path] = current_size
            except OSError as e:
                logger.warning("Failed to process %s: %s", file_path, e)
                continue

        return all_new_lines

    # -----------------------------------------
    # TELEGRAM DELIVERY
    # -----------------------------------------

    def _send_message(self, message: str) -> bool:
        """Send a message to Telegram. Returns True on success."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": message,
                "disable_notification": True,
            }
        ).encode("utf-8")
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})

        try:
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                return result.get("ok", False)
        except (URLError, Exception) as e:
            logger.warning("Telegram send failed: %s", e)
            return False

    def _send_batched(self, lines: List[str]) -> None:
        """Split lines into messages respecting TELEGRAM_MAX_LENGTH, send each."""
        if not lines:
            return

        batch: List[str] = []
        batch_len = 0

        for line in lines:
            # +1 for the newline separator between lines
            line_len = len(line) + (1 if batch else 0)

            if batch_len + line_len > TELEGRAM_MAX_LENGTH and batch:
                # Send current batch
                message = "\n".join(batch)
                self._send_message(message)
                batch = []
                batch_len = 0

            batch.append(line)
            batch_len += line_len

        # Send remaining
        if batch:
            message = "\n".join(batch)
            self._send_message(message)

    # -----------------------------------------
    # DAEMON THREAD
    # -----------------------------------------

    def _run(self) -> None:
        """Main loop: read new lines, batch, send, sleep."""
        logger.info("Log streamer started for branch: %s", self.branch_name)
        # Report the glob actually used, not the branch-scoped one — a system-wide
        # streamer that claims to watch <branch>_*.log hides the very scope that
        # let it watch itself.
        scope = "*.log" if self._system_wide else f"{self.branch_name}_*.log"
        logger.info("Watching: %s/%s (chat_id=%s)", SYSTEM_LOGS_DIR, scope, self.chat_id)

        while self._running:
            try:
                new_lines = self._read_new_lines()
                new_lines = self._filter_lines(new_lines)
                if new_lines:
                    # No "forwarding N lines" announcement here, by Patrick's ruling:
                    # the forwarded lines are their own evidence. Anything logged in
                    # this loop lands in the bot's own captured log, which a
                    # system-wide streamer watches — that is what fed the loop.
                    self._send_batched(new_lines)
            except Exception as e:
                logger.warning("Streamer cycle error: %s", e)

            # Interruptible sleep
            self._stop_event.wait(BATCH_INTERVAL)

        logger.info("Log streamer stopped for branch: %s", self.branch_name)

    # -----------------------------------------
    # PUBLIC API
    # -----------------------------------------

    def start(self) -> None:
        """Start the log streamer daemon thread."""
        if self._running:
            logger.warning("Log streamer already running")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"log-streamer-{self.branch_name}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Daemon thread started: %s", self._thread.name)
        json_handler.log_operation("streamer_started", {"branch": self.branch_name, "chat_id": self.chat_id})

    def stop(self) -> None:
        """Stop the log streamer and wait for thread to finish."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=BATCH_INTERVAL + 2)
            if self._thread.is_alive():
                logger.warning("Daemon thread did not exit cleanly")
            self._thread = None

        logger.info("Log streamer stopped")
        json_handler.log_operation("streamer_stopped", {"branch": self.branch_name})
