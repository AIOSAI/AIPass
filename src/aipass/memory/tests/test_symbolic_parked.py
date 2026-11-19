# =================== AIPass ====================
# Name: test_symbolic_parked.py
# Description: Pins the refusal surfaces of the parked symbolic fragments tier (the owner's ruling, 2026-08-14)
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-11-17
# =============================================

"""Tests for apps/modules/symbolic.py and the parked handlers/symbolic package."""

# The declared pass — what is NOT tested here, and what covers it instead:

import importlib
from pathlib import Path

import pytest

from aipass.memory.apps.modules import symbolic
from aipass.memory import new_state, should_surface

_SUBCOMMANDS = ["demo", "analyze", "extract", "bootstrap", "fragments", "hook-test"]


def _names_the_ruling(text: str) -> bool:
    """A parked surface must say what happened, when, and where to go instead."""
    lowered = text.lower()
    return "parked" in lowered and "2026-08-14" in text and "compass" in lowered


class TestModuleSurfaceParked:
    """`drone @memory symbolic ...` must refuse loudly, not quietly do nothing."""

    def test_no_args_introspection_says_parked(self, capsys):
        symbolic.handle_command("symbolic", [])
        out = capsys.readouterr().out
        assert _names_the_ruling(out), out

    def test_help_explains_the_park_without_executing(self, capsys):
        """Help flag anywhere explains, never executes — and never exits non-zero."""
        symbolic.handle_command("symbolic", ["--help"])
        out = capsys.readouterr().out
        assert _names_the_ruling(out), out

    @pytest.mark.parametrize("sub", _SUBCOMMANDS)
    def test_invoking_a_subcommand_fails_loudly(self, sub, capsys):
        """Fail honest: a caller checking the exit code must see failure."""
        with pytest.raises(SystemExit) as exc:
            symbolic.handle_command("symbolic", [sub, "whatever"])

        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert _names_the_ruling(captured.err), captured.err
        assert captured.out == "", "a refusal belongs on stderr, not mixed into output"

    @pytest.mark.parametrize("sub", _SUBCOMMANDS)
    def test_legacy_direct_routing_also_refuses(self, sub, capsys):
        """The entry point can send these without the `symbolic` prefix."""
        with pytest.raises(SystemExit):
            symbolic.handle_command(sub, [])

        assert _names_the_ruling(capsys.readouterr().err)

    def test_a_foreign_command_is_still_declined_not_claimed(self):
        """Parking must not turn this module into a catch-all router."""
        assert symbolic.handle_command("rollover", []) is False

    def test_calling_a_parked_function_names_the_ruling(self):
        """The old public API is gone — asking for it must explain, not AttributeError blankly."""
        with pytest.raises(Exception) as exc:
            symbolic.analyze_conversation

        assert _names_the_ruling(str(exc.value)), str(exc.value)


class TestHandlerPackageParked:
    """Importing the tier is the other way in. It must hit the same wall."""

    def test_importing_the_handler_package_names_the_ruling(self):
        with pytest.raises(Exception) as exc:
            importlib.import_module("aipass.memory.apps.handlers.symbolic")

        assert _names_the_ruling(str(exc.value)), str(exc.value)

    @pytest.mark.parametrize("submodule", ["extractor", "deduplicator", "hook", "storage", "retriever"])
    def test_importing_a_submodule_hits_the_same_wall(self, submodule):
        """A submodule import runs the package __init__ first — no side door."""
        with pytest.raises(Exception) as exc:
            importlib.import_module(f"aipass.memory.apps.handlers.symbolic.{submodule}")

        assert _names_the_ruling(str(exc.value)), str(exc.value)


class TestLiveLaneUntouched:
    """Nothing that runs today may lose a thing to this park."""

    def test_handlers_package_no_longer_pulls_symbolic_in(self):
        """`from . import symbolic` in handlers/__init__ ran on EVERY live import."""
        source = (Path(__file__).resolve().parent.parent / "apps" / "handlers" / "__init__.py").read_text(
            encoding="utf-8"
        )
        live = [ln for ln in source.splitlines() if ln.strip().startswith("from . import symbolic")]
        assert live == [], f"live lane still imports the parked tier: {live}"

    def test_the_live_entry_points_still_import(self):
        for dotted in (
            "aipass.memory.apps.handlers.intake.auto_process",
            "aipass.memory.apps.handlers.rollover.orchestrator",
            "aipass.memory.apps.handlers.monitor.detector",
            "aipass.memory.apps.modules.rollover",
            "aipass.memory.apps.modules.search",
            "aipass.memory.apps.modules.governance",
        ):
            assert importlib.import_module(dotted).__name__ == dotted

    def test_governance_is_not_parked(self):
        """Governance is a SEPARATE tier and is live on the prompt lane (@hooks compass_recall)."""
        surfaced, reason, state = should_surface("item-1", 0.9, new_state())
        assert surfaced is True, reason

    def test_the_orphaned_embedder_left_the_live_tree(self):
        """Parked with the tier (devpulse's ruling) — its only importers were symbolic's."""
        vector_dir = Path(__file__).resolve().parent.parent / "apps" / "handlers" / "vector"
        assert not (vector_dir / "embedder.py").exists()
        assert (vector_dir / "embed_subprocess.py").is_file(), "the live lane's script must stay"
