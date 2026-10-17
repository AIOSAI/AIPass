# =================== AIPass ====================
# Name: test_rollover_pipeline_valve.py
# Description: Rollover pipeline - the extractor's safety valve, snapshot budget and newest-first guard
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/rollover/extractor.py — the safety valve, the snapshot budget and the ordering guard."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — write_memory_file_simple(), stood in here; tests/test_memory_files.py

import json
import logging
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from aipass.memory.tests.support_rollover_pipeline import _import_extractor


class TestRolloverSafetyValve:
    """Entries dated today or numbered above the head must never be archived as 'oldest'."""

    def test_skips_archiving_entry_dated_today(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()
        today = datetime.now().strftime("%Y-%m-%d")

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 4, "date": "2026-01-04", "summary": "newest", "status": "completed"},
                {"number": 3, "date": "2026-01-03", "summary": "second", "status": "completed"},
                {"number": 1, "date": today, "summary": "fresh-write-at-tail", "status": "completed"},
                {"number": 2, "date": "2026-01-01", "summary": "oldest-real", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True
        archived_summaries = [e["summary"] for e in result["extracted"]]
        assert "fresh-write-at-tail" not in archived_summaries
        assert "oldest-real" in archived_summaries
        remaining_summaries = [e["summary"] for e in data["sessions"]]
        assert "fresh-write-at-tail" in remaining_summaries

    def test_skips_archiving_entry_numbered_above_head(self, monkeypatch, tmp_path):
        """A tail entry numbered higher than the head is a misplaced write, not oldest history."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 5, "date": "2026-01-05", "summary": "newest", "status": "completed"},
                {"number": 4, "date": "2026-01-04", "summary": "second", "status": "completed"},
                {"number": 9, "date": "2020-01-01", "summary": "misplaced-high-number", "status": "completed"},
                {"number": 3, "date": "2026-01-01", "summary": "oldest-real", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True
        archived_summaries = [e["summary"] for e in result["extracted"]]
        assert "misplaced-high-number" not in archived_summaries
        assert "oldest-real" in archived_summaries
        remaining_summaries = [e["summary"] for e in data["sessions"]]
        assert "misplaced-high-number" in remaining_summaries

    def test_archives_genuinely_old_entry_normally(self, monkeypatch, tmp_path):
        """Sanity check: a plain old-dated, correctly-numbered tail entry still archives."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 3, "date": "2026-01-03", "summary": "newest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "middle", "status": "completed"},
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived_summaries = [e["summary"] for e in result["extracted"]]
        assert archived_summaries == ["oldest"]


class TestAutoCompactSnapshotBudget:
    """AUTO-COMPACT SNAPSHOT entries get a small dedicated cap, separate from the session keep budget."""

    def test_auto_compact_entries_capped_independently(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        sessions = [
            {"number": 6, "date": "2026-01-06", "summary": "AUTO-COMPACT SNAPSHOT: d", "status": "auto-compact"},
            {"number": 5, "date": "2026-01-05", "summary": "regular newest", "status": "completed"},
            {"number": 4, "date": "2026-01-04", "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 3, "date": "2026-01-03", "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 2, "date": "2026-01-02", "summary": "regular oldest", "status": "completed"},
            {"number": 1, "date": "2026-01-01", "summary": "AUTO-COMPACT SNAPSHOT: a", "status": "auto-compact"},
        ]
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": sessions,
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {
                branch_key: {"local": {"sessions": {"count": 10, "auto_compact_cap": 3}}},
            },
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived_summaries = {e["summary"] for e in result["extracted"]}
        assert archived_summaries == {"AUTO-COMPACT SNAPSHOT: a"}
        remaining_summaries = {e["summary"] for e in data["sessions"]}
        assert "regular newest" in remaining_summaries
        assert "regular oldest" in remaining_summaries

    def test_auto_compact_entries_do_not_count_against_regular_budget(self, monkeypatch, tmp_path):
        """Auto-compact snapshots must not push regular sessions out early."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        # Keep-2 keeps 2: three regulars are needed for anything to move.
        sessions = [
            {"number": 6, "date": "2026-01-06", "summary": "regular newest", "status": "completed"},
            {"number": 5, "date": "2026-01-05", "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 4, "date": "2026-01-04", "summary": "regular middle", "status": "completed"},
            {"number": 3, "date": "2026-01-03", "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 2, "date": "2026-01-02", "summary": "regular oldest", "status": "completed"},
            {"number": 1, "date": "2026-01-01", "summary": "AUTO-COMPACT SNAPSHOT: a", "status": "auto-compact"},
        ]
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": sessions,
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {
                branch_key: {"local": {"sessions": {"count": 2, "auto_compact_cap": 5}}},
            },
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived_summaries = {e["summary"] for e in result["extracted"]}
        assert archived_summaries == {"regular oldest"}
        remaining_summaries = {e["summary"] for e in data["sessions"]}
        assert "AUTO-COMPACT SNAPSHOT: a" in remaining_summaries
        assert "AUTO-COMPACT SNAPSHOT: b" in remaining_summaries
        assert "AUTO-COMPACT SNAPSHOT: c" in remaining_summaries
        assert "regular newest" in remaining_summaries
        assert "regular middle" in remaining_summaries


class TestAutoCompactSameDaySnapshots:
    """The snapshot lane must drain even when every snapshot is dated today, or the detector skip-loops."""

    @staticmethod
    def _setup(ext, mocks, tmp_path, sessions, cap=3, count=10):
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": sessions,
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {tmp_path.name.lower(): {"local": {"sessions": {"count": count, "auto_compact_cap": cap}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data
        return file_path, data

    def test_same_day_snapshots_drain_over_cap(self, monkeypatch, tmp_path):
        """4 snapshots, all written today, cap 3 -> the oldest one archives despite the date."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 30, "date": today, "summary": "regular newest", "status": "completed"},
            {"number": 29, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: d", "status": "auto-compact"},
            {"number": 27, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 25, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 22, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: a", "status": "auto-compact"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True, "snapshot lane skipped — the file cannot drain"
        assert {e["summary"] for e in result["extracted"]} == {"AUTO-COMPACT SNAPSHOT: a"}
        assert "regular newest" in {e["summary"] for e in data["sessions"]}

    def test_skip_loop_terminates(self, monkeypatch, tmp_path):
        """Repeated runs must reach a steady state AT the cap (keep-3 keeps 3), not re-trigger forever."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [{"number": 40, "date": today, "summary": "regular newest", "status": "completed"}]
        sessions += [
            {"number": 30 - i, "date": today, "summary": f"snap-{i}", "status": "auto-compact"} for i in range(5)
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        # The write path is mocked, so `data` (mutated in place) is what the next run reads.
        archived_total = 0
        per_run = []
        for _ in range(5):
            result = ext.extract_items(file_path)
            assert result["success"] is True
            archived = len(result.get("extracted", []))
            archived_total += archived
            per_run.append(archived)

        snapshots = [e for e in data["sessions"] if e.get("status") == "auto-compact"]
        assert archived_total > 0, "nothing ever archived — the skip loop is live"
        assert len(snapshots) == 3, f"snapshot lane did not settle at the cap: {len(snapshots)} left"
        assert per_run[-1] == 0 and per_run[-2] == 0, f"lane never stopped draining: {per_run}"

    def test_snapshot_numbered_above_head_is_still_refused(self, monkeypatch, tmp_path):
        """Relaxing the date rule must not relax the ordering rule."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 30, "date": today, "summary": "regular newest", "status": "completed"},
            {"number": 29, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 28, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"number": 99, "date": today, "summary": "misplaced-high-number", "status": "auto-compact"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        result = ext.extract_items(file_path)

        archived = {e["summary"] for e in result.get("extracted", [])}
        assert "misplaced-high-number" not in archived
        assert "misplaced-high-number" in {e["summary"] for e in data["sessions"]}

    def test_snapshot_without_a_number_keeps_the_date_guard(self, monkeypatch, tmp_path):
        """When ordering cannot decide, the conservative date rule still applies."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 30, "date": today, "summary": "regular newest", "status": "completed"},
            {"number": 29, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: c", "status": "auto-compact"},
            {"number": 28, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: b", "status": "auto-compact"},
            {"date": today, "summary": "numberless-fresh-snapshot", "status": "auto-compact"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions)

        result = ext.extract_items(file_path)

        archived = {e["summary"] for e in result.get("extracted", [])}
        assert "numberless-fresh-snapshot" not in archived
        assert "numberless-fresh-snapshot" in {e["summary"] for e in data["sessions"]}

    def test_regular_session_dated_today_is_still_refused(self, monkeypatch, tmp_path):
        """DPLAN-0278 protection for the regular lane is untouched by the snapshot relaxation."""
        ext, mocks = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        sessions = [
            {"number": 4, "date": "2026-01-04", "summary": "regular newest", "status": "completed"},
            {"number": 3, "date": "2026-01-03", "summary": "regular second", "status": "completed"},
            {"number": 9, "date": today, "summary": "AUTO-COMPACT SNAPSHOT: fresh", "status": "auto-compact"},
            {"number": 1, "date": today, "summary": "fresh-write-at-tail", "status": "completed"},
        ]
        file_path, data = self._setup(ext, mocks, tmp_path, sessions, cap=3, count=2)

        result = ext.extract_items(file_path)

        archived = {e["summary"] for e in result.get("extracted", [])}
        assert "fresh-write-at-tail" not in archived
        assert "fresh-write-at-tail" in {e["summary"] for e in data["sessions"]}

    def test_is_misplaced_entry_date_guard_matrix(self, monkeypatch):
        """Pin the helper directly: what each guard mode decides."""
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")

        fresh_today = {"number": 5, "date": today}
        above_head = {"number": 99, "date": "2020-01-01"}
        numberless = {"date": today}

        # Date guard on: an unknown head_date reads as "not today".
        assert ext._is_misplaced_entry(fresh_today, 10) is True
        assert ext._is_misplaced_entry(above_head, 10) is True
        assert ext._is_misplaced_entry(numberless, 10) is True

        # A head itself dated today: ordering decides for entries below it.
        assert ext._is_misplaced_entry(fresh_today, 10, head_date=today) is False
        assert ext._is_misplaced_entry(above_head, 10, head_date=today) is True
        assert ext._is_misplaced_entry(numberless, 10, head_date=today) is True

        # Date guard off: ordering decides, unless it cannot.
        assert ext._is_misplaced_entry(fresh_today, 10, date_guard=False) is False
        assert ext._is_misplaced_entry(above_head, 10, date_guard=False) is True
        assert ext._is_misplaced_entry(numberless, 10, date_guard=False) is True


class TestARefusedWriteMustNotReadAsASuccessfulRollover:
    """A swallowed write refusal makes the archive store, every run, entries the file never gave up."""

    def test_a_refused_write_raises_instead_of_returning_quietly(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        target = tmp_path / "local.json"
        target.write_text("{}", encoding="utf-8")

        writer = MagicMock(return_value=False)
        monkeypatch.setattr(ext, "write_memory_file_simple", writer)

        with pytest.raises(OSError):
            ext._write_memory_file(target, {"sessions": []})
        writer.assert_called_once_with(target, {"sessions": []})

    def test_a_successful_write_still_returns_quietly(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        target = tmp_path / "local.json"
        target.write_text("{}", encoding="utf-8")

        writer = MagicMock(return_value=True)
        monkeypatch.setattr(ext, "write_memory_file_simple", writer)

        assert ext._write_memory_file(target, {"sessions": []}) is None
        writer.assert_called_once_with(target, {"sessions": []})

    def test_the_refusal_reaches_the_caller_as_a_failed_extraction(self, monkeypatch, tmp_path):
        """A refused write must NOT be reported as archived, or the orchestrator vectorizes what the file holds."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": n, "date": "2026-01-0%d" % (n % 9 + 1), "summary": f"s{n}", "status": "completed"}
                for n in range(6, 0, -1)
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 2}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data
        writer = MagicMock(return_value=False)
        monkeypatch.setattr(ext, "write_memory_file_simple", writer)

        result = ext.extract_items(file_path)

        assert writer.call_args.args[0] == file_path, "the refusal must come from the rolled file's own write"
        assert result["success"] is False
        # No `extracted` key at all, so no caller can read partial work out of a dead run.
        assert sorted(result) == ["error", "success"], sorted(result)


class TestTodayIsNotEvidenceAgainstANumberedEntry:
    """A day's worth of correctly numbered entries drains: the date is only a proxy where ordering cannot decide."""

    def test_a_days_worth_of_correctly_ordered_entries_can_drain(self, monkeypatch, caplog):
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": today} for n in range(135, 108, -1)]
        assert len(entries) == 27

        with caplog.at_level(logging.WARNING):
            archivable = ext._extract_tail_excess(
                entries, 15, entries[0]["number"], "key_learnings", "memory", head_date=today
            )

        assert [e["number"] for e in archivable] == list(range(120, 108, -1))
        assert "NOTHING DRAINED" not in caplog.text

    def test_an_entry_numbered_above_the_head_is_still_refused(self, monkeypatch):
        """The real convention-loss shape survives the narrowing."""
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": today} for n in range(20, 10, -1)]
        entries.append({"number": 99, "date": today, "why": "prepend became append"})

        archivable = ext._extract_tail_excess(
            entries, 5, entries[0]["number"], "key_learnings", "victim", head_date=today
        )

        assert 99 not in [e["number"] for e in archivable]

    def test_a_tail_entry_numbered_equal_to_the_head_is_still_refused(self, monkeypatch):
        """The `<` in `number < head_number`: a duplicate of the head at the tail falls to the date rule."""
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": today} for n in range(20, 10, -1)]
        entries.append({"number": 20, "date": today, "why": "duplicate of the head, at the tail"})

        archivable = ext._extract_tail_excess(
            entries, 5, entries[0]["number"], "key_learnings", "victim", head_date=today
        )

        assert all("why" not in e for e in archivable), archivable

    def test_key_learnings_drain_end_to_end_when_the_whole_array_is_todays(self, monkeypatch, tmp_path):
        """The head_date WIRING through `_extract_items_v2`, not just the predicate."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()
        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "key_learnings": [{"number": n, "date": today, "key": f"k{n}", "value": f"v{n}"} for n in range(27, 0, -1)],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"key_learnings": {"count": 15}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data
        mocks["memory_files"].write_memory_file_simple.return_value = True

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is not True, "the whole point is that it does NOT skip"
        assert result["extracted_count"] == 12, result.get("extracted_count")
        assert [e["number"] for e in result["extracted"]] == list(range(12, 0, -1))

    def test_a_numberless_entry_dated_today_is_still_refused(self, monkeypatch):
        """Where ordering cannot decide, the date rule is all there is."""
        ext, _ = _import_extractor(monkeypatch)
        today = datetime.now().strftime("%Y-%m-%d")
        entries = [{"number": n, "date": "2020-01-01"} for n in range(20, 10, -1)]
        entries.append({"date": today, "summary": "no number at all"})

        archivable = ext._extract_tail_excess(
            entries, 5, entries[0]["number"], "key_learnings", "victim", head_date=today
        )

        assert all("summary" not in e for e in archivable)


class TestNewestFirstOrderingGuard:
    """Rollover must not trust stored order — the tail is only 'oldest' if the array is newest-first."""

    def test_oldest_first_array_is_reordered_before_archiving(self, monkeypatch, tmp_path):
        """An oldest-first sessions[] must be re-sorted so the newest entry is never archived."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "second", "status": "completed"},
                {"number": 3, "date": "2026-01-03", "summary": "third", "status": "completed"},
                {"number": 4, "date": "2026-01-04", "summary": "NEWEST", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 3}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived = [e["summary"] for e in result["extracted"]]
        assert "NEWEST" not in archived
        assert archived == ["oldest"]
        assert [e["number"] for e in data["sessions"]] == [4, 3, 2]

    def test_commons_mixed_order_regression(self, monkeypatch, tmp_path):
        """Newest prepended above an oldest-first legacy block: the valve alone cannot catch it."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        sessions = [{"number": 16, "date": "2026-08-07", "summary": "newest prepended", "status": "completed"}]
        sessions += [
            {"number": n, "date": "2026-03-28", "summary": f"legacy-{n}", "status": "completed"} for n in range(1, 14)
        ]
        data = {"document_metadata": {"schema_version": "3.0.0", "status": {}}, "sessions": sessions}
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 13}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["success"] is True
        archived = [e["summary"] for e in result["extracted"]]
        assert "legacy-13" not in archived
        assert archived == ["legacy-1"]
        assert data["sessions"][0]["number"] == 16
        assert data["sessions"][-1]["number"] == 2

    def test_order_repair_persisted_when_nothing_archived(self, monkeypatch, tmp_path):
        """A reorder with no excess must still be written, or the fault recurs next run."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "newest", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 10}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        writer = mocks["memory_files"].write_memory_file_simple
        writer.reset_mock()

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is True
        writer.assert_called_once()
        written_data = writer.call_args[0][1]
        assert [e["number"] for e in written_data["sessions"]] == [2, 1]

    def test_correctly_ordered_array_is_left_untouched(self, monkeypatch, tmp_path):
        """No spurious rewrite when the array is already newest-first."""
        ext, mocks = _import_extractor(monkeypatch)
        branch_key = tmp_path.name.lower()

        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {}},
            "sessions": [
                {"number": 3, "date": "2026-01-03", "summary": "newest", "status": "completed"},
                {"number": 2, "date": "2026-01-02", "summary": "middle", "status": "completed"},
                {"number": 1, "date": "2026-01-01", "summary": "oldest", "status": "completed"},
            ],
        }
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 10}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        writer = mocks["memory_files"].write_memory_file_simple
        writer.reset_mock()

        result = ext.extract_items(file_path)

        assert result["success"] is True
        assert result.get("skipped") is True
        writer.assert_not_called()
        assert [e["number"] for e in data["sessions"]] == [3, 2, 1]

    def test_entries_without_numbers_are_not_reordered(self, monkeypatch, tmp_path):
        """Arrays lacking numeric 'number' fields must pass through unchanged."""
        ext, _ = _import_extractor(monkeypatch)
        entries = [{"summary": "a"}, {"summary": "b"}]
        result, repaired = ext._ensure_newest_first(entries, "sessions", "test")
        assert repaired is False
        assert result == entries
