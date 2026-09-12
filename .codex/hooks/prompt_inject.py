#!/usr/bin/env python3
"""Codex UserPromptSubmit hook: inject per-turn AIPass context.

Injects branch identity, email notifications, and current time on every prompt.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def find_repo_root():
    p = Path.cwd()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return None


def get_branch_from_cwd(repo_root):
    cwd = Path.cwd()
    try:
        rel = cwd.relative_to(repo_root / "src" / "aipass")
        return str(rel).split("/")[0]
    except ValueError:
        try:
            rel = cwd.relative_to(repo_root / "src")
            return str(rel).split("/")[0]
        except ValueError:
            return None


def main():
    # stdin is DRAINED, not read: Codex writes the event JSON here and nothing
    # this hook injects depends on a field of it, but a hook that never reads
    # the pipe can hand the provider a broken one. The parse is what proves the
    # pipe was consumed; the value was bound to a name nobody used (ruff F841).
    try:
        json.loads(sys.stdin.read())
    except (OSError, ValueError):
        # Named and narrow rather than bare: an unreadable or unparseable event
        # changes nothing this hook prints, and there is nowhere to log from a
        # stdlib-only provider hook whose stdout IS the injected context.
        pass

    repo_root = find_repo_root()
    if not repo_root:
        print(json.dumps({}))
        return

    context_parts = []

    # 1. Current time
    now = datetime.now().strftime("%A, %B %-d %Y — %-I:%M %p")
    context_parts.append(f"# Current Time: {now}")

    # 2. Branch identity (compact form for per-turn)
    branch = get_branch_from_cwd(repo_root)
    if branch:
        branch_dir = repo_root / "src" / "aipass" / branch
        if not branch_dir.exists():
            branch_dir = repo_root / "src" / branch

        passport = branch_dir / ".trinity" / "passport.json"
        if passport.exists():
            try:
                data = json.loads(passport.read_text(encoding="utf-8"))
                identity = data.get("identity", {})
                traits = data.get("traits", [])
                context_parts.append(
                    f"# {branch.upper()} Identity\n"
                    f"Path: {data.get('branch_info', {}).get('path', 'unknown')}\n"
                    f"Role: {identity.get('role', 'unknown')}\n"
                    f"Traits: {' | '.join(traits)}\n"
                    f"Purpose: {identity.get('purpose', 'unknown')}"
                )
            except Exception:
                pass

        # 3. Email notification
        inbox = branch_dir / ".ai_mail.local" / "inbox.json"
        if inbox.exists():
            try:
                mail = json.loads(inbox.read_text(encoding="utf-8"))
                unread = mail.get("unread_count", 0)
                if unread > 0:
                    context_parts.append(f"You have {unread} new emails - check with: drone @ai_mail inbox")
            except Exception:
                pass

    if context_parts:
        context = "\n\n".join(context_parts)
        output = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}
    else:
        output = {}

    print(json.dumps(output))


if __name__ == "__main__":
    main()
