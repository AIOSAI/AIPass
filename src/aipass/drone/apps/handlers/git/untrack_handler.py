# =================== AIPass ====================
# Name: untrack_handler.py
# Description: Take tracked files out of the index, leaving the working tree as it is
# Version: 1.0.0
# Created: 2026-10-15
# Modified: 2026-10-15
# =============================================

"""Take tracked files out of the index, leaving the working tree as it is.

The twin of ``git rm --cached``. A ``.gitignore`` line never untracks a file
that is already in the index, so four seedgo ratchet artifacts carrying a home
path rode every clone after their directory was ignored, and with raw git
blocked for every seat there was no door to take them out (DPLAN-0409 C1).

Each path is classified first, by the same rule ``tracked`` uses. Only a
TRACKED path is touched; every other class is refused by name and nothing is
done for it. Nothing here commits.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.tracked_handler import TRACKED, classify

# Refusal texts, printed exactly as written here; --help renders the same constants.
REFUSE_NOT_TRACKED = "untrack refused: {path} is {state}, not in the index. Nothing was done for it."
REFUSE_DIRECTORY = (
    "untrack refused: {path} is a directory. Name files; a directory would untrack everything under it "
    "(or give --recursive). Nothing was done for it."
)
# The next step names no paths on purpose: commit with paths runs `git add` on
# them, which stages the file straight back (or fails on an ignored one).
NEXT_STEP = (
    "Untracked {count} file(s) from the index; the working tree is unchanged. "
    'Commit the removal: drone @git commit "<message>"  (no paths: naming them stages them again)'
)


def _remove_cached(repo_root: Path, path: str, recursive: bool) -> subprocess.CompletedProcess[str]:
    argv = ["git", "rm", "--cached", "--quiet", *(["-r"] if recursive else []), "--", path]
    return subprocess.run(argv, cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8")


def untrack(repo_root: Path, cwd: Path | None, tokens: list[str], recursive: bool = False) -> dict:
    """Take each TRACKED path out of the index; refuse every other path by name, with its class.

    A directory is refused unless *recursive*, then leaves the index whole. The
    working tree is never touched and nothing is committed. Refused paths do
    not stop the accepted ones.

    Returns:
        Dict with ok (bool: False only when the paths could not be classified),
        removed (repo-relative paths that left the index), refused (one line
        per path not handled) and message (str).
    """
    classified = classify(repo_root, cwd, tokens)
    if not classified["ok"]:
        return {"ok": False, "removed": [], "refused": [], "message": classified["message"]}

    removed: list[str] = []
    refused: list[str] = []
    for state, shown in classified["rows"]:
        if state != TRACKED:
            refused.append(REFUSE_NOT_TRACKED.format(path=shown, state=state))
            continue
        is_dir = (repo_root / shown).is_dir()
        if is_dir and not recursive:
            refused.append(REFUSE_DIRECTORY.format(path=shown))
            continue
        try:
            result = _remove_cached(repo_root, shown, is_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("git untrack: git rm --cached could not run for %s: %s", shown, exc)
            refused.append(f"untrack failed for {shown}: git rm --cached could not run ({exc})")
            continue
        if result.returncode != 0:
            logger.warning("git untrack: git rm --cached refused %s: %s", shown, result.stderr.strip())
            refused.append(f"untrack failed for {shown}: {result.stderr.strip()}")
            continue
        removed.append(shown)

    logger.info("git untrack: %d left the index, %d refused", len(removed), len(refused))
    json_handler.log_operation("git_untrack", {"removed": removed, "refused": len(refused)})
    return {"ok": True, "removed": removed, "refused": refused, "message": NEXT_STEP.format(count=len(removed))}
