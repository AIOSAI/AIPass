# =================== AIPass ====================
# Name: test_host_read_lane_history.py
# Description: Tests for the read lane's per-file diff, commit patch, log, commit detail and remote link-cards
# Version: 1.1.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for read_diff, read_git_log, read_commit and read_git_remote in apps/handlers/host/git_reads.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — drone's own diff, show, log and remote output; subprocess.run and the diff door's Popen are faked here

import io
import json
import secrets
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import git_reads as host_git
from aipass.api.tests.support_host_read_lane import (
    GIT_LOG_STDOUT,
    GIT_SHOW_STDOUT,
    GIT_SHOW_TEXT,
    TWO_FILE_DIFF,
    _BranchNotFound,
    _RegistryBroken,
    remote_document,
    remotes_document,
    show_document,
)

# This file's own constants, not conftest's: seedgo's discarded_patch rule judges an imported target.
PATCH_READS_LOGGER = "aipass.api.apps.handlers.host.reads.logger"
PATCH_READS_JSON = "aipass.api.apps.handlers.host.reads.json_handler"
PATCH_READS_DRONE = "aipass.api.apps.handlers.host.reads.drone"
PATCH_GIT_LOGGER = "aipass.api.apps.handlers.host.git_reads.logger"
PATCH_GIT_JSON = "aipass.api.apps.handlers.host.git_reads.json_handler"

# What drone's door serves at branch grain: only the blocks under the branch.
BRANCH_ONLY_DIFF = TWO_FILE_DIFF[: TWO_FILE_DIFF.index("diff --git", 1)]


class TestPerFileDiff:
    """
    Tap-a-file: one file's patch is cut out of the generated diff on its repo-relative headers.

    The header-parsing cases ask at repo grain, where a path is matched exactly as given.
    """

    def _completed(self, stdout: str = TWO_FILE_DIFF, returncode: int = 0, stderr: str = "") -> Any:
        """drone's diff door as a child process: the patch on its stdout pipe."""
        child = MagicMock()
        child.stdout = io.BytesIO(stdout.encode("utf-8"))
        child.stderr = io.BytesIO(stderr.encode("utf-8"))
        child.wait.return_value = returncode
        return child

    def test_a_path_returns_only_that_files_patch(self, fake_repo: dict) -> None:
        """The tap-a-file contract: one file in, one file's changes out."""
        with patch.object(subprocess, "Popen", return_value=self._completed()):
            result = host_git.read_diff("demo", path="src/aipass/demo/hello.txt")

        assert "hello world" in result["diff"]
        assert "thing.py" not in result["diff"]

    def test_the_patch_keeps_its_own_file_header(self, fake_repo: dict) -> None:
        """react-diff-view's parseDiff() reads the header for the filename and the change kind."""
        with patch.object(subprocess, "Popen", return_value=self._completed()):
            result = host_git.read_diff("demo", path="src/aipass/other/thing.py", grain="repo")

        assert result["diff"].startswith("diff --git a/src/aipass/other/thing.py")
        assert "@@" in result["diff"]

    def test_the_answer_names_the_path_it_answered_for(self, fake_repo: dict) -> None:
        """The response says which file it is, never leaving it to be inferred."""
        with patch.object(subprocess, "Popen", return_value=self._completed()):
            result = host_git.read_diff("demo", path="src/aipass/demo/hello.txt")

        assert result["path"] == "src/aipass/demo/hello.txt"

    def test_no_path_returns_the_whole_diff_unchanged(self, fake_repo: dict) -> None:
        """The live lane keeps its contract — the phone reads it right now."""
        with patch.object(subprocess, "Popen", return_value=self._completed()):
            result = host_git.read_diff("demo")

        assert result["diff"] == TWO_FILE_DIFF
        assert result["path"] == ""

    def test_a_file_with_no_changes_is_refused_in_words(self, fake_repo: dict) -> None:
        """An empty string would read as "no changes rendered fine"; a stale tap gets a sentence."""
        with patch.object(subprocess, "Popen", side_effect=lambda *_a, **_k: self._completed()):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_diff("demo", path="src/aipass/demo/never_touched.py")

        assert "never_touched.py" in str(caught.value)

    def test_a_near_miss_name_does_not_match(self, fake_repo: dict) -> None:
        """The header's exact path, not a substring: "hello.txt" must not answer for "other_hello.txt"."""
        with patch.object(subprocess, "Popen", side_effect=lambda *_a, **_k: self._completed()):
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_diff("demo", path="demo/hello.txt")

    def test_an_oversized_single_file_is_refused_not_trimmed(self, fake_repo: dict) -> None:
        """Half a patch is a broken one: a renderer handed a severed hunk paints nonsense."""
        huge = (
            "diff --git a/src/aipass/demo/big.txt b/src/aipass/demo/big.txt\n"
            "--- a/src/aipass/demo/big.txt\n+++ b/src/aipass/demo/big.txt\n@@ -1 +1 @@\n"
            + "+x\n"
            * host_git.MAX_DIFF_BYTES
        )

        with patch.object(subprocess, "Popen", return_value=self._completed(huge)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_diff("demo", path="src/aipass/demo/big.txt")

        assert str(host_git.MAX_DIFF_BYTES) in str(caught.value)

    def test_a_file_block_is_copied_once_not_once_per_line(self, fake_repo: dict, monkeypatch: Any) -> None:
        """
        The per-file split pins its COST, never a clock: one join per block, whatever its length.

        Blind spot: it counts joins, not copies; a list copied once per line joins once and passes.
        """
        joins = []

        def counted(lines: Any) -> str:
            joins.append(len(lines))
            return "".join(lines)

        monkeypatch.setattr(host_git, "_BLOCK_JOIN", counted)
        body = "@@ -1 +1 @@\n" + "+x\n" * 500
        patch_text = "".join(
            f"diff --git a/src/aipass/demo/{name} b/src/aipass/demo/{name}\n"
            f"--- a/src/aipass/demo/{name}\n+++ b/src/aipass/demo/{name}\n" + body
            for name in ("one.txt", "two.txt")
        )

        with patch.object(subprocess, "Popen", return_value=self._completed(patch_text)):
            answer = host_git.read_diff("demo", path="src/aipass/demo/two.txt")

        assert joins == [504, 504], "one join per file block, each over the whole block"
        assert answer["diff"].count("+x\n") == 500

    def test_removed_content_that_looks_like_a_header_is_not_read_as_one(self, fake_repo: dict) -> None:
        """
        THE TRAP: deleting a line '-- x' yields '--- x', the shape of a file header.
        Scanning past the hunk marker for names would read that deletion as the file's name.
        """
        patch_text = (
            "diff --git a/doc.md b/doc.md\n"
            "--- a/doc.md\n"
            "+++ b/doc.md\n"
            "@@ -1,2 +1,2 @@\n"
            "--- a/decoy/path.txt\n"
            "+++ b/decoy/path.txt\n"
        )

        with patch.object(subprocess, "Popen", return_value=self._completed(patch_text)):
            result = host_git.read_diff("demo", path="doc.md", grain="repo")

        assert result["path"] == "doc.md"
        assert "decoy" in result["diff"]

    def test_a_binary_file_is_named_from_its_own_header(self, fake_repo: dict) -> None:
        """A binary change has no ---/+++ lines; the header names the path twice and the halves must agree."""
        patch_text = (
            "diff --git a/img/logo.png b/img/logo.png\n"
            "index 1111111..2222222 100644\n"
            "Binary files a/img/logo.png and b/img/logo.png differ\n"
        )

        with patch.object(subprocess, "Popen", return_value=self._completed(patch_text)):
            result = host_git.read_diff("demo", path="img/logo.png", grain="repo")

        assert "Binary files" in result["diff"]

    def test_a_filename_carrying_the_header_marker_still_resolves(self, fake_repo: dict) -> None:
        """A path containing the header's own separator; the agreeing halves keep the split out of the name."""
        patch_text = (
            "diff --git a/odd b/name.bin b/odd b/name.bin\nindex 1111111..2222222 100644\nBinary files differ\n"
        )

        with patch.object(subprocess, "Popen", return_value=self._completed(patch_text)):
            result = host_git.read_diff("demo", path="odd b/name.bin", grain="repo")

        assert "Binary files differ" in result["diff"]

    def test_repo_grain_diff_asks_for_the_whole_repo(self, fake_repo: dict) -> None:
        """The app's file list is repo grain, so its taps must be too."""
        with patch.object(subprocess, "Popen", return_value=self._completed()) as mock_run:
            host_git.read_diff("demo", path="src/aipass/other/thing.py", grain="repo")

        assert "--all" in mock_run.call_args[0][0]

    def test_an_unknown_grain_is_refused_here_too(self, fake_repo: dict) -> None:
        """One vocabulary across the lanes, one refusal for breaking it."""
        with patch.object(subprocess, "Popen", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_diff("demo", grain="sideways")

        assert mock_run.call_count == 0

    # C#2: branch-grain change rows are branch-local; the patch headers are repo-relative.

    def test_a_branch_local_path_opens_its_patch_at_branch_grain(self, fake_repo: dict) -> None:
        """The card's row spelling (README.md, not src/aipass/<b>/README.md) used to be refused."""
        with patch.object(subprocess, "Popen", return_value=self._completed(BRANCH_ONLY_DIFF)):
            result = host_git.read_diff("demo", path="hello.txt")

        assert "hello world" in result["diff"]
        assert result["path"] == "hello.txt"

    def test_a_repo_relative_path_still_opens_at_repo_grain(self, fake_repo: dict) -> None:
        path = "/".join(["src", "aipass", "other", "thing.py"])

        with patch.object(subprocess, "Popen", return_value=self._completed()):
            result = host_git.read_diff("demo", path=path, grain="repo")

        assert "add one" in result["diff"]
        assert "hello world" not in result["diff"]

    def test_an_already_prefixed_path_is_not_prefixed_twice(self, fake_repo: dict) -> None:
        path = "/".join(["src", "aipass", "demo", "hello.txt"])

        with patch.object(subprocess, "Popen", return_value=self._completed(BRANCH_ONLY_DIFF)) as mock_run:
            result = host_git.read_diff("demo", path=path)

        assert "hello world" in result["diff"]
        assert mock_run.call_count == 1

    def test_a_path_outside_the_branch_is_refused_at_branch_grain_as_before(self, fake_repo: dict) -> None:
        with patch.object(subprocess, "Popen", side_effect=lambda *_a, **_k: self._completed(BRANCH_ONLY_DIFF)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_diff("demo", path="thing.py")

        assert str(caught.value) == "No changes to thing.py in this patch"

    # C#4: the list is git status (index and worktree); the door's patch is worktree against index.

    def _halves(self, unstaged: str, staged: str) -> Any:
        """drone's diff door: the index's half when --staged is asked, the worktree's otherwise."""
        return lambda command, **_: self._completed(staged if "--staged" in command else unstaged)

    def test_a_staged_only_file_opens_its_staged_patch(self, fake_repo: dict) -> None:
        with patch.object(subprocess, "Popen", side_effect=self._halves("", BRANCH_ONLY_DIFF)) as mock_run:
            result = host_git.read_diff("demo", path="hello.txt")

        assert "hello world" in result["diff"]
        assert result["staged"] is True
        assert "--staged" in mock_run.call_args[0][0]

    def test_an_mm_file_shows_its_unstaged_half_and_asks_the_index_nothing(self, fake_repo: dict) -> None:
        index_half = BRANCH_ONLY_DIFF.replace("+hello world", "+hello index")

        with patch.object(subprocess, "Popen", side_effect=self._halves(BRANCH_ONLY_DIFF, index_half)) as mock_run:
            result = host_git.read_diff("demo", path="hello.txt")

        assert "+hello world" in result["diff"]
        assert "+hello index" not in result["diff"]
        assert result["staged"] is False
        assert mock_run.call_count == 1

    def test_an_unstaged_change_is_answered_from_the_worktree_alone(self, fake_repo: dict) -> None:
        with patch.object(subprocess, "Popen", side_effect=self._halves(BRANCH_ONLY_DIFF, "")) as mock_run:
            result = host_git.read_diff("demo", path="hello.txt")

        assert "hello world" in result["diff"]
        assert result["staged"] is False
        assert "--staged" not in mock_run.call_args[0][0]

    def test_a_file_in_neither_half_is_refused_after_both_are_asked(self, fake_repo: dict) -> None:
        with patch.object(subprocess, "Popen", side_effect=self._halves(BRANCH_ONLY_DIFF, "")) as mock_run:
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_diff("demo", path="absent.py")

        assert str(caught.value) == "No changes to absent.py in this patch"
        assert mock_run.call_count == 2


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
            host_git.read_diff("demo", ref="7edf8c2d")

        command = mock_run.call_args[0][0]
        assert command[:2] == ["drone", "@git"]
        assert "7edf8c2d" in command

    def test_the_commit_header_is_not_part_of_the_patch(self, fake_repo: dict) -> None:
        """Left in, the author and date lines make the renderer's first file a phantom named "commit"."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_diff("demo", ref="7edf8c2d")

        assert result["diff"].startswith("diff --git ")
        assert "AIOSAI" not in result["diff"]

    def test_a_ref_and_a_path_together_give_one_file_of_one_commit(self, fake_repo: dict) -> None:
        """The deepest tap in the app: this file, in this commit."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_diff("demo", ref="7edf8c2d", path="src/aipass/other/thing.py")

        assert "add two" in result["diff"]
        assert "hello world" not in result["diff"]

    def test_the_answer_names_the_ref(self, fake_repo: dict) -> None:
        """Which commit this patch came from is part of the answer."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_diff("demo", ref="7edf8c2d")

        assert result["ref"] == "7edf8c2d"

    def test_a_commit_is_always_repo_wide_and_says_so(self, fake_repo: dict) -> None:
        """drone's show door is repo-wide by design, so the grain reports repo."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_diff("demo", ref="7edf8c2d")

        assert result["grain"] == "repo"

    def test_asking_for_branch_grain_on_a_commit_is_refused(self, fake_repo: dict) -> None:
        """Silently ignoring a parameter is a lie told by omission."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_diff("demo", ref="7edf8c2d", grain="branch")

        assert "repo" in str(caught.value)

    def test_staged_and_a_ref_together_are_refused(self, fake_repo: dict) -> None:
        """A commit has no staging area — the combination is meaningless."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_diff("demo", ref="7edf8c2d", staged=True)

    def test_a_ref_shaped_like_a_flag_is_refused_before_spawn(self, fake_repo: dict) -> None:
        """A leading dash would be read as an option, not a commit."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_diff("demo", ref="--upload-pack=evil")

        assert mock_run.call_count == 0

    def test_a_ref_with_a_shell_metacharacter_is_refused(self, fake_repo: dict) -> None:
        """No shell is used, but a ref outside git's own vocabulary is garbage."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_diff("demo", ref="HEAD; wipe everything")

        assert mock_run.call_count == 0

    def test_ordinary_revisions_are_allowed_through(self, fake_repo: dict) -> None:
        """The fence must not become a wall: HEAD~3 and a branch path are what an operator types."""
        for ref in ("HEAD", "HEAD~3", "HEAD^", "work/api", "v1.2.3", "b47462b7"):
            with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
                host_git.read_diff("demo", ref=ref)

            assert mock_run.call_count == 1, f"{ref} should have been allowed"


class TestGitLog:
    """
    Commit list. drone's log door is --oneline from the repo root: a short sha and a subject only.
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
            host_git.read_git_log("demo")

        assert mock_run.call_args[0][0][:2] == ["drone", "@git"]

    def test_each_entry_splits_sha_from_subject(self, fake_repo: dict) -> None:
        """Split once: the subject may contain any number of spaces."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_log("demo")

        assert result["commits"][0]["sha"] == "b47462b7"
        assert result["commits"][0]["subject"] == "feat(fleet): the newest one"

    def test_the_list_is_newest_first_as_drone_gives_it(self, fake_repo: dict) -> None:
        """Order is git's, not re-sorted here on a guess about what a phone wants."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_log("demo")

        assert [c["sha"] for c in result["commits"]] == ["b47462b7", "7edf8c2d", "cb4afb12"]

    def test_a_row_with_no_object_name_is_not_a_commit(self, fake_repo: dict) -> None:
        """A row without an object name names nothing a caller could ever ask for again."""
        document = json.dumps(
            {
                "ok": True,
                "commits": [
                    {"sha": "b47462b7", "subject": "a real one"},
                    {"sha": "", "subject": "carries no object name"},
                ],
                "count": 2,
                "message": "2 commit(s)",
            }
        )

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            result = host_git.read_git_log("demo")

        assert result["count"] == 1
        assert result["commits"] == [{"sha": "b47462b7", "subject": "a real one"}]

    def test_count_agrees_with_the_list(self, fake_repo: dict) -> None:
        """One number, derived from the list, never counted twice."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_log("demo")

        assert result["count"] == len(result["commits"]) == 3

    def test_history_is_repo_wide_and_says_so(self, fake_repo: dict) -> None:
        """drone's log runs from find_repo_root() with no pathspec: the REPO's history."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_log("demo")

        assert result["grain"] == "repo"

    def test_the_limit_reaches_drone(self, fake_repo: dict) -> None:
        """The cap is enforced at the door, not by trimming a longer answer here."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_log("demo", limit=5)

        assert "5" in mock_run.call_args[0][0]

    def test_a_limit_over_the_cap_is_refused_naming_it(self, fake_repo: dict) -> None:
        """A silent clamp would let a caller believe 50 rows was all the history there is."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_git_log("demo", limit=500)

        assert str(host_git.MAX_LOG_COMMITS) in str(caught.value)
        assert mock_run.call_count == 0

    def test_a_limit_below_one_is_refused(self, fake_repo: dict) -> None:
        """drone's own door exits 1 on count below one; refusing here says why."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_git_log("demo", limit=0)

        assert mock_run.call_count == 0

    def test_a_missing_drone_is_an_honest_unavailable(self, fake_repo: dict) -> None:
        """Same 503 as every other lane that routes through drone."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("no drone")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_log("demo")

    def test_a_log_that_answered_with_nothing_is_reported_not_returned_empty(self, fake_repo: dict) -> None:
        """No document is drone's caller-check refusal (it never reaches the door): a 503, not no history."""
        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_log("demo")

    def test_prose_is_not_a_commit_list_it_is_a_could_not_tell(self, fake_repo: dict) -> None:
        """Output that is not a document is not a thin commit list; nobody can tell, so a 503."""
        rendered = "Recent commits in the repository:\nb47462b7 feat(fleet): the newest one"

        with patch.object(subprocess, "run", return_value=self._completed(rendered)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_log("demo")

    def test_a_refusal_document_is_an_answer_not_a_breakdown(self, fake_repo: dict) -> None:
        """git said no: a 400 in drone's words; a 503 would say retry for something that never changes."""
        refusal = json.dumps({"ok": False, "commits": [], "count": 0, "message": "git log error: bad revision"})

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_git_log("demo")

        assert "bad revision" in str(caught.value)


class TestCommitDetail:
    """One commit's story, parsed from drone's show door (git's --pretty=medium header)."""

    def _completed(self, stdout: str = GIT_SHOW_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_routes_through_drones_show_door(self, fake_repo: dict) -> None:
        """Git is drone-only here too."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_commit("demo", ref="7edf8c2d")

        assert mock_run.call_args[0][0][:2] == ["drone", "@git"]

    def test_the_author_and_date_come_from_the_header(self, fake_repo: dict) -> None:
        """The fields the log door cannot give, which is why detail is a separate lane."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert result["author"] == "AIOSAI <aipass.system@gmail.com>"
        assert result["date"] == "Sat Aug 15 10:15:22 2026 -0700"

    def test_the_full_sha_is_reported_alongside_the_ref_asked_for(self, fake_repo: dict) -> None:
        """A caller who asked with HEAD~3 still learns which commit that was."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert result["sha"] == "7edf8c2dfcccbc1ce1b04d8420405f98e212a474"
        assert result["ref"] == "7edf8c2d"

    def test_the_subject_is_the_first_line_of_the_message(self, fake_repo: dict) -> None:
        """Git's own convention, and what a list row shows."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert result["subject"] == "feat(demo): the subject line"

    def test_the_message_keeps_its_body_without_the_display_indent(self, fake_repo: dict) -> None:
        """show indents the message four spaces; passed through, every body renders as a code block."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert "And a second paragraph of body." in result["message"]
        assert "\n    And a second" not in result["message"]

    def test_the_files_carry_plus_and_minus_counts(self, fake_repo: dict) -> None:
        """Counted from +/- line starts; the exact counts also hold that a context line counts as neither."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        rows = {row["path"]: row for row in result["files"]}
        assert rows["src/aipass/demo/hello.txt"]["additions"] == 1
        assert rows["src/aipass/demo/hello.txt"]["deletions"] == 1
        assert rows["src/aipass/other/thing.py"]["additions"] == 2
        assert rows["src/aipass/other/thing.py"]["deletions"] == 1

    def test_the_file_headers_are_not_counted_as_changed_lines(self, fake_repo: dict) -> None:
        """THE CLASSIC MISCOUNT: the ---/+++ header lines start like changed lines."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        total = sum(row["additions"] + row["deletions"] for row in result["files"])
        assert total == 5

    def test_count_agrees_with_the_file_list(self, fake_repo: dict) -> None:
        """One number, derived."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert result["count"] == len(result["files"]) == 2

    def test_the_whole_patch_is_not_shipped_in_the_detail(self, fake_repo: dict) -> None:
        """The patch is the diff lane's job, per file, so a phone never loads a whole commit."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert "diff" not in result

    def test_a_garbage_ref_is_refused_before_spawn(self, fake_repo: dict) -> None:
        """One fence, shared with the diff lane."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_commit("demo", ref="-x")

        assert mock_run.call_count == 0

    def test_an_unknown_commit_is_the_callers_answer_in_gits_own_words(self, fake_repo: dict) -> None:
        """The real door answers a bad revision with an ok:false DOCUMENT, so a 400, not a 503."""
        refusal = show_document("", ref="deadbeef", ok=False, message="git show error: fatal: bad object deadbeef")

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_commit("demo", ref="deadbeef")

        assert "bad object" in str(caught.value)

    def test_a_door_that_leaves_no_document_is_still_a_503(self, fake_repo: dict) -> None:
        """drone's caller check refuses before the door runs, sentence on stderr: nobody could tell."""
        failed = self._completed(stdout="", returncode=1, stderr="cannot verify caller")

        with patch.object(subprocess, "run", return_value=failed):
            with pytest.raises(host_reads.ReadUnavailable) as caught:
                host_git.read_commit("demo", ref="deadbeef")

        assert "cannot verify caller" in str(caught.value)

    def test_a_commit_that_changed_nothing_is_still_a_commit(self, fake_repo: dict) -> None:
        """An empty or merge commit has a header and no patch: zero files, not a refusal."""
        header_only = show_document("\n".join(GIT_SHOW_TEXT.splitlines()[:6]) + "\n")

        with patch.object(subprocess, "run", return_value=self._completed(header_only)):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert result["files"] == []
        assert result["count"] == 0


class TestGitRemote:
    """
    Link-cards out to the forge, zero-auth, from the repository's remote via `drone @git remote --json`.
    """

    def test_the_configured_remote_comes_back(self, remote_repo: dict) -> None:
        """The whole point of the lane."""
        answer = host_git.read_git_remote("demo")

        assert answer["url"] == "https://github.com/AIOSAI/AIPass.git"

    def test_the_browsable_form_drops_the_dot_suffix(self, remote_repo: dict) -> None:
        """`/pulls` appended to a URL ending in the clone suffix is a 404 on every forge."""
        answer = host_git.read_git_remote("demo")

        assert answer["web"] == "https://github.com/AIOSAI/AIPass"

    def test_the_configured_url_is_never_rewritten(self, remote_repo: dict) -> None:
        """`url` is what the repository says, `web` is what a person can open."""
        answer = host_git.read_git_remote("demo")

        assert answer["url"].endswith(".git")
        assert not answer["web"].endswith(".git")

    def test_it_names_which_remote_answered(self, remote_repo: dict) -> None:
        """A card labelled with the wrong remote's URL is worse than no card."""
        assert host_git.read_git_remote("demo")["remote"] == "origin"

    def test_a_remote_is_a_repository_fact_and_says_so(self, remote_repo: dict) -> None:
        """The branch names WHICH repository, never a scope inside one."""
        assert host_git.read_git_remote("demo")["grain"] == "repo"

    def test_origin_wins_when_several_are_configured(self, remote_repo: dict) -> None:
        """The convention, honoured — and still named rather than assumed."""
        remote_repo["serve"](
            remotes_document(
                [
                    {"name": "upstream", "fetch": "https://github.com/other/thing.git", "redacted": False},
                    {"name": "origin", "fetch": "https://github.com/AIOSAI/AIPass.git", "redacted": False},
                ]
            )
        )

        answer = host_git.read_git_remote("demo")

        assert answer["remote"] == "origin"
        assert "AIPass" in answer["url"]

    def test_without_an_origin_the_first_one_answers_and_is_named(self, remote_repo: dict) -> None:
        """No origin is not an error; the `remote` field keeps the fallback visible."""
        remote_repo["serve"](remote_document("https://github.com/other/thing.git", name="upstream"))

        answer = host_git.read_git_remote("demo")

        assert answer["remote"] == "upstream"
        assert answer["web"] == "https://github.com/other/thing"

    def test_a_push_only_remote_still_answers(self, remote_repo: dict) -> None:
        """The door reports fetch and push separately; push-only is unusual, not broken."""
        remote_repo["serve"](
            remotes_document([{"name": "origin", "push": "https://github.com/AIOSAI/AIPass.git", "redacted": False}])
        )

        assert host_git.read_git_remote("demo")["web"] == "https://github.com/AIOSAI/AIPass"

    def test_a_repository_with_no_remote_answers_the_same_shape_with_null_links(self, remote_repo: dict) -> None:
        """Contract C-D: no remote is a fact about the repository, never a refusal."""
        configured = host_git.read_git_remote("demo")
        remote_repo["serve"](remotes_document([]))

        answer = host_git.read_git_remote("demo")

        assert set(answer) == set(configured)
        assert answer == {
            "branch": "demo",
            "grain": "repo",
            "remote": None,
            "url": None,
            "web": None,
            "redacted": False,
        }

    def test_a_remote_carrying_no_url_is_refused_rather_than_served_empty(self, remote_repo: dict) -> None:
        """A named remote with nothing to point at is a link card to nowhere."""
        remote_repo["serve"](remotes_document([{"name": "origin", "fetch": "", "push": "", "redacted": False}]))

        with pytest.raises(host_reads.ReadRefused):
            host_git.read_git_remote("demo")

    def test_a_refusing_door_travels_in_its_own_words(self, remote_repo: dict) -> None:
        """git said no; that sentence is theirs and arrives unrewritten."""
        remote_repo["serve"](
            json.dumps({"ok": False, "remotes": [], "count": 0, "message": "git remote error: not a repository"}),
            returncode=1,
        )

        with pytest.raises(host_reads.ReadRefused) as caught:
            host_git.read_git_remote("demo")

        assert "not a repository" in str(caught.value)

    def test_a_door_that_leaves_no_document_is_unavailable_not_refused(self, remote_repo: dict) -> None:
        """drone's caller check leaves no stdout: a 503 carrying their sentence, never "no remote"."""
        remote_repo["serve"]("", returncode=1, stderr="cannot verify caller")

        with pytest.raises(host_reads.ReadUnavailable) as caught:
            host_git.read_git_remote("demo")

        assert "cannot verify caller" in str(caught.value)

    def test_this_lane_routes_through_drone_like_every_other(self, remote_repo: dict) -> None:
        """Git is drone-only, servers included, and asked in machine mode (--json)."""
        host_git.read_git_remote("demo")

        command = remote_repo["runner"].call_args[0][0]

        assert command[:3] == ["drone", "@git", "remote"]
        assert "--json" in command

    def test_it_runs_in_the_branch_directory(self, remote_repo: dict) -> None:
        """Exactly as an operator standing in that branch would run it."""
        host_git.read_git_remote("demo")

        assert remote_repo["runner"].call_args.kwargs["cwd"] == str(remote_repo["branch"].resolve())


class TestRemoteURLForms:
    """Every shape a remote is written in; the ssh forms are pinned before anyone clones over ssh."""

    def _web(self, remote_repo: dict, url: str) -> Any:
        remote_repo["serve"](remote_document(url))
        return host_git.read_git_remote("demo")["web"]

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
        """ssh has no browsable form so converting it is forced; http has one, so it stays."""
        assert self._web(remote_repo, "http://internal.example/o/r.git") == "http://internal.example/o/r"

    def test_a_local_path_remote_has_no_web_form_and_says_so(self, remote_repo: dict, tmp_path: Path) -> None:
        """A directory is not a web page; `None` is the honest answer."""
        mirror = str(tmp_path / "mirrors" / "aipass.git")
        remote_repo["serve"](remote_document(mirror))

        answer = host_git.read_git_remote("demo")

        assert answer["web"] is None
        assert answer["url"] == mirror

    def test_a_relative_path_remote_has_no_web_form_either(self, remote_repo: dict) -> None:
        """`../sibling` is a path however few slashes it has."""
        assert self._web(remote_repo, "../sibling-repo") is None

    def test_a_windows_path_is_not_mistaken_for_the_scp_form(self, remote_repo: dict) -> None:
        """THE TRAP: `C:\\repos\\thing` has a colon like `host:path`; read as scp it names a host C."""
        assert self._web(remote_repo, "C:\\repos\\thing") is None


class TestRemoteCredentialsNeverTravel:
    """
    THE DOCTRINE THAT OUTLIVED THE MODULE THAT CARRIED IT.

    A remote URL may carry `user:token@`. drone redacts too; these assert what THIS surface
    emits regardless, since it is the last process before the network.
    """

    # Generated per run: a token-shaped literal trips secret scanners.
    SECRET = f"ghp_{secrets.token_hex(8)}"
    WITH_SECRET = f"https://aiosai:{SECRET}@github.com/AIOSAI/AIPass.git"

    def test_a_password_in_the_url_is_redacted(self, remote_repo: dict) -> None:
        """The secret never leaves this process, in any field."""
        remote_repo["serve"](remote_document(self.WITH_SECRET))

        answer = host_git.read_git_remote("demo")

        assert self.SECRET not in json.dumps(answer)

    def test_the_secret_is_stripped_even_when_upstream_says_it_already_did(self, remote_repo: dict) -> None:
        """A door reporting `redacted: true` while still carrying the token is not taken at its word."""
        remote_repo["serve"](remote_document(self.WITH_SECRET, redacted=True))

        answer = host_git.read_git_remote("demo")

        assert self.SECRET not in json.dumps(answer)
        assert answer["redacted"] is True

    def test_a_token_with_no_user_is_redacted_and_announced(self, remote_repo: dict) -> None:
        """`https://<token>@host` is how a token rides with no password half; it is the whole secret."""
        remote_repo["serve"](remote_document(f"https://{self.SECRET}@github.com/AIOSAI/AIPass.git"))

        answer = host_git.read_git_remote("demo")

        assert self.SECRET not in json.dumps(answer)
        assert answer["redacted"] is True
        assert answer["url"] == "https://***@github.com/AIOSAI/AIPass.git"

    def test_the_redaction_is_announced_never_silent(self, remote_repo: dict) -> None:
        """An operator comparing this to their configuration must see that it was changed."""
        remote_repo["serve"](remote_document(self.WITH_SECRET))

        assert host_git.read_git_remote("demo")["redacted"] is True

    def test_a_clean_url_is_not_flagged_as_redacted(self, remote_repo: dict) -> None:
        """A flag that is always true says nothing at all."""
        assert host_git.read_git_remote("demo")["redacted"] is False

    def test_upstreams_own_verdict_survives_even_when_nothing_is_left_to_strip(self, remote_repo: dict) -> None:
        """If drone already replaced the secret, our no-op pass must not un-announce their verdict."""
        remote_repo["serve"](remote_document("https://***@github.com/AIOSAI/AIPass.git", redacted=True))

        assert host_git.read_git_remote("demo")["redacted"] is True

    def test_the_url_keeps_its_shape_so_it_is_still_recognisable(self, remote_repo: dict) -> None:
        """Redacted, not deleted — the operator should still know which remote this is."""
        remote_repo["serve"](remote_document(self.WITH_SECRET))

        answer = host_git.read_git_remote("demo")

        assert "aiosai" in answer["url"]
        assert "github.com/AIOSAI/AIPass" in answer["url"]

    def test_the_web_form_carries_no_user_at_all(self, remote_repo: dict) -> None:
        """A browsable link needs no identity in it, so it is given none."""
        remote_repo["serve"](remote_document(self.WITH_SECRET))

        answer = host_git.read_git_remote("demo")

        assert answer["web"] == "https://github.com/AIOSAI/AIPass"
        assert "@" not in answer["web"]

    def test_the_ssh_user_is_not_a_credential(self, remote_repo: dict) -> None:
        """`git@github.com` carries the standard ssh user and no secret."""
        remote_repo["serve"](remote_document("git@github.com:AIOSAI/AIPass.git"))

        assert host_git.read_git_remote("demo")["redacted"] is False

    def test_the_ssh_user_is_not_a_credential_in_the_explicit_form_either(self, remote_repo: dict) -> None:
        """
        THE ONE THAT ACTUALLY REACHES THE RULE: the scp form has no `://` and skips the bare-user check;
        `ssh://git@` has a scheme AND a colonless user.
        """
        remote_repo["serve"](remote_document("ssh://git@github.com/AIOSAI/AIPass.git"))

        answer = host_git.read_git_remote("demo")

        assert answer["redacted"] is False
        assert answer["url"] == "ssh://git@github.com/AIOSAI/AIPass.git"


class TestTheRemoteLaneReadsNoConfiguration:
    """
    No .git/config parse and no worktree pointer-following: git resolves commondir itself.
    """

    def test_a_worktree_needs_nothing_special_from_this_side(self, tmp_path: Path) -> None:
        """A branch whose .git is a FILE: the door answers for it like any other."""
        tree = tmp_path / "Tree"
        branch = tree / "src" / "aipass" / "demo"
        branch.mkdir(parents=True)
        (tree / ".git").write_text("gitdir: %s\n" % (tmp_path / "Main" / ".git" / "worktrees" / "wt"), encoding="utf-8")

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

        completed = MagicMock()
        completed.stdout = remote_document("https://github.com/AIOSAI/AIPass.git")
        completed.stderr = ""
        completed.returncode = 0

        with (
            patch(PATCH_READS_DRONE, fake_drone),
            patch(PATCH_READS_LOGGER),
            patch(PATCH_READS_JSON),
            patch(PATCH_GIT_LOGGER),
            patch(PATCH_GIT_JSON),
            patch.object(subprocess, "run", return_value=completed),
        ):
            answer = host_git.read_git_remote("demo")

        assert answer["web"] == "https://github.com/AIOSAI/AIPass"

    def test_a_repository_configuration_is_never_opened(self, remote_repo: dict) -> None:
        """Watched via Path.open, not the source: a second resolution can be spelled any way."""
        opened = []
        real_open = Path.open

        def watched(self: Path, *args: Any, **kwargs: Any) -> Any:
            opened.append(str(self))
            return real_open(self, *args, **kwargs)

        with patch.object(Path, "open", watched):
            host_git.read_git_remote("demo")

        assert opened == []


class TestWhichRepositoryADirectoryIsIn:
    """repository_of(), pinned directly since the change list and the remote lane both lean on it."""

    def test_the_nearest_ancestor_carrying_the_marker_wins(self, tmp_path) -> None:
        """Not the outermost repository — the one this directory actually sits in."""
        outer = tmp_path / "outer"
        inner = outer / "vendor" / "inner"
        deep = inner / "src" / "aipass" / "api"
        deep.mkdir(parents=True)
        (outer / ".git").mkdir()
        (inner / ".git").mkdir()

        assert host_reads.repository_of(deep) == inner

    def test_a_marker_that_is_a_file_still_counts(self, tmp_path) -> None:
        """A worktree keeps a file where a clone keeps a directory; is_dir() would miss it."""
        worktree = tmp_path / "checked-out-elsewhere"
        inside = worktree / "src"
        inside.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")

        assert host_reads.repository_of(inside) == worktree

    def test_no_repository_above_it_answers_none_not_a_guess(self, tmp_path) -> None:
        """Absent is a real answer here; callers branch on it rather than assume."""
        loose = tmp_path / "just" / "some" / "directories"
        loose.mkdir(parents=True)

        assert host_reads.repository_of(loose) is None

    def test_a_directory_that_is_itself_the_repository_answers_itself(self, tmp_path) -> None:
        """The walk starts at the directory, not at its parent."""
        repository = tmp_path / "seat"
        repository.mkdir()
        (repository / ".git").mkdir()

        assert host_reads.repository_of(repository) == repository
