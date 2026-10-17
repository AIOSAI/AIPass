# =================== AIPass ====================
# Name: test_token.py
# Description: AIPASS-TEST ping token detection and auto-ack
# Version: 1.0.1
# Created: 2026-04-22
# Modified: 2026-10-17
# =============================================

"""
AIPASS-TEST Ping Token Handler
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

TEST_TOKEN = "[AIPASS-TEST — do not update memories, do not execute, reply 'ack' only]"


def has_test_token(body: str) -> bool:
    """Return True if body contains the AIPASS-TEST token outside a code fence."""
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and stripped == TEST_TOKEN:
            return True
    return False


def auto_ack_test_email(branch_path: Path, branch_email: str, message: Dict[str, Any]) -> bool:
    """Send an 'ack' reply to a test-token email and close it.

    cwd=branch_path makes the sender resolve to the target branch, not @ai_mail.
    """
    json_handler.log_operation("test_token_ack", {"branch": branch_email, "id": message.get("id", "")})
    msg_id = message.get("id", "")
    sender = message.get("from_email") or message.get("from", "")
    subject = message.get("subject", "")
    if not msg_id or not sender:
        logger.warning("[test_token] auto_ack_test_email: missing id or sender in message")
        return False

    reply_subject = f"Re: {subject}" if subject else "Re: (no subject)"
    try:
        result = subprocess.run(
            ["drone", "@ai_mail", "email", sender, reply_subject, "ack"],
            cwd=str(branch_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "[test_token] auto_ack_test_email: reply failed for %s: %s",
                msg_id,
                result.stderr,
            )
            return False
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[test_token] auto_ack_test_email: reply subprocess error: %s", exc)
        return False

    try:
        result = subprocess.run(
            ["drone", "@ai_mail", "close", msg_id],
            cwd=str(branch_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "[test_token] auto_ack_test_email: close failed for %s: %s",
                msg_id,
                result.stderr,
            )
            return False
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[test_token] auto_ack_test_email: close subprocess error: %s", exc)
        return False

    logger.info("[test_token] auto-acked test email %s at %s", msg_id, branch_email)
    return True


def scan_and_ack_test_emails(branch_path: Path, branch_email: str) -> int:
    """Scan a branch inbox for AIPASS-TEST tokens and auto-ack each one.

    Runs before check_inbox_for_dispatch so test emails never reach the dispatch scanner.
    """
    from aipass.ai_mail.apps.handlers.dispatch.daemon import JsonUnreadable, _read_json

    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    try:
        inbox_data = _read_json(inbox_file)
    except JsonUnreadable as e:
        # Nothing acked is the safe side; the dispatch scan refuses the same inbox too.
        logger.warning("[test_token] %s — no test email acked", e)
        return 0
    if inbox_data is None:
        return 0

    acked = 0
    for msg in inbox_data.get("messages", []):
        if msg.get("status") not in ("new", "opened"):
            continue
        body = msg.get("body", "")
        if has_test_token(body):
            if auto_ack_test_email(branch_path, branch_email, msg):
                acked += 1
    return acked


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("AIPASS-TEST PING TOKEN HANDLER")
    console.print("=" * 70)
    console.print("\nFunctions provided:")
    console.print("  - has_test_token(body) -> bool")
    console.print("  - auto_ack_test_email(branch_path, branch_email, message) -> bool")
    console.print("  - scan_and_ack_test_emails(branch_path, branch_email) -> int")
    console.print()
    console.print(f"TEST_TOKEN = {TEST_TOKEN!r}")
    console.print()
    console.print("=" * 70 + "\n")
