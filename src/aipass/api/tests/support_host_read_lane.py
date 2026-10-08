# =================== AIPass ====================
# Name: support_host_read_lane.py
# Description: Shared helpers for the read lane's test files (test_host_read_lane*.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers shared by test_host_read_lane.py and its _feed, _changes and _history siblings.

No test_ prefix and no Test class, so pytest never collects it. Moved here
whole from test_host_read_lane.py when the file split along the unit under
test (api, the oversize split leg, 2026-10-08): drone's two stand-in error
classes, the feed line builders, and drone's --json documents with the
fixtures built from them, each used by two or more of the four files or by
the fixtures in conftest.py. The patch-target strings stay each file's own
constants: seedgo's discarded_patch rule judges a target imported from this
branch's package, and those patches silence loggers on purpose.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
from pathlib import Path
from typing import Any


class _BranchNotFound(Exception):
    """Stand-in for drone.BranchNotFoundError."""


class _RegistryBroken(Exception):
    """Stand-in for drone.RegistryError."""


def _event(ts: str, kind: str = "mail", title: str = "t", body: str = "b", source: str = "api") -> dict:
    """Build a feed line in @ai_mail's shape."""
    return {"ts": ts, "kind": kind, "title": title, "body": body, "source": source}


def _write_feed(path: Path, events: list) -> None:
    """Write events as JSON lines, one per line, in order."""
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


# @drone's real `git status` rendering, which is `f"  {status:>2} {path}"` per
# file between a header line and a scope footer. Paths are REPO-relative there;
# @baud's desktop card uses --relative and speaks branch-local names.
def status_document(rows: Any, scope: str = "branch", ok: bool = True, message: str = "changed") -> str:
    """
    drone's `status --json` document, as the door writes it to stdout.

    Every fixture in this file is built through here on purpose. The lane used
    to be fed hand-written RENDERED lines, and on 2026-08-18 that turned out to
    be the bug rather than the fixture: drone right-aligns the porcelain code
    for the screen, so 'A ' reaches a reader as ' A' and no test written by
    hand ever saw it. Building from the two columns git actually reports means
    a fixture cannot express a status drone could not have sent.

    Args:
        rows: (status, path) pairs, status being porcelain's two columns.
        scope: branch or repo, as the door names its own scope.
        ok: The verdict.
        message: The door's own sentence.

    Returns:
        The document, serialised.
    """
    files = [{"status": status, "path": path, "index": status[:1], "worktree": status[1:2]} for status, path in rows]

    return json.dumps(
        {
            "ok": ok,
            "branch": "demo",
            "scope": scope,
            "files": files,
            "total": len(files),
            "message": message,
        }
    )


def log_document(commits: Any, ok: bool = True) -> str:
    """
    drone's `log --json` document.

    Args:
        commits: (sha, subject) pairs, newest first.
        ok: The verdict.

    Returns:
        The document, serialised.
    """
    rows = [{"sha": sha, "subject": subject} for sha, subject in commits]

    return json.dumps({"ok": ok, "commits": rows, "count": len(rows), "message": f"{len(rows)} commit(s)"})


def show_document(content: str, ref: str = "HEAD", ok: bool = True, message: str = "showed HEAD") -> str:
    """
    drone's `show --json` document.

    MEASURED 2026-08-18: this one is an ENVELOPE. Its `content` is git show's
    own text — header, then patch — so the fixtures below still carry raw text
    inside it, and the commit lane still parses that text on structure.

    Args:
        content: The raw output git show produced.
        ref: The revision asked for.
        ok: The verdict.
        message: The door's own sentence.

    Returns:
        The document, serialised.
    """
    return json.dumps({"ok": ok, "ref": ref, "path": None, "content": content, "message": message})


def remote_document(url: str, name: str = "origin", redacted: bool = False, ok: bool = True) -> str:
    """
    drone's `remote --json` document, one remote.

    Args:
        url: The URL for both fetch and push.
        name: Which remote.
        redacted: Whether the door says it already redacted something.
        ok: The verdict.

    Returns:
        The document, serialised.
    """
    return remotes_document([{"name": name, "fetch": url, "push": url, "redacted": redacted}], ok=ok)


def remotes_document(remotes: Any, ok: bool = True, message: str = "") -> str:
    """
    drone's `remote --json` document, any number of remotes.

    Args:
        remotes: The rows, in the door's own order.
        ok: The verdict.
        message: The door's own sentence.

    Returns:
        The document, serialised.
    """
    return json.dumps(
        {
            "ok": ok,
            "remotes": remotes,
            "count": len(remotes),
            "message": message or f"{len(remotes)} remote(s)",
        }
    )


# The card's own fixture, in git's two columns. ' M' is an unstaged edit, '??'
# a file git has never seen, ' D' an unstaged delete and 'R ' a staged rename.
GIT_STATUS_STDOUT = status_document(
    (
        (" M", "src/aipass/demo/hello.txt"),
        ("??", "src/aipass/demo/brand_new.py"),
        (" D", "src/aipass/demo/nested/deep.txt"),
        ("R ", "src/aipass/demo/old_name.py -> src/aipass/demo/new_name.py"),
    ),
    message="4 file(s) changed under src/aipass/demo",
)

# drone's `status --all` document. Same per-file shape, but the scope is the
# whole repo and the paths already arrive repo-relative — so the branch-local
# prefix stripping that the CARD needs would be actively wrong here.
GIT_STATUS_ALL_STDOUT = status_document(
    (
        (" M", "src/aipass/demo/hello.txt"),
        (" M", "src/aipass/other/thing.py"),
        ("??", "src/aipass/demo/brand_new.py"),
        (" D", "src/aipass/third/gone.txt"),
    ),
    scope="repo",
    message="4 file(s) changed under the repository",
)

# Two files in one unified diff, in git's own machine-stable framing. The
# per-file lane finds a file by its header, never by a heading or a footer.
TWO_FILE_DIFF = """diff --git a/src/aipass/demo/hello.txt b/src/aipass/demo/hello.txt
index 1111111..2222222 100644
--- a/src/aipass/demo/hello.txt
+++ b/src/aipass/demo/hello.txt
@@ -1 +1 @@
-hello
+hello world
diff --git a/src/aipass/other/thing.py b/src/aipass/other/thing.py
index 3333333..4444444 100644
--- a/src/aipass/other/thing.py
+++ b/src/aipass/other/thing.py
@@ -1,2 +1,3 @@
 keep
-drop
+add one
+add two
"""

# What `drone @git show <ref>` puts in its document's `content` field: git's
# default --pretty=medium header, then the patch. Measured against the real
# door on 2026-08-17, and re-measured on 2026-08-18 when --json arrived — the
# flag wrapped this text in an envelope and did not structure it.
GIT_SHOW_TEXT = (
    """commit 7edf8c2dfcccbc1ce1b04d8420405f98e212a474
Author: AIOSAI <aipass.system@gmail.com>
Date:   Sat Aug 15 10:15:22 2026 -0700

    feat(demo): the subject line

    And a second paragraph of body.

"""
    + TWO_FILE_DIFF
)

GIT_SHOW_STDOUT = show_document(GIT_SHOW_TEXT, ref="7edf8c2d")

GIT_LOG_STDOUT = log_document(
    (
        ("b47462b7", "feat(fleet): the newest one"),
        ("7edf8c2d", "feat(demo): the subject line"),
        ("cb4afb12", "feat(host): an older one"),
    )
)
