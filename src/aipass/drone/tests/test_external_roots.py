# =================== AIPass ====================
# Name: test_external_roots.py
# Description: Declared roots are the third resolution source
# Version: 1.0.4
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/registry_handler.py's declared-roots tier: externals resolve, never over a local."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.memory.apps.modules import door_registry_scope as registry_scope
from aipass.memory.apps.modules import fleet
from aipass.drone.apps.handlers import registry_handler
from aipass.drone.apps.handlers.registry_handler import reset_registry_path, set_registry_path
from aipass.drone.apps.modules.resolver import BranchNotFoundError, resolve_branch


# @memory alone reads AIPASS_ROOTS.json. Declaration is the credential: an external metadata.id never matches.
# Precedence: AIPass local always wins, declaration order breaks external ties, collisions log both sides.


def _make_root(base: Path, repo: str, branches: list[tuple[str, str]]) -> Path:
    """Build a stand-in external repo with its own sealed registry."""
    root = base / repo
    root.mkdir(parents=True)
    rows = []
    for name, rel in branches:
        branch = root / rel
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        rows.append({"name": name, "path": rel, "email": f"@{name.lower()}", "status": "active"})
    (root / f"{repo.upper()}_REGISTRY.json").write_text(
        json.dumps({"metadata": {"id": f"{repo}-id"}, "branches": rows}),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def local_world(tmp_path, monkeypatch):
    """A complete stand-in AIPass installation — registry, citizens, passport.

    CI has no ``AIPASS_REGISTRY.json`` (gitignored), so the world is built; its ``metadata.id`` matches
    the passport ``registry_id`` and ``caller_cwd`` is inside it, so the credential gate passes on merit.
    """
    world = tmp_path / "StandInAIPass"
    registry_id = "standin-registry-id"
    for name in ("drone", "memory"):
        trinity = world / "src" / name / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(
            json.dumps({"citizenship": {"registry_id": registry_id}}), encoding="utf-8"
        )
    (world / "AIPASS_REGISTRY.json").write_text(
        json.dumps(
            {
                "metadata": {"id": registry_id},
                "branches": [
                    {"name": "drone", "path": "src/drone", "email": "@drone", "status": "active"},
                    {"name": "memory", "path": "src/memory", "email": "@memory", "status": "active"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AIPASS_HOME", raising=False)
    monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
    monkeypatch.setattr(registry_handler, "caller_cwd", lambda: world / "src" / "drone")
    registry_handler.set_registry_path(world / "AIPASS_REGISTRY.json")
    yield world
    registry_handler.reset_registry_path()


@pytest.fixture()
def standin(tmp_path):
    """An AIPass home with declared roots, read by @memory's REAL reader."""
    home = tmp_path / "AIPassHome"
    home.mkdir()
    (home / "AIPASS_REGISTRY.json").write_text(
        json.dumps({"metadata": {"id": "home-id"}, "branches": []}), encoding="utf-8"
    )
    _make_root(tmp_path, "alpha", [("ALPHA_AGENT", "src/alpha/worker")])
    _make_root(tmp_path, "beta", [("BETA_AGENT", "src/beta/helper")])
    (home / "AIPASS_ROOTS.json").write_text(
        json.dumps(
            {
                "metadata": {"version": "1.0.0"},
                "roots": [
                    {"path": "../alpha", "label": "alpha", "status": "active"},
                    {"path": "../beta", "label": "beta", "status": "active"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return home


class TestTheStandInWorldIsSealed:
    """The fixture's isolation is a test, not a hope.

    ``local_world`` unsets AIPASS_HOME (the second source); a real citizen absent from the
    stand-in must not resolve inside it, or the seal stops working unobserved.
    """

    def test_a_real_citizen_absent_from_the_stand_in_does_not_resolve(self, local_world):
        with patch.object(fleet, "external_branches", return_value=[]):
            assert registry_handler.get_branch_by_name("trigger") is None


class TestNothingMovesUntilTheOwnerBlesses:
    """The tier is driven by the declared file and by nothing else.

    A rule, not a machine state: a project with no declared roots resolves as if the tier did not exist.
    """

    def test_a_project_with_no_declared_roots_sees_no_externals(self, local_world):
        """The empty state is legal and silent — not an error, not a fallback (mutant killed: a fallback citizen)."""
        with patch.object(registry_handler, "logger") as log:
            names = {b["name"] for b in registry_handler.get_all_branches()}

        assert names == {"drone", "memory"}
        assert log.error.call_args_list == []

    def test_no_external_source_is_consulted_when_nothing_is_declared(self, local_world):
        with patch.object(fleet, "external_branches", return_value=[]) as gateway:
            assert registry_handler.get_branch_by_name("drone") is not None
        assert not gateway.called, "a local hit must never pay for a cross-repo read"

    def test_a_local_citizen_still_resolves_unchanged(self, local_world):
        branch = registry_handler.get_branch_by_name("memory")
        assert branch is not None
        assert branch["name"] == "memory"
        assert branch["path"] == str(local_world / "src" / "memory")

    def test_an_unknown_name_is_still_not_found(self, local_world):
        with patch.object(fleet, "external_branches", return_value=[]):
            assert registry_handler.get_branch_by_name("nosuchbranch") is None


class TestDeclaredRootsResolve:
    def test_an_external_citizen_resolves_through_memorys_real_reader(self, standin):
        """End to end against the gateway, not against a mock of it."""
        with patch.object(
            fleet,
            "external_branches",
            side_effect=lambda _root=None, **kw: registry_scope.external_branches(standin, **kw),
        ):
            result = registry_handler.get_branch_with_registry("alpha_agent")

        assert result is not None, "a declared root's citizen did not resolve"
        branch, registry_path = result
        assert branch["name"] == "alpha_agent"
        assert registry_path.name == "ALPHA_REGISTRY.json"

    def test_the_external_path_is_absolute_and_inside_its_own_root(self, standin):
        with patch.object(
            fleet,
            "external_branches",
            side_effect=lambda _root=None, **kw: registry_scope.external_branches(standin, **kw),
        ):
            found = registry_handler.get_branch_with_registry("beta_agent")

        assert found is not None, "the declared root's citizen did not resolve at all"
        branch, registry_path = found
        path = Path(branch["path"])
        assert path.is_absolute()
        assert registry_path.parent in path.parents

    def test_externals_appear_in_the_enumeration(self, standin):
        with patch.object(
            fleet,
            "external_branches",
            side_effect=lambda _root=None, **kw: registry_scope.external_branches(standin, **kw),
        ):
            names = {b["name"] for b in registry_handler.get_all_branches()}

        assert {"alpha_agent", "beta_agent"} <= names


# A path the malformed records below merely carry: never resolved, never what is wrong.
_SOME_PATH = Path(tempfile.gettempdir()) / "x" / "src" / "a"


def _external(name: str, root: str) -> dict:
    # tempfile.gettempdir(), not a "/tmp" literal: Windows CI runs this suite and has no /tmp.
    return {
        "name": name,
        "path": Path(tempfile.gettempdir()) / root / "src" / name,
        "registry": f"{root.upper()}_REGISTRY.json",
        "email": f"@{name}",
        "residency": fleet.RESIDENCY_EXTERNAL,
    }
    # Exactly registry_scope's keys: a stand-in more generous than the real reader hides guards.


class TestPrecedence:
    def test_aipass_local_always_wins(self, local_world):
        """An external named 'memory' must never shadow the local @memory."""
        with patch.object(fleet, "external_branches", return_value=[]):
            undisturbed = registry_handler.get_branch_by_name("memory")

        with patch.object(fleet, "external_branches", return_value=[_external("memory", "impostor")]):
            branch = registry_handler.get_branch_by_name("memory")

        assert undisturbed is not None and branch is not None, "the local @memory stopped resolving"
        assert branch["path"] == undisturbed["path"], branch["path"]
        assert branch["path"] == str(local_world / "src" / "memory"), branch["path"]
        assert "impostor" not in branch["path"], branch["path"]

    def test_declaration_order_breaks_ties_among_externals(self, local_world):
        """Mutant killed: the external tier walked in reverse declaration order."""
        first = _external("shared", "alpha")
        second = _external("shared", "beta")
        with patch.object(fleet, "external_branches", return_value=[first, second]):
            branch = registry_handler.get_branch_by_name("shared")

        assert branch is not None, "a declared citizen did not resolve at all"
        assert Path(branch["path"]) == Path(first["path"]), "the earlier declared root must win"

    def test_a_local_external_collision_is_logged_on_both_sides(self, local_world):
        with patch.object(fleet, "external_branches", return_value=[_external("memory", "impostor")]):
            with patch.object(registry_handler, "logger") as log:
                registry_handler.get_all_branches()

        collisions = [c for c in log.warning.call_args_list if "collision" in str(c).lower()]
        assert collisions, "a shadowed external citizen must not vanish quietly"
        assert any("memory" in str(c) for c in collisions)


class TestGatewayFailureIsContained:
    def test_local_resolution_survives_a_broken_gateway(self, local_world):
        with patch.object(fleet, "external_branches", side_effect=RuntimeError("gateway down")):
            assert registry_handler.get_branch_by_name("nosuchbranch") is None

    def test_a_broken_gateway_is_loud(self, local_world):
        with patch.object(fleet, "external_branches", side_effect=RuntimeError("gateway down")):
            with patch.object(registry_handler, "logger") as log:
                registry_handler.get_branch_by_name("nosuchbranch")

        assert log.error.called, "losing the external tier must never pass in silence"

    def test_a_lost_tier_answers_none_and_an_empty_fleet_answers_empty(self, local_world):
        """A lost tier and a fleet with no externals are two answers, not one.

        Mutant killed (runner): the gateway failure's None put back to [].
        """
        with patch.object(fleet, "external_branches", side_effect=RuntimeError("gateway down")):
            lost = registry_handler.external_branches()
        with patch.object(fleet, "external_branches", return_value=[]):
            empty = registry_handler.external_branches()

        assert lost is None, "a lost external tier must not read as an empty one"
        assert empty == []

    def test_a_tier_with_no_project_root_answers_none(self, local_world):
        """No project root to scope the declared roots is a lost tier, not an empty one.

        Mutant killed (runner): the no-root None put back to [].
        """
        with patch.object(registry_handler, "get_registry_path", side_effect=RuntimeError("no registry")):
            assert registry_handler.external_branches() is None

    def test_a_lost_tier_still_refuses_an_unknown_name_through_resolve_branch(self, local_world):
        """resolve_branch's lookup reads the lost tier as no externals, never as a crash.

        Mutant killed (runner): the lost tier's None handed straight to get_branch_with_registry's loop.
        """
        with patch.object(fleet, "external_branches", side_effect=RuntimeError("gateway down")):
            with pytest.raises(BranchNotFoundError, match="not found in registry"):
                resolve_branch("@nosuchbranch")


class TestMalformedRecordsAreSkippedNotTrusted:
    """A record missing what resolution needs is refused BY NAME, never routed.

    The record shape is @memory's contract and can move; a citizen routed with path None crashes far away.
    """

    @pytest.mark.parametrize(
        "broken",
        [
            {"path": _SOME_PATH, "registry": "X_REGISTRY.json"},
            {"name": "a", "registry": "X_REGISTRY.json"},
            {"name": "a", "path": _SOME_PATH},
            {"name": "", "path": _SOME_PATH, "registry": "X_REGISTRY.json"},
        ],
        ids=["no-name", "no-path", "no-registry", "empty-name"],
    )
    def test_a_record_missing_a_required_key_is_dropped(self, broken, local_world):
        """Mutant killed: the required-key check removed."""
        with patch.object(fleet, "external_branches", return_value=[broken]):
            names = {b["name"] for b in registry_handler.get_all_branches()}

        assert names == {"drone", "memory"}

    def test_the_dropped_record_is_named(self, local_world):
        """Mutant killed: the malformed-record warning removed."""
        with patch.object(fleet, "external_branches", return_value=[{"name": "a"}]):
            with patch.object(registry_handler, "logger") as log:
                registry_handler.get_all_branches()

        named = [c.args[1] for c in log.warning.call_args_list if len(c.args) > 1]
        assert {"name": "a"} in named, "a record dropped without a line is a citizen that vanished"

    def test_a_good_record_beside_a_broken_one_still_resolves(self, local_world):
        """Mutant killed: a malformed record ending the walk instead of being skipped."""
        good = _external("keeper", "alpha")
        with patch.object(fleet, "external_branches", return_value=[{"name": "a"}, good]):
            names = {b["name"] for b in registry_handler.get_all_branches()}

        assert names == {"drone", "memory", "keeper"}


class TestResolutionEndToEnd:
    def test_an_external_citizen_resolves_all_the_way_through_resolve_branch(self, standin):
        """resolve_branch is the door every routed command comes through.

        _validate_branch_path refuses a path escaping its project root; an external passes only because
        get_branch_with_registry hands back the sealed registry the entry was read from.
        """
        with patch.object(
            fleet,
            "external_branches",
            side_effect=lambda _root=None, **kw: registry_scope.external_branches(standin, **kw),
        ):
            resolved = resolve_branch("@alpha_agent")

        # Path parts, not a string suffix: Windows CI's separator is not "/".
        assert Path(resolved).parts[-4:] == ("alpha", "src", "alpha", "worker"), resolved

    def test_an_undeclared_repo_is_still_refused(self, standin):
        with patch.object(
            fleet,
            "external_branches",
            side_effect=lambda _root=None, **kw: registry_scope.external_branches(standin, **kw),
        ):
            with pytest.raises(BranchNotFoundError):
                resolve_branch("@gamma_agent")


class TestTheTierIsScopedToTheProjectBeingResolved:
    """The real machine's declared roots must not leak into another project."""

    def test_enumeration_scopes_the_tier_to_the_registry_it_was_handed(self, standin, monkeypatch):
        """get_all_branches must read the roots beside ITS registry, not the process cwd."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)  # the SECOND source, isolated the way the suite already does
        registry = standin / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps(
                {
                    "metadata": {"id": "7087bb93-570f-4b9a-b035-4fd7f570200e"},
                    "branches": [],
                }
            ),
            encoding="utf-8",
        )
        try:
            set_registry_path(registry)
            names = {b["name"] for b in registry_handler.get_all_branches()}
        finally:
            reset_registry_path()

        assert names == {"alpha_agent", "beta_agent"}  # enumeration lowercases names

    def test_the_scope_follows_the_registry_not_the_checkout(self, standin, tmp_path, monkeypatch):
        """A project WITH declared roots sees its own; mutant killed: roots read one level above the registry."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        # No metadata id: the credential gate passes on "nothing to compare", not on this machine's passport.
        (standin / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
        nowhere = tmp_path / "nowhere"
        nowhere.mkdir()
        (nowhere / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
        try:
            set_registry_path(standin / "AIPASS_REGISTRY.json")
            declared = {b["name"] for b in registry_handler.get_all_branches()}
            set_registry_path(nowhere / "AIPASS_REGISTRY.json")
            undeclared = {b["name"] for b in registry_handler.get_all_branches()}
        finally:
            reset_registry_path()

        assert declared == {"alpha_agent", "beta_agent"}
        assert undeclared == set()


class TestTheHomeFallbackDoesNotSwallowTheThirdSource:
    """A MISS in the AIPASS_HOME registry must not end the search.

    When ``home_path != primary_path``, ``get_branch_by_name`` must fall through on a home miss as
    ``get_branch_with_registry`` does (``if branch is not None``), or the external tier is unreachable.
    """

    def test_a_home_registry_miss_still_reaches_a_declared_root(self, tmp_path, monkeypatch):
        home = tmp_path / "elsewhere"
        home.mkdir()
        (home / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
        monkeypatch.setenv("AIPASS_HOME", str(home))

        with patch.object(fleet, "external_branches", return_value=[_external("shared", "alpha")]):
            branch = registry_handler.get_branch_by_name("shared")

        assert branch is not None, "the home registry missed — it did not answer"
        assert branch["name"] == "shared"

    def test_a_home_registry_hit_still_wins_over_an_external(self, tmp_path, monkeypatch):
        """Falling through on a miss must not skip the home tier; mutant killed: externals consulted first."""
        home = tmp_path / "elsewhere"
        home.mkdir()
        (home / "AIPASS_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "shared", "path": "src/home/shared", "email": "@shared"}]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("AIPASS_HOME", str(home))

        with patch.object(fleet, "external_branches", return_value=[_external("shared", "alpha")]):
            branch = registry_handler.get_branch_by_name("shared")

        assert branch is not None, "no source answered for a name two sources declare"
        assert Path(branch["path"]) == (home / "src" / "home" / "shared").resolve(), (
            "AIPass home outranks a declared root"
        )


class TestTheStandInMatchesTheRealReader:
    """The fixture's shape is pinned to @memory's reader, not to my memory of it."""

    def test_the_helper_builds_exactly_the_keys_the_gateway_returns(self, standin):
        produced = registry_scope.external_branches(standin)

        assert produced, "the stand-in declares two roots — the reader found neither"
        assert set(produced[0]) == set(_external("shared", "alpha")), (
            f"reader returns {sorted(produced[0])}, fixture builds {sorted(_external('shared', 'alpha'))}"
        )


class TestTheGatewaysImportCannotTakeDroneDown:
    """Containment must hold at IMPORT, not only at the call.

    Anything raising in @memory's import chain must not kill drone's import: on a bare runner,
    registry_scope's module-level find_repo_root falls back to Path.cwd(), ENOENT in a deleted cwd.
    The finder is a real import failure: no patch reproduces a module that will not import.
    """

    def test_drone_imports_when_the_gateway_module_cannot_be_imported(self):
        import subprocess
        import sys
        import textwrap

        probe = textwrap.dedent(
            """
            import importlib.abc, sys

            class Boom(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path, target=None):
                    if name.startswith("aipass.memory"):
                        raise FileNotFoundError("simulated bare-world crash inside @memory")
                    return None

            sys.meta_path.insert(0, Boom())
            from aipass.drone.apps.handlers import registry_handler
            print("imported", registry_handler.__name__.rsplit(".", 1)[-1])
            """
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8")

        assert result.returncode == 0, result.stderr
        assert "imported registry_handler" in result.stdout

    def test_a_gateway_that_will_not_import_is_contained_and_loud(self, local_world):
        """The tier is lost, resolution is not; mutant killed: the lost-tier error line removed.

        Refused at registry_handler's one import door, not by replacing ``builtins.__import__``.
        Mutant killed (runner): the gateway imported inline, past the door.
        """

        def refuse_memory():
            raise ImportError("simulated bare-world crash inside @memory")

        with patch.object(registry_handler, "_fleet_gateway", refuse_memory):
            with patch.object(registry_handler, "logger") as log:
                names = {b["name"] for b in registry_handler.get_all_branches()}

        assert names == {"drone", "memory"}
        assert "External tier unavailable" in log.error.call_args[0][0], "losing the tier must never pass in silence"
