# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_symbolic_parked.py
# Date: 2026-08-14
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Tests for parking the symbolic fragments tier (Patrick's ruling, 2026-08-14).

The Agent Memory Atlas review of AIPass memory (revision 0d27e5ef) flagged the
AUDN deduplicator: an LLM returns a Delete verdict and nothing records what was
removed or why — an unauditable deletion. The tier was never wired into any live
lane, and Compass became the curated-truth piece, so Patrick ruled: park it,
revivable, and say where the active piece is.

A park is only honest if it is loud. These tests pin the two halves:
  - every disabled surface names the ruling, its date, and Compass
  - nothing that runs today lost anything (the live lane never touched it)
"""

import importlib
from pathlib import Path

import pytest

from aipass.memory.apps.modules import symbolic

_ARCHIVE = Path(__file__).resolve().parent.parent / ".archive" / "parked_symbolic_20260814"

# Every subcommand the tier used to answer. All of them must now refuse.
_SUBCOMMANDS = ["demo", "analyze", "extract", "bootstrap", "fragments", "hook-test"]


def _names_the_ruling(text: str) -> bool:
    """A parked surface must say what happened, when, and where to go instead."""
    lowered = text.lower()
    return "parked" in lowered and "2026-08-14" in text and "compass" in lowered


# ---------------------------------------------------------------------------
# The CLI surface
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The programmatic surface
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The live lane
# ---------------------------------------------------------------------------


class TestLiveLaneUntouched:
    """Nothing that runs today may lose a thing to this park."""

    def test_handlers_package_no_longer_pulls_symbolic_in(self):
        """`from . import symbolic` in handlers/__init__ ran on EVERY live import."""
        source = (Path(__file__).resolve().parent.parent / "apps" / "handlers" / "__init__.py").read_text(
            encoding="utf-8"
        )
        live = [ln for ln in source.splitlines() if ln.strip().startswith("from . import symbolic")]
        assert not live, f"live lane still imports the parked tier: {live}"

    def test_the_live_entry_points_still_import(self):
        for dotted in (
            "aipass.memory.apps.handlers.intake.auto_process",
            "aipass.memory.apps.handlers.rollover.orchestrator",
            "aipass.memory.apps.handlers.monitor.detector",
            "aipass.memory.apps.modules.rollover",
            "aipass.memory.apps.modules.search",
            "aipass.memory.apps.modules.governance",
        ):
            assert importlib.import_module(dotted) is not None

    def test_governance_is_not_parked(self):
        """Governance is a SEPARATE tier and is live on the prompt lane (@hooks compass_recall)."""
        from aipass.memory.apps.modules.governance import should_surface, new_state

        surfaced, reason, state = should_surface("item-1", 0.9, new_state())
        assert surfaced is True, reason


# ---------------------------------------------------------------------------
# Revivability — a park, not a demolition
# ---------------------------------------------------------------------------


class TestRevivable:
    """Patrick may want this back. Everything must still be here."""

    @pytest.mark.parametrize(
        "relative",
        [
            "handlers/__init__.py",
            "handlers/chroma_client.py",
            "handlers/deduplicator.py",
            "handlers/extractor.py",
            "handlers/hook.py",
            "handlers/retriever.py",
            "handlers/storage.py",
            "modules/symbolic.py",
            "handlers_vector/embedder.py",
        ],
    )
    def test_implementation_is_preserved(self, relative):
        assert (_ARCHIVE / relative).is_file(), f"missing from the park: {relative}"

    def test_the_orphaned_embedder_left_the_live_tree(self):
        """Parked with the tier (devpulse's ruling) — its only importers were symbolic's."""
        vector_dir = Path(__file__).resolve().parent.parent / "apps" / "handlers" / "vector"
        assert not (vector_dir / "embedder.py").exists()
        assert (vector_dir / "embed_subprocess.py").is_file(), "the live lane's script must stay"

    def test_the_park_documents_its_own_revival(self):
        readme = _ARCHIVE / "README.md"
        assert readme.is_file()
        text = readme.read_text(encoding="utf-8")
        assert _names_the_ruling(text)
        assert "revive" in text.lower()
