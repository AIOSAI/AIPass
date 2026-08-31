# =================== AIPass ====================
# Name: ping_sweep/__init__.py
# Description: Verify registered branches respond via test-convention email
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
ping_sweep — verify each registered branch responds.

Sends test-convention emails and waits for ack replies.
The AIPASS-TEST token protocol is recognized by ai_mail's daemon
(handlers/dispatch/test_token.py); branches with a running daemon
will auto-ack. Branches without a daemon time out — that's expected.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Dict

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.shared.registry_discovery import registries_in

TEST_TOKEN = "[AIPASS-TEST — do not update memories, do not execute, reply 'ack' only]"
TIMEOUT_PER_BRANCH = 30

BRANCHES = [
    "drone",
    "seedgo",
    "prax",
    "cli",
    "flow",
    "ai_mail",
    "api",
    "trigger",
    "spawn",
    "memory",
    "devpulse",
]

_BRANCH_ROOT = Path(__file__).resolve().parents[3]


def _discover_branches() -> list[str]:
    """Read branches from the project's own registry. Returns empty if none found."""
    cwd = Path.cwd()
    search = cwd
    for _ in range(10):
        candidates = registries_in(search)
        if candidates:
            try:
                data = json.loads(candidates[0].read_text(encoding="utf-8"))
                branches = [b.get("name", "") for b in data.get("branches", [])]
                return [b for b in branches if b]
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[ping_sweep] failed to read registry %s: %s", candidates[0], exc)
            return []
        parent = search.parent
        if parent == search:
            break
        search = parent
    return BRANCHES


def _aipass_inbox_path() -> Path:
    """Path to aipass's own inbox.json."""
    return _BRANCH_ROOT / ".ai_mail.local" / "inbox.json"


def _send_test_email(branch: str, body: str) -> bool:
    """Send test email to branch via drone. Returns True on success.

    Runs drone with cwd=aipass branch root so ai_mail's branch detection
    resolves the sender as @aipass (it requires a .trinity/passport.json
    in the working dir). Without this, the wrapper's cwd is the AIPass
    project root and every send fails with BRANCH DETECTION FAILED.
    """
    try:
        result = subprocess.run(
            ["drone", "@ai_mail", "email", f"@{branch}", "AIPASS PING", body],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(_BRANCH_ROOT),
        )
        if result.returncode != 0:
            logger.warning(
                "[ping_sweep] email to @%s failed (rc=%d): %s",
                branch,
                result.returncode,
                result.stderr[:200],
            )
            return False
        return True
    except FileNotFoundError as exc:
        logger.warning("[ping_sweep] drone not found: %s", exc)
        return False
    except subprocess.TimeoutExpired as exc:
        logger.warning("[ping_sweep] send to @%s timed out: %s", branch, exc)
        return False


def _wait_for_ack(branch: str, timeout: int) -> str:
    """
    Poll aipass inbox for an ack reply from branch.
    Returns 'ack' | 'timeout'.
    Auto-ack requires the target branch's ai_mail daemon to be running.
    """
    deadline = time.time() + timeout
    inbox_path = _aipass_inbox_path()

    while time.time() < deadline:
        time.sleep(2)
        if not inbox_path.exists():
            continue
        try:
            with open(inbox_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for msg in data.get("messages", []):
                msg_from = msg.get("from", "").lstrip("@")
                subj = msg.get("subject", "").lower()
                body_lower = msg.get("message", "").lower()
                if msg_from == branch and msg.get("status") == "new" and ("ack" in subj or "ack" in body_lower):
                    return "ack"
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[ping_sweep] inbox read error: %s", exc)

    return "timeout"


def sweep_all_branches(timeout: int = TIMEOUT_PER_BRANCH) -> Dict[str, str]:
    """
    Send AIPASS PING to each branch, collect acks.
    Returns {branch: 'ack' | 'timeout' | 'error'}.
    """
    results: Dict[str, str] = {}
    body = f"AIPASS PING — checking that you are reachable.\n\n{TEST_TOKEN}"

    for branch in _discover_branches():
        ok = _send_test_email(branch, body)
        if not ok:
            results[branch] = "error"
            continue
        results[branch] = _wait_for_ack(branch, timeout)
        logger.info("[ping_sweep] @%s → %s", branch, results[branch])

    json_handler.log_operation("ping_sweep", {"results": results})
    return results


def sweep_summary(results: Dict[str, str]) -> str:
    """Return human-readable sweep summary."""
    acks = sum(1 for v in results.values() if v == "ack")
    timeouts = sum(1 for v in results.values() if v == "timeout")
    errors = sum(1 for v in results.values() if v == "error")
    return f"{acks} ack / {timeouts} timeout / {errors} error"
