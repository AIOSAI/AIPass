# =================== AIPass ====================
# Name: test_git_json_and_remote.py
# Description: Machine output on the git read doors, the remote read door, the gh passthrough tiers and merge-main
# Version: 1.0.4
# Created: 2026-08-18
# Modified: 2026-10-01
# =============================================

"""Tests for apps/modules/git_module.py's --json on status/log/show and apps/handlers/git/remote_handler.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.dumps' own encoding of the documents

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.handlers.json_flags import JSON_FLAG, strip_json_flag, wants_json
from aipass.drone.apps.handlers.git import blame_handler, log_handler, remote_handler
from aipass.drone.apps.handlers.git.status_handler import get_branch_status
from aipass.drone.apps.modules.git_module import get_help, handle_command
from aipass.drone.apps.plugins.devpulse_ops.auth import GH_SUBCOMMANDS, GIT_ACCESS_TIERS, gh_access_key

# FPLAN-0438 round 4a, the two door asks from @api's boundary assessment.
# ASK 1: --json on status / log / show, so a consumer reads a document instead
# of scraping a rendered sentence.
# ASK 2: drone @git remote, a door that did not exist, which is why @api parsed
# .git/config as an INI file with its own worktree-following.
# Every prose assertion here is a REGRESSION PIN: the asks were explicitly
# additive, so the desktop and every current caller must keep reading exactly
# the bytes they read before.

_GIT_MOD = "aipass.drone.apps.modules.git_module"
_AUTH = "aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access"
_STATUS_MOD = "aipass.drone.apps.handlers.git.status_handler"
_REMOTE_MOD = "aipass.drone.apps.handlers.git.remote_handler"


# ===========================================================================
# 1. The flag predicate — position-agnostic, stripped, outranked by help
# ===========================================================================


class TestJsonFlag:
    """--json rides in any slot and never survives into positional parsing."""

    @pytest.mark.parametrize(
        "args",
        [[JSON_FLAG], ["20", JSON_FLAG], [JSON_FLAG, "20"], ["--all", JSON_FLAG, "x"]],
    )
    def test_detected_in_any_slot(self, args: list[str]) -> None:
        assert wants_json(args) is True

    @pytest.mark.parametrize("args", [[], ["20"], ["--all"], ["json"], ["-json"]])
    def test_absent_is_false(self, args: list[str]) -> None:
        """No bare `json` form — it is plausible free text and would swallow a value."""
        assert wants_json(args) is False

    def test_none_is_false(self) -> None:
        assert wants_json(None) is False

    def test_strip_removes_every_occurrence(self) -> None:
        assert strip_json_flag(["a", JSON_FLAG, "b", JSON_FLAG]) == ["a", "b"]

    def test_strip_returns_new_list(self) -> None:
        original = ["a", JSON_FLAG]
        assert strip_json_flag(original) is not original
        assert original == ["a", JSON_FLAG]


# ===========================================================================
# 2. The status code collapse — the bug the door exposed
# ===========================================================================


def _status_run(porcelain: str) -> MagicMock:
    return MagicMock(returncode=0, stdout=porcelain, stderr="")


class TestStatusCodeFidelity:
    """The two porcelain columns are index then worktree — two different facts.

    ``M `` (staged modification) and `` M`` (unstaged modification) were BOTH
    reduced to ``M`` by the handler's ``line[:2].strip()``, so every consumer
    downstream read a staged change as an unstaged one. Measured, not assumed.
    """

    PORCELAIN = "M  a.txt\n M b.txt\nA  c.txt\nMM d.txt\n?? e.txt\n"

    def _files(self, tmp_path: Path) -> list[dict]:
        with patch(f"{_STATUS_MOD}.subprocess.run", return_value=_status_run(self.PORCELAIN)):
            with patch(f"{_STATUS_MOD}.find_repo_root", return_value=tmp_path):
                return get_branch_status(tmp_path)["files"]

    def test_staged_and_unstaged_modification_stay_distinct(self, tmp_path: Path) -> None:
        """The exact collapse: two different facts must not become one answer."""
        codes = [f["status"] for f in self._files(tmp_path)]
        assert codes[0] == "M "
        assert codes[1] == " M"
        assert codes[0] != codes[1]

    def test_code_is_the_verbatim_two_columns(self, tmp_path: Path) -> None:
        assert [f["status"] for f in self._files(tmp_path)] == ["M ", " M", "A ", "MM", "??"]

    def test_columns_are_split_for_the_caller(self, tmp_path: Path) -> None:
        """Both chips derive from index vs worktree; deriving it once here beats
        every consumer re-slicing a padded string and getting it wrong."""
        files = self._files(tmp_path)
        assert (files[0]["index"], files[0]["worktree"]) == ("M", " ")
        assert (files[1]["index"], files[1]["worktree"]) == (" ", "M")
        assert (files[3]["index"], files[3]["worktree"]) == ("M", "M")

    def test_path_still_survives_a_two_column_code(self, tmp_path: Path) -> None:
        assert [f["path"] for f in self._files(tmp_path)] == ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"]


# ===========================================================================
# 3. Prose is UNCHANGED — the additive promise, pinned
# ===========================================================================


_PROSE_STATUS = {
    "ok": True,
    "files": [{"status": "M ", "path": "src/x.py", "index": "M", "worktree": " "}],
    "total": 1,
    "message": "1 file(s) changed under src",
}


class TestProseUnchanged:
    """The rendered surface every current caller reads must not move a byte."""

    @patch(_AUTH, return_value="drone")
    def test_status_row_renders_the_same_stripped_code(self, _auth: MagicMock, tmp_path: Path) -> None:
        """Raw code in the data, right-aligned single letter on screen — as before."""
        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path)):
            with patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=dict(_PROSE_STATUS)):
                result = handle_command("status", [])

        assert "   M src/x.py" in result["stdout"]
        assert "(showing drone scope — use --all for full repo)" in result["stdout"]
        assert result["exit_code"] == 0

    @patch(_AUTH, return_value="drone")
    def test_log_prose_untouched(self, _auth: MagicMock) -> None:
        with patch(
            f"{_GIT_MOD}.log_handler.get_git_log",
            return_value={"success": True, "entries": ["abc123 subject"], "count": 1, "message": "1 log entries"},
        ):
            result = handle_command("log", ["1"])

        assert result["stdout"] == "abc123 subject"


# ===========================================================================
# 4. --json on the three read doors
# ===========================================================================


class TestStatusJson:
    """status --json — a document, with the codes intact."""

    @patch(_AUTH, return_value="drone")
    def test_emits_parseable_document(self, _auth: MagicMock, tmp_path: Path) -> None:
        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path)):
            with patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=dict(_PROSE_STATUS)):
                result = handle_command("status", [JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is True
        assert doc["branch"] == "drone"
        assert doc["scope"] == "branch"
        assert doc["total"] == 1
        assert doc["files"] == [{"status": "M ", "path": "src/x.py", "index": "M", "worktree": " "}]

    @patch(_AUTH, return_value="drone")
    def test_no_prose_leaks_into_the_document(self, _auth: MagicMock, tmp_path: Path) -> None:
        """The scope footer is prose; a JSON caller must never have to strip it."""
        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path)):
            with patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=dict(_PROSE_STATUS)):
                result = handle_command("status", [JSON_FLAG])

        assert "showing drone scope" not in result["stdout"]
        json.loads(result["stdout"])

    @patch(_AUTH, return_value="drone")
    def test_all_reports_repo_scope(self, _auth: MagicMock, tmp_path: Path) -> None:
        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path)):
            with patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path):
                with patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=dict(_PROSE_STATUS)):
                    result = handle_command("status", ["--all", JSON_FLAG])

        assert json.loads(result["stdout"])["scope"] == "repo"

    @patch(_AUTH, return_value="drone")
    def test_undetectable_branch_still_answers_as_a_document(self, _auth: MagicMock) -> None:
        """Every exit from a --json call must be parseable, including the early ones.

        This refusal fires before the branch is known, which is exactly how a
        caller ends up with a bare sentence where it expected a document.
        """
        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=None):
            result = handle_command("status", [JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert "Cannot detect branch directory" in doc["message"]
        assert result["exit_code"] == 1

    @patch(_AUTH, return_value="drone")
    def test_failure_is_a_document_too_and_still_exits_nonzero(self, _auth: MagicMock, tmp_path: Path) -> None:
        """A JSON caller gets a JSON refusal — never a bare sentence it cannot parse.

        The false-green lesson holds underneath: ok is False AND the exit code
        is non-zero, so a script reading either signal is told the truth.
        """
        failed = {"ok": False, "files": [], "total": 0, "message": "status error: fatal: not a repository"}
        with patch(f"{_GIT_MOD}._detect_branch_dir", return_value=("drone", tmp_path)):
            with patch(f"{_GIT_MOD}.status_handler.get_branch_status", return_value=failed):
                result = handle_command("status", [JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert "not a repository" in doc["message"]
        assert result["exit_code"] == 1


class TestLogJson:
    """log --json — sha and subject split, which is the whole point."""

    @patch(_AUTH, return_value="drone")
    def test_splits_sha_from_subject(self, _auth: MagicMock) -> None:
        entries = ["abc1234 fix(git): a subject with spaces", "def5678 feat: another"]
        with patch(
            f"{_GIT_MOD}.log_handler.get_git_log",
            return_value={"success": True, "entries": entries, "count": 2, "message": "2 log entries"},
        ):
            result = handle_command("log", ["2", JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is True
        assert doc["count"] == 2
        assert doc["commits"][0] == {"sha": "abc1234", "subject": "fix(git): a subject with spaces"}
        assert doc["commits"][1]["sha"] == "def5678"

    @patch(_AUTH, return_value="drone")
    def test_flag_does_not_become_the_count(self, _auth: MagicMock) -> None:
        """Stripped before positional parsing: `log --json 5` still means 5.

        Unstripped, --json reached int() and logged a bogus 'Invalid log count'.
        """
        with patch(
            f"{_GIT_MOD}.log_handler.get_git_log",
            return_value={"success": True, "entries": [], "count": 0, "message": "0 log entries"},
        ) as mock_log:
            handle_command("log", [JSON_FLAG, "5"])

        assert mock_log.call_args.kwargs["count"] == 5

    @patch(_AUTH, return_value="drone")
    def test_subjectless_commit_does_not_lose_its_sha(self, _auth: MagicMock) -> None:
        with patch(
            f"{_GIT_MOD}.log_handler.get_git_log",
            return_value={"success": True, "entries": ["abc1234"], "count": 1, "message": "1 log entries"},
        ):
            doc = json.loads(handle_command("log", [JSON_FLAG])["stdout"])

        assert doc["commits"] == [{"sha": "abc1234", "subject": ""}]

    @patch(_AUTH, return_value="drone")
    def test_bad_count_refuses_as_a_document(self, _auth: MagicMock) -> None:
        result = handle_command("log", ["0", JSON_FLAG])
        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert result["exit_code"] == 1

    @patch(_AUTH, return_value="drone")
    def test_unknown_argument_refuses_by_name(self, _auth: MagicMock) -> None:
        """The owner's standing ruling: an unknown argument FAILS, by name.

        Red before 2026-09-07. ``log not_a_real_count`` logged a WARNING that
        the token was unparseable and then carried on with the default 10, so
        the output was byte-identical to plain ``log``, stderr was empty and the
        exit code was 0 — the caller was told the count it asked for had been
        honoured. The bad token must reach the message, or the next reader has
        nothing to grep for.
        """
        with patch(f"{_GIT_MOD}.log_handler.get_git_log") as mock_log:
            result = handle_command("log", ["not_a_real_count"])

        assert result["exit_code"] == 1
        assert result["stdout"] == ""
        assert "not_a_real_count" in result["stderr"]
        mock_log.assert_not_called()

    @patch(_AUTH, return_value="drone")
    def test_unknown_argument_refuses_as_a_document_under_json(self, _auth: MagicMock) -> None:
        """A refusal is a document too — the JSON caller parses why, not a guess."""
        with patch(f"{_GIT_MOD}.log_handler.get_git_log") as mock_log:
            result = handle_command("log", ["not_a_real_count", JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert "not_a_real_count" in doc["message"]
        assert result["exit_code"] == 1
        mock_log.assert_not_called()

    @patch(_AUTH, return_value="drone")
    def test_the_valid_idioms_still_parse(self, _auth: MagicMock) -> None:
        """The refusal must not eat the three shapes git itself accepts."""
        for args, expected in ((["20"], 20), (["-n", "5"], 5), (["-3"], 3)):
            with patch(
                f"{_GIT_MOD}.log_handler.get_git_log",
                return_value={"success": True, "entries": [], "count": 0, "message": "0 log entries"},
            ) as mock_log:
                handle_command("log", args)
            assert mock_log.call_args.kwargs["count"] == expected, args


class TestLogPathFilter:
    """log keeps only the commits touching the paths it is given (DPLAN-0356), no raw `git log -- path` needed."""

    _OK = {"success": True, "entries": ["abc1234 touched it"], "count": 1, "message": "1 log entries"}

    @patch(_AUTH, return_value="canary")
    def test_a_path_from_the_caller_directory_reaches_git_absolute(self, _auth: MagicMock, tmp_path: Path) -> None:
        """`log -n 3 apps` from a branch dir hands git that dir's apps, whatever cwd git runs in."""
        caller = tmp_path / "repo" / "src" / "canary"
        (caller / "apps").mkdir(parents=True)
        with (
            patch(f"{_GIT_MOD}.caller_cwd", return_value=caller),
            patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path / "repo"),
            patch(f"{_GIT_MOD}.log_handler.get_git_log", return_value=dict(self._OK)) as mock_log,
        ):
            result = handle_command("log", ["-n", "3", "apps"])

        assert result == {"stdout": "abc1234 touched it", "stderr": "", "exit_code": 0}
        assert mock_log.call_args.kwargs == {"count": 3, "repo_root": None, "paths": [str(caller / "apps")]}

    @patch(_AUTH, return_value="canary")
    def test_a_path_is_read_against_the_repo_root_when_the_caller_dir_lacks_it(
        self, _auth: MagicMock, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        (repo / "src" / "aipass" / "canary").mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        with (
            patch(f"{_GIT_MOD}.caller_cwd", return_value=elsewhere),
            patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=repo),
            patch(f"{_GIT_MOD}.log_handler.get_git_log", return_value=dict(self._OK)) as mock_log,
        ):
            handle_command("log", ["src/aipass/canary", "5"])

        assert mock_log.call_args.kwargs["paths"] == [str(repo / "src" / "aipass" / "canary")]
        assert mock_log.call_args.kwargs["count"] == 5

    @patch(_AUTH, return_value="canary")
    def test_a_gone_path_after_the_separator_is_still_a_filter(self, _auth: MagicMock, tmp_path: Path) -> None:
        """The history of a deleted file: after `--` nothing has to exist, and it reads from the caller's dir."""
        with (
            patch(f"{_GIT_MOD}.caller_cwd", return_value=tmp_path),
            patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path),
            patch(f"{_GIT_MOD}.log_handler.get_git_log", return_value=dict(self._OK)) as mock_log,
        ):
            result = handle_command("log", ["--", "old.py", "20"])

        assert result["exit_code"] == 0, result["stderr"]
        assert mock_log.call_args.kwargs["paths"] == [str(tmp_path / "old.py"), str(tmp_path / "20")]
        assert mock_log.call_args.kwargs["count"] == 10

    @patch(_AUTH, return_value="canary")
    def test_a_bare_token_that_is_no_path_is_refused_by_name(self, _auth: MagicMock, tmp_path: Path) -> None:
        with (
            patch(f"{_GIT_MOD}.caller_cwd", return_value=tmp_path),
            patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path),
            patch(f"{_GIT_MOD}.log_handler.get_git_log") as mock_log,
        ):
            result = handle_command("log", ["5", "no_such_dir"])

        assert result["exit_code"] == 1
        assert result["stderr"] == (
            "Unknown argument for 'log': no_such_dir (not a count, and no such path; "
            "a path that no longer exists goes after --)"
        )
        mock_log.assert_not_called()

    @patch(_AUTH, return_value="canary")
    def test_a_git_failure_exits_1_with_its_reason(self, _auth: MagicMock) -> None:
        """It once printed git's error on stdout with exit 0; a path outside the repo makes it likelier."""
        failed = {"success": False, "entries": [], "count": 0, "message": "git log error: fatal: outside repository"}
        with patch(f"{_GIT_MOD}.log_handler.get_git_log", return_value=failed):
            result = handle_command("log", [])

        assert result == {"stdout": "", "stderr": "git log error: fatal: outside repository", "exit_code": 1}

    @patch(_AUTH, return_value="canary")
    def test_a_git_failure_under_json_is_a_refusal_document(self, _auth: MagicMock) -> None:
        failed = {"success": False, "entries": [], "count": 0, "message": "git log error: x"}
        with patch(f"{_GIT_MOD}.log_handler.get_git_log", return_value=failed):
            result = handle_command("log", [JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert doc["message"] == "git log error: x"
        assert result["exit_code"] == 1

    def test_the_handler_puts_the_paths_after_the_separator(self, tmp_path: Path) -> None:
        ran = MagicMock(returncode=0, stdout="abc1234 s\n", stderr="")
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=ran) as mock_run:
            paths = [str(tmp_path / "a"), str(tmp_path / "b")]
            result = log_handler.get_git_log(count=4, repo_root=tmp_path, paths=paths)

        assert mock_run.call_args.args[0] == ["git", "log", "--oneline", "-4", "--", *paths]
        assert result["success"] is True
        assert result["entries"] == ["abc1234 s"]

    def test_the_handler_without_paths_runs_the_plain_log(self, tmp_path: Path) -> None:
        ran = MagicMock(returncode=0, stdout="", stderr="")
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=ran) as mock_run:
            result = log_handler.get_git_log(count=2, repo_root=tmp_path)

        assert mock_run.call_args.args[0] == ["git", "log", "--oneline", "-2"]
        assert result == {"success": True, "entries": [], "count": 0, "message": "0 log entries"}

    def test_the_handler_says_git_failed(self, tmp_path: Path) -> None:
        ran = MagicMock(returncode=128, stdout="", stderr="fatal: bad\n")
        with patch("aipass.drone.apps.handlers.git.log_handler.subprocess.run", return_value=ran):
            result = log_handler.get_git_log(count=2, repo_root=tmp_path)

        assert result == {"success": False, "entries": [], "count": 0, "message": "git log error: fatal: bad"}

    def test_resolve_prefers_the_caller_dir_then_the_root(self, tmp_path: Path) -> None:
        cwd, root = tmp_path / "cwd", tmp_path / "root"
        (cwd / "both").mkdir(parents=True)
        (root / "both").mkdir(parents=True)
        (root / "only_root").mkdir()

        assert log_handler.resolve_log_path("both", root, cwd, True) == str(cwd / "both")
        assert log_handler.resolve_log_path("only_root", root, cwd, True) == str(root / "only_root")
        assert log_handler.resolve_log_path("neither", root, cwd, True) is None
        assert log_handler.resolve_log_path("neither", root, cwd, False) == str(cwd / "neither")
        assert log_handler.resolve_log_path("neither", root, None, False) == str(root / "neither")

    def test_the_help_names_the_path_form_and_the_raw_twins(self) -> None:
        """@hooks' refusal text points agents here, so the forms are pinned as written."""
        verb = get_help("log")
        page = get_help()
        assert verb.startswith("git log [count] [path ...] [-- gone-path ...] — ")
        assert "  Example: drone @git log 5 src/aipass/drone\n" in verb
        assert "  git log -n 5 -- <path>   drone @git log 5 <path>  (deleted path: after --)\n" in page
        assert "  git show <sha>:<path>    drone @git show <sha> <path>\n" in page

    def test_resolve_keeps_an_absolute_path_and_checks_it_only_when_asked(self, tmp_path: Path) -> None:
        gone = tmp_path / "gone"
        assert log_handler.resolve_log_path(str(tmp_path), tmp_path, None, True) == str(tmp_path)
        assert log_handler.resolve_log_path(str(gone), tmp_path, None, True) is None
        assert log_handler.resolve_log_path(str(gone), tmp_path, None, False) == str(gone)


class TestBlame:
    """blame <file> [-L START,END]: the read twin of raw git blame (DPLAN-0356 leg 2), global tier."""

    _BLAMED = {"success": True, "lines": ["abc1234 (x 2026-09-30 1) a", "abc1234 (x 2026-09-30 2) b"], "message": ""}

    def test_blame_is_a_global_read(self) -> None:
        assert "blame" in GIT_ACCESS_TIERS["global"]["commands"]
        assert "blame" not in GIT_ACCESS_TIERS["owner"]["commands"]

    @patch(_AUTH, return_value="canary")
    def test_a_file_from_the_caller_directory_is_blamed_in_range(self, _auth: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "f.py").write_text("a\nb\n", encoding="utf-8")
        with (
            patch(f"{_GIT_MOD}.caller_cwd", return_value=tmp_path),
            patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path),
            patch(f"{_GIT_MOD}.blame_handler.get_git_blame", return_value=dict(self._BLAMED)) as mock_blame,
        ):
            result = handle_command("blame", ["f.py", "-L", "1,2"])

        assert result == {"stdout": "\n".join(self._BLAMED["lines"]), "stderr": "", "exit_code": 0}
        mock_blame.assert_called_once_with(str(tmp_path / "f.py"), (1, 2), repo_root=tmp_path)

    @patch(_AUTH, return_value="canary")
    def test_a_missing_file_is_refused_by_name(self, _auth: MagicMock, tmp_path: Path) -> None:
        with (
            patch(f"{_GIT_MOD}.caller_cwd", return_value=tmp_path),
            patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path),
            patch(f"{_GIT_MOD}.blame_handler.get_git_blame") as mock_blame,
        ):
            result = handle_command("blame", ["nope.py"])

        assert result == {"stdout": "", "stderr": "No such file for 'blame': nope.py", "exit_code": 1}
        mock_blame.assert_not_called()

    @patch(_AUTH, return_value="canary")
    def test_a_bad_range_and_a_stray_argument_refuse_before_git(self, _auth: MagicMock) -> None:
        with patch(f"{_GIT_MOD}.blame_handler.get_git_blame") as mock_blame:
            backwards = handle_command("blame", ["f.py", "-L", "5,2"])
            no_value = handle_command("blame", ["f.py", "-L"])
            stray = handle_command("blame", ["f.py", "extra"])
            bare = handle_command("blame", [])

        assert backwards["stderr"] == "Invalid line range for 'blame': '5,2' (use -L START,END, e.g. -L 10,40)"
        assert no_value["stderr"] == "Invalid line range for 'blame': '' (use -L START,END, e.g. -L 10,40)"
        assert stray["stderr"] == "Unknown argument for 'blame': extra\nUsage: drone @git blame <file> [-L START,END]"
        assert bare["stderr"] == "Usage: drone @git blame <file> [-L START,END]"
        assert {r["exit_code"] for r in (backwards, no_value, stray, bare)} == {1}
        mock_blame.assert_not_called()

    @patch(_AUTH, return_value="canary")
    def test_a_git_failure_exits_1_with_its_reason(self, _auth: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "f.py").write_text("a\n", encoding="utf-8")
        failed = {"success": False, "lines": [], "message": "git blame error: fatal: no such path"}
        with (
            patch(f"{_GIT_MOD}.caller_cwd", return_value=tmp_path),
            patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=tmp_path),
            patch(f"{_GIT_MOD}.blame_handler.get_git_blame", return_value=failed),
        ):
            result = handle_command("blame", ["f.py"])

        assert result == {"stdout": "", "stderr": "git blame error: fatal: no such path", "exit_code": 1}

    def test_the_handler_command_puts_the_range_before_the_separator(self, tmp_path: Path) -> None:
        ran = MagicMock(returncode=0, stdout="l1\nl2\n", stderr="")
        with patch("aipass.drone.apps.handlers.git.blame_handler.subprocess.run", return_value=ran) as mock_run:
            target = str(tmp_path / "f.py")
            ranged = blame_handler.get_git_blame(target, (3, 9), repo_root=tmp_path)
            whole = blame_handler.get_git_blame(target, repo_root=tmp_path)

        assert mock_run.call_args_list[0].args[0] == ["git", "blame", "--date=short", "-L", "3,9", "--", target]
        assert mock_run.call_args_list[1].args[0] == ["git", "blame", "--date=short", "--", target]
        assert ranged == {"success": True, "lines": ["l1", "l2"], "message": "2 line(s) blamed"}
        assert whole["success"] is True

    def test_the_handler_says_git_failed(self, tmp_path: Path) -> None:
        ran = MagicMock(returncode=128, stdout="", stderr="fatal: no such path\n")
        with patch("aipass.drone.apps.handlers.git.blame_handler.subprocess.run", return_value=ran):
            result = blame_handler.get_git_blame(str(tmp_path / "f.py"), repo_root=tmp_path)

        assert result == {"success": False, "lines": [], "message": "git blame error: fatal: no such path"}

    def test_only_two_ordered_line_numbers_make_a_range(self) -> None:
        assert blame_handler.parse_line_range("10,40") == (10, 40)
        assert blame_handler.parse_line_range("7,7") == (7, 7)
        for bad in ("0,4", "5,2", "10", "10,", "/re/,+3", ":func", "-1,3", ""):
            assert blame_handler.parse_line_range(bad) is None, bad

    def test_the_help_names_the_verb_and_its_raw_twin(self) -> None:
        assert get_help("blame").startswith("git blame <file> [-L START,END] — ")
        assert "  git blame -L 10,40 <f>   drone @git blame <f> -L 10,40\n" in get_help()


class TestGhPassthroughTiers:
    """issue, run and workflow: reads stay global, every write asks the owner tier, unknown is refused.

    DPLAN-0356 leg 3. The gate is stubbed with a recorder of the key it is asked
    for, so each test reads which tier a subcommand reaches; gh never runs.
    """

    @staticmethod
    def _route(command: str, args: list[str]) -> tuple[dict, list[str], MagicMock]:
        asked: list[str] = []

        def gate(key: str) -> str:
            asked.append(key)
            return "canary"

        with patch(_AUTH, side_effect=gate), patch(f"{_GIT_MOD}.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
            result = handle_command(command, args)
        return result, asked, mock_run

    @pytest.mark.parametrize(
        ("command", "args"),
        [
            ("issue", ["list"]),
            ("issue", ["view", "12", "--comments"]),
            ("issue", ["status"]),
            ("run", ["list"]),
            ("run", ["view", "55", "--log-failed"]),
            ("run", ["watch", "55"]),
            ("workflow", ["list"]),
            ("workflow", ["view", "ci.yml"]),
        ],
    )
    def test_a_read_asks_the_global_key(self, command: str, args: list[str]) -> None:
        result, asked, mock_run = self._route(command, args)
        assert asked == [command]
        assert result["exit_code"] == 0
        mock_run.assert_called_once()

    @pytest.mark.parametrize(
        ("command", "args"),
        [
            ("issue", ["create", "--title", "x"]),
            ("issue", ["close", "12"]),
            ("issue", ["comment", "12", "--body", "x"]),
            ("issue", ["edit", "12"]),
            ("run", ["rerun", "55"]),
            ("run", ["cancel", "55"]),
            ("run", ["delete", "55"]),
            ("workflow", ["run", "ci.yml"]),
            ("workflow", ["enable", "ci.yml"]),
            ("workflow", ["disable", "ci.yml"]),
        ],
    )
    def test_a_write_asks_the_owner_key(self, command: str, args: list[str]) -> None:
        _result, asked, _mock_run = self._route(command, args)
        assert asked == [f"{command}-write"]

    def test_an_unknown_subcommand_is_refused_before_the_gate_and_gh(self) -> None:
        result, asked, mock_run = self._route("issue", ["frobnicate", "12"])
        assert asked == []
        mock_run.assert_not_called()
        assert result["exit_code"] == 1
        assert result["stderr"].startswith("Unknown subcommand for 'issue': 'frobnicate'. ")

    def test_a_flag_in_the_subcommand_slot_is_refused(self) -> None:
        """gh reads `issue -R x/y create` as a create; the slot must hold the subcommand itself."""
        result, asked, mock_run = self._route("issue", ["-R", "x/y", "create"])
        assert asked == []
        mock_run.assert_not_called()
        assert result["exit_code"] == 1

    @pytest.mark.parametrize("command", ["issue", "run", "workflow"])
    def test_the_key_for_each_shape(self, command: str) -> None:
        table = GH_SUBCOMMANDS[command]
        assert gh_access_key(command, []) == command
        assert gh_access_key(command, [table["read"][0]]) == command
        assert gh_access_key(command, [table["write"][-1]]) == f"{command}-write"
        assert gh_access_key(command, ["frobnicate"]) is None

    @pytest.mark.parametrize("command", ["issue", "run", "workflow"])
    def test_the_write_key_is_owner_only(self, command: str) -> None:
        assert f"{command}-write" in GIT_ACCESS_TIERS["owner"]["commands"]
        assert f"{command}-write" not in GIT_ACCESS_TIERS["global"]["commands"]
        assert command in GIT_ACCESS_TIERS["global"]["commands"]

    @pytest.mark.parametrize("command", ["issue", "run", "workflow"])
    def test_verb_help_names_every_read_and_every_owner_write(self, command: str) -> None:
        table = GH_SUBCOMMANDS[command]
        text = get_help(command)
        reads_line = next(line for line in text.splitlines() if line.startswith("  Reads [global]: "))
        owner_at = text.index("  Owner only: ")
        for sub in table["read"]:
            assert sub in reads_line
        for sub in table["write"]:
            assert sub in text[owner_at:]
        assert "refused" in text
        assert all(len(line) <= 80 for line in text.splitlines())

    def test_the_page_lists_the_reads_as_global_and_the_writes_as_owner(self) -> None:
        page = get_help()
        global_part, owner_part = page.split("Owner (devpulse only):\n", 1)
        owner_part = owner_part.split("\n\n", 1)[0]
        for command, table in GH_SUBCOMMANDS.items():
            assert f"  {command} {'|'.join(table['read'])}" in global_part
            assert f"  {command} <write> " in owner_part
        assert "  gh issue list|view|status  drone @git issue list|view|status\n" in page
        gh_lines = [line for line in page.splitlines() if line.startswith(tuple(f"  {c} " for c in GH_SUBCOMMANDS))]
        assert len(gh_lines) == 6
        assert all(len(line) <= 80 for line in gh_lines)


class TestShowJson:
    """show --json — content carried as a field, not as the whole stream."""

    @patch(_AUTH, return_value="drone")
    def test_content_travels_as_a_field(self, _auth: MagicMock) -> None:
        with patch(
            f"{_GIT_MOD}.show_handler.show_object",
            return_value={"success": True, "content": "line one\nline two\n", "message": "showed HEAD"},
        ):
            result = handle_command("show", ["HEAD", JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is True
        assert doc["ref"] == "HEAD"
        assert doc["path"] is None
        assert doc["content"] == "line one\nline two\n"

    @patch(_AUTH, return_value="drone")
    def test_flag_is_never_mistaken_for_the_ref(self, _auth: MagicMock) -> None:
        """Unstripped, `show --json HEAD` refused --json as a flag-shaped ref."""
        with patch(
            f"{_GIT_MOD}.show_handler.show_object",
            return_value={"success": True, "content": "x", "message": "showed HEAD"},
        ) as mock_show:
            handle_command("show", [JSON_FLAG, "HEAD"])

        assert mock_show.call_args[0][0] == "HEAD"

    @patch(_AUTH, return_value="drone")
    def test_path_form_survives(self, _auth: MagicMock) -> None:
        with patch(
            f"{_GIT_MOD}.show_handler.show_object",
            return_value={"success": True, "content": "x", "message": "showed HEAD:f.py"},
        ) as mock_show:
            doc = json.loads(handle_command("show", ["HEAD", "f.py", JSON_FLAG])["stdout"])

        assert mock_show.call_args[0] == ("HEAD", "f.py")
        assert doc["path"] == "f.py"

    @patch(_AUTH, return_value="drone")
    def test_missing_ref_refuses_as_a_document(self, _auth: MagicMock) -> None:
        result = handle_command("show", [JSON_FLAG])
        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert result["exit_code"] == 1

    @patch(_AUTH, return_value="drone")
    def test_failure_refuses_as_a_document(self, _auth: MagicMock) -> None:
        with patch(
            f"{_GIT_MOD}.show_handler.show_object",
            return_value={"success": False, "content": "", "message": "show error: unknown revision"},
        ):
            result = handle_command("show", ["nope", JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert "unknown revision" in doc["message"]
        assert result["exit_code"] == 1


# ===========================================================================
# 5. ASK 2 — the remote read door
# ===========================================================================


def _remote_run(stdout: str, returncode: int = 0, stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


_TWO_REMOTES = (
    "origin\thttps://github.com/aipass/aipass.git (fetch)\n"
    "origin\thttps://github.com/aipass/aipass.git (push)\n"
    "upstream\tgit@github.com:other/aipass.git (fetch)\n"
    "upstream\tgit@github.com:other/aipass.git (push)\n"
)


class TestRemoteHandler:
    """Names and urls, credentials redacted before anything can travel."""

    def _remotes(self, stdout: str, tmp_path: Path) -> dict:
        with patch(f"{_REMOTE_MOD}.subprocess.run", return_value=_remote_run(stdout)):
            with patch(f"{_REMOTE_MOD}.find_repo_root", return_value=tmp_path):
                return remote_handler.list_remotes()

    def test_collapses_fetch_and_push_into_one_entry(self, tmp_path: Path) -> None:
        result = self._remotes(_TWO_REMOTES, tmp_path)
        assert result["ok"] is True
        assert result["count"] == 2
        assert [r["name"] for r in result["remotes"]] == ["origin", "upstream"]
        assert result["remotes"][0]["fetch"] == "https://github.com/aipass/aipass.git"
        assert result["remotes"][0]["push"] == "https://github.com/aipass/aipass.git"

    def test_differing_push_url_is_not_lost(self, tmp_path: Path) -> None:
        stdout = "origin\thttps://a.example/r.git (fetch)\norigin\thttps://b.example/r.git (push)\n"
        entry = self._remotes(stdout, tmp_path)["remotes"][0]
        assert entry["fetch"] == "https://a.example/r.git"
        assert entry["push"] == "https://b.example/r.git"

    def test_no_remote_is_an_answer_not_a_failure(self, tmp_path: Path) -> None:
        """Two real projects in the tree have none — that is a fact, not an error."""
        result = self._remotes("", tmp_path)
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["remotes"] == []

    def test_failure_is_not_reported_as_no_remotes(self, tmp_path: Path) -> None:
        """The false-green trap: an error must never read as an empty answer."""
        with patch(f"{_REMOTE_MOD}.subprocess.run", return_value=_remote_run("", 128, "fatal: not a repository")):
            with patch(f"{_REMOTE_MOD}.find_repo_root", return_value=tmp_path):
                result = remote_handler.list_remotes()

        assert result["ok"] is False
        assert "not a repository" in result["message"]

    def test_missing_binary_is_reported_honestly(self, tmp_path: Path) -> None:
        with patch(f"{_REMOTE_MOD}.subprocess.run", side_effect=OSError("boom")):
            with patch(f"{_REMOTE_MOD}.find_repo_root", return_value=tmp_path):
                result = remote_handler.list_remotes()

        assert result["ok"] is False
        assert result["remotes"] == []


class TestRemoteRedaction:
    """A link-card is exactly the surface that ends up screenshotted."""

    def _one(self, url: str, tmp_path: Path) -> dict:
        stdout = f"origin\t{url} (fetch)\norigin\t{url} (push)\n"
        with patch(f"{_REMOTE_MOD}.subprocess.run", return_value=_remote_run(stdout)):
            with patch(f"{_REMOTE_MOD}.find_repo_root", return_value=tmp_path):
                return remote_handler.list_remotes()["remotes"][0]

    def test_password_never_travels(self, tmp_path: Path) -> None:
        entry = self._one("https://user:s3cret@github.com/a/b.git", tmp_path)
        assert "s3cret" not in json.dumps(entry)
        assert entry["redacted"] is True

    def test_token_in_the_username_slot_never_travels(self, tmp_path: Path) -> None:
        """The common PAT form is `https://<TOKEN>@host/...` — the secret IS the
        username, so redacting only a password would leak it.

        The token is ASSEMBLED rather than written: the shape is what this test
        needs, and a PAT-shaped literal in the source is what the hardcoded_key
        checker exists to catch. It cannot tell a synthetic subject from a real
        leak, and it should not have to.
        """
        token = "ghp_" + "A" * 16
        entry = self._one(f"https://{token}@github.com/a/b.git", tmp_path)
        assert token not in json.dumps(entry)
        assert entry["redacted"] is True

    def test_host_and_path_survive_redaction(self, tmp_path: Path) -> None:
        """Redaction must leave a link-card that still says where it points."""
        entry = self._one("https://user:pw@github.com/aipass/aipass.git", tmp_path)
        assert entry["fetch"] == "https://***@github.com/aipass/aipass.git"

    def test_clean_https_is_untouched(self, tmp_path: Path) -> None:
        entry = self._one("https://github.com/aipass/aipass.git", tmp_path)
        assert entry["fetch"] == "https://github.com/aipass/aipass.git"
        assert entry["redacted"] is False

    def test_scp_ssh_form_is_not_mangled(self, tmp_path: Path) -> None:
        """`git@github.com:a/b.git` — that `git@` is the standard SSH form, not a
        secret. Redacting it would ruin every normal ssh remote in the fleet."""
        entry = self._one("git@github.com:aipass/aipass.git", tmp_path)
        assert entry["fetch"] == "git@github.com:aipass/aipass.git"
        assert entry["redacted"] is False

    def test_ssh_scheme_user_is_not_mangled(self, tmp_path: Path) -> None:
        entry = self._one("ssh://git@github.com/aipass/aipass.git", tmp_path)
        assert entry["fetch"] == "ssh://git@github.com/aipass/aipass.git"
        assert entry["redacted"] is False

    def test_redacted_url_is_what_reaches_the_audit_log(self, tmp_path: Path) -> None:
        """The raw value must not reach a log line either."""
        stdout = "origin\thttps://user:s3cret@h/a.git (fetch)\norigin\thttps://user:s3cret@h/a.git (push)\n"
        with patch(f"{_REMOTE_MOD}.subprocess.run", return_value=_remote_run(stdout)):
            with patch(f"{_REMOTE_MOD}.find_repo_root", return_value=tmp_path):
                with patch(f"{_REMOTE_MOD}.json_handler.log_operation") as mock_log:
                    remote_handler.list_remotes()

        assert "s3cret" not in json.dumps(mock_log.call_args[0][1])


class TestRemoteCommand:
    """The door as callers reach it: `drone @git remote`."""

    _RESULT = {
        "ok": True,
        "remotes": [
            {
                "name": "origin",
                "fetch": "https://github.com/a/b.git",
                "push": "https://github.com/a/b.git",
                "redacted": False,
            }
        ],
        "count": 1,
        "message": "1 remote(s)",
    }

    @patch(_AUTH, return_value="drone")
    def test_prose_names_the_remote_and_its_url(self, _auth: MagicMock) -> None:
        with patch(f"{_GIT_MOD}.remote_handler.list_remotes", return_value=dict(self._RESULT)):
            result = handle_command("remote", [])

        assert "origin" in result["stdout"]
        assert "https://github.com/a/b.git" in result["stdout"]
        assert result["exit_code"] == 0

    @patch(_AUTH, return_value="drone")
    def test_json_document(self, _auth: MagicMock) -> None:
        with patch(f"{_GIT_MOD}.remote_handler.list_remotes", return_value=dict(self._RESULT)):
            result = handle_command("remote", [JSON_FLAG])

        doc = json.loads(result["stdout"])
        assert doc["ok"] is True
        assert doc["count"] == 1
        assert doc["remotes"][0]["name"] == "origin"

    @patch(_AUTH, return_value="drone")
    def test_no_remote_says_so_in_words(self, _auth: MagicMock) -> None:
        empty = {"ok": True, "remotes": [], "count": 0, "message": "no remote configured"}
        with patch(f"{_GIT_MOD}.remote_handler.list_remotes", return_value=empty):
            result = handle_command("remote", [])

        assert "no remote" in result["stdout"].lower()
        assert result["exit_code"] == 0

    @patch(_AUTH, return_value="drone")
    def test_failure_exits_nonzero(self, _auth: MagicMock) -> None:
        failed = {"ok": False, "remotes": [], "count": 0, "message": "remote error: fatal: not a repository"}
        with patch(f"{_GIT_MOD}.remote_handler.list_remotes", return_value=failed):
            result = handle_command("remote", [])

        assert result["exit_code"] == 1
        assert "not a repository" in result["stderr"]

    def test_remote_is_global_tier_so_every_branch_may_read_it(self) -> None:
        """A read door refused to everyone but the owner is not a read door.

        Unlisted commands raise 'Unknown git command' in the gate, so this pins
        the tier registration, not just the routing.
        """
        assert "remote" in GIT_ACCESS_TIERS["global"]["commands"]
        assert "remote" not in GIT_ACCESS_TIERS["owner"]["commands"]

    @patch(_AUTH, return_value="drone")
    def test_help_outranks_json(self, _auth: MagicMock) -> None:
        """`remote --help --json` is still a question (DPLAN-0291 rule E)."""
        with patch(f"{_GIT_MOD}.remote_handler.list_remotes") as mock_remote:
            result = handle_command("remote", ["--help", JSON_FLAG])

        mock_remote.assert_not_called()
        assert result["exit_code"] == 0


# ---------------------------------------------------------------------------
# merge-main — origin/main into dev with a merge commit, against a temp repo
# ---------------------------------------------------------------------------


#: Why the unreadable-index pin skips: a mode-0 file binds no one on Windows or as root.
_PERMISSIONS_REASON = "needs POSIX permissions that bind the caller"


def _git(cwd: Path, *argv: str, check: bool = True) -> str:
    """Run git in *cwd* for fixture setup and read-back."""
    return subprocess.run(
        ["git", *argv], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", check=check
    ).stdout.strip()


@pytest.fixture()
def diverged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A work repo on dev, one commit ahead of main, while origin/main took two files dev never saw.

    Git runs with no host config, a fixed identity and a ceiling at tmp_path, so
    no repository above the sandbox answers for it.
    """
    empty_config = tmp_path / "gitconfig"
    empty_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", os.pathsep.join(sorted({str(tmp_path), str(tmp_path.resolve())})))
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Merge Test")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "merge@test.invalid")

    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    for name in ("a.txt", "b.txt"):
        (work / name).write_text(f"{name} seed\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "seed")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "origin", "main")

    upstream = tmp_path / "upstream"
    _git(tmp_path, "clone", "-q", str(origin), str(upstream))
    (upstream / "a.txt").write_text("a.txt from main\n", encoding="utf-8")
    (upstream / "m.txt").write_text("new on main\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-q", "-m", "main moves on")
    _git(upstream, "push", "-q", "origin", "main")

    _git(work, "checkout", "-q", "-b", "dev")
    (work / "d.txt").write_text("dev work\n", encoding="utf-8")
    _git(work, "add", "d.txt")
    _git(work, "commit", "-q", "-m", "dev work")
    monkeypatch.chdir(work)
    return {"work": work, "origin": origin, "upstream": upstream}


class TestMergeMain:
    """merge-main: main's commits into dev by merge, refused on any doubt, never pushed, forced or stashed."""

    @staticmethod
    def _run(work: Path, args: list[str] | None = None) -> dict:
        with patch(_AUTH, return_value="devpulse"), patch(f"{_GIT_MOD}.lock_handler.find_repo_root", return_value=work):
            return handle_command("merge-main", args or [])

    def test_a_clean_merge_is_a_merge_commit_with_main_as_second_parent_and_is_not_pushed(
        self, diverged: dict[str, Path]
    ) -> None:
        work = diverged["work"]
        dev_before = _git(work, "rev-parse", "HEAD")
        (work / "d.txt").write_text("uncommitted, unrelated\n", encoding="utf-8")

        result = self._run(work)

        assert result["exit_code"] == 0, result["stderr"]
        main_sha = _git(work, "rev-parse", "origin/main")
        assert _git(work, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:] == [dev_before, main_sha]
        assert _git(work, "branch", "--show-current") == "dev"
        assert (work / "a.txt").read_text(encoding="utf-8") == "a.txt from main\n"
        assert (work / "d.txt").read_text(encoding="utf-8") == "uncommitted, unrelated\n"
        assert _git(work, "ls-remote", "origin", "dev") == ""
        assert _git(work, "stash", "list") == ""
        assert "2 file(s)" in result["stdout"]
        assert "Not pushed" in result["stdout"]

    def test_a_dev_with_nothing_of_its_own_still_gets_a_merge_commit_not_a_fast_forward(
        self, diverged: dict[str, Path]
    ) -> None:
        work = diverged["work"]
        _git(work, "reset", "-q", "--hard", "main")
        dev_before = _git(work, "rev-parse", "HEAD")

        result = self._run(work)

        assert result["exit_code"] == 0, result["stderr"]
        parents = _git(work, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        assert parents == [dev_before, _git(work, "rev-parse", "origin/main")]

    @pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason=_PERMISSIONS_REASON)
    def test_a_git_read_that_fails_refuses_rather_than_reading_as_no_overlap(self, diverged: dict[str, Path]) -> None:
        """An unreadable index is the command route to a failed listing; mode restored in finally."""
        work = diverged["work"]
        head = _git(work, "rev-parse", "HEAD")
        # fetch's on-demand submodule check opens the index too; off, the first reader is the listing.
        _git(work, "config", "fetch.recurseSubmodules", "false")
        index = work / ".git" / "index"
        index.chmod(0)
        try:
            result = self._run(work)
        finally:
            index.chmod(0o644)

        assert result["exit_code"] == 1
        assert result["stderr"].startswith("git diff --cached --name-only -z failed: ")
        assert result["stderr"].endswith(". Nothing was merged.")
        assert _git(work, "rev-parse", "HEAD") == head

    def test_off_dev_it_refuses_before_touching_anything(self, diverged: dict[str, Path]) -> None:
        work = diverged["work"]
        _git(work, "checkout", "-q", "main")
        head = _git(work, "rev-parse", "HEAD")

        result = self._run(work)

        assert result["exit_code"] == 1
        assert result["stderr"].startswith("merge-main runs on dev only; HEAD is main.")
        assert _git(work, "rev-parse", "HEAD") == head
        assert _git(work, "rev-parse", "--verify", "--quiet", "origin/main", check=False) == head

    def test_a_dirty_file_main_also_changes_is_refused_and_named(self, diverged: dict[str, Path]) -> None:
        work = diverged["work"]
        head = _git(work, "rev-parse", "HEAD")
        (work / "a.txt").write_text("local edit\n", encoding="utf-8")
        (work / "m.txt").write_text("untracked here, added on main\n", encoding="utf-8")

        result = self._run(work)

        assert result["exit_code"] == 1
        assert "a.txt\n  m.txt" in result["stderr"]
        assert "b.txt" not in result["stderr"]
        assert _git(work, "rev-parse", "HEAD") == head
        assert (work / "a.txt").read_text(encoding="utf-8") == "local edit\n"

    def test_a_staged_change_is_refused_so_the_merge_commit_never_sweeps_it_in(self, diverged: dict[str, Path]) -> None:
        work = diverged["work"]
        head = _git(work, "rev-parse", "HEAD")
        (work / "b.txt").write_text("staged\n", encoding="utf-8")
        _git(work, "add", "b.txt")

        result = self._run(work)

        assert result["exit_code"] == 1
        assert "Staged changes" in result["stderr"]
        assert "b.txt" in result["stderr"]
        assert _git(work, "rev-parse", "HEAD") == head
        assert _git(work, "diff", "--cached", "--name-only") == "b.txt"

    def test_a_conflict_is_aborted_named_and_leaves_the_tree_as_before(self, diverged: dict[str, Path]) -> None:
        work = diverged["work"]
        (work / "a.txt").write_text("dev's own a\n", encoding="utf-8")
        _git(work, "commit", "-q", "-am", "dev edits a")
        head = _git(work, "rev-parse", "HEAD")
        (work / "d.txt").write_text("uncommitted, unrelated\n", encoding="utf-8")

        result = self._run(work)

        assert result["exit_code"] == 1
        assert "Conflicted files:\n  a.txt" in result["stderr"]
        assert "aborted" in result["stderr"]
        assert _git(work, "rev-parse", "HEAD") == head
        assert _git(work, "rev-parse", "--verify", "--quiet", "MERGE_HEAD", check=False) == ""
        assert (work / "a.txt").read_text(encoding="utf-8") == "dev's own a\n"
        assert (work / "d.txt").read_text(encoding="utf-8") == "uncommitted, unrelated\n"
        assert _git(work, "status", "--porcelain") == "M d.txt"
        assert _git(work, "stash", "list") == ""

    def test_a_merge_already_in_progress_is_refused_and_left_alone(self, diverged: dict[str, Path]) -> None:
        """An abort on conflict would throw away somebody else's half-done merge."""
        work = diverged["work"]
        (work / "a.txt").write_text("dev's own a\n", encoding="utf-8")
        _git(work, "commit", "-q", "-am", "dev edits a")
        _git(work, "fetch", "-q", "origin")
        _git(work, "merge", "origin/main", check=False)
        merge_head = _git(work, "rev-parse", "MERGE_HEAD")

        result = self._run(work)

        assert result["exit_code"] == 1
        assert "already in progress" in result["stderr"]
        assert _git(work, "rev-parse", "MERGE_HEAD") == merge_head

    def test_a_second_run_finds_nothing_to_merge_and_adds_no_commit(self, diverged: dict[str, Path]) -> None:
        work = diverged["work"]
        self._run(work)
        head = _git(work, "rev-parse", "HEAD")

        result = self._run(work)

        assert result["exit_code"] == 0
        assert "nothing to merge" in result["stdout"]
        assert _git(work, "rev-parse", "HEAD") == head

    def test_an_argument_is_refused_before_git_runs(self, diverged: dict[str, Path]) -> None:
        work = diverged["work"]
        head = _git(work, "rev-parse", "HEAD")

        result = self._run(work, ["--force"])

        assert result["exit_code"] == 1
        assert result["stderr"] == "merge-main takes no arguments; got: --force"
        assert _git(work, "rev-parse", "HEAD") == head
        assert _git(work, "rev-parse", "--verify", "--quiet", "origin/main", check=False) != _git(
            diverged["upstream"], "rev-parse", "HEAD"
        )

    def test_it_asks_the_owner_tier(self) -> None:
        assert "merge-main" in GIT_ACCESS_TIERS["owner"]["commands"]
        assert "merge-main" not in GIT_ACCESS_TIERS["global"]["commands"]
        asked: list[str] = []
        with (
            patch(_AUTH, side_effect=lambda key: asked.append(key) or "devpulse"),
            patch(f"{_GIT_MOD}.merge_main_handler.merge_main", return_value={"success": True, "message": "ok"}),
        ):
            handle_command("merge-main", [])
        assert asked == ["merge-main"]

    def test_help_names_the_verb_and_fix_points_at_it(self) -> None:
        verb = get_help("merge-main")
        assert verb.startswith("git merge-main — Merge origin/main into dev (no rewrite) [owner]\n")
        for claim in ("--no-ff", "never pushes", "never forces", "never stashes", "dev-pr"):
            assert claim in verb
        assert "drone @git merge-main" in get_help("fix")
        owner_part = get_help().split("Owner (devpulse only):\n", 1)[1].split("\n\n", 1)[0]
        assert "  merge-main " in owner_part
