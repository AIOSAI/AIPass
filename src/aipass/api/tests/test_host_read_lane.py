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

    def test_project_mismatch_refused(self, fake_repo: dict) -> None:
        """A project this server does not serve is refused, never ignored."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "hello.txt", project="SomeOtherProject")

        assert "seated" in str(exc.value).lower()

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
