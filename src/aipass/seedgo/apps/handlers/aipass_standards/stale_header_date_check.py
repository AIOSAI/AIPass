# =================== AIPass ====================
# Name: stale_header_date_check.py
# Description: Stale Header Date Standards Checker Handler
# Version: 1.0.3
# Created: 2026-09-25
# Modified: 2026-10-24
# =============================================

"""
Stale Header Date Standards Checker Handler

Reference: stale_header_date.md
"""

from functools import partial
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
from aipass.seedgo.apps.handlers.aipass_standards.check_support import read_text, result

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


def _today() -> str:
    """Today's ISO date, read at call: the one clock a test freezes to judge the working tree."""
    return datetime.date.today().isoformat()


def truth_date(path: Path) -> Tuple[str | None, str]:
    """(the date the file's content is from, what that date is), or (None, why not)."""
    known = history(path.resolve().parent)
    if isinstance(known, str):
        return None, known
    dates, changed = known
    if path.name in changed:
        return _today(), "its uncommitted change, today"
    if path.name in dates:
        return dates[path.name], "its last commit"
    return None, "git has no history for this file"


_read = partial(read_text, tag="stale_header_date", errors="ignore")
_result = partial(result, standard=STANDARD)


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
    """Check a test file's ``Modified:`` date against the file's own history."""
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
