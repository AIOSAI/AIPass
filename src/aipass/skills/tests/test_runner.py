# =================== AIPass ====================
# Name: test_runner.py
# Description: Unit tests for skills runner
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-24
# Category: skills/tests
# =============================================

"""Tests for apps/modules/runner.py and the built-in skills it runs (system_status, drone_commands, branch_health, inbox_check)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that runner.py and runner_handler.py parse and import

import os
import subprocess
import time
from collections import namedtuple

import pytest

from aipass.skills.apps.modules.loader import load_skill
from aipass.skills.apps.modules.runner import handle_command, run_skill


class TestRunSkillHandler:
    def test_the_run_command_prints_the_disk_report_to_stdout(self, capsys):
        # Pins handle_command's console.print loop.
        assert handle_command("run", ["system_status", "disk"]) is True
        out, err = capsys.readouterr()
        assert "  Disk Usage (/)" in out
        assert err == ""

    # No platform guards below: the skill asks psutil, which answers on every supported host.

    def test_run_system_status_memory(self):
        result = run_skill("system_status", action="memory")
        assert result["success"] is True
        assert "Memory" in result["output"]

    def test_run_system_status_uptime(self):
        result = run_skill("system_status", action="uptime")
        assert result["success"] is True
        assert "Uptime" in result["output"]

    def test_run_system_status_processes(self):
        result = run_skill("system_status", action="processes")
        assert result["success"] is True
        assert "processes" in result["output"].lower()

    def test_run_system_status_summary(self):
        result = run_skill("system_status", action="summary")
        assert result["success"] is True
        assert "Disk Usage" in result["output"]
        assert "Memory" in result["output"]
        assert "Uptime" in result["output"]
        assert result["error"] is None

    def test_invalid_action(self):
        result = run_skill("system_status", action="nonexistent")
        assert result["success"] is False
        assert result["error"] is not None

    def test_no_action_lists_actions(self):
        result = run_skill("system_status")
        assert result["success"] is True
        assert "Available actions" in result["output"]

    def test_nonexistent_skill(self):
        result = run_skill("nonexistent_skill_xyz")
        assert result["success"] is False
        assert result["error"] is not None


class TestDroneCommandsNeverUsesAShell:
    """drone_commands runs drone and only drone: shell syntax in the command is a plain argument."""

    def test_a_chained_command_reaches_drone_as_arguments_not_a_second_program(self, monkeypatch):
        # Pins a shipped defect: shell=True ran "echo" after drone, past every bash hook gate.
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs.get("shell", False)))
            return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_skill("drone_commands", action="run", args={"command": "drone @flow list; echo pwned"})

        assert result["success"] is True
        assert calls == [(["drone", "@flow", "list;", "echo", "pwned"], False)]


class TestABranchNameIsNeverAPath:
    """branch_health and inbox_check take a branch name as their action, never a path."""

    @pytest.mark.parametrize("skill", ["branch_health", "inbox_check"])
    @pytest.mark.parametrize("name", ["..", "../..", os.path.join("x", "y")])
    def test_a_path_shaped_name_is_refused_before_any_read(self, skill, name):
        # Pins a shipped defect: "../.." walked every .py file above src/aipass.
        result = run_skill(skill, action=name)
        assert result["success"] is False
        assert result["error"] == f"Not a branch name: {name!r}"


class TestRunSkillMarkdown:
    def test_run_github_returns_body(self):
        result = run_skill("github")
        assert result["success"] is True
        assert result["output"] is not None
        assert len(result["output"]) > 100
        assert "github" in result["output"].lower()
        assert result["error"] is None

    def test_output_format(self):
        result = run_skill("github")
        assert result["output"].startswith("=== Skill: github ===")


class TestRunSkillReturnContract:
    def test_return_has_required_keys(self):
        result = run_skill("system_status", action="disk")
        assert "success" in result
        assert "output" in result
        assert "error" in result
        assert result["success"] is True
        assert "Disk Usage" in result["output"]
        assert result["error"] is None

    def test_success_result_types(self):
        result = run_skill("system_status", action="disk")
        assert isinstance(result["success"], bool)
        assert isinstance(result["output"], str)
        assert result["error"] is None
        assert result["success"] is True
        assert len(result["output"]) > 0
        assert "Disk Usage" in result["output"]

    def test_failure_result_types(self):
        result = run_skill("nonexistent_skill_xyz")
        assert isinstance(result["success"], bool)
        assert isinstance(result["output"], str)
        assert isinstance(result["error"], str)
        assert result["success"] is False
        assert "not found" in result["error"].lower()
        assert result["output"] == ""


# A macOS host built on Linux: platform darwin, every /proc read refused, psutil a stand-in
# (real psutil on Linux reads /proc, a failure no Mac can have).
PROC_ROOT = "/proc"
PROC_MEMINFO = "/proc/meminfo"
GIB = 1024**3

# macOS has no buffers/cached, Linux has both; the handler prints them only where present.
_VirtualDarwin = namedtuple("svmem", ["total", "available", "percent", "used", "free", "active", "inactive", "wired"])
_VirtualLinux = namedtuple(
    "svmem",
    ["total", "available", "percent", "used", "free", "active", "inactive", "buffers", "cached", "shared", "slab"],
)
_Swap = namedtuple("sswap", ["total", "used", "free", "percent", "sin", "sout"])


class _PsutilStandIn:
    """A psutil stand-in with numbers this host lacks, so an assertion passes only if the handler asked it."""

    def __init__(self, virtual, swap, pids, boot_time):
        self._virtual = virtual
        self._swap = swap
        self._pids = pids
        self._boot_time = boot_time

    def virtual_memory(self):
        return self._virtual

    def swap_memory(self):
        return self._swap

    def pids(self):
        return list(self._pids)

    def boot_time(self):
        return self._boot_time


class _PsutilWithBrokenMemory(_PsutilStandIn):
    """A psutil whose memory read fails the way a sandboxed host's does."""

    def virtual_memory(self):
        raise OSError("host_statistics64 refused")


def _darwin_swap():
    return _Swap(total=4 * GIB, used=1 * GIB, free=3 * GIB, percent=25.0, sin=0, sout=0)


def _darwin_psutil(boot_time):
    virtual = _VirtualDarwin(
        total=8 * GIB,
        available=2 * GIB,
        percent=75.0,
        used=5 * GIB,
        free=1 * GIB,
        active=4 * GIB,
        inactive=1 * GIB,
        wired=1 * GIB,
    )
    return _PsutilStandIn(virtual, _darwin_swap(), [1, 42, 4242], boot_time)


@pytest.fixture()
def status_handler():
    """The system_status handler module, loaded the way the runner loads it."""
    loaded = load_skill("system_status")
    assert loaded["success"] is True
    handler = loaded["handler"]
    assert handler is not None
    return handler


@pytest.fixture()
def darwin_host(monkeypatch, status_handler, audit_guard):
    """A host with no /proc, with psutil answering the way it does on a Mac."""

    def _deny_proc(event, args):
        # "open" covers every file route; the two directory reads are their own events.
        if event not in ("open", "os.listdir", "os.scandir") or not isinstance(args[0], (str, os.PathLike)):
            return
        text = os.fspath(args[0])
        if text == PROC_ROOT or text.startswith(PROC_ROOT + "/"):
            raise FileNotFoundError(2, "No such file or directory", text)

    audit_guard(_deny_proc)
    monkeypatch.setattr(status_handler, "_host_platform", lambda: "darwin")
    # 1d 1h 1m 1s ago, read at fixture time
    monkeypatch.setattr(status_handler, "psutil", _darwin_psutil(time.time() - 90061))
    return status_handler


class TestTheDarwinWorldIsLive:
    """Controls. A world that reached nothing must not pass quietly."""

    def test_the_host_has_no_proc(self, darwin_host):
        assert darwin_host._host_platform() == "darwin"
        with pytest.raises(FileNotFoundError):
            open(PROC_MEMINFO, encoding="utf-8").close()
        with pytest.raises(FileNotFoundError):
            os.close(os.open(PROC_MEMINFO, os.O_RDONLY))

    def test_the_denial_can_still_say_yes(self, darwin_host, tmp_path):
        """Control on the control: a path outside /proc still opens."""
        probe = tmp_path / "probe.txt"
        probe.write_text("alive", encoding="utf-8")
        with open(probe, encoding="utf-8") as handle:
            assert handle.read() == "alive"
        assert "probe.txt" in os.listdir(tmp_path)

    def test_the_process_table_is_gone_too(self, darwin_host):
        with pytest.raises(FileNotFoundError):
            os.listdir(PROC_ROOT)
        with pytest.raises(FileNotFoundError):
            os.scandir(PROC_ROOT).close()


class TestSystemStatusOffLinux:
    """The four actions that were red on every macOS run."""

    def test_memory_answers(self, darwin_host):
        result = darwin_host.run("memory")
        assert result["success"] is True
        assert result["error"] is None
        assert "Total:     8.0 GB" in result["output"]
        # used is total - available, not psutil's own `used` field (5 GB here)
        assert "Used:      6.0 GB (75.0%)" in result["output"]
        assert "Available: 2.0 GB" in result["output"]

    def test_memory_prints_no_buffers_or_cached_where_the_platform_has_none(self, darwin_host):
        """A zero would read like a measurement. macOS has neither field."""
        output = darwin_host.run("memory")["output"]
        assert "Buffers" not in output
        assert "Cached" not in output
        assert "Swap" in output
        assert "Total:     4.0 GB" in output

    def test_memory_prints_buffers_and_cached_where_the_platform_has_them(self, monkeypatch, status_handler):
        """The other half of the same branch — a Linux-shaped virtual_memory."""
        virtual = _VirtualLinux(
            total=8 * GIB,
            available=2 * GIB,
            percent=75.0,
            used=5 * GIB,
            free=1 * GIB,
            active=4 * GIB,
            inactive=1 * GIB,
            buffers=1 * GIB,
            cached=3 * GIB,
            shared=0,
            slab=0,
        )
        monkeypatch.setattr(status_handler, "psutil", _PsutilStandIn(virtual, _darwin_swap(), [1], time.time()))
        output = status_handler.run("memory")["output"]
        assert "Buffers:   1.0 GB" in output
        assert "Cached:    3.0 GB" in output

    def test_uptime_answers(self, darwin_host):
        result = darwin_host.run("uptime")
        assert result["success"] is True
        assert result["output"].startswith("Uptime: 1d 1h 1m")
        seconds = float(result["output"].split("(")[1].split()[0])
        # now minus boot time, not the boot time itself
        assert 90061 <= seconds < 90071

    def test_processes_counts_what_psutil_reports(self, darwin_host):
        result = darwin_host.run("processes")
        assert result["success"] is True
        # This box runs far more than three. Only the stand-in says 3.
        assert result["output"] == "Running processes: 3"

    def test_summary_is_whole(self, darwin_host):
        result = darwin_host.run("summary")
        assert result["success"] is True
        assert result["error"] is None
        for heading in ("Disk Usage", "Memory", "Uptime", "Running processes: 3"):
            assert heading in result["output"]


class TestSummaryIsHonestAboutAFailedSection:
    """A partial report is not a good answer: a caller checking `success` must see the failure."""

    def test_a_failed_section_makes_the_summary_fail(self, monkeypatch, status_handler):
        broken = _PsutilWithBrokenMemory(None, _darwin_swap(), [1, 2], time.time() - 90061)
        monkeypatch.setattr(status_handler, "psutil", broken)
        result = status_handler.run("summary")
        assert result["success"] is False
        assert "Incomplete summary" in result["error"]
        assert "memory" in result["error"]
        assert "host_statistics64 refused" in result["error"]

    def test_the_sections_that_answered_are_still_handed_back(self, monkeypatch, status_handler):
        broken = _PsutilWithBrokenMemory(None, _darwin_swap(), [1, 2], time.time() - 90061)
        monkeypatch.setattr(status_handler, "psutil", broken)
        result = status_handler.run("summary")
        assert "Disk Usage" in result["output"]
        assert "Uptime" in result["output"]
        assert "Running processes: 2" in result["output"]
        # and the failure is not hidden in the body where nobody checks it
        assert "Errors:" not in result["output"]


class TestWithoutPsutil:
    """A host that cannot import psutil is told the recipe, not a partial."""

    def test_memory_names_psutil_and_the_install(self, monkeypatch, status_handler):
        monkeypatch.setattr(status_handler, "psutil", None)
        result = status_handler.run("memory")
        assert result["success"] is False
        assert result["output"] == ""
        assert "memory" in result["error"]
        assert "psutil" in result["error"]
        assert "pip install" in result["error"]

    def test_uptime_names_psutil_and_the_install(self, monkeypatch, status_handler):
        monkeypatch.setattr(status_handler, "psutil", None)
        result = status_handler.run("uptime")
        assert result["success"] is False
        assert "uptime" in result["error"]
        assert "pip install" in result["error"]

    def test_processes_names_psutil_and_the_install(self, monkeypatch, status_handler):
        monkeypatch.setattr(status_handler, "psutil", None)
        result = status_handler.run("processes")
        assert result["success"] is False
        assert "process table" in result["error"]
        assert "pip install" in result["error"]

    def test_disk_still_answers_without_psutil(self, monkeypatch, status_handler):
        """shutil.disk_usage needs nothing. Losing psutil must not cost it."""
        monkeypatch.setattr(status_handler, "psutil", None)
        result = status_handler.run("disk")
        assert result["success"] is True
        assert "Disk Usage" in result["output"]

    def test_summary_fails_and_names_all_three_sections(self, monkeypatch, status_handler):
        monkeypatch.setattr(status_handler, "psutil", None)
        result = status_handler.run("summary")
        assert result["success"] is False
        for section in ("memory", "uptime", "processes"):
            assert section in result["error"]
        assert "Disk Usage" in result["output"]
