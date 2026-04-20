#!/usr/bin/env python3
"""
SubagentStop Gate — Checks files modified by subagents before allowing them to finish.

Runs seedgo checklist + basic validation on any .py files the subagent touched.
If violations found, blocks the stop and tells the subagent to fix them.

Version: 1.0.0
"""

import json
import sys
import subprocess
from pathlib import Path

AIPASS_ROOT = Path.home() / "Projects" / "AIPass"


def get_modified_py_files() -> list[str]:
    """Get Python files modified in the working tree (unstaged + staged)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(AIPASS_ROOT)
        )
        files = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.endswith(".py") and not line.startswith(".claude/"):
                full = AIPASS_ROOT / line
                if full.exists():
                    files.append(str(full))
        return files
    except Exception:
        return []


def run_seedgo_checklist(file_path: str) -> list[str]:
    """Run seedgo checklist on a single file."""
    if "/.claude/" in file_path:
        return []
    try:
        result = subprocess.run(
            ["drone", "@seedgo", "checklist", file_path],
            capture_output=True, text=True, timeout=15,
            cwd=str(AIPASS_ROOT)
        )
        if result.returncode != 0:
            return []
        violations = []
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("\u2717"):
                v = line[1:].strip()
                if v:
                    violations.append(v)
        return violations[:5]
    except Exception:
        return []


def main():
    try:
        input_data = json.load(sys.stdin)

        modified = get_modified_py_files()
        if not modified:
            return  # Nothing to check

        all_violations = {}
        for f in modified:
            vs = run_seedgo_checklist(f)
            if vs:
                name = Path(f).name
                all_violations[name] = vs

        if not all_violations:
            return  # All clear

        # Build the block reason
        lines = ["Standards violations found in files you modified:\n"]
        for fname, vs in all_violations.items():
            lines.append(f"  {fname}:")
            for v in vs:
                lines.append(f"    - {v}")
        lines.append("\nFix these violations before finishing.")

        output = {
            "decision": "block",
            "reason": "\n".join(lines)
        }
        print(json.dumps(output))

    except Exception:
        pass  # Silent fail — don't block on errors


if __name__ == "__main__":
    main()
