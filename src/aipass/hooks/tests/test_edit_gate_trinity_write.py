# =================== AIPass ====================
# Name: test_edit_gate_trinity_write.py
# Description: edit_gate's .trinity caps on the Write lane: clean, over cap, the cut point, warn, fail-open, legacy
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/security/edit_gate.py: the .trinity character caps on Write."""

# The Edit lane is test_edit_gate_trinity_edit.py; the shell tripwire is
# test_edit_gate_trinity_tripwire.py; the advisories and budgets are
# test_edit_gate_trinity.py; the refusal wording is test_edit_gate_trinity_refusals.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that edit_gate.py parses and its imports resolve
# seedgo: no-test-needed(stdlib) — json.loads' parsing of the proposed content; the gate's reading of it is pinned

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

from aipass.hooks.apps.handlers.security.edit_gate import handle
from aipass.hooks.tests.support_edit_gate_trinity import (
    _TEST_LIMITS_DISABLED,
    _TEST_LIMITS_ENFORCE,
    _TEST_LIMITS_WARN,
    _fence_real,
    _hook_data,
    _imports_via_seam,
    _make_trinity_path,
    _mock_entry_limits,
)


class TestTrinityWriteClean:
    """Write to .trinity with entries under cap -> allowed."""

    def test_clean_write_local_json(self, tmp_path):
        """All entries under cap in local.json -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps(
            {
                "key_learnings": {"learn_1": "short"},
                "sessions": [{"summary": "short session"}],
                "todos": [{"task": "short todo"}],
            }
        )

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_clean_write_observations_json(self, tmp_path):
        """All entries under cap in observations.json -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "short observation"}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""


class TestTrinityWriteOverLimitEnforced:
    """Write with over-limit entry + enforce=True -> blocked."""

    def test_a_file_already_broken_on_disk_still_has_its_caps_checked(self, tmp_path):
        """Fleet green leg 5: an unparseable file on disk returned None (allow) before any cap was read, so the
        repairing Write carried whatever it held. The repair now passes the caps as if the file were new."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        Path(file_path).write_text("{not json", encoding="utf-8")
        content = json.dumps({"key_learnings": {"learn_1": "x" * 201}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=str(tmp_path / "src" / "aipass" / "hooks")))

        assert result["exit_code"] == 2
        assert "key_learnings" in json.loads(result["stdout"])["reason"]

    def test_a_file_the_gate_cannot_read_is_refused_not_allowed(self, tmp_path):
        """Fleet green leg 5: the catch-all around the caps check allowed the write when the current file could
        not be read (mode 0o200: writable, not readable). Where the platform still reads it (Windows, root), the
        cap refuses instead: the test opens the file with its own hands and asserts the refusal either way."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        Path(file_path).write_text("{}", encoding="utf-8")
        content = json.dumps({"key_learnings": {"learn_1": "x" * 201}})
        Path(file_path).chmod(0o200)
        try:
            try:
                Path(file_path).read_text(encoding="utf-8")
                unreadable = False
            except OSError as exc:
                logging.getLogger(__name__).info("the platform refuses the read, as the gate will see: %s", exc)
                unreadable = True
            with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
                result = handle(_hook_data(file_path, content, cwd=str(tmp_path / "src" / "aipass" / "hooks")))
        finally:
            Path(file_path).chmod(0o600)

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert ("could not be checked" in reason) if unreadable else ("key_learnings" in reason)

    def test_block_over_limit_key_learning(self, tmp_path):
        """key_learning value 201 chars vs 200 cap -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"learn_1": "x" * 201}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "key_learnings" in parsed["reason"]
        assert "201" in parsed["reason"]
        assert "200" in parsed["reason"]

    def test_block_over_limit_session_summary(self, tmp_path):
        """Session summary 301 chars vs 300 cap -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "x" * 301}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "sessions" in parsed["reason"]

    def test_block_over_limit_todo(self, tmp_path):
        """Todo task 201 chars vs 200 cap -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"todos": [{"task": "x" * 201}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "todos" in parsed["reason"]

    def test_block_over_limit_observation(self, tmp_path):
        """Observation note 601 chars vs 600 cap -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "observations.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"observations": [{"note": "x" * 601}]})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "observations" in parsed["reason"]

    def test_block_reason_includes_over_by(self, tmp_path):
        """Block reason includes the +over_by amount."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 210}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        parsed = json.loads(result["stdout"])
        assert "+10" in parsed["reason"]


class TestRejectionNamesTheCutPoint:
    """DPLAN-0342 row 1: the refusal shows WHERE the cap cut, not only by how much.

    Fleet measurement (@devpulse, 2280 .trinity edits): the median overage is 7%
    of the cap and 88% sit under 20% — agents aim at the line and land a few words
    past it. "336/300 (+36)" makes the rewrite a re-guess of the whole entry; the
    kept prefix and the overflow after a bar make it a trim of a visible tail. The
    block itself does not change, and nothing is ever truncated.
    """

    def _reason(self, tmp_path, content: dict) -> str:
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, json.dumps(content), cwd=cwd))
        assert result["exit_code"] == 2, "the block itself must not change"
        return json.loads(result["stdout"])["reason"]

    def test_a_list_entry_shows_the_kept_prefix_and_the_overflow(self, tmp_path):
        reason = self._reason(tmp_path, {"sessions": [{"summary": "k" * 300 + " and past the line"}]})
        assert "sessions [0]: 318/300 chars (+18)" in reason
        assert f'kept: "{"k" * 300}" | over: " and past the line"' in reason

    def test_the_cut_sits_on_the_line_after_its_measurement(self, tmp_path):
        lines = self._reason(tmp_path, {"sessions": [{"summary": "k" * 300 + "TAIL"}]}).splitlines()
        index = next(i for i, line in enumerate(lines) if "304/300" in line)
        assert lines[index + 1].lstrip().startswith('kept: "')
        assert lines[index + 1].endswith('| over: "TAIL"')

    def test_a_dict_entry_resolves_by_its_key(self, tmp_path):
        assert '| over: "yz"' in self._reason(tmp_path, {"key_learnings": {"k1": "x" * 200 + "yz"}})

    def test_the_boundary_is_visible_when_it_is_whitespace_or_a_quote(self, tmp_path):
        """JSON-quoted halves: a trailing space or a newline at the cut cannot hide."""
        reason = self._reason(tmp_path, {"sessions": [{"summary": "a" * 299 + ' \n"q'}]})
        assert f'kept: "{"a" * 299} "' in reason
        assert 'over: "\\n\\"q"' in reason

    def test_the_cut_counts_code_points_like_the_cap_does(self, tmp_path):
        """len() is the unit the cap is measured in, so an accented letter is one."""
        reason = self._reason(tmp_path, {"sessions": [{"summary": "é" * 300 + "Z"}]})
        assert "301/300 chars (+1)" in reason
        assert f'kept: "{"é" * 300}" | over: "Z"' in reason

    def test_a_record_that_disagrees_with_the_document_draws_no_cut(self, tmp_path):
        """A cut on text the record did not measure would point at the wrong characters."""
        el = _mock_entry_limits(_TEST_LIMITS_ENFORCE)
        record = {
            "entry_type": "sessions",
            "container": "sessions",
            "key": "0",
            "length": 999,
            "cap": 300,
            "over_by": 699,
        }
        el.configure_mock(changed_entries=MagicMock(return_value=[record]))
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"sessions": [{"summary": "k" * 310}]})
        with _imports_via_seam(_fence_real(el)):
            result = handle(_hook_data(file_path, content, cwd=cwd))
        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "999/300 chars (+699)" in reason
        assert "kept:" not in reason

    def test_warn_mode_logs_the_same_cut(self, tmp_path, caplog):
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 200 + "past"}})
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))
        assert result["exit_code"] == 0
        assert '| over: "past"' in caplog.text
        assert "warn only" in caplog.text

    def test_the_advisory_says_a_shell_write_is_refused_now(self, tmp_path):
        """DPLAN-0342 row 3: the line that said a Bash write was "not measured" was true, and not enough."""
        reason = self._reason(tmp_path, {"sessions": [{"summary": "k" * 301}]})
        assert "a write to a memory file made through Bash is refused" in reason
        assert "not measured" not in reason
        # The lane the cap does cover is named too (moved here from test_edit_gate's
        # private _evaluate_limits pins, fleet green leg 8), beside the entry it refused.
        assert "Caps are measured on Edit/Write" in reason
        assert "sessions [0]: 301/300 chars (+1)" in reason


class TestTrinityWriteOverLimitWarnOnly:
    """Write with over-limit entry + enforce=False -> allowed + warning logged."""

    def test_allow_over_limit_warn_only(self, tmp_path):
        """Over-limit with enforce=False -> exit_code 0, empty stdout."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"learn_1": "x" * 250}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert result["stdout"] == ""

    def test_warn_logs_over_limit_entries(self, tmp_path, caplog):
        """Over-limit with enforce=False -> warning logged with warn-only message."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 250}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0
        assert "warn only" in caplog.text


class TestTrinityWriteNonTrinity:
    """Write to non-.trinity file -> passes through unchanged."""

    def test_non_trinity_py_passthrough(self, tmp_path):
        """Write to a .py file -> no .trinity check, passes to diagnostics gate."""
        seat = tmp_path / "src" / "aipass" / "hooks"
        result = handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(seat / "apps" / "test.py"), "content": "print('hello')"},
                "cwd": str(seat),
            }
        )
        assert result["exit_code"] == 0

    def test_non_trinity_json_passthrough(self, tmp_path):
        """Write to a non-.trinity .json file -> allowed."""
        seat = tmp_path / "src" / "aipass" / "hooks"
        result = handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(seat / "apps" / "config.json"), "content": '{"key": "value"}'},
                "cwd": str(seat),
            }
        )
        assert result["exit_code"] == 0

    def test_trinity_passport_passthrough(self, tmp_path):
        """passport.json is in .trinity but NOT in _TRINITY_MEMORY_FILES."""
        trinity_dir = tmp_path / "src" / "aipass" / "hooks" / ".trinity"
        trinity_dir.mkdir(parents=True, exist_ok=True)
        file_path = str(trinity_dir / "passport.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        result = handle(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": file_path, "content": '{"identity": {}}'},
                "cwd": cwd,
            }
        )
        assert result["exit_code"] == 0


class TestTrinityWriteFailOpen:
    """A write whose RESULT does not parse is refused; a gate that cannot run still allows.

    Until 2026-09-16 unparseable content fell into the catch-all and was allowed.
    Measured then (FPLAN-0593 Phase 5, row 4): every fleet writer is atomic, so a
    memory file that does not parse is a complete file an edit broke — two in the
    retained logs, each on disk 8-9 seconds, one reported by another seat's
    tripwire as a defect. The import failure below stays fail-open: that is the
    gate unable to run, not the file being broken.
    """

    def test_invalid_json_content(self, tmp_path):
        """Non-JSON content is refused with the parse error, before any cap is measured."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, "not valid json {{{", cwd=cwd))

        assert result["exit_code"] == 2
        reason = json.loads(result["stdout"])["reason"]
        assert "local.json: this edit would leave the file unparseable as JSON" in reason

    def test_empty_content(self, tmp_path):
        """An empty Write would blank the seat's memory: refused like any other unparseable result."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, "", cwd=cwd))

        assert result["exit_code"] == 2

    def test_import_failure_fails_closed(self, tmp_path):
        """importlib.import_module raises ImportError -> the write is refused (DPLAN-0356 item 2; was fail-open)."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 500}})

        with _imports_via_seam(ImportError("no module")):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        assert "edit_gate could not check this call" in json.loads(result["stdout"])["reason"]


class TestTrinityWriteCharNotByte:
    """Character vs byte boundary: em-dash is 3 bytes / 1 char."""

    def test_em_dash_at_cap_allowed(self, tmp_path):
        """200 em-dashes = 200 chars (600 bytes) = exactly at cap -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "—" * 200}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0

    def test_em_dash_over_cap_blocked(self, tmp_path):
        """201 em-dashes = 201 chars (603 bytes) = over cap -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "—" * 201}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"


class TestTrinityWriteDisabled:
    """Feature disabled via enabled:false -> passthrough."""

    def test_disabled_allows_over_limit(self, tmp_path):
        """enabled=False -> size check skipped, over-limit entry allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        content = json.dumps({"key_learnings": {"k1": "x" * 500}})

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_DISABLED))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0


class TestTrinityWriteUnchangedLegacy:
    """REVERSED BACK (2026-08-30): rollover-safety is universal, not todos-only.

    This is the exact shape that broke @memory's lane in production: the
    extractor removed a tail, wrote the SMALLER document back, and the write was
    refused over an entry in the head it never touched — failing identically
    every 20 minutes for three hours. The archiver is always on the losing side
    of that trade. Carrying an over-cap entry forward while adding a clean one
    is a write that authored nothing over cap, and it is allowed.
    """

    def test_unchanged_over_limit_is_allowed(self, tmp_path):
        """Over-limit entry identical in before/after -> carried, allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        existing = {"key_learnings": {"old_fat": "x" * 500}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"key_learnings": {"old_fat": "x" * 500, "new_clean": "short"}}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 0, "a rollover-shaped write was refused for what it carried"

    def test_changed_legacy_blocked(self, tmp_path):
        """Legacy entry modified (text changed, still over-limit) -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        existing = {"key_learnings": {"old_fat": "x" * 500}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        after = {"key_learnings": {"old_fat": "y" * 500}}
        content = json.dumps(after)

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(_hook_data(file_path, content, cwd=cwd))

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
