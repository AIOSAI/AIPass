# =================== AIPass ====================
# Name: test_host_read_lane.py
# Description: Tests for the host API read lane — feed cursor, file fence, diff
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""Tests for apps/handlers/host/{feed,reads}.py and their routes.

FPLAN-0411 Phase 2 (partial: feed + files + diff; fleet held on C1).

The two things that must not be got wrong here are the cursor (a stale one is
the TG 10-hour outage species) and the fence (a remote caller choosing what to
read). Both carry the most tests.

Tests — handlers/host/feed.py (design call D3):
- read_feed: no cursor returns the most recent window, newest cursor
- read_feed: empty feed returns an empty envelope, no crash
- read_feed: missing feed file reads as empty, not an error
- read_feed: cursor mid-feed returns everything at or after it
- read_feed: boundary event is RE-DELIVERED (at-least-once, dupes over drops)
- read_feed: cursor older than the feed flags gap + gap_reason=feed_trimmed
- read_feed: cursor ahead of the feed clamps, returns empty, never spins
- read_feed: limit caps the window and reports more=True (no silent cap)
- read_feed: limit is clamped to MAX_LIMIT
- read_feed: malformed lines are skipped, good ones still returned
- read_feed: lines without a ts are skipped
- read_feed: file order is preserved (never re-sorted)
- read_feed: unreadable feed raises FeedUnavailable rather than faking empty
- read_feed: a real trim (400->200) leaves an old cursor flagged, not silent

Tests — handlers/host/reads.py (the name fence):
- _fence: absolute path refused
- _fence: '..' component refused
- _fence: nested '..' refused
- _fence: symlink escaping the branch refused (post-resolution check)
- _fence: empty name refused
- _fence: legitimate nested file accepted
- _fence: missing file refused
- resolve_branch_root: known branch resolves via the registry
- resolve_branch_root: email form resolves
- resolve_branch_root: unknown branch refused
- resolve_branch_root: empty branch refused
- resolve_branch_root: unreadable registry raises ReadUnavailable
- read_file: returns content and byte count
- read_file: over-cap file is REFUSED, never silently truncated
- read_file: non-UTF8 file refused
- read_file: project mismatch refused
- read_diff: routes through drone, never raw git
- read_diff: staged flag is passed through
- read_diff: drone missing raises ReadUnavailable
- read_diff: timeout raises ReadUnavailable
- read_diff: non-zero exit raises ReadUnavailable
- read_diff: oversized diff is truncated AND reports truncated=True

Tests — routes:
- GET /v1/feed: 401 without a token
- GET /v1/feed: 200 with a read token, returns the envelope
- GET /v1/feed: gap surfaces through the route
- GET /v1/files: 401 without a token
- GET /v1/files: 200 returns file content
- GET /v1/files: fence violation is 400 with the error envelope
- GET /v1/diff: 200 returns diff text
- GET /v1/diff: unknown branch is 400
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import feed as host_feed
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens


PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"

PATCH_FEED_PATH = "aipass.api.apps.handlers.host.feed.feed_path"
PATCH_FEED_LOGGER = "aipass.api.apps.handlers.host.feed.logger"
PATCH_FEED_JSON = "aipass.api.apps.handlers.host.feed.json_handler"

PATCH_READS_LOGGER = "aipass.api.apps.handlers.host.reads.logger"
PATCH_READS_JSON = "aipass.api.apps.handlers.host.reads.json_handler"
PATCH_READS_DRONE = "aipass.api.apps.handlers.host.reads.drone"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_HOST_FLEET = "aipass.api.apps.handlers.host.fleet"


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


@pytest.fixture
def feed_file(tmp_path: Path):
    """A temp feed file wired into the handler."""
    path = tmp_path / "notifications.jsonl"
    with patch(PATCH_FEED_PATH, return_value=path), patch(PATCH_FEED_LOGGER), patch(PATCH_FEED_JSON):
        yield path


@pytest.fixture
def fake_repo(tmp_path: Path):
    """A repo root with a registry and one branch, wired into the handler."""
    root = tmp_path / "FakeRepo"
    branch = root / "src" / "aipass" / "demo"
    branch.mkdir(parents=True)
    (branch / "hello.txt").write_text("hello world", encoding="utf-8")
    (branch / "nested").mkdir()
    (branch / "nested" / "deep.txt").write_text("deep", encoding="utf-8")
    (root / "secret.txt").write_text("do not read me", encoding="utf-8")

    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps({"branches": [{"name": "DEMO", "path": str(branch), "email": "@demo"}]}),
        encoding="utf-8",
    )

    # Stand in for @drone's public surface — the door this handler resolves
    # through. Its real error classes are kept so the refused/unavailable split
    # is exercised rather than assumed.
    fake_drone = MagicMock()
    fake_drone.BranchNotFoundError = _BranchNotFound
    fake_drone.RegistryError = _RegistryBroken
    fake_drone.get_registry_path.return_value = str(registry)

    def _info(name: str) -> dict:
        if name.lower() not in ("demo", "@demo"):
            raise _BranchNotFound(name)
        return {"name": "DEMO", "path": str(branch), "email": "@demo"}

    fake_drone.get_branch_info.side_effect = _info

    with patch(PATCH_READS_DRONE, fake_drone), patch(PATCH_READS_LOGGER), patch(PATCH_READS_JSON):
        yield {"root": root, "branch": branch, "registry": registry, "drone": fake_drone}


# =============================================
# FEED — the cursor
# =============================================


class TestFeedCursor:
    """The cursor clamps both ends and never spins."""

    def test_no_cursor_returns_recent_window(self, feed_file: Path) -> None:
        """First contact gets the latest window, not the whole file."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00"), _event("2026-08-14T11:00:00")])

        result = host_feed.read_feed()

        assert len(result["events"]) == 2
        assert result["cursor"] == "2026-08-14T11:00:00"
        assert result["gap"] is False

    def test_empty_feed_returns_empty_envelope(self, feed_file: Path) -> None:
        """An empty feed is a real state, not an error."""
        feed_file.write_text("", encoding="utf-8")

        result = host_feed.read_feed()

        assert result["events"] == []
        assert result["gap"] is False

    def test_missing_feed_file_reads_as_empty(self, feed_file: Path) -> None:
        """No feed yet is quiet, matching @ai_mail's own doctrine."""
        result = host_feed.read_feed()

        assert result["events"] == []

    def test_cursor_mid_feed_returns_the_remainder(self, feed_file: Path) -> None:
        """The ordinary poll: everything at or after the cursor."""
        _write_feed(
            feed_file,
            [_event("2026-08-14T10:00:00"), _event("2026-08-14T11:00:00"), _event("2026-08-14T12:00:00")],
        )

        result = host_feed.read_feed(since="2026-08-14T11:00:00")

        assert [event["ts"] for event in result["events"]] == ["2026-08-14T11:00:00", "2026-08-14T12:00:00"]

    def test_boundary_event_is_redelivered(self, feed_file: Path) -> None:
        """At-least-once on purpose: two events can share a microsecond, and a
        duplicate is a nuisance where a dropped alert is the whole failure."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00"), _event("2026-08-14T11:00:00")])

        result = host_feed.read_feed(since="2026-08-14T11:00:00")

        assert [event["ts"] for event in result["events"]] == ["2026-08-14T11:00:00"]

    def test_cursor_older_than_feed_flags_the_gap(self, feed_file: Path) -> None:
        """THE trim case: clamp and TELL the phone, never under-report silently."""
        _write_feed(feed_file, [_event("2026-08-14T11:00:00"), _event("2026-08-14T12:00:00")])

        result = host_feed.read_feed(since="2026-08-14T09:00:00")

        assert result["gap"] is True
        assert result["gap_reason"] == host_feed.GAP_TRIMMED
        assert len(result["events"]) == 2

    def test_cursor_ahead_of_feed_clamps_and_returns_empty(self, feed_file: Path) -> None:
        """The outage species: ahead of the feed clamps and delivers, never spins."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00")])

        result = host_feed.read_feed(since="2026-09-01T00:00:00")

        assert result["events"] == []
        assert result["cursor"] == "2026-08-14T10:00:00"
        assert result["gap"] is False

    def test_real_trim_leaves_an_old_cursor_flagged(self, feed_file: Path) -> None:
        """Simulates @ai_mail's actual 400->200 trim: a cursor into the dropped
        half must come back flagged, which a line-offset cursor could not do."""
        original = [_event(f"2026-08-14T10:{minute:02d}:00") for minute in range(60)]
        _write_feed(feed_file, original)
        old_cursor = original[5]["ts"]

        _write_feed(feed_file, original[30:])  # the trim drops the oldest half

        result = host_feed.read_feed(since=old_cursor)

        assert result["gap"] is True
        assert result["gap_reason"] == host_feed.GAP_TRIMMED


class TestFeedLimits:
    """Caps are enforced and reported."""

    def test_limit_caps_window_and_reports_more(self, feed_file: Path) -> None:
        """No silent caps — a truncated window says so."""
        _write_feed(feed_file, [_event(f"2026-08-14T10:{minute:02d}:00") for minute in range(10)])

        result = host_feed.read_feed(since="2026-08-14T10:00:00", limit=3)

        assert len(result["events"]) == 3
        assert result["more"] is True

    def test_more_is_false_when_window_is_complete(self, feed_file: Path) -> None:
        """The ordinary case does not cry wolf."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00")])

        result = host_feed.read_feed(since="2026-08-14T10:00:00", limit=10)

        assert result["more"] is False

    def test_limit_is_clamped_to_max(self, feed_file: Path) -> None:
        """A caller cannot ask for the world."""
        _write_feed(feed_file, [_event(f"2026-08-14T10:{minute:02d}:00") for minute in range(5)])

        result = host_feed.read_feed(limit=99999)

        assert len(result["events"]) == 5

    def test_zero_limit_is_raised_to_one(self, feed_file: Path) -> None:
        """A zero limit would poll forever returning nothing."""
        _write_feed(feed_file, [_event("2026-08-14T10:00:00")])

        result = host_feed.read_feed(limit=0)

        assert len(result["events"]) == 1


class TestFeedRobustness:
    """Malformed input is skipped, real failure is reported."""

    def test_malformed_lines_are_skipped(self, feed_file: Path) -> None:
        """One bad line must not blind the phone to the good ones."""
        feed_file.write_text(
            json.dumps(_event("2026-08-14T10:00:00")) + "\nnot json\n" + json.dumps(_event("2026-08-14T11:00:00")),
            encoding="utf-8",
        )

        result = host_feed.read_feed()

        assert len(result["events"]) == 2

    def test_lines_without_ts_are_skipped(self, feed_file: Path) -> None:
        """The cursor IS the ts — an event without one cannot be positioned."""
        feed_file.write_text(
            json.dumps({"kind": "mail", "title": "no ts"}) + "\n" + json.dumps(_event("2026-08-14T10:00:00")),
            encoding="utf-8",
        )

        result = host_feed.read_feed()

        assert len(result["events"]) == 1

    def test_file_order_is_preserved(self, feed_file: Path) -> None:
        """Never re-sorted: a sort would shuffle same-ts events and make the
        cursor non-monotonic."""
        _write_feed(feed_file, [_event("2026-08-14T12:00:00"), _event("2026-08-14T10:00:00")])

        result = host_feed.read_feed()

        assert [event["ts"] for event in result["events"]] == ["2026-08-14T12:00:00", "2026-08-14T10:00:00"]

    def test_unreadable_feed_raises_rather_than_faking_empty(self, feed_file: Path) -> None:
        """Fail honest: an unreadable feed is not 'no notifications'."""
        feed_file.write_text("{}", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=OSError("boom")):
            with pytest.raises(host_feed.FeedUnavailable):
                host_feed.read_feed()


# =============================================
# READS — the name fence
# =============================================


class TestFence:
    """A remote caller must never choose what gets read."""

    def test_absolute_path_refused(self, fake_repo: dict) -> None:
        """An absolute name is the exact thing the fence exists to reject."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads._fence(fake_repo["branch"], "/etc/passwd")

    def test_parent_traversal_refused(self, fake_repo: dict) -> None:
        """'..' never survives, checked before the filesystem is touched."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads._fence(fake_repo["branch"], "../../secret.txt")

    def test_nested_traversal_refused(self, fake_repo: dict) -> None:
        """A '..' buried mid-path is the same attack with better manners."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads._fence(fake_repo["branch"], "nested/../../secret.txt")

    def test_symlink_escape_refused(self, fake_repo: dict) -> None:
        """The post-resolution check — the only gate that sees a symlink out."""
        if sys.platform == "win32":
            pytest.skip("POSIX symlinks")

        link = fake_repo["branch"] / "escape.txt"
        link.symlink_to(fake_repo["root"] / "secret.txt")

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads._fence(fake_repo["branch"], "escape.txt")

        assert "outside" in str(exc.value).lower()

    def test_empty_name_refused(self, fake_repo: dict) -> None:
        """An empty name is a bug, not a directory listing."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads._fence(fake_repo["branch"], "   ")

    def test_missing_file_refused(self, fake_repo: dict) -> None:
        """A name that resolves nowhere is refused, not returned empty."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads._fence(fake_repo["branch"], "nope.txt")

    def test_legitimate_nested_file_accepted(self, fake_repo: dict) -> None:
        """Ordinary reads still work — the fence is not a wall."""
        resolved = host_reads._fence(fake_repo["branch"], "nested/deep.txt")

        assert resolved.name == "deep.txt"


class TestResolveBranchRoot:
    """Branch names resolve through the registry, never from caller input."""

    def test_known_branch_resolves(self, fake_repo: dict) -> None:
        """The registry is the catalog; this handler only reads it."""
        assert host_reads.resolve_branch_root("demo") == fake_repo["branch"].resolve()

    def test_email_form_resolves(self, fake_repo: dict) -> None:
        """'@demo' is how the rest of the system addresses a citizen."""
        assert host_reads.resolve_branch_root("@demo") == fake_repo["branch"].resolve()

    def test_unknown_branch_refused(self, fake_repo: dict) -> None:
        """An unregistered name reaches no filesystem at all."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_branch_root("ghost")

    def test_empty_branch_refused(self, fake_repo: dict) -> None:
        """No branch means no read."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_branch_root("")

    def test_broken_registry_raises_unavailable_not_refused(self, fake_repo: dict) -> None:
        """A corrupt catalog must NOT read as 'unknown branch' — that would send
        an operator hunting for a typo while the real fault is the registry."""
        fake_repo["drone"].get_branch_info.side_effect = _RegistryBroken("corrupt")

        with pytest.raises(host_reads.ReadUnavailable):
            host_reads.resolve_branch_root("demo")

    def test_registry_path_that_does_not_exist_raises_unavailable(self, fake_repo: dict) -> None:
        """A registry pointing at a vanished directory is our problem to report."""
        fake_repo["drone"].get_branch_info.side_effect = None
        fake_repo["drone"].get_branch_info.return_value = {"name": "DEMO", "path": "/nope/not/here"}

        with pytest.raises(host_reads.ReadUnavailable):
            host_reads.resolve_branch_root("demo")


class TestSeating:
    """The server serves exactly one project and says which."""

    def test_repo_root_is_the_registry_parent(self, fake_repo: dict) -> None:
        """Root comes from drone's own resolution, not a guess."""
        assert host_reads.repo_root() == fake_repo["root"]

    def test_seated_project_is_the_root_name(self, fake_repo: dict) -> None:
        """The name a client must match on the project parameter."""
        assert host_reads.seated_project() == "FakeRepo"


class TestReadFile:
    """File reads, caps and honesty about them."""

    def test_returns_content_and_size(self, fake_repo: dict) -> None:
        """The ordinary read."""
        result = host_reads.read_file("demo", "hello.txt")

        assert result["content"] == "hello world"
        assert result["bytes"] == len("hello world")
        assert result["truncated"] is False

    def test_over_cap_file_is_refused_not_truncated(self, fake_repo: dict) -> None:
        """A silent trim would read as 'this is the whole file'. Refuse instead."""
        big = fake_repo["branch"] / "big.bin"
        big.write_text("x" * (host_reads.MAX_READ_BYTES + 1), encoding="utf-8")

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "big.bin")

        assert "cap" in str(exc.value).lower()

    def test_non_utf8_file_refused(self, fake_repo: dict) -> None:
        """Binary is refused rather than returned as mojibake."""
        blob = fake_repo["branch"] / "blob.bin"
        blob.write_bytes(b"\xff\xfe\x00\x01")

        with pytest.raises(host_reads.ReadRefused):
            host_reads.read_file("demo", "blob.bin")

        assert True

    def test_matching_project_accepted(self, fake_repo: dict) -> None:
        """Naming the seated project explicitly is fine."""
        result = host_reads.read_file("demo", "hello.txt", project="FakeRepo")

        assert result["content"] == "hello world"


class TestReadDiff:
    """Diffs route through drone — git is drone-only, servers included."""

    def _completed(self, stdout: str = "diff text", returncode: int = 0) -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = ""
        result.returncode = returncode
        return result

    def test_routes_through_drone_not_raw_git(self, fake_repo: dict) -> None:
        """The house rule holds here: never a raw git subprocess."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_diff("demo")

        command = mock_run.call_args[0][0]
        assert command[:3] == ["drone", "@git", "diff"]

    def test_staged_flag_passed_through(self, fake_repo: dict) -> None:
        """--staged reaches drone rather than being reinterpreted here."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_diff("demo", staged=True)

        assert "--staged" in mock_run.call_args[0][0]

    def test_runs_in_the_branch_directory(self, fake_repo: dict) -> None:
        """drone's git lane is CWD-scoped, so the cwd IS the branch selection."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_diff("demo")

        assert mock_run.call_args.kwargs["cwd"] == str(fake_repo["branch"].resolve())

    def test_missing_drone_raises_unavailable(self, fake_repo: dict) -> None:
        """No drone on PATH is an honest 503, not an empty diff."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("no drone")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_diff("demo")

    def test_timeout_raises_unavailable(self, fake_repo: dict) -> None:
        """A hung diff must not hang the request forever."""
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_diff("demo")

    def test_non_zero_exit_raises_unavailable(self, fake_repo: dict) -> None:
        """A failed diff is reported, never returned as empty output."""
        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_diff("demo")

    def test_oversized_diff_truncates_and_says_so(self, fake_repo: dict) -> None:
        """Generated output may be capped — but the cap is REPORTED."""
        huge = "x" * (host_reads.MAX_DIFF_BYTES + 100)

        with patch.object(subprocess, "run", return_value=self._completed(stdout=huge)):
            result = host_reads.read_diff("demo")

        assert result["truncated"] is True
        assert len(result["diff"]) <= host_reads.MAX_DIFF_BYTES


# @drone's real `git status` rendering, which is `f"  {status:>2} {path}"` per
# file between a header line and a scope footer. Paths are REPO-relative there;
# @baud's desktop card uses --relative and speaks branch-local names.
GIT_STATUS_STDOUT = """4 file(s) changed under src/aipass/demo
   M src/aipass/demo/hello.txt
  ?? src/aipass/demo/brand_new.py
   D src/aipass/demo/nested/deep.txt
   R src/aipass/demo/old_name.py -> src/aipass/demo/new_name.py
(showing demo scope — use --all for full repo)"""


class TestGitChangesMatchesTheDesktopCard:
    """
    @baud's desktop already answers this question, so the phone must not get a
    second answer to it. Their contract, read from their tree on 2026-08-16:

        GitChanges { files: Vec<String>, count: usize }

    served by `git diff HEAD --relative --name-only -- .` — TRACKED files that
    differ from HEAD, named relative to the branch directory. Their own comment
    says why the card is deliberately not the whole-repo question: a card
    should only ever speak about its own subtree.
    """

    def _completed(self, stdout: str = GIT_STATUS_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_the_shape_is_files_and_count(self, fake_repo: dict) -> None:
        """Their two fields, spelled their way, with count agreeing with files."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert isinstance(result["files"], list)
        assert result["count"] == len(result["files"])

    def test_untracked_files_are_not_changes_on_a_card(self, fake_repo: dict) -> None:
        """
        The desktop asks `diff HEAD`, which cannot see a file git never has.

        Counting the new file here would make the phone's badge disagree with
        the desktop's on the same branch at the same moment — and the phone
        would be the one that was wrong, because @baud owns this question.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert "brand_new.py" not in result["files"]
        assert result["count"] == 3

    def test_the_untracked_ones_are_counted_separately_rather_than_dropped(self, fake_repo: dict) -> None:
        """
        Matching the desktop must not mean hiding what was measured.

        @baud's OWN reasoning for the whole-project total is that a brand-new
        module is the most interesting change in a tree and a count that hid it
        reads as false calm. That reasoning does not stop being true because
        this route answers the card's narrower question, so the number is
        reported beside the contract rather than thrown away.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert result["untracked"] == 1

    def test_paths_are_branch_local_not_repo_relative(self, fake_repo: dict) -> None:
        """
        Their --relative, reproduced.

        Every src/aipass branch shares one repo, so a repo-relative name on a
        card would prefix every row with the same nine characters and push the
        part that differs off a phone screen.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert "hello.txt" in result["files"]
        assert "nested/deep.txt" in result["files"]
        assert not any(path.startswith("src/") for path in result["files"])

    def test_a_rename_is_reported_at_the_name_it_has_now(self, fake_repo: dict) -> None:
        """
        Porcelain renders a rename as 'old -> new' on one line.

        Passing that through whole would put an arrow and two paths in a field
        the desktop fills with one filename, and a phone tapping it would ask
        for a file whose name contains ' -> '.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert "new_name.py" in result["files"]
        assert not any("->" in path for path in result["files"])

    def test_the_header_and_footer_are_not_files(self, fake_repo: dict) -> None:
        """drone frames the list with prose. Prose is not a changed file."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert not any("file(s) changed" in path for path in result["files"])
        assert not any("showing demo scope" in path for path in result["files"])

    def test_a_clean_branch_is_zero_and_not_an_error(self, fake_repo: dict) -> None:
        """Nothing changed is an answer, and the commonest one."""
        clean = "0 file(s) changed under src/aipass/demo\n(showing demo scope — use --all for full repo)"

        with patch.object(subprocess, "run", return_value=self._completed(stdout=clean)):
            result = host_reads.read_git_changes("demo")

        assert result == {
            "branch": "demo",
            "grain": "branch",
            "files": [],
            "count": 0,
            "untracked": 0,
            "rows": [],
        }


class TestGitStaysDroneOnlyOnThisLaneToo:
    """
    Git is drone-only in this system, servers included — the same house rule
    the diff lane above is built on, and not one this route gets to bend
    because a badge would be easier to fill with a raw subprocess.
    """

    def _completed(self, stdout: str = GIT_STATUS_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_routes_through_drone_not_raw_git(self, fake_repo: dict) -> None:
        """The command is drone's, never git's."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_git_changes("demo")

        assert mock_run.call_args[0][0] == ["drone", "@git", "status"]

    def test_runs_in_the_branch_directory(self, fake_repo: dict) -> None:
        """drone's git lane is CWD-scoped, so the cwd IS the branch selection."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_git_changes("demo")

        assert mock_run.call_args.kwargs["cwd"] == str(fake_repo["branch"].resolve())

    def test_missing_drone_raises_unavailable(self, fake_repo: dict) -> None:
        """No drone on PATH is an honest 503, not a badge reading zero."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("no drone")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_git_changes("demo")

    def test_timeout_raises_unavailable(self, fake_repo: dict) -> None:
        """A hung status must not hang the request forever."""
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_git_changes("demo")

    def test_a_failed_status_is_never_read_as_a_clean_tree(self, fake_repo: dict) -> None:
        """
        drone learned this one the hard way and says so in their own source: a
        failed `git status` that exits 0 false-greened scripts into reading an
        error as a clean tree for months. They now exit 1 and put the reason on
        stderr, so a zero count here must only ever mean zero.
        """
        with patch.object(
            subprocess,
            "run",
            return_value=self._completed(stdout="", returncode=1, stderr="git status error: bad object HEAD"),
        ):
            with pytest.raises(host_reads.ReadUnavailable) as excinfo:
                host_reads.read_git_changes("demo")

        assert "bad object HEAD" in str(excinfo.value)

    def test_a_caller_drone_will_not_verify_is_reported_in_drones_words(self, fake_repo: dict) -> None:
        """
        THE measured limit of this lane, and the reason it is not hidden.

        drone verifies its caller by finding a passport in the cwd hierarchy.
        Foreign projects — projects/baud, anything external — have no AIPass
        passport at those paths, so drone refuses the command outright with
        exit 1. This route resolves a foreign branch root perfectly well and
        then cannot ask git about it, which is a 503 carrying drone's own
        sentence: inventing an empty change list would paint a foreign branch
        as clean when nothing was ever measured.
        """
        refusal = (
            "No .trinity/passport.json found in directory hierarchy "
            "(caller cwd: /home/patrick/Projects/AIPass/projects/baud/src/baud) — cannot verify caller"
        )

        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1, stderr=refusal)):
            with pytest.raises(host_reads.ReadUnavailable) as excinfo:
                host_reads.read_git_changes("demo")

        assert "cannot verify caller" in str(excinfo.value)


class TestGitChangesFollowsTheReadDoctrine:
    """
    Same two doors as every other read: the seat resolves through the local
    citizen registry, a foreign project through @baud's census. Browsing is
    free — the seat is a default, never a fence.
    """

    def test_an_unknown_branch_never_reaches_a_subprocess(self, fake_repo: dict) -> None:
        """Refused before spawn, exactly like the file and diff lanes."""
        with patch.object(subprocess, "run") as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_git_changes("ghost")

        mock_run.assert_not_called()

    def test_a_missing_branch_name_is_refused(self, fake_repo: dict) -> None:
        """There is no current branch to infer from a phone."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.read_git_changes("")


# =============================================
# ROUTES
# =============================================


fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def client(tmp_path: Path):
    """TestClient with an isolated token store."""
    from fastapi.testclient import TestClient

    store = tmp_path / "secrets"
    store.mkdir()
    with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
            _, raw = host_tokens.issue_token("phone", "read")
            yield TestClient(host_server.create_app(), raise_server_exceptions=False), raw


@fastapi_required
class TestReadLaneRoutes:
    """The read lane behind the Phase 1 auth."""

    def test_feed_requires_auth(self, client: Any, feed_file: Path) -> None:
        """The read lane is not public."""
        api, _ = client

        assert api.get("/v1/feed").status_code == 401

    def test_feed_returns_the_envelope(self, client: Any, feed_file: Path) -> None:
        """The shape @baud codes against."""
        api, raw = client
        _write_feed(feed_file, [_event("2026-08-14T10:00:00")])

        response = api.get("/v1/feed", headers={"Authorization": f"Bearer {raw}"})
        body = response.json()

        assert response.status_code == 200
        assert set(body) == {"events", "cursor", "gap", "gap_reason", "more"}

    def test_feed_gap_surfaces_through_the_route(self, client: Any, feed_file: Path) -> None:
        """The clamp is not just handler-deep — the phone actually sees it."""
        api, raw = client
        _write_feed(feed_file, [_event("2026-08-14T11:00:00")])

        response = api.get(
            "/v1/feed",
            params={"since": "2026-08-01T00:00:00"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.json()["gap"] is True

    def test_files_requires_auth(self, client: Any, fake_repo: dict) -> None:
        """No token, no file."""
        api, _ = client

        assert api.get("/v1/files", params={"branch": "demo", "file": "hello.txt"}).status_code == 401

    def test_files_returns_content(self, client: Any, fake_repo: dict) -> None:
        """The ordinary read, end to end."""
        api, raw = client

        response = api.get(
            "/v1/files",
            params={"branch": "demo", "file": "hello.txt"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200
        assert response.json()["content"] == "hello world"

    def test_files_fence_violation_is_400_with_envelope(self, client: Any, fake_repo: dict) -> None:
        """A refused read comes back in the one error shape, not a stack trace."""
        api, raw = client

        response = api.get(
            "/v1/files",
            params={"branch": "demo", "file": "../../secret.txt"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"

    def test_diff_returns_text(self, client: Any, fake_repo: dict) -> None:
        """The diff lane, end to end, with drone stubbed."""
        api, raw = client
        completed = MagicMock()
        completed.stdout = "diff --git a/x b/x"
        completed.stderr = ""
        completed.returncode = 0

        with patch.object(subprocess, "run", return_value=completed):
            response = api.get(
                "/v1/diff",
                params={"branch": "demo"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 200
        assert response.json()["diff"] == "diff --git a/x b/x"

    def test_diff_unknown_branch_is_400(self, client: Any, fake_repo: dict) -> None:
        """An unregistered branch never reaches a subprocess."""
        api, raw = client

        response = api.get(
            "/v1/diff",
            params={"branch": "ghost"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400

    def test_git_changes_needs_a_token(self, client: Any, fake_repo: dict) -> None:
        """A read scope is still a scope. Nothing on /v1 is open."""
        api, _ = client

        assert api.get("/v1/git-changes", params={"branch": "demo"}).status_code == 401

    def test_git_changes_serves_the_card_contract(self, client: Any, fake_repo: dict) -> None:
        """End to end, in the shape @baud's tile already knows how to render."""
        api, raw = client
        completed = MagicMock()
        completed.stdout = GIT_STATUS_STDOUT
        completed.stderr = ""
        completed.returncode = 0

        with patch.object(subprocess, "run", return_value=completed):
            response = api.get(
                "/v1/git-changes",
                params={"branch": "demo"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "branch": "demo",
            "grain": "branch",
            "files": ["hello.txt", "nested/deep.txt", "new_name.py"],
            "count": 3,
            "untracked": 1,
            "rows": [
                {"path": "hello.txt", "status": " M"},
                {"path": "brand_new.py", "status": "??"},
                {"path": "nested/deep.txt", "status": " D"},
                {"path": "new_name.py", "status": " R"},
            ],
        }

    def test_git_changes_unknown_branch_is_400(self, client: Any, fake_repo: dict) -> None:
        """Refused before spawn, and named — the read lane's standing rule."""
        api, raw = client

        with patch.object(subprocess, "run") as mock_run:
            response = api.get(
                "/v1/git-changes",
                params={"branch": "ghost"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        mock_run.assert_not_called()
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"

    def test_git_changes_reports_a_refused_git_door_as_503(self, client: Any, fake_repo: dict) -> None:
        """
        A branch this server can locate but cannot ask git about.

        503 and drone's sentence, never 200 with an empty list: a clean badge
        on a branch nothing was measured on is the one answer that would be
        read as fact.
        """
        api, raw = client
        completed = MagicMock()
        completed.stdout = ""
        completed.stderr = "No .trinity/passport.json found in directory hierarchy — cannot verify caller"
        completed.returncode = 1

        with patch.object(subprocess, "run", return_value=completed):
            response = api.get(
                "/v1/git-changes",
                params={"branch": "demo"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "read_unavailable"
        assert "cannot verify caller" in response.json()["error"]["message"]

    def _completed(self, stdout: str) -> Any:
        completed = MagicMock()
        completed.stdout = stdout
        completed.stderr = ""
        completed.returncode = 0
        return completed

    def test_git_changes_serves_repo_grain_over_the_wire(self, client: Any, fake_repo: dict) -> None:
        """The app's question, end to end, naming its own scope in the answer."""
        api, raw = client

        with patch.object(subprocess, "run", return_value=self._completed(GIT_STATUS_ALL_STDOUT)):
            response = api.get(
                "/v1/git-changes",
                params={"branch": "demo", "grain": "repo"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        body = response.json()
        assert response.status_code == 200
        assert body["grain"] == "repo"
        assert "src/aipass/other/thing.py" in body["files"]

    def test_git_changes_refuses_an_unknown_grain_with_400(self, client: Any, fake_repo: dict) -> None:
        """A typo'd scope is a caller error, in the documented envelope."""
        api, raw = client

        with patch.object(subprocess, "run") as mock_run:
            response = api.get(
                "/v1/git-changes",
                params={"branch": "demo", "grain": "everything"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        mock_run.assert_not_called()
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"

    def test_diff_serves_one_file_over_the_wire(self, client: Any, fake_repo: dict) -> None:
        """Tap-a-file: the whole point of the round, through the real route."""
        api, raw = client

        with patch.object(subprocess, "run", return_value=self._completed(TWO_FILE_DIFF)):
            response = api.get(
                "/v1/diff",
                params={"branch": "demo", "path": "src/aipass/demo/hello.txt"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        body = response.json()
        assert response.status_code == 200
        assert body["path"] == "src/aipass/demo/hello.txt"
        assert "thing.py" not in body["diff"]

    def test_diff_refuses_a_file_it_has_no_changes_for(self, client: Any, fake_repo: dict) -> None:
        """A stale tap gets a sentence, not an empty patch that renders as calm."""
        api, raw = client

        with patch.object(subprocess, "run", return_value=self._completed(TWO_FILE_DIFF)):
            response = api.get(
                "/v1/diff",
                params={"branch": "demo", "path": "src/aipass/demo/absent.py"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        assert response.status_code == 400
        assert "absent.py" in response.json()["error"]["message"]

    def test_git_log_requires_auth(self, client: Any, fake_repo: dict) -> None:
        """History is not public either."""
        api, _ = client

        assert api.get("/v1/git-log", params={"branch": "demo"}).status_code == 401

    def test_git_log_serves_the_commit_list(self, client: Any, fake_repo: dict) -> None:
        """Sha and subject, in the order the door gave them."""
        api, raw = client

        with patch.object(subprocess, "run", return_value=self._completed(GIT_LOG_STDOUT)):
            response = api.get(
                "/v1/git-log",
                params={"branch": "demo", "limit": 3},
                headers={"Authorization": f"Bearer {raw}"},
            )

        body = response.json()
        assert response.status_code == 200
        assert body["grain"] == "repo"
        assert body["commits"][0]["sha"] == "b47462b7"

    def test_git_log_refuses_an_over_cap_limit_with_400(self, client: Any, fake_repo: dict) -> None:
        """The cap is stated, not silently applied."""
        api, raw = client

        with patch.object(subprocess, "run") as mock_run:
            response = api.get(
                "/v1/git-log",
                params={"branch": "demo", "limit": 500},
                headers={"Authorization": f"Bearer {raw}"},
            )

        mock_run.assert_not_called()
        assert response.status_code == 400
        assert str(host_reads.MAX_LOG_COMMITS) in response.json()["error"]["message"]

    def test_commit_requires_auth(self, client: Any, fake_repo: dict) -> None:
        """Read scope, like every other lane here."""
        api, _ = client

        assert api.get("/v1/commit", params={"branch": "demo", "ref": "HEAD"}).status_code == 401

    def test_commit_serves_facts_and_stats(self, client: Any, fake_repo: dict) -> None:
        """The detail card's contract, end to end."""
        api, raw = client

        with patch.object(subprocess, "run", return_value=self._completed(GIT_SHOW_STDOUT)):
            response = api.get(
                "/v1/commit",
                params={"branch": "demo", "ref": "7edf8c2d"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        body = response.json()
        assert response.status_code == 200
        assert body["author"] == "AIOSAI <aipass.system@gmail.com>"
        assert body["count"] == 2
        assert "diff" not in body

    def test_commit_refuses_a_garbage_ref_with_400(self, client: Any, fake_repo: dict) -> None:
        """Refused before spawn, in the documented envelope."""
        api, raw = client

        with patch.object(subprocess, "run") as mock_run:
            response = api.get(
                "/v1/commit",
                params={"branch": "demo", "ref": "--upload-pack=evil"},
                headers={"Authorization": f"Bearer {raw}"},
            )

        mock_run.assert_not_called()
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"

    def test_commit_without_a_ref_is_a_normalized_422(self, client: Any, fake_repo: dict) -> None:
        """
        ref has no default, so FastAPI refuses first. The envelope stays ours —
        the same normalization the upload lane needed, tested here so a naked
        framework shape can never reach the phone from this route.
        """
        api, raw = client

        response = api.get(
            "/v1/commit",
            params={"branch": "demo"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 422
        assert "error" in response.json()

    def test_remote_requires_auth(self, client: Any, remote_repo: dict) -> None:
        """The link-card lane is not public either."""
        api, _ = client

        assert api.get("/v1/git-remote", params={"branch": "demo"}).status_code == 401

    def test_remote_serves_the_link_card_contract(self, client: Any, remote_repo: dict) -> None:
        """End to end, in the shape the face builds its links from."""
        api, raw = client

        response = api.get(
            "/v1/git-remote",
            params={"branch": "demo"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        body = response.json()
        assert response.status_code == 200
        assert body["web"] == "https://github.com/AIOSAI/AIPass"
        assert body["remote"] == "origin"
        assert body["redacted"] is False

    def test_remote_absent_is_400_in_the_envelope(self, client: Any, remote_repo: dict) -> None:
        """
        Two real projects have no remote. The face gets a sentence it can show,
        never an empty string it would render as a dead link.
        """
        api, raw = client
        remote_repo["configure"]("[core]\n\tbare = false\n")

        response = api.get(
            "/v1/git-remote",
            params={"branch": "demo"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"
        assert "remote" in response.json()["error"]["message"]


class TestReadsFollowTheFleetLane:
    """
    Browsing is free. The seat is a default, never a fence, on the read lane.

    Patrick ruled it on 2026-08-16, his words: "I should be able to open another
    project via the project tab drop down, and view other agent project files,
    open any passport and view watch read files. no restriction."

    The contradiction he hit, measured on the live host by @baud: /v1/fleet
    served project=BAUD and painted the cards, then EVERY file read under those
    cards refused with "This server is seated in AIPass and does not serve
    project BAUD" — README, inbox, dashboard, memory, passport. One surface
    answering two different questions about the same project.

    OPERATE ROUTES ARE UNTOUCHED BY THIS. The terminal still binds to the seat;
    attach is the only takeover. Reads are reads.
    """

    @pytest.fixture
    def foreign(self, fake_repo: dict, tmp_path: Path):
        """A branch living in another project, as @baud's census reports it."""
        root = tmp_path / "OtherProject" / "src" / "baud"
        root.mkdir(parents=True)
        (root / "README.md").write_text("the other project", encoding="utf-8")

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "baud", "path": str(root)}

        # Patched on the PACKAGE, not in sys.modules: reads.py imports the
        # census with `from ...host import fleet`, which reads the attribute off
        # the already-imported parent package and would sail straight past a
        # sys.modules entry.
        with patch(PATCH_HOST_FLEET, census):
            yield {"root": root, "census": census}

    def test_a_foreign_project_is_served_not_refused(self, fake_repo: dict, foreign: dict) -> None:
        """The exact read that refused on the live host tonight."""
        result = host_reads.read_file("baud", "README.md", project="BAUD")

        assert result["content"] == "the other project"

    def test_the_path_comes_from_bauds_census_never_composed_here(self, fake_repo: dict, foreign: dict) -> None:
        """
        This server never builds a filesystem path for a project it is not
        seated in — the row carries the real one, from @baud's own discovery.
        """
        host_reads.read_file("baud", "README.md", project="BAUD")

        foreign["census"].resolve_branch.assert_called_once_with("BAUD", "baud")

    def test_the_project_name_travels_verbatim(self, fake_repo: dict, foreign: dict) -> None:
        """
        @baud's census owns the ruling on how a project name is matched, so the
        caller's spelling reaches them unchanged rather than being normalised
        into a shape this server preferred.
        """
        host_reads.read_file("baud", "README.md", project="  BAUD  ")

        assert foreign["census"].resolve_branch.call_args[0][0] == "  BAUD  "

    def test_an_unknown_branch_in_a_known_project_is_the_callers_mistake(self, fake_repo: dict, foreign: dict) -> None:
        """400, phrased with both names — and never a filesystem path."""
        foreign["census"].resolve_branch.return_value = None

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("nosuch", "README.md", project="BAUD")

        assert "BAUD" in str(exc.value) and "nosuch" in str(exc.value)

    def test_an_unknown_project_carries_bauds_own_sentence(self, fake_repo: dict, foreign: dict) -> None:
        """
        Kept distinct from the branch case and NOT paraphrased: the census
        already says "no project named X", which is the most actionable words
        this refusal has.
        """
        foreign["census"].resolve_branch.side_effect = host_fleet.FleetUnavailable(
            "no project named 'nope' in BAUD's census"
        )

        with pytest.raises(host_reads.ReadUnavailable) as exc:
            host_reads.read_file("baud", "README.md", project="nope")

        assert "no project named 'nope'" in str(exc.value)

    @pytest.mark.parametrize("named", ["", "FakeRepo", "fakerepo", "FAKEREPO"])
    def test_the_seat_never_pays_for_a_census(self, fake_repo: dict, foreign: dict, named: str) -> None:
        """
        The local registry stays the fast path, in any case the caller types.

        Routing the seat through a subprocess would put @baud's snapshot gate in
        front of every file the phone opens — one gated binary and the whole
        read lane goes dark for the project it is standing in.
        """
        result = host_reads.read_file("demo", "hello.txt", project=named)

        assert result["content"] == "hello world"
        foreign["census"].resolve_branch.assert_not_called()

    def test_the_directory_browser_crosses_projects_too(self, fake_repo: dict, foreign: dict) -> None:
        """/v1/dir refused the same way and had to be swept with the rest."""
        result = host_reads.list_dir("baud", project="BAUD")

        assert any(entry["name"] == "README.md" for entry in result["entries"])

    def test_the_diff_lane_crosses_projects_too(self, fake_repo: dict, foreign: dict) -> None:
        """
        Same sweep. drone runs in the foreign branch's own directory, so its
        git lane resolves in that project's context rather than the seat's.
        """
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "diff --git a/x b/x"
        completed.stderr = ""

        with patch.object(host_reads.subprocess, "run", return_value=completed) as run:
            result = host_reads.read_diff("baud", project="BAUD")

        assert result["diff"] == "diff --git a/x b/x"
        assert run.call_args.kwargs["cwd"] == str(foreign["root"])

    def test_the_fence_still_holds_inside_a_foreign_branch(self, fake_repo: dict, foreign: dict) -> None:
        """
        Free browsing is free browsing of BRANCHES, not of the disk. Names
        still resolve under the branch root and a traversal still dies here.
        """
        with pytest.raises(host_reads.ReadRefused):
            host_reads.read_file("baud", "../../../etc/passwd", project="BAUD")

    def test_no_read_still_says_it_does_not_serve_the_project(self, fake_repo: dict) -> None:
        """
        The sentence itself is gone from this lane.

        A grep-shaped guard on purpose: this refusal lived in one helper that
        three reads shared, so a future editor restoring it anywhere would put
        the contradiction back on every one of them at once.
        """
        source = Path(host_reads.__file__).read_text(encoding="utf-8")

        assert "does not serve project" not in source


class TestGitChangesInAForeignProject:
    """
    A FOREIGN PROJECT'S ROWS MUST BE BRANCH-LOCAL TOO, and for a while they
    were not.

    This class exists because of a wrong belief, and it is worth recording
    which one. On 2026-08-16 I reported that no drone-routed read lane could
    serve a foreign project at all: drone verifies its caller by finding a
    passport in the cwd hierarchy, and I had measured a real refusal in
    projects/baud/src/baud. @baud's live sweep then served five foreign
    projects with real data, and the reconciliation was that my probe path was
    never a census-known BRANCH — the registered one sits a level deeper and,
    like every census branch, carries its own passport. The command measurement
    was true; the inference from it to the route was not.

    The cost of the wrong belief was this bug: `repo_root()` is the SEAT's
    root, so a foreign branch fell out of `relative_to` and its paths were left
    exactly as drone printed them — relative to the FOREIGN repo root, i.e.
    'src/vera_studio/vera/CLAUDE.md' where @baud's --relative contract says
    'CLAUDE.md'. Believing the lane could not serve those projects is precisely
    why nothing looked wrong.
    """

    @pytest.fixture
    def foreign_repo(self, fake_repo: dict, tmp_path: Path):
        """A whole other repository, with its own .git and its own branch."""
        project = tmp_path / "OtherRepo"
        (project / ".git").mkdir(parents=True)
        root = project / "src" / "vera_studio" / "vera"
        root.mkdir(parents=True)

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "vera", "path": str(root)}

        with patch(PATCH_HOST_FLEET, census):
            yield {"root": root, "project": project}

    def _completed(self, stdout: str) -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = ""
        result.returncode = 0
        return result

    def test_a_foreign_branchs_rows_are_branch_local(self, fake_repo: dict, foreign_repo: dict) -> None:
        """
        drone prints paths relative to the repo it found, which for a foreign
        branch is not this server's. The prefix to strip is that branch's own
        repository root, discovered rather than assumed.
        """
        stdout = (
            "2 file(s) changed under src/vera_studio/vera\n"
            "   M src/vera_studio/vera/CLAUDE.md\n"
            "   M src/vera_studio/vera/.aipass/local_system_prompt.md\n"
            "(showing vera scope — use --all for full repo)"
        )

        with patch.object(host_reads.subprocess, "run", return_value=self._completed(stdout)):
            result = host_reads.read_git_changes("vera", project="VERA-STUDIO")

        assert result["files"] == ["CLAUDE.md", ".aipass/local_system_prompt.md"]
        assert not any(path.startswith("src/") for path in result["files"])

    def test_the_seated_branch_is_unaffected(self, fake_repo: dict) -> None:
        """The seat resolved correctly before and must keep doing so."""
        stdout = "1 file(s) changed under src/aipass/demo\n   M src/aipass/demo/hello.txt"

        with patch.object(host_reads.subprocess, "run", return_value=self._completed(stdout)):
            result = host_reads.read_git_changes("demo")

        assert result["files"] == ["hello.txt"]

    def test_a_nested_repository_inside_the_seat_is_stripped_against_the_inner_one(
        self, fake_repo: dict, tmp_path: Path
    ) -> None:
        """
        THE case the seat-first version got wrong, and the one that hid longest.

        projects/baud carries its own .git INSIDE the AIPass tree. So the branch
        is inside this server's repo — `relative_to(seat)` succeeds and yields
        'projects/baud/src/baud/baud/' — while the rows drone printed are
        relative to the INNER repository and start 'src/baud/baud/'. The prefix
        that resolves cleanly is the wrong one, which is worse than one that
        fails: nothing raises, and every row silently keeps its prefix.

        Discovery has to win for that reason, not merely by preference — which
        is why this test exists at all. Two mutations survived the suite before
        it did: swapping the order back, and requiring the marker to be a
        directory.
        """
        tenant = fake_repo["root"] / "projects" / "tenant"
        (tenant / ".git").mkdir(parents=True)
        root = tenant / "src" / "tenant" / "tenant"
        root.mkdir(parents=True)

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "tenant", "path": str(root)}

        stdout = "1 file(s) changed under src/tenant/tenant\n   M src/tenant/tenant/lib.rs"

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_reads.subprocess, "run", return_value=self._completed(stdout)):
                result = host_reads.read_git_changes("tenant", project="TENANT")

        assert result["files"] == ["lib.rs"]

    def test_a_worktree_marker_is_a_file_and_still_marks_a_repository(self, fake_repo: dict, tmp_path: Path) -> None:
        """
        A worktree and a submodule carry '.git' as a FILE, not a directory.

        Reading those as "not a repository" would fall through to the seat and
        silently un-strip every row inside them — the same failure as the
        nested case, reached by a different route.
        """
        project = tmp_path / "WorktreeRepo"
        root = project / "src" / "thing" / "br"
        root.mkdir(parents=True)
        (project / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt", encoding="utf-8")

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "br", "path": str(root)}

        stdout = "1 file(s) changed under src/thing/br\n   M src/thing/br/main.py"

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_reads.subprocess, "run", return_value=self._completed(stdout)):
                result = host_reads.read_git_changes("br", project="WT")

        assert result["files"] == ["main.py"]

    def test_a_branch_in_no_repository_at_all_keeps_drones_names(self, fake_repo: dict, tmp_path: Path) -> None:
        """
        No .git anywhere above it — so there is no prefix that could be
        stripped honestly. drone's names travel untouched rather than being
        trimmed on a guess, and the case is logged rather than swallowed.
        """
        loose = tmp_path / "Loose" / "src" / "thing" / "br"
        loose.mkdir(parents=True)

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "br", "path": str(loose)}

        stdout = "1 file(s) changed under whatever\n   M whatever/file.py"

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_reads.subprocess, "run", return_value=self._completed(stdout)):
                result = host_reads.read_git_changes("br", project="LOOSE")

        assert result["files"] == ["whatever/file.py"]


# =============================================
# THE GIT APP — repo grain, per-file, and history
# =============================================

# drone's `status --all` render. Same per-file shape, but the scope is the whole
# repo and the paths already arrive repo-relative — so the branch-local prefix
# stripping that the CARD needs would be actively wrong here.
GIT_STATUS_ALL_STDOUT = """6 file(s) changed under the repository
   M src/aipass/demo/hello.txt
   M src/aipass/other/thing.py
  ?? src/aipass/demo/brand_new.py
   D src/aipass/third/gone.txt
(showing full repo)"""

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

# `drone @git show <ref>` — git's default --pretty=medium header, then the
# patch. Measured against the real door on 2026-08-17.
GIT_SHOW_STDOUT = (
    """commit 7edf8c2dfcccbc1ce1b04d8420405f98e212a474
Author: AIOSAI <aipass.system@gmail.com>
Date:   Sat Aug 15 10:15:22 2026 -0700

    feat(demo): the subject line

    And a second paragraph of body.

"""
    + TWO_FILE_DIFF
)

GIT_LOG_STDOUT = """b47462b7 feat(fleet): the newest one
7edf8c2d feat(demo): the subject line
cb4afb12 feat(host): an older one"""


class TestRepoGrainChanges:
    """
    The git APP is per-repo; the agent card's git tile is per-branch. Two
    grains, both honest — and the answer has to NAME which one it is, because a
    file list that does not say its own scope is a list a client can silently
    read at the wrong grain.

    Measured door: `status --all` targets lock_handler's find_repo_root(), so
    the repo grain already exists on the other side.
    """

    def _completed(self, stdout: str = GIT_STATUS_ALL_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_repo_grain_asks_drone_for_the_whole_repo(self, fake_repo: dict) -> None:
        """--all is what makes drone target the repo root instead of the branch."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_git_changes("demo", grain="repo")

        assert "--all" in mock_run.call_args[0][0]

    def test_branch_grain_never_asks_for_the_whole_repo(self, fake_repo: dict) -> None:
        """The card's question is unchanged — no --all leaks into the old grain."""
        with patch.object(subprocess, "run", return_value=self._completed(GIT_STATUS_STDOUT)) as mock_run:
            host_reads.read_git_changes("demo")

        assert "--all" not in mock_run.call_args[0][0]

    def test_the_answer_names_its_own_grain(self, fake_repo: dict) -> None:
        """Both grains say which they are, so a client cannot mistake them."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            wide = host_reads.read_git_changes("demo", grain="repo")
        with patch.object(subprocess, "run", return_value=self._completed(GIT_STATUS_STDOUT)):
            narrow = host_reads.read_git_changes("demo")

        assert wide["grain"] == "repo"
        assert narrow["grain"] == "branch"

    def test_repo_grain_keeps_repo_relative_names(self, fake_repo: dict) -> None:
        """
        THE BUG THIS PINS: the card strips a branch prefix to keep rows short.
        At repo grain the names already ARE repo-relative, so stripping would
        eat the part that distinguishes one branch's file from another's.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo", grain="repo")

        assert "src/aipass/demo/hello.txt" in result["files"]
        assert "src/aipass/other/thing.py" in result["files"]

    def test_repo_grain_reaches_beyond_the_anchor_branch(self, fake_repo: dict) -> None:
        """The whole point: files from branches other than the anchor arrive."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo", grain="repo")

        assert result["count"] == 3
        assert any("third" in name for name in result["files"])

    def test_untracked_still_rides_as_a_count_at_repo_grain(self, fake_repo: dict) -> None:
        """One doctrine, both grains — tracked core, untracked additive."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo", grain="repo")

        assert result["untracked"] == 1
        assert not any("brand_new" in name for name in result["files"])

    def test_an_unknown_grain_is_refused_naming_both(self, fake_repo: dict) -> None:
        """
        A typo'd grain must never quietly fall back to a scope the caller did
        not ask for — that is how a phone shows one branch's changes while
        believing it shows a repo's.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_reads.read_git_changes("demo", grain="everything")

        assert "branch" in str(caught.value) and "repo" in str(caught.value)

    def test_grain_is_refused_before_drone_is_ever_run(self, fake_repo: dict) -> None:
        """Garbage is refused before spawn — the standing rule on every lane."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_git_changes("demo", grain="REPOSITORY")

        assert mock_run.call_count == 0


# Every code the face needs a chip for, in drone's own render. The two columns
# are index-then-worktree, so 'A ' (staged new) and ' M' (modified, unstaged)
# are DIFFERENT answers that both collapse to one letter if either is stripped.
GIT_STATUS_CODES_STDOUT = """6 file(s) changed under src/aipass/demo
   M src/aipass/demo/modified.txt
  A  src/aipass/demo/staged_new.py
  MM src/aipass/demo/both.py
   D src/aipass/demo/gone.txt
  R  src/aipass/demo/old.py -> src/aipass/demo/new.py
  ?? src/aipass/demo/untracked.py
  !! src/aipass/demo/ignored.log
(showing demo scope)"""


class TestStatusPerRow:
    """
    @devpulse's rider, 13:48: the face can only build two of its four VS Code
    chips because this lane read the porcelain code and then THREW IT AWAY, and
    untracked names never left the server at all. A staged-new file was
    indistinguishable from a modified one.

    The fix carries git's OWN code per row, verbatim and unstripped. This server
    owns the pipe and never the meaning: deciding that some code "means" the
    letter A is the face's call, made once in their buildRows, and a letter
    invented here would be a second vocabulary for the same fact.
    """

    def _completed(self, stdout: str = GIT_STATUS_CODES_STDOUT, returncode: int = 0) -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = ""
        result.returncode = returncode
        return result

    def _rows(self, result: dict) -> dict:
        return {row["path"]: row["status"] for row in result["rows"]}

    def test_every_changed_row_carries_its_status(self, fake_repo: dict) -> None:
        """The field that did not exist before this rider."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert self._rows(result)["modified.txt"] == " M"

    def test_a_staged_new_file_is_distinguishable_from_a_modified_one(self, fake_repo: dict) -> None:
        """
        THE EXACT GAP THEY MEASURED. Both columns travel, so index-A and
        worktree-M stay two different answers instead of collapsing to one
        letter — which is what made a new file look like an edited one.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            rows = self._rows(host_reads.read_git_changes("demo"))

        assert rows["staged_new.py"] == "A "
        assert rows["modified.txt"] == " M"
        assert rows["staged_new.py"] != rows["modified.txt"]

    def test_both_columns_survive_when_both_are_set(self, fake_repo: dict) -> None:
        """Staged AND unstaged changes to one file is one row with two codes."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            rows = self._rows(host_reads.read_git_changes("demo"))

        assert rows["both.py"] == "MM"

    def test_untracked_files_arrive_by_NAME_not_only_as_a_count(self, fake_repo: dict) -> None:
        """
        The other half of the rider: the face could not paint a U chip on a file
        whose name it had never been told.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert self._rows(result)["untracked.py"] == "??"

    def test_the_tracked_list_is_unchanged_by_all_of_this(self, fake_repo: dict) -> None:
        """
        THE ADDITIVE PROMISE, pinned. @baud's desktop consumer parses `files`
        and `count`; untracked must stay OUT of them however many rows exist,
        or the phone starts disagreeing with the desktop again.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert "untracked.py" not in result["files"]
        assert result["count"] == len(result["files"]) == 5
        assert result["untracked"] == 1

    def test_ignored_files_are_in_no_list_at_all(self, fake_repo: dict) -> None:
        """Ignored is not a change. It was never in files; it is not a row either."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert "ignored.log" not in self._rows(result)
        assert "ignored.log" not in result["files"]

    def test_a_rename_row_names_the_file_it_is_now(self, fake_repo: dict) -> None:
        """
        Same rule as the card's list: the arrow never reaches a filename, or a
        phone tapping the row asks for a file that cannot exist.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            rows = self._rows(host_reads.read_git_changes("demo"))

        assert rows["new.py"] == "R "
        assert not any(" -> " in path for path in rows)

    def test_rows_and_files_agree_on_the_tracked_paths(self, fake_repo: dict) -> None:
        """
        Two views of one measurement, never two measurements. Every tracked file
        is a row, and every row that is not untracked is a tracked file.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        tracked_rows = [r["path"] for r in result["rows"] if r["status"].strip() != "??"]
        assert sorted(tracked_rows) == sorted(result["files"])

    def test_rows_ride_the_repo_grain_too(self, fake_repo: dict) -> None:
        """
        The rider asks for both lanes. Repo grain keeps repo-relative names here
        as well — one parser, so there is no second place for them to drift.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo", grain="repo")

        rows = self._rows(result)
        assert rows["src/aipass/demo/staged_new.py"] == "A "
        assert rows["src/aipass/demo/untracked.py"] == "??"

    def test_the_status_is_never_reinterpreted_into_a_letter(self, fake_repo: dict) -> None:
        """
        D0: this server owns the pipe and never the meaning. git's codes travel
        as git wrote them — a one-letter vocabulary invented here would be a
        second answer to a question git has already answered.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_changes("demo")

        assert all(len(row["status"]) == 2 for row in result["rows"])


class TestPerFileDiff:
    """
    Patrick's words: "git diffs are pretty much useless. we need a real diff
    setup." The fix is tap-a-file, so the lane needs a path.

    MEASURED BLOCKER: drone's _handle_diff recognises exactly --staged and
    --all. There is no path parameter and no -U passthrough, so a single file's
    patch can only be reached by generating the diff and splitting it here — on
    the per-file headers, which is machine structure, the same doctrine that
    keeps the status parser off drone's prose.
    """

    def _completed(self, stdout: str = TWO_FILE_DIFF, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_a_path_returns_only_that_files_patch(self, fake_repo: dict) -> None:
        """The tap-a-file contract: one file in, one file's changes out."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo", path="src/aipass/demo/hello.txt")

        assert "hello world" in result["diff"]
        assert "thing.py" not in result["diff"]

    def test_the_patch_keeps_its_own_file_header(self, fake_repo: dict) -> None:
        """
        react-diff-view's parseDiff() reads the header to know the filename and
        the change kind. Handing it a bare hunk would strip the file's identity.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo", path="src/aipass/other/thing.py")

        assert result["diff"].startswith("diff --git a/src/aipass/other/thing.py")
        assert "@@" in result["diff"]

    def test_the_answer_names_the_path_it_answered_for(self, fake_repo: dict) -> None:
        """The response says which file it is, never leaving it to be inferred."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo", path="src/aipass/demo/hello.txt")

        assert result["path"] == "src/aipass/demo/hello.txt"

    def test_no_path_returns_the_whole_diff_unchanged(self, fake_repo: dict) -> None:
        """The live lane keeps its contract — the phone reads it right now."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo")

        assert result["diff"] == TWO_FILE_DIFF
        assert result["path"] == ""

    def test_a_file_with_no_changes_is_refused_in_words(self, fake_repo: dict) -> None:
        """
        An empty string would read as "no changes rendered fine". A tap on a
        stale list is a real event and it gets a real sentence.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_reads.read_diff("demo", path="src/aipass/demo/never_touched.py")

        assert "never_touched.py" in str(caught.value)

    def test_a_near_miss_name_does_not_match(self, fake_repo: dict) -> None:
        """
        Matching on the header's exact path, not a substring — otherwise
        "hello.txt" would answer for "other_hello.txt" and the phone would show
        a diff belonging to a different file.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_diff("demo", path="demo/hello.txt")

    def test_an_oversized_single_file_is_refused_not_trimmed(self, fake_repo: dict) -> None:
        """
        Half a patch is not a small patch — it is a broken one, and a renderer
        handed a severed hunk paints nonsense. The whole-diff cap reports a
        trim because a wall of text degrades gracefully; one file does not.
        """
        huge = (
            "diff --git a/src/aipass/demo/big.txt b/src/aipass/demo/big.txt\n"
            "--- a/src/aipass/demo/big.txt\n+++ b/src/aipass/demo/big.txt\n@@ -1 +1 @@\n"
            + "+x\n"
            * host_reads.MAX_DIFF_BYTES
        )

        with patch.object(subprocess, "run", return_value=self._completed(huge)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_reads.read_diff("demo", path="src/aipass/demo/big.txt")

        assert str(host_reads.MAX_DIFF_BYTES) in str(caught.value)

    def test_removed_content_that_looks_like_a_header_is_not_read_as_one(self, fake_repo: dict) -> None:
        """
        THE TRAP THIS PINS: deleting a line that reads '-- x' produces a patch
        line reading '--- x', which is character-for-character the shape of a
        file header. Scanning past the hunk marker for names would read that
        deletion as the file's own name, and the tapped file would come back
        under a name nobody has.
        """
        patch_text = (
            "diff --git a/doc.md b/doc.md\n"
            "--- a/doc.md\n"
            "+++ b/doc.md\n"
            "@@ -1,2 +1,2 @@\n"
            "--- a/decoy/path.txt\n"
            "+++ b/decoy/path.txt\n"
        )

        with patch.object(subprocess, "run", return_value=self._completed(patch_text)):
            result = host_reads.read_diff("demo", path="doc.md")

        assert result["path"] == "doc.md"
        assert "decoy" in result["diff"]

    def test_a_binary_file_is_named_from_its_own_header(self, fake_repo: dict) -> None:
        """
        A binary change has no per-line names at all — no minus line, no plus
        line, just the header and a sentence. The header names the path twice,
        and the halves agreeing is what makes reading it safe.
        """
        patch_text = (
            "diff --git a/img/logo.png b/img/logo.png\n"
            "index 1111111..2222222 100644\n"
            "Binary files a/img/logo.png and b/img/logo.png differ\n"
        )

        with patch.object(subprocess, "run", return_value=self._completed(patch_text)):
            result = host_reads.read_diff("demo", path="img/logo.png")

        assert "Binary files" in result["diff"]

    def test_a_filename_carrying_the_header_marker_still_resolves(self, fake_repo: dict) -> None:
        """
        A path containing the very characters the header uses as a separator.
        The two halves must agree, which is what stops the split landing inside
        the name — measured with a binary change so only the header can answer.
        """
        patch_text = (
            "diff --git a/odd b/name.bin b/odd b/name.bin\nindex 1111111..2222222 100644\nBinary files differ\n"
        )

        with patch.object(subprocess, "run", return_value=self._completed(patch_text)):
            result = host_reads.read_diff("demo", path="odd b/name.bin")

        assert "Binary files differ" in result["diff"]

    def test_repo_grain_diff_asks_for_the_whole_repo(self, fake_repo: dict) -> None:
        """The app's file list is repo grain, so its taps must be too."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_diff("demo", path="src/aipass/other/thing.py", grain="repo")

        assert "--all" in mock_run.call_args[0][0]

    def test_an_unknown_grain_is_refused_here_too(self, fake_repo: dict) -> None:
        """One vocabulary across the lanes, one refusal for breaking it."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_diff("demo", grain="sideways")

        assert mock_run.call_count == 0


class TestCommitPatch:
    """A commit's patch, per file — the same splitter, pointed at history."""

    def _completed(self, stdout: str = GIT_SHOW_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_a_ref_routes_through_drones_show_door(self, fake_repo: dict) -> None:
        """show is the measured door that carries a commit's patch."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_diff("demo", ref="7edf8c2d")

        command = mock_run.call_args[0][0]
        assert command[:2] == ["drone", "@git"]
        assert "7edf8c2d" in command

    def test_the_commit_header_is_not_part_of_the_patch(self, fake_repo: dict) -> None:
        """
        parseDiff() is handed a patch, not a letter. The author and date lines
        belong to the detail lane; leaving them in would make the renderer's
        first file a phantom named "commit".
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo", ref="7edf8c2d")

        assert result["diff"].startswith("diff --git ")
        assert "AIOSAI" not in result["diff"]

    def test_a_ref_and_a_path_together_give_one_file_of_one_commit(self, fake_repo: dict) -> None:
        """The deepest tap in the app: this file, in this commit."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo", ref="7edf8c2d", path="src/aipass/other/thing.py")

        assert "add two" in result["diff"]
        assert "hello world" not in result["diff"]

    def test_the_answer_names_the_ref(self, fake_repo: dict) -> None:
        """Which commit this patch came from is part of the answer."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo", ref="7edf8c2d")

        assert result["ref"] == "7edf8c2d"

    def test_a_commit_is_always_repo_wide_and_says_so(self, fake_repo: dict) -> None:
        """drone's show door is repo-wide by design, so the grain reports repo."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_diff("demo", ref="7edf8c2d")

        assert result["grain"] == "repo"

    def test_asking_for_branch_grain_on_a_commit_is_refused(self, fake_repo: dict) -> None:
        """
        Silently ignoring a parameter is a lie told by omission. A caller who
        asked for branch scope on a commit gets told why it cannot exist.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_reads.read_diff("demo", ref="7edf8c2d", grain="branch")

        assert "repo" in str(caught.value)

    def test_staged_and_a_ref_together_are_refused(self, fake_repo: dict) -> None:
        """A commit has no staging area — the combination is meaningless."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_diff("demo", ref="7edf8c2d", staged=True)

    def test_a_ref_shaped_like_a_flag_is_refused_before_spawn(self, fake_repo: dict) -> None:
        """
        A leading dash would be read as an option, not a commit. Garbage is
        refused before a subprocess exists, never argued with afterwards.
        """
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_diff("demo", ref="--upload-pack=evil")

        assert mock_run.call_count == 0

    def test_a_ref_with_a_shell_metacharacter_is_refused(self, fake_repo: dict) -> None:
        """No shell is used, but a ref outside git's own vocabulary is garbage."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_diff("demo", ref="HEAD; wipe everything")

        assert mock_run.call_count == 0

    def test_ordinary_revisions_are_allowed_through(self, fake_repo: dict) -> None:
        """
        The fence must not become a wall: HEAD~3 and a branch path are the
        names an operator actually types.
        """
        for ref in ("HEAD", "HEAD~3", "HEAD^", "work/api", "v1.2.3", "b47462b7"):
            with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
                host_reads.read_diff("demo", ref=ref)

            assert mock_run.call_count == 1, f"{ref} should have been allowed"


class TestGitLog:
    """
    Commit list. MEASURED: drone's log door is --oneline from the repo root, so
    an entry carries a short sha and a subject and NOTHING else — no author, no
    date, however much the design asked for them. This lane ships what the door
    gives and the gap is reported rather than invented.
    """

    def _completed(self, stdout: str = GIT_LOG_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_routes_through_drone_not_raw(self, fake_repo: dict) -> None:
        """Git is drone-only, and history is no exception."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_git_log("demo")

        assert mock_run.call_args[0][0][:2] == ["drone", "@git"]

    def test_each_entry_splits_sha_from_subject(self, fake_repo: dict) -> None:
        """
        --oneline is a sha, one space, then a subject that may contain any
        number more. Splitting once is what keeps a colon-heavy message intact.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_log("demo")

        assert result["commits"][0]["sha"] == "b47462b7"
        assert result["commits"][0]["subject"] == "feat(fleet): the newest one"

    def test_the_list_is_newest_first_as_drone_gives_it(self, fake_repo: dict) -> None:
        """Order is git's, not re-sorted here on a guess about what a phone wants."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_log("demo")

        assert [c["sha"] for c in result["commits"]] == ["b47462b7", "7edf8c2d", "cb4afb12"]

    def test_count_agrees_with_the_list(self, fake_repo: dict) -> None:
        """One number, derived from the list, never counted twice."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_log("demo")

        assert result["count"] == len(result["commits"]) == 3

    def test_history_is_repo_wide_and_says_so(self, fake_repo: dict) -> None:
        """
        drone's log runs from find_repo_root() with no pathspec, so this is the
        REPO's history even though a branch named the anchor. Reporting branch
        grain here would be a straight lie.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_git_log("demo")

        assert result["grain"] == "repo"

    def test_the_limit_reaches_drone(self, fake_repo: dict) -> None:
        """The cap is enforced at the door, not by trimming a longer answer here."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_git_log("demo", limit=5)

        assert "5" in mock_run.call_args[0][0]

    def test_a_limit_over_the_cap_is_refused_naming_it(self, fake_repo: dict) -> None:
        """
        Clamping silently would hand back 50 rows to a caller who asked for 500
        and let them believe that was all the history there is.
        """
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_reads.read_git_log("demo", limit=500)

        assert str(host_reads.MAX_LOG_COMMITS) in str(caught.value)
        assert mock_run.call_count == 0

    def test_a_limit_below_one_is_refused(self, fake_repo: dict) -> None:
        """drone's own door exits 1 on count below one; refusing here says why."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_git_log("demo", limit=0)

        assert mock_run.call_count == 0

    def test_a_missing_drone_is_an_honest_unavailable(self, fake_repo: dict) -> None:
        """Same 503 as every other lane that routes through drone."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("no drone")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_git_log("demo")

    def test_a_failed_log_is_reported_not_returned_empty(self, fake_repo: dict) -> None:
        """An empty commit list would read as a repo with no history."""
        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_git_log("demo")

    def test_prose_lines_are_not_commits(self, fake_repo: dict) -> None:
        """
        Structure, not prose: an entry qualifies by leading with a hex sha, so
        a header or footer drone might add cannot become a phantom commit.
        """
        noisy = "Recent commits in the repository:\n" + GIT_LOG_STDOUT + "\n(showing 3 of many)"

        with patch.object(subprocess, "run", return_value=self._completed(noisy)):
            result = host_reads.read_git_log("demo")

        assert result["count"] == 3


class TestCommitDetail:
    """
    One commit's story: who, when, what it said, and which files moved by how
    much. Parsed from drone's show door, whose header is git's own
    --pretty=medium framing.
    """

    def _completed(self, stdout: str = GIT_SHOW_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_routes_through_drones_show_door(self, fake_repo: dict) -> None:
        """Git is drone-only here too."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_reads.read_commit("demo", ref="7edf8c2d")

        assert mock_run.call_args[0][0][:2] == ["drone", "@git"]

    def test_the_author_and_date_come_from_the_header(self, fake_repo: dict) -> None:
        """
        The fields the log door cannot give. show carries them, which is why
        detail is a separate lane rather than a richer list.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        assert result["author"] == "AIOSAI <aipass.system@gmail.com>"
        assert result["date"] == "Sat Aug 15 10:15:22 2026 -0700"

    def test_the_full_sha_is_reported_alongside_the_ref_asked_for(self, fake_repo: dict) -> None:
        """A caller who asked with HEAD~3 still learns which commit that was."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        assert result["sha"] == "7edf8c2dfcccbc1ce1b04d8420405f98e212a474"
        assert result["ref"] == "7edf8c2d"

    def test_the_subject_is_the_first_line_of_the_message(self, fake_repo: dict) -> None:
        """Git's own convention, and what a list row shows."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        assert result["subject"] == "feat(demo): the subject line"

    def test_the_message_keeps_its_body_without_the_display_indent(self, fake_repo: dict) -> None:
        """
        show indents the message by four spaces for display. Passing that
        through would paint every commit body as a code block on the phone.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        assert "And a second paragraph of body." in result["message"]
        assert "\n    And a second" not in result["message"]

    def test_the_files_carry_plus_and_minus_counts(self, fake_repo: dict) -> None:
        """
        The stat line every git surface shows. Counted from the patch's own
        plus and minus line starts, which is structure.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        rows = {row["path"]: row for row in result["files"]}
        assert rows["src/aipass/demo/hello.txt"]["additions"] == 1
        assert rows["src/aipass/demo/hello.txt"]["deletions"] == 1
        assert rows["src/aipass/other/thing.py"]["additions"] == 2
        assert rows["src/aipass/other/thing.py"]["deletions"] == 1

    def test_the_file_headers_are_not_counted_as_changed_lines(self, fake_repo: dict) -> None:
        """
        THE CLASSIC MISCOUNT: the two file-header lines start with the same
        characters as a changed line. Counting them would add one phantom
        addition and one phantom deletion to every file in every commit.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        total = sum(row["additions"] + row["deletions"] for row in result["files"])
        assert total == 5

    def test_context_lines_count_as_neither(self, fake_repo: dict) -> None:
        """A space-prefixed line is unchanged context, not a change."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        rows = {row["path"]: row for row in result["files"]}
        assert rows["src/aipass/other/thing.py"]["additions"] == 2

    def test_count_agrees_with_the_file_list(self, fake_repo: dict) -> None:
        """One number, derived."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        assert result["count"] == len(result["files"]) == 2

    def test_the_whole_patch_is_not_shipped_in_the_detail(self, fake_repo: dict) -> None:
        """
        The detail lane is metadata plus a stat list. The patch is the diff
        lane's job, per file, precisely so a phone never loads a whole commit.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        assert "diff" not in result

    def test_a_garbage_ref_is_refused_before_spawn(self, fake_repo: dict) -> None:
        """One fence, shared with the diff lane."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_reads.read_commit("demo", ref="-x")

        assert mock_run.call_count == 0

    def test_an_unknown_commit_is_reported_honestly(self, fake_repo: dict) -> None:
        """git says fatal, drone exits non-zero, and this lane says so."""
        failed = self._completed(stdout="", returncode=128, stderr="fatal: bad object deadbeef")

        with patch.object(subprocess, "run", return_value=failed):
            with pytest.raises(host_reads.ReadUnavailable) as caught:
                host_reads.read_commit("demo", ref="deadbeef")

        assert "bad object" in str(caught.value)

    def test_a_commit_that_changed_nothing_is_still_a_commit(self, fake_repo: dict) -> None:
        """
        An empty or merge commit has a header and no patch. Zero files is the
        honest answer, not a refusal and not a crash.
        """
        header_only = "\n".join(GIT_SHOW_STDOUT.splitlines()[:6]) + "\n"

        with patch.object(subprocess, "run", return_value=self._completed(header_only)):
            result = host_reads.read_commit("demo", ref="7edf8c2d")

        assert result["files"] == []
        assert result["count"] == 0


# =============================================
# THE REMOTE — link-cards out to the forge
# =============================================


def _raise(error: Exception) -> Any:
    """Raise inside a lambda — the fixture's resolver needs one expression."""
    raise error


@pytest.fixture
def remote_repo(tmp_path: Path):
    """A repo whose configuration can be rewritten per test, with one branch."""
    root = tmp_path / "RemoteRepo"
    branch = root / "src" / "aipass" / "demo"
    branch.mkdir(parents=True)
    (root / ".git").mkdir()

    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps({"branches": [{"name": "DEMO", "path": str(branch), "email": "@demo"}]}),
        encoding="utf-8",
    )

    fake_drone = MagicMock()
    fake_drone.BranchNotFoundError = _BranchNotFound
    fake_drone.RegistryError = _RegistryBroken
    fake_drone.get_registry_path.return_value = str(registry)
    fake_drone.get_branch_info.side_effect = lambda name: (
        {"name": "DEMO", "path": str(branch), "email": "@demo"}
        if name.lower() in ("demo", "@demo")
        else _raise(_BranchNotFound(name))
    )

    def configure(text: str) -> None:
        (root / ".git" / "config").write_text(text, encoding="utf-8")

    configure('[remote "origin"]\n\turl = https://github.com/AIOSAI/AIPass.git\n')

    with patch(PATCH_READS_DRONE, fake_drone), patch(PATCH_READS_LOGGER), patch(PATCH_READS_JSON):
        yield {"root": root, "branch": branch, "configure": configure}


class TestGitRemote:
    """
    Phase 4 wants link-cards out to the forge, zero-auth, from constructible
    URLs — so the face needs to be told the repository's remote.

    MEASURED, 2026-08-17, before anything was designed: THERE IS NO REMOTE DOOR.
    Not a verb on drone's git surface, not on drone's public Python surface, and
    the fleet's own gate refuses both raw readers — neither is in its read-only
    allowlist. So this lane invokes nothing and reads the repository's
    configuration as the INI file it is. That keeps "git is drone-only, servers
    included" intact rather than quietly carving an exception into it, and a
    verb on drone retires every line of it. It has been asked for.
    """

    def test_the_configured_remote_comes_back(self, remote_repo: dict) -> None:
        """The whole point of the lane."""
        answer = host_reads.read_git_remote("demo")

        assert answer["url"] == "https://github.com/AIOSAI/AIPass.git"

    def test_the_browsable_form_drops_the_dot_suffix(self, remote_repo: dict) -> None:
        """
        What the face actually links. `/pulls` appended to a URL ending in the
        clone suffix is a 404 on every forge there is.
        """
        answer = host_reads.read_git_remote("demo")

        assert answer["web"] == "https://github.com/AIOSAI/AIPass"

    def test_the_configured_url_is_never_rewritten(self, remote_repo: dict) -> None:
        """
        `url` is what was configured, verbatim; `web` is what a browser can
        open. Two fields because they are two facts, and collapsing them would
        make the lane lie about one of them.
        """
        answer = host_reads.read_git_remote("demo")

        assert answer["url"].endswith(".git")
        assert not answer["web"].endswith(".git")

    def test_it_names_which_remote_answered(self, remote_repo: dict) -> None:
        """A repository may have several. Which one spoke is part of the answer."""
        answer = host_reads.read_git_remote("demo")

        assert answer["remote"] == "origin"

    def test_a_remote_is_a_repository_fact_and_says_so(self, remote_repo: dict) -> None:
        """
        Same vocabulary as the log and commit lanes: the branch names WHICH
        repository, never a scope inside it.
        """
        answer = host_reads.read_git_remote("demo")

        assert answer["grain"] == "repo"

    def test_origin_wins_when_several_are_configured(self, remote_repo: dict) -> None:
        """The convention, honoured — and still named rather than assumed."""
        remote_repo["configure"](
            '[remote "upstream"]\n\turl = https://github.com/other/thing.git\n'
            '[remote "origin"]\n\turl = https://github.com/AIOSAI/AIPass.git\n'
        )

        answer = host_reads.read_git_remote("demo")

        assert answer["remote"] == "origin"
        assert "AIPass" in answer["url"]

    def test_without_an_origin_the_first_one_answers_and_is_named(self, remote_repo: dict) -> None:
        """
        Refusing a repository that simply named its remote something else would
        be this lane inventing a rule that does not exist. It answers, and the
        `remote` field is what stops that being a guess the caller cannot see.
        """
        remote_repo["configure"]('[remote "upstream"]\n\turl = https://github.com/other/thing.git\n')

        answer = host_reads.read_git_remote("demo")

        assert answer["remote"] == "upstream"
        assert answer["web"] == "https://github.com/other/thing"

    def test_a_repository_with_no_remote_is_refused_in_words(self, remote_repo: dict) -> None:
        """
        NOT hypothetical: two projects in the real tree have none at all. An
        empty string would render as a link card pointing nowhere.
        """
        remote_repo["configure"]("[core]\n\tbare = false\n")

        with pytest.raises(host_reads.ReadRefused) as caught:
            host_reads.read_git_remote("demo")

        assert "remote" in str(caught.value)

    def test_a_branch_in_no_repository_is_unavailable_not_refused(self, remote_repo: dict, tmp_path: Path) -> None:
        """
        Consistent with the changes lane: not-a-repository is a 503, because
        nothing about the caller's request was wrong.
        """
        loose = tmp_path / "Loose" / "src" / "thing" / "br"
        loose.mkdir(parents=True)

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "br", "path": str(loose)}

        with patch(PATCH_HOST_FLEET, census):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_git_remote("br", project="LOOSE")

    def test_no_subprocess_is_ever_spawned_on_this_lane(self, remote_repo: dict) -> None:
        """
        THE DOCTRINE PIN. The gate refuses both raw readers, so this lane shells
        nothing at all. A subprocess appearing here later would be an exception
        carved into "git is drone-only" without anyone deciding to carve it.
        """
        with patch.object(subprocess, "run") as mock_run:
            host_reads.read_git_remote("demo")

        mock_run.assert_not_called()


class TestRemoteURLForms:
    """
    Every shape a remote is written in. The seat and its siblings all use https
    today — measured across seven real repositories — so the ssh forms are
    pinned here rather than discovered the day somebody clones over ssh.
    """

    def _web(self, remote_repo: dict, url: str) -> Any:
        remote_repo["configure"]('[remote "origin"]\n\turl = %s\n' % url)
        return host_reads.read_git_remote("demo")["web"]

    def test_the_scp_short_form_becomes_browsable(self, remote_repo: dict) -> None:
        """The form every forge offers by default."""
        assert self._web(remote_repo, "git@github.com:AIOSAI/AIPass.git") == "https://github.com/AIOSAI/AIPass"

    def test_an_explicit_ssh_url_becomes_browsable(self, remote_repo: dict) -> None:
        """The long form of the same thing."""
        assert self._web(remote_repo, "ssh://git@github.com/AIOSAI/AIPass.git") == "https://github.com/AIOSAI/AIPass"

    def test_the_anonymous_protocol_becomes_browsable(self, remote_repo: dict) -> None:
        """Read-only clone URLs still describe a page a person can open."""
        assert self._web(remote_repo, "git://github.com/AIOSAI/AIPass.git") == "https://github.com/AIOSAI/AIPass"

    def test_http_is_not_silently_upgraded(self, remote_repo: dict) -> None:
        """
        Turning a configured `http` into `https` would be this lane deciding
        something about somebody's host that it cannot know. ssh has no
        browsable form of its own so converting it is forced; http has one.
        """
        assert self._web(remote_repo, "http://internal.example/o/r.git") == "http://internal.example/o/r"

    def test_a_local_path_remote_has_no_web_form_and_says_so(self, remote_repo: dict) -> None:
        """
        A directory is not a web page. `None` is the honest answer — a
        constructed scheme in front of a filesystem path would be a link card
        leading somewhere that has never existed.
        """
        remote_repo["configure"]('[remote "origin"]\n\turl = /srv/mirrors/aipass.git\n')

        answer = host_reads.read_git_remote("demo")

        assert answer["web"] is None
        assert answer["url"] == "/srv/mirrors/aipass.git"

    def test_a_relative_path_remote_has_no_web_form_either(self, remote_repo: dict) -> None:
        """`../sibling` is a path however few slashes it has."""
        assert self._web(remote_repo, "../sibling-repo") is None

    def test_a_windows_path_is_not_mistaken_for_the_scp_form(self, remote_repo: dict) -> None:
        """
        THE TRAP: `C:\\repos\\thing` has a colon in it, exactly like
        `host:path`. Reading it as the short form would emit a link card
        pointing at a host named C.
        """
        assert self._web(remote_repo, "C:\\repos\\thing") is None


class TestRemoteCredentialsNeverTravel:
    """
    NOT IN THE ASK, and shipped anyway because the alternative is a credential
    on a phone. A remote URL may carry `user:token@` — that is how a machine
    clones a private repository without an agent — and this lane's entire job is
    to hand that URL to a client over the network.
    """

    WITH_SECRET = '[remote "origin"]\n\turl = https://aiosai:ghp_supersecret@github.com/AIOSAI/AIPass.git\n'

    def test_a_password_in_the_url_is_redacted(self, remote_repo: dict) -> None:
        """The secret never leaves this process, in any field."""
        remote_repo["configure"](self.WITH_SECRET)

        answer = host_reads.read_git_remote("demo")

        assert "ghp_supersecret" not in json.dumps(answer)

    def test_the_redaction_is_announced_never_silent(self, remote_repo: dict) -> None:
        """
        An operator comparing this answer to their own configuration must be
        able to see that it was changed, or they will chase a phantom mismatch.
        """
        remote_repo["configure"](self.WITH_SECRET)

        assert host_reads.read_git_remote("demo")["redacted"] is True

    def test_the_url_keeps_its_shape_so_it_is_still_recognisable(self, remote_repo: dict) -> None:
        """Redacted, not deleted — the operator should still know which remote this is."""
        remote_repo["configure"](self.WITH_SECRET)

        answer = host_reads.read_git_remote("demo")

        assert "aiosai" in answer["url"]
        assert "github.com/AIOSAI/AIPass" in answer["url"]

    def test_the_web_form_carries_no_user_at_all(self, remote_repo: dict) -> None:
        """A browsable link needs no identity in it, so it is given none."""
        remote_repo["configure"](self.WITH_SECRET)

        answer = host_reads.read_git_remote("demo")

        assert answer["web"] == "https://github.com/AIOSAI/AIPass"
        assert "@" not in answer["web"]

    def test_the_ssh_user_is_not_a_credential(self, remote_repo: dict) -> None:
        """
        `git@github.com` carries the standard ssh user and no secret. Flagging
        it would cry wolf on the single commonest remote form there is, and an
        alarm that fires on everything is an alarm nobody reads.
        """
        remote_repo["configure"]('[remote "origin"]\n\turl = git@github.com:AIOSAI/AIPass.git\n')

        assert host_reads.read_git_remote("demo")["redacted"] is False


class TestRemoteInAWorktree:
    """
    A worktree carries its marker as a FILE pointing elsewhere, and its
    configuration lives in the repository it was cut from — the same shape that
    already bit the changed-file lane once.
    """

    def _wire(self, tree: Path, branch: Path) -> Any:
        registry = tree / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "DEMO", "path": str(branch), "email": "@demo"}]}),
            encoding="utf-8",
        )
        fake_drone = MagicMock()
        fake_drone.BranchNotFoundError = _BranchNotFound
        fake_drone.RegistryError = _RegistryBroken
        fake_drone.get_registry_path.return_value = str(registry)
        fake_drone.get_branch_info.return_value = {"name": "DEMO", "path": str(branch)}
        return fake_drone

    def test_a_pointer_file_is_followed_to_the_real_configuration(self, tmp_path: Path) -> None:
        """Following the pointer is the difference between an answer and a 503."""
        main = tmp_path / "Main"
        (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
        (main / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/AIOSAI/AIPass.git\n', encoding="utf-8"
        )
        (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")

        tree = tmp_path / "Tree"
        branch = tree / "src" / "aipass" / "demo"
        branch.mkdir(parents=True)
        (tree / ".git").write_text("gitdir: %s\n" % (main / ".git" / "worktrees" / "wt"), encoding="utf-8")

        fake_drone = self._wire(tree, branch)
        with patch(PATCH_READS_DRONE, fake_drone), patch(PATCH_READS_LOGGER), patch(PATCH_READS_JSON):
            answer = host_reads.read_git_remote("demo")

        assert answer["web"] == "https://github.com/AIOSAI/AIPass"

    def test_a_pointer_to_nowhere_refuses_rather_than_guessing(self, tmp_path: Path) -> None:
        """A dangling pointer is reported. A fallback here would invent a repository."""
        tree = tmp_path / "Broken"
        branch = tree / "src" / "aipass" / "demo"
        branch.mkdir(parents=True)
        (tree / ".git").write_text("gitdir: %s\n" % (tmp_path / "gone"), encoding="utf-8")

        fake_drone = self._wire(tree, branch)
        with patch(PATCH_READS_DRONE, fake_drone), patch(PATCH_READS_LOGGER), patch(PATCH_READS_JSON):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.read_git_remote("demo")
