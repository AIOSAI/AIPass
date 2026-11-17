# =================== AIPass ====================
# Name: test_fleet_gateway.py
# Description: Pins the public cross-branch gateway for the fleet definition and the package top file
# Version: 1.1.0
# Created: 2026-08-30
# Modified: 2026-11-16
# =============================================

"""Tests for apps/modules/fleet.py and __init__.py, memory's one import door."""

# modules/ is the public gateway; handlers/ is private. The mechanics of finding residents are not re-exported.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — declared_residency answers, in tests/test_residency_scope.py
# sentry: no-test-needed(covered_elsewhere) — declared_roots values, in tests/test_declared_roots.py
# sentry: no-test-needed(covered_elsewhere) — find_repo_root's walk, in tests/test_repo_root.py
# sentry: no-test-needed(shared) — the json_handler.log_operation audit line; the json handler's lane

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.memory as door
from aipass.cli import reset_command_state, resolve_exit
from aipass.memory.apps import memory
from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.apps.modules import fleet


CONTRACT = (
    "fleet_branches",
    "find_repo_root",
    "declared_residency",
    "accepted_resident_paths",
    "declared_roots",
    "external_branches",
    "RESIDENCY_CORE",
    "RESIDENCY_RESIDENT",
    "RESIDENCY_EXTERNAL",
    "DECLARED_ROOTS",
)

INTERNAL = ("resident_registry_paths", "read_registry_branches", "_refuse", "_accepted_residents")

_H = "aipass.memory.apps.handlers"
# Written out by hand, not read from the door: the door's own table must agree with an independent list.
DOOR_HOMES = {
    f"{_H}.monitor.registry_scope": (
        "fleet_branches",
        "external_branches",
        "declared_roots",
        "declared_residency",
        "find_repo_root",
        "RESIDENCY_CORE",
        "RESIDENCY_RESIDENT",
        "RESIDENCY_EXTERNAL",
    ),
    f"{_H}.governance.engine": ("should_surface", "record_message", "new_state"),
    f"{_H}.json.entry_limits": (
        "load_entry_limits",
        "check_file_budget",
        "changed_entries",
        "fields_for",
        "draft_target",
    ),
    f"{_H}.json.config_loader": ("get_todos_count", "section"),
    f"{_H}.tracking.tab_renderer": ("compose_meta", "render_all_meta_tabs"),
    f"{_H}.templates.trinity_push": ("entry_rules",),
    f"{_H}.rollover.todo_report": ("READY_PHRASE",),
    f"{_H}.intake.auto_process": ("spawn_background",),
    f"{_H}.intake.plans_processor": ("process_plans",),
    "aipass.memory.apps.modules.health": ("get_branch_health",),
}
DOOR_NAMES = [(home, name) for home, names in DOOR_HOMES.items() for name in names]

# Prints every aipass.memory submodule loaded after the probe's body runs.
_LOADED = "\nprint(json.dumps(sorted(m for m in sys.modules if m.startswith('aipass.memory.'))))"


def _fresh(body: str, cwd: Path | None = None) -> list[str]:
    """Run *body* in a clean interpreter; answer the memory submodules it left loaded."""
    done = subprocess.run(
        [sys.executable, "-c", "import importlib, json, sys\n" + body + _LOADED],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(cwd) if cwd else None,
    )
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1])


class TestTheGatewayIsADoorNotACopy:
    """Re-export, never reimplement. A gateway that computes anything is a second definition."""

    @pytest.mark.parametrize("name", CONTRACT)
    def test_every_contract_name_is_the_same_object_as_the_handler_s(self, name):
        """Identity, not equality. A wrapper that merely AGREES today is the defect this ends."""
        assert getattr(fleet, name) is getattr(registry_scope, name)

    def test_dunder_all_is_exactly_the_contract(self):
        assert tuple(fleet.__all__) == CONTRACT

    @pytest.mark.parametrize("name", INTERNAL)
    def test_the_internals_stay_behind_the_door(self, name):
        """Named one by one: a later re-export would silently widen what I must not break."""
        assert not hasattr(fleet, name), f"{name} is internal and must not be part of the public gateway"


class TestTheCommandSurfaceIsIntrospectionOnly:
    """Discoverable like health.py, but the CLI describes the contract and never executes fleet work."""

    def test_it_answers_only_its_own_command(self):
        """A module that claims a command it does not own swallows another module's work."""
        assert fleet.handle_command("rollover", []) is False
        assert fleet.handle_command("search", ["x"]) is False

    @pytest.mark.parametrize("args", [[], ["--help"], ["-h"], ["help"]])
    def test_the_bare_command_and_every_help_spelling_introspect(self, capsys, args):
        assert fleet.handle_command("fleet", args) is True
        assert "fleet Module" in capsys.readouterr().out

    def test_an_unknown_subcommand_is_named_not_swallowed(self, capsys):
        """Claimed and reported, never a silent no-op that looks like success: exits 2, read from both streams."""
        reset_command_state()
        assert fleet.handle_command("fleet", ["nonsense"]) is True
        assert resolve_exit(True) == 2, "an unknown subcommand refused but would exit 0"
        captured = capsys.readouterr()
        assert "nonsense" in captured.out + captured.err

    def test_the_command_surface_executes_no_fleet_work(self, monkeypatch):
        """The pin that keeps this a door: the CLI must never answer the question itself.

        Both bindings are watched: ``fleet`` holds its own names for the handler's functions.
        """
        called = []
        for owner in (registry_scope, fleet):
            monkeypatch.setattr(owner, "fleet_branches", lambda *a, **k: called.append(a) or [])
            monkeypatch.setattr(owner, "accepted_resident_paths", lambda *a, **k: called.append(a) or set())
        assert fleet.handle_command("fleet", []) is True
        assert called == [], "the gateway's CLI computed fleet state instead of describing the contract"

    def test_it_is_discovered_by_the_real_loops_own_rule(self):
        """Every ``modules/*.py`` defining ``handle_command`` is discovered by the real loop, and nothing else."""
        modules_dir = Path(fleet.__file__).parent
        on_disk = {
            path.stem
            for path in modules_dir.glob("*.py")
            if not path.name.startswith("_") and "def handle_command(" in path.read_text(encoding="utf-8")
        }
        commanded = sorted(module.__name__.rsplit(".", 1)[-1] for module in memory.discover_modules())
        assert commanded == sorted(on_disk)
        assert "fleet" in commanded
        assert "health" in commanded, "the precedent gateway no longer follows the convention this one copied"


class TestTheDoorAnswersTheSameAsTheRoom:
    """One behavioural pass, so the re-export is proven to carry real answers."""

    def test_fleet_branches_through_the_gateway_matches_the_handler(self):
        repo_root = registry_scope.find_repo_root()
        assert fleet.fleet_branches(repo_root) == registry_scope.fleet_branches(repo_root)


class TestTheTopFileIsTheOneDoor:
    """from aipass.memory import <name>: each name from its real home, lazily, never cached."""

    def test_the_public_list_is_exactly_the_hand_written_table(self):
        assert sorted(door.__all__) == sorted(name for _, name in DOOR_NAMES)
        assert set(door.__all__) <= set(dir(door))

    @pytest.mark.parametrize(("home", "name"), DOOR_NAMES)
    def test_every_name_is_the_same_object_as_its_home_s(self, home, name):
        assert getattr(door, name) is getattr(importlib.import_module(home), name)

    @pytest.mark.parametrize("name", ["fleet", "door_entry_limits", "accepted_resident_paths", "_refuse"])
    def test_an_unknown_name_raises_attribute_error_with_no_fallback(self, name):
        with pytest.raises(AttributeError, match=name):
            getattr(door, name)

    @pytest.mark.parametrize(("home", "name"), DOOR_NAMES)
    def test_a_patch_on_the_home_reaches_a_caller_that_read_the_door_before(self, monkeypatch, home, name):
        """A door that caches the first answer hands later callers the unpatched name."""
        getattr(door, name)
        sentinel = object()
        monkeypatch.setattr(importlib.import_module(home), name, sentinel)
        assert getattr(door, name) is sentinel

    def test_a_bare_import_loads_nothing_under_apps(self):
        assert _fresh("import aipass.memory") == []

    @pytest.mark.parametrize("home", list(DOOR_HOMES))
    def test_each_name_loads_no_more_than_its_home_alone(self, home):
        """No door_ module, no other home: the door's reach equals a direct import of the home."""
        names = DOOR_HOMES[home]
        through_door = _fresh(f"import aipass.memory as d\nfor n in {names!r}: getattr(d, n)")
        direct = _fresh(f"importlib.import_module({home!r})")
        assert through_door == direct
        assert not [m for m in through_door if ".door_" in m]

    def test_a_foreign_branch_passes_the_handlers_fence_through_the_door(self, tmp_path):
        """The fence refuses a foreign importer of handlers; the door is kin acting on its behalf."""
        seat = tmp_path / "aipass" / "foreign" / "probe.py"
        seat.parent.mkdir(parents=True)
        seat.write_text("from aipass.memory import fleet_branches, load_entry_limits\n", encoding="utf-8")
        loaded = _fresh(f"import runpy\nrunpy.run_path({str(seat)!r}, run_name='__main__')", cwd=tmp_path)
        assert f"{_H}.monitor.registry_scope" in loaded
        assert f"{_H}.json.entry_limits" in loaded
