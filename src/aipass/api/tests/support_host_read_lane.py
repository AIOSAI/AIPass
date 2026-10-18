# =================== AIPass ====================
# Name: support_host_read_lane.py
# Description: Shared helpers for the read lane's test files (test_host_read_lane*.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers shared by test_host_read_lane.py and its _feed, _changes and _history siblings."""

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


def status_document(rows: Any, scope: str = "branch", ok: bool = True, message: str = "changed") -> str:
    """drone's `status --json` document, as the door writes it to stdout."""
    # Built from git's two porcelain columns, never rendered lines: drone right-aligns 'A ' to ' A' on screen.
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
    """drone's `log --json` document."""
    rows = [{"sha": sha, "subject": subject} for sha, subject in commits]

    return json.dumps({"ok": ok, "commits": rows, "count": len(rows), "message": f"{len(rows)} commit(s)"})


def show_document(content: str, ref: str = "HEAD", ok: bool = True, message: str = "showed HEAD") -> str:
    """drone's `show --json` document."""
    # An ENVELOPE: `content` is git show's raw text, which the commit lane parses on structure.
    return json.dumps({"ok": ok, "ref": ref, "path": None, "content": content, "message": message})


def remote_document(url: str, name: str = "origin", redacted: bool = False, ok: bool = True) -> str:
    """drone's `remote --json` document, one remote."""
    return remotes_document([{"name": name, "fetch": url, "push": url, "redacted": redacted}], ok=ok)


def remotes_document(remotes: Any, ok: bool = True, message: str = "") -> str:
    """drone's `remote --json` document, any number of remotes."""
    return json.dumps(
        {
            "ok": ok,
            "remotes": remotes,
            "count": len(remotes),
            "message": message or f"{len(remotes)} remote(s)",
        }
    )


GIT_STATUS_STDOUT = status_document(
    (
        (" M", "src/aipass/demo/hello.txt"),
        ("??", "src/aipass/demo/brand_new.py"),
        (" D", "src/aipass/demo/nested/deep.txt"),
        ("R ", "src/aipass/demo/old_name.py -> src/aipass/demo/new_name.py"),
    ),
    message="4 file(s) changed under src/aipass/demo",
)

# `status --all`: paths arrive repo-relative, so the card's branch-local prefix stripping would be wrong here.
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

# The per-file lane finds a file by its `diff --git` header, never by a heading or a footer.
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

# What `drone @git show <ref>` puts in `content`: git's default --pretty=medium header, then the patch.
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
