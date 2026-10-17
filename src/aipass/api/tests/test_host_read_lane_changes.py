# =================== AIPass ====================
# Name: test_host_read_lane_changes.py
# Description: Tests for the read lane's git-changes lane — the card contract, the stampede, grains, rows, refusals
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for read_git_changes() in apps/handlers/host/git_reads.py and its cache and refusal memory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — drone's own `git status --json`; subprocess.run is faked, drone tests it

import concurrent.futures as cf
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import git_reads as host_git
from aipass.api.apps.handlers.host import refusals as host_refusals
from aipass.api.tests.support_host_read_lane import GIT_STATUS_ALL_STDOUT, GIT_STATUS_STDOUT, status_document

# Own constants, not conftest's: discarded_patch judges a target imported from this package.
PATCH_GIT_LOGGER = "aipass.api.apps.handlers.host.git_reads.logger"
PATCH_CACHE_LOGGER = "aipass.api.apps.handlers.host.read_cache.logger"
PATCH_HOST_FLEET = "aipass.api.apps.handlers.host.fleet"

# Every case here calls read_git_changes, which answers from its cache.
pytestmark = pytest.mark.usefixtures("_clean_git_changes_cache")


class TestGitChangesMatchesTheDesktopCard:
    """@baud's desktop already answers this question, so the phone must not get a
    second answer to it: `git diff HEAD --relative --name-only -- .`, TRACKED files, branch-relative."""

    def _completed(self, stdout: str = GIT_STATUS_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_the_shape_is_files_and_count(self, fake_repo: dict) -> None:
        """Their two fields, spelled their way, with count agreeing with files."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert isinstance(result["files"], list)
        assert result["count"] == len(result["files"])

    def test_untracked_files_are_not_changes_on_a_card(self, fake_repo: dict) -> None:
        """The desktop asks `diff HEAD`, which cannot see a file git never has."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert "brand_new.py" not in result["files"]
        assert result["count"] == 3

    def test_paths_are_branch_local_not_repo_relative(self, fake_repo: dict) -> None:
        """Their --relative, reproduced."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert "hello.txt" in result["files"]
        assert "nested/deep.txt" in result["files"]
        assert not any(path.startswith("src/") for path in result["files"])

    def test_a_rename_is_reported_at_the_name_it_has_now(self, fake_repo: dict) -> None:
        """Porcelain renders a rename as 'old -> new' on one line."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert "new_name.py" in result["files"]
        assert not any("->" in path for path in result["files"])

    def test_the_header_and_footer_are_not_files(self, fake_repo: dict) -> None:
        """drone frames the list with prose. Prose is not a changed file."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert not any("file(s) changed" in path for path in result["files"])
        assert not any("showing demo scope" in path for path in result["files"])

    def test_a_clean_branch_is_zero_and_not_an_error(self, fake_repo: dict) -> None:
        """Nothing changed is an answer, and the commonest one."""
        clean = status_document((), message="0 file(s) changed under src/aipass/demo")

        with patch.object(subprocess, "run", return_value=self._completed(stdout=clean)):
            result = host_git.read_git_changes("demo")

        assert result == {
            "branch": "demo",
            "grain": "branch",
            "files": [],
            "count": 0,
            "untracked": 0,
            "rows": [],
        }


class TestGitChangesCoalescesTheStampede:
    """The 2026-09-07 cure: one screen's worth of cards costs one exec per
    distinct question, not one per card."""

    # N concurrent subprocesses fight over one machine, so the cure is single-flight plus TTL, not a longer timeout.

    def _completed(self, stdout: str = GIT_STATUS_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_concurrent_callers_asking_the_same_question_share_one_subprocess(self, fake_repo: dict) -> None:
        """Thirty-one cards, one exec. The stampede itself, pinned."""
        # SLOW, not a barrier: only one thread is ever inside the subprocess, so a 31-way barrier never releases.
        entered = threading.Event()

        def slow(*_args: Any, **_kwargs: Any) -> Any:
            entered.set()
            time.sleep(0.4)
            return self._completed()

        with patch.object(subprocess, "run", side_effect=slow) as mock_run:
            with cf.ThreadPoolExecutor(max_workers=31) as pool:
                futures = [pool.submit(host_git.read_git_changes, "demo") for _ in range(31)]
                answers = [f.result(timeout=30) for f in futures]

        assert entered.is_set(), "the first flight must actually have run"
        assert len(answers) == 31, "every caller must get an answer"
        assert mock_run.call_count == 1, "thirty-one cards must not mean thirty-one subprocesses"

    def test_a_second_read_inside_the_ttl_runs_nothing(self, fake_repo: dict) -> None:
        """The other half: a re-poll within the window costs no exec at all."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo")
            host_git.read_git_changes("demo")

        assert mock_run.call_count == 1

    def test_an_expired_entry_is_read_again_rather_than_served_stale(self, fake_repo: dict) -> None:
        """A cache that never expires is a lane that lies about a tree that moved."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo")
            key = ("demo", "", "branch")
            stored_at, answer = host_git._changes._entries[key]
            host_git._changes._entries[key] = (stored_at - (host_git.GIT_CHANGES_TTL_SECONDS + 1), answer)
            host_git.read_git_changes("demo")

        assert mock_run.call_count == 2

    def test_one_callers_edit_to_a_row_does_not_reach_the_next_caller(self, fake_repo: dict) -> None:
        """A cached answer is handed out as a COPY, and this pin exists because a
        mutation proved it was not protected."""
        # THREE reads: a miss gets the producer's own object, so only the second HIT proves the copy on the way out.
        with patch.object(subprocess, "run", return_value=self._completed()):
            first = host_git.read_git_changes("demo")
            assert first["rows"], "the fixture must produce at least one row to mutate"

            first["rows"][0]["path"] = "clobbered-on-the-way-in"

            second = host_git.read_git_changes("demo")
            assert second["rows"][0]["path"] != "clobbered-on-the-way-in", (
                "the answer was stored by reference — the caller that filled the cache can still edit it"
            )

            second["rows"][0]["path"] = "clobbered-on-the-way-out"
            second["files"].append("clobbered-on-the-way-out")

            third = host_git.read_git_changes("demo")

        assert third["rows"][0]["path"] != "clobbered-on-the-way-out", (
            "the third caller was served the second caller's edit — the cache is handing out its own object"
        )
        assert "clobbered-on-the-way-out" not in third["files"], (
            "the file list is shared too, so one card's edit rewrites the next card's list"
        )

    def test_different_branches_are_not_queued_behind_each_other(self, fake_repo: dict) -> None:
        """The flight lock is PER KEY. A global one would turn the stampede into a
        queue — every card correct, every card late."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo")
            host_git.read_git_changes("demo", grain="repo")

        assert mock_run.call_count == 2, "branch and repo grain are different questions"

    def test_one_branch_name_in_two_projects_is_two_cache_entries(self, fake_repo: dict, tmp_path: Path) -> None:
        """The PROJECT is part of the key, and this pin exists because a mutation
        proved it was not protected: a branch NAME is not unique across projects."""
        foreign = tmp_path / "OtherRepo"
        (foreign / ".git").mkdir(parents=True)
        foreign_root = foreign / "src" / "other" / "demo"
        foreign_root.mkdir(parents=True)

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "demo", "path": str(foreign_root)}

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
                host_git.read_git_changes("demo")
                host_git.read_git_changes("demo", project="OTHER")

        assert mock_run.call_count == 2, "the same branch name in two projects is two different questions"

    def test_a_failed_read_is_never_stored_in_the_cache(self, fake_repo: dict) -> None:
        """Only a good answer is stored, so no branch is served a remembered
        failure once its read starts working again."""
        # On the CACHE, not a second exec: refusals.py's own memory decides re-execs, and would be pinned by accident.
        broken = self._completed(stdout="not a json object", returncode=1, stderr="boom")

        with patch.object(subprocess, "run", return_value=broken):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")

        assert host_git._changes._entries == {}, "a failure must never be stored as an answer"

    def test_callers_queued_behind_a_failed_flight_share_its_failure(self, fake_repo: dict) -> None:
        """The half of the promise nothing pinned, measured false 2026-09-25."""
        # refusals.py does not remember a timeout, so without sharing, N queued callers cost N serial 30s execs.
        callers = 8
        arrivals = []
        all_queued = threading.Event()
        real_flight_lock = host_git._changes._flight_lock

        class CountedFlight:
            """The real per-key lock, counting who reached it."""

            def __init__(self, lock: Any) -> None:
                self._lock = lock

            def __enter__(self) -> Any:
                arrivals.append(threading.get_ident())
                if len(arrivals) == callers:
                    all_queued.set()
                return self._lock.__enter__()

            def __exit__(self, *exc: Any) -> Any:
                return self._lock.__exit__(*exc)

        def stalled(*_args: Any, **_kwargs: Any) -> Any:
            all_queued.wait(timeout=10)
            raise subprocess.TimeoutExpired("drone", 30)

        with (
            patch.object(host_git._changes, "_flight_lock", lambda key: CountedFlight(real_flight_lock(key))),
            patch.object(subprocess, "run", side_effect=stalled) as mock_run,
            cf.ThreadPoolExecutor(max_workers=callers) as pool,
        ):
            futures = [pool.submit(host_git.read_git_changes, "demo") for _ in range(callers)]
            outcomes = [type(future.exception(timeout=30)) for future in futures]

        assert all_queued.is_set(), "every caller must have queued behind the stalled flight"
        assert outcomes == [host_reads.ReadUnavailable] * callers, "every queued caller must be told the failure"
        assert mock_run.call_count == 1, "eight callers behind one stall must not mean eight stalls"

    def test_a_caller_arriving_after_a_failed_flight_reads_again(self, fake_repo: dict) -> None:
        """Sharing is for the callers who were WAITING, never a remembered refusal."""
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)) as mock_run:
            for _ in range(2):
                with pytest.raises(host_reads.ReadUnavailable):
                    host_git.read_git_changes("demo")

        assert mock_run.call_count == 2

        # A recovered key lets go of its failure, so no traceback is held for the life of the server.
        with patch.object(subprocess, "run", return_value=self._completed()):
            assert host_git.read_git_changes("demo")["branch"] == "demo"

        assert host_git._changes._failures == {}, "a recovered key must not keep its old failure"

    def test_a_failed_flight_names_its_cache_key_in_the_log(self, fake_repo: dict) -> None:
        """6b7f72e9's same-second twins logged one root each: only the key can say if two keys ran."""
        with (
            patch(PATCH_CACHE_LOGGER) as log,
            patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)),
            pytest.raises(host_reads.ReadUnavailable),
        ):
            host_git.read_git_changes("demo", project="AIPASS")

        message, *values = log.warning.call_args.args
        assert "('demo', 'AIPASS', 'branch')" in message % tuple(values)


class TestGitStaysDroneOnlyOnThisLaneToo:
    """Git is drone-only in this system, servers included — the same house rule
    the diff lane above is built on."""

    def _completed(self, stdout: str = GIT_STATUS_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_routes_through_drone_not_raw_git(self, fake_repo: dict) -> None:
        """The command is drone's, never git's."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo")

        assert mock_run.call_args[0][0] == ["drone", "@git", "status", "--json"]

    def test_runs_in_the_branch_directory(self, fake_repo: dict) -> None:
        """drone's git lane is CWD-scoped, so the cwd IS the branch selection."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo")

        assert mock_run.call_args.kwargs["cwd"] == str(fake_repo["branch"].resolve())

    def test_missing_drone_raises_unavailable(self, fake_repo: dict) -> None:
        """No drone on PATH is an honest 503, not a badge reading zero."""
        with patch.object(subprocess, "run", side_effect=FileNotFoundError("no drone")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")

    def test_timeout_raises_unavailable(self, fake_repo: dict) -> None:
        """A hung status must not hang the request forever."""
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")

    def test_a_timeout_says_which_directory_it_was_reading(self, fake_repo: dict) -> None:
        """a6a71c2d fired three times in two weeks naming only the lane, so neither
        occurrence could say WHICH card went dark."""
        # The phone's refusal carries no host path; the log is where a path belongs.
        with patch(PATCH_GIT_LOGGER) as log:
            with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)):
                with pytest.raises(host_reads.ReadUnavailable) as refused:
                    host_git.read_git_changes("demo")

        message, *values = log.error.call_args.args
        assert str(fake_repo["branch"].resolve()) in message % tuple(values)
        assert str(fake_repo["branch"].resolve()) not in str(refused.value)

    def test_a_failed_status_is_never_read_as_a_clean_tree(self, fake_repo: dict) -> None:
        """drone learned this one the hard way and says so in their own source: a
        failed `git status` now exits 1 with the reason on stderr, so a zero count must only mean zero."""
        with patch.object(
            subprocess,
            "run",
            return_value=self._completed(stdout="", returncode=1, stderr="git status error: bad object HEAD"),
        ):
            with pytest.raises(host_reads.ReadUnavailable) as excinfo:
                host_git.read_git_changes("demo")

        assert "bad object HEAD" in str(excinfo.value)

    def test_a_caller_drone_will_not_verify_is_reported_in_drones_words(self, fake_repo: dict) -> None:
        """THE measured limit of this lane, and the reason it is not hidden."""
        # drone refuses a cwd with no passport; an empty change list would paint the branch clean, unmeasured.
        foreign = Path(fake_repo["branch"]).parent / "projects" / "baud" / "src" / "baud"
        refusal = (
            f"No .trinity/passport.json found in directory hierarchy (caller cwd: {foreign}) — cannot verify caller"
        )

        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1, stderr=refusal)):
            with pytest.raises(host_reads.ReadUnavailable) as excinfo:
                host_git.read_git_changes("demo")

        assert "cannot verify caller" in str(excinfo.value)


class TestGitChangesFollowsTheReadDoctrine:
    """Same two doors as every other read: the seat resolves through the local
    citizen registry, a foreign project through @baud's census."""

    def test_an_unknown_branch_never_reaches_a_subprocess(self, fake_repo: dict) -> None:
        """Refused before spawn, exactly like the file and diff lanes."""
        with patch.object(subprocess, "run") as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_git_changes("ghost")

        mock_run.assert_not_called()

    def test_a_missing_branch_name_is_refused(self, fake_repo: dict) -> None:
        """There is no current branch to infer from a phone."""
        with pytest.raises(host_reads.ReadRefused):
            host_git.read_git_changes("")


class TestGitChangesInAForeignProject:
    """A FOREIGN PROJECT'S ROWS MUST BE BRANCH-LOCAL TOO: `repo_root()` is the
    SEAT's root, so stripping against it leaves a foreign branch's rows repo-relative."""

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
        """drone prints paths relative to the repo it found; the prefix to strip is
        that branch's own repository root, discovered rather than assumed."""
        stdout = status_document(
            (
                (" M", "src/vera_studio/vera/CLAUDE.md"),
                (" M", "src/vera_studio/vera/.aipass/local_system_prompt.md"),
            )
        )

        with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
            result = host_git.read_git_changes("vera", project="VERA-STUDIO")

        assert result["files"] == ["CLAUDE.md", ".aipass/local_system_prompt.md"]
        assert not any(path.startswith("src/") for path in result["files"])

    def test_the_seated_branch_is_unaffected(self, fake_repo: dict) -> None:
        """The seat resolved correctly before and must keep doing so."""
        stdout = status_document(((" M", "src/aipass/demo/hello.txt"),))

        with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
            result = host_git.read_git_changes("demo")

        assert result["files"] == ["hello.txt"]

    def test_a_nested_repository_inside_the_seat_is_stripped_against_the_inner_one(
        self, fake_repo: dict, tmp_path: Path
    ) -> None:
        """THE case the seat-first version got wrong: a nested .git inside the seat
        makes `relative_to(seat)` succeed with the wrong prefix, so discovery must win."""
        tenant = fake_repo["root"] / "projects" / "tenant"
        (tenant / ".git").mkdir(parents=True)
        root = tenant / "src" / "tenant" / "tenant"
        root.mkdir(parents=True)

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "tenant", "path": str(root)}

        stdout = status_document(((" M", "src/tenant/tenant/lib.rs"),))

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
                result = host_git.read_git_changes("tenant", project="TENANT")

        assert result["files"] == ["lib.rs"]

    def test_a_worktree_marker_is_a_file_and_still_marks_a_repository(self, fake_repo: dict, tmp_path: Path) -> None:
        """A worktree and a submodule carry '.git' as a FILE, not a directory."""
        project = tmp_path / "WorktreeRepo"
        root = project / "src" / "thing" / "br"
        root.mkdir(parents=True)
        (project / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt", encoding="utf-8")

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "br", "path": str(root)}

        stdout = status_document(((" M", "src/thing/br/main.py"),))

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
                result = host_git.read_git_changes("br", project="WT")

        assert result["files"] == ["main.py"]

    def test_a_branch_in_no_repository_at_all_keeps_drones_names(self, fake_repo: dict, tmp_path: Path) -> None:
        """No .git anywhere above it, so drone's names travel untouched rather than
        being trimmed on a guess."""
        loose = tmp_path / "Loose" / "src" / "thing" / "br"
        loose.mkdir(parents=True)

        census = MagicMock()
        census.FleetUnavailable = host_fleet.FleetUnavailable
        census.resolve_branch.return_value = {"name": "br", "path": str(loose)}

        stdout = status_document(((" M", "whatever/file.py"),))

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
                result = host_git.read_git_changes("br", project="LOOSE")

        assert result["files"] == ["whatever/file.py"]


class TestRepoGrainChanges:
    """The git APP is per-repo; the agent card's git tile is per-branch, and the
    answer has to NAME which grain it is so a client cannot read it at the wrong one."""

    def _completed(self, stdout: str = GIT_STATUS_ALL_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_repo_grain_asks_drone_for_the_whole_repo(self, fake_repo: dict) -> None:
        """--all is what makes drone target the repo root instead of the branch."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo", grain="repo")

        assert "--all" in mock_run.call_args[0][0]

    def test_branch_grain_never_asks_for_the_whole_repo(self, fake_repo: dict) -> None:
        """The card's question is unchanged — no --all leaks into the old grain."""
        with patch.object(subprocess, "run", return_value=self._completed(GIT_STATUS_STDOUT)) as mock_run:
            host_git.read_git_changes("demo")

        assert "--all" not in mock_run.call_args[0][0]

    def test_the_answer_names_its_own_grain(self, fake_repo: dict) -> None:
        """Both grains say which they are, so a client cannot mistake them."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            wide = host_git.read_git_changes("demo", grain="repo")
        with patch.object(subprocess, "run", return_value=self._completed(GIT_STATUS_STDOUT)):
            narrow = host_git.read_git_changes("demo")

        assert wide["grain"] == "repo"
        assert narrow["grain"] == "branch"

    def test_repo_grain_keeps_repo_relative_names(self, fake_repo: dict) -> None:
        """THE BUG THIS PINS: stripping a branch prefix at repo grain would eat the
        part that distinguishes one branch's file from another's."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo", grain="repo")

        assert "src/aipass/demo/hello.txt" in result["files"]
        assert "src/aipass/other/thing.py" in result["files"]

    def test_repo_grain_reaches_beyond_the_anchor_branch(self, fake_repo: dict) -> None:
        """The whole point: files from branches other than the anchor arrive."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo", grain="repo")

        assert result["count"] == 3
        assert any("third" in name for name in result["files"])

    def test_untracked_still_rides_as_a_count_at_repo_grain(self, fake_repo: dict) -> None:
        """One doctrine, both grains — tracked core, untracked additive."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo", grain="repo")

        assert result["untracked"] == 1
        assert not any("brand_new" in name for name in result["files"])

    def test_an_unknown_grain_is_refused_naming_both(self, fake_repo: dict) -> None:
        """A typo'd grain must never quietly fall back to a scope the caller did
        not ask for."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_git_changes("demo", grain="everything")

        assert "branch" in str(caught.value) and "repo" in str(caught.value)

    def test_grain_is_refused_before_drone_is_ever_run(self, fake_repo: dict) -> None:
        """Garbage is refused before spawn — the standing rule on every lane."""
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            with pytest.raises(host_reads.ReadRefused):
                host_git.read_git_changes("demo", grain="REPOSITORY")

        assert mock_run.call_count == 0


# Columns are index-then-worktree: 'A ' and ' M' are DIFFERENT answers that collapse if either is stripped.
GIT_STATUS_CODES_STDOUT = status_document(
    (
        (" M", "src/aipass/demo/modified.txt"),
        ("A ", "src/aipass/demo/staged_new.py"),
        ("MM", "src/aipass/demo/both.py"),
        (" D", "src/aipass/demo/gone.txt"),
        ("R ", "src/aipass/demo/old.py -> src/aipass/demo/new.py"),
        ("??", "src/aipass/demo/untracked.py"),
        ("!!", "src/aipass/demo/ignored.log"),
    ),
    message="6 file(s) changed under src/aipass/demo",
)


class TestStatusPerRow:
    """Each row carries git's OWN code, verbatim and unstripped: mapping a code
    to a chip letter is the face's call (their buildRows), never this server's."""

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
            result = host_git.read_git_changes("demo")

        assert self._rows(result)["modified.txt"] == " M"

    def test_a_staged_new_file_is_distinguishable_from_a_modified_one(self, fake_repo: dict) -> None:
        """THE EXACT GAP THEY MEASURED: index-A and worktree-M stay two answers."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["staged_new.py"] == "A "
        assert rows["modified.txt"] == " M"
        assert rows["staged_new.py"] != rows["modified.txt"]

    def test_both_columns_survive_when_both_are_set(self, fake_repo: dict) -> None:
        """Staged AND unstaged changes to one file is one row with two codes."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["both.py"] == "MM"

    def test_untracked_files_arrive_by_name_not_only_as_a_count(self, fake_repo: dict) -> None:
        """The face cannot paint a U chip on a file whose name it was never told."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert self._rows(result)["untracked.py"] == "??"

    def test_the_tracked_list_is_unchanged_by_all_of_this(self, fake_repo: dict) -> None:
        """THE ADDITIVE PROMISE: @baud's desktop parses `files` and `count`, so
        untracked stays OUT of them and is reported beside them instead."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert "untracked.py" not in result["files"]
        assert result["count"] == len(result["files"]) == 5
        assert result["untracked"] == 1

    def test_ignored_files_are_in_no_list_at_all(self, fake_repo: dict) -> None:
        """Ignored is not a change. It was never in files; it is not a row either."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert "ignored.log" not in self._rows(result)
        assert "ignored.log" not in result["files"]

    def test_a_rename_row_names_the_file_it_is_now(self, fake_repo: dict) -> None:
        """The arrow never reaches a filename, or a tapped row asks for no file."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["new.py"] == "R "
        assert not any(" -> " in path for path in rows)

    def test_rows_and_files_agree_on_the_tracked_paths(self, fake_repo: dict) -> None:
        """Two views of one measurement, never two measurements."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        tracked_rows = [r["path"] for r in result["rows"] if r["status"].strip() != "??"]
        assert sorted(tracked_rows) == sorted(result["files"])

    def test_rows_ride_the_repo_grain_too(self, fake_repo: dict) -> None:
        """Repo grain keeps repo-relative names here too: one parser, no drift."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo", grain="repo")

        rows = self._rows(result)
        assert rows["src/aipass/demo/staged_new.py"] == "A "
        assert rows["src/aipass/demo/untracked.py"] == "??"

    def test_the_status_is_never_reinterpreted_into_a_letter(self, fake_repo: dict) -> None:
        """D0: this server owns the pipe and never the meaning."""
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert all(len(row["status"]) == 2 for row in result["rows"])


class TestStagedAndUnstagedAreDifferentAnswers:
    """drone's rendered line right-aligns `status.strip()` into the SECOND column,
    so 'M ' and ' M' render identically; only the JSON document keeps them apart."""

    def _completed(self, stdout: str, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def _rows(self, result: dict) -> dict:
        return {row["path"]: row for row in result["rows"]}

    STAGED_AND_UNSTAGED = (
        ("M ", "src/aipass/demo/staged.py"),
        (" M", "src/aipass/demo/unstaged.py"),
    )

    def test_a_staged_modification_and_an_unstaged_one_are_not_the_same_row(self, fake_repo: dict) -> None:
        """THE PIN: one file edited and added, one edited and not, are two rows."""
        document = status_document(self.STAGED_AND_UNSTAGED)

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["staged.py"]["status"] != rows["unstaged.py"]["status"]

    def test_the_staged_one_says_staged_in_gits_own_spelling(self, fake_repo: dict) -> None:
        """Not merely different — right. The index column is where git put it."""
        document = status_document(self.STAGED_AND_UNSTAGED)

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["staged.py"]["status"] == "M "
        assert rows["unstaged.py"]["status"] == " M"

    def test_the_two_columns_arrive_split_as_well_as_whole(self, fake_repo: dict) -> None:
        """The split rides beside the verbatim code so two faces cannot slice it differently."""
        document = status_document(self.STAGED_AND_UNSTAGED)

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["staged.py"]["index"] == "M"
        assert rows["staged.py"]["worktree"] == " "
        assert rows["unstaged.py"]["index"] == " "
        assert rows["unstaged.py"]["worktree"] == "M"

    def test_a_staged_delete_is_not_an_unstaged_delete(self, fake_repo: dict) -> None:
        """The same collapse, on the code a phone most needs to get right."""
        document = status_document(
            (
                ("D ", "src/aipass/demo/removed_and_staged.py"),
                (" D", "src/aipass/demo/removed_only.py"),
            )
        )

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["removed_and_staged.py"]["index"] == "D"
        assert rows["removed_only.py"]["worktree"] == "D"
        assert rows["removed_and_staged.py"]["status"] != rows["removed_only.py"]["status"]

    def test_a_file_staged_and_then_edited_again_carries_both_columns(self, fake_repo: dict) -> None:
        """'MM' is the one code the rendered surface DID survive; it must keep working."""
        document = status_document((("MM", "src/aipass/demo/both.py"),))

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["both.py"]["index"] == "M"
        assert rows["both.py"]["worktree"] == "M"

    def test_the_split_is_derived_from_the_code_when_the_door_omits_it(self, fake_repo: dict) -> None:
        """An older drone answers with `status` and no columns; those columns ARE the code."""
        document = json.dumps(
            {
                "ok": True,
                "branch": "demo",
                "scope": "branch",
                "files": [{"status": "A ", "path": "src/aipass/demo/new.py"}],
                "total": 1,
                "message": "1 file(s) changed",
            }
        )

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["new.py"]["index"] == "A"
        assert rows["new.py"]["worktree"] == " "

    def test_the_rendered_surface_could_not_have_carried_this(self, fake_repo: dict) -> None:
        """THE EVIDENCE, KEPT: why this lane must never read drone's screen output again."""
        rendered = ["  %s %s" % (status.strip().rjust(2), path) for status, path in self.STAGED_AND_UNSTAGED]

        assert rendered[0][:4] == rendered[1][:4]
        assert len({line.split(" ")[-2] for line in rendered}) == 1


class TestTheStatusDoorsVerdictIsHonoured:
    """The refusal split: a document saying `ok: false` is an answer (400, their
    words); output that is not a document at all is a could-not-tell (503)."""

    def _completed(self, stdout: str, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_a_refusing_document_is_the_callers_answer(self, fake_repo: dict) -> None:
        """Their sentence, verbatim, at 400 — not a retry-later at 503."""
        refusal = status_document((), ok=False, message="git status error: not a git repository")

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_git_changes("demo")

        assert "not a git repository" in str(caught.value)

    def test_a_refusal_with_no_words_still_refuses_and_says_that(self, fake_repo: dict) -> None:
        """Inventing a reason is not this server's to do; saying they gave none is a fact."""
        refusal = json.dumps({"ok": False, "files": [], "total": 0})

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_git_changes("demo")

        assert "without saying why" in str(caught.value)

    def test_a_true_verdict_is_never_read_off_the_exit_code(self, fake_repo: dict) -> None:
        """THE VERDICT IS THEIRS TO GIVE: ok with a non-zero exit is still an answer."""
        document = status_document(((" M", "src/aipass/demo/hello.txt"),))

        with patch.object(subprocess, "run", return_value=self._completed(document, returncode=1)):
            result = host_git.read_git_changes("demo")

        assert result["count"] == 1

    def test_a_json_array_is_not_a_document(self, fake_repo: dict) -> None:
        """One JSON OBJECT or nothing: a list parses cleanly but carries no verdict."""
        with patch.object(subprocess, "run", return_value=self._completed("[]")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")

    def test_a_half_written_document_is_a_could_not_tell(self, fake_repo: dict) -> None:
        """A truncated answer is not a small answer."""
        with patch.object(subprocess, "run", return_value=self._completed('{"ok": true, "files": [')):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")


class TestARefusedRootIsNotReAskedEveryFiveSeconds:
    """A phone polls every 5 seconds; a root drone refuses must not spawn and warn on every poll.

    WHAT IS REMEMBERED IS DRONE'S ANSWER, NOT DRONE'S RULE: checking for a passport here would
    reimplement drone's auth and drift from it. The refusal is kept for a short window only."""

    def _completed(self, stdout: str, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def _refused(self) -> Any:
        """What drone's caller-verification refusal looks like: no document, reason on stderr."""
        return self._completed("", returncode=1, stderr="No .trinity/passport.json found (caller cwd: /x)")

    def test_the_second_poll_does_not_spawn_a_second_subprocess(self, fake_repo: dict) -> None:
        """The whole point: one refusal answers the polls that follow it."""
        with patch.object(subprocess, "run", return_value=self._refused()) as ran:
            for _ in range(12):
                with pytest.raises(host_reads.ReadUnavailable):
                    host_git.read_git_changes("demo")

        assert ran.call_count == 1, f"a minute of polling spawned {ran.call_count} subprocesses"

    def test_the_remembered_refusal_still_says_what_drone_said(self, fake_repo: dict) -> None:
        """A cached refusal that loses the reason is worse than the spam."""
        with patch.object(subprocess, "run", return_value=self._refused()):
            with pytest.raises(host_reads.ReadUnavailable) as first:
                host_git.read_git_changes("demo")
            with pytest.raises(host_reads.ReadUnavailable) as second:
                host_git.read_git_changes("demo")

        assert "passport.json" in str(first.value)
        assert str(second.value) == str(first.value)

    def test_only_the_first_refusal_is_logged(self, fake_repo: dict) -> None:
        """Two branches' logs stop filling. This is the reported symptom."""
        with patch(PATCH_GIT_LOGGER) as log:
            with patch.object(subprocess, "run", return_value=self._refused()):
                for _ in range(12):
                    with pytest.raises(host_reads.ReadUnavailable):
                        host_git.read_git_changes("demo")

        assert log.warning.call_count == 1, f"12 polls wrote {log.warning.call_count} warnings"

    def test_the_root_recovers_on_its_own_when_the_window_passes(self, fake_repo: dict) -> None:
        """A remembered refusal MUST expire, or a passport arriving is invisible."""
        clock = [1000.0]

        with patch.object(host_refusals.time, "monotonic", lambda: clock[0]):
            with patch.object(subprocess, "run", return_value=self._refused()) as ran:
                with pytest.raises(host_reads.ReadUnavailable):
                    host_git.read_git_changes("demo")

                clock[0] += host_refusals.REFUSAL_TTL_SECONDS + 1

                with pytest.raises(host_reads.ReadUnavailable):
                    host_git.read_git_changes("demo")

        assert ran.call_count == 2, "the window expired and the door was still not re-asked"

    def test_a_root_that_starts_working_is_answered_normally(self, fake_repo: dict) -> None:
        """Recovery is not just a re-ask — it has to produce the real answer."""
        clock = [1000.0]
        document = status_document(((" M", "src/aipass/demo/hello.txt"),))

        with patch.object(host_refusals.time, "monotonic", lambda: clock[0]):
            with patch.object(subprocess, "run", return_value=self._refused()):
                with pytest.raises(host_reads.ReadUnavailable):
                    host_git.read_git_changes("demo")

            clock[0] += host_refusals.REFUSAL_TTL_SECONDS + 1

            with patch.object(subprocess, "run", return_value=self._completed(document)):
                result = host_git.read_git_changes("demo")

        assert result["count"] == 1

    def test_a_refusing_document_is_never_remembered(self, fake_repo: dict) -> None:
        """`ok: false` is a live git answer that can change with the next edit, so it is never cached."""
        refusal = status_document((), ok=False, message="git status error: not a git repository")

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)) as ran:
            for _ in range(3):
                with pytest.raises(host_reads.ReadRefused):
                    host_git.read_git_changes("demo")

        assert ran.call_count == 3, "a live git answer was cached as if the root were unreadable"

    def test_one_lanes_silence_does_not_mute_another(self, fake_repo: dict) -> None:
        """Memory is per (root, lane), not per root.

        Keyed on root alone, one lane broken for its OWN reason would mute the working lanes.
        """
        with patch.object(subprocess, "run", return_value=self._refused()) as ran:
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_log("demo")

        assert ran.call_count == 2
