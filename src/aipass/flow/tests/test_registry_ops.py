# =================== AIPass ====================
# Name: test_registry_ops.py
# Description: Tests for registry_ops handler — template registry CRUD
# Version: 1.1.0
# Created: 2026-04-26
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/template/registry_ops.py and the plan registry save it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
from functools import partial
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.flow.apps.handlers.registry import load_registry as plan_load
from aipass.flow.apps.handlers.registry import save_registry as plan_reg
from aipass.flow.apps.handlers.runner import lock_ops
from aipass.flow.apps.handlers.template import registry_ops


class TestPlanRegistryLoadRefusesWhatItCannotRead:
    """The plan registry load: absent is empty, unreadable is a refusal.

    An empty answer for an unreadable registry lets create reissue 0001 and a save overwrite every row.
    """

    @pytest.fixture
    def flow_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plan_load, "FLOW_JSON_DIR", tmp_path)
        monkeypatch.setattr(plan_load, "REGISTRY_FILE", tmp_path / "fplan_registry.json")
        return tmp_path

    def test_an_absent_registry_is_the_empty_default(self, flow_json):
        assert plan_load.load_registry("dplan_registry.json") == {"plans": {}, "next_number": 1}

    def test_a_registry_that_is_not_json_refuses_and_is_left_as_it_was(self, flow_json):
        target = flow_json / "fplan_registry.json"
        target.write_text('{"plans": {"1": ', encoding="utf-8")

        with pytest.raises(plan_load.RegistryUnreadableError, match="cannot be read") as excinfo:
            plan_load.load_registry()

        assert str(target) in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)
        assert target.read_text(encoding="utf-8") == '{"plans": {"1": '

    def test_a_registry_that_is_not_an_object_refuses(self, flow_json):
        (flow_json / "dplan_registry.json").write_text("[]", encoding="utf-8")

        with pytest.raises(plan_load.RegistryUnreadableError, match="is not a JSON object: list"):
            plan_load.load_registry("dplan_registry.json")


_MOD = "aipass.flow.apps.handlers.template.registry_ops"
# The PLAN registry writer has no test class of its own; its lock cases ride in TestSaveRegistry.


@pytest.fixture
def setup_flow_root(tmp_path, monkeypatch):
    """Redirect FLOW_ROOT and REGISTRY_PATH to tmp_path for isolation."""
    mod = registry_ops
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


class TestLoadRegistry:
    """Tests for load_registry() — auto-creation, healing, corrupt handling."""

    def test_creates_registry_when_missing(self, setup_flow_root):
        """Auto-creates registry file with defaults when it does not exist."""
        mod = registry_ops
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
        """The create branch must run the same auto-discovery as the read branch, or call 1 and call 2 differ."""
        mod = registry_ops
        for name in ("flow_plans", "dev_plans", "audit_plans", "playbook_plans"):
            _create_template_dir(setup_flow_root, name, ["default.md"])

        first = sorted(e["prefix"] for e in mod.load_registry()["types"].values())
        second = sorted(e["prefix"] for e in mod.load_registry()["types"].values())

        assert first == second, "the registered set must not depend on how many times it has been read"
        assert "APLAN" in first and "PPLAN" in first

    def test_a_recreated_corrupt_registry_also_sees_shipped_templates(self, setup_flow_root):
        """Same fall-through, reached by the corrupt-file branch instead."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "audit_plans", ["default.md"])
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        reg_path.write_text("{ not json", encoding="utf-8")

        prefixes = sorted(e["prefix"] for e in mod.load_registry()["types"].values())

        assert "APLAN" in prefixes

    def test_loads_existing_valid_registry(self, setup_flow_root):
        """Loads a valid existing registry from disk."""
        mod = registry_ops
        data = _valid_registry()
        _write_registry(setup_flow_root, data)
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert result["types"]["flow_plans"]["prefix"] == "FPLAN"
        assert result["types"]["dev_plans"]["prefix"] == "DPLAN"

    def test_corrupt_json_recreates(self, setup_flow_root):
        """Corrupt JSON triggers recreation with defaults."""
        mod = registry_ops
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        reg_path.write_text("{invalid json!!!", encoding="utf-8")
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert "types" in result
        assert "flow_plans" in result["types"]

    def test_non_dict_recreates(self, setup_flow_root):
        """Non-dict JSON (e.g. a list) triggers recreation.

        Mutant: if changed or seeded: -> if changed: reddens this.
        """
        mod = registry_ops
        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        reg_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        result = mod.load_registry()

        assert set(result["types"]) == {"flow_plans", "dev_plans"}
        assert json.loads(reg_path.read_text(encoding="utf-8")) == result

    def test_heals_missing_types_key(self, setup_flow_root):
        """Auto-heals missing 'types' key by injecting defaults."""
        mod = registry_ops
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
        mod = registry_ops
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
        """load_registry invokes prune and auto-register.

        Mutant: changed = _prune_orphaned_types(data) -> changed = _prune_orphaned_types({}) reddens this.
        """
        mod = registry_ops
        data = _valid_registry()
        _write_registry(setup_flow_root, data)
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])

        with (
            patch(f"{_MOD}._prune_orphaned_types", return_value=False) as mock_prune,
            patch(f"{_MOD}._auto_register_new_types", return_value=False) as mock_auto,
        ):
            result = mod.load_registry()
            mock_prune.assert_called_once_with(result)
            mock_auto.assert_called_once_with(result)


class TestSaveRegistry:
    """Tests for save_registry() — writing, metadata update, validation."""

    def test_saves_valid_registry(self, setup_flow_root):
        """Writes valid registry JSON to disk."""
        mod = registry_ops
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
        mod = registry_ops
        data = _valid_registry()
        data["metadata"]["last_updated"] = "1999-01-01"
        data["metadata"]["type_count"] = 0

        mod.save_registry(data)

        reg_path = setup_flow_root / "flow_json" / "template_registry.json"
        saved = json.loads(reg_path.read_text(encoding="utf-8"))
        assert saved["metadata"]["last_updated"] != "1999-01-01"
        assert saved["metadata"]["type_count"] == 2

    def test_raises_for_invalid_structure_not_dict(self, setup_flow_root):
        """Raises when data is not a dict, and writes nothing: False would read as a failed write.

        Mutant: `raise ValueError(...)` -> `return False` reddens this.
        """
        mod = registry_ops

        with pytest.raises(ValueError, match="invalid registry structure: str"):
            mod.save_registry("not a dict")  # type: ignore[arg-type]

        assert not (setup_flow_root / "flow_json" / "template_registry.json").exists()

    def test_raises_for_missing_types_key(self, setup_flow_root):
        """Raises when 'types' key is absent, and writes nothing."""
        mod = registry_ops

        with pytest.raises(ValueError, match="invalid registry structure: dict"):
            mod.save_registry({"metadata": {}})

        assert not (setup_flow_root / "flow_json" / "template_registry.json").exists()

    def test_returns_false_on_os_error(self, setup_flow_root, monkeypatch, tmp_path):
        """Returns False when file write fails with OSError."""
        mod = registry_ops
        data = _valid_registry()
        # A file as parent makes mkdir fail on every platform.
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file", encoding="utf-8")
        monkeypatch.setattr(mod, "REGISTRY_PATH", blocker / "subdir" / "registry.json")

        result = mod.save_registry(data)

        assert result is False

    def test_logs_via_json_handler(self, setup_flow_root, mock_json_handler):
        """Calls json_handler.log_operation on successful save.

        Mutant: {"type_count": data["metadata"]["type_count"]} -> {"type_count": 0} reddens this.
        """
        mod = registry_ops
        data = _valid_registry()

        mod.save_registry(data)

        mock_json_handler.assert_called_once_with(
            "save_template_registry",
            {"type_count": 2},
            module_name="registry_ops",
        )

    def test_plan_registry_save_refuses_while_another_holder_keeps_the_lock(self, tmp_path, monkeypatch, mock_logger):
        """A held write lock is waited out to its timeout, then the save fails and writes nothing.

        Mutant: dropping `with registry_lock():` from save_registry reddens this.
        """
        monkeypatch.setattr(plan_reg, "FLOW_JSON_DIR", tmp_path)
        monkeypatch.setattr(plan_reg, "os_file_lock", partial(lock_ops.os_file_lock, timeout=0.0))
        target = tmp_path / "fplan_registry.json"
        before = {"plans": {}, "next_number": 1}
        target.write_text(json.dumps(before), encoding="utf-8")

        with lock_ops.os_file_lock(tmp_path / plan_reg.LOCK_NAME, timeout=0.0):
            result = plan_reg.save_registry({"plans": {"1": {}}, "next_number": 2}, registry_file=target.name)

        assert result is False
        assert json.loads(target.read_text(encoding="utf-8")) == before
        logged = " ".join(str(arg) for c in mock_logger.error.call_args_list for arg in c.args)
        assert plan_reg.LOCK_NAME in logged

    def test_registry_lock_is_reentrant_and_released(self, tmp_path, monkeypatch):
        """A nested holder never waits on itself, and the lock is free once the outer holder leaves.

        Mutant: dropping the depth check in registry_lock reddens this (the inner take times out).
        """
        monkeypatch.setattr(plan_reg, "FLOW_JSON_DIR", tmp_path)
        monkeypatch.setattr(plan_reg, "os_file_lock", partial(lock_ops.os_file_lock, timeout=0.0))

        with plan_reg.registry_lock():
            with plan_reg.registry_lock():
                assert plan_reg.save_registry({"plans": {}, "next_number": 1}, registry_file="x_registry.json")

        with lock_ops.os_file_lock(tmp_path / plan_reg.LOCK_NAME, timeout=0.0):
            pass


class TestAddType:
    """Tests for add_type() — validation, registration, plan registry creation."""

    def test_adds_new_type_successfully(self, setup_flow_root):
        """Registers a new type when all validations pass."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task_template.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.add_type("task_plans", "TPLAN", "test")

            assert result is True
            reg = mod.load_registry()
            assert "task_plans" in reg["types"]
            assert reg["types"]["task_plans"]["prefix"] == "TPLAN"

    def test_rejects_duplicate_dir_name(self, setup_flow_root):
        """Returns False if dir_name is already registered."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("flow_plans", "XPLAN", "test")

        assert result is False

    def test_rejects_duplicate_prefix_case_insensitive(self, setup_flow_root):
        """Returns False if prefix already taken (case-insensitive)."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["template.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("task_plans", "fplan", "test")

        assert result is False

    def test_rejects_missing_template_dir(self, setup_flow_root):
        """Returns False if template directory does not exist."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("nonexistent_plans", "NPLAN", "test")

        assert result is False

    def test_rejects_dir_without_md_files(self, setup_flow_root):
        """Returns False if template directory has no .md files."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "empty_plans")
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.add_type("empty_plans", "EPLAN", "test")

        assert result is False

    def test_creates_plan_registry_on_success(self, setup_flow_root):
        """Creates plan registry JSON for the new type."""
        mod = registry_ops
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


class TestRemoveType:
    """Tests for remove_type() — removal, protection, not-found."""

    def test_removes_existing_type(self, setup_flow_root):
        """Successfully removes a non-protected type."""
        mod = registry_ops
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

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.remove_type("task_plans")

            assert result is True
            reg = mod.load_registry()
            assert "task_plans" not in reg["types"]

    def test_returns_false_if_not_found(self, setup_flow_root):
        """Returns False if dir_name is not in registry."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.remove_type("nonexistent_plans")

        assert result is False

    def test_returns_false_for_protected_flow_plans(self, setup_flow_root):
        """Cannot remove protected type flow_plans."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.remove_type("flow_plans")

        assert result is False

    def test_returns_false_for_protected_dev_plans(self, setup_flow_root):
        """Cannot remove protected type dev_plans."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.remove_type("dev_plans")

        assert result is False


class TestGetPrefixMap:
    """Tests for get_prefix_map() — dir_name to prefix mapping."""

    def test_returns_all_registered_prefixes(self, setup_flow_root):
        """Returns {dir_name: prefix} for all types."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.get_prefix_map()

        assert result["flow_plans"] == "FPLAN"
        assert result["dev_plans"] == "DPLAN"

    def test_includes_custom_types(self, setup_flow_root):
        """Includes custom registered types in the map."""
        mod = registry_ops
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


class TestGetTypeMap:
    """Tests for get_type_map() — shorthand to dir_name mapping."""

    def test_returns_default_entry(self, setup_flow_root):
        """Always includes 'default': 'flow_plans'."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.get_type_map()

        assert result["default"] == "flow_plans"

    def test_returns_shorthand_mappings(self, setup_flow_root):
        """Maps shorthand to dir_name for all types."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        result = mod.get_type_map()

        assert result["fplan"] == "flow_plans"
        assert result["dplan"] == "dev_plans"

    def test_includes_custom_type_shorthand(self, setup_flow_root):
        """Custom types are included with their shorthand."""
        mod = registry_ops
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


class TestScanUnregistered:
    """Tests for scan_unregistered() — discovery of unregistered template dirs."""

    def test_finds_unregistered_dir(self, setup_flow_root):
        """Detects a template dir not in the registry."""
        mod = registry_ops
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
        mod = registry_ops
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
        mod = registry_ops
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
        mod = registry_ops
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
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()
        _write_registry(setup_flow_root, data)

        with patch(f"{_MOD}._auto_register_new_types", return_value=False):
            result = mod.scan_unregistered()

        assert result == []

    def test_returns_template_metadata(self, setup_flow_root):
        """Each result includes dir_name, template_count, and templates."""
        mod = registry_ops
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

        mod = registry_ops
        data = _valid_registry()
        _write_registry(setup_flow_root, data)
        tpl_dir = setup_flow_root / "templates"
        if tpl_dir.exists():
            shutil.rmtree(tpl_dir)

        with patch(f"{_MOD}._prune_orphaned_types", return_value=False):
            with patch(f"{_MOD}._auto_register_new_types", return_value=False):
                result = mod.scan_unregistered()

        assert result == []


class TestPruneOrphanedTypes:
    """Tests for _prune_orphaned_types() — cleaning stale entries."""

    def test_prunes_orphaned_non_protected_type(self, setup_flow_root):
        """Removes entries whose template directory is missing."""
        mod = registry_ops
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
        mod = registry_ops
        data = _valid_registry()

        mod._prune_orphaned_types(data)

        assert "flow_plans" in data["types"]
        assert "dev_plans" in data["types"]

    def test_returns_false_when_nothing_to_prune(self, setup_flow_root):
        """Returns False when all non-protected types have directories."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()

        result = mod._prune_orphaned_types(data)

        assert result is False

    def test_keeps_the_plan_registry_and_its_rows(self, setup_flow_root):
        """A type whose template directory is missing loses its entry, never its plan rows.

        Mutant: deleting <shorthand>_registry.json in _prune_orphaned_types reddens this.
        """
        mod = registry_ops
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
        rows = {"next_number": 3, "plans": {"0001": {"status": "open"}, "0002": {"status": "closed"}}}
        plan_reg.write_text(json.dumps(rows), encoding="utf-8")

        assert mod._prune_orphaned_types(data) is True

        assert "task_plans" not in data["types"]
        assert json.loads(plan_reg.read_text(encoding="utf-8")) == rows


class TestAutoRegisterNewTypes:
    """Tests for _auto_register_new_types() — automatic discovery and registration."""

    def test_registers_new_template_dir(self, setup_flow_root):
        """Finds and registers a new template directory."""
        mod = registry_ops
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
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, ".hidden", ["secret.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert ".hidden" not in data["types"]

    def test_skips_pycache(self, setup_flow_root):
        """__pycache__ directories are skipped."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "__pycache__", ["cache.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert "__pycache__" not in data["types"]

    def test_skips_underscore_dirs(self, setup_flow_root):
        """Directories starting with '_' are skipped."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "_internal", ["internal.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert "_internal" not in data["types"]

    def test_returns_false_when_templates_dir_missing(self, setup_flow_root):
        """Returns False when templates/ directory does not exist."""
        import shutil

        mod = registry_ops
        data = _valid_registry()
        tpl_dir = setup_flow_root / "templates"
        if tpl_dir.exists():
            shutil.rmtree(tpl_dir)

        result = mod._auto_register_new_types(data)

        assert result is False

    def test_returns_false_when_nothing_new(self, setup_flow_root):
        """Returns False when all dirs are already registered."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        data = _valid_registry()

        result = mod._auto_register_new_types(data)

        assert result is False

    def test_handles_prefix_collision_single_char(self, setup_flow_root):
        """Skips registration when derived prefix collides and no fallback."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "f", ["test.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        assert "f" not in data["types"]

    def test_creates_plan_registry_for_auto_registered(self, setup_flow_root):
        """Auto-registered types get a plan registry JSON created."""
        mod = registry_ops
        _create_template_dir(setup_flow_root, "flow_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "dev_plans", ["default.md"])
        _create_template_dir(setup_flow_root, "task_plans", ["task.md"])
        data = _valid_registry()

        mod._auto_register_new_types(data)

        plan_reg = setup_flow_root / "flow_json" / "tplan_registry.json"
        assert plan_reg.exists()
        content = json.loads(plan_reg.read_text(encoding="utf-8"))
        assert content["next_number"] == 1


class TestDerivePrefix:
    """Tests for _derive_prefix() — prefix derivation and collision handling."""

    def test_basic_derivation(self):
        """Derives first letter + 'PLAN' from dir name."""
        mod = registry_ops

        result = mod._derive_prefix("task_plans", set())

        assert result == "TPLAN"

    def test_collision_falls_back_to_two_chars(self):
        """On collision, tries first two letters + 'PLAN'."""
        mod = registry_ops

        result = mod._derive_prefix("task_plans", {"TPLAN"})

        assert result == "TAPLAN"

    def test_returns_none_on_double_collision(self):
        """Returns None when both single and double-char prefix collide."""
        mod = registry_ops

        result = mod._derive_prefix("task_plans", {"TPLAN", "TAPLAN"})

        assert result is None

    def test_single_char_dir_no_fallback(self):
        """Single-char dir name cannot fall back to 2-char prefix."""
        mod = registry_ops

        result = mod._derive_prefix("t", {"TPLAN"})

        assert result is None

    def test_empty_dir_name_gives_xplan(self):
        """Empty dir name (empty first_word) falls back to XPLAN."""
        mod = registry_ops

        result = mod._derive_prefix("", set())

        assert result == "XPLAN"

    def test_every_meaningful_word_contributes_an_initial(self):
        """One initial per word, trailing 'plans' dropped: SAPLAN, not SPLAN."""
        mod = registry_ops

        result = mod._derive_prefix("security_audit_plans", set())

        assert result == "SAPLAN"

    def test_team_dev_plans_derives_tdplan_on_a_fresh_install(self):
        """The ruled answer, with an EMPTY registry — no install history to lean on."""
        mod = registry_ops

        assert mod._derive_prefix("team_dev_plans", set()) == "TDPLAN"

    def test_derivation_does_not_depend_on_what_is_already_registered(self):
        """Same directory, three different registries, one answer: install history must not move it."""
        mod = registry_ops

        answers = {
            mod._derive_prefix("team_dev_plans", set()),
            mod._derive_prefix("team_dev_plans", {"FPLAN", "DPLAN"}),
            mod._derive_prefix("team_dev_plans", {"FPLAN", "DPLAN", "APLAN", "PPLAN", "RPLAN", "CPLAN"}),
        }

        assert answers == {"TDPLAN"}

    def test_every_shipped_template_dir_derives_its_registered_prefix(self):
        """A fresh install must reach the prefixes this branch's files already use.

        Read off the live registry, not a hand-copied table that would agree with itself.
        """
        mod = registry_ops
        registry = mod.load_registry()

        mismatches = {
            dir_name: (entry.get("prefix"), mod._derive_prefix(dir_name, set()))
            for dir_name, entry in registry["types"].items()
            if mod._derive_prefix(dir_name, set()) != entry.get("prefix")
        }

        assert mismatches == {}, f"derivation disagrees with the registry: {mismatches}"
