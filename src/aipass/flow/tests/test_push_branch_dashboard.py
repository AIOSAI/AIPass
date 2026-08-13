# =================== AIPass ====================
# Name: test_push_branch_dashboard.py
# Description: Tests for push_branch_dashboard handler — branch dashboard push
# Version: 1.1.0
# Created: 2026-04-26
# Modified: 2026-08-13
# =============================================

"""Tests for push_branch_dashboard handler — branch dashboard push."""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

_MOD = "aipass.flow.apps.handlers.dashboard.push_branch_dashboard"


# ─── Import helpers ───────────────────────────────────────


def _import_mod():
    import aipass.flow.apps.handlers.dashboard.push_branch_dashboard as mod

    return mod


# ═══════════════════════════════════════════════════════════
# 1. _write_dashboard_section
# ═══════════════════════════════════════════════════════════


class TestWriteDashboardSection:
    """Tests for _write_dashboard_section."""

    def test_creates_dashboard_when_not_exists(self, tmp_path):
        """Creates DASHBOARD.local.json when it does not exist."""
        mod = _import_mod()
        section_data = {"managed_by": "flow", "active_plans": [], "active_count": 0}
        with patch.object(mod, "DASHBOARD_TEMPLATE_FILE", tmp_path / "nonexistent_template.json"):
            result = mod._write_dashboard_section(tmp_path, "flow", section_data)
        assert result is True
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        assert dashboard_path.exists()
        dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
        assert "flow" in dashboard["sections"]
        assert dashboard["sections"]["flow"]["managed_by"] == "flow"

    def test_updates_existing_dashboard(self, tmp_path):
        """Updates an existing DASHBOARD.local.json with new section data."""
        mod = _import_mod()
        existing = {
            "branch": "TEST",
            "last_updated": "",
            "quick_status": {},
            "sections": {
                "ai_mail": {"managed_by": "ai_mail", "new": 0},
            },
        }
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps(existing), encoding="utf-8")

        section_data = {"managed_by": "flow", "active_plans": [], "active_count": 0}
        result = mod._write_dashboard_section(tmp_path, "flow", section_data)

        assert result is True
        updated = json.loads(dashboard_path.read_text(encoding="utf-8"))
        assert "flow" in updated["sections"]
        assert "ai_mail" in updated["sections"]

    def test_corrupt_json_creates_fresh(self, tmp_path):
        """Corrupt JSON in dashboard file triggers creation of fresh dashboard."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text("{not valid json!!!", encoding="utf-8")

        section_data = {"managed_by": "flow", "active_count": 0}
        with patch.object(mod, "DASHBOARD_TEMPLATE_FILE", tmp_path / "nonexistent_template.json"):
            result = mod._write_dashboard_section(tmp_path, "flow", section_data)

        assert result is True
        updated = json.loads(dashboard_path.read_text(encoding="utf-8"))
        assert "sections" in updated
        assert "flow" in updated["sections"]

    def test_empty_file_creates_fresh(self, tmp_path):
        """Empty dashboard file triggers creation of fresh dashboard."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text("", encoding="utf-8")

        section_data = {"managed_by": "flow", "active_count": 0}
        with patch.object(mod, "DASHBOARD_TEMPLATE_FILE", tmp_path / "nonexistent_template.json"):
            result = mod._write_dashboard_section(tmp_path, "flow", section_data)

        assert result is True
        updated = json.loads(dashboard_path.read_text(encoding="utf-8"))
        assert "sections" in updated

    def test_recalculates_quick_status(self, tmp_path):
        """Dashboard quick_status is recalculated after section write."""
        mod = _import_mod()
        existing = {
            "branch": "TEST",
            "last_updated": "",
            "quick_status": {},
            "sections": {
                "ai_mail": {"managed_by": "ai_mail", "new": 3},
            },
        }
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps(existing), encoding="utf-8")

        section_data = {"managed_by": "flow", "active_count": 2}
        result = mod._write_dashboard_section(tmp_path, "flow", section_data)

        assert result is True
        updated = json.loads(dashboard_path.read_text(encoding="utf-8"))
        assert updated["quick_status"]["action_required"] is True
        assert updated["quick_status"]["new_mail"] == 3
        assert updated["quick_status"]["active_plans"] == 2

    def test_preserves_foreign_quick_status_keys(self, tmp_path):
        """A quick_status key written by another service survives our push."""
        mod = _import_mod()
        existing = {
            "branch": "TEST",
            "last_updated": "",
            # @prax's schema: has todo_count, has no commons_mentions
            "quick_status": {
                "new_mail": 1,
                "opened_mail": 0,
                "active_plans": 0,
                "todo_count": 9,
                "action_required": True,
                "summary": "1 new emails, 9 todos",
            },
            "sections": {
                "ai_mail": {"managed_by": "ai_mail", "new": 1},
            },
        }
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps(existing), encoding="utf-8")

        section_data = {"managed_by": "flow", "active_count": 0}
        result = mod._write_dashboard_section(tmp_path, "flow", section_data)

        assert result is True
        updated = json.loads(dashboard_path.read_text(encoding="utf-8"))
        quick = updated["quick_status"]
        assert quick["todo_count"] == 9, "foreign key was clobbered by the flow push"
        assert "9 todos" in quick["summary"]
        assert quick["new_mail"] == 1

    def test_returns_false_on_exception(self, tmp_path):
        """Returns False when an exception occurs during write."""
        mod = _import_mod()
        section_data = {"managed_by": "flow"}
        # Patch Path to simulate write failure
        with patch.object(mod, "_create_fresh_dashboard", side_effect=RuntimeError("boom")):
            result = mod._write_dashboard_section(tmp_path, "flow", section_data)
        assert result is False

    def test_adds_last_updated_to_section(self, tmp_path):
        """Section data gets a last_updated timestamp injected."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps({"sections": {}}), encoding="utf-8")

        section_data = {"managed_by": "flow", "active_count": 0}
        mod._write_dashboard_section(tmp_path, "flow", section_data)

        updated = json.loads(dashboard_path.read_text(encoding="utf-8"))
        assert "last_updated" in updated["sections"]["flow"]
        assert "last_updated" in updated


# ═══════════════════════════════════════════════════════════
# 2. _create_fresh_dashboard
# ═══════════════════════════════════════════════════════════


class TestCreateFreshDashboard:
    """Tests for _create_fresh_dashboard."""

    def test_uses_template_when_exists(self, tmp_path):
        """Loads from DASHBOARD_TEMPLATE_FILE when it exists."""
        mod = _import_mod()
        template = {
            "branch": "{{BRANCHNAME}}",
            "sections": {},
            "last_updated": "",
        }
        template_file = tmp_path / "DASHBOARD.template.json"
        template_file.write_text(json.dumps(template), encoding="utf-8")

        branch_path = tmp_path / "my_branch"
        branch_path.mkdir()

        with patch.object(mod, "DASHBOARD_TEMPLATE_FILE", template_file):
            result = mod._create_fresh_dashboard(branch_path)

        assert result["branch"] == "MY_BRANCH"
        assert "last_updated" in result

    def test_fallback_when_no_template(self, tmp_path):
        """Falls back to hardcoded defaults when template file does not exist."""
        mod = _import_mod()
        branch_path = tmp_path / "test_branch"
        branch_path.mkdir()

        with patch.object(mod, "DASHBOARD_TEMPLATE_FILE", tmp_path / "nonexistent.json"):
            result = mod._create_fresh_dashboard(branch_path)

        assert result["branch"] == "TEST_BRANCH"
        assert result["_warning"] == "AUTO-GENERATED FILE - DO NOT MANUALLY EDIT."
        assert "ai_mail" in result["sections"]
        assert "flow" in result["sections"]
        assert "memory" in result["sections"]
        assert "devpulse" in result["sections"]
        assert "commons_activity" in result["sections"]

    def test_fallback_on_corrupt_template(self, tmp_path):
        """Falls back to defaults when template file contains invalid JSON."""
        mod = _import_mod()
        template_file = tmp_path / "DASHBOARD.template.json"
        template_file.write_text("not json at all", encoding="utf-8")

        branch_path = tmp_path / "fallback_branch"
        branch_path.mkdir()

        with patch.object(mod, "DASHBOARD_TEMPLATE_FILE", template_file):
            result = mod._create_fresh_dashboard(branch_path)

        assert result["branch"] == "FALLBACK_BRANCH"
        assert "sections" in result


# ═══════════════════════════════════════════════════════════
# 3. _calculate_quick_status
# ═══════════════════════════════════════════════════════════


class TestCalculateQuickStatus:
    """Tests for _calculate_quick_status."""

    def test_all_clear_when_nothing(self):
        """Returns 'All clear' summary when all counts are zero."""
        mod = _import_mod()
        sections = {
            "ai_mail": {"new": 0, "opened": 0},
            "flow": {"active_count": 0},
            "commons_activity": {"mentions": 0},
        }
        result = mod._calculate_quick_status(sections)
        assert result["action_required"] is False
        assert result["summary"] == "All clear"
        assert result["new_mail"] == 0

    def test_action_required_with_new_mail(self):
        """Sets action_required True when there is new mail."""
        mod = _import_mod()
        sections = {
            "ai_mail": {"new": 5, "opened": 1},
            "flow": {"active_count": 0},
            "commons_activity": {"mentions": 0},
        }
        result = mod._calculate_quick_status(sections)
        assert result["action_required"] is True
        assert "5 new emails" in result["summary"]
        assert "1 opened" in result["summary"]

    def test_active_plans_as_list(self):
        """Handles active_count being a list by taking len()."""
        mod = _import_mod()
        sections = {
            "ai_mail": {"new": 0},
            "flow": {"active_count": ["plan1", "plan2", "plan3"]},
            "commons_activity": {"mentions": 0},
        }
        result = mod._calculate_quick_status(sections)
        assert result["active_plans"] == 3
        assert result["action_required"] is True
        assert "3 active plans" in result["summary"]

    def test_active_plans_as_int(self):
        """Handles active_count as an integer directly."""
        mod = _import_mod()
        sections = {
            "ai_mail": {"new": 0},
            "flow": {"active_count": 2},
            "commons_activity": {"mentions": 0},
        }
        result = mod._calculate_quick_status(sections)
        assert result["active_plans"] == 2

    def test_mentions_trigger_action_required(self):
        """Commons mentions trigger action_required."""
        mod = _import_mod()
        sections = {
            "ai_mail": {"new": 0},
            "flow": {"active_count": 0},
            "commons_activity": {"mentions": 4},
        }
        result = mod._calculate_quick_status(sections)
        assert result["action_required"] is True
        assert "4 mentions" in result["summary"]

    def test_empty_sections(self):
        """Handles completely empty sections dict."""
        mod = _import_mod()
        result = mod._calculate_quick_status({})
        assert result["action_required"] is False
        assert result["summary"] == "All clear"
        assert result["new_mail"] == 0
        assert result["active_plans"] == 0
        assert result["commons_mentions"] == 0

    def test_uses_unread_fallback(self):
        """Falls back to 'unread' key when 'new' is missing from ai_mail."""
        mod = _import_mod()
        sections = {
            "ai_mail": {"unread": 7},
            "flow": {"active_count": 0},
            "commons_activity": {"mentions": 0},
        }
        result = mod._calculate_quick_status(sections)
        assert result["new_mail"] == 7
        assert result["action_required"] is True


# ═══════════════════════════════════════════════════════════
# 3b. _calculate_quick_status — merge semantics (foreign keys)
# ═══════════════════════════════════════════════════════════


class TestCalculateQuickStatusMerge:
    """quick_status has multiple writers — we update our keys, preserve theirs."""

    def test_unknown_keys_survive_verbatim(self):
        """Keys we know nothing about are carried through untouched."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 0}, "flow": {"active_count": 0}}
        existing = {"todo_count": 9, "custom_flag": "keep-me", "nested": {"a": 1}}

        result = mod._calculate_quick_status(sections, existing)

        assert result["todo_count"] == 9
        assert result["custom_flag"] == "keep-me"
        assert result["nested"] == {"a": 1}

    def test_foreign_counter_keeps_action_required(self):
        """A foreign *_count still pending means the branch still needs action."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 0}, "flow": {"active_count": 0}}

        result = mod._calculate_quick_status(sections, {"todo_count": 9})

        assert result["action_required"] is True
        assert result["summary"] == "9 todos"

    def test_foreign_counter_at_zero_stays_all_clear(self):
        """A zeroed foreign counter is preserved but raises no flag."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 0}, "flow": {"active_count": 0}}

        result = mod._calculate_quick_status(sections, {"todo_count": 0})

        assert result["todo_count"] == 0
        assert result["action_required"] is False
        assert result["summary"] == "All clear"

    def test_foreign_non_counter_is_preserved_but_not_interpreted(self):
        """Only *_count keys are read as counters; other keys are data we pass on."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 0}, "flow": {"active_count": 0}}

        result = mod._calculate_quick_status(sections, {"last_refresh_ms": 1500})

        assert result["last_refresh_ms"] == 1500
        assert result["action_required"] is False
        assert "1500" not in result["summary"]

    def test_non_numeric_foreign_counter_does_not_raise(self):
        """A *_count key holding junk is preserved, never compared numerically."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 0}, "flow": {"active_count": 0}}

        result = mod._calculate_quick_status(sections, {"todo_count": None, "err_count": "n/a"})

        assert result["todo_count"] is None
        assert result["err_count"] == "n/a"
        assert result["action_required"] is False

    def test_our_own_keys_win_over_stale_values(self):
        """Keys we own are recomputed, never inherited from the previous write."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 1}, "flow": {"active_count": 2}, "commons_activity": {"mentions": 0}}
        existing = {"active_plans": 99, "commons_mentions": 99, "summary": "stale"}

        result = mod._calculate_quick_status(sections, existing)

        assert result["active_plans"] == 2
        assert result["commons_mentions"] == 0
        assert result["summary"] == "1 new emails, 2 active plans"

    def test_mail_counts_already_set_are_not_downgraded(self):
        """@prax reads inbox.json first-hand; our stale section view must not overwrite it."""
        mod = _import_mod()
        # Section says nothing is open; the live inbox (via @prax) says one is.
        sections = {"ai_mail": {"new": 0, "opened": 0}, "flow": {"active_count": 0}}
        existing = {"new_mail": 0, "opened_mail": 1}

        result = mod._calculate_quick_status(sections, existing)

        assert result["opened_mail"] == 1
        assert result["summary"] == "1 opened"

    def test_mail_counts_seeded_when_absent(self):
        """On a dashboard with no mail counts yet, we seed them from the ai_mail section."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 3, "opened": 2}, "flow": {"active_count": 0}}

        result = mod._calculate_quick_status(sections, {"todo_count": 1})

        assert result["new_mail"] == 3
        assert result["opened_mail"] == 2
        assert result["summary"] == "3 new emails, 2 opened, 1 todos"

    def test_summary_lists_our_parts_then_foreign(self):
        """Foreign counters are appended after the parts we compute."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 1}, "flow": {"active_count": 2}, "commons_activity": {"mentions": 3}}

        result = mod._calculate_quick_status(sections, {"todo_count": 4})

        assert result["summary"] == "1 new emails, 2 active plans, 3 mentions, 4 todos"

    def test_no_existing_block_behaves_as_before(self):
        """Omitting the existing block keeps the original single-writer behaviour."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 0}, "flow": {"active_count": 0}}

        assert mod._calculate_quick_status(sections) == mod._calculate_quick_status(sections, {})

    def test_non_dict_existing_is_ignored(self):
        """A corrupt (non-dict) quick_status block does not break the write."""
        mod = _import_mod()
        sections = {"ai_mail": {"new": 0}, "flow": {"active_count": 0}}

        result = mod._calculate_quick_status(sections, "not-a-dict")

        assert result["summary"] == "All clear"
        assert result["action_required"] is False


# ═══════════════════════════════════════════════════════════
# 4. _get_all_registry_files
# ═══════════════════════════════════════════════════════════


class TestGetAllRegistryFiles:
    """Tests for _get_all_registry_files."""

    def test_reads_template_registry(self, tmp_path):
        """Reads per-type registry filenames from template_registry.json."""
        mod = _import_mod()
        template_reg = {
            "types": {
                "flow_plans": {"prefix": "FPLAN"},
                "dev_plans": {"prefix": "DPLAN"},
            }
        }
        reg_file = tmp_path / "template_registry.json"
        reg_file.write_text(json.dumps(template_reg), encoding="utf-8")

        with patch.object(mod, "FLOW_JSON_DIR", tmp_path):
            result = mod._get_all_registry_files()

        assert "fplan_registry.json" in result
        assert "dplan_registry.json" in result
        assert len(result) == 2

    def test_falls_back_on_missing_template_registry(self, tmp_path):
        """Falls back to REGISTRY_FILE.name when template_registry.json is missing."""
        mod = _import_mod()
        with patch.object(mod, "FLOW_JSON_DIR", tmp_path):
            result = mod._get_all_registry_files()
        assert result == [mod.REGISTRY_FILE.name]

    def test_deduplicates_prefixes(self, tmp_path):
        """Does not duplicate registry filenames for repeated prefixes."""
        mod = _import_mod()
        template_reg = {
            "types": {
                "flow_plans": {"prefix": "FPLAN"},
                "flow_plans_v2": {"prefix": "FPLAN"},
            }
        }
        reg_file = tmp_path / "template_registry.json"
        reg_file.write_text(json.dumps(template_reg), encoding="utf-8")

        with patch.object(mod, "FLOW_JSON_DIR", tmp_path):
            result = mod._get_all_registry_files()

        assert result.count("fplan_registry.json") == 1


# ═══════════════════════════════════════════════════════════
# 5. _load_registry
# ═══════════════════════════════════════════════════════════


class TestLoadRegistry:
    """Tests for _load_registry."""

    def test_merges_multiple_registries(self, tmp_path):
        """Merges plans from multiple registry files using composite keys."""
        mod = _import_mod()
        fplan_reg = {"plans": {"1": {"subject": "fplan one", "file_path": "/p/FPLAN-0001_test.md"}}, "next_number": 5}
        dplan_reg = {"plans": {"2": {"subject": "dplan one", "file_path": "/p/DPLAN-0002_test.md"}}, "next_number": 10}
        (tmp_path / "fplan_registry.json").write_text(json.dumps(fplan_reg), encoding="utf-8")
        (tmp_path / "dplan_registry.json").write_text(json.dumps(dplan_reg), encoding="utf-8")

        with (
            patch.object(mod, "FLOW_JSON_DIR", tmp_path),
            patch.object(mod, "_get_all_registry_files", return_value=["fplan_registry.json", "dplan_registry.json"]),
        ):
            result = mod._load_registry()

        assert "FPLAN-0001" in result["plans"]
        assert "DPLAN-0002" in result["plans"]
        assert result["next_number"] == 10

    def test_handles_missing_registry(self, tmp_path):
        """Gracefully handles a missing registry file."""
        mod = _import_mod()
        with (
            patch.object(mod, "FLOW_JSON_DIR", tmp_path),
            patch.object(mod, "_get_all_registry_files", return_value=["nonexistent_registry.json"]),
        ):
            result = mod._load_registry()
        assert result["plans"] == {}
        assert result["next_number"] == 1

    def test_keeps_highest_next_number(self, tmp_path):
        """Keeps the highest next_number across registries."""
        mod = _import_mod()
        reg_a = {"plans": {}, "next_number": 3}
        reg_b = {"plans": {}, "next_number": 50}
        reg_c = {"plans": {}, "next_number": 20}
        (tmp_path / "a_registry.json").write_text(json.dumps(reg_a), encoding="utf-8")
        (tmp_path / "b_registry.json").write_text(json.dumps(reg_b), encoding="utf-8")
        (tmp_path / "c_registry.json").write_text(json.dumps(reg_c), encoding="utf-8")

        with (
            patch.object(mod, "FLOW_JSON_DIR", tmp_path),
            patch.object(
                mod,
                "_get_all_registry_files",
                return_value=["a_registry.json", "b_registry.json", "c_registry.json"],
            ),
        ):
            result = mod._load_registry()
        assert result["next_number"] == 50

    def test_handles_corrupt_registry_gracefully(self, tmp_path):
        """Skips a corrupt registry file and continues with others."""
        mod = _import_mod()
        (tmp_path / "bad_registry.json").write_text("not json!", encoding="utf-8")
        good_reg = {"plans": {"1": {"subject": "good", "file_path": "/p/GOOD-0001_test.md"}}, "next_number": 5}
        (tmp_path / "good_registry.json").write_text(json.dumps(good_reg), encoding="utf-8")

        with (
            patch.object(mod, "FLOW_JSON_DIR", tmp_path),
            patch.object(
                mod,
                "_get_all_registry_files",
                return_value=["bad_registry.json", "good_registry.json"],
            ),
        ):
            result = mod._load_registry()

        assert "GOOD-0001" in result["plans"]
        assert result["next_number"] == 5


# ═══════════════════════════════════════════════════════════
# 6. _filter_branch_plans
# ═══════════════════════════════════════════════════════════


class TestFilterBranchPlans:
    """Tests for _filter_branch_plans."""

    def test_filters_active_plans_for_branch(self, tmp_path):
        """Returns active plans matching the branch path."""
        mod = _import_mod()
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Plan A",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": str(tmp_path / "FPLAN-0001_plan_a.md"),
                    "location": str(tmp_path),
                },
                "FPLAN-0002": {
                    "subject": "Plan B",
                    "status": "open",
                    "created": "2026-04-22",
                    "file_path": str(tmp_path / "FPLAN-0002_plan_b.md"),
                    "location": str(tmp_path),
                },
            }
        }
        active, closed, total = mod._filter_branch_plans(registry, tmp_path)
        assert len(active) == 2
        assert len(closed) == 0
        assert total == 2
        # Newest first
        assert active[0]["id"] == "FPLAN-0002"

    def test_no_plans_for_branch(self, tmp_path):
        """Returns empty lists when no plans match the branch."""
        mod = _import_mod()
        other_path = tmp_path / "other_branch"
        other_path.mkdir()
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Elsewhere",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": "/somewhere/else/FPLAN-0001.md",
                    "location": str(other_path),
                },
            }
        }
        active, closed, total = mod._filter_branch_plans(registry, tmp_path)
        assert active == []
        assert closed == []
        assert total == 0

    def test_recently_closed_within_7_days(self, tmp_path):
        """Includes closed plans within the 7-day window."""
        mod = _import_mod()
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Recently closed",
                    "status": "closed",
                    "created": "2026-04-18",
                    "closed": recent_ts,
                    "file_path": str(tmp_path / "FPLAN-0001_recent.md"),
                    "location": str(tmp_path),
                },
            }
        }
        active, closed, total = mod._filter_branch_plans(registry, tmp_path)
        assert len(closed) == 1
        assert closed[0]["id"] == "FPLAN-0001"
        assert total == 1

    def test_excludes_old_closed_plans(self, tmp_path):
        """Excludes closed plans older than 7 days."""
        mod = _import_mod()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Old closed",
                    "status": "closed",
                    "created": "2026-03-01",
                    "closed": old_ts,
                    "file_path": str(tmp_path / "FPLAN-0001_old.md"),
                    "location": str(tmp_path),
                },
            }
        }
        active, closed, total = mod._filter_branch_plans(registry, tmp_path)
        assert len(closed) == 0
        assert total == 1

    def test_recently_closed_capped_at_5(self, tmp_path):
        """Recently closed list is limited to 5 entries."""
        mod = _import_mod()
        plans = {}
        for i in range(1, 9):
            ts = (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat()
            plans[f"FPLAN-{str(i).zfill(4)}"] = {
                "subject": f"Closed plan {i}",
                "status": "closed",
                "created": "2026-04-20",
                "closed": ts,
                "file_path": str(tmp_path / f"FPLAN-{str(i).zfill(4)}_closed_{i}.md"),
                "location": str(tmp_path),
            }
        registry = {"plans": plans}
        active, closed, total = mod._filter_branch_plans(registry, tmp_path)
        assert len(closed) == 5
        assert total == 8

    def test_unparseable_closed_timestamp_included_anyway(self, tmp_path):
        """Plans with unparseable closed timestamps are included anyway."""
        mod = _import_mod()
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Bad timestamp",
                    "status": "closed",
                    "created": "2026-04-20",
                    "closed": "not-a-date",
                    "file_path": str(tmp_path / "FPLAN-0001_bad_ts.md"),
                    "location": str(tmp_path),
                },
            }
        }
        active, closed, total = mod._filter_branch_plans(registry, tmp_path)
        assert len(closed) == 1
        assert closed[0]["closed"] == "not-a-date"

    def test_sorts_active_newest_first(self, tmp_path):
        """Active plans are sorted by created date, newest first."""
        mod = _import_mod()
        registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Oldest",
                    "status": "open",
                    "created": "2026-04-01",
                    "file_path": str(tmp_path / "FPLAN-0001_oldest.md"),
                    "location": str(tmp_path),
                },
                "FPLAN-0002": {
                    "subject": "Newest",
                    "status": "open",
                    "created": "2026-04-25",
                    "file_path": str(tmp_path / "FPLAN-0002_newest.md"),
                    "location": str(tmp_path),
                },
                "FPLAN-0003": {
                    "subject": "Middle",
                    "status": "open",
                    "created": "2026-04-15",
                    "file_path": str(tmp_path / "FPLAN-0003_middle.md"),
                    "location": str(tmp_path),
                },
            }
        }
        active, _, _ = mod._filter_branch_plans(registry, tmp_path)
        assert active[0]["subject"] == "Newest"
        assert active[1]["subject"] == "Middle"
        assert active[2]["subject"] == "Oldest"

    def test_extracts_plan_prefix_from_filepath(self, tmp_path):
        """Uses composite key as plan ID directly."""
        mod = _import_mod()
        registry = {
            "plans": {
                "DPLAN-0042": {
                    "subject": "Dev plan",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": str(tmp_path / "DPLAN-0042_dev_plan.md"),
                    "location": str(tmp_path),
                },
            }
        }
        active, _, _ = mod._filter_branch_plans(registry, tmp_path)
        assert active[0]["id"] == "DPLAN-0042"


# ═══════════════════════════════════════════════════════════
# 7. _build_section_data
# ═══════════════════════════════════════════════════════════


class TestBuildSectionData:
    """Tests for _build_section_data."""

    def test_builds_correct_structure(self):
        """Returns section dict with all expected keys."""
        mod = _import_mod()
        active = [{"id": "FPLAN-0001", "subject": "Test"}]
        closed = [{"id": "FPLAN-0002", "subject": "Done"}]
        result = mod._build_section_data(active, closed, 10)

        assert result["managed_by"] == "flow"
        assert result["active_plans"] == active
        assert result["active_count"] == 1
        assert result["recently_closed"] == closed
        assert result["total_plans"] == 10

    def test_empty_lists(self):
        """Handles empty active and closed lists."""
        mod = _import_mod()
        result = mod._build_section_data([], [], 0)
        assert result["active_count"] == 0
        assert result["active_plans"] == []
        assert result["recently_closed"] == []
        assert result["total_plans"] == 0


# ═══════════════════════════════════════════════════════════
# 8. push_flow_to_branch_dashboard
# ═══════════════════════════════════════════════════════════


class TestPushFlowToBranchDashboard:
    """Tests for push_flow_to_branch_dashboard."""

    def test_returns_false_if_no_dashboard_exists(self, tmp_path):
        """Returns False when DASHBOARD.local.json does not exist."""
        mod = _import_mod()
        result = mod.push_flow_to_branch_dashboard(tmp_path)
        assert result is False

    def test_success_calls_log_operation(self, tmp_path, mock_json_handler):
        """Logs via json_handler on successful push."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps({"sections": {}}), encoding="utf-8")

        mock_registry = {"plans": {}, "next_number": 1}
        with patch.object(mod, "_load_registry", return_value=mock_registry):
            result = mod.push_flow_to_branch_dashboard(tmp_path)

        assert result is True
        mock_json_handler.assert_called_once()
        call_args = mock_json_handler.call_args
        assert call_args[0][0] == "branch_dashboard_pushed"
        assert call_args[0][1]["success"] is True

    def test_orchestrates_full_pipeline(self, tmp_path, mock_json_handler):
        """Main handler calls load, filter, build, write in sequence."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps({"sections": {}}), encoding="utf-8")

        mock_registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Active plan",
                    "status": "open",
                    "created": "2026-04-20",
                    "file_path": str(tmp_path / "FPLAN-0001_active.md"),
                    "location": str(tmp_path),
                },
            },
            "next_number": 2,
        }
        with patch.object(mod, "_load_registry", return_value=mock_registry):
            result = mod.push_flow_to_branch_dashboard(tmp_path)

        assert result is True
        updated = json.loads(dashboard_path.read_text(encoding="utf-8"))
        flow_section = updated["sections"]["flow"]
        assert flow_section["active_count"] == 1
        assert flow_section["active_plans"][0]["id"] == "FPLAN-0001"

    def test_push_preserves_another_services_todo_count(self, tmp_path, mock_json_handler):
        """End-to-end: closing a plan must not wipe @prax's todo_count off the card."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(
            json.dumps(
                {
                    "sections": {"ai_mail": {"managed_by": "ai_mail", "new": 0}},
                    "quick_status": {
                        "new_mail": 0,
                        "opened_mail": 0,
                        "active_plans": 1,
                        "todo_count": 10,
                        "action_required": True,
                        "summary": "1 active plans, 10 todos",
                    },
                }
            ),
            encoding="utf-8",
        )

        # Registry says the branch's last plan just closed — active drops to zero.
        mock_registry = {
            "plans": {
                "FPLAN-0001": {
                    "subject": "Closed plan",
                    "status": "closed",
                    "closed": datetime.now(timezone.utc).isoformat(),
                    "file_path": str(tmp_path / "FPLAN-0001_closed.md"),
                    "location": str(tmp_path),
                },
            },
            "next_number": 2,
        }
        with patch.object(mod, "_load_registry", return_value=mock_registry):
            result = mod.push_flow_to_branch_dashboard(tmp_path)

        assert result is True
        quick = json.loads(dashboard_path.read_text(encoding="utf-8"))["quick_status"]
        assert quick["active_plans"] == 0, "our own key must be recomputed"
        assert quick["todo_count"] == 10, "foreign key was clobbered by the flow push"
        assert quick["action_required"] is True, "10 todos still need attention"
        assert quick["summary"] == "10 todos"

    def test_returns_false_on_exception(self, tmp_path):
        """Returns False when an exception occurs in the main handler."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps({"sections": {}}), encoding="utf-8")

        with patch.object(mod, "_load_registry", side_effect=RuntimeError("registry exploded")):
            result = mod.push_flow_to_branch_dashboard(tmp_path)

        assert result is False

    def test_returns_false_when_write_section_fails(self, tmp_path):
        """Returns False when _write_dashboard_section fails."""
        mod = _import_mod()
        dashboard_path = tmp_path / "DASHBOARD.local.json"
        dashboard_path.write_text(json.dumps({"sections": {}}), encoding="utf-8")

        mock_registry = {"plans": {}, "next_number": 1}
        with (
            patch.object(mod, "_load_registry", return_value=mock_registry),
            patch.object(mod, "_write_dashboard_section", return_value=False),
        ):
            result = mod.push_flow_to_branch_dashboard(tmp_path)

        assert result is False
