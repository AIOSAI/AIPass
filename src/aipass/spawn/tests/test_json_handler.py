# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Tests that spawn's shim is wired to the fleet json service
# Version: 2.0.0
# Created: 2026-03-25
# Modified: 2026-09-03
# =============================================

"""Tests for spawn's JSON handler shim.

Only the WIRING is tested here: that spawn's shim binds the fleet's one json
service (DPLAN-0325), that it lands in spawn_json/, and that it adds nothing of
its own. The service's BEHAVIOUR - defaults, validation, provisioning, rotation,
durability - is pinned once for all eighteen branches by seedgo's
tests/test_json_handler_contract.py and is deliberately not re-tested here.

What this file used to be is in tests/.archive/: the DPLAN-0059 universal
template stamp, discovering a ``_JSON_DIR`` attribute by name and patching it.
The service computes its directory per call and the shim has no attributes at
all, so the stamp SKIPPED itself module-wide the moment the shim landed - a file
that reports "1 skipped" and tests nothing. It is not rewritten; seedgo's
contract already carries every claim it made.

Redirection here is the ``AIPASS_TEST_LOG_DIR`` seam the conftest sets per test.
"""

import json
from pathlib import Path

import pytest

from aipass.prax import json_handler as json_service
from aipass.spawn.apps.handlers.json import json_handler


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


# =============================================================================
# THE SEAM — where spawn's json actually lands
# =============================================================================


class TestTheSeamRedirectsSpawnsJson:
    """The conftest's autouse fixture is the only redirect there is."""

    def test_get_json_path_lands_under_the_redirected_dir(self, tmp_path, monkeypatch):
        """get_json_path follows AIPASS_TEST_LOG_DIR, set after import."""
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))

        result = json_handler.get_json_path("probe", "config")

        assert result == tmp_path / "spawn" / "spawn_json" / "probe_config.json"

    def test_the_directory_is_recomputed_on_every_call(self, tmp_path, monkeypatch):
        """No captured directory: a redirect that arrives late still takes effect.

        This is what replaced the patched ``_JSON_DIR`` — there is no attribute
        to patch, so a test that forgets the seam writes into the real
        spawn_json/ rather than failing loudly. The autouse fixture in
        tests/conftest.py is what keeps that from happening.
        """
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


# =============================================================================
# THE SHIM — it binds, it never wraps
# =============================================================================


class TestTheShimBindsAndNeverWraps:
    """spawn's names ARE the service's callables, not calls into it."""

    @pytest.mark.parametrize("name", BOUND_NAMES)
    def test_every_public_name_is_a_bound_method_of_the_service(self, name):
        """A wrapper would add a stack frame, and the service names the calling
        module from frame 2 — every entry spawn logged would be attributed to
        the wrapper's file instead of the caller's."""
        bound = getattr(json_handler, name)

        assert bound.__func__ is getattr(json_service.JsonHandle, name)
        assert isinstance(bound.__self__, json_service.JsonHandle)

    def test_the_shim_reexports_every_documented_name(self):
        """The full service surface, not a subset."""
        expected = BOUND_NAMES + ("InvalidDocument", "WriteFailed")
        missing = [name for name in expected if not hasattr(json_handler, name)]

        assert missing == [], f"shim is missing re-exports: {missing}"

    def test_the_exceptions_are_the_services_own(self):
        """A caller catching spawn's InvalidDocument catches the service's."""
        assert json_handler.InvalidDocument is json_service.InvalidDocument
        assert json_handler.WriteFailed is json_service.WriteFailed

    def test_the_shim_is_bound_to_spawn(self):
        """for_module derived spawn's root from the shim's own __file__."""
        assert json_handler.get_json_path.__self__.branch_root.name == "spawn"

    def test_the_shim_carries_nothing_else(self):
        """Byte-identical in all eighteen branches by design — anything spawn
        adds here is the drift DPLAN-0325 removed."""
        public = {name for name in vars(json_handler) if not name.startswith("_")}

        assert public == set(json_handler.__all__) | {"json_handler"}

    def test_the_shim_is_byte_identical_to_the_template_spawn_ships(self):
        """spawn mints every citizen from that file; if the two ever differ, a
        newborn is born off-fleet and nothing else in the suite would say so."""
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


# =============================================================================
# THE CONSUMERS — the return contract spawn's own code depends on
# =============================================================================


class TestTheBoolPrimitiveSpawnDependsOn:
    """write_json is the bool primitive four spawn call sites branch on.

    core.py:401, registry.py:277 and :454 and repair_ops.py:165 all read the
    return value. save_json now RAISES WriteFailed instead of answering False,
    so a future migration of these call sites to save_json would silently turn
    a handled failure into an escaping exception. These pin the contract they
    were written against.
    """

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
