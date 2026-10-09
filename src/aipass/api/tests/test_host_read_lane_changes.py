# =================== AIPass ====================
# Name: test_host_read_lane_changes.py
# Description: Tests for the read lane's git-changes lane — the card contract, the stampede, grains, rows, refusals
# Version: 1.0.1
# Created: 2026-10-08
# Modified: 2026-10-09
# =============================================

"""Tests for read_git_changes() in apps/handlers/host/git_reads.py and its cache and refusal memory."""

# Split out of test_host_read_lane.py along the unit under test (api, the
# oversize split leg, 2026-10-08): the git-changes lane end to end below the
# route — @baud's card contract, the single-flight cache, drone-only routing,
# foreign projects, both grains, git's two-column codes, the door's verdict,
# and the remembered refusal. The route itself is pinned in
# test_host_read_lane.py; per-file diffs, history and the remote in
# test_host_read_lane_history.py.

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

# The patch targets stay this file's own constants rather than conftest's:
# seedgo's discarded_patch rule reads a target imported from this branch's
# package as one it judges, and the loggers are silenced on purpose.
PATCH_GIT_LOGGER = "aipass.api.apps.handlers.host.git_reads.logger"
PATCH_CACHE_LOGGER = "aipass.api.apps.handlers.host.read_cache.logger"
PATCH_HOST_FLEET = "aipass.api.apps.handlers.host.fleet"

# Every case here calls read_git_changes, which answers from its cache.
pytestmark = pytest.mark.usefixtures("_clean_git_changes_cache")


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
            result = host_git.read_git_changes("demo")

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
            result = host_git.read_git_changes("demo")

        assert "brand_new.py" not in result["files"]
        assert result["count"] == 3

    def test_paths_are_branch_local_not_repo_relative(self, fake_repo: dict) -> None:
        """
        Their --relative, reproduced.

        Every src/aipass branch shares one repo, so a repo-relative name on a
        card would prefix every row with the same nine characters and push the
        part that differs off a phone screen.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

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
    """
    The 2026-09-07 cure: one screen's worth of cards costs one exec per
    distinct question, not one per card.

    The phone asks /v1/git-changes once per branch and fires them together.
    Every one of those used to reach its own `drone @git status --json`; on
    2026-09-07 at 12:17:03 thirty-one crossed the 30s timeout in the same
    second. Measured on that host: one call 0.5s, 31 concurrent 17.9s — N
    subprocesses fighting over one machine, which is why the cure is the
    single-flight-plus-TTL fleet.py already proves and NOT a longer timeout.
    """

    def _completed(self, stdout: str = GIT_STATUS_STDOUT, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_concurrent_callers_asking_the_same_question_share_one_subprocess(self, fake_repo: dict) -> None:
        """
        Thirty-one cards, one exec. The stampede itself, pinned.

        The read is made SLOW rather than synchronised on a barrier: a barrier
        across all thirty-one can never release here, because only one thread
        is ever inside the subprocess — which is the property under test. A
        slow first flight is what gives the other thirty time to arrive, queue
        on the lock, and be served by the re-check inside it.
        """
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
        """
        A cache that never expires is a lane that lies about a tree that moved.

        The TTL is aged out directly rather than slept through: a test that
        waits 1.5s to prove a 1.5s window is a test nobody runs.
        """
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo")
            key = ("demo", "", "branch")
            stored_at, answer = host_git._changes._entries[key]
            host_git._changes._entries[key] = (stored_at - (host_git.GIT_CHANGES_TTL_SECONDS + 1), answer)
            host_git.read_git_changes("demo")

        assert mock_run.call_count == 2

    def test_one_callers_edit_to_a_row_does_not_reach_the_next_caller(self, fake_repo: dict) -> None:
        """
        A cached answer is handed out as a COPY, and this pin exists because a
        mutation proved it was not protected.

        The answer carries `rows` — a list of mutable dicts. Returning the
        stored object lets whoever edits a row edit it for everyone until the
        TTL runs out: not a crash, just a card quietly showing another card's
        text. Returning `answer` in place of the deep copy survived the whole
        suite when it was mutated in, including the five cases above, because
        every one of them counts execs rather than reading what came back.

        THREE reads, not two, and the number is the whole point. The caller
        that MISSES is handed the producer's own object while a copy goes into
        the store, so its edits cannot reach anyone — two reads therefore pass
        against a cache that copies on the way in and shares on the way out.
        It is the second HIT that proves the read path: caller two edits what
        it was given, and caller three is what notices.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            first = host_git.read_git_changes("demo")
            assert first["rows"], "the fixture must produce at least one row to mutate"

            # The way IN: the miss returns the producer's object, so this edit
            # must not have reached the entry that was stored.
            first["rows"][0]["path"] = "clobbered-on-the-way-in"

            second = host_git.read_git_changes("demo")
            assert second["rows"][0]["path"] != "clobbered-on-the-way-in", (
                "the answer was stored by reference — the caller that filled the cache can still edit it"
            )

            # The way OUT: this one was served FROM the store.
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
        """
        The flight lock is PER KEY. A global one would turn the stampede into a
        queue — every card correct, every card late, which on a phone is the
        same complaint wearing better manners.
        """
        with patch.object(subprocess, "run", return_value=self._completed()) as mock_run:
            host_git.read_git_changes("demo")
            host_git.read_git_changes("demo", grain="repo")

        assert mock_run.call_count == 2, "branch and repo grain are different questions"

    def test_one_branch_name_in_two_projects_is_two_cache_entries(self, fake_repo: dict, tmp_path: Path) -> None:
        """
        The PROJECT is part of the key, and this pin exists because a mutation
        proved it was not protected.

        The brief specified single-flight per (branch, grain). Keying on that
        literally is wrong: a branch NAME is not unique across projects, so the
        seat's 'demo' and a foreign project's 'demo' would share one entry and
        one card would be served the other's change list. Dropping `project`
        from the key survived the whole suite when it was mutated in — nothing
        anywhere could tell. That is an unpinned contract, not dead code, so it
        is pinned here rather than left to the next reader to rediscover.
        """
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
        """
        Only a good answer is stored, so no branch is served a remembered
        failure once its read starts working again.

        This asserts on the CACHE rather than on a second subprocess, and the
        distinction is real: `refusals.py` keeps its own deliberate memory of
        an unreadable root to stop a broken tree writing the same sentence to
        the log on every poll. That mechanism — not this one — is what decides
        whether a second call re-execs. Pinning a second exec here would be
        pinning refusals.py's behaviour through this lane by accident, and
        would go red the day that module tuned its own window.
        """
        broken = self._completed(stdout="not a json object", returncode=1, stderr="boom")

        with patch.object(subprocess, "run", return_value=broken):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")

        assert host_git._changes._entries == {}, "a failure must never be stored as an answer"

    def test_callers_queued_behind_a_failed_flight_share_its_failure(self, fake_repo: dict) -> None:
        """
        The half of the promise nothing pinned, measured false 2026-09-25.

        Every caller queued behind a flight that TIMED OUT used to run its own
        subprocess the moment the lock came free — so under a stall, one card
        re-polled N times cost N serial 30s execs, each waiter holding a server
        thread for its own wait plus everyone's ahead of it. A timeout is not
        remembered by refusals.py, so nothing else stopped it. Queued callers
        get the flight's own failure; nobody waits out a second 30s for it.
        """
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
            # The flight stalls until every other caller is queued behind it —
            # the stall is the real condition, not a guess at how long it takes.
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
        """
        Sharing is for the callers who were WAITING, never a remembered refusal.

        A timeout is released with its flight: the next poll after it runs a
        fresh read, so a stall that has cleared is not refused for a moment
        longer than it lasted.
        """
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)) as mock_run:
            for _ in range(2):
                with pytest.raises(host_reads.ReadUnavailable):
                    host_git.read_git_changes("demo")

        assert mock_run.call_count == 2

        # And a key that recovers lets go of its last failure: the exception
        # and its traceback are not held for the life of the server.
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
        """
        a6a71c2d fired three times in two weeks naming only the lane, so neither
        occurrence could say WHICH card went dark — every request on this route
        runs the same command and differs only by the directory it runs in.

        The phone's sentence stays as it was: a refusal that travels to a
        handset carries no host path, and the log is where a path belongs.
        """
        with patch(PATCH_GIT_LOGGER) as log:
            with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("drone", 30)):
                with pytest.raises(host_reads.ReadUnavailable) as refused:
                    host_git.read_git_changes("demo")

        message, *values = log.error.call_args.args
        assert str(fake_repo["branch"].resolve()) in message % tuple(values)
        assert str(fake_repo["branch"].resolve()) not in str(refused.value)

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
                host_git.read_git_changes("demo")

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
        foreign = Path(fake_repo["branch"]).parent / "projects" / "baud" / "src" / "baud"
        refusal = (
            f"No .trinity/passport.json found in directory hierarchy (caller cwd: {foreign}) — cannot verify caller"
        )

        with patch.object(subprocess, "run", return_value=self._completed(stdout="", returncode=1, stderr=refusal)):
            with pytest.raises(host_reads.ReadUnavailable) as excinfo:
                host_git.read_git_changes("demo")

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
                host_git.read_git_changes("ghost")

        mock_run.assert_not_called()

    def test_a_missing_branch_name_is_refused(self, fake_repo: dict) -> None:
        """There is no current branch to infer from a phone."""
        with pytest.raises(host_reads.ReadRefused):
            host_git.read_git_changes("")


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

        stdout = status_document(((" M", "src/tenant/tenant/lib.rs"),))

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
                result = host_git.read_git_changes("tenant", project="TENANT")

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

        stdout = status_document(((" M", "src/thing/br/main.py"),))

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
                result = host_git.read_git_changes("br", project="WT")

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

        stdout = status_document(((" M", "whatever/file.py"),))

        with patch(PATCH_HOST_FLEET, census):
            with patch.object(host_git.subprocess, "run", return_value=self._completed(stdout)):
                result = host_git.read_git_changes("br", project="LOOSE")

        assert result["files"] == ["whatever/file.py"]


# =============================================
# THE GIT APP — repo grain, per-file, and history
# =============================================


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
        """
        THE BUG THIS PINS: the card strips a branch prefix to keep rows short.
        At repo grain the names already ARE repo-relative, so stripping would
        eat the part that distinguishes one branch's file from another's.
        """
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
        """
        A typo'd grain must never quietly fall back to a scope the caller did
        not ask for — that is how a phone shows one branch's changes while
        believing it shows a repo's.
        """
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


# Every code the face needs a chip for. The two columns are index-then-worktree,
# so 'A ' (staged new) and ' M' (modified, unstaged) are DIFFERENT answers that
# both collapse to one letter if either is stripped.
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
            result = host_git.read_git_changes("demo")

        assert self._rows(result)["modified.txt"] == " M"

    def test_a_staged_new_file_is_distinguishable_from_a_modified_one(self, fake_repo: dict) -> None:
        """
        THE EXACT GAP THEY MEASURED. Both columns travel, so index-A and
        worktree-M stay two different answers instead of collapsing to one
        letter — which is what made a new file look like an edited one.
        """
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
        """
        The other half of the rider: the face could not paint a U chip on a file
        whose name it had never been told.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        assert self._rows(result)["untracked.py"] == "??"

    def test_the_tracked_list_is_unchanged_by_all_of_this(self, fake_repo: dict) -> None:
        """
        THE ADDITIVE PROMISE, pinned. @baud's desktop consumer parses `files`
        and `count`; untracked must stay OUT of them however many rows exist,
        or the phone starts disagreeing with the desktop again.

        And matching the desktop must not mean hiding what was measured: a
        brand-new module is the most interesting change in a tree (@baud's own
        reasoning), so untracked is reported beside the contract rather than
        dropped (its own test retired as a duplicate of this one, api, fleet
        green leg 8).
        """
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
        """
        Same rule as the card's list: the arrow never reaches a filename, or a
        phone tapping the row asks for a file that cannot exist.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["new.py"] == "R "
        assert not any(" -> " in path for path in rows)

    def test_rows_and_files_agree_on_the_tracked_paths(self, fake_repo: dict) -> None:
        """
        Two views of one measurement, never two measurements. Every tracked file
        is a row, and every row that is not untracked is a tracked file.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo")

        tracked_rows = [r["path"] for r in result["rows"] if r["status"].strip() != "??"]
        assert sorted(tracked_rows) == sorted(result["files"])

    def test_rows_ride_the_repo_grain_too(self, fake_repo: dict) -> None:
        """
        The rider asks for both lanes. Repo grain keeps repo-relative names here
        as well — one parser, so there is no second place for them to drift.
        """
        with patch.object(subprocess, "run", return_value=self._completed()):
            result = host_git.read_git_changes("demo", grain="repo")

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
            result = host_git.read_git_changes("demo")

        assert all(len(row["status"]) == 2 for row in result["rows"])


class TestStagedAndUnstagedAreDifferentAnswers:
    """
    THE BUG THIS ROUND WAS FOR, and it was bigger than the brief said.

    Rows have carried git's two-column code verbatim since they existed, and
    that contract was right. The DATA was not. drone's rendered status line is
    built as `f"  {status.strip():>2} {path}"` — their own comment calls it "for
    the screen only" — which right-aligns a one-letter code into the SECOND
    column. So every index-only change reached this server already dressed as a
    worktree one, and no parser could have recovered it:

        git says 'M ' (staged edit)   -> rendered '   M' -> read as ' M'
        git says ' M' (unstaged edit) -> rendered '   M' -> read as ' M'
        git says 'A ' (staged new)    -> rendered '   A' -> read as ' A'
        git says 'D ' (staged delete) -> rendered '   D' -> read as ' D'

    Measured against the shipped parser on 2026-08-18, before the switch: of
    six codes fed through drone's own renderer, three came back as something
    git never said, and staged-vs-unstaged modify and staged-vs-unstaged delete
    were each a single answer. The face could not have built its chips from
    that, and neither could anything else.

    The document reports index and worktree separately. These tests pin the
    difference the old path could not express.
    """

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
        """
        THE PIN. One file edited and added, one file edited and not — two
        different facts about a repository, and for as long as this lane read
        rendered lines they arrived as one.
        """
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
        """
        What the four VS Code chips are actually derived from. The verbatim code
        stays because it is git's own answer; the split rides beside it because
        every consumer was going to do this slice anyway, and a slice done once
        here cannot be done differently by two faces.
        """
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
        """
        'MM' is the one code the rendered surface DID survive, because both its
        columns were already full. It must keep working — the fix must not have
        traded one collapse for another.
        """
        document = status_document((("MM", "src/aipass/demo/both.py"),))

        with patch.object(subprocess, "run", return_value=self._completed(document)):
            rows = self._rows(host_git.read_git_changes("demo"))

        assert rows["both.py"]["index"] == "M"
        assert rows["both.py"]["worktree"] == "M"

    def test_the_split_is_derived_from_the_code_when_the_door_omits_it(self, fake_repo: dict) -> None:
        """
        An older drone answers with `status` and no columns. Deriving them from
        the verbatim code is not a guess — those columns ARE the code, by
        porcelain's definition — so the lane restates the same fact rather than
        dropping the field and leaving a face to invent one.
        """
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
        """
        THE EVIDENCE, KEPT. Not a test of drone — a statement of why this lane
        must never read their screen output again, written in their own
        formatting rule so it stays true if anyone is tempted back.

        A reader parsing those two rendered lines gets one answer for two
        different states, whatever it does with the characters afterwards.
        """
        rendered = ["  %s %s" % (status.strip().rjust(2), path) for status, path in self.STAGED_AND_UNSTAGED]

        assert rendered[0][:4] == rendered[1][:4]
        assert len({line.split(" ")[-2] for line in rendered}) == 1


class TestTheStatusDoorsVerdictIsHonoured:
    """
    The refusal split, on the lane a phone hits most.

    A document that says `ok: false` is an ANSWER: drone reached git, git had
    something to say, and the caller learns a true thing about their
    repository. That is a 400 in their words. Output that is not a document at
    all is nobody being able to tell, and that is a 503 — which is exactly the
    shape drone's caller-verification refusal takes, since it never reaches the
    door and leaves its sentence on stderr.
    """

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
        """
        Inventing a reason would be this server deciding a meaning that is not
        its to decide. Saying they gave none is a fact.
        """
        refusal = json.dumps({"ok": False, "files": [], "total": 0})

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)):
            with pytest.raises(host_reads.ReadRefused) as caught:
                host_git.read_git_changes("demo")

        assert "without saying why" in str(caught.value)

    def test_a_true_verdict_is_never_read_off_the_exit_code(self, fake_repo: dict) -> None:
        """
        THE VERDICT IS THEIRS TO GIVE. A door that answers ok with a non-zero
        exit is answering; second-guessing it here would be this server
        deciding for them, which is the thing D0 exists to stop.
        """
        document = status_document(((" M", "src/aipass/demo/hello.txt"),))

        with patch.object(subprocess, "run", return_value=self._completed(document, returncode=1)):
            result = host_git.read_git_changes("demo")

        assert result["count"] == 1

    def test_a_json_array_is_not_a_document(self, fake_repo: dict) -> None:
        """
        One JSON OBJECT or nothing. A list parses cleanly and has no verdict in
        it at all, so reading one as an answer would mean trusting a shape that
        never said ok.
        """
        with patch.object(subprocess, "run", return_value=self._completed("[]")):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")

    def test_a_half_written_document_is_a_could_not_tell(self, fake_repo: dict) -> None:
        """A truncated answer is not a small answer."""
        with patch.object(subprocess, "run", return_value=self._completed('{"ok": true, "files": [')):
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")


class TestARefusedRootIsNotReAskedEveryFiveSeconds:
    """
    The 5-second noise machine, measured by @trigger and reported 2026-08-19.

    A phone polling the git lane hits it every 5 SECONDS. For a root that
    cannot authenticate — an external project whose branch carries no
    `.trinity/passport.json` — drone refuses the CALLER before the door ever
    runs, so every one of those 720 polls an hour spawns a subprocess that was
    never going to work and warns in THREE places: this branch's git_reads.log
    plus @drone's auth.log and git_module.log. Trigger escalated it x10 in an
    hour (signature d7605b500bbc).

    The refusal is correct and stays. What was wrong was asking again.

    WHAT IS REMEMBERED IS DRONE'S ANSWER, NOT DRONE'S RULE. Checking for a
    passport file here would be this branch reimplementing another branch's
    authentication and drifting from it the day they change it — and drifting
    in the WORST direction, refusing work that would have succeeded. So the
    door is asked once, its refusal is kept for a short window, and the window
    expiring is what lets a root that gains a passport start working again with
    nobody restarting anything.
    """

    def _completed(self, stdout: str, returncode: int = 0, stderr: str = "") -> Any:
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def _refused(self) -> Any:
        """What drone's caller-verification refusal actually looks like: no
        document at all, and the reason on stderr."""
        return self._completed("", returncode=1, stderr="No .trinity/passport.json found (caller cwd: /x)")

    def test_the_second_poll_does_not_spawn_a_second_subprocess(self, fake_repo: dict) -> None:
        """The whole point: one refusal answers the polls that follow it."""
        with patch.object(subprocess, "run", return_value=self._refused()) as ran:
            for _ in range(12):
                with pytest.raises(host_reads.ReadUnavailable):
                    host_git.read_git_changes("demo")

        assert ran.call_count == 1, f"a minute of polling spawned {ran.call_count} subprocesses"

    def test_the_remembered_refusal_still_says_what_drone_said(self, fake_repo: dict) -> None:
        """A cached refusal that loses the reason is worse than the spam.

        The operator reading the 503 needs the same sentence either way —
        otherwise the second poll onwards is a mystery, and the reason it is a
        mystery is the fix.
        """
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
        """A remembered refusal MUST expire, or a passport arriving is invisible.

        This is why the answer is a short-lived memory rather than a permanent
        deny-list: nobody should have to restart the server because they ran
        spawn. Time is driven rather than slept — a real 60s wait in a suite is
        not a test, it is a delay.
        """
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
        """
        The split this must not blur.

        `ok: false` means drone REACHED git and git answered — a live fact
        about a working repository that can change with the next edit. Caching
        it would freeze a real answer for a minute and tell a phone its tree is
        broken after the operator fixed it. Only a no-document failure, where
        the root could not be read at all, is worth remembering.
        """
        refusal = status_document((), ok=False, message="git status error: not a git repository")

        with patch.object(subprocess, "run", return_value=self._completed(refusal, returncode=1)) as ran:
            for _ in range(3):
                with pytest.raises(host_reads.ReadRefused):
                    host_git.read_git_changes("demo")

        assert ran.call_count == 3, "a live git answer was cached as if the root were unreadable"

    def test_one_lanes_silence_does_not_mute_another(self, fake_repo: dict) -> None:
        """Memory is per (root, lane), not per root.

        A root refused for the caller check fails every lane, so keying on the
        root alone would kill the spam too. But a lane that breaks for its OWN
        reason would then take three working lanes down with it — and telling
        the two apart means reading drone's refusal TEXT, which this branch
        does not do to another branch's words.
        """
        with patch.object(subprocess, "run", return_value=self._refused()) as ran:
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_changes("demo")
            with pytest.raises(host_reads.ReadUnavailable):
                host_git.read_git_log("demo")

        assert ran.call_count == 2
