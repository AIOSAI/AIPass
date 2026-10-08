# =================== AIPass ====================
# Name: test_edit_gate_trinity_tripwire.py
# Description: edit_gate's memory tripwire: a .trinity write a shell made is reported at PostToolUse, project-wide
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/security/edit_gate.py: tripwire_snapshot and tripwire."""

# The caps on Write and Edit are test_edit_gate_trinity_write.py and
# test_edit_gate_trinity_edit.py; the advisories are test_edit_gate_trinity.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that edit_gate.py parses and its imports resolve

import json
import logging

from aipass.hooks.apps.handlers.security import edit_gate
from aipass.hooks.tests.support_edit_gate_trinity import (
    _TEST_LIMITS_ENFORCE,
    _imports_via_seam,
    _mock_importlib_modules,
)


class TestShellMemoryTripwire:
    """DPLAN-0342 row 3, the tripwire: a memory write the shell reader could not see is reported as it lands.

    The Bash-lane refusal covers every shape the reader claims. Three stay open (a bare file name
    after cd, a path joined in program text, a path in a shell variable), and drift through them
    used to surface weeks later in an audit nobody ran. tripwire_snapshot records the seat's memory
    stats at PreToolUse under the call's tool_use_id; tripwire compares at PostToolUse. The command
    strings are never run: each test writes the file itself, where the shell would have.
    """

    RESIDUAL = 'F=.trinity/local.json; printf "%s" "$doc" > "$F"'
    SILENT = {"stdout": "", "exit_code": 0}

    def _seat(self, tmp_path, monkeypatch):
        monkeypatch.setattr(edit_gate, "_TRIPWIRE_DIR", tmp_path)
        seat = tmp_path / "src" / "aipass" / "hooks"
        (seat / ".trinity").mkdir(parents=True)
        self._write(seat, "local.json", {"sessions": [{"summary": "short"}]})
        return seat

    @staticmethod
    def _write(seat, name, doc):
        text = doc if isinstance(doc, str) else json.dumps(doc)
        (seat / ".trinity" / name).write_text(text, encoding="utf-8")

    def _over_cap(self, seat):
        self._write(seat, "local.json", {"sessions": [{"summary": "s" * 300 + "tail"}]})

    @staticmethod
    def _data(seat, command, tool_use_id="toolu_a"):
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(seat),
            "session_id": "session-1",
            "tool_use_id": tool_use_id,
        }

    def _around(self, seat, command, during=None):
        """Both halves of one call, with *during* standing in for what the shell did."""
        data = self._data(seat, command)
        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_ENFORCE)):
            assert edit_gate.tripwire_snapshot(data) == self.SILENT, "the snapshot never blocks"
            if during:
                during()
            return edit_gate.tripwire(data)

    @staticmethod
    def _context(result):
        assert result["exit_code"] == 0, "the tripwire never blocks: the command has already run"
        return json.loads(result["stdout"])["hookSpecificOutput"]["additionalContext"]

    def test_an_over_cap_write_the_reader_missed_is_named_with_its_cut(self, tmp_path, monkeypatch, caplog):
        seat = self._seat(tmp_path, monkeypatch)
        context = self._context(self._around(seat, self.RESIDUAL, during=lambda: self._over_cap(seat)))
        assert context.startswith("MEMORY WRITTEN FROM A SHELL: ")
        assert "local.json changed during this Bash call" in context
        assert "sessions [0]: 304/300 chars (+4)" in context
        assert '| over: "tail"' in context
        assert "tripwire" in caplog.text
        assert "304/300" in caplog.text

    def test_a_clean_change_still_says_a_shell_wrote_memory(self, tmp_path, monkeypatch):
        seat = self._seat(tmp_path, monkeypatch)
        grown = {"sessions": [{"summary": "short, and a little longer"}]}
        context = self._context(
            self._around(seat, self.RESIDUAL, during=lambda: self._write(seat, "local.json", grown))
        )
        assert "outside the caps gate" in context
        assert "It measures clean" in context

    def test_a_file_written_before_the_call_is_not_blamed_on_it(self, tmp_path, monkeypatch):
        """An Edit that landed just before the call belongs to the gate's lane, not the shell's."""
        seat = self._seat(tmp_path, monkeypatch)
        self._over_cap(seat)
        assert self._around(seat, "drone @ai_mail inbox") == self.SILENT

    def test_a_drone_memory_verb_is_the_sanctioned_writer(self, tmp_path, monkeypatch):
        seat = self._seat(tmp_path, monkeypatch)
        command = "AIPASS_QUIET=1 drone @memory rollover"
        assert self._around(seat, command, during=lambda: self._over_cap(seat)) == self.SILENT

    def test_a_drone_verb_for_another_branch_is_not_sanctioned(self, tmp_path, monkeypatch):
        seat = self._seat(tmp_path, monkeypatch)
        result = self._around(seat, "drone @ai_mail inbox", during=lambda: self._over_cap(seat))
        assert "MEMORY WRITTEN FROM A SHELL" in self._context(result)

    def test_a_file_the_shell_left_unreadable_is_named(self, tmp_path, monkeypatch):
        seat = self._seat(tmp_path, monkeypatch)
        result = self._around(seat, self.RESIDUAL, during=lambda: self._write(seat, "local.json", "x\n"))
        assert "local.json no longer parses as JSON" in self._context(result)

    def test_a_created_memory_file_counts_as_a_change(self, tmp_path, monkeypatch):
        seat = self._seat(tmp_path, monkeypatch)
        note = {"observations": [{"note": "n" * 601}]}
        result = self._around(seat, self.RESIDUAL, during=lambda: self._write(seat, "observations.json", note))
        context = self._context(result)
        assert "observations.json changed" in context
        assert "observations [0]: 601/600 chars (+1)" in context

    def test_each_call_is_compared_with_its_own_snapshot(self, tmp_path, monkeypatch):
        seat = self._seat(tmp_path, monkeypatch)
        first = self._data(seat, self.RESIDUAL, tool_use_id="toolu_first")
        second = self._data(seat, "drone @ai_mail inbox", tool_use_id="toolu_second")
        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_ENFORCE)):
            edit_gate.tripwire_snapshot(first)
            self._over_cap(seat)
            edit_gate.tripwire_snapshot(second)
            assert edit_gate.tripwire(second) == self.SILENT
            assert "304/300" in self._context(edit_gate.tripwire(first))

    def test_the_seat_is_the_one_the_call_started_in(self, tmp_path, monkeypatch):
        """A command that cd's away leaves the PostToolUse payload standing somewhere else."""
        seat = self._seat(tmp_path, monkeypatch)
        before = self._data(seat, self.RESIDUAL)
        after = {**before, "cwd": str(tmp_path)}
        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_ENFORCE)):
            edit_gate.tripwire_snapshot(before)
            self._over_cap(seat)
            assert "304/300" in self._context(edit_gate.tripwire(after))

    def test_a_call_with_no_snapshot_says_nothing_and_logs_why(self, tmp_path, monkeypatch, caplog):
        caplog.set_level(logging.INFO)
        seat = self._seat(tmp_path, monkeypatch)
        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_ENFORCE)):
            assert edit_gate.tripwire(self._data(seat, self.RESIDUAL)) == self.SILENT
        assert "no snapshot for toolu_a" in caplog.text

    def test_the_pending_snapshots_stay_bounded(self, tmp_path, monkeypatch):
        """A call whose PostToolUse never fires (a later gate refused it) must not grow the file."""
        seat = self._seat(tmp_path, monkeypatch)
        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_ENFORCE)):
            for index in range(20):
                edit_gate.tripwire_snapshot(self._data(seat, "ls", tool_use_id=f"toolu_{index}"))
        pending = json.loads((tmp_path / "aipass-trinity-tripwire-session-1.json").read_text(encoding="utf-8"))
        assert list(pending) == [f"toolu_{index}" for index in range(12, 20)]


class TestTripwireWatchesEveryTrinityInTheProject:
    """DPLAN-0347 row 4: the tripwire stats every .trinity in the project, and passport.json with them.

    It used to watch the seat's own two files alone, so the one shape the
    cross-branch fence exists to refuse — a shell write into ANOTHER branch's
    memory, arriving by a path the reader cannot see — landed unreported. Stats
    only: 24 dirs and 72 stats measured ~19 ms on this repo, and no file is read
    unless something changed.
    """

    SILENT = {"stdout": "", "exit_code": 0}
    RESIDUAL = 'F=.trinity/local.json; printf "%s" "$doc" > "$F"'

    def _project(self, tmp_path, monkeypatch):
        """A project root with a registry marker and two branches that each hold memory."""
        monkeypatch.setattr(edit_gate, "_TRIPWIRE_DIR", tmp_path)
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        seats = {}
        for name in ("hooks", "memory"):
            seat = tmp_path / "src" / "aipass" / name
            (seat / ".trinity").mkdir(parents=True)
            (seat / ".trinity" / "local.json").write_text(
                json.dumps({"sessions": [{"summary": "short"}]}), encoding="utf-8"
            )
            (seat / ".trinity" / "passport.json").write_text(json.dumps({"identity": {}}), encoding="utf-8")
            seats[name] = seat
        return seats

    def _around(self, seat, during, command=RESIDUAL):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(seat),
            "session_id": "session-wide",
            "tool_use_id": "toolu_wide",
        }
        with _imports_via_seam(_mock_importlib_modules(_TEST_LIMITS_ENFORCE)):
            edit_gate.tripwire_snapshot(data)
            during()
            return edit_gate.tripwire(data)

    @staticmethod
    def _context(result):
        assert result["exit_code"] == 0, "the tripwire never blocks: the command has already run"
        return json.loads(result["stdout"])["hookSpecificOutput"]["additionalContext"]

    def test_a_write_into_another_branchs_memory_is_reported(self, tmp_path, monkeypatch):
        seats = self._project(tmp_path, monkeypatch)
        target = seats["memory"] / ".trinity" / "local.json"

        def _write_next_door():
            target.write_text(json.dumps({"sessions": [{"summary": "s" * 300 + "tail"}]}), encoding="utf-8")

        context = self._context(self._around(seats["hooks"], _write_next_door))

        assert str(target) in context
        assert "sessions [0]: 304/300 chars (+4)" in context

    def test_a_passport_change_is_reported_and_measured_by_size(self, tmp_path, monkeypatch):
        """A passport is measured by its file budget (@memory 1.11.0), never by a field shape — @spawn owns that."""
        seats = self._project(tmp_path, monkeypatch)
        passport = seats["hooks"] / ".trinity" / "passport.json"

        clean = self._context(
            self._around(
                seats["hooks"], lambda: passport.write_text(json.dumps({"identity": {"role": "r"}}), encoding="utf-8")
            )
        )

        assert f"MEMORY CHANGED DURING THIS BASH CALL: {passport} changed" in clean
        assert "inside its file budget" in clean

    def test_an_over_budget_passport_is_named_with_its_numbers(self, tmp_path, monkeypatch):
        seats = self._project(tmp_path, monkeypatch)
        passport = seats["hooks"] / ".trinity" / "passport.json"
        fat = json.dumps({"identity": {"purpose": "p" * 7000}})

        context = self._context(self._around(seats["hooks"], lambda: passport.write_text(fat, encoding="utf-8")))

        assert "the whole file is" in context and "/6000 chars" in context
        assert "'identity.purpose' is 7000/600 chars (+6400 over)" in context

    def test_a_neighbours_change_is_a_question_not_an_accusation(self, tmp_path, monkeypatch):
        """Measured the first time this ran fleet-wide: a 76s pytest caught two live seats saving their own memory.

        Every citizen runs its own session, so a neighbour's write lands inside
        this call's window through no act of this command. The report stays —
        a cross-branch shell write is the shape the fence cannot always see —
        but it may not say "you wrote this" when the neighbour did.
        """
        seats = self._project(tmp_path, monkeypatch)
        target = seats["memory"] / ".trinity" / "local.json"

        context = self._context(
            self._around(seats["hooks"], lambda: target.write_text(json.dumps({"sessions": []}), encoding="utf-8"))
        )

        assert context.startswith("ANOTHER BRANCH'S MEMORY CHANGED")
        assert "MEMORY WRITTEN FROM A SHELL" not in context
        assert "If that seat is live right now" in context
        assert "memory owns that file" in context

    def test_the_seats_own_broken_file_is_still_named_as_this_calls_write(self, tmp_path, monkeypatch):
        seats = self._project(tmp_path, monkeypatch)
        mine = seats["hooks"] / ".trinity" / "local.json"
        over = json.dumps({"sessions": [{"summary": "s" * 300 + "tail"}]})

        context = self._context(self._around(seats["hooks"], lambda: mine.write_text(over, encoding="utf-8")))

        assert context.startswith("MEMORY WRITTEN FROM A SHELL")
        assert "Re-land each entry" in context

    def test_the_seats_own_clean_change_is_said_not_charged(self, tmp_path, monkeypatch, caplog):
        """Measured 2026-09-16: another seat's compaction ran @memory's rollover, which rewrote
        THIS seat's local.json mid-call. Clean, sanctioned, and not this command's write."""
        seats = self._project(tmp_path, monkeypatch)
        mine = seats["hooks"] / ".trinity" / "local.json"

        with caplog.at_level("INFO"):
            context = self._context(
                self._around(
                    seats["hooks"],
                    lambda: mine.write_text(json.dumps({"sessions": [{"summary": "new"}]}), encoding="utf-8"),
                )
            )

        assert context.startswith("MEMORY CHANGED DURING THIS BASH CALL")
        assert "MEMORY WRITTEN FROM A SHELL" not in context and "Re-land" not in context
        assert "It may not have been this command" in context
        tripwire_lines = [r for r in caplog.records if "edit_gate tripwire:" in r.getMessage()]
        assert tripwire_lines and all(r.levelname == "INFO" for r in tripwire_lines), "clean is not a defect"

    def test_an_untouched_project_stays_silent(self, tmp_path, monkeypatch):
        seats = self._project(tmp_path, monkeypatch)
        assert self._around(seats["hooks"], lambda: None) == self.SILENT

    def test_outside_a_project_only_the_seat_is_watched(self, tmp_path, monkeypatch):
        """No registry marker means no project boundary, and a fence that cannot find one never invents it."""
        monkeypatch.setattr(edit_gate, "_TRIPWIRE_DIR", tmp_path)
        docs = {}
        for name in ("loose", "neighbour"):
            (tmp_path / name / ".trinity").mkdir(parents=True)
            docs[name] = tmp_path / name / ".trinity" / "local.json"
            docs[name].write_text(json.dumps({"sessions": []}), encoding="utf-8")

        def write(name):
            return lambda: docs[name].write_text(json.dumps({"sessions": [{"summary": "new"}]}), encoding="utf-8")

        assert self._around(tmp_path / "loose", write("neighbour")) == self.SILENT
        result = self._around(tmp_path / "loose", write("loose"))
        assert result != self.SILENT, "a write into the seat's own memory went unreported"
        assert str(docs["loose"]) in self._context(result)

    def test_the_seat_and_its_neighbours_are_watched_from_any_seat(self, tmp_path, monkeypatch):
        """Read through tripwire's report, which lists changes sorted by path, so the watch list's
        own order (the seat first) shows in no public answer and is not pinned (fleet green leg 9)."""
        seats = self._project(tmp_path, monkeypatch)
        for name in ("memory", "hooks"):
            doc = seats[name] / ".trinity" / "local.json"

            def write(doc=doc):
                doc.write_text(json.dumps({"sessions": [{"summary": "new"}]}), encoding="utf-8")

            result = self._around(seats["memory"], write)
            assert result != self.SILENT, f"a write into {name}'s memory went unreported"
            assert str(doc) in self._context(result)
