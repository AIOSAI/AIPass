"""Tests for plan display handler -- formatting and display functions."""


# ─── Helpers ─────────────────────────────────────────────


def _import(name: str):
    """Import a function from display module inside test scope."""
    import aipass.flow.apps.handlers.plan.display as mod

    return getattr(mod, name)


# ═══════════════════════════════════════════════════════════
# 1. display_plan_created
# ═══════════════════════════════════════════════════════════


class TestDisplayPlanCreated:
    def test_basic_output(self):
        fn = _import("display_plan_created")
        result = fn(plan_num=1, relative_location="flow", subject="My plan", template_type="default")
        assert "FPLAN-0001" in result
        assert "flow" in result
        assert "My plan" in result
        assert "default" in result

    def test_custom_prefix_and_digits(self):
        fn = _import("display_plan_created")
        result = fn(
            plan_num=42, relative_location="dev", subject="Dev plan", template_type="sprint", prefix="DPLAN", digits=6
        )
        assert "DPLAN-000042" in result
        assert "dev" in result

    def test_multiline_format(self):
        fn = _import("display_plan_created")
        result = fn(plan_num=5, relative_location="flow", subject="Test", template_type="default")
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("[FLOW]")
        assert "Template:" in lines[1]
        assert "Subject:" in lines[2]

    def test_large_plan_number(self):
        fn = _import("display_plan_created")
        result = fn(plan_num=9999, relative_location="flow", subject="Big", template_type="default")
        assert "FPLAN-9999" in result

    def test_plan_number_zero_padded(self):
        fn = _import("display_plan_created")
        result = fn(plan_num=7, relative_location="flow", subject="Pad test", template_type="default")
        assert "FPLAN-0007" in result


# ═══════════════════════════════════════════════════════════
# 2. display_plan_result
# ═══════════════════════════════════════════════════════════


class TestDisplayPlanResult:
    def test_success_result(self):
        fn = _import("display_plan_result")
        result = fn(success=True, plan_num=3, location="flow", template_type="default", error="")
        assert "[green]" in result
        assert "FPLAN-0003" in result
        assert "default template" in result

    def test_failure_result(self):
        fn = _import("display_plan_result")
        result = fn(success=False, plan_num=0, location="", template_type="", error="Something broke")
        assert "[red]" in result
        assert "Something broke" in result

    def test_custom_prefix_success(self):
        fn = _import("display_plan_result")
        result = fn(
            success=True, plan_num=10, location="dev", template_type="sprint", error="", prefix="DPLAN", digits=6
        )
        assert "DPLAN-000010" in result

    def test_failure_ignores_plan_details(self):
        fn = _import("display_plan_result")
        result = fn(success=False, plan_num=99, location="flow", template_type="default", error="disk full")
        assert "FPLAN" not in result
        assert "disk full" in result


# ═══════════════════════════════════════════════════════════
# 3. format_plan_deletion_header
# ═══════════════════════════════════════════════════════════


class TestFormatPlanDeletionHeader:
    def test_basic_header(self):
        fn = _import("format_plan_deletion_header")
        plan_info = {
            "relative_path": "flow",
            "subject": "Test subject",
            "status": "open",
            "file_path": "/tmp/FPLAN-0001.md",
        }
        result = fn("0001", plan_info)
        assert "Close FPLAN-0001" in result
        assert "Test subject" in result
        assert "flow" in result
        assert "open" in result

    def test_custom_prefix(self):
        fn = _import("format_plan_deletion_header")
        result = fn("0005", {"file_path": ""}, prefix="DPLAN")
        assert "Close DPLAN-0005" in result

    def test_missing_fields_use_defaults(self):
        fn = _import("format_plan_deletion_header")
        result = fn("0010", {"file_path": ""})
        assert "unknown" in result
        assert "N/A" in result


# ═══════════════════════════════════════════════════════════
# 4. format_plan_error
# ═══════════════════════════════════════════════════════════


class TestFormatPlanError:
    def test_not_found(self):
        fn = _import("format_plan_error")
        result = fn("not_found", plan_num="0001")
        assert "FPLAN-0001 not found" in result

    def test_invalid_number(self):
        fn = _import("format_plan_error")
        result = fn("invalid_number", plan_num="abc")
        assert "Invalid plan number: abc" in result

    def test_general_error(self):
        fn = _import("format_plan_error")
        result = fn("general", details="disk is full")
        assert "disk is full" in result

    def test_unknown_error_type(self):
        fn = _import("format_plan_error")
        result = fn("bogus_type")
        assert "Unknown error" in result

    def test_custom_prefix(self):
        fn = _import("format_plan_error")
        result = fn("not_found", plan_num="0002", prefix="DPLAN")
        assert "DPLAN-0002 not found" in result


# ═══════════════════════════════════════════════════════════
# 5. format_plan_deletion_success
# ═══════════════════════════════════════════════════════════


class TestFormatPlanDeletionSuccess:
    def test_default_prefix(self):
        fn = _import("format_plan_deletion_success")
        result = fn("0001")
        assert "FPLAN-0001 closed successfully" in result

    def test_custom_prefix(self):
        fn = _import("format_plan_deletion_success")
        result = fn("0003", prefix="DPLAN")
        assert "DPLAN-0003 closed successfully" in result


# ═══════════════════════════════════════════════════════════
# 6. format_deletion_cancelled
# ═══════════════════════════════════════════════════════════


class TestFormatDeletionCancelled:
    def test_output(self):
        fn = _import("format_deletion_cancelled")
        assert fn() == "Deletion cancelled"


# ═══════════════════════════════════════════════════════════
# 7. format_delete_usage_error
# ═══════════════════════════════════════════════════════════


class TestFormatDeleteUsageError:
    def test_contains_usage_instructions(self):
        fn = _import("format_delete_usage_error")
        result = fn()
        assert "Plan number required" in result
        assert "Usage:" in result
        assert "delete" in result


# ═══════════════════════════════════════════════════════════
# 8. format_restore_header
# ═══════════════════════════════════════════════════════════


class TestFormatRestoreHeader:
    def test_basic_header(self):
        fn = _import("format_restore_header")
        plan_info = {
            "relative_path": "flow",
            "subject": "Restore me",
            "status": "closed",
            "file_path": "/tmp/FPLAN-0001.md",
            "closed": "2026-03-19",
            "closed_reason": "completed",
        }
        result = fn("0001", plan_info)
        assert "Restore FPLAN-0001" in result
        assert "Restore me" in result
        assert "closed" in result
        assert "2026-03-19" in result
        assert "completed" in result

    def test_missing_close_fields(self):
        fn = _import("format_restore_header")
        result = fn("0002", {"file_path": ""})
        assert "unknown" in result
        assert "N/A" in result

    def test_custom_prefix(self):
        fn = _import("format_restore_header")
        result = fn("0003", {"file_path": ""}, prefix="DPLAN")
        assert "Restore DPLAN-0003" in result


# ═══════════════════════════════════════════════════════════
# 9. format_restore_success
# ═══════════════════════════════════════════════════════════


class TestFormatRestoreSuccess:
    def test_with_location(self):
        fn = _import("format_restore_success")
        result = fn("0001", restored_location="/home/user/plans")
        assert "FPLAN-0001 restored" in result
        assert "/home/user/plans" in result

    def test_without_location(self):
        fn = _import("format_restore_success")
        result = fn("0001")
        assert "FPLAN-0001 restored to open status" in result
        assert "at:" not in result

    def test_custom_prefix(self):
        fn = _import("format_restore_success")
        result = fn("0005", prefix="DPLAN")
        assert "DPLAN-0005" in result


# ═══════════════════════════════════════════════════════════
# 10. format_restore_error
# ═══════════════════════════════════════════════════════════


class TestFormatRestoreError:
    def test_not_found(self):
        fn = _import("format_restore_error")
        assert "not found" in fn("not_found", plan_key="0001")

    def test_already_open(self):
        fn = _import("format_restore_error")
        result = fn("already_open", plan_key="0001")
        assert "already open" in result

    def test_file_missing(self):
        fn = _import("format_restore_error")
        result = fn("file_missing", plan_key="0001")
        assert "file not found" in result

    def test_invalid_number(self):
        fn = _import("format_restore_error")
        result = fn("invalid_number", plan_key="xyz")
        assert "Invalid plan number: xyz" in result

    def test_general(self):
        fn = _import("format_restore_error")
        result = fn("general", details="timeout")
        assert "timeout" in result

    def test_unknown_type(self):
        fn = _import("format_restore_error")
        assert "Unknown error" in fn("something_else")


# ═══════════════════════════════════════════════════════════
# 11. format_restore_usage_error
# ═══════════════════════════════════════════════════════════


class TestFormatRestoreUsageError:
    def test_contains_usage(self):
        fn = _import("format_restore_usage_error")
        result = fn()
        assert "Plan number required" in result
        assert "restore" in result


# ═══════════════════════════════════════════════════════════
# 12. format_plan_info
# ═══════════════════════════════════════════════════════════


class TestFormatPlanInfo:
    def test_basic_plan_info(self):
        fn = _import("format_plan_info")
        plan_info = {
            "subject": "My plan",
            "relative_path": "flow",
            "status": "open",
            "created": "2026-03-20T10:30:00Z",
        }
        result = fn("0001", plan_info)
        assert "FPLAN-0001" in result
        assert "My plan" in result
        assert "open" in result
        assert "2026-03-20" in result

    def test_source_prefix_override(self):
        fn = _import("format_plan_info")
        plan_info = {
            "subject": "Dev plan",
            "relative_path": "dev",
            "status": "open",
            "created": "unknown",
            "_source_prefix": "DPLAN",
        }
        result = fn("0001", plan_info, prefix="FPLAN")
        assert "DPLAN-0001" in result
        assert "FPLAN" not in result

    def test_plan_num_override(self):
        fn = _import("format_plan_info")
        plan_info = {
            "subject": "Test",
            "relative_path": "flow",
            "status": "open",
            "created": "unknown",
            "_plan_num": "0099",
        }
        result = fn("0001", plan_info)
        assert "0099" in result

    def test_missing_fields_use_defaults(self):
        fn = _import("format_plan_info")
        result = fn("0001", {})
        assert "No subject" in result
        assert "unknown" in result

    def test_invalid_date_falls_back(self):
        fn = _import("format_plan_info")
        plan_info = {
            "subject": "Bad date",
            "relative_path": "flow",
            "status": "open",
            "created": "not-a-date",
        }
        result = fn("0001", plan_info)
        assert "not-a-date" in result


# ═══════════════════════════════════════════════════════════
# 13. format_plans_list
# ═══════════════════════════════════════════════════════════


class TestFormatPlansList:
    def test_empty_plans(self):
        fn = _import("format_plans_list")
        result = fn({})
        assert "No plans found" in result

    def test_filter_returns_empty(self):
        fn = _import("format_plans_list")
        plans = {
            "0001": {"status": "open", "subject": "Test", "relative_path": "flow", "created": "unknown"},
        }
        result = fn(plans, filter_status="closed")
        assert "No closed plans found" in result

    def test_with_plans_shows_header(self):
        fn = _import("format_plans_list")
        plans = {
            "0001": {"status": "open", "subject": "Alpha", "relative_path": "flow", "created": "unknown"},
            "0002": {"status": "closed", "subject": "Beta", "relative_path": "flow", "created": "unknown"},
        }
        result = fn(plans, show_header=True)
        assert "PLAN Registry" in result
        assert "Alpha" in result
        assert "Beta" in result

    def test_filter_open_only(self):
        fn = _import("format_plans_list")
        plans = {
            "0001": {"status": "open", "subject": "Alpha", "relative_path": "flow", "created": "unknown"},
            "0002": {"status": "closed", "subject": "Beta", "relative_path": "flow", "created": "unknown"},
        }
        result = fn(plans, filter_status="open")
        assert "Alpha" in result
        assert "Beta" not in result

    def test_no_header(self):
        fn = _import("format_plans_list")
        plans = {
            "0001": {"status": "open", "subject": "Alpha", "relative_path": "flow", "created": "unknown"},
        }
        result = fn(plans, show_header=False)
        assert "PLAN Registry" not in result
        assert "Alpha" in result

    def test_sorted_by_key(self):
        fn = _import("format_plans_list")
        plans = {
            "0003": {"status": "open", "subject": "Third", "relative_path": "flow", "created": "unknown"},
            "0001": {"status": "open", "subject": "First", "relative_path": "flow", "created": "unknown"},
        }
        result = fn(plans, show_header=False)
        first_pos = result.index("First")
        third_pos = result.index("Third")
        assert first_pos < third_pos


# ═══════════════════════════════════════════════════════════
# 14. format_statistics_summary
# ═══════════════════════════════════════════════════════════


class TestFormatStatisticsSummary:
    def test_basic_stats(self):
        fn = _import("format_statistics_summary")
        stats = {"total_plans": 10, "open_plans": 7, "closed_plans": 3, "other_plans": 0}
        result = fn(stats)
        assert "Total plans: 10" in result
        assert "Open: 7" in result
        assert "Closed: 3" in result
        assert "Other" not in result

    def test_with_other_plans(self):
        fn = _import("format_statistics_summary")
        stats = {"total_plans": 10, "open_plans": 5, "closed_plans": 3, "other_plans": 2}
        result = fn(stats)
        assert "Other: 2" in result
