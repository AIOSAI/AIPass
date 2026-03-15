#!/usr/bin/env python3
"""
Pre-Compact Hook - Inject live state for post-compact recovery.

Reads STATUS.local.md, last session from local.json, and git branch
to give the model real context after compaction — not generic advice.

Version: 3.0.0
"""

import json
import subprocess
import sys
from pathlib import Path


def _find_branch_dir():
    """Find the current branch directory from CWD."""
    cwd = Path.cwd()

    # Check if we're in a branch dir or subdirectory of one
    # Pattern: .../src/aipass/{branch}/...
    parts = cwd.parts
    for i, part in enumerate(parts):
        if part == "aipass" and i > 0 and parts[i - 1] == "src":
            branch_dir = Path(*parts[: i + 2])
            if branch_dir.is_dir():
                return branch_dir

    # Check if CWD itself has .trinity/
    if (cwd / ".trinity").is_dir():
        return cwd

    return None


def _read_status_local(branch_dir):
    """Read STATUS.local.md if it exists."""
    for name in ["STATUS.local.md", "dev.local.md"]:
        path = branch_dir / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")[:3000]
            except Exception:
                pass
    return None


def _read_last_session(branch_dir):
    """Read the most recent session and key_learnings from local.json."""
    local_path = branch_dir / ".trinity" / "local.json"
    if not local_path.is_file():
        return None

    try:
        data = json.loads(local_path.read_text(encoding="utf-8"))
        result = []

        # Last session
        sessions = data.get("sessions", [])
        if sessions:
            last = sessions[0]
            result.append(
                f"Last session (#{last.get('session_number', '?')}, "
                f"{last.get('date', '?')}): {last.get('summary', 'no summary')}"
            )

        # Key learnings (just the keys, not full values — breadcrumbs)
        learnings = data.get("key_learnings", {})
        if learnings:
            keys = list(learnings.keys())[-10:]  # last 10
            result.append(f"Key learnings available: {', '.join(keys)}")

        return "\n".join(result) if result else None
    except Exception:
        return None


def _get_git_info():
    """Get current git branch and short status."""
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "diff", "--stat", "--cached", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        result = []
        if branch.returncode == 0:
            result.append(f"Git branch: {branch.stdout.strip()}")
        if dirty.returncode == 0 and dirty.stdout.strip():
            lines = dirty.stdout.strip().split("\n")
            result.append(f"Uncommitted changes: {len(lines)} files")

        return "\n".join(result) if result else None
    except Exception:
        return None


def _get_branch_name(branch_dir):
    """Extract branch name from directory."""
    return branch_dir.name if branch_dir else "unknown"


def main():
    """Main hook entry point."""
    try:
        json.load(sys.stdin)

        branch_dir = _find_branch_dir()
        branch_name = _get_branch_name(branch_dir)

        sections = []

        sections.append(f"""POST-COMPACT RECOVERY — @{branch_name}

Context just compacted. Below is your live state. Use it to continue seamlessly.""")

        # Git info
        git_info = _get_git_info()
        if git_info:
            sections.append(f"## Git\n{git_info}")

        # Last session from local.json
        if branch_dir:
            session_info = _read_last_session(branch_dir)
            if session_info:
                sections.append(f"## Last Session\n{session_info}")

        # STATUS.local.md — the main context
        if branch_dir:
            status = _read_status_local(branch_dir)
            if status:
                sections.append(f"## STATUS.local.md\n{status}")

        # Recovery instructions (lean)
        sections.append("""## Recovery Protocol
- Continue where the summary left off — don't restart or ask generic questions
- .trinity/local.json has full session history and key_learnings — read it if you need more context
- STATUS.local.md has current work, known issues, and todos
- Save memories proactively — compaction just proved you need to
- Match the conversation tone from before compaction""")

        print("\n\n".join(sections), file=sys.stdout)
        print("Pre-compact: live state injected", file=sys.stderr)

    except Exception as e:
        # Fail silently — never block compaction
        print(f"Pre-compact hook error: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
