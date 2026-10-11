# =================== AIPass ====================
# Name: blame_handler.py
# Description: Git blame handler — who last touched each line of a file
# Version: 1.0.0
# Created: 2026-09-30
# Modified: 2026-09-30
# =============================================

"""Git blame handler — who last touched each line of a file.

Granted at the GLOBAL read tier (DPLAN-0356 leg 2): raw git reads are blocked
for every seat but devpulse, so blame needs a twin here. Like show, it is not
scoped to the caller's branch: reading another branch's history is the use case.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root

_LINE_RANGE = re.compile(r"^(\d+),(\d+)$")


def parse_line_range(spec: str) -> tuple[int, int] | None:
    """Read a ``START,END`` line range (1-based, inclusive), or None when it is not one.

    Only the numeric form is taken: git's regex and :funcname forms of -L stay
    out, so a token can never be read as something other than two line numbers.
    """
    match = _LINE_RANGE.match(spec)
    if match is None:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1 or end < start:
        return None
    return start, end


def get_git_blame(path: str, line_range: tuple[int, int] | None = None, repo_root: Path | None = None) -> dict:
    """Blame *path* (absolute) in *repo_root* (default: the standing repo).

    ``success`` is False when git could not answer, with git's reason in
    ``message``; ``lines`` holds git blame's own output, one entry per line.
    """
    if repo_root is None:
        repo_root = find_repo_root()

    cmd = ["git", "blame", "--date=short"]
    if line_range is not None:
        cmd += ["-L", f"{line_range[0]},{line_range[1]}"]
    cmd += ["--", path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo_root))
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git blame failed: %s", exc)
        return {"success": False, "lines": [], "message": f"git blame failed: {exc}"}

    if result.returncode != 0:
        return {"success": False, "lines": [], "message": f"git blame error: {result.stderr.strip()}"}

    lines = result.stdout.splitlines()
    json_handler.log_operation("get_git_blame", {"lines": len(lines), "ranged": line_range is not None})
    return {"success": True, "lines": lines, "message": f"{len(lines)} line(s) blamed"}
