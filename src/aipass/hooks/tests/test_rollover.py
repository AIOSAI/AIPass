# =================== AIPass ====================
# Name: test_rollover.py
# Version: 2.2.2
# Description: Tests for rollover lifecycle handler
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-10-05
# =============================================

"""Tests for apps/handlers/lifecycle/rollover.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and its logger import resolves
# seedgo: no-test-needed(stdlib) — subprocess.run's timeout mechanics; the tests stub it at the edge
# seedgo: no-test-needed(documentation) — that the handler's functions carry docstrings

from unittest.mock import patch, MagicMock
import subprocess

from aipass.hooks.apps.handlers.lifecycle import rollover
from aipass.hooks.apps.handlers.lifecycle.rollover import handle
from aipass.memory.apps.handlers.rollover import todo_report


MOD = "aipass.hooks.apps.handlers.lifecycle.rollover"

CHECK_OVERDUE_OUTPUT = (
    "Found 3 files ready for rollover:\n"
    "  * HOOKS.local (15/15 sessions)\n"
    "  * aipass.local (15/15 key_learnings)\n"
    "  * devpulse.local (15/15 key_learnings)\n"
)

CHECK_CLEAN_OUTPUT = "No files need rollover.\n"


def _mock_run(stdout="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = returncode
    return m


def _rolled(monkeypatch, tmp_path, check_out=CHECK_OVERDUE_OUTPUT, run_out="done", run_rc=0, times_out=None):
    """One PreCompact through handle() at a tmp repo root; (result, drone argvs, logger mock).

    subprocess.run is the sealed edge: `rollover check` answers *check_out*,
    `rollover run` answers *run_out* / *run_rc*, and the verb named by
    *times_out* raises TimeoutExpired instead. The root is found through
    AIPASS_HOME, the probe flag is cleared so the run arm is reached.
    """
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        verb = argv[3]
        if verb == times_out:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))
        if verb == "check":
            return _mock_run(stdout=check_out)
        return _mock_run(stdout=run_out, returncode=run_rc)

    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AIPASS_HOME", str(tmp_path))
    monkeypatch.delenv("AIPASS_HOOK_PROBE", raising=False)
    monkeypatch.setattr(rollover.subprocess, "run", fake_run)
    with patch(f"{MOD}.logger") as log:
        result = rollover.handle({"cwd": str(tmp_path)})
    return result, calls, log


class TestRolloverHandler:
    def test_no_repo_root_returns_empty(self):
        with patch(f"{MOD}._find_repo_root", return_value=None):
            result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_no_overdue_returns_empty(self):
        with patch(f"{MOD}._find_repo_root", return_value=MagicMock()):
            with patch(f"{MOD}._run_check", return_value=(False, CHECK_CLEAN_OUTPUT)):
                result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert "sound" not in result

    def test_overdue_triggers_rollover(self):
        with patch(f"{MOD}._find_repo_root", return_value=MagicMock()):
            with patch(f"{MOD}._run_check", return_value=(True, CHECK_OVERDUE_OUTPUT)):
                with patch(f"{MOD}._run_rollover", return_value=(True, "ok")):
                    result = handle({})

        assert result["exit_code"] == 0
        assert result["sound"] == "pre compact rollover"

    def test_overdue_rollover_failure_still_returns_sound(self):
        with patch(f"{MOD}._find_repo_root", return_value=MagicMock()):
            with patch(f"{MOD}._run_check", return_value=(True, CHECK_OVERDUE_OUTPUT)):
                with patch(f"{MOD}._run_rollover", return_value=(False, "error")):
                    result = handle({})

        assert result["exit_code"] == 0
        assert result["sound"] == "pre compact rollover"

    # The check and the run are read through handle() (fleet green leg 8), not
    # _run_check / _run_rollover by name: which drone verbs ran, and what was logged.

    def test_run_check_parses_overdue(self, monkeypatch, tmp_path):
        _result, calls, log = _rolled(monkeypatch, tmp_path)

        assert [argv[3] for argv in calls] == ["check", "run"]
        log.info.assert_any_call(
            "[HOOKS] rollover: overdue files detected — %s", CHECK_OVERDUE_OUTPUT.strip().replace("\n", " | ")
        )

    def test_run_check_parses_clean(self, monkeypatch, tmp_path):
        result, calls, _log = _rolled(monkeypatch, tmp_path, check_out=CHECK_CLEAN_OUTPUT)

        assert [argv[3] for argv in calls] == ["check"]
        assert result == {"stdout": "", "exit_code": 0}

    def test_run_check_timeout_returns_false(self, monkeypatch, tmp_path):
        _result, calls, log = _rolled(monkeypatch, tmp_path, times_out="check")

        assert [argv[3] for argv in calls] == ["check"]
        log.warning.assert_any_call("[HOOKS] rollover: check timed out (30s)")

    def test_run_rollover_success(self, monkeypatch, tmp_path):
        _result, _calls, log = _rolled(monkeypatch, tmp_path)

        log.info.assert_any_call("[HOOKS] rollover: complete (branch=%s)", None)
        log.warning.assert_not_called()

    def test_run_rollover_failure(self, monkeypatch, tmp_path):
        _result, _calls, log = _rolled(monkeypatch, tmp_path, run_out="error", run_rc=1)

        log.warning.assert_any_call("[HOOKS] rollover: FAILED — %s", "error")

    def test_run_rollover_timeout(self, monkeypatch, tmp_path):
        _result, _calls, log = _rolled(monkeypatch, tmp_path, times_out="run")

        log.warning.assert_any_call("[HOOKS] rollover: FAILED — %s", "Rollover timed out (110s)")


class TestTheCompactingBranchIsNamed:
    """DPLAN-0345 / FPLAN-0590 row 7: @memory rolls ONE branch's todo pad per call.

    drone runs this handler's commands with cwd = repo root and re-stamps
    AIPASS_CALLER_CWD with that, so memory resolves no branch and rolls no pad
    unless the hook names one (memory measured it, 2026-09-15). The branch is
    the compacting session's, read from the PreCompact payload's cwd.
    """

    @staticmethod
    def _spy(monkeypatch, check_stdout=CHECK_OVERDUE_OUTPUT):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs.get("cwd")))
            return _mock_run(stdout=check_stdout if "check" in argv else "done")

        monkeypatch.setattr(rollover.subprocess, "run", fake_run)
        monkeypatch.delenv("AIPASS_HOOK_PROBE", raising=False)
        return rollover, calls

    # Both through handle() (fleet green leg 8): each call's argv and the repo root it runs in.

    def test_check_names_the_branch(self, monkeypatch, tmp_path):
        rollover, calls = self._spy(monkeypatch)
        (tmp_path / "src" / "aipass" / "hooks").mkdir(parents=True)
        monkeypatch.setattr(rollover, "_find_repo_root", lambda: tmp_path)
        rollover.handle({"cwd": str(tmp_path / "src" / "aipass" / "hooks")})
        assert calls[0] == (["drone", "@memory", "rollover", "check", "--branch", "@hooks"], str(tmp_path))

    def test_run_names_the_branch(self, monkeypatch, tmp_path):
        rollover, calls = self._spy(monkeypatch)
        (tmp_path / "src" / "aipass" / "hooks").mkdir(parents=True)
        monkeypatch.setattr(rollover, "_find_repo_root", lambda: tmp_path)
        rollover.handle({"cwd": str(tmp_path / "src" / "aipass" / "hooks")})
        assert calls[1] == (["drone", "@memory", "rollover", "run", "--branch", "@hooks"], str(tmp_path))

    def test_handle_reads_the_branch_from_the_payload_cwd(self, monkeypatch, tmp_path):
        """Not the process cwd: the hook runs wherever CC launched the bridge."""
        rollover, calls = self._spy(monkeypatch)
        branch_dir = tmp_path / "src" / "aipass" / "compacting_one"
        (branch_dir / "apps").mkdir(parents=True)
        monkeypatch.setattr(rollover, "_find_repo_root", lambda: tmp_path)

        rollover.handle({"cwd": str(branch_dir / "apps"), "trigger": "auto"})

        assert [argv for argv, _ in calls] == [
            ["drone", "@memory", "rollover", "check", "--branch", "@compacting_one"],
            ["drone", "@memory", "rollover", "run", "--branch", "@compacting_one"],
        ]

    def test_no_branch_still_runs_the_fleet_rollover(self, monkeypatch, tmp_path):
        """A seat in no branch still owes the fleet its sessions roll: bare call, no flag."""
        rollover, calls = self._spy(monkeypatch)
        monkeypatch.setattr(rollover, "_find_repo_root", lambda: tmp_path)

        rollover.handle({"cwd": str(tmp_path)})

        assert [argv for argv, _ in calls] == [
            ["drone", "@memory", "rollover", "check"],
            ["drone", "@memory", "rollover", "run"],
        ]

    def test_memorys_todos_line_alone_reads_as_overdue(self, monkeypatch, tmp_path):
        """The contract: memory keeps its phrase on the todos line for this grep.

        Built from memory's own constant, so a rename there turns this red here.
        """
        todos_line = (
            f"No files need rollover\n@hooks todos: pad 12/10 - 2 {todo_report.READY_PHRASE} "
            "(oldest by number -> .backup/todo/hooks/backlog.json)"
        )
        _result, calls, log = _rolled(monkeypatch, tmp_path, check_out=todos_line)
        assert [argv[3] for argv in calls] == ["check", "run"]
        log.info.assert_any_call("[HOOKS] rollover: overdue files detected — %s", todos_line.replace("\n", " | "))


class TestFindRepoRootFailLoud:
    """_find_repo_root logs error (not silent skip) when no AIPASS_REGISTRY.json found."""

    def test_bad_root_logs_error(self, monkeypatch, tmp_path):
        """No AIPASS_REGISTRY.json anywhere -> logger.error with AIPASS_HOME + cwd.

        Through handle() from a real tmp cwd (fleet green leg 8), not _find_repo_root by name.
        """
        monkeypatch.setenv("AIPASS_HOME", "")
        monkeypatch.chdir(tmp_path)
        with patch(f"{MOD}.logger") as log, patch(f"{MOD}.subprocess.run") as run:
            result = rollover.handle({"cwd": str(tmp_path)})

        assert result == {"stdout": "", "exit_code": 0}
        run.assert_not_called()
        message, home, _cwd = log.error.call_args.args
        assert "_find_repo_root failed" in message
        assert "AIPASS_REGISTRY.json" in message
        assert home == ""

    def test_bad_aipass_home_falls_through_to_cwd(self, monkeypatch, tmp_path):
        """AIPASS_HOME set but no registry there -> falls through, still logs error if cwd also fails."""
        bad_home = str(tmp_path / "nonexistent")
        monkeypatch.setenv("AIPASS_HOME", bad_home)
        monkeypatch.chdir(tmp_path)
        with patch(f"{MOD}.logger") as log, patch(f"{MOD}.subprocess.run") as run:
            rollover.handle({"cwd": str(tmp_path)})

        run.assert_not_called()
        message, home, _cwd = log.error.call_args.args
        assert "_find_repo_root failed" in message
        assert home == bad_home


class TestProbeSuppression:
    """The test runner must not trigger a fleet-wide memory trim (DPLAN-0323 tie-up).

    @memory resolves its own roots — AIPASS_HOME appears nowhere in its tree
    (measured 2026-09-06) — so pointing cwd or the environment at a tempdir
    cannot confine `drone @memory rollover run`. The refusal lives at the call.
    """

    def _patched(self, monkeypatch):
        ran = []
        monkeypatch.setattr(rollover, "_find_repo_root", lambda: MagicMock())
        monkeypatch.setattr(rollover, "_compacting_branch", lambda hook_data: "hooks")
        monkeypatch.setattr(rollover, "_run_check", lambda root, branch: (True, CHECK_OVERDUE_OUTPUT))
        monkeypatch.setattr(rollover, "_run_rollover", lambda root, branch: (ran.append("ran"), (True, ""))[1])
        return rollover, ran

    def test_probe_run_suppresses_the_fleet_rollover(self, monkeypatch):
        rollover, ran = self._patched(monkeypatch)
        monkeypatch.setenv("AIPASS_HOOK_PROBE", "1")
        result = rollover.handle({})
        assert ran == []
        assert result["exit_code"] == 0

    def test_real_run_still_rolls_over(self, monkeypatch):
        """CAUSATION: a guard that suppresses everything proves nothing."""
        rollover, ran = self._patched(monkeypatch)
        monkeypatch.delenv("AIPASS_HOOK_PROBE", raising=False)
        rollover.handle({})
        assert ran == ["ran"]

    def test_the_read_only_check_still_runs_under_a_probe(self, monkeypatch):
        """Suppression is at the mutation, not at the entry — the handler must still work."""
        checked = []
        monkeypatch.setattr(rollover, "_find_repo_root", lambda: MagicMock())
        monkeypatch.setattr(rollover, "_compacting_branch", lambda hook_data: "hooks")
        monkeypatch.setattr(
            rollover,
            "_run_check",
            lambda root, branch: (checked.append("checked"), (True, CHECK_OVERDUE_OUTPUT))[1],
        )
        monkeypatch.setattr(rollover, "_run_rollover", lambda root, branch: (True, ""))
        monkeypatch.setenv("AIPASS_HOOK_PROBE", "1")
        rollover.handle({})
        assert checked == ["checked"]

    def test_only_the_exact_flag_value_suppresses(self, monkeypatch):
        """An unset-but-present variable must not silently dark the handler."""
        rollover, ran = self._patched(monkeypatch)
        monkeypatch.setenv("AIPASS_HOOK_PROBE", "0")
        rollover.handle({})
        assert ran == ["ran"]
