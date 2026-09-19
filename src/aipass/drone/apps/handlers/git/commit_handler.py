# =================== AIPass ====================
# Name: commit_handler.py
# Description: Commit handler with scoped staging
# Version: 1.2.0
# Created: 2026-05-12
# Modified: 2026-09-15
# =============================================

"""Commit handler with scoped staging."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aipass.prax import logger

# A commit subject and a plan subject are the same glance — the dashboard's
# last_commit_msg, the oneline log, the PR list — so they are the same number.
# Read prax's cap here; never copy the digits into drone (DPLAN-0347).
from aipass.prax.apps.modules.dashboard import SUBJECT_CAP
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.lock_handler import find_repo_root

# Per-branch pytest budget. The largest suite in the fleet (@api, 1298 tests)
# runs ~202s — a cap below a green suite's real runtime turns the gate into a
# false red that blocks every commit touching that branch.
TEST_GATE_TIMEOUT = 600

# The refusal IS the rule, in plain words. Every commit door renders this one
# text, so the shape is taught the same way wherever it is refused.
SUBJECT_REFUSAL = (
    "Commit subject is {length} chars; the cap is {cap}.\n"
    "\n"
    "The first line IS the subject — keep it under about 80 chars in\n"
    "type(scope): what form. Then a blank line, then the why in the body.\n"
    "A body of any length is fine and wanted.\n"
    "\n"
    "git log --oneline, the dashboard and the PR list all show the subject,\n"
    "so an essay there is read at every glance; in the body it is read once,\n"
    "by whoever needs it, and the record still keeps every word.\n"
    "\n"
    "Nothing was committed."
)


def commit_subject(message: str) -> str:
    """The subject line of *message* — what the oneline log and dashboards show.

    Leading blank lines are stripped first, which is what git's own message
    cleanup does before it takes line one, and what prax's ``cap_subject``
    reads: the same line is measured here and rendered there.

    Args:
        message: The full commit message; may be empty or body-only.

    Returns:
        The first non-empty line, stripped; "" when there is no such line.
    """
    stripped = (message or "").strip()
    if not stripped:
        return ""
    return stripped.splitlines()[0].strip()


def subject_refusal(message: str) -> str | None:
    """Refusal text when *message*'s subject is over the cap, else ``None``.

    Args:
        message: The full commit message about to be handed to git.

    Returns:
        The rendered refusal, or ``None`` when the subject fits.
    """
    subject = commit_subject(message)
    if len(subject) <= SUBJECT_CAP:
        return None
    return SUBJECT_REFUSAL.format(length=len(subject), cap=SUBJECT_CAP)


def _find_branch_for_path(filepath: str, repo_root: Path) -> tuple[str, Path] | None:
    """Find which branch a changed file belongs to by walking up to .trinity/."""
    abs_path = (repo_root / filepath).resolve()
    root = repo_root.resolve()
    # Templates ship full branch skeletons incl. .trinity/, so nested hits are
    # template trees, not citizens. Citizens never nest: outermost hit wins.
    found: tuple[str, Path] | None = None
    for parent in [abs_path.parent, *abs_path.parent.parents]:
        if not parent.is_relative_to(root):
            break
        if (parent / ".trinity").is_dir():
            found = (parent.name, parent)
    return found


def _run_test_gate(repo_root: Path) -> dict | None:
    """Run pytest for changed branches. Returns error dict if tests fail, None if all pass."""
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    changed_branches: dict[str, Path] = {}
    for line in status_result.stdout.splitlines():
        if len(line) < 4:
            continue
        filepath = line[3:].split(" -> ")[-1]
        result = _find_branch_for_path(filepath, repo_root)
        if result:
            name, branch_path = result
            changed_branches[name] = branch_path

    venv_python = repo_root / ".venv" / "bin" / "python"
    python_bin = str(venv_python) if venv_python.exists() else "python3"

    failed_branches: list[tuple[str, str]] = []
    for branch_name in sorted(changed_branches):
        test_dir = changed_branches[branch_name] / "tests"
        if not test_dir.is_dir():
            continue
        try:
            test_result = subprocess.run(
                [python_bin, "-m", "pytest", str(test_dir), "--tb=short", "-q"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
                timeout=TEST_GATE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            logger.warning("pytest timed out for branch %s (%ss limit)", branch_name, TEST_GATE_TIMEOUT)
            failed_branches.append((branch_name, f"pytest timed out ({TEST_GATE_TIMEOUT}s)"))
            continue
        if test_result.returncode != 0:
            failed_branches.append((branch_name, test_result.stdout.strip()))

    if not failed_branches:
        return None

    msg_parts = ["Test failures — fix before committing:"]
    for bname, output in failed_branches:
        msg_parts.append(f"\n--- {bname} ---\n{output}")
    return {
        "stdout": "",
        "stderr": "\n".join(msg_parts),
        "exit_code": 1,
    }


def stage_branch_dir(branch_dir: Path, repo_root: Path | None = None) -> dict:
    """Stage all changes under branch_dir.

    Shared utility used by both commit_handler and pr_handler.
    """
    if repo_root is None:
        repo_root = find_repo_root()

    try:
        rel_dir = branch_dir.resolve().relative_to(repo_root.resolve())
    except ValueError:
        logger.warning(
            "stage_branch_dir: branch_dir %s not relative to repo root %s",
            branch_dir,
            repo_root,
        )
        rel_dir = branch_dir

    add_result = subprocess.run(
        ["git", "add", str(rel_dir) + "/"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )

    if add_result.returncode != 0:
        return {
            "success": False,
            "rel_dir": rel_dir,
            "message": f"Failed to stage files: {add_result.stderr.strip()}",
        }

    return {"success": True, "rel_dir": rel_dir, "message": f"Staged files under {rel_dir}"}


def commit_changes(
    message: str,
    branch_dir: Path | None = None,
    all_files: bool = False,
    files: list[str] | None = None,
    repo_root: Path | None = None,
) -> dict:
    """Commit changes. With --all, stages the entire repo (not CWD-scoped).

    Post-DPLAN-0173: only devpulse commits, agents don't PR. Repo-wide
    staging is the correct default since dispatched agents work across
    multiple branch directories.

    With file paths, stages only those specific files (selective commit).

    *repo_root* defaults to the repo the caller stands in. The external-repo door
    names another one, and gets exactly the commit that repo's own seat gets —
    same staging, same lint and test gate on --all. Commit never pushes.

    An over-cap subject is refused FIRST, before any staging, lint or test run:
    the shape of the message is knowable without touching the repo, and a
    refusal that has already spent three minutes of pytest teaches nothing.
    """
    refusal = subject_refusal(message)
    if refusal is not None:
        return {"stdout": "", "stderr": refusal, "exit_code": 1}

    if repo_root is None:
        repo_root = find_repo_root()

    if files:
        add_result = subprocess.run(
            ["git", "add", "--"] + files,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if add_result.returncode != 0:
            return {"stdout": "", "stderr": f"Failed to stage: {add_result.stderr.strip()}", "exit_code": 1}
    elif all_files:
        import shutil

        ruff_bin = shutil.which("ruff")
        if not ruff_bin:
            venv_ruff = repo_root / ".venv" / "bin" / "ruff"
            if venv_ruff.exists():
                ruff_bin = str(venv_ruff)
        if ruff_bin:
            subprocess.run(
                [ruff_bin, "check", "--fix", "src/", "tests/"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            subprocess.run(
                [ruff_bin, "format", "src/", "tests/"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            lint_check = subprocess.run(
                [ruff_bin, "check", "src/", "tests/"],
                capture_output=True,
                text=True,
                cwd=str(repo_root),
            )
            if lint_check.returncode != 0:
                return {
                    "stdout": "",
                    "stderr": f"Lint errors — fix before committing:\n{lint_check.stdout.strip()}",
                    "exit_code": 1,
                }

        test_gate_result = _run_test_gate(repo_root)
        if test_gate_result is not None:
            return test_gate_result

        add_result = subprocess.run(
            ["git", "add", "-A"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if add_result.returncode != 0:
            return {"stdout": "", "stderr": f"Failed to stage: {add_result.stderr.strip()}", "exit_code": 1}

    diff_check = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    if diff_check.returncode == 0:
        return {
            "stdout": "",
            "stderr": "Nothing to commit: no changes staged",
            "exit_code": 1,
        }

    try:
        cmd = ["git", "commit", "-m", message]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("git commit failed: %s", exc)
        return {"stdout": "", "stderr": f"git commit failed: {exc}", "exit_code": 1}

    json_handler.log_operation(
        "commit_changes",
        {"message": message, "all_files": all_files, "files": files, "exit_code": result.returncode},
    )

    return {
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "exit_code": result.returncode,
    }
