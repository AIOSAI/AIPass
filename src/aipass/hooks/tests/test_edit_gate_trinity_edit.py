# =================== AIPass ====================
# Name: test_edit_gate_trinity_edit.py
# Description: edit_gate's .trinity caps on the Edit lane: Edit, replace_all, MultiEdit, carried vs authored entries
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/security/edit_gate.py: the .trinity character caps on Edit and MultiEdit."""

# The Write lane is test_edit_gate_trinity_write.py; the shell tripwire is
# test_edit_gate_trinity_tripwire.py; the advisories are test_edit_gate_trinity.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that edit_gate.py parses and its imports resolve
# seedgo: no-test-needed(stdlib) — json.loads' parsing of the proposed content; the gate's reading of it is pinned

import json
from pathlib import Path

from aipass.hooks.apps.handlers.security.edit_gate import handle
from aipass.hooks.tests.support_edit_gate_trinity import (
    _TEST_LIMITS_ENFORCE,
    _TEST_LIMITS_WARN,
    _fence_real,
    _hook_data,
    _imports_via_seam,
    _make_trinity_path,
    _mock_entry_limits,
)


class TestTrinityEditClean:
    """Edit to .trinity with entries under cap -> allowed."""

    def test_edit_clean_entry(self, tmp_path):
        """Edit changes a key_learning to a short value -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "old value"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"old value"',
                    new_string='"new short value"',
                )
            )

        assert result["exit_code"] == 0
        assert result["stdout"] == ""


class TestTrinityEditOverLimit:
    """Edit producing over-limit entry -> blocked (enforce) or warned."""

    def test_edit_over_limit_enforce_blocks(self, tmp_path):
        """Edit pushes key_learning over 200 cap, enforce=True -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "x" * 250 + '"',
                )
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"
        assert "key_learnings" in parsed["reason"]

    def test_edit_over_limit_warn_allows(self, tmp_path, caplog):
        """Edit pushes key_learning over cap, enforce=False -> allowed + warn."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_WARN))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "x" * 250 + '"',
                )
            )

        assert result["exit_code"] == 0
        assert "warn only" in caplog.text

    def test_edit_modifies_entry_to_exceed_cap(self, tmp_path):
        """Edit modifies existing entry from under cap to over cap -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "a" * 100}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"' + "a" * 100 + '"',
                    new_string='"' + "b" * 250 + '"',
                )
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"


class TestTrinityEditFailOpen:
    """Edit fail-open: old_string not found, invalid JSON result."""

    def test_edit_old_string_not_found_fail_open(self, tmp_path):
        """old_string absent from file -> _resolve_after_text returns None -> allow."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "hello"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string="NONEXISTENT",
                    new_string="x" * 500,
                )
            )

        assert result["exit_code"] == 0

    def test_edit_producing_invalid_json_is_refused(self, tmp_path):
        """Edit breaks JSON structure -> refused, the file on disk stays whole."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "hello"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"hello"',
                    new_string='"hello',
                )
            )

        assert result["exit_code"] == 2
        assert "unparseable as JSON" in json.loads(result["stdout"])["reason"]

    def test_an_edit_that_repairs_an_already_broken_file_is_allowed(self, tmp_path):
        """The measured 18:40 shape, second half: the next Edit is the fix, and it must land."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        Path(file_path).write_text('{"key_learnings": {"k1": "hello}}', encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(file_path, tool_name="Edit", cwd=cwd, old_string='"hello}}', new_string='"hello"}}')
            )

        assert result["exit_code"] == 0

    def test_edit_nonexistent_file_allows(self, tmp_path):
        """Edit to a .trinity file that doesn't exist yet -> allow."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string="anything",
                    new_string="x" * 500,
                )
            )

        assert result["exit_code"] == 0


class TestTrinityEditReplaceAll:
    """Edit with replace_all=True vs False."""

    def test_replace_all_true(self, tmp_path):
        """replace_all=True replaces all occurrences -> checks result."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "aaa"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"aaa"',
                    new_string='"' + "x" * 250 + '"',
                    replace_all=True,
                )
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_replace_all_false_single(self, tmp_path):
        """replace_all=False replaces first occurrence only -> one entry over."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "bbb"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"aaa"',
                    new_string='"' + "x" * 250 + '"',
                    replace_all=False,
                )
            )

        assert result["exit_code"] == 2


class TestTrinityEditCharNotByte:
    """Character vs byte boundary via Edit tool."""

    def test_em_dash_edit_at_cap_allowed(self, tmp_path):
        """Edit producing 200 em-dashes (200 chars, 600 bytes) -> at cap -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "—" * 200 + '"',
                )
            )

        assert result["exit_code"] == 0

    def test_em_dash_edit_over_cap_blocked(self, tmp_path):
        """Edit producing 201 em-dashes (201 chars, 603 bytes) -> over cap -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "short"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"' + "—" * 201 + '"',
                )
            )

        assert result["exit_code"] == 2


class TestTrinityMultiEdit:
    """MultiEdit: sequential edits, ordering, over-limit detection."""

    def test_multiedit_clean(self, tmp_path):
        """MultiEdit with both edits under cap -> allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "bbb"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"aaa"', "new_string": '"new_a"'},
            {"old_string": '"bbb"', "new_string": '"new_b"'},
        ]
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 0

    def test_multiedit_over_limit_blocked(self, tmp_path):
        """MultiEdit where second edit produces over-limit entry -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "aaa", "k2": "bbb"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"aaa"', "new_string": '"short"'},
            {"old_string": '"bbb"', "new_string": '"' + "x" * 250 + '"'},
        ]
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 2
        parsed = json.loads(result["stdout"])
        assert parsed["decision"] == "block"

    def test_multiedit_ordering_dependent(self, tmp_path):
        """MultiEdit where edit 2 depends on edit 1's output -> applied sequentially."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "alpha"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"alpha"', "new_string": '"beta"'},
            {"old_string": '"beta"', "new_string": '"gamma"'},
        ]
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 0

    def test_multiedit_old_string_not_found_fail_open(self, tmp_path):
        """MultiEdit where an old_string is missing -> fail-open."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "hello"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"hello"', "new_string": '"world"'},
            {"old_string": '"NONEXISTENT"', "new_string": '"' + "x" * 500 + '"'},
        ]
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 0

    def test_multiedit_replace_all_in_edit(self, tmp_path):
        """MultiEdit with replace_all=True in one edit -> replaces all occurrences."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {"key_learnings": {"k1": "zzz", "k2": "zzz"}}
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        edits = [
            {"old_string": '"zzz"', "new_string": '"' + "x" * 250 + '"', "replace_all": True},
        ]
        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {"file_path": file_path, "edits": edits},
                    "cwd": cwd,
                }
            )

        assert result["exit_code"] == 2


class TestTrinityEditUnrelatedFieldOnFatFile:
    """REVERSED TWICE, and the second reversal restores the original answer.

    Written as "THE critical no-false-reject test", flipped to expect a block on
    2026-08-27 when the fleet had converged, flipped back on 2026-08-30. The
    round trip is the lesson, not an embarrassment: the 08-27 premise was that
    drift had been cured fleet-wide, and a clause justified by a temporary state
    has to be re-read when that state ends. @memory measured that it had ended —
    drift RECURS (@ai_mail carried three over-cap learnings the same evening,
    @seedgo one) — and that refusing carried debt deadlocks the archiver:
    a file cannot get smaller because it is too big.

    So the rule is @memory's entry_limits 1.6.0 rule, and this gate now keeps
    the same one: a write is refused for what it AUTHORS, never for what it
    CARRIES. Blocking an unrelated edit over a fat entry the agent did not write
    was never a standard worth having — it is unsatisfiable by any allowed
    action, which is the species this branch has now fixed three times.
    """

    def test_unrelated_edit_on_fat_file_is_allowed(self, tmp_path):
        """Fat legacy sessions + key_learnings, edit touches only a todo -> ALLOWED."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        fat_sessions = [{"summary": "x" * 300} for _ in range(13)]
        fat_learnings = {f"k{i}": "y" * 500 for i in range(10)}
        existing = {
            "key_learnings": fat_learnings,
            "sessions": fat_sessions,
            "todos": [{"task": "old todo"}],
        }
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"old todo"',
                    new_string='"new todo"',
                )
            )

        assert result["exit_code"] == 0, "an unrelated edit was refused for entries this write did not author"
        assert result["stdout"] == "", "an allowed write must not print a refusal"

    def test_unrelated_edit_plus_new_over_limit_blocked(self, tmp_path):
        """Fat file, but Edit ALSO adds a new over-limit entry -> blocked."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")

        existing = {
            "key_learnings": {"old_fat": "y" * 500},
            "todos": [{"task": "old todo"}],
        }
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"old todo"',
                    new_string='"' + "z" * 250 + '"',
                )
            )

        assert result["exit_code"] == 2


class TestTrinityEditUnchangedLegacy:
    """REVERSED BACK (2026-08-30): an untouched over-limit entry is carried, not refused.

    "Unchanged" does not mean "legacy" and it does not mean "written and not yet
    caught" either — it means THIS WRITE DID NOT AUTHOR IT, which is the only
    thing a write gate can honestly judge. Detection of drift already on disk
    belongs to drone @memory lint, which reads whole files; a PreToolUse gate
    sees only the next write and is structurally blind to drift that arrived
    through Bash — as this gate's own refusal text says out loud.
    """

    def test_edit_unchanged_over_limit_is_allowed(self, tmp_path):
        """Over-limit key_learning untouched by the Edit -> carried, allowed."""
        file_path = _make_trinity_path(tmp_path, "hooks", "local.json")
        cwd = str(tmp_path / "src" / "aipass" / "hooks")
        existing = {
            "key_learnings": {"old_fat": "x" * 500, "k2": "short"},
            "todos": [{"task": "my todo"}],
        }
        Path(file_path).write_text(json.dumps(existing), encoding="utf-8")

        with _imports_via_seam(_fence_real(_mock_entry_limits(_TEST_LIMITS_ENFORCE))):
            result = handle(
                _hook_data(
                    file_path,
                    tool_name="Edit",
                    cwd=cwd,
                    old_string='"short"',
                    new_string='"still short"',
                )
            )

        assert result["exit_code"] == 0, "a write was refused for an entry it did not author"
