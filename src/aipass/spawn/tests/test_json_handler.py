# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests that spawn's shim is wired to the fleet json service
# Version: 2.0.1
# Created: 2026-03-25
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/json/json_handler.py — spawn's shim onto the fleet json service."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in apps/handlers/json/ parses and imports
# seedgo: no-test-needed(covered_elsewhere) — behaviour, in tests/test_json_handler_contract.py

import json
from pathlib import Path

from aipass.spawn.apps.handlers.json import json_handler

# Only the WIRING is tested here; the service's behaviour is pinned once, fleet-wide, by seedgo's contract test.


BOUND_NAMES = (
    "read_json",
    "write_json",
    "validate_json_structure",
    "get_json_path",
    "ensure_json_exists",
    "ensure_module_jsons",
    "load_json",
    "save_json",
    "log_operation",
)


class TestTheSeamRedirectsSpawnsJson:
    """The conftest's autouse fixture is the only redirect there is."""

    def test_get_json_path_lands_under_the_redirected_dir(self, tmp_path, monkeypatch):
        """get_json_path follows AIPASS_TEST_LOG_DIR, set after import."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        result = json_handler.get_json_path("probe", "config")

        assert result == tmp_path / "spawn" / "spawn_json" / "probe_config.json"

    def test_the_directory_is_recomputed_on_every_call(self, tmp_path, monkeypatch):
        """No captured directory: a redirect that arrives late still takes effect."""
        first = json_handler.get_json_path("probe", "config").parent
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "moved"))
        second = json_handler.get_json_path("probe", "config").parent

        assert first != second
        assert second == tmp_path / "moved" / "spawn" / "spawn_json"

    def test_ensure_module_jsons_provisions_into_the_sandbox(self, tmp_path, monkeypatch):
        """spawn's own modules call this; it must never touch the live branch."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        assert json_handler.ensure_module_jsons("probe") is True
        for json_type in ("config", "data", "log"):
            assert (tmp_path / "spawn" / "spawn_json" / f"probe_{json_type}.json").exists()

    def test_load_json_reads_back_what_ensure_exists_wrote(self, tmp_path, monkeypatch):
        """ensure_json_exists provisions, load_json parses — through the seam."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        assert json_handler.ensure_json_exists("probe", "config") is True
        loaded = json_handler.load_json("probe", "config")

        assert isinstance(loaded, dict)
        assert loaded["module_name"] == "probe"

    def test_validate_json_structure_answers_for_spawns_own_documents(self):
        """The one call spawn makes that never touches the disk."""
        assert json_handler.validate_json_structure({"created": "x", "last_updated": "y"}, "data") is True
        assert json_handler.validate_json_structure({"missing": "keys"}, "data") is False


class TestTheShimBindsAndNeverWraps:
    """spawn's names ARE the service's callables, not calls into it."""

    def test_the_shim_reexports_every_documented_name(self):
        """The full service surface, not a subset."""
        expected = BOUND_NAMES + ("InvalidDocument", "WriteFailed")
        missing = [name for name in expected if not hasattr(json_handler, name)]

        assert missing == [], f"shim is missing re-exports: {missing}"

    def test_the_shim_is_bound_to_spawn(self):
        """for_module derived spawn's root from the shim's own __file__."""
        assert json_handler.get_json_path.__self__.branch_root.name == "spawn"

    def test_the_shim_is_byte_identical_to_the_template_spawn_ships(self):
        """spawn mints every citizen from that file; if the two differ, a newborn is born off-fleet."""
        shim = Path(json_handler.__file__).read_bytes()
        template = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "citizen"
            / "apps"
            / "handlers"
            / "json"
            / "json_handler.py"
        ).read_bytes()

        assert shim == template


class TestTheBoolPrimitiveSpawnDependsOn:
    """write_json is the bool primitive spawn's call sites branch on; save_json raises WriteFailed instead."""

    def test_write_json_reports_true_and_the_document_parses_from_disk(self, tmp_path):
        target = tmp_path / "out.json"

        assert json_handler.write_json(target, {"a": 1}) is True
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    def test_write_json_answers_false_and_never_raises_on_an_os_error(self, tmp_path):
        """A file where a directory must be — the failure spawn's callers handle."""
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file, not a directory", encoding="utf-8")

        assert json_handler.write_json(blocker / "nested" / "out.json", {"a": 1}) is False

    def test_read_json_answers_none_for_a_missing_file(self, tmp_path):
        """registry.py and repair_ops.py both test the result for None."""
        assert json_handler.read_json(tmp_path / "not_here.json") is None

    def test_read_json_answers_none_for_an_unparseable_file(self, tmp_path):
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{not valid json", encoding="utf-8")

        assert json_handler.read_json(corrupt) is None
