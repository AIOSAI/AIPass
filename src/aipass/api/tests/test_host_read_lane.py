# =================== AIPass ====================
# Name: test_host_read_lane.py
# Description: Tests for the host API read lane — file reads, the whole diff, and the read lane's /v1 routes
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-10-08
# =============================================

"""Tests for the file and diff reads in apps/handlers/host/reads.py and git_reads.py, and their /v1 routes."""

# Tests for apps/handlers/host/{feed,reads}.py and their routes.
#
# FPLAN-0411 Phase 2 (partial: feed + files + diff; fleet held on C1).
#
# The two things that must not be got wrong here are the cursor (a stale one is
# the TG 10-hour outage species) and the fence (a remote caller choosing what to
# read). Both carry the most tests.
#
# Tests — handlers/host/feed.py (design call D3):
# - read_feed: no cursor returns the most recent window, newest cursor
# - read_feed: empty feed returns an empty envelope, no crash
# - read_feed: missing feed file reads as empty, not an error
# - read_feed: cursor mid-feed returns everything at or after it
# - read_feed: boundary event is RE-DELIVERED (at-least-once, dupes over drops)
# - read_feed: cursor older than the feed flags gap + gap_reason=feed_trimmed
# - read_feed: cursor ahead of the feed clamps, returns empty, never spins
# - read_feed: limit caps the window and reports more=True (no silent cap)
# - read_feed: limit is clamped to MAX_LIMIT
# - read_feed: malformed lines are skipped, good ones still returned
# - read_feed: lines without a ts are skipped
# - read_feed: file order is preserved (never re-sorted)
# - read_feed: unreadable feed raises FeedUnavailable rather than faking empty
# - read_feed: a real trim (400->200) leaves an old cursor flagged, not silent
#
# Tests — handlers/host/reads.py, git_reads.py and remotes.py (the name fence):
# - _fence: absolute path refused
# - _fence: '..' component refused
# - _fence: nested '..' refused
# - _fence: symlink escaping the branch refused (post-resolution check)
# - _fence: empty name refused
# - _fence: legitimate nested file accepted
# - _fence: missing file refused
# - resolve_branch_root: known branch resolves via the registry
# - resolve_branch_root: email form resolves
# - resolve_branch_root: unknown branch refused
# - resolve_branch_root: empty branch refused
# - resolve_branch_root: unreadable registry raises ReadUnavailable
# - read_file: returns content and byte count
# - read_file: over-cap file is REFUSED, never silently truncated
# - read_file: non-UTF8 file refused
# - read_file: project mismatch refused
# - read_diff: routes through drone, never raw git
# - read_diff: staged flag is passed through
# - read_diff: drone missing raises ReadUnavailable
# - read_diff: timeout raises ReadUnavailable
# - read_diff: non-zero exit raises ReadUnavailable
# - read_diff: oversized diff is truncated AND reports truncated=True
#
# Tests — routes:
# - GET /v1/feed: 401 without a token
# - GET /v1/feed: 200 with a read token, returns the envelope
# - GET /v1/feed: gap surfaces through the route
# - GET /v1/files: 401 without a token
# - GET /v1/files: 200 returns file content
# - GET /v1/files: fence violation is 400 with the error envelope
# - GET /v1/diff: 200 returns diff text
# - GET /v1/diff: unknown branch is 400
#
# WHERE EACH LIVES since the oversize split (api, 2026-10-08): the feed
# cursor, the fence, branch roots and the seat listed above are in
# test_host_read_lane_feed.py; the git-changes lane in
# test_host_read_lane_changes.py; per-file diffs, commit patches, the log,
# commit detail and the remote in test_host_read_lane_history.py. This file
# keeps the file and whole-diff reads and every route. The shared builders
# are in support_host_read_lane.py, the shared fixtures in conftest.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — drone's own diff output; read_diff's subprocess call is faked, drone tests it
# seedgo: no-test-needed(covered_elsewhere) — token minting and the token store; tests/test_host_token_store.py
# seedgo: no-test-needed(ruff) — that every module in apps/handlers/host/ parses and imports

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import git_reads as host_git
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.tests.support_host_read_lane import (
    GIT_LOG_STDOUT,
    GIT_SHOW_STDOUT,
    GIT_STATUS_ALL_STDOUT,
    GIT_STATUS_STDOUT,
    TWO_FILE_DIFF,
    _event,
    _write_feed,
    remotes_document,
)


PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"

PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_HOST_FLEET = "aipass.api.apps.handlers.host.fleet"


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

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("demo", "blob.bin")

        # `assert True` sat here until 2026-09-07 — an assertion that cannot
        # fail, decorating a raises block that was already the real oracle.
        # Replaced with the thing the raises block does NOT check: that the
        # refusal says what was wrong, so a caller is not left guessing whether
        # the path or the bytes were the problem.
        said = str(exc.value)

        assert "Not UTF-8 text" in said, f"the refusal does not say the file was not text: {said}"
        assert "blob.bin" in said, f"the refusal does not name the file it refused: {said}"

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
            host_git.read_diff("demo")

        command = mock_run.call_args[0][0]
        assert command[:3] == ["drone", "@git", "diff"]

    def test_staged_flag_passed_through(self, fake_repo: dict) -> None:
        """--staged reaches drone rather than being reinterpreted here."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_diff("demo", staged=True)

        assert "--staged" in mock_run.call_args[0][0]

    def test_runs_in_the_branch_directory(self, fake_repo: dict) -> None:
        """drone's git lane is CWD-scoped, so the cwd IS the branch selection."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_diff("demo")

        assert mock_run.call_args.kwargs["cwd"] == str(fake_repo["branch"].resolve())

    def test_missing_drone_raises_unavailable(self, fake_repo: dict) -> None:
        """No drone on PATH is an honest 503, not an empty diff."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("no drone")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_diff("demo")

    def test_timeout_raises_unavailable(self, fake_repo: dict) -> None:
        """A hung diff must not hang the request forever."""
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_diff("demo")

    def test_non_zero_exit_raises_unavailable(self, fake_repo: dict) -> None:
        """A failed diff is reported, never returned as empty output."""
        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_diff("demo")

    def test_oversized_diff_truncates_and_says_so(self, fake_repo: dict) -> None:
        """Generated output may be capped — but the cap is REPORTED."""
        huge = "x" * (host_git.MAX_DIFF_BYTES + 100)

        with patch.object(subprocess, "run", return_value=self._completed(stdout=huge)):
            result = host_git.read_diff("demo")

        assert result["truncated"] is True
        assert len(result["diff"]) <= host_git.MAX_DIFF_BYTES


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
                {"path": "hello.txt", "status": " M", "index": " ", "worktree": "M"},
                {"path": "brand_new.py", "status": "??", "index": "?", "worktree": "?"},
                {"path": "nested/deep.txt", "status": " D", "index": " ", "worktree": "D"},
                # THE BUG, VISIBLE IN THE WIRE PIN. This row read ' R' until
                # 2026-08-18 — an unstaged rename, which git does not emit. The
                # rename is STAGED, the code is 'R ', and the old lane could not
                # have said so: drone's rendered surface had already right-
                # aligned the letter out of the index column before this server
                # saw it. The contract was always right; the data now honours it.
                {"path": "new_name.py", "status": "R ", "index": "R", "worktree": " "},
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
        assert str(host_git.MAX_LOG_COMMITS) in response.json()["error"]["message"]

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
        remote_repo["serve"](remotes_document([]))

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

    The owner ruled it on 2026-08-16, his words: "I should be able to open another
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

        with patch.object(host_git.subprocess, "run", return_value=completed) as run:
            result = host_git.read_diff("baud", project="BAUD")

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
