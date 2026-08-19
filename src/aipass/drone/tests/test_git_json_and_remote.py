# =================== AIPass ====================
# Name: test_git_json_and_remote.py
# Description: Machine output on the git read doors, and the remote read door
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""FPLAN-0438 round 4a — the two door asks from @api's boundary assessment.

ASK 1: ``--json`` on status / log / show, so a consumer reads a document
instead of scraping a rendered sentence.

ASK 2: ``drone @git remote`` — a door that did not exist, which is why @api
parsed .git/config as an INI file with its own worktree-following.

Every prose assertion here is a REGRESSION PIN: the asks were explicitly
additive, so the desktop and every current caller must keep reading exactly the
bytes they read before.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.handlers.json_flags import JSON_FLAG, strip_json_flag, wants_json
from aipass.drone.apps.handlers.git import remote_handler
from aipass.drone.apps.handlers.git.status_handler import get_branch_status
from aipass.drone.apps.modules.git_module import handle_command

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
            return_value={"entries": ["abc123 subject"], "count": 1, "message": "1 log entries"},
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
            return_value={"entries": entries, "count": 2, "message": "2 log entries"},
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
            return_value={"entries": [], "count": 0, "message": "0 log entries"},
        ) as mock_log:
            handle_command("log", [JSON_FLAG, "5"])

        assert mock_log.call_args.kwargs["count"] == 5

    @patch(_AUTH, return_value="drone")
    def test_subjectless_commit_does_not_lose_its_sha(self, _auth: MagicMock) -> None:
        with patch(
            f"{_GIT_MOD}.log_handler.get_git_log",
            return_value={"entries": ["abc1234"], "count": 1, "message": "1 log entries"},
        ):
            doc = json.loads(handle_command("log", [JSON_FLAG])["stdout"])

        assert doc["commits"] == [{"sha": "abc1234", "subject": ""}]

    @patch(_AUTH, return_value="drone")
    def test_bad_count_refuses_as_a_document(self, _auth: MagicMock) -> None:
        result = handle_command("log", ["0", JSON_FLAG])
        doc = json.loads(result["stdout"])
        assert doc["ok"] is False
        assert result["exit_code"] == 1


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
        username, so redacting only a password would leak it."""
        entry = self._one("https://ghp_AAAABBBBCCCCDDDD@github.com/a/b.git", tmp_path)
        assert "ghp_AAAABBBBCCCCDDDD" not in json.dumps(entry)
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
        from aipass.drone.apps.plugins.devpulse_ops.auth import GIT_ACCESS_TIERS

        assert "remote" in GIT_ACCESS_TIERS["global"]["commands"]
        assert "remote" not in GIT_ACCESS_TIERS["owner"]["commands"]

    @patch(_AUTH, return_value="drone")
    def test_help_outranks_json(self, _auth: MagicMock) -> None:
        """`remote --help --json` is still a question (DPLAN-0291 rule E)."""
        with patch(f"{_GIT_MOD}.remote_handler.list_remotes") as mock_remote:
            result = handle_command("remote", ["--help", JSON_FLAG])

        mock_remote.assert_not_called()
        assert result["exit_code"] == 0
