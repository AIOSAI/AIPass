# =================== AIPass ====================
# Name: history.py
# Description: age and authorship per test function, from one blame per file
# Version: 1.0.1
# Created: 2026-09-01
# Modified: 2026-10-29
# =============================================

"""
AGE AND AUTHORSHIP, from one `blame` per FILE and an AST line-range map.

One blame per file instead of per function is ~100x faster. Blame dates each
line's LAST touch, so age is a LOWER BOUND. Authors key on NAME (agents and the
human share one email); an unknown name goes to OTHER, never HUMAN. A file with
no history is UNTRACKED, never defaulted."""

import re
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger

#: The read-only version-control verb this module runs, and nothing else.
BLAME_ARGV: tuple = ("git", "blame", "--porcelain", "--")

AUTHOR_BUCKETS: dict = {
    "AIOSAI": "AGENT_AIOSAI",
    "AIPass": "AGENT_AIPASS",
    "dependabot[bot]": "BOT",
}

BUCKET_OTHER = "OTHER"

BUCKET_UNTRACKED = "UNTRACKED"

SECONDS_PER_DAY = 86400.0

#: Capped: hundreds of concurrent blames on a four-core box spend their time being scheduled.
BLAME_WORKERS = 8

#: The porcelain header line that opens each hunk: sha, source line, result line.
_HEADER = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)(?: \d+)?$")


@dataclass
class LineHistory:
    """Who last touched each line of one file, and when."""

    authors: Dict[int, str]
    times: Dict[int, int]
    tracked: bool


@dataclass
class FunctionHistory:
    """What blame says about one test function's line range."""

    author: str
    author_bucket: str
    age_days: Optional[float]
    days_since_touch: Optional[float]
    lines: int


def blame_files(root: Path, relpaths: Sequence[str]) -> Dict[str, LineHistory]:
    """One blame per file, in parallel, keyed by relative path."""
    with ThreadPoolExecutor(max_workers=BLAME_WORKERS) as pool:
        results = pool.map(lambda relpath: (relpath, _blame_one(root, relpath)), relpaths)
    return dict(results)


def _blame_one(root: Path, relpath: str) -> LineHistory:
    """The per-line author and time for one file, or an untracked marker."""
    try:
        completed = subprocess.run(
            [*BLAME_ARGV, relpath],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(f"[INVENTORY] blame failed for {relpath}, its rows carry no history: {exc}")
        return LineHistory(authors={}, times={}, tracked=False)

    if completed.returncode != 0:
        logger.info(f"[INVENTORY] {relpath} has no version-control history, its rows say UNTRACKED")
        return LineHistory(authors={}, times={}, tracked=False)

    return parse_porcelain(completed.stdout)


def parse_porcelain(output: str) -> LineHistory:
    """Per-line author and commit time from porcelain blame output.

    Porcelain gives the full header once per commit, so identity is cached per commit.
    Guard-and-continue, not elif: an elif ladder in this loop measures as depth five."""
    authors: Dict[int, str] = {}
    times: Dict[int, int] = {}
    by_commit: Dict[str, Tuple[str, int]] = {}
    commit = ""
    lineno = 0

    for line in output.splitlines():
        if match := _HEADER.match(line):
            commit, lineno = match.group(1), int(match.group(2))
            continue
        if line.startswith("\t") and commit:
            authors[lineno], times[lineno] = by_commit.get(commit, ("", 0))
            continue
        _remember_identity(line, commit, by_commit)

    return LineHistory(authors=authors, times=times, tracked=bool(authors))


def _remember_identity(line: str, commit: str, by_commit: Dict[str, Tuple[str, int]]) -> None:
    """Cache the author name or commit time a porcelain header line carries."""
    known = by_commit.get(commit, ("", 0))

    if line.startswith("author "):
        by_commit[commit] = (line[len("author ") :], known[1])
    if line.startswith("author-time "):
        by_commit[commit] = (known[0], int(line[len("author-time ") :]))


def attribute(history: LineHistory, first_line: int, last_line: int, now: float) -> FunctionHistory:
    """The history of one function, from the blame of the file it lives in.

    The author owns the MOST lines in the range, not the last touch: a formatter is not an author."""
    if not history.tracked:
        return _no_history()

    span = range(first_line, last_line + 1)
    authors = [history.authors[line] for line in span if line in history.authors]
    times = [history.times[line] for line in span if line in history.times]

    if not authors or not times:
        return _no_history()

    author = Counter(authors).most_common(1)[0][0]
    return FunctionHistory(
        author=author,
        author_bucket=bucket_for(author),
        age_days=round((now - min(times)) / SECONDS_PER_DAY, 1),
        days_since_touch=round((now - max(times)) / SECONDS_PER_DAY, 1),
        lines=len(authors),
    )


def _no_history() -> FunctionHistory:
    """The row for a function version control can say nothing about."""
    return FunctionHistory(author="", author_bucket=BUCKET_UNTRACKED, age_days=None, days_since_touch=None, lines=0)


def bucket_for(author: str) -> str:
    """The declared bucket for a commit author name."""
    return AUTHOR_BUCKETS.get(author, BUCKET_OTHER)


def author_census(histories: Sequence[FunctionHistory]) -> List[dict]:
    """Every distinct author name with its bucket and test count.

    Published so the OTHER bucket is auditable."""
    counts = Counter(history.author for history in histories if history.author)
    return [{"author": author, "bucket": bucket_for(author), "tests": count} for author, count in counts.most_common()]


def now_seconds() -> float:
    """The instant every age in one run is measured from."""
    return time.time()
