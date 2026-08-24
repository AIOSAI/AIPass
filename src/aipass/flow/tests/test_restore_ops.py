"""Tests for restore_ops handler -- plan restore business logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch


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
        "load_registry": MagicMock(
            return_value={
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
            }
        ),
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

        # registry_file-keyed responses -- only fplan_registry.json has the
        # recovered plan; every other type's registry is empty. Emulates the
        # real load_registry() contract (routes on registry_file, not call order).
        def load_side_effect(registry_file=None):
            return recovered_registry if registry_file == "fplan_registry.json" else {"plans": {}}

        load_mock = MagicMock(side_effect=load_side_effect)
        deps = _make_deps(
            validate_plan_exists=MagicMock(return_value=(False, "not found")),
            recover_plan_from_backup_fn=MagicMock(return_value=(True, "Recovered FPLAN-9999")),
            load_registry=load_mock,
        )

        # The no-prefix fallback discovers plan types from flow_json/
        # template_registry.json — a runtime-managed (gitignored) file that
        # doesn't exist on fresh checkouts/CI. Pin the discovery so this
        # test never depends on the machine's live registry state.
        with (
            patch(
                "aipass.flow.apps.handlers.plan.registry_routing._load_template_registry",
                return_value={"types": {"flow_plans": {"prefix": "FPLAN"}}},
            ),
            patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True),
        ):
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
# 9. restore_plan_impl -- cross-type same-number collision (VERA repro)
# ═══════════════════════════════════════════════════════════


class TestRestoreCrossTypeCollision:
    """Regression coverage for the reported bug: `restore PPLAN-0011` must
    never resolve against FPLAN-0011 just because both share number 0011."""

    def _registries(self, tmp_path):
        fplan_file = tmp_path / "FPLAN-0011.md"
        fplan_file.write_text("# FPLAN", encoding="utf-8")
        pplan_file = tmp_path / "PPLAN-0011.md"
        pplan_file.write_text("# PPLAN", encoding="utf-8")

        fplan_registry = {
            "plans": {
                "0011": {
                    "status": "open",  # already open -- would error if wrongly matched
                    "file_path": str(fplan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Unrelated FPLAN",
                },
            }
        }
        pplan_registry = {
            "plans": {
                "0011": {
                    "status": "closed",
                    "file_path": str(pplan_file),
                    "location": str(tmp_path),
                    "relative_path": "flow",
                    "subject": "Weekly update playbook run",
                    "closed": "2026-07-20",
                    "closed_reason": "completed",
                },
            }
        }
        return fplan_registry, pplan_registry

    def test_explicit_prefix_restores_correct_type(self, tmp_path):
        fn = _import_restore_plan_impl()
        from aipass.flow.apps.handlers.plan.validator import (
            normalize_plan_number as real_normalize,
            validate_plan_exists as real_validate,
        )

        fplan_registry, pplan_registry = self._registries(tmp_path)
        registries = {"fplan_registry.json": fplan_registry, "pplan_registry.json": pplan_registry}
        load_mock = MagicMock(side_effect=lambda registry_file="": registries[registry_file])
        save_mock = MagicMock()

        deps = _make_deps(
            normalize_plan_number=real_normalize,
            validate_plan_exists=real_validate,
            load_registry=load_mock,
            save_registry=save_mock,
        )

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            result = fn(plan_num="PPLAN-0011", **deps)

        assert result["success"] is True
        assert result["plan_key"] == "0011"
        # Never touched the unrelated FPLAN-0011 entry
        assert fplan_registry["plans"]["0011"]["status"] == "open"
        save_mock.assert_called_once()
        saved_registry = save_mock.call_args[0][0]
        assert save_mock.call_args[1].get("registry_file") == "pplan_registry.json"
        assert saved_registry["plans"]["0011"]["status"] == "open"

    def test_explicit_prefix_does_not_fall_back_to_other_type(self, tmp_path):
        """If PPLAN-0011 doesn't exist but FPLAN-0011 does, restore must fail
        outright -- never silently restore the FPLAN entry instead."""
        fn = _import_restore_plan_impl()
        from aipass.flow.apps.handlers.plan.validator import (
            normalize_plan_number as real_normalize,
            validate_plan_exists as real_validate,
        )

        fplan_registry, _ = self._registries(tmp_path)
        registries = {"fplan_registry.json": fplan_registry, "pplan_registry.json": {"plans": {}}}
        load_mock = MagicMock(side_effect=lambda registry_file="": registries[registry_file])

        deps = _make_deps(
            normalize_plan_number=real_normalize,
            validate_plan_exists=real_validate,
            load_registry=load_mock,
            recover_plan_from_backup_fn=MagicMock(return_value=(False, "no backup")),
        )

        result = fn(plan_num="PPLAN-0011", **deps)

        assert result["success"] is False
        assert any(m.get("error_type") == "not_found" for m in result["messages"])
        assert any(m.get("prefix") == "PPLAN" for m in result["messages"])

    def test_restore_success_message_carries_resolved_type_prefix(self, tmp_path):
        """Display messages must reflect the plan's real type, not a silent
        'FPLAN' default -- otherwise a restored PPLAN prints as 'FPLAN-0011'."""
        fn = _import_restore_plan_impl()
        from aipass.flow.apps.handlers.plan.validator import (
            normalize_plan_number as real_normalize,
            validate_plan_exists as real_validate,
        )

        _, pplan_registry = self._registries(tmp_path)
        registries = {"pplan_registry.json": pplan_registry}
        load_mock = MagicMock(side_effect=lambda registry_file="": registries[registry_file])

        deps = _make_deps(
            normalize_plan_number=real_normalize,
            validate_plan_exists=real_validate,
            load_registry=load_mock,
            save_registry=MagicMock(),
        )

        with patch("aipass.flow.apps.handlers.plan.restore_ops.trigger", create=True):
            result = fn(plan_num="PPLAN-0011", **deps)

        header = next(m for m in result["messages"] if m["type"] == "restore_header")
        success = next(m for m in result["messages"] if m["type"] == "restore_success")
        assert header["prefix"] == "PPLAN"
        assert success["prefix"] == "PPLAN"


# ═══════════════════════════════════════════════════════════
# 10. recover_plan_from_backup
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

        with (
            patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir),
            patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path),
            patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", tmp_path / "flow"),
        ):
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

        with (
            patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir),
            patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path),
            patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", flow_root),
        ):
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

        with (
            patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir),
            patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path),
            patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", tmp_path / "flow"),
        ):
            ok, msg = fn("0005", load_registry=load, save_registry=save)

        assert ok is True
        assert "DPLAN-0005" in msg

    def test_no_prefix_writes_to_registry_matching_recovered_file(self, tmp_path):
        """Even without an explicit prefix, the entry must land in the
        registry matching the RECOVERED file's actual type (DPLAN here),
        never the default fplan_registry.json."""
        fn = _import_recover_plan_from_backup()

        backup_dir = tmp_path / "processed_plans"
        backup_dir.mkdir()
        backup_file = backup_dir / "DPLAN-0005.md"
        backup_file.write_text("# Plan\n**Location**: " + str(tmp_path) + "\n", encoding="utf-8")

        registry = {"plans": {}}
        load = MagicMock(return_value=registry)
        save = MagicMock()

        with (
            patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir),
            patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path),
            patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", tmp_path / "flow"),
        ):
            ok, msg = fn("0005", load_registry=load, save_registry=save)

        assert ok is True
        load.assert_called_once_with(registry_file="dplan_registry.json")
        save.assert_called_once()
        assert save.call_args[1].get("registry_file") == "dplan_registry.json"

    def test_explicit_prefix_restricts_search_to_matching_type(self, tmp_path):
        """A caller-specified prefix must not be overridden by a newer
        same-numbered backup from a different plan type."""
        fn = _import_recover_plan_from_backup()

        backup_dir = tmp_path / "processed_plans"
        backup_dir.mkdir()

        # Older FPLAN backup, requested explicitly
        fplan_backup = backup_dir / "FPLAN-0011.md"
        fplan_backup.write_text("# FPLAN\n**Location**: " + str(tmp_path) + "\n", encoding="utf-8")

        import time

        time.sleep(0.05)

        # Newer PPLAN backup with the SAME number -- must be ignored
        pplan_backup = backup_dir / "PPLAN-0011.md"
        pplan_backup.write_text("# PPLAN\n**Location**: " + str(tmp_path) + "\n", encoding="utf-8")

        registries = {}
        load = MagicMock(side_effect=lambda registry_file=None: registries.setdefault(registry_file, {"plans": {}}))
        save = MagicMock()

        with (
            patch("aipass.flow.apps.handlers.plan.restore_ops.PROCESSED_PLANS_DIR", backup_dir),
            patch("aipass.flow.apps.handlers.plan.restore_ops._PKG_ROOT", tmp_path),
            patch("aipass.flow.apps.handlers.plan.restore_ops.FLOW_ROOT", tmp_path / "flow"),
        ):
            ok, msg = fn("0011", plan_num_raw="FPLAN-0011", load_registry=load, save_registry=save)

        assert ok is True
        assert "FPLAN-0011" in msg
        save.assert_called_once()
        assert save.call_args[1].get("registry_file") == "fplan_registry.json"


# ═══════════════════════════════════════════════════════════
# 10. THE ARCHIVE IS THE SAFETY NET — restoring a normally-closed plan
#
# Measured on the live tree before writing any of this: 719 closed
# rows, 0 with a file at their registered path, 412 with an intact
# copy in the archive. Restore failed for all 719 because step 5
# checked one location and never looked at the other.
# ═══════════════════════════════════════════════════════════


def _import_find_backup_copy():
    from aipass.flow.apps.handlers.plan.restore_ops import find_backup_copy

    return find_backup_copy


def _import_restore_file_from_backup():
    from aipass.flow.apps.handlers.plan.restore_ops import restore_file_from_backup

    return restore_file_from_backup


def _closed_plan(tmp_path, name="FPLAN-0042_the_real_subject_2026-08-01.md"):
    """A plan closed the normal way: row intact, file archived out of the tree."""
    home = tmp_path / "src" / "aipass" / "somebranch"
    home.mkdir(parents=True)
    archive = tmp_path / ".backup" / "processed_plans"
    archive.mkdir(parents=True)
    (archive / name).write_text("# The plan\n\n**Location**: " + str(home) + "\n", encoding="utf-8")
    row = {
        "status": "closed",
        "file_path": str(home / name),
        "location": str(home),
        "relative_path": "somebranch",
        "subject": "The real subject",
        "created": "2026-08-01T00:00:00+00:00",
        "closed": "2026-08-20T00:00:00+00:00",
        "closed_reason": "completed",
    }
    return row, home, archive, name


class TestFindBackupCopy:
    def test_matches_the_rows_own_filename_slug_and_date_intact(self, tmp_path):
        find_backup_copy = _import_find_backup_copy()
        row, _home, archive, name = _closed_plan(tmp_path)

        found = find_backup_copy(row, "0042", backup_dir=archive)
        assert found is not None
        # Not a PREFIX-NNNN.md husk -- the name that carries the work.
        assert found.name == name
        assert "the_real_subject" in found.name and "2026-08-01" in found.name

    def test_glob_fallback_is_type_scoped(self, tmp_path):
        """Every registry numbers from 0001; a bare-number glob returns the wrong plan."""
        find_backup_copy = _import_find_backup_copy()
        row, _home, archive, _name = _closed_plan(tmp_path, "FPLAN-0011_wanted_2026-08-01.md")
        # Row points at a name that is NOT in the archive, forcing the fallback.
        row["file_path"] = str(tmp_path / "gone" / "FPLAN-0011_renamed_2026-08-01.md")
        (archive / "DPLAN-0011_decoy_2026-08-01.md").write_text("# decoy", encoding="utf-8")

        found = find_backup_copy(row, "0011", backup_dir=archive)
        assert found is not None
        assert found.name.startswith("FPLAN-0011")

    def test_row_without_type_evidence_is_not_globbed(self, tmp_path):
        find_backup_copy = _import_find_backup_copy()
        _row, _home, archive, _name = _closed_plan(tmp_path)
        assert find_backup_copy({"file_path": ""}, "0042", backup_dir=archive) is None

    def test_absent_archive_returns_none(self, tmp_path):
        find_backup_copy = _import_find_backup_copy()
        row, _home, _archive, _name = _closed_plan(tmp_path)
        assert find_backup_copy(row, "0042", backup_dir=tmp_path / "no_such_dir") is None


class TestRestoreFileFromBackup:
    def test_copies_back_and_preserves_the_archive(self, tmp_path):
        """COPY, not move -- a restore must be repeatable and must not consume the net."""
        restore_file_from_backup = _import_restore_file_from_backup()
        row, home, archive, name = _closed_plan(tmp_path)

        target, msg = restore_file_from_backup(row, "0042", backup_dir=archive)
        assert target == home / name
        assert target.is_file()
        assert (archive / name).is_file(), "archive copy was consumed"
        assert "restored" in msg

    def test_refuses_when_the_original_location_is_gone(self, tmp_path):
        restore_file_from_backup = _import_restore_file_from_backup()
        row, home, archive, _name = _closed_plan(tmp_path)
        import shutil

        shutil.rmtree(home)

        target, msg = restore_file_from_backup(row, "0042", backup_dir=archive)
        assert target is None
        assert "no longer exists" in msg

    def test_reports_plainly_when_nothing_is_archived(self, tmp_path):
        restore_file_from_backup = _import_restore_file_from_backup()
        row, _home, archive, name = _closed_plan(tmp_path)
        (archive / name).unlink()

        target, msg = restore_file_from_backup(row, "0042", backup_dir=archive)
        assert target is None
        assert "no archived copy" in msg


class TestRestoreOfANormallyClosedPlan:
    """The end-to-end claim: 'every closed plan is recoverable'."""

    def test_closed_plan_with_an_archived_copy_restores(self, tmp_path):
        fn = _import_restore_plan_impl()
        row, home, archive, name = _closed_plan(tmp_path)
        registry = {"plans": {"0042": row}}

        deps = _make_deps(
            normalize_plan_number=MagicMock(side_effect=lambda x: str(x).split("-")[-1].zfill(4)),
            load_registry=MagicMock(return_value=registry),
        )
        deps["restore_file_from_backup_fn"] = lambda info, key: _import_restore_file_from_backup()(
            info, key, backup_dir=archive
        )

        result = fn(plan_num="FPLAN-0042", **deps)

        # REACHED: the restore ran to completion, not short-circuited earlier.
        assert result["success"] is True, result["messages"]
        # OUTCOME: file back on disk, row reopened, and the name still carries the work.
        assert (home / name).is_file()
        assert registry["plans"]["0042"]["status"] == "open"
        assert "the_real_subject" in name and "2026-08-01" in name

    def test_the_rows_own_metadata_survives_the_restore(self, tmp_path):
        """recover_plan_from_backup would have overwritten subject and created."""
        fn = _import_restore_plan_impl()
        row, _home, archive, _name = _closed_plan(tmp_path)
        registry = {"plans": {"0042": row}}

        deps = _make_deps(
            normalize_plan_number=MagicMock(side_effect=lambda x: str(x).split("-")[-1].zfill(4)),
            load_registry=MagicMock(return_value=registry),
        )
        deps["restore_file_from_backup_fn"] = lambda info, key: _import_restore_file_from_backup()(
            info, key, backup_dir=archive
        )

        fn(plan_num="FPLAN-0042", **deps)

        restored = registry["plans"]["0042"]
        assert restored["subject"] == "The real subject"
        assert restored["created"] == "2026-08-01T00:00:00+00:00"
        assert restored["subject"] != "Recovered from backup"
        # Close metadata is cleared, which is what reopening means.
        assert "closed" not in restored

    def test_no_archived_copy_still_refuses_and_says_where_it_looked(self, tmp_path):
        fn = _import_restore_plan_impl()
        row, _home, archive, name = _closed_plan(tmp_path)
        (archive / name).unlink()
        registry = {"plans": {"0042": row}}

        deps = _make_deps(
            normalize_plan_number=MagicMock(side_effect=lambda x: str(x).split("-")[-1].zfill(4)),
            load_registry=MagicMock(return_value=registry),
        )
        deps["restore_file_from_backup_fn"] = lambda info, key: _import_restore_file_from_backup()(
            info, key, backup_dir=archive
        )

        result = fn(plan_num="FPLAN-0042", **deps)
        assert result["success"] is False
        assert any(m.get("error_type") == "file_missing" for m in result["messages"])
        blob = " ".join(str(m.get("text", "")) for m in result["messages"])
        assert "Archive lookup" in blob and "no archived copy" in blob
