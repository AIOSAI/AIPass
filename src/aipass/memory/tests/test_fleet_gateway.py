# =================== AIPass ====================
# Name: test_fleet_gateway.py
# Description: Pins the public cross-branch gateway for the fleet definition
# Version: 1.0.1
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/fleet.py."""

# modules/ is the public gateway; handlers/ is private. The mechanics of finding residents are not re-exported.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — declared_residency answers, in tests/test_residency_scope.py
# seedgo: no-test-needed(covered_elsewhere) — declared_roots values, in tests/test_declared_roots.py
# seedgo: no-test-needed(covered_elsewhere) — find_repo_root's walk, in tests/test_repo_root.py
# seedgo: no-test-needed(shared) — the json_handler.log_operation audit line; the json handler's lane

from pathlib import Path

import pytest

from aipass.cli.apps.modules import reset_command_state, resolve_exit
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
