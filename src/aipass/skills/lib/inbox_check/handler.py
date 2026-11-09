# ===================AIPASS====================
# META DATA HEADER
# Name: handler.py - Inbox Check skill handler
# Date: 2026-03-29
# Version: 1.3.0
# Modified: 2026-11-09
# Category: skills/lib/inbox_check
# =============================================

"""
Inbox Check skill handler.

Called by: drone @skills run inbox_check <action>
"""

import json
from pathlib import Path

from aipass.memory.apps.modules import door_registry_scope


def run(action, args=None, config=None):
    """Execute an inbox check action: summary, all, or a branch name."""
    args = args or {}
    config = config or {}

    try:
        if action in ("summary", "all"):
            return _scan_all(detail=(action == "all"))
        return _scan_branch(action)
    except Exception as exc:
        return {
            "success": False,
            "output": "",
            "error": f"Action '{action}' failed: {exc}",
        }


def get_actions():
    """List available actions for this skill."""
    return ["summary", "all", "<branch_name>"]


def _find_inboxes():
    """Yield (branch_name, inbox_path) for every citizen memory's door reports that has an inbox."""
    for row in door_registry_scope.fleet_branches():
        inbox = Path(row["path"]) / ".ai_mail.local" / "inbox.json"
        if inbox.is_file():
            yield (row["name"], inbox)


def _read_inbox(inbox_path):
    """Read and parse an inbox.json file. Returns list of messages."""
    try:
        text = inbox_path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "messages" in data:
            return data["messages"]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _count_new(messages):
    """Count messages where status == 'new'."""
    return sum(1 for m in messages if isinstance(m, dict) and m.get("status") == "new")


def _scan_all(detail=False):
    """Scan all branches for inbox status."""
    lines = []
    total_new = 0
    total_messages = 0
    branch_count = 0

    for branch_name, inbox_path in _find_inboxes():
        messages = _read_inbox(inbox_path)
        new_count = _count_new(messages)
        total_new += new_count
        total_messages += len(messages)
        branch_count += 1

        if detail:
            lines.append(f"\n  {branch_name} ({new_count} new / {len(messages)} total):")
            if messages:
                lines += [f"  {line}" for line in _message_lines(messages)]
            else:
                lines.append("      (empty)")
        else:
            if new_count > 0:
                lines.append(f"  {branch_name}: {new_count} new ({len(messages)} total)")

    if not lines and not detail:
        output = "Inbox Check\n  No unread messages across any branch."
    else:
        header = f"Inbox Check -- {branch_count} branches scanned"
        summary = f"  Total: {total_new} new / {total_messages} messages"
        body = "\n".join(lines) if lines else "  No unread messages."
        output = f"{header}\n{summary}\n{body}"

    return {"success": True, "output": output, "error": None}


def _message_lines(messages):
    """One line per message: marker, status, sender, subject."""
    lines = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        status = msg.get("status", "unknown")
        sender = msg.get("from", msg.get("sender", "unknown"))
        subject = msg.get("subject", msg.get("message", "(no subject)"))
        marker = "*" if status == "new" else " "
        lines.append(f"  {marker} [{status}] from {sender}: {subject}")
    return lines


def _scan_branch(branch_name):
    """Show inbox for a specific branch."""
    # A branch is one name, never a path: refused before the door is read.
    if not branch_name or Path(branch_name).name != branch_name or branch_name in (".", ".."):
        return {"success": False, "output": "", "error": f"Not a branch name: {branch_name!r}"}

    inbox_path = None
    for row in door_registry_scope.fleet_branches():
        if row["name"].lower() == branch_name.lower():
            branch_name, inbox_path = row["name"], Path(row["path"]) / ".ai_mail.local" / "inbox.json"
            break
    if inbox_path is None or not inbox_path.is_file():
        return {
            "success": True,
            "output": f"Inbox Check -- {branch_name}\n  No inbox found for branch '{branch_name}'.",
            "error": None,
        }

    messages = _read_inbox(inbox_path)
    new_count = _count_new(messages)

    lines = [f"Inbox Check -- {branch_name} ({new_count} new / {len(messages)} total):"]
    if messages:
        lines += _message_lines(messages)
    else:
        lines.append("  (empty inbox)")

    return {"success": True, "output": "\n".join(lines), "error": None}
