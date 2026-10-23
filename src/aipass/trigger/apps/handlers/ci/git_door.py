# =================== AIPass ====================
# Name: git_door.py
# Description: CI red lane's drone calls - run list, run view, diff, remote and the ci-cure door
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""
CI Git Door Handler - every git fact the lane reads, and its one write, through drone from trigger's own directory
"""

import os
import re
import shutil
import subprocess
from typing import List, Tuple

from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler

DRONE_TIMEOUT_SECONDS = 300
# The cure door commits and pushes; a slow remote must not read as a refusal.
CURE_TIMEOUT_SECONDS = 600
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
_SLUG = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?(?:\s|$)")


class DroneCallFailed(RuntimeError):
    """A drone read answered non-zero; the message carries its output."""


def run_drone(args: List[str], timeout: int = DRONE_TIMEOUT_SECONDS) -> Tuple[int, str]:
    """Run one drone command from trigger's directory, so drone signs it @trigger; returns (exit code, output)."""
    drone = shutil.which("drone")
    if drone is None:
        raise DroneCallFailed("drone is not on PATH")
    # Wide columns: a Rich-wrapped line would split gh's tab-separated rows.
    env = {**os.environ, "COLUMNS": "500"}
    try:
        result = subprocess.run(
            [drone, *args],
            cwd=str(TRIGGER_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DroneCallFailed(f"drone {' '.join(args[:3])} did not finish: {exc}") from exc
    json_handler.log_operation("ci_drone_call", {"args": args[:3], "exit": result.returncode})
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _read(args: List[str]) -> str:
    """A read that must succeed: non-zero raises with drone's own words."""
    code, output = run_drone(args)
    if code != 0:
        raise DroneCallFailed(f"drone {' '.join(args[:3])} exited {code}: {output.strip()[-400:]}")
    return output


def run_list() -> str:
    """`drone @git run list`: gh's newest runs, one tab-separated row each."""
    return _read(["@git", "run", "list"])


def run_view_failed(run_id: str) -> str:
    """`drone @git run view <id> --log-failed`: the failed steps' log lines."""
    return _read(["@git", "run", "view", str(run_id), "--log-failed"])


def diff(paths: List[str]) -> str:
    """`drone @git diff <paths>`: the working-tree diff of the cure's files."""
    return _read(["@git", "diff", *paths])


def repo_slug() -> str:
    """owner/name of origin on GitHub, read from `drone @git remote`; empty when origin is not GitHub."""
    match = _SLUG.search(_read(["@git", "remote"]))
    return match.group(1) if match else ""


def ci_cure(run_id: str, owner: str, message: str, paths: List[str]) -> Tuple[bool, str, str]:
    """The cure door: (pushed, sha, output). Any non-zero exit, the verb's absence included, is not pushed."""
    code, output = run_drone(["@git", "ci-cure", str(run_id), f"@{owner}", message, *paths], CURE_TIMEOUT_SECONDS)
    first = output.strip().splitlines()[0] if output.strip() else ""
    sha = _SHA.search(first)
    pushed = code == 0 and sha is not None
    return pushed, sha.group(0) if sha else "", output
