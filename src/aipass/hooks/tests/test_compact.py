# =================== AIPass ====================
# Name: test_compact.py
# Version: 2.0.1
# Description: Tests for the compaction handlers: summary instructions (PreCompact), resume list (SessionStart)
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-11-26
# =============================================

"""Tests for apps/handlers/lifecycle/compact.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(generated) — the logger.info lines on each except path; the text is the exception's own

import json
import subprocess
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.lifecycle import compact
from aipass.hooks.apps.handlers.lifecycle.compact import handle, handle_resume
from aipass.hooks.apps.modules import cadence, context_window


@pytest.fixture(autouse=True)
def _isolate_cadence_state(tmp_path, monkeypatch):
    """handle() resets cadence for real: unisolated, each test re-armed the developer's own session's re-ground."""
    monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-compact-session")


_PROMPT = "Run the night shift: finish the bypass sweep, then mail devpulse the totals."


def _branch(tmp_path, unread=3, git=True):
    """A seat: .trinity, an inbox, a transcript whose newest rows are a tool result and a harness wake-up."""
    seat = tmp_path / "seat"
    (seat / ".trinity").mkdir(parents=True)
    (seat / ".trinity" / "local.json").write_text(
        json.dumps({"sessions": [{"number": 10, "date": "2026-11-25", "summary": "swept 40 rows"}]}), encoding="utf-8"
    )
    if unread is not None:
        (seat / ".ai_mail.local").mkdir()
        (seat / ".ai_mail.local" / "inbox.json").write_text(json.dumps({"unread_count": unread}), encoding="utf-8")
    if git:
        subprocess.run(["git", "init", "-q", str(seat)], check=True, capture_output=True)
        (seat / "notes.py").write_text("x = 1\n", encoding="utf-8")
    rows = [
        {"type": "user", "message": {"content": "an older line"}},
        {"type": "user", "message": {"content": _PROMPT}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "user", "message": {"content": "<task-notification>monitor expired</task-notification>"}},
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
    ]
    transcript = tmp_path / "chat.jsonl"
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return seat, transcript


def _plan(seat, log_line="- [x] swept rows 1-40"):
    plan = seat / "FPLAN-0001_sweep.md"
    plan.write_text(
        f"# FPLAN-0001\n\n## Execution Log\n\n### 2026-11-25\n{log_line}\n\n---\n\n## Notes\nx\n", encoding="utf-8"
    )
    return [("0001", {"location": str(seat.resolve()), "file_path": str(plan), "created": "2026-11-25T01:00"})]


def _run(handler, seat, transcript, plans=(), dispatches=(), **extra):
    with (
        patch("aipass.flow.get_open_plans", return_value=list(plans)),
        patch("aipass.ai_mail.outstanding_dispatches", return_value=list(dispatches)),
    ):
        return handler({"cwd": str(seat), "transcript_path": str(transcript), **extra})


class TestCompactHandler:
    """PreCompact stdout is the summarizer's instructions: what the summary must carry and how it ends."""

    def test_the_summary_is_told_to_carry_the_work_still_out_and_end_on_the_resume_order(self, tmp_path):
        seat, transcript = _branch(tmp_path)
        sent = {"sender": "@seat", "target": "@sentry", "subject": "Audit the sweep"}
        owed = {"sender": "@devpulse", "target": "@seat", "subject": "Night shift"}
        result = _run(handle, seat, transcript, _plan(seat), [sent, owed, {"sender": "@a", "target": "@b"}])

        out = result["stdout"]
        assert result["exit_code"] == 0 and result["sound"] == "pre compact"
        assert 'section headed "Work still out"' in out
        assert out.endswith(f'verbatim: "{compact.RESUME_SENTENCE}"')
        assert "- Uncommitted files: 4: ?? .ai_mail.local/, ?? .trinity/, ?? FPLAN-0001_sweep.md, ?? notes.py" in out
        assert "- Open dispatches: sent to @sentry: Audit the sweep; from @devpulse, still open: Night shift" in out
        assert "- Unread mail: 3" in out
        assert "- Newest open plan: FPLAN-0001_sweep.md; last log line: - [x] swept rows 1-40" in out
        assert "- Last session (#10, 2026-11-25): swept 40 rows" in out
        assert f"- The user's last instruction, verbatim: {_PROMPT}" in out

    def test_every_part_at_its_cap_stays_under_8000_characters(self, tmp_path):
        seat, transcript = _branch(tmp_path)
        for i in range(300):
            (seat / f"{'long_file_name_' * 6}{i}.py").write_text("x\n", encoding="utf-8")
        with transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "w" * 20_000}}) + "\n")
        dispatches = [{"sender": "@seat", "target": "@x", "subject": "s" * 900} for _ in range(40)]
        out = _run(handle, seat, transcript, _plan(seat, "l" * 5000), dispatches)["stdout"]
        assert "Uncommitted files: 304: " in out and "(+279 more)" in out and "[…cut]" in out
        assert len(out) < 8000

    def test_a_reader_that_fails_is_written_into_the_list_not_dropped(self, tmp_path):
        seat, transcript = _branch(tmp_path, unread=None, git=False)
        out = _run(handle, seat, transcript)["stdout"]
        assert "- Unread mail: could not be read (FileNotFoundError" in out
        assert "- Uncommitted files: could not be read (RuntimeError" in out
        assert "- Newest open plan: none" in out and "- Open dispatches: none" in out

    def test_the_log_line_skips_fenced_blocks_and_bold_notes(self, tmp_path):
        seat, transcript = _branch(tmp_path)
        plans = _plan(seat, "- [x] swept rows 1-40\n\n**Log Pattern:** Task\n\n```bash\ndrone @flow close X\n```")
        out = _run(handle, seat, transcript, plans)["stdout"]
        assert "- Newest open plan: FPLAN-0001_sweep.md; last log line: - [x] swept rows 1-40" in out

    def test_only_the_seats_own_tree_counts_as_uncommitted(self, tmp_path):
        seat, transcript = _branch(tmp_path, git=False)
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
        (tmp_path / "other_branch.py").write_text("y = 2\n", encoding="utf-8")
        out = _run(handle, seat, transcript)["stdout"]
        assert "other_branch.py" not in out
        assert "- Uncommitted files: 1: ?? seat/" in out

    def test_a_dispatched_seat_is_told_to_save_memories_first(self, tmp_path, monkeypatch):
        seat, transcript = _branch(tmp_path)
        monkeypatch.setenv("AIPASS_SESSION_TYPE", "dispatched")
        assert "next turn saves its memories first" in _run(handle, seat, transcript)["stdout"]

    def test_no_branch_dir_still_instructs_the_summary(self, tmp_path):
        out = _run(handle, tmp_path / "nowhere", tmp_path / "missing.jsonl")["stdout"]
        assert "seat @unknown" in out and out.endswith(f'"{compact.RESUME_SENTENCE}"')
        assert "- The user's last instruction, verbatim: could not be read (FileNotFoundError" in out


class TestCompactResume:
    """SessionStart after a compaction re-injects the same list, as context, with one resume line."""

    def test_source_compact_injects_the_work_still_out_as_context(self, tmp_path):
        seat, transcript = _branch(tmp_path)
        result = _run(handle_resume, seat, transcript, _plan(seat), source="compact")
        out = json.loads(result["stdout"])["hookSpecificOutput"]
        assert out["hookEventName"] == "SessionStart"
        context = out["additionalContext"]
        assert context.startswith("WORK STILL OUT — @seat")
        assert context.endswith("Resume this list before replying: answer the user's last line only inside that work.")
        assert "- Newest open plan: FPLAN-0001_sweep.md; last log line: - [x] swept rows 1-40" in context
        assert f"- The user's last instruction, verbatim: {_PROMPT}" in context

    @pytest.mark.parametrize("source", ["startup", "resume", "clear", ""])
    def test_any_other_source_injects_nothing(self, tmp_path, source):
        seat, transcript = _branch(tmp_path)
        assert _run(handle_resume, seat, transcript, source=source) == {"stdout": "", "exit_code": 0}


class TestARaiseIsTheEnginesFault:
    def test_an_unexpected_raise_is_one_engine_fault_line_and_compaction_goes_on(self, engine_fault, tmp_path):
        handler = f"{compact.__name__}.handle"
        with patch.object(context_window, "find_branch_dir", side_effect=RuntimeError("boom")):
            faults, (stdout, code) = engine_fault("PreCompact", "pre_compact", handler, {"cwd": str(tmp_path)})

        assert code != 2 and stdout == ""
        assert len(faults) == 1 and f"fault[PreCompact.pre_compact.{handler}.RuntimeError@" in faults[0]
