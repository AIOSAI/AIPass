# =================== AIPass ====================
# Name: diff_scope.py
# Description: the changed LINES of a commit or working tree, as a mutation scope
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-10-17
# =============================================

"""Probe what changed, not what exists.

A cost strategy, not a smaller whole-tree pass (see `SCOPE_LIMITS`). Read from the
real target before the copy, since `.git` is excluded from it.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

GRANULARITY_LINE = "changed_lines"
GRANULARITY_FILE = "changed_files"

#: The artifact reads the same constant the filter reads, so it cannot misstate lines vs files.
GRANULARITY = GRANULARITY_LINE

WORKING_TREE = None

#: `-U3` would silently widen a one-line fix into a seven-line scope.
NO_CONTEXT = "--unified=0"

#: Only the post-image START is read; the body is walked because `drone @git show`
#: refuses `--unified=0`, so the header count includes context lines.
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

_NEW_PATH = re.compile(r"^\+\+\+ b/(.+)$")
_DEV_NULL = "+++ /dev/null"

#: `drone @git diff` is scoped to the caller's own branch by cwd; `drone @git show <ref>`
#: prints a whole commit fleet-wide. A ref goes through `show`, the working tree `diff`.
GIT_DIFF = ("drone", "@git", "diff")
GIT_SHOW = ("drone", "@git", "show")

CALLER_MARKER = Path(".trinity") / "passport.json"

DIFF_TIMEOUT_SECONDS = 120

#: Travels with the scope: "53 probed" without these reads as "53 of the risk".
SCOPE_LIMITS: Sequence[str] = (
    "It probes changed lines, so a statement that is unchanged but became UNOBSERVED because of a "
    "change elsewhere - a test weakened, a fixture rewritten, a caller that stopped reaching it - is "
    "invisible to this scope. That is a real class of defect and diff scope does not cover it.",
    "It reads the POST-image only. A statement deleted by the change has no line to splice into, so "
    "a deletion is out of reach here by construction rather than by choice.",
    "A rename or a move reads as a whole-file addition, so the scope for that commit is the whole "
    "file and the cost estimate for it is the file's, not the edit's.",
    "A changed TEST does not put any source statement in scope. The scope is over source lines, and "
    "a commit that only touches tests probes nothing - which is correct, and is not the same as clean.",
    "UNTRACKED FILES ARE INVISIBLE. `git diff` reports changes to tracked files, so a brand-new "
    "module has no hunk and none of its statements enter scope - measured on this lane's own "
    "working tree, where two new modules contributed 0 of the 342 lines. A new file is exactly the "
    "code with the least history, so this is the limit that bites hardest on the work most worth "
    "probing: stage it, or run whole-tree.",
    "THE WORKING-TREE SCOPE SEES ONE BRANCH - the caller's. `drone @git diff` is scoped by cwd to the "
    "branch that ran it, so a working-tree scope over another branch's target comes back empty. A ref "
    "goes through `drone @git show`, which prints the commit whole and does reach every branch, so "
    "cross-branch scoping is per COMMIT and not per working tree.",
    "A REF OLDER THAN HEAD ADDRESSES A TREE THAT MOVED. The line numbers come from the commit; the "
    "mutants are spliced into the tree on disk now. Where a later commit edited the same file, the "
    "scope points at a line that has shifted - measured on canary's fourth build, where 2 of 4 source "
    "files were byte-identical at HEAD and the entry point was not. Scoping a commit at the moment it "
    "lands, which is the cadence this is for, has no drift; scoping backwards does.",
    "It is a COST strategy, never a coverage claim. A clean diff-scoped run says nothing about the "
    "13,690 statements it did not probe; only a whole-tree pass says anything about those.",
)


class DiffScopeError(RuntimeError):
    """The change set could not be read, so there is no scope to probe."""


@dataclass
class DiffScope:
    """The changed lines of one target, addressed the way sites are addressed."""

    changed: Dict[str, Set[int]] = field(default_factory=dict)

    ref: Optional[str] = None

    @property
    def files(self) -> int:
        """How many files the change set touched inside the target."""
        return len(self.changed)

    @property
    def lines(self) -> int:
        """How many lines it changed inside the target."""
        return sum(len(numbers) for numbers in self.changed.values())

    def holds(self, relpath: str, lineno: int, end_lineno: int) -> bool:
        """True when any line of `lineno..end_lineno` changed.

        A changed middle line puts the whole statement in scope: the mutation deletes all of it.
        """
        numbers = self.changed.get(relpath)
        if not numbers:
            return False
        return any(n in numbers for n in range(lineno, end_lineno + 1))

    def to_document(self) -> dict:
        """The artifact's scope block."""
        return {
            "granularity": GRANULARITY,
            "ref": self.ref if self.ref is not None else "working_tree",
            "changed_files": self.files,
            "changed_lines": self.lines,
            "limits": list(SCOPE_LIMITS),
        }


def caller_home() -> Path:
    """The branch directory drone should log this read against - seedgo's own."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / CALLER_MARKER).is_file():
            return candidate
    raise DiffScopeError(
        f"no {CALLER_MARKER.as_posix()} above {__file__}, so `drone @git` has no caller to "
        "verify and the change set cannot be read"
    )


def _run_git(command: Sequence[str], what: str) -> str:
    """The raw unified diff, or raise naming what could not be read."""
    try:
        result = subprocess.run(
            list(command), capture_output=True, text=True, cwd=str(caller_home()), timeout=DIFF_TIMEOUT_SECONDS
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise DiffScopeError(f"{what} could not be read: {type(exc).__name__}: {exc}") from exc

    if result.returncode != 0:
        raise DiffScopeError(f"{what} could not be read ({result.returncode}): {result.stderr.strip()[:300]}")

    text = result.stdout
    if not text.strip() or text.strip().startswith("Refusing"):
        raise DiffScopeError(f"{what} came back with no diff: {text.strip()[:200] or 'empty output'}")
    return text


def parse_changed_lines(diff_text: str) -> Dict[str, Set[int]]:
    """Repo-relative path -> the post-image line numbers the diff ADDED.

    A pure-deletion hunk adds no line, so there is nowhere to splice a mutant.
    """
    changed: Dict[str, Set[int]] = {}
    current: Optional[str] = None
    post = 0

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            match = _NEW_PATH.match(line)
            current = match.group(1) if match else None
            continue

        if line.startswith("--- ") or line.startswith("diff --git "):
            continue

        hunk = _HUNK.match(line)
        if hunk is not None:
            post = int(hunk.group(1))
            continue

        if current is None or post == 0:
            continue

        if line.startswith("+"):
            changed.setdefault(current, set()).add(post)
            post += 1
        elif line.startswith("-") or line.startswith("\\"):
            continue
        elif line.startswith(" ") or line == "":
            post += 1
        else:
            #: Above the first `+++` is commit prose; a message quoting a diff is not a hunk.
            post = 0
            current = None

    return changed


def _target_relative(repo_path: str, target_prefix: str) -> Optional[str]:
    """`src/aipass/seedgo/apps/x.py` -> `apps/x.py`, or None if outside."""
    if not repo_path.startswith(target_prefix):
        return None
    return repo_path[len(target_prefix) :]


def read_scope(target: Path, repo_root: Path, ref: Optional[str] = WORKING_TREE) -> DiffScope:
    """The change set of `target`, read from the REAL tree before any copy.

    Raises `DiffScopeError` on no repository or an empty change set (an empty scope reads clean).
    """
    try:
        prefix = target.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise DiffScopeError(f"{target} is not inside {repo_root}, so its change set cannot be read") from exc

    prefix = f"{prefix}/" if prefix and not prefix.endswith("/") else prefix
    if ref is None:
        text = _run_git([*GIT_DIFF, NO_CONTEXT], "the working tree")
    else:
        text = _run_git([*GIT_SHOW, ref], f"commit {ref}")

    changed: Dict[str, Set[int]] = {}
    for repo_path, numbers in parse_changed_lines(text).items():
        relpath = _target_relative(repo_path, prefix)
        if relpath is not None:
            changed[relpath] = numbers

    scope = DiffScope(changed=changed, ref=ref)
    if not changed:
        raise DiffScopeError(
            f"{'the working tree' if ref is None else ref} changed nothing inside {target.name}, so the "
            f"scope is empty and an empty scope is not a clean run"
            + ("" if ref is not None else "; note `drone @git diff` reports the CALLER's branch only")
        )

    logger.info(
        "[audit_tests] diff scope: %d line(s) across %d file(s) in %s",
        scope.lines,
        scope.files,
        target.name,
    )
    json_handler.log_operation(
        "diff_scope_read",
        {"target": target.name, "files": scope.files, "lines": scope.lines, "ref": ref or "working_tree"},
    )
    return scope


def apply(sites: Sequence, scope: DiffScope) -> List:
    """Every site whose own span intersects the change set.

    Untyped on purpose: one filter for statement and function sites, so they cannot drift.
    """
    return [s for s in sites if scope.holds(s.relpath, s.lineno, s.end_lineno)]
