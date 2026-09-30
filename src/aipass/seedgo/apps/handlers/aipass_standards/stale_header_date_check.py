# =================== AIPass ====================
# Name: stale_header_date_check.py
# Description: Stale Header Date Standards Checker Handler
# Version: 1.0.1
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Stale Header Date Standards Checker Handler

Test template v1 item 5 puts the META header on top of every test file, and
the header says ``# Modified: <date>``. The date is a claim about the file,
and it goes stale the moment a change lands without moving it. The 2026-09-24
review of @backup's tests found 14 of 14 headers reading 2026-09-22 after
b92e0361 rewrote every one of them on 2026-09-23.

THE DATE OF TRUTH IS VERSION CONTROL'S. A file is stale when its ``Modified:``
date is older than the author date of the last commit that touched it. A
file with uncommitted changes, or one never committed, is judged as of TODAY:
its content is newer than any commit, so a change that did not move the date
is convicted at the edit (the checklist hook runs on every write) and a change
that moved it passes at once. That is also what keeps a verdict stable across
the commit that follows, which matters because the audit's incremental cache
keys a file's result on its (mtime, size), and a commit changes neither.

THIS IS THE FIRST CHECKER IN THE PACK TO READ GIT, and it reads only:
``rev-parse``, ``log``, ``diff --name-only`` and ``ls-files``, one batch per
directory, cached for the process. Where the history cannot answer, it
DECLINES rather than passes -- the file is reported not applicable and stays
out of the average, because a 100 would claim a measurement that never
happened:

  * no git on PATH, or the file is not in a work tree (an installed wheel, a
    tarball);
  * a SHALLOW clone, where every file's last commit is the one HEAD commit.
    CI's seedgo-audit job checks out with ``fetch-depth: 0`` (ci.yml), so the
    gate sees full history and matches a local audit; any other shallow
    checkout declines the whole lane rather than convict or acquit on a
    history it does not have;
  * a file git has no history for and does not list as changed (ignored).

A file with no ``Modified:`` line is not this rule's business: item 5 owns the
header's presence, and ``file_top`` convicts its absence.

CHECK FIRST, measured 2026-09-25 over the fleet's 561 test files: 422 carry a
``Modified:`` line, 320 of them are older than their last commit, and 182 of
those by more than 30 days. The number is large because the date has never
been read by anything; nothing is tuned to make it smaller.
"""

import datetime
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed
from aipass.seedgo.apps.handlers.json import json_handler

APPLIES_TO = "tests"
AUDIT_SCOPE = "all_files"

STANDARD = "STALE_HEADER_DATE"
STANDARD_KEY = "stale_header_date"

#: The header's date line, read from the top of the file only.
MODIFIED = re.compile(r"^#\s*Modified:\s*(\d{4}-\d{2}-\d{2})", re.M)

#: How far down the file the META header can reach.
HEADER_LINES = 15

#: Seconds any one git call may take before the lane declines.
GIT_TIMEOUT = 60

#: Variables that would point git at a different repository than the file's.
GIT_REDIRECTS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")

#: The marker _run_all_files reads to leave a result out of the average.
DECLINED = "not applicable"

CURE = "move Modified: to the date of the change"


def header_date(source: str) -> str | None:
    """The ``Modified:`` date in the META header, or None when there is none."""
    match = MODIFIED.search("\n".join(source.splitlines()[:HEADER_LINES]))
    return match.group(1) if match else None


def _git(directory: Path, *argv: str) -> str:
    """One read-only git call in ``directory``; raises when git cannot answer."""
    env = {key: value for key, value in os.environ.items() if key not in GIT_REDIRECTS}
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=off", *argv],
        cwd=str(directory),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT,
        env=env,
        check=True,
    )
    return completed.stdout


@lru_cache(maxsize=256)
def history(directory: Path) -> Tuple[Dict[str, str], FrozenSet[str]] | str:
    """(last author date per file, files changed since HEAD), or why there is none.

    One ``log`` walks every file in the directory at once; the first date a
    file appears under is its last commit, because log runs newest first.
    """
    try:
        if _git(directory, "rev-parse", "--is-shallow-repository").strip() == "true":
            return "a shallow clone, where every file's last commit is HEAD"
        log = _git(directory, "log", "--format=%x00%as", "--name-only", "--relative", "--", ".")
        changed = _git(directory, "diff", "--name-only", "--relative", "HEAD", "--", ".")
        untracked = _git(directory, "ls-files", "--others", "--exclude-standard", "--", ".")
    except FileNotFoundError as exc:
        logger.info("[stale_header_date] git is not installed: %s", exc)
        return "git is not installed"
    except subprocess.CalledProcessError as exc:
        logger.info("[stale_header_date] No history in %s: %s", directory, exc.stderr)
        return "git could not read a history here (no work tree, or no commit yet)"
    except subprocess.TimeoutExpired as exc:
        logger.info("[stale_header_date] git timed out in %s: %s", directory, exc)
        return "git did not answer in time"
    dates: Dict[str, str] = {}
    date = ""
    for line in log.splitlines():
        if line.startswith("\x00"):
            date = line[1:]
        elif line and line not in dates:
            dates[line] = date
    return dates, frozenset(changed.splitlines()) | frozenset(untracked.splitlines())


def truth_date(path: Path) -> Tuple[str | None, str]:
    """(the date the file's content is from, what that date is), or (None, why not)."""
    known = history(path.resolve().parent)
    if isinstance(known, str):
        return None, known
    dates, changed = known
    if path.name in changed:
        return datetime.date.today().isoformat(), "its uncommitted change, today"
    if path.name in dates:
        return dates[path.name], "its last commit"
    return None, "git has no history for this file"


def _read(path: Path) -> str | None:
    """A file's text, or None if it cannot be read."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.info("[stale_header_date] Cannot read %s: %s", path, exc)
        return None


def _result(passed: bool, checks: List[Dict], score: int) -> Dict:
    """The result shape every checker in this pack returns."""
    return {"passed": passed, "checks": checks, "score": score, "standard": STANDARD}


def _one_check(passed: bool, message: str) -> List[Dict]:
    """A single-entry checks list, for the paths that have one thing to say."""
    return [{"name": "Header date", "passed": passed, "message": message}]


def _declined(reason: str) -> Dict:
    """A result that measured nothing: out of the average, never a 100."""
    return {
        "passed": True,
        "score": 100,
        "not_applicable": True,
        "checks": [{**check, "declined": True} for check in _one_check(True, f"Header date {DECLINED}: {reason}")],
        "standard": STANDARD,
    }


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Check a test file's ``Modified:`` date against the file's own history.

    Args:
        module_path: Path to the file to check.
        bypass_rules: Optional bypass rules, applied per standard.

    Returns:
        dict: {'passed', 'checks', 'score', 'standard'} -- the pack's shape.
    """
    if is_bypassed(module_path, STANDARD_KEY, bypass_rules=bypass_rules):
        return _result(True, _one_check(True, "Standard bypassed via .seedgo/bypass.json"), 100)

    path = Path(module_path)
    if not path.exists():
        return _result(False, _one_check(False, f"File not found: {module_path}"), 0)

    source = _read(path)
    if source is None:
        return _result(False, _one_check(False, f"Error reading file: {module_path}"), 0)

    claimed = header_date(source)
    if claimed is None:
        return _declined("no Modified: line in the header (file_top owns the header)")

    truth, what = truth_date(path)
    if truth is None:
        return _declined(what)

    if claimed >= truth:
        return _result(True, _one_check(True, f"Modified: {claimed} is current with {what} ({truth})"), 100)

    json_handler.log_operation(
        "check_completed",
        {"file": str(module_path), "score": 0, "standard": STANDARD_KEY, "claimed": claimed, "truth": truth},
    )
    message = f"{path.name}: Modified: {claimed} is older than {what} ({truth}) - {CURE}"
    return _result(False, _one_check(False, message), 0)
