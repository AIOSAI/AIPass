# =================== AIPass ====================
# Name: init_handler.py
# Description: init --repo: put a brand-new project directory under git, on main, nothing else
# Version: 1.0.0
# Created: 2026-11-08
# Modified: 2026-11-08
# =============================================

"""``drone @git init --repo <path>``: make an existing directory a new git repository on ``main``.

The door's one verb that runs where no repository exists yet, so it resolves its own target
instead of ``repo_door.resolve_repo``. No remote, no first commit: those are their own verbs.
Refused for a directory that already is or sits in a repository, and for anything in AIPass.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.git import repo_door
from aipass.drone.apps.handlers.json import json_handler

REFUSE_ARGS = "init takes no arguments: drone @git init --repo <path>"
REFUSE_HAS_GIT = "init refused: {path} already holds a .git. It is a repository; nothing was changed."
REFUSE_IN_AIPASS = "init refused: {path} is inside the AIPass tree. A new project lives outside it."
REFUSE_IN_REPO = (
    "init refused: {path} sits inside the git repository at {toplevel}; a repo nested in another "
    "is tracked by neither. Nothing was changed."
)
INITIALIZED = "Initialized an empty git repository on main at {path}. No remote, no commit."


def _target(raw: str, aipass_root: Path) -> Path:
    """The directory *raw* names, resolved like the door's own; raise ValueError with the refusal."""
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = aipass_root / candidate
    if not candidate.exists():
        raise ValueError(repo_door.REFUSE_MISSING.format(path=raw))
    if not candidate.is_dir():
        raise ValueError(repo_door.REFUSE_NOT_DIR.format(path=raw))
    resolved = candidate.resolve()
    if resolved.is_relative_to(aipass_root.resolve()):
        raise ValueError(REFUSE_IN_AIPASS.format(path=raw))
    marker = resolved / ".git"
    if marker.is_file() or (marker.is_dir() and any(marker.iterdir())):
        raise ValueError(REFUSE_HAS_GIT.format(path=raw))
    toplevel = repo_door._git_toplevel(resolved)
    if toplevel is not None:
        raise ValueError(REFUSE_IN_REPO.format(path=raw, toplevel=toplevel))
    return resolved


def init_repo(caller: str, flag: repo_door.RepoFlag, aipass_root: Path) -> dict:
    """``git init -b main`` in the named directory after every check; one door record either way."""
    repo: Path | str = flag.path
    try:
        if flag.args:
            raise ValueError(REFUSE_ARGS)
        repo = _target(flag.path, aipass_root)
        result = subprocess.run(
            ["git", "init", "-q", "-b", "main"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=repo_door.GIT_LOCAL_TIMEOUT,
        )
        if result.returncode != 0:
            raise ValueError(f"git init failed in {repo}: {(result.stderr or result.stdout).strip()}")
        json_handler.log_operation("init_repo", {"caller": caller, "repo": str(repo)})
        answer = {"stdout": INITIALIZED.format(path=repo), "stderr": "", "exit_code": 0}
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        logger.warning("git repo door refused 'init' --repo %s: %s", flag.path, exc)
        answer = {"stdout": "", "stderr": str(exc), "exit_code": 1}

    repo_door.record_use(
        caller=caller,
        verb="init",
        args=flag.args,
        requested=flag.path,
        repo=repo,
        head_before="",
        head_after="",
        exit_code=answer["exit_code"],
        outcome=repo_door.OUTCOME_RAN if answer["exit_code"] == 0 else repo_door.OUTCOME_REFUSED,
        reason=answer["stderr"],
    )
    return answer
