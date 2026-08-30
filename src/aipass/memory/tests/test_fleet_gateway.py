# =================== AIPass ====================
# Name: test_fleet_gateway.py
# Description: Pins the public cross-branch gateway for the fleet definition
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""The fleet definition has one owner and now one door.

@daemon reported (dispatch 2a70bbcd) that the cross-branch import I sanctioned
fails two of @seedgo's checks at once. The rule is not arbitrary and it is not
"do not consume @memory" — ``handlers_check.py:310`` says another branch's
``modules`` package is its PUBLIC GATEWAY and sends cross-branch callers there
explicitly. ``apps/handlers/`` is private implementation.

So the seam moves, and nothing else does. ``registry_scope`` stays the single
definition; this module is the door to it, owned here rather than shimmed in
each consumer's tree — a gateway living in @daemon would be a second public
surface for my module in a branch I do not control, and the next consumer would
import theirs or write a third.

What is deliberately NOT re-exported is as much of the contract as what is:
``resident_registry_paths`` and ``read_registry_branches`` are the mechanics of
HOW residents are found, and they stop being the whole story the moment the
external tier lands.
"""

import importlib
from pathlib import Path

import pytest

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
    """A correction to my own first design, kept visible rather than quietly rewritten.

    I built this gateway with no ``handle_command``, reasoning that a library
    surface should stay invisible to ``apps/memory.py``'s duck-typed module
    discovery, and wrote a test asserting exactly that. The branch's own
    convention disagreed: ``health.py`` — the gateway built for the same
    consumer, for the same reason — is discoverable and answers introspection,
    and three @seedgo standards (cli, introspection, json_structure) fail
    without it. The convention won and the test inverted.

    What stays true either way is the part that matters: the CLI describes the
    contract and never executes fleet work. A gateway whose command surface
    starts answering fleet questions is the second definition all over again.
    """

    def test_it_answers_only_its_own_command(self):
        """A module that claims a command it does not own swallows another module's work."""
        assert fleet.handle_command("rollover", []) is False
        assert fleet.handle_command("search", ["x"]) is False

    @pytest.mark.parametrize("args", [[], ["--help"], ["-h"], ["help"]])
    def test_the_bare_command_and_every_help_spelling_introspect(self, capsys, args):
        assert fleet.handle_command("fleet", args) is True
        assert "fleet Module" in capsys.readouterr().out

    def test_an_unknown_subcommand_is_named_not_swallowed(self, capsys):
        """Claimed and reported, never a silent no-op that looks like success.

        Read from BOTH streams on purpose: the warning routes to stderr under
        @seedgo's output-routing standard, and asserting stdout alone made this
        red on the first run for a reason that had nothing to do with the
        behaviour being pinned.
        """
        assert fleet.handle_command("fleet", ["nonsense"]) is True
        captured = capsys.readouterr()
        assert "nonsense" in captured.out + captured.err

    def test_the_command_surface_executes_no_fleet_work(self, monkeypatch):
        """The pin that keeps this a door: the CLI must never answer the question itself."""
        called = []
        monkeypatch.setattr(registry_scope, "fleet_branches", lambda *a, **k: called.append(a) or [])
        monkeypatch.setattr(registry_scope, "accepted_resident_paths", lambda *a, **k: called.append(a) or set())
        fleet.handle_command("fleet", [])
        assert not called, "the gateway's CLI computed fleet state instead of describing the contract"

    def test_it_is_discovered_by_the_real_loops_own_rule(self):
        """Asserted against the discovery rule rather than trusted.

        ``apps/memory.py`` duck-types every file in ``modules/`` on
        ``handle_command``. This confirms the rule is still what the module was
        written against, so the shape above is deliberate and not incidental.
        """
        modules_dir = Path(fleet.__file__).parent
        commanded = []
        for path in sorted(modules_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            module = importlib.import_module(f"aipass.memory.apps.modules.{path.stem}")
            if hasattr(module, "handle_command"):
                commanded.append(path.stem)
        assert "fleet" in commanded
        assert "health" in commanded, "the precedent gateway no longer follows the convention this one copied"


class TestTheDoorAnswersTheSameAsTheRoom:
    """One behavioural pass, so the re-export is proven to carry real answers."""

    def test_fleet_branches_through_the_gateway_matches_the_handler(self):
        repo_root = registry_scope.find_repo_root()
        assert fleet.fleet_branches(repo_root) == registry_scope.fleet_branches(repo_root)
