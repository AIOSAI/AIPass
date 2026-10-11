# =================== AIPass ====================
# Name: test_host_read_lane_history.py
# Description: Tests for the read lane's per-file diff, commit patch, log, commit detail and remote link-cards
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for read_diff, read_git_log, read_commit and read_git_remote in apps/handlers/host/git_reads.py."""

# Split out of test_host_read_lane.py along the unit under test (api, the
# oversize split leg, 2026-10-08): the per-file diff and the commit patch
# (one splitter), the log, a commit's detail, the remote and its URL forms,
# credentials and configuration, and repository_of(). The whole-diff lane and
# the routes stay in test_host_read_lane.py; the git-changes lane is in
# test_host_read_lane_changes.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — drone's own diff, show, log and remote output; subprocess.run is faked here

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

# The patch targets stay this file's own constants rather than conftest's:
# seedgo's discarded_patch rule reads a target imported from this branch's
# package as one it judges, and the loggers are silenced on purpose.
PATCH_READS_LOGGER = "aipass.api.apps.handlers.host.reads.logger"
PATCH_READS_JSON = "aipass.api.apps.handlers.host.reads.json_handler"
PATCH_READS_DRONE = "aipass.api.apps.handlers.host.reads.drone"
PATCH_GIT_LOGGER = "aipass.api.apps.handlers.host.git_reads.logger"
PATCH_GIT_JSON = "aipass.api.apps.handlers.host.git_reads.json_handler"


class TestPerFileDiff:
    """
    The owner's words: "git diffs are pretty much useless. we need a real diff
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
            result = host_git.read_diff("demo", path="src/aipass/demo/hello.txt")

        assert "hello world" in result["diff"]
        assert "thing.py" not in result["diff"]

    def test_the_patch_keeps_its_own_file_header(self, fake_repo: dict) -> None:
        """
        react-diff-view's parseDiff() reads the header to know the filename and
        the change kind. Handing it a bare hunk would strip the file's identity.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_diff("demo", path="src/aipass/other/thing.py")

        assert result["diff"].startswith("diff --git a/src/aipass/other/thing.py")
        assert "@@" in result["diff"]

    def test_the_answer_names_the_path_it_answered_for(self, fake_repo: dict) -> None:
        """The response says which file it is, never leaving it to be inferred."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_diff("demo", path="src/aipass/demo/hello.txt")

        assert result["path"] == "src/aipass/demo/hello.txt"

    def test_no_path_returns_the_whole_diff_unchanged(self, fake_repo: dict) -> None:
        """The live lane keeps its contract — the phone reads it right now."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_diff("demo")

        assert result["diff"] == TWO_FILE_DIFF
        assert result["path"] == ""

    def test_a_file_with_no_changes_is_refused_in_words(self, fake_repo: dict) -> None:
        """
        An empty string would read as "no changes rendered fine". A tap on a
        stale list is a real event and it gets a real sentence.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_diff("demo", path="src/aipass/demo/never_touched.py")

        assert "never_touched.py" in str(caught.value)

    def test_a_near_miss_name_does_not_match(self, fake_repo: dict) -> None:
        """
        Matching on the header's exact path, not a substring — otherwise
        "hello.txt" would answer for "other_hello.txt" and the phone would show
        a diff belonging to a different file.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_diff("demo", path="demo/hello.txt")

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
            * host_git.MAX_DIFF_BYTES
        )

        with patch.object(subprocess, "run", return_value=self._completed(huge)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_diff("demo", path="src/aipass/demo/big.txt")

        assert str(host_git.MAX_DIFF_BYTES) in str(caught.value)

    def test_a_file_block_is_copied_once_not_once_per_line(self, fake_repo: dict, monkeypatch: Any) -> None:
        """
        The per-file split pins its COST, never a clock: growing a block by one
        line per pass copied it once per line, so a diff at the size limit took
        85s alone (api, fleet green leg 3). One join per block, whatever its length.
        Mutant that reddens it: a join per line (the quadratic shape with the seam kept).
        WHAT IT CANNOT SEE: it counts joins, not copies. A block list copied once
        per line (blocks[-1] = blocks[-1] + [line]) joins once and passes while
        as quadratic as the string was; with no clock and no threshold nothing
        here observes that copy (api, fleet green leg 4).
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

        with patch.object(subprocess, "run", return_value=self._completed(patch_text)):
            answer = host_git.read_diff("demo", path="src/aipass/demo/two.txt")

        assert joins == [504, 504], "one join per file block, each over the whole block"
        assert answer["diff"].count("+x\n") == 500

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
            result = host_git.read_diff("demo", path="doc.md")

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
            result = host_git.read_diff("demo", path="img/logo.png")

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
            result = host_git.read_diff("demo", path="odd b/name.bin")

        assert "Binary files differ" in result["diff"]

    def test_repo_grain_diff_asks_for_the_whole_repo(self, fake_repo: dict) -> None:
        """The app's file list is repo grain, so its taps must be too."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_diff("demo", path="src/aipass/other/thing.py", grain="repo")

        assert "--all" in mock_run.call_args[0][0]

    def test_an_unknown_grain_is_refused_here_too(self, fake_repo: dict) -> None:
        """One vocabulary across the lanes, one refusal for breaking it."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_diff("demo", grain="sideways")

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
            host_git.read_diff("demo", ref="7edf8c2d")

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
        """
        Silently ignoring a parameter is a lie told by omission. A caller who
        asked for branch scope on a commit gets told why it cannot exist.
        """
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
        """
        A leading dash would be read as an option, not a commit. Garbage is
        refused before a subprocess exists, never argued with afterwards.
        """
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
        """
        The fence must not become a wall: HEAD~3 and a branch path are the
        names an operator actually types.
        """
        for ref in ("HEAD", "HEAD~3", "HEAD^", "work/api", "v1.2.3", "b47462b7"):
            with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
                host_git.read_diff("demo", ref=ref)

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
            host_git.read_git_log("demo")

        assert mock_run.call_args[0][0][:2] == ["drone", "@git"]

    def test_each_entry_splits_sha_from_subject(self, fake_repo: dict) -> None:
        """
        --oneline is a sha, one space, then a subject that may contain any
        number more. Splitting once is what keeps a colon-heavy message intact.
        """
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
        """
        A commit is identified by its object name, and a row without one names
        nothing a caller could ever ask for again. Passing it through would put
        an untappable entry in the phone's history — the document equivalent of
        the phantom commit the old rendered lane guarded against.
        """
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
        """
        drone's log runs from find_repo_root() with no pathspec, so this is the
        REPO's history even though a branch named the anchor. Reporting branch
        grain here would be a straight lie.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_log("demo")

        assert result["grain"] == "repo"

    def test_the_limit_reaches_drone(self, fake_repo: dict) -> None:
        """The cap is enforced at the door, not by trimming a longer answer here."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_log("demo", limit=5)

        assert "5" in mock_run.call_args[0][0]

    def test_a_limit_over_the_cap_is_refused_naming_it(self, fake_repo: dict) -> None:
        """
        Clamping silently would hand back 50 rows to a caller who asked for 500
        and let them believe that was all the history there is.
        """
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
        """
        An empty commit list would read as a repository with no history. No
        document at all is the shape drone's caller-verification refusal takes,
        because that one never reaches the door — so it is a 503, not a repo
        that has never been committed to.
        """
        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_log("demo")

    def test_prose_is_not_a_commit_list_it_is_a_could_not_tell(self, fake_repo: dict) -> None:
        """
        THE OLD GUARD, STRENGTHENED. This lane used to read rendered lines and
        had to check each one led with a hex sha, so a header drone might add
        could not become a phantom commit. A document has no framing to
        mistake — and output that is not a document is not a thin commit list,
        it is nobody being able to tell, which is a 503.
        """
        rendered = "Recent commits in the repository:\nb47462b7 feat(fleet): the newest one"

        with patch.object(subprocess, "run", return_value=self._completed(rendered)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_log("demo")

    def test_a_refusal_document_is_an_answer_not_a_breakdown(self, fake_repo: dict) -> None:
        """
        drone reached git and git said no. That is the CALLER learning
        something true about their repository — a 400 in drone's own words —
        and reporting it as a 503 would tell them to try again later for
        something that will never change.
        """
        refusal = json.dumps({"ok": False, "commits": [], "count": 0, "message": "git log error: bad revision"})

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_git_log("demo")

        assert "bad revision" in str(caught.value)


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
            host_git.read_commit("demo", ref="7edf8c2d")

        assert mock_run.call_args[0][0][:2] == ["drone", "@git"]

    def test_the_author_and_date_come_from_the_header(self, fake_repo: dict) -> None:
        """
        The fields the log door cannot give. show carries them, which is why
        detail is a separate lane rather than a richer list.
        """
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
        """
        show indents the message by four spaces for display. Passing that
        through would paint every commit body as a code block on the phone.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert "And a second paragraph of body." in result["message"]
        assert "\n    And a second" not in result["message"]

    def test_the_files_carry_plus_and_minus_counts(self, fake_repo: dict) -> None:
        """
        The stat line every git surface shows. Counted from the patch's own
        plus and minus line starts, which is structure: a space-prefixed context
        line counts as neither, which the exact counts here hold (its own test
        retired as a duplicate of this one, api, fleet green leg 8).
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

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
            result = host_git.read_commit("demo", ref="7edf8c2d")

        total = sum(row["additions"] + row["deletions"] for row in result["files"])
        assert total == 5

    def test_count_agrees_with_the_file_list(self, fake_repo: dict) -> None:
        """One number, derived."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert result["count"] == len(result["files"]) == 2

    def test_the_whole_patch_is_not_shipped_in_the_detail(self, fake_repo: dict) -> None:
        """
        The detail lane is metadata plus a stat list. The patch is the diff
        lane's job, per file, precisely so a phone never loads a whole commit.
        """
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
        """
        MEASURED, 2026-08-18: the real door answers a bad revision with a
        DOCUMENT — ok false, git's fatal in the message, exit 1. So this is a
        400 now and not a 503: the caller named something that is not in this
        repository, which is a fact about their request, not about this server.
        """
        refusal = show_document("", ref="deadbeef", ok=False, message="git show error: fatal: bad object deadbeef")

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_commit("demo", ref="deadbeef")

        assert "bad object" in str(caught.value)

    def test_a_door_that_leaves_no_document_is_still_a_503(self, fake_repo: dict) -> None:
        """
        The other half of the split, and the one that keeps a foreign project
        honest: drone's caller check refuses before the door runs and puts its
        sentence on stderr with nothing on stdout. Nobody could tell, so nobody
        claims to.
        """
        failed = self._completed(stdout="", returncode=1, stderr="cannot verify caller")

        with patch.object(subprocess, "run", return_value=failed):
            with pytest.raises(host_reads.ReadUnavailable) as caught:
                host_git.read_commit("demo", ref="deadbeef")

        assert "cannot verify caller" in str(caught.value)

    def test_a_commit_that_changed_nothing_is_still_a_commit(self, fake_repo: dict) -> None:
        """
        An empty or merge commit has a header and no patch. Zero files is the
        honest answer, not a refusal and not a crash.
        """
        header_only = show_document("\n".join(GIT_SHOW_TEXT.splitlines()[:6]) + "\n")

        with patch.object(subprocess, "run", return_value=self._completed(header_only)):
            result = host_git.read_commit("demo", ref="7edf8c2d")

        assert result["files"] == []
        assert result["count"] == 0


# =============================================
# THE REMOTE — link-cards out to the forge
# =============================================


class TestGitRemote:
    """
    Phase 4 wants link-cards out to the forge, zero-auth, from constructible
    URLs — so the face needs to be told the repository's remote.

    THE DOOR ARRIVED, 2026-08-18. When this lane was built there was none: not
    a verb on drone's git surface, not on their public Python surface, and the
    fleet gate refused both raw readers. So it read the repository's INI
    configuration directly and followed worktree pointers by hand — the one
    lane in this package that shelled nothing, kept in its own module so that
    boundary stayed visible. `drone @git remote --json` retired all of it. The
    lane now lives with the other drone-door readers and the old module is
    archived beside them, which is why every test below drives a door.
    """

    def test_the_configured_remote_comes_back(self, remote_repo: dict) -> None:
        """The whole point of the lane."""
        answer = host_git.read_git_remote("demo")

        assert answer["url"] == "https://github.com/AIOSAI/AIPass.git"

    def test_the_browsable_form_drops_the_dot_suffix(self, remote_repo: dict) -> None:
        """
        What the face actually links. `/pulls` appended to a URL ending in the
        clone suffix is a 404 on every forge there is.
        """
        answer = host_git.read_git_remote("demo")

        assert answer["web"] == "https://github.com/AIOSAI/AIPass"

    def test_the_configured_url_is_never_rewritten(self, remote_repo: dict) -> None:
        """
        Two fields, two jobs: `url` is what the repository actually says, `web`
        is what a person can open. Collapsing them would leave an operator
        unable to compare this answer to their own configuration.
        """
        answer = host_git.read_git_remote("demo")

        assert answer["url"].endswith(".git")
        assert not answer["web"].endswith(".git")

    def test_it_names_which_remote_answered(self, remote_repo: dict) -> None:
        """A card labelled with the wrong remote's URL is worse than no card."""
        assert host_git.read_git_remote("demo")["remote"] == "origin"

    def test_a_remote_is_a_repository_fact_and_says_so(self, remote_repo: dict) -> None:
        """
        Same vocabulary as the log and commit lanes: the branch names WHICH
        repository, never a scope inside one.
        """
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
        """
        Refusing a repository that simply named its remote something else would
        be this lane inventing a rule that does not exist. It answers, and the
        `remote` field is what stops that being a guess the caller cannot see.
        """
        remote_repo["serve"](remote_document("https://github.com/other/thing.git", name="upstream"))

        answer = host_git.read_git_remote("demo")

        assert answer["remote"] == "upstream"
        assert answer["web"] == "https://github.com/other/thing"

    def test_a_push_only_remote_still_answers(self, remote_repo: dict) -> None:
        """
        The door reports fetch and push separately. A remote carrying only the
        second one is unusual, not broken, and refusing it would hide a real
        repository behind a shape assumption.
        """
        remote_repo["serve"](
            remotes_document([{"name": "origin", "push": "https://github.com/AIOSAI/AIPass.git", "redacted": False}])
        )

        assert host_git.read_git_remote("demo")["web"] == "https://github.com/AIOSAI/AIPass"

    def test_a_repository_with_no_remote_is_refused_in_words(self, remote_repo: dict) -> None:
        """
        NOT hypothetical: projects in the real tree have none at all. An empty
        string would render as a link card pointing nowhere.
        """
        remote_repo["serve"](remotes_document([]))

        with pytest.raises(host_reads.ReadRefused) as caught:
            host_git.read_git_remote("demo")

        assert "remote" in str(caught.value)

    def test_a_remote_carrying_no_url_is_refused_rather_than_served_empty(self, remote_repo: dict) -> None:
        """A named remote with nothing to point at is a link card to nowhere."""
        remote_repo["serve"](remotes_document([{"name": "origin", "fetch": "", "push": "", "redacted": False}]))

        with pytest.raises(host_reads.ReadRefused):
            host_git.read_git_remote("demo")

    def test_a_refusing_door_travels_in_its_own_words(self, remote_repo: dict) -> None:
        """
        D0. drone reached git and git said no; that sentence is theirs and it
        arrives unrewritten, because this server owns the pipe and not the
        meaning.
        """
        remote_repo["serve"](
            json.dumps({"ok": False, "remotes": [], "count": 0, "message": "git remote error: not a repository"}),
            returncode=1,
        )

        with pytest.raises(host_reads.ReadRefused) as caught:
            host_git.read_git_remote("demo")

        assert "not a repository" in str(caught.value)

    def test_a_door_that_leaves_no_document_is_unavailable_not_refused(self, remote_repo: dict) -> None:
        """
        drone's caller check refuses before the door runs, with nothing on
        stdout and the reason on stderr. Nobody could tell — so this is a 503
        and it carries their sentence rather than inventing "no remote".
        """
        remote_repo["serve"]("", returncode=1, stderr="cannot verify caller")

        with pytest.raises(host_reads.ReadUnavailable) as caught:
            host_git.read_git_remote("demo")

        assert "cannot verify caller" in str(caught.value)

    def test_this_lane_routes_through_drone_like_every_other(self, remote_repo: dict) -> None:
        """
        THE DOCTRINE PIN, INVERTED BY THE DOOR ARRIVING. It used to read that no
        subprocess was ever spawned here, because there was nothing to spawn.
        Now "git is drone-only, servers included" means this lane must go
        through drone exactly like the rest — and ask in machine mode, because
        a rendered answer is the thing this round was spent getting away from.
        """
        host_git.read_git_remote("demo")

        command = remote_repo["runner"].call_args[0][0]

        assert command[:3] == ["drone", "@git", "remote"]
        assert "--json" in command

    def test_it_runs_in_the_branch_directory(self, remote_repo: dict) -> None:
        """Exactly as an operator standing in that branch would run it."""
        host_git.read_git_remote("demo")

        assert remote_repo["runner"].call_args.kwargs["cwd"] == str(remote_repo["branch"].resolve())


class TestRemoteURLForms:
    """
    Every shape a remote is written in. The seat and its siblings all use https
    today — measured across seven real repositories — so the ssh forms are
    pinned here rather than discovered the day somebody clones over ssh.
    """

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
        """
        Turning a configured `http` into `https` would be this lane deciding
        something about somebody's host that it cannot know. ssh has no
        browsable form of its own so converting it is forced; http has one.
        """
        assert self._web(remote_repo, "http://internal.example/o/r.git") == "http://internal.example/o/r"

    def test_a_local_path_remote_has_no_web_form_and_says_so(self, remote_repo: dict, tmp_path: Path) -> None:
        """
        A directory is not a web page. `None` is the honest answer — a
        constructed scheme in front of a filesystem path would be a link card
        leading somewhere that has never existed.
        """
        mirror = str(tmp_path / "mirrors" / "aipass.git")
        remote_repo["serve"](remote_document(mirror))

        answer = host_git.read_git_remote("demo")

        assert answer["web"] is None
        assert answer["url"] == mirror

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
    THE DOCTRINE THAT OUTLIVED THE MODULE THAT CARRIED IT.

    A remote URL may carry `user:token@` — that is how a machine clones a
    private repository without an agent — and this lane's entire job is to hand
    that URL to a client over the network.

    drone redacts on their side too, and these tests do not re-test that. Every
    assertion here is about what THIS surface emits when handed a credentialed
    URL, whatever upstream did or did not do with it first: a rule enforced
    only by somebody else's code is a rule that leaves silently the day their
    code changes, and this process is the last one a URL passes through before
    it crosses a network.
    """

    # Generated per run rather than written down: the proof is that whatever
    # token is handed in does not come back out, which a literal can only claim
    # for its own value — and a token-shaped literal trips secret scanners.
    SECRET = f"ghp_{secrets.token_hex(8)}"
    WITH_SECRET = f"https://aiosai:{SECRET}@github.com/AIOSAI/AIPass.git"

    def test_a_password_in_the_url_is_redacted(self, remote_repo: dict) -> None:
        """The secret never leaves this process, in any field."""
        remote_repo["serve"](remote_document(self.WITH_SECRET))

        answer = host_git.read_git_remote("demo")

        assert self.SECRET not in json.dumps(answer)

    def test_the_secret_is_stripped_even_when_upstream_says_it_already_did(self, remote_repo: dict) -> None:
        """
        THE PIN THE ARCHIVED MODULE HANDED OVER. A door that reports
        `redacted: true` while still carrying the token is a door this server
        must not take at its word — the answer is the only evidence, so the
        answer is what is asserted.
        """
        remote_repo["serve"](remote_document(self.WITH_SECRET, redacted=True))

        answer = host_git.read_git_remote("demo")

        assert self.SECRET not in json.dumps(answer)
        assert answer["redacted"] is True

    def test_the_redaction_is_announced_never_silent(self, remote_repo: dict) -> None:
        """
        An operator comparing this answer to their own configuration must be
        able to see that it was changed, or they will chase a phantom mismatch.
        """
        remote_repo["serve"](remote_document(self.WITH_SECRET))

        assert host_git.read_git_remote("demo")["redacted"] is True

    def test_a_clean_url_is_not_flagged_as_redacted(self, remote_repo: dict) -> None:
        """A flag that is always true says nothing at all."""
        assert host_git.read_git_remote("demo")["redacted"] is False

    def test_upstreams_own_verdict_survives_even_when_nothing_is_left_to_strip(self, remote_repo: dict) -> None:
        """
        If drone already replaced the secret, this lane finds nothing to do —
        and must still report that the URL was changed. Dropping their verdict
        because our own pass was a no-op would silently un-announce it.
        """
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
        """
        `git@github.com` carries the standard ssh user and no secret. Flagging
        it would cry wolf on the single commonest remote form there is, and an
        alarm that fires on everything is an alarm nobody reads. drone draws
        the same line on their side, independently — this asserts ours.
        """
        remote_repo["serve"](remote_document("git@github.com:AIOSAI/AIPass.git"))

        assert host_git.read_git_remote("demo")["redacted"] is False

    def test_the_ssh_user_is_not_a_credential_in_the_explicit_form_either(self, remote_repo: dict) -> None:
        """
        THE ONE THAT ACTUALLY REACHES THE RULE. The scp short form carries no
        `://` and leaves the redactor at its first line, so it never exercises
        the bare-user check at all — a mutation flagging every userinfo as a
        secret survived the whole suite until this case existed. `ssh://git@`
        has a scheme AND a colonless user, which is the only shape that does.
        """
        remote_repo["serve"](remote_document("ssh://git@github.com/AIOSAI/AIPass.git"))

        answer = host_git.read_git_remote("demo")

        assert answer["redacted"] is False
        assert answer["url"] == "ssh://git@github.com/AIOSAI/AIPass.git"


class TestTheRemoteLaneReadsNoConfiguration:
    """
    WHAT THE ARCHIVED MODULE USED TO DO, pinned as something that must not come
    back.

    It parsed .git/config as an INI file and followed worktree pointer files by
    hand to find the right one — necessary when there was no door, and a second
    implementation of git's own resolution the moment there was. git resolves
    commondir itself, so a worktree needs nothing special from this side now.

    A file read reappearing here would be that resolution growing back quietly,
    which is why the pin is on the behaviour rather than on the source.
    """

    def test_a_worktree_needs_nothing_special_from_this_side(self, tmp_path: Path) -> None:
        """
        The case that used to need pointer-following: a branch whose .git is a
        FILE. The door answers for it like any other, because git resolved it.
        """
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
        """
        The INI parse is gone and stays gone. Asserted by watching Path.open
        across the whole call rather than by reading the source, because a
        second resolution can be written with any spelling at all.
        """
        opened = []
        real_open = Path.open

        def watched(self: Path, *args: Any, **kwargs: Any) -> Any:
            opened.append(str(self))
            return real_open(self, *args, **kwargs)

        with patch.object(Path, "open", watched):
            host_git.read_git_remote("demo")

        assert opened == []


class TestWhichRepositoryADirectoryIsIn:
    """
    repository_of() — private until the split, public now that both halves ask.

    It is the answer the change list strips row paths against and the answer the
    remote lane looks for a configuration beside, so it gets pinned directly
    rather than only through the two lanes that lean on it.
    """

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
        """
        A worktree keeps a file where a clone keeps a directory.

        Checking is_dir() here would read every worktree as "not a repository"
        and silently un-strip every path inside it — the shape that has already
        bitten one lane on this surface.
        """
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
