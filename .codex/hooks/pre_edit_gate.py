#!/usr/bin/env python3
"""Codex PreToolUse hook: gate file edits to protect critical files.

Blocks edits to .trinity/passport.json and other protected paths.
"""

import json
import sys


PROTECTED_PATTERNS = [
    ".trinity/passport.json",
    ".aipass/registry.json",
    "setup.sh",
]


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except Exception:
        print(json.dumps({}))
        return

    tool_input = input_data.get("input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")

    if not file_path:
        print(json.dumps({}))
        return

    for pattern in PROTECTED_PATTERNS:
        if pattern in file_path:
            output = {
                "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"},
                "systemMessage": f"Edit blocked: {pattern} is a protected file.",
            }
            print(json.dumps(output))
            return

    print(json.dumps({}))


if __name__ == "__main__":
    main()
