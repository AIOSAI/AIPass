# =================== AIPass ====================
# Name: diff_scope.py
# Description: the changed LINES of a commit or working tree, as a mutation scope
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Probe what changed, not what exists.

WHY THIS EXISTS. `statement_deletion` measured at 454 mutants and 353 s on
canary's whole tree, which is a cadence. Seedgo is 13,743 probeable statements
and that is not. The same measurement on one real seedgo change set found 53
probeable statements in its added lines - 0.39% of the tree - and that IS a
cadence, on the fleet's largest branch. This module is the difference between
those two numbers, moved out of a one-off script and into the lane.

LINES, NOT FILES, AND THE ARTIFACT SAYS WHICH. A one-line fix in a 400-line
module must probe one statement, not four hundred. `GRANULARITY` is published
in every scope document, so a reader never has to infer from a count whether
the number means lines or files.

WHAT THIS SCOPE CANNOT SEE, stated the way the width axis states its limits:
`SCOPE_LIMITS` below. The load-bearing one is the second - a statement that did
not change but became unobserved BECAUSE of a change elsewhere is invisible
here, and that is a real class of defect, not a quibble. Diff scope is a cost
strategy. It is not a smaller version of the whole-tree pass.

THE COPY IS NOT A REPOSITORY. `.git` is in RSYNC_EXCLUDES, so the diff is read
from the REAL target before anything is copied. The line numbers carry over
unchanged because the copy is byte-identical - that is the same property that
makes coverage-mapped test selection sound, used a second time.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

#: What a scope row addresses. Published so a count is never ambiguous.
GRANULARITY_LINE = "changed_lines"
GRANULARITY_FILE = "changed_files"

#: The scope this module implements. Named as a constant rather than written
#: as a literal in the document, because the brief's boundary was "if you ship
#: file scope because line scope is harder, say so in the artifact" - and the
#: only way that promise survives a later edit is for the artifact to read the
#: same constant the filter reads.
GRANULARITY = GRANULARITY_LINE

#: No ref means the working tree: unstaged and staged edits against HEAD.
WORKING_TREE = None

#: `git diff` with no context. Every hunk header then describes exactly the
#: changed lines and nothing around them, which is the whole point: `-U3`
#: would silently widen a one-line fix into a seven-line scope.
NO_CONTEXT = "--unified=0"

#: Post-image hunk header: `@@ -a,b +c,d @@`. Only the `+` side is read - the
#: pre-image line numbers address a file that no longer exists on disk, and a
#: mutant can only be spliced into a line that is still there.
#:
#: The header gives only the START. The body is walked line by line from there,
#: because the header's COUNT includes context lines and `drone @git show`
#: refuses `--unified=0` (git would read it as a ref). Counting `+` lines in
#: the body instead of trusting the header makes the parse exact at any
#: context width, which is what keeps "changed LINES" honest when the diff
#: arrives with three lines of padding around every hunk.
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

#: `+++ b/<path>`, or `+++ /dev/null` for a deletion.
_NEW_PATH = re.compile(r"^\+\+\+ b/(.+)$")
_DEV_NULL = "+++ /dev/null"

#: Read-only git, through the one sanctioned interface. The lane already
#: shells out to rsync and pytest; this is the third, and it is the only one
#: that touches a repository.
#:
#: TWO DOORS, AND THEY SEE DIFFERENT THINGS - measured, not assumed:
#: `drone @git diff` is scoped to the CALLER'S OWN branch by cwd ("Show git
#: diff for your branch"), so a working-tree scope covers seedgo and nothing
#: else. Run against @canary it returned 0 files, and the first cut of this
#: module reported that as a measured, empty, perfectly clean campaign.
#: `drone @git show <ref>` prints one commit whole, every branch it touched,
#: read as whoever asked - which is both fleet-wide and honest in the trail.
#: So: a ref goes through `show`, the working tree goes through `diff`.
GIT_DIFF = ("drone", "@git", "diff")
GIT_SHOW = ("drone", "@git", "show")

#: The file drone reads to decide WHO is running a command.
CALLER_MARKER = Path(".trinity") / "passport.json"

#: A diff that takes longer than this is not a diff of a change set.
DIFF_TIMEOUT_SECONDS = 120

#: Every limit travels with the scope, the way WIDTH_AXIS_LIMITS travels with
#: the width axis. A reader who sees "53 probed" without these reads it as
#: "53 of the risk", and it is not.
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

    #: Target-relative posix path -> the post-image line numbers it changed at.
    changed: Dict[str, Set[int]] = field(default_factory=dict)

    #: What was diffed. `None` is the working tree.
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

        A multi-line statement whose MIDDLE changed is in scope: the mutation
        deletes the whole statement, so the whole span is what the change can
        have broken.
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
    """The branch directory drone should log this read against - seedgo's own.

    MEASURED, not assumed. Run from the repo root, `drone @git` refuses with
    "cannot verify caller" because there is no citizen there; run from the
    TARGET's directory, the read is logged against whichever branch is being
    audited. The auditor reads git as itself, from where it stands.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / CALLER_MARKER).is_file():
            return candidate
    raise DiffScopeError(
        f"no {CALLER_MARKER.as_posix()} above {__file__}, so `drone @git` has no caller to "
        "verify and the change set cannot be read"
    )


def _run_git(command: Sequence[str], what: str) -> str:
    """The raw unified diff, or raise naming what could not be read.

    The CWD says which citizen is asking, and that is not the same question as
    which repository: git answers from anywhere inside the tree, so reading
    from seedgo's own home costs nothing and keeps the trail naming the branch
    that actually ran it.
    """
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

    The body is walked, not the header count: a context line and an added line
    both advance the post-image counter, a removed line does not, and only the
    added ones are recorded. A pure-deletion hunk therefore contributes
    nothing - it adds no line, so there is no line to splice a mutant into.
    That is limit 2 falling out of the parse rather than being enforced on top
    of it.
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
            #: Commit-message prose, `index ...`, `similarity index ...`: not
            #: hunk body. `show` prints all of it above the first `+++`, and
            #: the message of a commit that quotes a diff would otherwise be
            #: read as one.
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

    Raises `DiffScopeError` when the target is not inside a repository the
    diff can address, and when the change set turns out to hold nothing of the
    target. An empty scope probes nothing and would otherwise print as a
    campaign that ran clean, which is the exact way this feature goes wrong.
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

    Deliberately untyped in the site: this filter reads `relpath`, `lineno`
    and `end_lineno` and nothing else, so it narrows a statement site and a
    function site with one implementation instead of two that drift.
    """
    return [s for s in sites if scope.holds(s.relpath, s.lineno, s.end_lineno)]
