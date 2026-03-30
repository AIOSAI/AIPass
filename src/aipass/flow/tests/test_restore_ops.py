"""Tests for restore_ops handler -- plan restore business logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ─── Helpers ─────────────────────────────────────────────

def _import_restore_plan_impl():
    """Import restore_plan_impl inside test scope."""
    from aipass.flow.apps.handlers.plan.restore_ops import restore_plan_impl
    return restore_plan_impl


def _import_recover_plan_from_backup():
    """Import recover_plan_from_backup inside test scope."""
    from aipass.flow.apps.handlers.plan.restore_ops import recover_plan_from_backup
    return recover_plan_from_backup


def _make_deps(**overrides):
    """Build a default set of injected dependencies, with optional overrides."""
    deps = {
        "normalize_plan_number": MagicMock(side_effect=lambda x: x.zfill(4)),
        "load_registry": MagicMock(return_value={
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": "/tmp/FPLAN-0001.md",
                    "location": "/tmp",
                    "relative_path": "flow",
                    "subject": "Test plan",
                    "closed": "2026-03-19",
                    "closed_reason": "completed",
                    "memory_created": True,
                    "memory_created_date": "2026-03-19",
                    "memory_file": "/tmp/memory.md",
                },
            }
        }),
        "save_registry": MagicMock(),
        "validate_plan_exists": MagicMock(return_value=(True, "")),
        "recover_plan_from_backup_fn": MagicMock(return_value=(False, "not found")),
        "scan_plan_files": MagicMock(),
        "update_dashboard_local": MagicMock(return_value=True),
        "push_to_plans_central": MagicMock(return_value=True),
    }
    deps.update(overrides)
    return deps


# ═══════════════════════════════════════════════════════════
# 1. restore_plan_impl -- no plan number
# ═══════════════════════════════════════════════════════════

class TestRestoreNoPlanNumber:

    def test_none_returns_error(self):
        fn = _import_restore_plan_impl()
        result = fn(plan_num=None, **_make_deps())
        assert result["success"] is False
        assert result["messages"][0]["error_type"] == "invalid_number"

    def test_empty_string_returns_error(self):
        fn = _import_restore_plan_impl()
        result = fn(plan_num="", **_make_deps())
        assert result["success"] is False


# ═══════════════════════════════════════════════════════════
# 2. restore_plan_impl -- success path
# ═══════════════════════════════════════════════════════════

class TestRestoreSuccess:

    def test_successful_restore(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        registry = {
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Test plan",
                    "closed": "2026-03-19",
                    "closed_reason": "completed",
                },
            }
        }
        deps = _make_deps(load_registry=MagicMock(return_value=registry))

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            result = fn(plan_num="1", **deps)

        assert result["success"] is True
        assert result["plan_key"] == "0001"
        assert result["restored_location"] == str(tmp_path)

    def test_registry_saved_after_restore(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        registry = {
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Test",
                    "closed": "2026-03-19",
                    "closed_reason": "done",
                },
            }
        }
        save_mock = MagicMock()
        deps = _make_deps(load_registry=MagicMock(return_value=registry), save_registry=save_mock)

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            fn(plan_num="1", **deps)

        save_mock.assert_called_once()
        saved = save_mock.call_args[0][0]
        assert saved["plans"]["0001"]["status"] == "open"
        assert "closed" not in saved["plans"]["0001"]
        assert "closed_reason" not in saved["plans"]["0001"]
        assert "memory_created" not in saved["plans"]["0001"]

    def test_scan_plan_files_called(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        registry = {
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Test",
                },
            }
        }
        scan_mock = MagicMock()
        deps = _make_deps(load_registry=MagicMock(return_value=registry), scan_plan_files=scan_mock)

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            fn(plan_num="1", **deps)

        scan_mock.assert_called_once()

    def test_messages_contain_header_and_success(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        registry = {
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Test",
                },
            }
        }
        deps = _make_deps(load_registry=MagicMock(return_value=registry))

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            result = fn(plan_num="1", **deps)

        types = [m["type"] for m in result["messages"]]
        assert "restore_header" in types
        assert "restore_success" in types


# ═══════════════════════════════════════════════════════════
# 3. restore_plan_impl -- plan already open
# ═══════════════════════════════════════════════════════════

class TestRestoreAlreadyOpen:

    def test_open_plan_returns_error(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        registry = {
            "plans": {
                "0001": {
                    "status": "open",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Already open",
                },
            }
        }
        deps = _make_deps(load_registry=MagicMock(return_value=registry))
        result = fn(plan_num="1", **deps)

        assert result["success"] is False
        assert any(m.get("error_type") == "already_open" for m in result["messages"])


# ═══════════════════════════════════════════════════════════
# 4. restore_plan_impl -- plan not found + recovery
# ═══════════════════════════════════════════════════════════

class TestRestoreNotFound:

    def test_not_found_no_backup(self):
        fn = _import_restore_plan_impl()
        deps = _make_deps(
            validate_plan_exists=MagicMock(return_value=(False, "not found")),
            recover_plan_from_backup_fn=MagicMock(return_value=(False, "no backup")),
        )
        result = fn(plan_num="9999", **deps)

        assert result["success"] is False
        assert any(m.get("error_type") == "not_found" for m in result["messages"])

    def test_not_found_but_recovered(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-9999.md"
        plan_file.write_text("# Recovered", encoding="utf-8")

        recovered_registry = {
            "plans": {
                "9999": {
                    "status": "closed",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Recovered from backup",
                    "closed": "2026-03-19",
                    "closed_reason": "recovered_from_backup",
                },
            }
        }
        load_mock = MagicMock(side_effect=[
            {"plans": {}},  # first load: empty
            recovered_registry,  # second load: after recovery
        ])
        deps = _make_deps(
            validate_plan_exists=MagicMock(return_value=(False, "not found")),
            recover_plan_from_backup_fn=MagicMock(return_value=(True, "Recovered FPLAN-9999")),
            load_registry=load_mock,
        )

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            result = fn(plan_num="9999", **deps)

        assert result["success"] is True
        assert any(m.get("type") == "success" for m in result["messages"])


# ═══════════════════════════════════════════════════════════
# 5. restore_plan_impl -- file missing
# ═══════════════════════════════════════════════════════════

class TestRestoreFileMissing:

    def test_file_not_at_location(self):
        fn = _import_restore_plan_impl()
        registry = {
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": "/nonexistent/path/FPLAN-0001.md",
                    "location": "/nonexistent/path",
                    "relative_path": "flow",
                    "subject": "Missing file",
                },
            }
        }
        deps = _make_deps(load_registry=MagicMock(return_value=registry))
        result = fn(plan_num="1", **deps)

        assert result["success"] is False
        assert any(m.get("error_type") == "file_missing" for m in result["messages"])


# ═══════════════════════════════════════════════════════════
# 6. restore_plan_impl -- ValueError (invalid number)
# ═══════════════════════════════════════════════════════════

class TestRestoreValueError:

    def test_invalid_plan_number_raises_value_error(self):
        fn = _import_restore_plan_impl()
        deps = _make_deps(
            normalize_plan_number=MagicMock(side_effect=ValueError("bad number")),
        )
        result = fn(plan_num="abc", **deps)

        assert result["success"] is False
        assert result["messages"][0]["error_type"] == "invalid_number"

    def test_plan_key_is_original_input_on_value_error(self):
        fn = _import_restore_plan_impl()
        deps = _make_deps(
            normalize_plan_number=MagicMock(side_effect=ValueError("bad")),
        )
        result = fn(plan_num="xyz", **deps)
        assert result["messages"][0]["plan_key"] == "xyz"


# ═══════════════════════════════════════════════════════════
# 7. restore_plan_impl -- generic exception
# ═══════════════════════════════════════════════════════════

class TestRestoreGenericException:

    def test_unexpected_error(self):
        fn = _import_restore_plan_impl()
        deps = _make_deps(
            scan_plan_files=MagicMock(side_effect=RuntimeError("kaboom")),
        )
        result = fn(plan_num="1", **deps)

        assert result["success"] is False
        assert result["messages"][0]["error_type"] == "general"
        assert "kaboom" in result["messages"][0]["details"]


# ═══════════════════════════════════════════════════════════
# 8. restore_plan_impl -- dashboard failures
# ═══════════════════════════════════════════════════════════

class TestRestoreDashboardFailures:

    def test_dashboard_failure_does_not_block_success(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        registry = {
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Test",
                },
            }
        }
        deps = _make_deps(
            load_registry=MagicMock(return_value=registry),
            update_dashboard_local=MagicMock(return_value=False),
            push_to_plans_central=MagicMock(return_value=False),
        )

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            result = fn(plan_num="1", **deps)

        assert result["success"] is True

    def test_central_failure_does_not_block_success(self, tmp_path):
        fn = _import_restore_plan_impl()
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        registry = {
            "plans": {
                "0001": {
                    "status": "closed",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Test",
                },
            }
        }
        deps = _make_deps(
            load_registry=MagicMock(return_value=registry),
            push_to_plans_central=MagicMock(return_value=False),
        )

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            result = fn(plan_num="1", **deps)

        assert result["success"] is True


# ═══════════════════════════════════════════════════════════
# 9. recover_plan_from_backup
# ═══════════════════════════════════════════════════════════

class TestRecoverPlanFromBackup:

    def test_no_backup_dir(self):
        fn = _import_recover_plan_from_backup()
        load = MagicMock(return_value={"plans": {}})
        save = MagicMock()

        with patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", Path("/nonexistent_dir_xyz")):
            ok, msg = fn("9999", load_registry=load, save_registry=save)

        assert ok is False
        assert "not found" in msg

    def test_successful_recovery(self, tmp_path):
        fn = _import_recover_plan_from_backup()

        # Create backup file with Location header
        backup_dir = tmp_path / "processed_plans"
        backup_dir.mkdir()
        backup_file = backup_dir / "FPLAN-0042.md"
        backup_file.write_text("# Plan\n**Location**: " + str(tmp_path) + "\n\nContent here", encoding="utf-8")

        registry = {"plans": {}}
        load = MagicMock(return_value=registry)
        save = MagicMock()

        with patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir), \
             patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path), \
             patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", tmp_path / "flow"):
            ok, msg = fn("0042", load_registry=load, save_registry=save)

        assert ok is True
        assert "Recovered" in msg
        save.assert_called_once()
        saved_reg = save.call_args[0][0]
        assert "0042" in saved_reg["plans"]
        assert saved_reg["plans"]["0042"]["status"] == "closed"

    def test_recovery_without_location_header(self, tmp_path):
        fn = _import_recover_plan_from_backup()

        backup_dir = tmp_path / "processed_plans"
        backup_dir.mkdir()
        backup_file = backup_dir / "FPLAN-0010.md"
        backup_file.write_text("# Plan\nNo location header here\n", encoding="utf-8")

        flow_root = tmp_path / "flow"
        flow_root.mkdir()

        registry = {"plans": {}}
        load = MagicMock(return_value=registry)
        save = MagicMock()

        with patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir), \
             patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path), \
             patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", flow_root):
            ok, msg = fn("0010", load_registry=load, save_registry=save)

        assert ok is True
        # Should default to FLOW_ROOT
        saved_reg = save.call_args[0][0]
        assert saved_reg["plans"]["0010"]["location"] == str(flow_root)

    def test_picks_newest_variant(self, tmp_path):
        fn = _import_recover_plan_from_backup()

        backup_dir = tmp_path / "processed_plans"
        backup_dir.mkdir()

        # Create two variants - older FPLAN, newer DPLAN
        old_file = backup_dir / "FPLAN-0005.md"
        old_file.write_text("# Old\n**Location**: " + str(tmp_path) + "\n", encoding="utf-8")

        import time
        time.sleep(0.05)

        new_file = backup_dir / "DPLAN-0005.md"
        new_file.write_text("# New\n**Location**: " + str(tmp_path) + "\n", encoding="utf-8")

        registry = {"plans": {}}
        load = MagicMock(return_value=registry)
        save = MagicMock()

        with patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir), \
             patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path), \
             patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", tmp_path / "flow"):
            ok, msg = fn("0005", load_registry=load, save_registry=save)

        assert ok is True
        assert "DPLAN-0005" in msg
