# =================== AIPass ====================
# Name: tmux_manager.py
# Description: tmux Session Manager for Telegram Bridge
# Version: 1.2.0
# Created: 2026-02-12
# Modified: 2026-03-01
# =============================================

"""
tmux Session Manager for Telegram Bridge

Manages persistent Claude Code sessions in tmux:
- Named sessions (telegram-{branch_name}) running Claude Code
- Inject messages via tmux send-keys -l (literal mode)
- Kill/list sessions
- Capture pane content for status display

Each tmux session runs `claude --permission-mode bypassPermissions` continuously.
Messages are injected via send-keys, responses captured via Stop hook.
"""

import asyncio
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler  # noqa: F401

# =============================================
# CONSTANTS
# =============================================

SESSION_PREFIX = "telegram-"
DEFAULT_BRANCH = "dev_central"
CLAUDE_BIN = str(Path.home() / ".local" / "bin" / "claude")
SEND_KEYS_DELAY = 0.5  # seconds between text injection and Enter

RENAME_DELAY = 3  # seconds to wait for Claude to initialize before /rename


# =============================================
# HELPERS
# =============================================


def _session_name(branch_name: str) -> str:
    """Build tmux session name from branch name."""
    return f"{SESSION_PREFIX}{branch_name}"


def _send_rename(session_name: str, branch_name: str) -> None:
    """Send /rename to a tmux session after Claude initializes."""
    time.sleep(RENAME_DELAY)
    rename_cmd = f"/rename {branch_name.upper()}-telegram"
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", session_name, rename_cmd, "Enter"],
            capture_output=True,
        )
    except FileNotFoundError:
        logger.warning("tmux not found — could not rename session %s", session_name)


def has_tmux() -> bool:
    """Check if tmux is available on the system."""
    return shutil.which("tmux") is not None


def session_exists(branch_name: str) -> bool:
    """
    Check if a tmux session exists for the given branch.

    Args:
        branch_name: Branch name (e.g. 'dev_central')

    Returns:
        True if session is alive
    """
    name = _session_name(branch_name)
    # send_message, kill_session and get_session_pane all call this BEFORE
    # their own try, so a raise here escaped all three on a host without tmux.
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True,
        )
    except FileNotFoundError:
        logger.warning("tmux not found — session %s cannot exist", name)
        return False
    return result.returncode == 0


async def send_message(branch_name: str, message: str) -> bool:
    """
    Inject a message into a tmux session via send-keys.

    Uses -l flag for literal mode (no shell interpretation).
    Sends text first, waits briefly, then sends Enter.

    Args:
        branch_name: Branch name identifying the session
        message: The message text to inject

    Returns:
        True if message was sent successfully
    """
    name = _session_name(branch_name)

    if not session_exists(branch_name):
        logger.error("Session %s does not exist", name)
        return False

    try:
        # Send text literally (no shell interpretation)
        result = subprocess.run(
            ["tmux", "send-keys", "-t", name, "-l", message],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error("Failed to send text to %s: %s", name, result.stderr)
            return False

        # Wait before sending Enter (prevents rapid keystroke issues)
        await asyncio.sleep(SEND_KEYS_DELAY)

        # Send Enter to submit the message
        result = subprocess.run(
            ["tmux", "send-keys", "-t", name, "Enter"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error("Failed to send Enter to %s: %s", name, result.stderr)
            return False

        logger.info("Injected message into %s (%d chars)", name, len(message))
        return True

    except Exception as e:
        logger.error("Error sending to tmux session %s: %s", name, e)
        return False


def kill_session(branch_name: str) -> bool:
    """
    Kill a tmux session for the given branch.

    Args:
        branch_name: Branch name identifying the session

    Returns:
        True if session was killed (or didn't exist)
    """
    name = _session_name(branch_name)

    if not session_exists(branch_name):
        logger.info("Session %s does not exist, nothing to kill", name)
        return True

    try:
        result = subprocess.run(
            ["tmux", "kill-session", "-t", name],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info("Killed tmux session %s", name)
            return True
        else:
            logger.error("Failed to kill session %s: %s", name, result.stderr)
            return False

    except Exception as e:
        logger.error("Error killing tmux session %s: %s", name, e)
        return False


def list_sessions() -> List[str]:
    """
    List all active telegram-* tmux sessions.

    Returns:
        List of branch names with active sessions
    """
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return []

        sessions = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith(SESSION_PREFIX):
                branch = line[len(SESSION_PREFIX) :]
                if branch:
                    sessions.append(branch)

        return sessions

    except Exception as e:
        logger.warning("Error listing tmux sessions: %s", e)
        return []


def get_session_pane(branch_name: str) -> Optional[str]:
    """
    Capture current visible pane content from a tmux session.

    Args:
        branch_name: Branch name identifying the session

    Returns:
        Pane content as string, or None if session doesn't exist
    """
    name = _session_name(branch_name)

    if not session_exists(branch_name):
        return None

    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", name, "-p"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            json_handler.log_operation("get_session_pane", {"branch_name": branch_name})
            return result.stdout
        return None

    except Exception as e:
        logger.warning("Error capturing pane for session %s: %s", name, e)
        return None
