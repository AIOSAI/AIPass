# =================== AIPass ====================
# Name: test_rm_gate.py
# Version: 3.2.0
# Description: Tests for rm_gate security handler, the DPLAN-0356 lockdown since 2.0.0
# Branch: hooks
# Created: 2026-06-02
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/security/rm_gate.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — that the gate's functions carry docstrings
# seedgo: no-test-needed(ruff) — that the module parses and its logger import resolves
# seedgo: no-test-needed(stdlib) — shlex's tokenising itself; the gate's reading of the tokens is pinned here

import json
import logging
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.security import rm_gate
from aipass.hooks.apps.modules import bash_writes
from aipass.prax.apps.modules.logger import system_logger
from aipass.hooks.apps.handlers.security.rm_gate import handle

_BRANCH = Path(__file__).resolve().parent.parent
# Both sinks the prax logger feeds. system_logs/ is the aggregate @trigger watches —
# that is the file whose 3597 lines/min fired the runaway alert (fc74ef8b).
LIVE_RECORDS = (
    _BRANCH / "logs" / "rm_gate.log",
    _BRANCH.parents[2] / "system_logs" / "hooks_rm_gate.log",
)


def _home_through_a_link(real: Path, link: Path, monkeypatch) -> None:
    """HOME (USERPROFILE on Windows) spelled through *link*, a directory symlink to *real*, as macOS's /var is."""
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("HOME", str(link))
    monkeypatch.setenv("USERPROFILE", str(link))


@pytest.fixture(autouse=True)
def audit_log_to_tmp(tmp_path, monkeypatch):
    """Route the deletion record to tmp_path — the live one carries real events only.

    @devpulse 7be84afb: the first run of these tests wrote hundreds of identical
    DELETE lines into the live hooks_rm_gate.log and prax fired a CRITICAL runaway
    (3597 lines/min). A record nobody can trust to be real is not a record.
    """
    probe = logging.getLogger("test_rm_gate_audit")
    probe.setLevel(logging.INFO)
    handler = logging.FileHandler(tmp_path / "rm_gate.log", encoding="utf-8")
    probe.addHandler(handler)
    monkeypatch.setattr(rm_gate, "logger", probe)
    yield
    probe.removeHandler(handler)
    handler.close()


@pytest.fixture(autouse=True)
def no_admin_grant():
    """No test reads this machine's real admin grant; TestTheLockdown grants it where it means to."""
    with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=False):
        yield


class TestWhatTheScanReads:
    """Quoted text is an argument, and every clause of a compound command is read — through handle().

    Replaced the direct unit tests of _strip_quotes and _split_clauses (2.0.0):
    each of their inputs is a row here, judged end to end.
    """

    CWD = str(_BRANCH)

    QUOTED = (
        'echo "rm -rf foo bar"',
        "echo 'rm -rf foo bar'",
        r'echo "he said \"rm -rf x\""',
        'echo "then rm -rf x"',
        "echo 'then rm -rf x'",
    )
    CLAUSES = (
        """echo "hello" && rm -rf 'x'""",
        "cd build && rm -rf foo",
        "echo hi; rm -rf build/x",
        "ls | rm -rf build/x",
        "true || rm -rf build/x",
        "echo $(rm -rf build/x)",
        "echo `rm -rf build/x`",
    )

    def _decide(self, command: str) -> int:
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.CWD})["exit_code"]

    def test_rm_inside_any_quoting_is_not_a_delete(self):
        for command in self.QUOTED:
            assert self._decide(command) == 0, f"wrongly refused: {command!r}"

    def test_a_variable_named_rm_is_not_the_program_but_rm_of_a_variable_is(self):
        for command in ("echo $RM", "X=a; echo ${RM}", "run $RM -rf x"):
            assert self._decide(command) == 0, f"wrongly refused: {command!r}"
        assert self._decide("rm -rf $RM") == 2

    def test_an_rm_in_any_clause_of_a_compound_command_is_refused(self):
        for command in self.CLAUSES:
            assert self._decide(command) == 2, f"not refused: {command!r}"


class TestHandle:
    CWD = str(_BRANCH)

    def _bash(self, command: str) -> dict:
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.CWD})

    def _assert_blocked(self, result: dict):
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "Raw rm is refused" in parsed["reason"]

    def _assert_allowed(self, result: dict):
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_block_rm_rf(self):
        self._assert_blocked(self._bash("rm -rf build/x"))

    def test_a_plain_rm_is_refused_too(self):
        self._assert_blocked(self._bash("rm file.txt"))

    def test_block_compound_cd_and_rm(self):
        self._assert_blocked(self._bash("cd /etc && rm -rf ."))

    def test_block_compound_semicolon(self):
        self._assert_blocked(self._bash("echo hi; rm -rf build/x"))

    def test_block_subshell_rm(self):
        self._assert_blocked(self._bash("echo $(rm -rf build/x)"))

    def test_block_absolute_path_rm(self):
        self._assert_blocked(self._bash("/usr/bin/rm -rf build/x"))

    def test_rm_in_quoted_string_allowed(self):
        self._assert_allowed(self._bash('echo "rm -rf build/x"'))

    def test_rm_in_single_quoted_string_allowed(self):
        self._assert_allowed(self._bash("echo 'rm -rf build/x'"))

    def test_non_bash_tool_allowed(self):
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": "build/x"}, "cwd": self.CWD})
        self._assert_allowed(result)

    def test_empty_command_allowed(self):
        self._assert_allowed(self._bash(""))

    def test_empty_hook_data(self):
        result = handle({})
        assert result["exit_code"] == 0

    def test_no_tool_input(self):
        result = handle({"tool_name": "Bash"})
        assert result["exit_code"] == 0

    @patch("aipass.hooks.apps.handlers.security.rm_gate.logger")
    def test_a_crash_refuses_the_bash_call(self, mock_logger):
        """DPLAN-0356 item 2: `except: allow` became a refusal; a non-Bash call is not this gate's."""
        result = handle({"tool_name": "Bash", "tool_input": None, "cwd": self.CWD})
        assert result["exit_code"] == 2
        assert "rm_gate could not check this Bash call" in json.loads(result["stdout"])["reason"]
        mock_logger.error.assert_called()
        assert handle({"tool_name": "Read", "tool_input": None, "cwd": self.CWD})["exit_code"] == 0

    def test_block_variable_target(self):
        self._assert_blocked(self._bash("rm -rf $DIR"))


class TestDeletionRecord:
    """The owner, 2026-08-14: "we need a log for deleted files - if something deletes,
    it should be a record of it."

    @drone records the admin seat's drone rm. Since DPLAN-0356 every delete this
    gate sees from any other lane is refused, and every refused attempt is a line.
    """

    CWD = str(_BRANCH)

    def _bash(self, command: str, cwd: str | None = None) -> dict:
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd or self.CWD})

    def _audit_records(self, caplog):
        return [r for r in caplog.records if "DELETE" in r.getMessage()]

    def test_a_refused_plain_rm_is_recorded(self, caplog):
        with caplog.at_level(logging.INFO):
            result = self._bash("rm notes.txt")

        assert result["exit_code"] == 2
        records = self._audit_records(caplog)
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "rm notes.txt" in msg
        assert self.CWD in msg
        assert "hooks" in msg

    def test_the_record_is_info_never_warning(self, caplog):
        """Compass #273: the engine records the block at WARNING; this line only adds what it was."""
        with caplog.at_level(logging.INFO):
            self._bash("rm notes.txt")

        records = self._audit_records(caplog)
        assert records
        assert all(r.levelno == logging.INFO for r in records)

    def test_blocked_recursive_rm_is_recorded_with_its_command(self, caplog):
        """The engine logs THAT a block happened; only this line says WHAT it was."""
        with caplog.at_level(logging.INFO):
            result = self._bash("rm -rf build/x")

        assert result["exit_code"] == 2, "the block itself must not change"
        records = self._audit_records(caplog)
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "refused" in msg
        assert "rm -rf build/x" in msg

    def test_the_admin_seats_allowed_drone_rm_is_not_recorded_here(self, caplog):
        """The admin seat's drone rm is @drone's record — double-logging it would be a lie
        about how many deletions happened."""
        with (
            patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=True),
            caplog.at_level(logging.INFO),
        ):
            assert self._bash("drone rm build/x")["exit_code"] == 0

        assert not self._audit_records(caplog)

    def test_git_rm_is_not_recorded_here(self, caplog):
        """A different lane with its own gate — this record is about filesystem rm."""
        with caplog.at_level(logging.INFO):
            self._bash("git rm notes.txt")

        assert not self._audit_records(caplog)

    def test_a_command_with_no_rm_records_nothing(self, caplog):
        with caplog.at_level(logging.INFO):
            self._bash("ls -la && echo done")

        assert not self._audit_records(caplog)

    def test_rm_inside_quotes_is_not_a_deletion(self, caplog):
        """Same scan the block path uses — a quoted rm deletes nothing."""
        with caplog.at_level(logging.INFO):
            self._bash("echo 'rm notes.txt'")

        assert not self._audit_records(caplog)

    def test_branch_comes_from_the_passport_not_the_path(self, caplog, tmp_path):
        """Resolver-family lesson: path shape lies, the passport does not."""
        project = tmp_path / "somewhere" / "not-named-like-a-branch"
        (project / ".trinity").mkdir(parents=True)
        (project / ".trinity" / "passport.json").write_text(
            json.dumps({"branch_info": {"branch_name": "cartographer"}}), encoding="utf-8"
        )

        with caplog.at_level(logging.INFO):
            self._bash("rm notes.txt", cwd=str(project))

        records = self._audit_records(caplog)
        assert len(records) == 1
        assert "cartographer" in records[0].getMessage()

    def test_unresolvable_branch_still_records(self, caplog, tmp_path):
        """A missing passport must cost the record its branch, never the record."""
        with caplog.at_level(logging.INFO):
            self._bash("rm notes.txt", cwd=str(tmp_path))

        records = self._audit_records(caplog)
        assert len(records) == 1
        assert "rm notes.txt" in records[0].getMessage()

    def test_a_broken_passport_costs_the_name_never_the_refusal(self, caplog, tmp_path):
        project = tmp_path / "proj"
        (project / ".trinity").mkdir(parents=True)
        (project / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")

        with caplog.at_level(logging.INFO):
            result = self._bash("rm notes.txt", cwd=str(project))

        assert result["exit_code"] == 2
        records = self._audit_records(caplog)
        assert len(records) == 1 and "branch=unnamed" in records[0].getMessage()

    def test_a_passport_at_a_symlinked_home_names_no_one(self, caplog, tmp_path, monkeypatch):
        """host_portability (PR #774): the resolved walk never met an unresolved home and read home's passport."""
        real = tmp_path / "real_home"
        (real / ".trinity").mkdir(parents=True)
        (real / ".trinity" / "passport.json").write_text('{"branch_info": {"branch_name": "squatter"}}', "utf-8")
        (real / "work").mkdir()
        _home_through_a_link(real, tmp_path / "home", monkeypatch)

        with caplog.at_level(logging.INFO):
            self._bash("rm notes.txt", cwd=str(real / "work"))

        records = self._audit_records(caplog)
        assert len(records) == 1 and "branch=unnamed" in records[0].getMessage()

    def test_every_rm_clause_in_a_compound_command_is_recorded(self, caplog):
        """One line per deletion, or the count in the record is wrong."""
        with caplog.at_level(logging.INFO):
            self._bash("rm a.txt && echo mid && rm b.txt")

        records = self._audit_records(caplog)
        assert len(records) == 2

    def test_the_suite_never_writes_the_live_record(self):
        """The proof @devpulse asked for: a run of this class leaves the live logs alone."""
        sizes = {p: p.stat().st_size for p in LIVE_RECORDS if p.exists()}

        for _ in range(50):
            self._bash("rm notes.txt")
            self._bash("rm -rf build/x")

        for path, before in sizes.items():
            assert path.stat().st_size == before, f"tests polluted the live record: {path}"
        assert rm_gate.logger is not system_logger, "the handler is holding the live logger under test"

    def test_the_command_is_recorded_as_seen_not_as_scanned(self, caplog):
        """Quote-stripping is an implementation detail of matching, not evidence."""
        with caplog.at_level(logging.INFO):
            self._bash('rm "my notes.txt"')

        records = self._audit_records(caplog)
        assert len(records) == 1
        assert 'rm "my notes.txt"' in records[0].getMessage()


class TestTheDecisionMatrix:
    """Every decision, end to end, from a seat with no admin grant (DPLAN-0356 since 2.0.0).

    Until 2.0.0 a plain rm and drone rm were allowed here; the owner's ruling
    refuses both off the admin seat. The rows stay so the wiring from handle()
    down to the scan stays pinned for each spelling.
    """

    # Nine handle-level rows folded in here 2026-09-07 (DPLAN-0323 contested
    # band). Six were already carried by this matrix verbatim. The last three
    # were NOT end-to-end anywhere — -fr, a sudo prefix, and two targets after
    # the flag — so their inputs moved in rather than being dropped: a merge
    # keeps every claim, and clause-level pins alone would have left the wiring
    # from handle() down to the scan unpinned for those three.
    MATRIX = [
        ("rm -rf build/x", 2),
        ("rm -fr build/x", 2),
        ("rm -r build/x", 2),
        ("rm -R build/x", 2),
        ("rm --recursive build/x", 2),
        ("rm -rfv build/x", 2),
        ("rm -rf build/a build/b", 2),
        ("sudo rm -rf build/x", 2),
        ("ls && rm -rf build", 2),
        ("env VAR=val rm -rf build/x", 2),
        ("rm notes.txt", 2),
        ("rm -f notes.txt", 2),
        ("rm -f file.txt", 2),
        ("drone rm build/x", 2),
        ("drone rm -rf build/x", 2),
        ("echo 'rm -rf build/x'", 0),
        ("ls -la", 0),
        ("", 0),
    ]

    def test_every_row_decides_as_the_lockdown_rules(self):
        # The floor. This matrix absorbed three rows that have no other
        # end-to-end pin (-fr, the sudo prefix, two targets) when they were
        # folded in on 09-07, so a matrix that shrank would take those claims
        # with it and the loop would still report the gate unchanged.
        assert len(self.MATRIX) == 18
        for command, expected in self.MATRIX:
            result = handle(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "cwd": str(_BRANCH),
                }
            )
            assert result["exit_code"] == expected, f"decision changed for: {command!r}"


class TestOneDeleteSpelledManyWays:
    """A rename is not a bypass — the owner's go, 2026-09-19 (devpulse DPLAN-0352).

    Measured on this gate BEFORE the cure: every row below was allowed AND
    unrecorded except the bare lowercase spelling. Two losses in one, and the
    second is the quiet one — the record is the only trace the unsanctioned lane
    leaves, so a spelling the gate could not read deleted without a line.
    """

    CWD = str(Path(__file__).resolve().parent.parent)

    BLOCKED = (
        "rm.exe -rf build/x",
        "RM -rf build/x",
        "Rm -rf build/x",
        "/usr/bin/rm.exe -rf build/x",
        "C:\\Windows\\System32\\rm.exe -rf C:\\tmp\\x",
        "sudo RM.EXE -rf build/x",
    )
    PLAIN = ("rm.exe build/x", "RM build/x")

    def _bash(self, command: str) -> dict:
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.CWD})

    def test_every_spelling_of_a_recursive_delete_is_blocked(self):
        for command in self.BLOCKED:
            assert self._bash(command)["exit_code"] == 2, f"not refused: {command!r}"

    def test_every_spelling_of_a_plain_delete_is_refused_too(self):
        for command in self.PLAIN:
            assert self._bash(command)["exit_code"] == 2, f"not refused: {command!r}"

    def test_drone_spelled_any_way_is_the_admin_seats_lane(self):
        """DRONE rm is drone's lane, not a raw rm: the grant decides it, as for the bare spelling."""
        assert "admin seat's alone" in json.loads(self._bash("DRONE rm -rf build/x")["stdout"])["reason"]
        with patch("aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller", return_value=True):
            assert self._bash("DRONE rm -rf build/x")["exit_code"] == 0

    def test_a_renamed_delete_reaches_the_record(self, caplog):
        with caplog.at_level(logging.INFO):
            self._bash("rm.exe notes.txt")

        records = [r for r in caplog.records if "DELETE" in r.getMessage()]
        assert len(records) == 1
        assert "rm.exe notes.txt" in records[0].getMessage()

    def test_the_reader_being_away_leaves_the_old_narrow_reading(self):
        """Fail-safe direction: the bare spelling still refuses, and the log says so."""
        with patch("aipass.hooks.apps.modules.bash_writes.verb_name", side_effect=RuntimeError("boom")):
            assert self._bash("rm -rf build/x")["exit_code"] == 2


_RAIL = "aipass.ai_mail.apps.modules.door_verified_caller.is_verified_admin_caller"


def _seat(root: Path, name: str) -> str:
    """A branch directory carrying a passport that names *name*."""
    seat = root / name
    (seat / ".trinity").mkdir(parents=True)
    (seat / ".trinity" / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": name}}), encoding="utf-8"
    )
    return str(seat)


class TestTheLockdown:
    """DPLAN-0356, the owner 2026-09-30: raw rm refused for every seat, drone rm for @devpulse alone.

    WHO is the verified admin grant (@ai_mail's rail, patched here at that edge);
    the passport only names the caller in the refusal and the record.
    """

    def _run(self, command: str, cwd: str, grant: bool) -> dict:
        with patch(_RAIL, return_value=grant):
            return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})

    def _reason(self, result: dict) -> str:
        assert result["exit_code"] == 2
        return json.loads(result["stdout"])["reason"]

    def test_a_plain_rm_from_canary_is_refused_and_teaches_rename_or_archive(self, tmp_path):
        reason = self._reason(self._run("rm notes.txt", _seat(tmp_path, "canary"), grant=False))

        assert "@canary" in reason
        assert "(disabled)" in reason and ".archive/" in reason and "@devpulse" in reason
        assert "drone rm" not in reason

    def test_a_recursive_rm_from_canary_is_refused_the_same_way(self, tmp_path):
        reason = self._reason(self._run("rm -rf build", _seat(tmp_path, "canary"), grant=False))

        assert ".archive/" in reason and "drone rm" not in reason

    def test_drone_rm_from_canary_is_refused(self, tmp_path):
        reason = self._reason(self._run("drone rm notes.txt", _seat(tmp_path, "canary"), grant=False))

        assert "@canary" in reason and "admin" in reason

    def test_drone_rm_from_the_verified_admin_seat_is_allowed(self, tmp_path):
        result = self._run("drone rm notes.txt", _seat(tmp_path, "devpulse"), grant=True)

        assert (result["exit_code"], result["stdout"]) == (0, "")

    def test_a_seat_named_devpulse_without_the_grant_is_refused_drone_rm(self, tmp_path):
        self._reason(self._run("drone rm notes.txt", _seat(tmp_path, "devpulse"), grant=False))

    def test_a_raw_rm_from_the_admin_seat_is_refused_and_teaches_drone_rm(self, tmp_path):
        reason = self._reason(self._run("rm notes.txt", _seat(tmp_path, "devpulse"), grant=True))

        assert "drone rm <path>" in reason

    def test_a_caller_with_no_passport_is_refused_and_told_so(self, tmp_path):
        reason = self._reason(self._run("drone rm notes.txt", str(tmp_path), grant=False))

        assert "could not be named" in reason

    def test_rm_inside_a_shell_inline_script_is_refused(self, tmp_path):
        self._reason(self._run('bash -c "rm notes.txt"', _seat(tmp_path, "canary"), grant=False))

    def test_quoted_text_naming_rm_is_not_a_delete(self, tmp_path):
        result = self._run('drone @ai_mail email @x "S" "please rm notes.txt"', _seat(tmp_path, "canary"), grant=False)

        assert result["exit_code"] == 0

    def test_every_refused_attempt_is_recorded(self, tmp_path, caplog):
        canary = _seat(tmp_path, "canary")
        with caplog.at_level(logging.INFO):
            self._run("rm a.txt", canary, grant=False)
            self._run("drone rm b.txt", canary, grant=False)

        records = [r.getMessage() for r in caplog.records if "DELETE" in r.getMessage()]
        assert len(records) == 2
        assert all("refused" in r and "branch=canary" in r for r in records)


class TestEveryDeleteVerb:
    """The owner, 2026-09-30 (dab4e222): "rm is a big no no; only devpulse deletes."

    Every verb is refused off the admin seat with the rename/.archive text and
    allowed on it; moving, renaming and mkdir are never deletes. One row per verb,
    so the red team's canary list reads straight off this class.
    """

    REFUSED = (
        "rmdir build",
        "unlink notes.txt",
        "shred -u notes.txt",
        "find . -name '*.pyc' -delete",
        "find . -type d -empty -exec rmdir {} +",
        "ls | xargs -0 unlink",
        "sudo shred notes.txt",
        "env A=1 rmdir build",
        "/usr/bin/RMDIR build",
        "bash -c 'rmdir build'",
        "python3 -c \"import os; os.remove('notes.txt')\"",
        "python3 -c \"import os; os.unlink('notes.txt')\"",
        "python -c \"import shutil; shutil.rmtree('build')\"",
        "python3 -c \"from pathlib import Path; Path('notes.txt').unlink()\"",
        "python3 - <<'EOF'\nimport shutil\nshutil.rmtree('build')\nEOF",
        "python3 -c \"import subprocess; subprocess.run(['rm', 'notes.txt'])\"",
        "node -e \"require('fs').rmSync('build', {recursive: true})\"",
        "node -e \"require('fs').unlinkSync('notes.txt')\"",
        "perl -e 'unlink \"notes.txt\"'",
        "ruby -e \"FileUtils.rm_rf('build')\"",
        "php -r \"unlink('notes.txt');\"",
        "su -lc 'rmdir build'",
        "script -qc 'rmdir build'",
        "su root -c 'rmdir build'",
        "runuser alice --command='rmdir build'",
        "flock lock.f -c 'rmdir build'",
        "parallel ::: 'rmdir build'",
        "parallel -j2 ::: 'rmdir build'",
    )
    RAW_RM = (r"find . -name x -exec rm {} \;", "ls | xargs rm")
    ALLOWED = (
        "mkdir -p .archive && mv old.py .archive/",
        "mv old.py 'old(disabled).py'",
        "grep -rn unlink .",
        "echo rmdir",
        "find . -name '*.pyc'",
        "bash -c 'echo rmdir'",
        "parallel echo ::: rmdir",
        "su -sc root",
        'python3 -c "xs = [1]; xs.remove(1)"',
        "python3 -c \"print('rm is refused')\"",
    )

    def _run(self, command: str, cwd: str, grant: bool) -> dict:
        with patch(_RAIL, return_value=grant):
            return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})

    @pytest.mark.parametrize("command", REFUSED)
    def test_each_delete_verb_from_canary_is_refused_with_the_archive_text(self, tmp_path, command):
        result = self._run(command, _seat(tmp_path, "canary"), grant=False)

        assert result["exit_code"] == 2, command
        reason = json.loads(result["stdout"])["reason"]
        assert "is a delete" in reason and "@canary" in reason
        assert "(disabled)" in reason and ".archive/" in reason and "@devpulse" in reason

    @pytest.mark.parametrize("command", REFUSED)
    def test_each_delete_verb_from_the_admin_seat_is_allowed(self, tmp_path, command):
        result = self._run(command, _seat(tmp_path, "devpulse"), grant=True)

        assert (result["exit_code"], result["stdout"]) == (0, ""), command

    @pytest.mark.parametrize("command", RAW_RM)
    def test_find_exec_rm_and_xargs_rm_are_raw_rm_for_every_seat(self, tmp_path, command):
        for name, grant in (("canary", False), ("devpulse", True)):
            result = self._run(command, _seat(tmp_path / name, name), grant=grant)
            assert result["exit_code"] == 2, (command, name)
            assert "Raw rm is refused" in json.loads(result["stdout"])["reason"]

    @pytest.mark.parametrize("command", ALLOWED)
    def test_moves_renames_and_the_word_alone_are_not_deletes(self, tmp_path, command):
        result = self._run(command, _seat(tmp_path, "canary"), grant=False)

        assert (result["exit_code"], result["stdout"]) == (0, ""), command

    def test_a_script_file_is_read_at_decision_time(self, tmp_path):
        """DPLAN-0356 phase 3, R4 (red team, HIGH): a program on disk was never read."""
        seat = Path(_seat(tmp_path, "canary"))
        (seat / "cleanup.py").write_text("import os\nos.remove('notes.txt')\n", encoding="utf-8")
        (seat / "clean.sh").write_text("#!/bin/sh\nrmdir build\n", encoding="utf-8")
        (seat / "build.sh").write_text("#!/bin/sh\necho rmdir\n", encoding="utf-8")

        for command in (
            "python3 cleanup.py",
            "bash clean.sh",
            "sh ./clean.sh",
            "./clean.sh",
            "source clean.sh",
            ". clean.sh",
        ):
            result = self._run(command, str(seat), grant=False)
            assert result["exit_code"] == 2, command
            assert "is a delete" in json.loads(result["stdout"])["reason"], command
        assert (self._run("bash build.sh rmdir", str(seat), grant=False)["exit_code"]) == 0

    @pytest.mark.parametrize(
        "command", ["bash <(echo 'rm notes.txt')", "source <(echo hi)", ". <(echo hi)", "bash < <(echo hi)"]
    )
    def test_a_process_substitution_program_is_unread(self, tmp_path, command):
        """`<(...)` is no script on disk: its program is another command's output, never 'not written yet'."""
        result = self._run(command, _seat(tmp_path, "canary"), grant=False)
        assert result["exit_code"] == 2, command
        assert "process substitution" in json.loads(result["stdout"])["reason"], command

    def test_sed_runs_what_its_e_command_names(self, tmp_path):
        """e COMMAND runs a shell command; s///e runs the pattern space, which no reader sees."""
        seat = _seat(tmp_path, "canary")
        assert self._run("sed '1e rmdir build' notes.txt", seat, grant=False)["exit_code"] == 2
        assert self._run("sed -e p -e '2 e rmdir build' notes.txt", seat, grant=False)["exit_code"] == 2
        result = self._run("sed -n 's/x/y/e' notes.txt", seat, grant=False)
        assert "pattern space" in json.loads(result["stdout"])["reason"]
        for command in ("sed -n '/rmdir/p' notes.txt", "sed 's/rmdir/e/' notes.txt", "sed '1a rmdir e' notes.txt"):
            assert self._run(command, seat, grant=False)["exit_code"] == 0, command

    def test_a_process_substitution_a_reader_reads_is_no_program(self, tmp_path):
        assert self._run("diff <(ls a) <(ls b)", _seat(tmp_path, "canary"), grant=False)["exit_code"] == 0

    def test_a_script_that_cannot_be_read_is_refused_off_the_admin_seat(self, tmp_path):
        seat = Path(_seat(tmp_path, "canary"))
        (seat / "huge.py").write_text("x = 1\n" * 200_000, encoding="utf-8")

        (seat / "adir.sh").mkdir()

        for command in ("python3 huge.py", "bash adir.sh"):
            result = self._run(command, str(seat), grant=False)
            assert result["exit_code"] == 2, command
            assert "cannot read" in json.loads(result["stdout"])["reason"], command
        assert self._run("python3 huge.py", _seat(tmp_path, "devpulse"), grant=True)["exit_code"] == 0

    def test_a_script_not_yet_written_is_allowed_and_logged(self, tmp_path, caplog):
        """DPLAN-0356 phase 4, P1: refusing it broke the write-a-helper-then-run-it idiom."""
        seat = _seat(tmp_path, "canary")
        with caplog.at_level(logging.INFO):
            for command in (
                "python3 helper.py",
                "./build.sh",
                "cat > helper.py <<'EOF'\nprint('ok')\nEOF\npython3 helper.py",
            ):
                result = self._run(command, seat, grant=False)
                assert (result["exit_code"], result["stdout"]) == (0, ""), command
        assert any("does not exist yet" in r.getMessage() for r in caplog.records)

    def test_the_time_of_check_residual_is_named_in_not_caught(self):
        assert any("changes after the check" in gap for gap in bash_writes.NOT_CAUGHT)

    def test_each_refused_verb_is_recorded(self, tmp_path, caplog):
        canary = _seat(tmp_path, "canary")
        with caplog.at_level(logging.INFO):
            self._run("rmdir build", canary, grant=False)

        records = [r.getMessage() for r in caplog.records if "DELETE" in r.getMessage()]
        assert len(records) == 1 and "lane=delete verb" in records[0]


class TestTheShellSpellingIsReadTheWayTheShellRunsIt:
    """DPLAN-0356 phase 3, R3 (red team, HIGH): the gates read raw tokens, the shell runs joined words.

    Each spelling below runs rm. Before modules/shell_reader every one read as an unknown program.
    """

    SPELLINGS = (
        "r\\m notes.txt",
        "'r'm notes.txt",
        '"rm" notes.txt',
        "$'\\x72\\x6d' notes.txt",
        "$'\\162\\155' notes.txt",
        "{rm,notes.txt}",
        "/bin/r? notes.txt",
        "X=rm; $X notes.txt",
        "eval 'rm notes.txt'",
        'eval "r""m notes.txt"',
        "echo $(rm notes.txt)",
        "bash <<< 'rm notes.txt'",
    )

    @pytest.mark.parametrize("command", SPELLINGS)
    def test_each_spelling_is_raw_rm(self, tmp_path, command):
        with patch(_RAIL, return_value=False):
            result = handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": _seat(tmp_path, "canary")})

        assert result["exit_code"] == 2, command
        assert "Raw rm is refused" in json.loads(result["stdout"])["reason"], command

    def test_a_glob_that_matches_nothing_the_gate_can_list_is_read_as_the_verb_it_names(self, tmp_path):
        """CI red PR #774 (Windows): Git Bash's /bin is a mount the gate cannot list, so /bin/r? read as r?."""
        unlisted = tmp_path / "bin"
        unlisted.mkdir()
        command = f"{unlisted.as_posix()}/r? notes.txt"
        with patch(_RAIL, return_value=False):
            result = handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": _seat(tmp_path, "canary")})

        assert result["exit_code"] == 2
        assert "Raw rm is refused" in json.loads(result["stdout"])["reason"]

    @pytest.mark.parametrize("command", ("$UNSET notes.txt", "echo 'rm notes.txt' | bash", "$(cat verb) notes.txt"))
    def test_a_program_the_reader_cannot_name_is_refused_off_the_admin_seat(self, tmp_path, command):
        with patch(_RAIL, return_value=False):
            result = handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": _seat(tmp_path, "canary")})

        assert result["exit_code"] == 2, command
        assert "cannot read" in json.loads(result["stdout"])["reason"], command

    def test_the_admin_seat_runs_what_the_reader_cannot_name(self, tmp_path):
        with patch(_RAIL, return_value=True):
            result = handle(
                {"tool_name": "Bash", "tool_input": {"command": "$TOOL x"}, "cwd": _seat(tmp_path, "devpulse")}
            )

        assert (result["exit_code"], result["stdout"]) == (0, "")

    def test_many_arithmetic_commands_read_in_linear_time(self, tmp_path):
        """Each (( once searched every token after it for its )): 8000 of them took 11s."""
        command = "(( 1 )); " * 8000 + "rm notes.txt"
        started = time.monotonic()
        with patch(_RAIL, return_value=False):
            result = handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": _seat(tmp_path, "canary")})

        assert time.monotonic() - started < 3
        assert "Raw rm is refused" in json.loads(result["stdout"])["reason"]


class TestAnUnknownWrapperIsReadForWhatItRuns:
    """DPLAN-0356 phase 4, P3 (final review, HIGH): only tabled launchers were followed.

    A command word that is not a known plain program has its operands scanned for a
    delete verb, git or gh, and is read from there. Programs whose operands are data are not.
    """

    def _run(self, tmp_path, command: str) -> dict:
        with patch(_RAIL, return_value=False):
            return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": _seat(tmp_path, "canary")})

    @pytest.mark.parametrize("command", ("mywrapper rm notes.txt", "npx some-tool --quiet rm -rf build"))
    def test_an_unknown_wrapper_around_rm_is_refused(self, tmp_path, command):
        result = self._run(tmp_path, command)

        assert result["exit_code"] == 2, command
        assert "Raw rm is refused" in json.loads(result["stdout"])["reason"], command

    @pytest.mark.parametrize(
        "command",
        ("grep -rn rm .", "echo rm notes.txt", "printf 'git push'", "touch rm", "mv rm.log old.log", "git rm x"),
    )
    def test_a_program_whose_operands_are_data_is_not_scanned(self, tmp_path, command):
        result = self._run(tmp_path, command)

        assert (result["exit_code"], result["stdout"]) == (0, ""), command
