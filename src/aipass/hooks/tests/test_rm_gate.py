# =================== AIPass ====================
# Name: test_rm_gate.py
# Version: 1.1.0
# Description: Tests for rm_gate security handler
# Branch: hooks
# Created: 2026-06-02
# Modified: 2026-08-14
# =============================================

"""Tests for handlers/security/rm_gate.py."""

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.security import rm_gate
from aipass.prax.apps.modules.logger import system_logger
from aipass.hooks.apps.handlers.security.rm_gate import (
    _clause_has_raw_recursive_rm,
    _has_recursive_flag,
    _split_clauses,
    _strip_quotes,
    handle,
)

_BRANCH = Path(__file__).resolve().parent.parent
# Both sinks the prax logger feeds. system_logs/ is the aggregate @trigger watches —
# that is the file whose 3597 lines/min fired the runaway alert (fc74ef8b).
LIVE_RECORDS = (
    _BRANCH / "logs" / "rm_gate.log",
    _BRANCH.parents[2] / "system_logs" / "hooks_rm_gate.log",
)


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


class TestStripQuotes:
    def test_double_quotes(self):
        assert _strip_quotes('rm -rf "/tmp/foo bar"') == 'rm -rf ""'

    def test_single_quotes(self):
        assert _strip_quotes("rm -rf '/tmp/foo bar'") == "rm -rf ''"

    def test_escaped_quote_in_double(self):
        assert _strip_quotes(r'echo "he said \"hi\""') == 'echo ""'

    def test_no_quotes(self):
        assert _strip_quotes("rm -rf /tmp/foo") == "rm -rf /tmp/foo"

    def test_mixed_quotes(self):
        result = _strip_quotes("""echo "hello" && rm -rf '/tmp/x'""")
        assert "rm" in result
        assert "/tmp/x" not in result


class TestSplitClauses:
    def test_and_operator(self):
        clauses = _split_clauses("cd /tmp && rm -rf foo")
        assert any("rm" in c for c in clauses)

    def test_semicolon(self):
        clauses = _split_clauses("echo hi; rm -rf /tmp/x")
        assert any("rm" in c for c in clauses)

    def test_pipe(self):
        clauses = _split_clauses("ls | rm -rf /tmp/x")
        assert any("rm" in c for c in clauses)

    def test_or_operator(self):
        clauses = _split_clauses("true || rm -rf /tmp/x")
        assert any("rm" in c for c in clauses)

    def test_subshell(self):
        clauses = _split_clauses("echo $(rm -rf /tmp/x)")
        assert any("rm" in c for c in clauses)

    def test_backtick_subshell(self):
        clauses = _split_clauses("echo `rm -rf /tmp/x`")
        assert any("rm" in c for c in clauses)


class TestHasRecursiveFlag:
    def test_rf(self):
        assert _has_recursive_flag(["-rf", "/tmp/x"]) is True

    def test_fr(self):
        assert _has_recursive_flag(["-fr", "/tmp/x"]) is True

    def test_r_alone(self):
        assert _has_recursive_flag(["-r", "/tmp/x"]) is True

    def test_uppercase_r(self):
        assert _has_recursive_flag(["-R", "/tmp/x"]) is True

    def test_rfv(self):
        assert _has_recursive_flag(["-rfv", "/tmp/x"]) is True

    def test_recursive_long(self):
        assert _has_recursive_flag(["--recursive", "/tmp/x"]) is True

    def test_no_recursive(self):
        assert _has_recursive_flag(["-f", "/tmp/x"]) is False

    def test_after_double_dash(self):
        assert _has_recursive_flag(["--", "-rf", "/tmp/x"]) is False

    def test_empty(self):
        assert _has_recursive_flag([]) is False


class TestClauseHasRawRecursiveRm:
    def test_basic_rm_rf(self):
        assert _clause_has_raw_recursive_rm("rm -rf /tmp/x") is True

    def test_rm_fr(self):
        assert _clause_has_raw_recursive_rm("rm -fr /tmp/x") is True

    def test_rm_rfv(self):
        assert _clause_has_raw_recursive_rm("rm -rfv /tmp/x") is True

    def test_rm_recursive_long(self):
        assert _clause_has_raw_recursive_rm("rm --recursive /tmp/x") is True

    def test_rm_uppercase_r(self):
        assert _clause_has_raw_recursive_rm("rm -R /tmp/x") is True

    def test_drone_rm_not_blocked(self):
        assert _clause_has_raw_recursive_rm("drone rm /tmp/x") is False

    def test_non_recursive_rm(self):
        assert _clause_has_raw_recursive_rm("rm file.txt") is False

    def test_rm_force_only(self):
        assert _clause_has_raw_recursive_rm("rm -f file.txt") is False

    def test_sudo_rm_rf(self):
        assert _clause_has_raw_recursive_rm("sudo rm -rf /tmp/x") is True

    def test_env_prefix_rm_rf(self):
        assert _clause_has_raw_recursive_rm("env VAR=val rm -rf /tmp/x") is True

    def test_absolute_path_rm(self):
        assert _clause_has_raw_recursive_rm("/usr/bin/rm -rf /tmp/x") is True

    def test_empty_clause(self):
        assert _clause_has_raw_recursive_rm("") is False

    def test_whitespace_clause(self):
        assert _clause_has_raw_recursive_rm("   ") is False


class TestHandle:
    CWD = "/home/patrick/Projects/AIPass/src/aipass/hooks"

    def _bash(self, command: str) -> dict:
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.CWD})

    def _assert_blocked(self, result: dict):
        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "drone rm" in parsed["reason"]

    def _assert_allowed(self, result: dict):
        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_block_rm_rf(self):
        self._assert_blocked(self._bash("rm -rf /tmp/x"))

    def test_block_rm_fr(self):
        self._assert_blocked(self._bash("rm -fr /tmp/x"))

    def test_block_rm_rfv(self):
        self._assert_blocked(self._bash("rm -rfv /tmp/x"))

    def test_block_rm_recursive_long(self):
        self._assert_blocked(self._bash("rm --recursive /tmp/x"))

    def test_block_rm_uppercase_r(self):
        self._assert_blocked(self._bash("rm -R /tmp/x"))

    def test_block_rm_r(self):
        self._assert_blocked(self._bash("rm -r /tmp/x"))

    def test_allow_drone_rm(self):
        self._assert_allowed(self._bash("drone rm /tmp/x"))

    def test_allow_non_recursive_rm(self):
        self._assert_allowed(self._bash("rm file.txt"))

    def test_allow_rm_force_only(self):
        self._assert_allowed(self._bash("rm -f file.txt"))

    def test_block_compound_cd_and_rm(self):
        self._assert_blocked(self._bash("cd /etc && rm -rf ."))

    def test_block_compound_semicolon(self):
        self._assert_blocked(self._bash("echo hi; rm -rf /tmp/x"))

    def test_block_subshell_rm(self):
        self._assert_blocked(self._bash("echo $(rm -rf /tmp/x)"))

    def test_block_sudo_rm_rf(self):
        self._assert_blocked(self._bash("sudo rm -rf /tmp/x"))

    def test_block_absolute_path_rm(self):
        self._assert_blocked(self._bash("/usr/bin/rm -rf /tmp/x"))

    def test_rm_in_quoted_string_allowed(self):
        self._assert_allowed(self._bash('echo "rm -rf /tmp/x"'))

    def test_rm_in_single_quoted_string_allowed(self):
        self._assert_allowed(self._bash("echo 'rm -rf /tmp/x'"))

    def test_non_bash_tool_allowed(self):
        result = handle({"tool_name": "Edit", "tool_input": {"file_path": "/tmp/x"}, "cwd": self.CWD})
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
    def test_exception_allows(self, mock_logger):
        result = handle({"tool_name": "Bash", "tool_input": None, "cwd": self.CWD})
        assert result["exit_code"] == 0
        mock_logger.info.assert_called()

    def test_block_variable_target(self):
        self._assert_blocked(self._bash("rm -rf $DIR"))

    def test_block_multiple_targets(self):
        self._assert_blocked(self._bash("rm -rf /tmp/a /tmp/b"))


class TestDeletionRecord:
    """Patrick, 2026-08-14: "we need a log for deleted files - if something deletes,
    it should be a record of it."

    @drone records the sanctioned lane (drone rm). This covers the leak this gate
    already sees but never wrote down: a raw single-file rm, which passes through
    silently today. This is a RECORD, not a gate - nothing new is blocked.
    """

    CWD = "/home/patrick/Projects/AIPass/src/aipass/hooks"

    def _bash(self, command: str, cwd: str | None = None) -> dict:
        return handle({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd or self.CWD})

    def _audit_records(self, caplog):
        return [r for r in caplog.records if "DELETE" in r.getMessage()]

    def test_allowed_plain_rm_is_recorded(self, caplog):
        with caplog.at_level(logging.INFO):
            result = self._bash("rm notes.txt")

        assert result["exit_code"] == 0, "recording must not turn into blocking"
        assert result["stdout"] == ""
        records = self._audit_records(caplog)
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "rm notes.txt" in msg
        assert self.CWD in msg
        assert "hooks" in msg

    def test_the_record_is_info_never_warning(self, caplog):
        """Compass #273: an allowed command is chosen behaviour, not an escalation."""
        with caplog.at_level(logging.INFO):
            self._bash("rm notes.txt")

        records = self._audit_records(caplog)
        assert records
        assert all(r.levelno == logging.INFO for r in records)

    def test_blocked_recursive_rm_is_recorded_with_its_command(self, caplog):
        """The engine logs THAT a block happened; only this line says WHAT it was."""
        with caplog.at_level(logging.INFO):
            result = self._bash("rm -rf /tmp/x")

        assert result["exit_code"] == 2, "the block itself must not change"
        records = self._audit_records(caplog)
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "blocked" in msg
        assert "rm -rf /tmp/x" in msg

    def test_drone_rm_is_not_recorded_here(self, caplog):
        """The sanctioned lane is @drone's record — double-logging it would be a lie
        about how many deletions happened."""
        with caplog.at_level(logging.INFO):
            self._bash("drone rm /tmp/x")

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

    def test_a_broken_passport_does_not_break_the_gate(self, caplog, tmp_path):
        project = tmp_path / "proj"
        (project / ".trinity").mkdir(parents=True)
        (project / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")

        with caplog.at_level(logging.INFO):
            result = self._bash("rm notes.txt", cwd=str(project))

        assert result["exit_code"] == 0
        assert len(self._audit_records(caplog)) == 1

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
            self._bash("rm -rf /tmp/x")

        for path, before in sizes.items():
            assert path.stat().st_size == before, f"tests polluted the live record: {path}"
        assert rm_gate.logger is not system_logger, "the handler is holding the live logger under test"

    def test_the_command_is_recorded_as_seen_not_as_scanned(self, caplog):
        """Quote-stripping is an implementation detail of matching, not evidence."""
        with caplog.at_level(logging.INFO):
            self._bash('rm "my notes.txt"')

        records = self._audit_records(caplog)
        assert records
        assert 'rm "my notes.txt"' in records[0].getMessage()


class TestAllowDenyUnchanged:
    """Canary: the record must not move a single allow/deny decision."""

    MATRIX = [
        ("rm -rf /tmp/x", 2),
        ("rm -r /tmp/x", 2),
        ("rm -R /tmp/x", 2),
        ("rm --recursive /tmp/x", 2),
        ("rm -rfv /tmp/x", 2),
        ("ls && rm -rf build", 2),
        ("rm notes.txt", 0),
        ("rm -f notes.txt", 0),
        ("drone rm /tmp/x", 0),
        ("drone rm -rf /tmp/x", 0),
        ("echo 'rm -rf /tmp/x'", 0),
        ("ls -la", 0),
        ("", 0),
    ]

    def test_decisions_are_identical_to_the_pre_record_gate(self):
        for command, expected in self.MATRIX:
            result = handle(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "cwd": "/home/patrick/Projects/AIPass/src/aipass/hooks",
                }
            )
            assert result["exit_code"] == expected, f"decision changed for: {command!r}"
