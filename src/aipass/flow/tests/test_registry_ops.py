# =================== AIPass ====================
# Name: test_registry_ops.py
# Description: Tests for registry_ops handler — template registry CRUD
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

"""Tests for registry_ops: template registry CRUD, auto-healing, discovery, edge cases."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Module-level patch targets (patch where used, not where defined)
# ---------------------------------------------------------------------------

_MOD = "aipass.flow.apps.handlers.template.registry_ops"


def _import_mod():
    import aipass.flow.apps.handlers.template.registry_ops as mod

    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def setup_flow_root(tmp_path, monkeypatch):
    """Redirect FLOW_ROOT and REGISTRY_PATH to tmp_path for isolation."""
    mod = _import_mod()
    flow_root = tmp_path / "flow"
    flow_root.mkdir()
    (flow_root / "flow_json").mkdir()
    (flow_root / "templates").mkdir()
    monkeypatch.setattr(mod, "FLOW_ROOT", flow_root)
    monkeypatch.setattr(mod, "REGISTRY_PATH", flow_root / "flow_json" / "template_registry.json")
    return flow_root


def _write_registry(flow_root: Path, data: dict) -> Path:
    """Helper: write a template registry JSON and return its path."""
    path = flow_root / "flow_json" / "template_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _valid_registry(extra_types: dict | None = None) -> dict:
    """Return a minimal valid registry dict with default types."""
    types = {
        "flow_plans": {
            "prefix": "FPLAN",
            "shorthand": "fplan",
            "created": "2026-03-18",
            "registered_by": "system",
        },
        "dev_plans": {
            "prefix": "DPLAN",
            "shorthand": "dplan",
            "created": "2026-03-18",
            "registered_by": "system",
        },
    }
    if extra_types:
        types.update(extra_types)
    return {
        "types": types,
        "metadata": {
            "version": "1.0.0",
            "last_updated": "2026-03-18",
            "type_count": len(types),
        },
    }


def _create_template_dir(flow_root: Path, name: str, md_files: list[str] | None = None) -> Path:
    """Create a template directory under templates/ with optional .md files."""
    tpl_dir = flow_root / "templates" / name
    tpl_dir.mkdir(parents=True, exist_ok=True)
    for md in md_files or []:
        (tpl_dir / md).write_text(f"# {md}", encoding="utf-8")
    return tpl_dir


# =============================================================================
# load_registry
# =============================================================================


class TestLoadRegistry:
    """Tests for load_registry() — auto-creation, healing, corrupt handling."""

    def test_creates_registry_when_missing(self, setup_flow_root):
        """Auto-creates registry file with defaults when it does not exist."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert "types" in result
        assert "metadata" in result
        assert "flow_plans" in result["types"]
        assert "dev_plans" in result["types"]
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        assert reg_path.exists()

    def test_first_read_of_a_fresh_install_sees_every_shipped_template(self, setup_flow_root):
        """The defect CI found: call 1 answered with 2 types, call 2 with 7.

        A fresh checkout ships template directories and no registry. The
        create branch returned the bare defaults and never ran the same
        auto-discovery the read branch runs, so the FIRST flow command on a
        new install saw a registered set that was missing every shipped type
        beyond FPLAN and DPLAN -- and the second command saw them all. Two
        answers to one question, decided by call ordering.
        """
        mod = _import_mod()
        for name in ("flow_plans", "dev_plans", "audit_plans", "playbook_plans"):
            _create_template_dir(setup_flow_root, name, ["default.md"])

        first = sorted(e["prefix"] for e in mod.load_registry()["types"].values())
        second = sorted(e["prefix"] for e in mod.load_registry()["types"].values())

        assert first == second, "the registered set must not depend on how many times it has been read"
        assert "APLAN" in first and "PPLAN" in first

    def test_a_recreated_corrupt_registry_also_sees_shipped_templates(self, setup_flow_root):
        """Same fall-through, reached by the corrupt-file branch instead."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "audit_plans", ["default.md"])
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        reg_path.write_text("{ not json", encoding="utf-8")

        prefixes = sorted(e["prefix"] for e in mod.load_registry()["types"].values())

        assert "APLAN" in prefixes

    def test_loads_existing_valid_registry(self, setup_flow_root):
        """Loads a valid existing registry from disk."""
        mod = _import_mod()
        data = _valid_registry()
        _write_registry(setup_flow_root, data)
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert result["types"]["flow_plans"]["prefix"] == "FPLAN"
        assert result["types"]["dev_plans"]["prefix"] == "DPLAN"

    def test_corrupt_json_recreates(self, setup_flow_root):
        """Corrupt JSON triggers recreation with defaults."""
        mod = _import_mod()
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        reg_path.write_text("{invalid json!!!", encoding="utf-8")
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert "types" in result
        assert "flow_plans" in result["types"]

    def test_non_dict_recreates(self, setup_flow_root):
        """Non-dict JSON (e.g. a list) triggers recreation."""
        mod = _import_mod()
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        reg_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert isinstance(result, dict)
        assert "types" in result

    def test_heals_missing_types_key(self, setup_flow_root):
        """Auto-heals missing 'types' key by injecting defaults."""
        mod = _import_mod()
        data = {"metadata": {"version": "1.0.0", "last_updated": "2026-01-01", "type_count": 0}}
        _write_registry(setup_flow_root, data)
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert "types" in result
        assert "flow_plans" in result["types"]
        assert "dev_plans" in result["types"]

    def test_heals_missing_metadata_key(self, setup_flow_root):
        """Auto-heals missing 'metadata' key."""
        mod = _import_mod()
        data = {
            "types": {
                "flow_plans": {"prefix": "FPLAN", "shorthand": "fplan"},
                "dev_plans": {"prefix": "DPLAN", "shorthand": "dplan"},
            }
        }
        _write_registry(setup_flow_root, data)
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert "metadata" in result
        assert "version" in result["metadata"]
        assert "type_count" in result["metadata"]

    def test_calls_prune_and_auto_register(self, setup_flow_root):
        """load_registry invokes prune and auto-register."""
        mod = _import_mod()
        data = _valid_registry()
        _write_registry(setup_flow_root, data)
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        with (
            patch(f"{_MOD}._prune_orphaned_types", return_value=False) as mock_prune,
            patch(f"{_MOD}._auto_register_new_types", return_value=False) as mock_auto,
        ):
            mod.load_registry()
            mock_prune.assert_called_once()
            mock_auto.assert_called_once()


# =============================================================================
# save_registry
# =============================================================================


class TestSaveRegistry:
    """Tests for save_registry() — writing, metadata update, validation."""

    def test_saves_valid_registry(self, setup_flow_root):
        """Writes valid registry JSON to disk."""
        mod = _import_mod()
        data = _valid_registry()

        result = mod.save_registry(data)

        assert result is True
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        assert reg_path.exists()
        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert "types" in saved
        assert "metadata" in saved

    def test_updates_metadata_on_save(self, setup_flow_root):
        """Updates last_updated and type_count in metadata."""
        mod = _import_mod()
        data = _valid_registry()
        data["metadata"]["last_updated"] = "1999-01-01"
        data["metadata"]["type_count"] = 0

        mod.save_registry(data)

        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["metadata"]["last_updated"] != "1999-01-01"
        assert saved["metadata"]["type_count"] == 2

    def test_returns_false_for_invalid_structure_not_dict(self, setup_flow_root):
        """Returns False when data is not a dict."""
        mod = _import_mod()

        result = mod.save_registry("not a dict")  # type: ignore[arg-type]

        assert result is False

    def test_returns_false_for_missing_types_key(self, setup_flow_root):
        """Returns False when 'types' key is absent."""
        mod = _import_mod()

        result = mod.save_registry({"metadata": {}})

        assert result is False

    def test_returns_false_on_os_error(self, setup_flow_root, monkeypatch, tmp_path):
        """Returns False when file write fails with OSError."""
        mod = _import_mod()
        data = _valid_registry()
        # Use a file as parent so mkdir fails on all platforms
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file", encoding="utf-8")
        monkeypatch.setattr(mod, "REGISTRY_PATH", blocker / "subdir" / "registry.json")

        result = mod.save_registry(data)

        assert result is False

    def test_logs_via_json_handler(self, setup_flow_root, mock_json_handler):
        """Calls json_handler.log_operation on successful save."""
        mod = _import_mod()
        data = _valid_registry()

        mod.save_registry(data)

        mock_json_handler.assert_called()


# =============================================================================
# add_type
# =============================================================================


class TestAddType:
    """Tests for add_type() — validation, registration, plan registry creation."""

    def test_adds_new_type_successfully(self, setup_flow_root):
        """Registers a new type when all validations pass."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task_template.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        # Prevent auto-register from claiming task_plans before add_type does
        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.add_type("task_plans", "TPLAN", "test")

            assert result is True
            reg = mod.load_registry()
            assert "task_plans" in reg["types"]
            assert reg["types"]["task_plans"]["prefix"] == "TPLAN"

    def test_rejects_duplicate_dir_name(self, setup_flow_root):
        """Returns False if dir_name is already registered."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("flow_plans", "XPLAN", "test")

        assert result is False

    def test_rejects_duplicate_prefix_case_insensitive(self, setup_flow_root):
        """Returns False if prefix already taken (case-insensitive)."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["template.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("task_plans", "fplan", "test")

        assert result is False

    def test_rejects_missing_template_dir(self, setup_flow_root):
        """Returns False if template directory does not exist."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("nonexistent_plans", "NPLAN", "test")

        assert result is False

    def test_rejects_dir_without_md_files(self, setup_flow_root):
        """Returns False if template directory has no .md files."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "empty_plans")
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("empty_plans", "EPLAN", "test")

        assert result is False

    def test_creates_plan_registry_on_success(self, setup_flow_root):
        """Creates plan registry JSON for the new type."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        mod.add_type("task_plans", "TPLAN", "test")

        plan_reg = setup_flow_root / "flow_json" / "tplan_registry.json"
        assert plan_reg.exists()
        content = json.loads(plan_reg.read_text(encoding="utf-8"))
        assert content["next_number"] == 1
        assert content["plans"] == {}


# =============================================================================
# remove_type
# =============================================================================


class TestRemoveType:
    """Tests for remove_type() — removal, protection, not-found."""

    def test_removes_existing_type(self, setup_flow_root):
        """Successfully removes a non-protected type."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        extra = {
            "task_plans": {
                "prefix": "TPLAN",
                "shorthand": "tplan",
                "created": "2026-04-01",
                "registered_by": "test",
            }
        }
        data = _valid_registry(extra_types=extra)
        _write_registry(setup_flow_root, data)

        # Prevent auto-register from re-adding task_plans after removal
        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.remove_type("task_plans")

            assert result is True
            reg = mod.load_registry()
            assert "task_plans" not in reg["types"]

    def test_returns_false_if_not_found(self, setup_flow_root):
        """Returns False if dir_name is not in registry."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.remove_type("nonexistent_plans")

        assert result is False

    def test_returns_false_for_protected_flow_plans(self, setup_flow_root):
        """Cannot remove protected type flow_plans."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.remove_type("flow_plans")

        assert result is False

    def test_returns_false_for_protected_dev_plans(self, setup_flow_root):
        """Cannot remove protected type dev_plans."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.remove_type("dev_plans")

        assert result is False


# =============================================================================
# get_prefix_map
# =============================================================================


class TestGetPrefixMap:
    """Tests for get_prefix_map() — dir_name to prefix mapping."""

    def test_returns_all_registered_prefixes(self, setup_flow_root):
        """Returns {dir_name: prefix} for all types."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.get_prefix_map()

        assert result["flow_plans"] == "FPLAN"
        assert result["dev_plans"] == "DPLAN"

    def test_includes_custom_types(self, setup_flow_root):
        """Includes custom registered types in the map."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        extra = {
            "task_plans": {
                "prefix": "TPLAN",
                "shorthand": "tplan",
                "created": "2026-04-01",
                "registered_by": "test",
            }
        }
        data = _valid_registry(extra_types=extra)
        _write_registry(setup_flow_root, data)

        result = mod.get_prefix_map()

        assert result["task_plans"] == "TPLAN"
        assert len(result) == 3


# =============================================================================
# get_type_map
# =============================================================================


class TestGetTypeMap:
    """Tests for get_type_map() — shorthand to dir_name mapping."""

    def test_returns_default_entry(self, setup_flow_root):
        """Always includes 'default': 'flow_plans'."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.get_type_map()

        assert result["default"] == "flow_plans"

    def test_returns_shorthand_mappings(self, setup_flow_root):
        """Maps shorthand to dir_name for all types."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.get_type_map()

        assert result["fplan"] == "flow_plans"
        assert result["dplan"] == "dev_plans"

    def test_includes_custom_type_shorthand(self, setup_flow_root):
        """Custom types are included with their shorthand."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        extra = {
            "task_plans": {
                "prefix": "TPLAN",
                "shorthand": "tplan",
                "created": "2026-04-01",
                "registered_by": "test",
            }
        }
        data = _valid_registry(extra_types=extra)
        _write_registry(setup_flow_root, data)

        result = mod.get_type_map()

        assert result["tplan"] == "task_plans"


# =============================================================================
# scan_unregistered
# =============================================================================


class TestScanUnregistered:
    """Tests for scan_unregistered() — discovery of unregistered template dirs."""

    def test_finds_unregistered_dir(self, setup_flow_root):
        """Detects a template dir not in the registry."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.scan_unregistered()

        names = [r["dir_name"] for r in result]
        assert "task_plans" in names

    def test_skips_hidden_dirs(self, setup_flow_root):
        """Directories starting with '.' are ignored."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, ".hidden_plans", ["hidden.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.scan_unregistered()

        names = [r["dir_name"] for r in result]
        assert ".hidden_plans" not in names

    def test_skips_underscore_dirs(self, setup_flow_root):
        """Directories starting with '_' are ignored."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "_private_plans", ["private.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.scan_unregistered()

        names = [r["dir_name"] for r in result]
        assert "_private_plans" not in names

    def test_skips_dirs_without_md_files(self, setup_flow_root):
        """Dirs with no .md files are not returned."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "empty_plans")
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.scan_unregistered()

        names = [r["dir_name"] for r in result]
        assert "empty_plans" not in names

    def test_returns_empty_when_all_registered(self, setup_flow_root):
        """Returns empty list when no unregistered dirs exist."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.scan_unregistered()

        assert result == []

    def test_returns_template_metadata(self, setup_flow_root):
        """Each result includes dir_name, template_count, and templates."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "audit_plans", ["audit_a.md", "audit_b.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.scan_unregistered()

        assert len(result) == 1
        entry = result[0]
        assert entry["dir_name"] == "audit_plans"
        assert entry["template_count"] == 2
        templates = entry["templates"]
        assert isinstance(templates, list)
        assert sorted(templates) == ["audit_a", "audit_b"]

    def test_returns_empty_when_templates_dir_missing(self, setup_flow_root):
        """Returns empty list when templates/ directory does not exist."""
        import shutil

        mod = _import_mod()
        data = _valid_registry()
        _write_registry(setup_flow_root, data)
        tpl_dir = setup_flow_root / "templates"
        if tpl_dir.exists():
            shutil.rmtree(tpl_dir)

        with patch(f"{_MOD}._prune_orphaned_types", return_value=False):
            with patch(f"{_MOD}._auto_register_new_types", return_value=False):
                result = mod.scan_unregistered()

        assert result == []


# =============================================================================
# _prune_orphaned_types
# =============================================================================


class TestPruneOrphanedTypes:
    """Tests for _prune_orphaned_types() — cleaning stale entries."""

    def test_prunes_orphaned_non_protected_type(self, setup_flow_root):
        """Removes entries whose template directory is missing."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        extra = {
            "task_plans": {
                "prefix": "TPLAN",
                "shorthand": "tplan",
                "created": "2026-04-01",
                "registered_by": "test",
            }
        }
        data = _valid_registry(extra_types=extra)

        result = mod._prune_orphaned_types(data)

        assert result is True
        assert "task_plans" not in data["types"]

    def test_does_not_prune_protected_types(self, setup_flow_root):
        """Protected types (flow_plans, dev_plans) survive even without dirs."""
        mod = _import_mod()
        data = _valid_registry()

        mod._prune_orphaned_types(data)

        assert "flow_plans" in data["types"]
        assert "dev_plans" in data["types"]

    def test_returns_false_when_nothing_to_prune(self, setup_flow_root):
        """Returns False when all non-protected types have directories."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()

        result = mod._prune_orphaned_types(data)

        assert result is False

    def test_deletes_orphan_plan_registry_json(self, setup_flow_root):
        """Deletes the associated plan registry JSON when pruning."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        extra = {
            "task_plans": {
                "prefix": "TPLAN",
                "shorthand": "tplan",
                "created": "2026-04-01",
                "registered_by": "test",
            }
        }
        data = _valid_registry(extra_types=extra)
        plan_reg = setup_flow_root / "flow_json" / "tplan_registry.json"
        plan_reg.write_text(json.dumps({"next_number": 1, "plans": {}}), encoding="utf-8")

        mod._prune_orphaned_types(data)

        assert not plan_reg.exists()


# =============================================================================
# _auto_register_new_types
# =============================================================================


class TestAutoRegisterNewTypes:
    """Tests for _auto_register_new_types() — automatic discovery and registration."""

    def test_registers_new_template_dir(self, setup_flow_root):
        """Finds and registers a new template directory."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        data = _valid_registry()

        result = mod._auto_register_new_types(data)

        assert result is True
        assert "task_plans" in data["types"]
        assert data["types"]["task_plans"]["registered_by"] == "auto"

    def test_skips_hidden_dirs(self, setup_flow_root):
        """Directories starting with '.' are skipped."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, ".hidden", ["secret.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert ".hidden" not in data["types"]

    def test_skips_pycache(self, setup_flow_root):
        """__pycache__ directories are skipped."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "__pycache__", ["cache.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert "__pycache__" not in data["types"]

    def test_skips_underscore_dirs(self, setup_flow_root):
        """Directories starting with '_' are skipped."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "_internal", ["internal.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert "_internal" not in data["types"]

    def test_returns_false_when_templates_dir_missing(self, setup_flow_root):
        """Returns False when templates/ directory does not exist."""
        import shutil

        mod = _import_mod()
        data = _valid_registry()
        tpl_dir = setup_flow_root / "templates"
        if tpl_dir.exists():
            shutil.rmtree(tpl_dir)

        result = mod._auto_register_new_types(data)

        assert result is False

    def test_returns_false_when_nothing_new(self, setup_flow_root):
        """Returns False when all dirs are already registered."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()

        result = mod._auto_register_new_types(data)

        assert result is False

    def test_handles_prefix_collision_single_char(self, setup_flow_root):
        """Skips registration when derived prefix collides and no fallback."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        # "f" would try FPLAN (collision), but len("f") == 1 so no 2-char fallback
        _create_template_dir(setup_flow_root, "f", ["test.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert "f" not in data["types"]

    def test_creates_plan_registry_for_auto_registered(self, setup_flow_root):
        """Auto-registered types get a plan registry JSON created."""
        mod = _import_mod()
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        plan_reg = setup_flow_root / "flow_json" / "tplan_registry.json"
        assert plan_reg.exists()
        content = json.loads(plan_reg.read_text(encoding="utf-8"))
        assert content["next_number"] == 1


# =============================================================================
# _derive_prefix
# =============================================================================


class TestDerivePrefix:
    """Tests for _derive_prefix() — prefix derivation and collision handling."""

    def test_basic_derivation(self):
        """Derives first letter + 'PLAN' from dir name."""
        mod = _import_mod()

        result = mod._derive_prefix("task_plans", set())

        assert result == "TPLAN"

    def test_collision_falls_back_to_two_chars(self):
        """On collision, tries first two letters + 'PLAN'."""
        mod = _import_mod()

        result = mod._derive_prefix("task_plans", {"TPLAN"})

        assert result == "TAPLAN"

    def test_returns_none_on_double_collision(self):
        """Returns None when both single and double-char prefix collide."""
        mod = _import_mod()

        result = mod._derive_prefix("task_plans", {"TPLAN", "TAPLAN"})

        assert result is None

    def test_single_char_dir_no_fallback(self):
        """Single-char dir name cannot fall back to 2-char prefix."""
        mod = _import_mod()

        result = mod._derive_prefix("t", {"TPLAN"})

        assert result is None

    def test_empty_dir_name_gives_xplan(self):
        """Empty dir name (empty first_word) falls back to XPLAN."""
        mod = _import_mod()

        result = mod._derive_prefix("", set())

        assert result == "XPLAN"

    def test_underscore_prefix_splits_on_underscore(self):
        """Uses only the first word before underscore."""
        mod = _import_mod()

        result = mod._derive_prefix("security_audit_plans", set())

        assert result == "SPLAN"
