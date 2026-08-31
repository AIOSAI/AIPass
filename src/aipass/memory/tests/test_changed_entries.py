# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_changed_entries.py
# Date: 2026-06-13
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Tests for Phase 3 of FPLAN-0270: changed_entries diff helper and
write_memory_file entry-limits wiring.

Covers:
  - changed_entries: new over-limit, changed over-limit, unchanged legacy
    fat entries (rollover-safe), shrinking, dict/list containers, empty before.
  - write_memory_file wiring: warn mode writes through + logs, enforce mode
    rejects new fat entries, enforce mode allows unchanged legacy fat entries,
    non-trinity files unaffected, passport.json unaffected.
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Per-test fixture: fresh-import modules with mocks in place
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_modules(monkeypatch):
    """Drop cached modules so each test gets fresh imports.

    Evicted with ``monkeypatch.delitem``, not a bare ``sys.modules.pop``: a
    bare pop is one-way and the eviction outlives the test, which is how two
    receipt tests went red on a single xdist worker on a single run.
    """
    for name in (
        "aipass.memory.apps.handlers.json",
        "aipass.memory.apps.handlers.json.json_handler",
        "aipass.memory.apps.handlers.json.entry_limits",
        "aipass.memory.apps.handlers.json.memory_files",
        "aipass.memory.apps.handlers.json.lint_handler",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield


def _get_entry_limits():
    """Import and return the entry_limits module."""
    return importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")


def _get_memory_files():
    """Import and return the memory_files module."""
    return importlib.import_module("aipass.memory.apps.handlers.json.memory_files")


# ---------------------------------------------------------------------------
# Helpers: build limits dicts for testing
# ---------------------------------------------------------------------------

_KEY_LEARNINGS_ONLY: dict[str, Any] = {
    "enabled": True,
    "enforce": False,
    "entry_types": {
        "key_learnings": {
            "file": "local.json",
            "container": "key_learnings",
            "kind": "dict",
            "field": "value",
            "max_chars": 200,
        },
    },
}

_SESSIONS_ONLY: dict[str, Any] = {
    "enabled": True,
    "enforce": False,
    "entry_types": {
        "sessions": {
            "file": "local.json",
            "container": "sessions",
            "kind": "list",
            "field": "summary",
            "max_chars": 300,
        },
    },
}


def _full_limits(**overrides: Any) -> dict[str, Any]:
    """Return a complete limits dict with all four default entry types."""
    base: dict[str, Any] = {
        "enabled": True,
        "enforce": False,
        "entry_types": {
            "key_learnings": {
                "file": "local.json",
                "container": "key_learnings",
                "kind": "dict",
                "field": "value",
                "max_chars": 200,
            },
            "sessions": {
                "file": "local.json",
                "container": "sessions",
                "kind": "list",
                "field": "summary",
                "max_chars": 300,
            },
            "todos": {
                "file": "local.json",
                "container": "todos",
                "kind": "list",
                "field": "task",
                "max_chars": 200,
            },
            "observations": {
                "file": "observations.json",
                "container": "observations",
                "kind": "list",
                "field": "note",
                "max_chars": 600,
            },
        },
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. changed_entries: new over-limit entry detected
# ===========================================================================


class TestNewOverLimitEntry:
    """A new dict entry that exceeds the cap is returned as a violation."""

    def test_new_overlimit_key_learning(self) -> None:
        mod = _get_entry_limits()
        before = {"key_learnings": {"a": "short", "b": "also short"}}
        fat_text = "x" * 250
        after = {"key_learnings": {"a": "short", "b": "also short", "c": fat_text}}

        result = mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY)

        assert len(result) == 1
        assert result[0]["entry_type"] == "key_learnings"
        assert result[0]["key"] == "c"
        assert result[0]["length"] == 250
        assert result[0]["cap"] == 200
        assert result[0]["over_by"] == 50


# ===========================================================================
# 2. changed_entries: changed entry exceeds cap
# ===========================================================================


class TestChangedEntryOverCap:
    """An existing entry whose text grew past the cap is flagged."""

    def test_changed_key_learning_over_cap(self) -> None:
        mod = _get_entry_limits()
        before = {"key_learnings": {"a": "short text"}}
        after = {"key_learnings": {"a": "y" * 300}}

        result = mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY)

        assert len(result) == 1
        assert result[0]["key"] == "a"
        assert result[0]["over_by"] == 100


# ===========================================================================
# 3. changed_entries: UNCHANGED legacy over-limit entry NOT returned
# ===========================================================================


class TestUnchangedLegacyFatEntry:
    """THE KEY TEST, and it has been rewritten twice.

    2026-08-27 narrowed "unchanged and over cap passes" to `todos`, on the
    reasoning that the trinity push had cured drift fleet-wide and the clause
    now hid new drift instead of protecting old.

    2026-08-30 reversed it: drift recurs, and this gate never sees the writes
    that cause it (Bash lanes bypass @hooks entirely). Refusing the next write
    deadlocked rollover — the one lane whose write is always a shrink. The
    entry is now CARRIED: not refused, and no longer silent either.
    """

    def test_unchanged_500char_key_learning_is_carried_not_flagged(self) -> None:
        mod = _get_entry_limits()
        fat_text = "z" * 500
        before = {"key_learnings": {"legacy": fat_text}}
        after = {"key_learnings": {"legacy": fat_text}}

        assert mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY) == []

        carried = mod.classify_entries(before, after, _KEY_LEARNINGS_ONLY)["carried"]
        assert len(carried) == 1
        assert carried[0]["entry_type"] == "key_learnings"


class TestReshapeOnlyKeepsTheExemption:
    """`todos` is the one container where legacy drift legitimately persists.

    The trinity push is forbidden to archive open work (1.1.0), so nothing but
    the branch's own agent can ever cure a drifted todo. Refusing every write
    to that file would brick its rollover — the debt preserved by destroying
    the lane that preserves everything else.
    """

    _TODOS_ONLY = {
        "enabled": True,
        "enforce": True,
        "entry_types": {"todos": {"container": "todos", "field": "task", "max_chars": 150, "kind": "list"}},
    }

    def test_an_unchanged_over_cap_todo_is_not_flagged(self) -> None:
        mod = _get_entry_limits()
        fat = {"number": 1, "date": "2026-08-27", "task": "z" * 500, "priority": "high", "status": "open"}

        result = mod.changed_entries({"todos": [fat]}, {"todos": [dict(fat)]}, self._TODOS_ONLY)

        assert result == []

    def test_a_new_over_cap_todo_is_still_flagged(self) -> None:
        mod = _get_entry_limits()
        fresh = {"number": 2, "date": "2026-08-27", "task": "y" * 500, "priority": "high", "status": "open"}

        result = mod.changed_entries({"todos": []}, {"todos": [fresh]}, self._TODOS_ONLY)

        assert len(result) == 1
        assert result[0]["entry_type"] == "todos"

    _TODOS_AS_DICT = {
        "enabled": True,
        "enforce": True,
        "entry_types": {"todos": {"container": "todos", "field": "task", "max_chars": 150, "kind": "dict"}},
    }

    def test_editing_a_drifted_todo_into_another_drifted_shape_is_caught(self) -> None:
        """@hooks' M5, and it SURVIVED my set until they named it (2026-08-27).

        The exemption is for the entry that is ALREADY ON DISK — not for "the
        canonical field is missing on both sides". Both values here are
        unmeasurable (a list where a string belongs) and they are DIFFERENT
        values under the same key, so this write really did change the entry
        and must be reported. Keying identity on the field name instead of the
        raw value reads the second as untouched and exempts a drift this write
        introduced: one drifted todo would license every future edit of it.

        A NEW key never reaches this comparison at all (`key_known` is False
        and the entry is checked outright), which is why the obvious two-key
        version of this test does NOT bite the mutant — the surviving line is
        only reachable when the key exists and the value moved.

        HONEST ABOUT THE COVERAGE: this exercises the DICT container path,
        which no shipped entry type reaches — all four are `kind: list` since
        the grandfather clause narrowed to todos, so `_is_unchanged`'s exempt
        branch is currently unreachable in production. That is the other half
        of why the mutation survived. Pinned at the contract rather than end
        to end, because the branch is one config edit from live and a dead
        branch that is also unpinned comes back wrong.
        """
        mod = _get_entry_limits()
        on_disk = {"todos": {"a": {"task": ["chunk one", "chunk two"]}}}
        written = {"todos": {"a": {"task": ["a completely different malformed todo"]}}}

        result = mod.changed_entries(on_disk, written, self._TODOS_AS_DICT)

        assert [hit["key"] for hit in result] == ["a"], "a drifted todo exempted a different value under its own key"

    def test_the_same_drifted_todo_is_still_exempt_in_the_dict_path(self) -> None:
        """The other half of the contract: identical raw value, still skipped."""
        mod = _get_entry_limits()
        on_disk = {"todos": {"a": {"task": ["chunk one", "chunk two"]}}}
        rewritten = {"todos": {"a": {"task": ["chunk one", "chunk two"]}}}

        result = mod.changed_entries(on_disk, rewritten, self._TODOS_AS_DICT)

        assert result == []


# ===========================================================================
# 4. changed_entries: shrinking an entry is not flagged
# ===========================================================================


class TestShrinkingEntry:
    """An entry that went from 500 chars to 100 is not flagged."""

    def test_shrunk_entry_not_flagged(self) -> None:
        mod = _get_entry_limits()
        before = {"key_learnings": {"item": "z" * 500}}
        after = {"key_learnings": {"item": "z" * 100}}

        result = mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY)

        assert result == []


# ===========================================================================
# 5. changed_entries: dict container — value-as-string and value-as-dict
# ===========================================================================


class TestDictContainerShapes:
    """Both plain-string and dict-with-field value shapes are handled."""

    def test_value_as_string(self) -> None:
        mod = _get_entry_limits()
        before: dict[str, Any] = {"key_learnings": {}}
        after = {"key_learnings": {"new_key": "x" * 250}}

        result = mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY)

        assert len(result) == 1
        assert result[0]["length"] == 250

    def test_value_as_dict_with_field(self) -> None:
        mod = _get_entry_limits()
        before: dict[str, Any] = {"key_learnings": {}}
        after = {"key_learnings": {"new_key": {"value": "x" * 250, "source": "test"}}}

        result = mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY)

        assert len(result) == 1
        assert result[0]["length"] == 250


# ===========================================================================
# 6. changed_entries: list container — appended and unchanged
# ===========================================================================


class TestListContainer:
    """List containers detect new appended items and skip unchanged ones."""

    def test_appended_item_over_cap_detected(self) -> None:
        mod = _get_entry_limits()
        existing = {"session_number": 1, "summary": "short"}
        new_fat = {"session_number": 2, "summary": "s" * 400}
        before = {"sessions": [existing]}
        after = {"sessions": [existing, new_fat]}

        result = mod.changed_entries(before, after, _SESSIONS_ONLY)

        assert len(result) == 1
        assert result[0]["key"] == "1"
        assert result[0]["over_by"] == 100

    def test_existing_unchanged_items_are_carried_not_flagged(self) -> None:
        """Reversed 2026-08-30: unchanged means "this write did not author it"."""
        mod = _get_entry_limits()
        fat_item = {"session_number": 1, "summary": "s" * 400}
        before = {"sessions": [fat_item]}
        after = {"sessions": [fat_item]}

        assert mod.changed_entries(before, after, _SESSIONS_ONLY) == []
        assert len(mod.classify_entries(before, after, _SESSIONS_ONLY)["carried"]) == 1


# ===========================================================================
# 7. changed_entries: list prepend identity-match (Fix 1 — FPLAN-0276 cleanup)
# ===========================================================================


class TestListPrependIdentityMatch:
    """Prepending a new entry must NOT re-flag shifted legacy over-cap entries."""

    def test_prepend_carries_the_legacy_entries_it_shifted_past(self) -> None:
        """The prepend is clean, and the five it shifted past are not its doing.

        Identity is the TEXT, never the index — the whole point. A prepend
        moves every legacy entry one slot down; an index-keyed diff would call
        all five newly authored and refuse a write that authored one short
        entry. They are reported as carried debt instead, and the new entry is
        not among them because it is within cap.
        """
        mod = _get_entry_limits()
        legacy = [{"session_number": i, "summary": "s" * 400} for i in range(5, 0, -1)]
        before = {"sessions": legacy}
        new_entry = {"session_number": 6, "summary": "short new"}
        after = {"sessions": [new_entry] + legacy}

        assert mod.changed_entries(before, after, _SESSIONS_ONLY) == []

        carried = mod.classify_entries(before, after, _SESSIONS_ONLY)["carried"]
        assert len(carried) == 5
        assert all(hit["entry_type"] == "sessions" for hit in carried)
        assert "0" not in {hit["key"] for hit in carried}

    def test_edited_existing_entry_text_still_caught(self) -> None:
        """Changing an existing entry's text to over-cap is still flagged."""
        mod = _get_entry_limits()
        before = {"sessions": [{"session_number": 1, "summary": "short"}]}
        after = {"sessions": [{"session_number": 1, "summary": "s" * 400}]}

        result = mod.changed_entries(before, after, _SESSIONS_ONLY)

        assert len(result) == 1
        assert result[0]["over_by"] == 100

    def test_genuinely_new_overcap_entry_still_caught(self) -> None:
        """A brand-new over-cap entry is still flagged even alongside legacy."""
        mod = _get_entry_limits()
        legacy = [{"session_number": 1, "summary": "ok"}]
        before = {"sessions": legacy}
        new_fat = {"session_number": 2, "summary": "s" * 400}
        after = {"sessions": [new_fat] + legacy}

        result = mod.changed_entries(before, after, _SESSIONS_ONLY)

        assert len(result) == 1
        assert result[0]["over_by"] == 100


# ===========================================================================
# 8. changed_entries: empty before (new file) — all entries treated as new
# ===========================================================================


class TestEmptyBefore:
    """When before is empty, all after entries are treated as new."""

    def test_all_over_limit_entries_flagged(self) -> None:
        mod = _get_entry_limits()
        before: dict[str, Any] = {}
        after = {"key_learnings": {"a": "x" * 250, "b": "ok"}}

        result = mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY)

        assert len(result) == 1
        assert result[0]["key"] == "a"

    def test_within_limit_entries_not_flagged(self) -> None:
        mod = _get_entry_limits()
        before: dict[str, Any] = {}
        after = {"key_learnings": {"a": "short", "b": "also short"}}

        result = mod.changed_entries(before, after, _KEY_LEARNINGS_ONLY)

        assert result == []


# ===========================================================================
# 8. write_memory_file: warn mode writes through + logs warning
# ===========================================================================


class TestWarnModeWritesThrough:
    """In warn mode (enforce=False), over-limit entries log a warning but file is written."""

    def test_warn_mode_writes_and_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mem_mod = _get_memory_files()
        mock_logger = mem_mod.logger

        # Build .trinity/local.json path
        trinity = tmp_path / "test_branch" / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"

        before_data = {"key_learnings": {"existing": "short"}}
        local_path.write_text(json.dumps(before_data, indent=2), encoding="utf-8")

        fat_text = "x" * 300
        after_data = {"key_learnings": {"existing": "short", "new_fat": fat_text}}

        warn_limits = _full_limits(enforce=False)
        monkeypatch.setattr(mem_mod, "load_entry_limits", lambda branch: warn_limits)

        result = mem_mod.write_memory_file(local_path, after_data)

        assert result["success"] is True
        written = json.loads(local_path.read_text(encoding="utf-8"))
        assert written["key_learnings"]["new_fat"] == fat_text
        mock_logger.warning.assert_called()
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("entry_limits" in w for w in warning_calls)


# ===========================================================================
# 9. write_memory_file: enforce mode rejects new over-limit entry
# ===========================================================================


class TestEnforceModeRejects:
    """In enforce mode, a new over-limit entry is rejected and file is unchanged."""

    def test_enforce_rejects_new_fat_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mem_mod = _get_memory_files()

        trinity = tmp_path / "test_branch" / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"

        before_data = {"key_learnings": {"existing": "short"}}
        local_path.write_text(json.dumps(before_data, indent=2), encoding="utf-8")

        fat_text = "x" * 300
        after_data = {"key_learnings": {"existing": "short", "new_fat": fat_text}}

        enforce_limits = _full_limits(enforce=True)
        monkeypatch.setattr(mem_mod, "load_entry_limits", lambda branch: enforce_limits)

        result = mem_mod.write_memory_file(local_path, after_data)

        assert result["success"] is False
        assert "Entry limit exceeded" in result["error"]
        # File on disk is UNCHANGED
        on_disk = json.loads(local_path.read_text(encoding="utf-8"))
        assert "new_fat" not in on_disk["key_learnings"]


# ===========================================================================
# 10. write_memory_file: enforce mode ALLOWS unchanged legacy fat entries
# ===========================================================================


class TestEnforceAllowsUnchangedLegacy:
    """THE CRITICAL ROLLOVER-SAFE TEST: enforce mode allows writing back same fat data.

    The class name has been right the whole time; between 2026-08-27 and
    2026-08-30 the method under it asserted the opposite, which is its own
    small lesson — a name describing a rule the body no longer holds reads as
    proof the rule is there.
    """

    def test_enforce_allows_same_data_with_fat_entries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mem_mod = _get_memory_files()

        trinity = tmp_path / "test_branch" / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"

        fat_data = {"key_learnings": {"legacy": "z" * 500, "also_fat": "y" * 400}}
        local_path.write_text(json.dumps(fat_data, indent=2), encoding="utf-8")

        enforce_limits = _full_limits(enforce=True)
        monkeypatch.setattr(mem_mod, "load_entry_limits", lambda branch: enforce_limits)

        result = mem_mod.write_memory_file(local_path, fat_data)

        # Reversed 2026-08-30: the write authored nothing, so it is not refused.
        # Refusing it cured nothing and deadlocked rollover, whose write is
        # always the smaller document.
        assert result["success"] is True
        on_disk = json.loads(local_path.read_text(encoding="utf-8"))
        assert on_disk["key_learnings"]["legacy"] == "z" * 500


# ===========================================================================
# 11. write_memory_file: non-trinity file unaffected
# ===========================================================================


class TestNonTrinityFileUnaffected:
    """Files outside .trinity/ bypass validation entirely."""

    def test_writes_normally_outside_trinity(self, tmp_path: Path) -> None:
        mem_mod = _get_memory_files()

        output_path = tmp_path / "some_output.json"
        data = {"key": "value"}

        result = mem_mod.write_memory_file(output_path, data)

        assert result["success"] is True
        assert output_path.exists()
        written = json.loads(output_path.read_text(encoding="utf-8"))
        assert written == data


# ===========================================================================
# 12. write_memory_file: passport.json unaffected
# ===========================================================================


class TestPassportUnaffected:
    """Writes to .trinity/passport.json bypass validation."""

    def test_passport_writes_normally(self, tmp_path: Path) -> None:
        mem_mod = _get_memory_files()

        trinity = tmp_path / "test_branch" / ".trinity"
        trinity.mkdir(parents=True)
        passport_path = trinity / "passport.json"

        data = {"branch_info": {"branch_name": "test_branch"}, "identity": {"role": "test"}}

        result = mem_mod.write_memory_file(passport_path, data)

        assert result["success"] is True
        assert passport_path.exists()
        written = json.loads(passport_path.read_text(encoding="utf-8"))
        assert written == data


# ===========================================================================
# 13. THE SHRINK-WRITE DEADLOCK (2026-08-30)
# ===========================================================================
#
# @devpulse, via four @trigger repeat-signatures: rollover erroring identically
# every 20 minutes for three hours. The extractor removed the tail, wrote the
# document back, and the write gate refused the WHOLE file for an entry the
# extraction never touched — @seedgo's 343-char summary sitting in the head.
#
# That is a deadlock with the archiver on the losing side: the file cannot get
# smaller because it is too big. The lane that preserves everything else was
# bricked by one entry it is not allowed to shrink.
#
# THE NARROWING THAT CAUSED IT (2026-08-27) reasoned that the trinity push had
# cured drift fleet-wide, so "unchanged and over cap passes" now hid new drift
# instead of protecting old. Both halves were wrong about the world:
#
#   - Drift is not cured, it RECURS. @ai_mail carried three over-cap
#     key_learnings the same evening; @seedgo one.
#   - The write gate is structurally BLIND to how drift arrives. @hooks'
#     edit_gate says so in its own refusal text: writes made through Bash
#     (python -c, heredoc, sed) never reach it. @baud drifted to 2529/300 for
#     a week through that lane. An entry the gate never saw written cannot be
#     caught by refusing the next write — it can only be caught by READING THE
#     FILE, which is exactly what `drone @memory lint` does, on demand, fleet-
#     wide, read-only.
#
# So the narrowing put the detection job on the one component that cannot see
# the drift arrive, and paid for it with rollover.
#
# THE RULE, restored and widened: a write is judged by what it AUTHORS, never
# by what it carries. An entry byte-identical to one already on disk was not
# written by this write and cannot be refused to it. The silence that the
# narrowing rightly objected to is cured where silence was the actual defect —
# carried debt is now REPORTED on every write instead of skipped without a
# word, and `lint` remains the lane that reads disk.
#
# This is one classifier with two labels, not two rules: `changed_entries`
# answers "what did this write author", `carried_entries` answers "what is it
# carrying". Each consumer sets its own policy from the same measurement.


_FAT_SUMMARY = "X" * 343  # the @seedgo shape: over the 300-char sessions cap


class TestShrinkWriteIsNeverRefused:
    """Rollover's write REMOVES entries and authors nothing. It cannot be refused."""

    def test_removing_the_tail_passes_with_a_fat_entry_in_the_head(self, tmp_path: Path, monkeypatch) -> None:
        """The live deadlock, reproduced: 3 sessions in, tail archived, 2 out."""
        mem_mod = _get_memory_files()

        trinity = tmp_path / "seedgo" / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"

        before = {
            "sessions": [
                {"number": 3, "summary": _FAT_SUMMARY},  # head — kept, over cap, untouched
                {"number": 2, "summary": "within cap"},
                {"number": 1, "summary": "oldest — what rollover archives"},
            ]
        }
        local_path.write_text(json.dumps(before, indent=2), encoding="utf-8")

        enforce_limits = _full_limits(enforce=True)
        monkeypatch.setattr(mem_mod, "load_entry_limits", lambda branch: enforce_limits)

        after = {"sessions": before["sessions"][:2]}  # strictly a removal
        result = mem_mod.write_memory_file(local_path, after)

        assert result["success"] is True, f"shrink write refused: {result.get('error')}"
        assert len(json.loads(local_path.read_text(encoding="utf-8"))["sessions"]) == 2

    def test_the_carried_entry_is_reported_not_swallowed(self, tmp_path: Path, monkeypatch) -> None:
        """Passing silently is what the narrowing was right to object to."""
        mem_mod = _get_memory_files()
        mock_logger = mem_mod.logger

        trinity = tmp_path / "seedgo" / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"
        before = {"sessions": [{"number": 2, "summary": _FAT_SUMMARY}, {"number": 1, "summary": "old"}]}
        local_path.write_text(json.dumps(before, indent=2), encoding="utf-8")

        monkeypatch.setattr(mem_mod, "load_entry_limits", lambda branch: _full_limits(enforce=True))

        result = mem_mod.write_memory_file(local_path, {"sessions": before["sessions"][:1]})

        assert result["success"] is True
        warnings = " ".join(str(c) for c in mock_logger.warning.call_args_list)
        assert "CARRIED" in warnings, "carried debt passed without a word"
        assert "343/300" in warnings, "the report does not name the entry"
        assert "seedgo" in warnings, "the report does not name the owner"


class TestAuthoringIsStillRefused:
    """Widening the exemption must not open the door it was narrowed to close."""

    def test_a_new_over_cap_session_is_refused(self, tmp_path: Path, monkeypatch) -> None:
        mem_mod = _get_memory_files()

        trinity = tmp_path / "somebranch" / ".trinity"
        trinity.mkdir(parents=True)
        local_path = trinity / "local.json"
        local_path.write_text(json.dumps({"sessions": [{"number": 1, "summary": "ok"}]}), encoding="utf-8")

        monkeypatch.setattr(mem_mod, "load_entry_limits", lambda branch: _full_limits(enforce=True))

        after = {"sessions": [{"number": 2, "summary": _FAT_SUMMARY}, {"number": 1, "summary": "ok"}]}
        result = mem_mod.write_memory_file(local_path, after)

        assert result["success"] is False
        assert "343/300" in result["error"]

    def test_editing_a_carried_entry_and_leaving_it_over_cap_is_refused(self) -> None:
        """Touch it and you own it — the exemption covers only byte-identical text."""
        mod = _get_entry_limits()
        before = {"sessions": [{"number": 1, "summary": "z" * 500}]}
        after = {"sessions": [{"number": 1, "summary": "y" * 400}]}

        result = mod.changed_entries(before, after, _SESSIONS_ONLY)

        assert len(result) == 1
        assert result[0]["over_by"] == 100


class TestCarriedEntries:
    """The second label: what the write is carrying, measured from the same diff."""

    def test_carried_reports_the_untouched_over_cap_entry(self) -> None:
        mod = _get_entry_limits()
        fat = {"number": 1, "summary": _FAT_SUMMARY}
        before = {"sessions": [fat]}
        after = {"sessions": [fat]}

        assert mod.changed_entries(before, after, _SESSIONS_ONLY) == []
        carried = mod.classify_entries(before, after, _SESSIONS_ONLY)["carried"]
        assert len(carried) == 1
        assert carried[0]["container"] == "sessions"
        assert carried[0]["length"] == 343
        assert carried[0]["cap"] == 300

    def test_an_authored_entry_is_never_also_carried(self) -> None:
        """The two labels partition the over-cap set — no entry wears both."""
        mod = _get_entry_limits()
        before = {"sessions": [{"number": 1, "summary": "z" * 500}]}
        after = {
            "sessions": [
                {"number": 2, "summary": _FAT_SUMMARY},  # authored now
                {"number": 1, "summary": "z" * 500},  # carried
            ]
        }

        authored = mod.changed_entries(before, after, _SESSIONS_ONLY)
        carried = mod.classify_entries(before, after, _SESSIONS_ONLY)["carried"]

        assert [v["length"] for v in authored] == [343]
        assert [v["length"] for v in carried] == [500]

    def test_within_cap_entries_are_not_carried_debt(self) -> None:
        mod = _get_entry_limits()
        same = {"sessions": [{"number": 1, "summary": "well within"}]}

        assert mod.classify_entries(same, same, _SESSIONS_ONLY)["carried"] == []


class TestRenamedFieldEntryDoesNotBrickRollover:
    """An unmeasurable legacy entry is carried, not refused — same deadlock."""

    def test_a_legacy_renamed_field_entry_is_carried(self) -> None:
        """@ai_mail and @api carried `learning` where the config says `value`."""
        mod = _get_entry_limits()
        legacy = {"number": 1, "learning": "z" * 500}  # canonical field absent
        before = {"sessions": [legacy]}
        after = {"sessions": [legacy]}

        assert mod.changed_entries(before, after, _SESSIONS_ONLY) == []
        assert len(mod.classify_entries(before, after, _SESSIONS_ONLY)["carried"]) == 1


class TestTheBypassClaimIsMeasuredNotAsserted:
    """`.seedgo/bypass.json` claims @hooks calls `changed_entries` — this checks it.

    seedgo's unused_function checker is branch-local, so it correctly cannot see
    that this function's only caller lives in another tree. The bypass rule is
    the sanctioned way to say so, but a bypass is a CLAIM, and a claim nobody
    measures is how a real entry point gets deleted for a green audit two
    refactors from now.

    So the justification is pinned. The day @hooks stops calling it, this goes
    red and the bypass is provably stale — which is the moment to delete the
    function, not before.

    READ-ONLY and TOLERANT OF ABSENCE: it greps @hooks' tree for the call rather
    than pinning a line number, and skips where hooks is not installed, because
    an external checkout of this branch alone is a real world and not a failure.
    """

    @staticmethod
    def _hooks_root():
        """@hooks' source tree, or None when this checkout does not carry it."""
        from aipass.memory.apps.handlers import repo_root

        candidate = repo_root.SOURCE_ROOT / "src" / "aipass" / "hooks" / "apps"
        return candidate if candidate.is_dir() else None

    def test_hooks_still_calls_the_function_the_bypass_exempts(self) -> None:
        root = self._hooks_root()
        if root is None:
            pytest.skip("@hooks is not installed in this checkout — nothing to measure")

        callers = [
            path.relative_to(root)
            for path in root.rglob("*.py")
            if ".archive" not in path.parts and "changed_entries(" in path.read_text(encoding="utf-8")
        ]
        assert callers, (
            "no file in @hooks calls changed_entries() any more — the unused_function bypass in "
            ".seedgo/bypass.json is now a false claim. Either the caller moved (update the reason) "
            "or the function is genuinely dead (delete it and drop the bypass)."
        )

    def test_the_bypass_rule_is_narrowed_to_that_one_function(self) -> None:
        """A file-wide exemption would hide the NEXT orphan in the same file."""
        import json as _json
        from aipass.memory.apps.handlers import repo_root

        rules = _json.loads(
            (repo_root.SOURCE_ROOT / "src" / "aipass" / "memory" / ".seedgo" / "bypass.json").read_text(
                encoding="utf-8"
            )
        )["bypass"]
        mine = [
            rule
            for rule in rules
            if rule.get("standard") == "unused_function" and rule.get("file", "").endswith("entry_limits.py")
        ]
        assert mine, "the unused_function bypass for entry_limits.py is gone"
        assert mine[0].get("functions") == ["changed_entries"], (
            f"the exemption is not narrowed to the one function it was argued for: {mine[0]}"
        )
