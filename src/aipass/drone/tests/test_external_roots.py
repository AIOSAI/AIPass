# =================== AIPass ====================
# Name: test_external_roots.py
# Description: Declared roots are the third resolution source
# Version: 1.0.0
# Created: 2026-08-30
# =============================================

"""Citizens in declared roots resolve, and never at a local citizen's expense.

FPLAN-0460 phase 3. @memory owns AIPASS_ROOTS.json and is its ONLY reader; this
branch consumes the records their gateway returns and decides precedence.

Two rulings from @devpulse are pinned here rather than described:

  DECLARATION IS THE CREDENTIAL — an external registry can never satisfy the
  metadata.id check, because the ids differ by construction. The gate asks an
  intra-installation question and a cross-repo answer is not available to it.

  PRECEDENCE — AIPass local always wins; declaration order breaks ties among
  externals; collisions are logged on both sides rather than resolved quietly.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.apps.modules import fleet
from aipass.drone.apps.handlers import registry_handler


# ---------------------------------------------------------------------------
# Fixtures — stand-in roots, never a write into a sibling repo
# ---------------------------------------------------------------------------


def _make_root(base: Path, repo: str, branches: list[tuple[str, str]]) -> Path:
    """Build a stand-in external repo with its own sealed registry."""
    root = base / repo
    root.mkdir(parents=True)
    rows = []
    for name, rel in branches:
        branch = root / rel
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text("{}")
        rows.append({"name": name, "path": rel, "email": f"@{name.lower()}", "status": "active"})
    (root / f"{repo.upper()}_REGISTRY.json").write_text(
        json.dumps({"metadata": {"id": f"{repo}-id"}, "branches": rows})
    )
    return root


@pytest.fixture()
def local_world(tmp_path, monkeypatch):
    """A complete stand-in AIPass installation — registry, citizens, passport.

    CI has no ``AIPASS_REGISTRY.json``. It is gitignored and machine-local, so a
    clean checkout has neither it nor ``AIPASS_ROOTS.json``. Four tests below
    used the REAL machine's registry as their "local wins" baseline: green on
    every developer box, red on every bare runner, with the failure reading
    ``primary registry unavailable`` rather than anything about precedence.

    The hermeticity pass that preceded this one pinned both states of the ROOTS
    file and assumed the REGISTRY existed. Half a world is not a world. What
    these tests pin is precedence BETWEEN sources, which is a rule about the
    resolver and not a fact about this machine — so the local source is now
    built rather than borrowed.

    The world is self-consistent on purpose: ``metadata.id`` matches the
    passport ``registry_id`` and ``caller_cwd`` points inside it, so the
    credential gate passes on MERIT. A stand-in that simply omitted the id would
    pass by being unverifiable, which is a different reason with the same colour.
    """
    world = tmp_path / "StandInAIPass"
    registry_id = "standin-registry-id"
    for name in ("drone", "memory"):
        trinity = world / "src" / name / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(json.dumps({"citizenship": {"registry_id": registry_id}}))
    (world / "AIPASS_REGISTRY.json").write_text(
        json.dumps(
            {
                "metadata": {"id": registry_id},
                "branches": [
                    {"name": "drone", "path": "src/drone", "email": "@drone", "status": "active"},
                    {"name": "memory", "path": "src/memory", "email": "@memory", "status": "active"},
                ],
            }
        )
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
    (home / "AIPASS_REGISTRY.json").write_text(json.dumps({"metadata": {"id": "home-id"}, "branches": []}))
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
        )
    )
    return home


# ---------------------------------------------------------------------------
# The unblessed file — today's behaviour, pinned
# ---------------------------------------------------------------------------


class TestTheStandInWorldIsSealed:
    """The fixture's isolation is a test, not a hope.

    ``local_world`` unsets AIPASS_HOME because that is the SECOND resolution
    source and a stand-in world that still answers through the real machine is
    not a stand-in. Every other test here hits the primary registry first, so
    dropping the ``delenv`` changed no result anywhere and the guard survived
    mutation — an isolation nobody can observe is an isolation that quietly
    stops working.

    Observable now: a citizen of the REAL installation, absent from the
    stand-in, must not resolve inside it. On a bare runner AIPASS_HOME is unset
    and this passes for the trivial reason; on a developer machine it passes
    only because the fixture sealed the world. Both are correct answers to the
    same question, which is what makes it safe to run in both.
    """

    def test_a_real_citizen_absent_from_the_stand_in_does_not_resolve(self, local_world):
        with patch.object(fleet, "external_branches", return_value=[]):
            assert registry_handler.get_branch_by_name("trigger") is None


class TestNothingMovesUntilPatrickBlesses:
    """The tier is driven by the declared file and by nothing else.

    This class first pinned "declared_roots() is empty on this machine", which
    was true for about twenty minutes. AIPASS_ROOTS.json was blessed mid-build
    and the pin went red — correctly, because it asserted a machine STATE rather
    than a rule. A test that a file has not been created yet expires the moment
    someone creates it. What is durable is that a project with no declared roots
    resolves exactly as it did before the tier existed.
    """

    def test_a_project_with_no_declared_roots_sees_no_externals(self, tmp_path):
        """The empty state is legal and silent — not an error, not a fallback."""
        assert registry_handler._external_branches(repo_root=tmp_path) == []

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


# ---------------------------------------------------------------------------
# The third source
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Precedence — @devpulse's ruling
# ---------------------------------------------------------------------------


def _external(name: str, root: str) -> dict:
    return {
        "name": name,
        "path": Path(f"/tmp/{root}/src/{name}"),
        "registry": f"{root.upper()}_REGISTRY.json",
        "email": f"@{name}",
        "residency": fleet.RESIDENCY_EXTERNAL,
    }
    # Five keys, matching registry_scope 4.0.0 exactly. `scheduler` was here
    # until @memory dropped it: it reported ONE filename while @daemon reads
    # .daemon/*.json, so a consumer pre-filtering on it would silently lose
    # every job in a differently-named file. A stand-in more generous than the
    # real reader is how a guard stops being observable — the same species as
    # the name_from mutant that survived because this fixture once gave a
    # directory and its registry row the same name.


class TestPrecedence:
    def test_aipass_local_always_wins(self, local_world):
        """An external named 'memory' must never shadow the local @memory.

        Stated as "the impostor changes nothing", not as "the answer lives under
        this file's tree". The first cut asked the second question and it failed
        the moment the suite ran anywhere but here: @seedgo's hygiene gate runs
        it from an rsync'd copy in /tmp, where resolution answers correctly
        through AIPASS_HOME with a path in the REAL tree and the proxy assertion
        called that a loss. The impostor never won in either run — only the
        yardstick moved.

        With a built world the yardstick is nailed down, so the stronger
        assertion is available again and made: the answer is the stand-in's own
        citizen, by path.
        """
        with patch.object(fleet, "external_branches", return_value=[]):
            undisturbed = registry_handler.get_branch_by_name("memory")

        with patch.object(fleet, "external_branches", return_value=[_external("memory", "impostor")]):
            branch = registry_handler.get_branch_by_name("memory")

        assert undisturbed is not None and branch is not None, "the local @memory stopped resolving"
        assert branch["path"] == undisturbed["path"], branch["path"]
        assert branch["path"] == str(local_world / "src" / "memory"), branch["path"]
        assert "impostor" not in branch["path"], branch["path"]

    def test_declaration_order_breaks_ties_among_externals(self, local_world):
        first = _external("shared", "alpha")
        second = _external("shared", "beta")
        with patch.object(fleet, "external_branches", return_value=[first, second]):
            branch = registry_handler.get_branch_by_name("shared")

        assert branch is not None, "a tie among externals resolved to nothing"
        assert "alpha" in branch["path"], "the earlier declared root must win"

    def test_a_local_external_collision_is_logged_on_both_sides(self, local_world):
        with patch.object(fleet, "external_branches", return_value=[_external("memory", "impostor")]):
            with patch.object(registry_handler, "logger") as log:
                registry_handler.get_all_branches()

        collisions = [c for c in log.warning.call_args_list if "collision" in str(c).lower()]
        assert collisions, "a shadowed external citizen must not vanish quietly"
        assert any("memory" in str(c) for c in collisions)


# ---------------------------------------------------------------------------
# The gateway is another branch's code — it must not take routing down
# ---------------------------------------------------------------------------


class TestGatewayFailureIsContained:
    def test_local_resolution_survives_a_broken_gateway(self, local_world):
        with patch.object(fleet, "external_branches", side_effect=RuntimeError("gateway down")):
            assert registry_handler.get_branch_by_name("nosuchbranch") is None

    def test_a_broken_gateway_is_loud(self, local_world):
        with patch.object(fleet, "external_branches", side_effect=RuntimeError("gateway down")):
            with patch.object(registry_handler, "logger") as log:
                registry_handler.get_branch_by_name("nosuchbranch")

        assert log.error.called, "losing the external tier must never pass in silence"


# ---------------------------------------------------------------------------
# The gateway's shape is another branch's contract — it can move
# ---------------------------------------------------------------------------


class TestMalformedRecordsAreSkippedNotTrusted:
    """A record missing what resolution needs is refused BY NAME, never routed.

    @memory's record grew from three keys to six today. If it moves again, a
    row this branch cannot key on must drop out with a line saying so — routing
    a citizen whose path is None is a crash somewhere further from the cause.
    """

    @pytest.mark.parametrize(
        "broken",
        [
            {"path": Path("/tmp/x/src/a"), "registry": "X_REGISTRY.json"},
            {"name": "a", "registry": "X_REGISTRY.json"},
            {"name": "a", "path": Path("/tmp/x/src/a")},
            {"name": "", "path": Path("/tmp/x/src/a"), "registry": "X_REGISTRY.json"},
        ],
        ids=["no-name", "no-path", "no-registry", "empty-name"],
    )
    def test_a_record_missing_a_required_key_is_dropped(self, broken):
        with patch.object(fleet, "external_branches", return_value=[broken]):
            assert registry_handler._external_branches() == []

    def test_the_dropped_record_is_named(self):
        with patch.object(fleet, "external_branches", return_value=[{"name": "a"}]):
            with patch.object(registry_handler, "logger") as log:
                registry_handler._external_branches()

        assert log.warning.called, "a record dropped without a line is a citizen that vanished"

    def test_a_good_record_beside_a_broken_one_still_resolves(self):
        good = _external("keeper", "alpha")
        with patch.object(fleet, "external_branches", return_value=[{"name": "a"}, good]):
            entries = registry_handler._external_branches()

        assert [e["name"] for e in entries] == ["keeper"]


# ---------------------------------------------------------------------------
# The whole chain, not just the lookup
# ---------------------------------------------------------------------------


class TestResolutionEndToEnd:
    def test_an_external_citizen_resolves_all_the_way_through_resolve_branch(self, standin):
        """resolve_branch is the door every routed command comes through.

        The link worth pinning is the LAST one: _validate_branch_path refuses a
        branch path that escapes its project root, and an external citizen's
        path escapes OURS by definition. It passes because the root it is
        checked against is the external registry's own parent, not AIPass —
        which is only true because get_branch_with_registry hands back the
        sealed registry the entry was read from.
        """
        from aipass.drone.apps.modules.resolver import resolve_branch

        with patch.object(
            fleet,
            "external_branches",
            side_effect=lambda _root=None, **kw: registry_scope.external_branches(standin, **kw),
        ):
            resolved = resolve_branch("@alpha_agent")

        assert resolved.endswith("alpha/src/alpha/worker")

    def test_an_undeclared_repo_is_still_refused(self, standin):
        from aipass.drone.apps.modules.resolver import BranchNotFoundError, resolve_branch

        with patch.object(
            fleet,
            "external_branches",
            side_effect=lambda _root=None, **kw: registry_scope.external_branches(standin, **kw),
        ):
            with pytest.raises(BranchNotFoundError):
                resolve_branch("@gamma_agent")


class TestTheTierIsScopedToTheProjectBeingResolved:
    """The real machine's declared roots must not leak into another project.

    This is the regression that got through: the tier read THIS checkout's
    AIPASS_ROOTS.json no matter which registry the caller had pointed at, so the
    moment the file was blessed, eight enumeration tests across two files began
    seeing six real external citizens. The suite already isolated the AIPASS_HOME
    source with a fixture that unsets its env var — a third source with no
    equivalent scope is a third source nobody can test around.
    """

    def test_enumeration_scopes_the_tier_to_the_registry_it_was_handed(self, standin, monkeypatch):
        """get_all_branches must read the roots beside ITS registry, not the process cwd.

        Pointed at a stand-in home, enumeration returns that home's two declared
        citizens and none of this machine's — the leak, stated as an assertion.
        """
        from aipass.drone.apps.handlers.registry_handler import (
            reset_registry_path,
            set_registry_path,
        )

        monkeypatch.delenv("AIPASS_HOME", raising=False)  # the SECOND source, isolated the way the suite already does
        registry = standin / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps(
                {
                    "metadata": {"id": "7087bb93-570f-4b9a-b035-4fd7f570200e"},
                    "branches": [],
                }
            )
        )
        try:
            set_registry_path(registry)
            names = {b["name"] for b in registry_handler.get_all_branches()}
        finally:
            reset_registry_path()

        assert names == {"alpha_agent", "beta_agent"}  # enumeration lowercases names

    def test_the_scope_follows_the_registry_not_the_checkout(self, standin, tmp_path):
        """A project WITH declared roots sees its own, not ours."""
        assert registry_handler._external_branches(repo_root=standin)
        assert registry_handler._external_branches(repo_root=tmp_path / "nowhere") == []


class TestTheHomeFallbackDoesNotSwallowTheThirdSource:
    """A MISS in the AIPASS_HOME registry must not end the search.

    Found by running the suite from a machine whose AIPass home is not the
    project registry — the state @devpulse asked me to prove green. Two pins in
    this file went red there and neither was about the roots file: on that
    layout ``home_path != primary_path``, and ``get_branch_by_name`` RETURNED
    the home registry's lookup whether or not it found anything, so the external
    tier below it was unreachable. Its sibling ``get_branch_with_registry``
    guards the same lookup with ``if branch is not None`` and falls through.
    Two functions answering the same question two ways is the defect; the
    external tier just made it observable.
    """

    def test_a_home_registry_miss_still_reaches_a_declared_root(self, tmp_path, monkeypatch):
        home = tmp_path / "elsewhere"
        home.mkdir()
        (home / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}))
        monkeypatch.setenv("AIPASS_HOME", str(home))

        with patch.object(fleet, "external_branches", return_value=[_external("shared", "alpha")]):
            branch = registry_handler.get_branch_by_name("shared")

        assert branch is not None, "the home registry missed — it did not answer"
        assert branch["name"] == "shared"

    def test_a_home_registry_hit_still_wins_over_an_external(self, tmp_path, monkeypatch):
        """Falling through on a miss must not turn into skipping the home tier."""
        home = tmp_path / "elsewhere"
        home.mkdir()
        (home / "AIPASS_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "shared", "path": "src/home/shared", "email": "@shared"}]})
        )
        monkeypatch.setenv("AIPASS_HOME", str(home))

        with patch.object(fleet, "external_branches", return_value=[_external("shared", "alpha")]):
            branch = registry_handler.get_branch_by_name("shared")

        assert branch is not None, "the AIPass home citizen did not resolve"
        assert "home" in str(branch["path"]), "AIPass home outranks a declared root"


class TestTheStandInMatchesTheRealReader:
    """The fixture's shape is pinned to @memory's reader, not to my memory of it.

    The record moved twice in one day — three keys to six, then six to five —
    and both times I learned about it by mail. A stand-in that describes a shape
    the reader no longer produces is how a guard stops being observable, so the
    comparison is a test now: @memory's REAL reader runs against a stand-in root
    here, and its keys must be exactly the keys ``_external`` builds.
    """

    def test_the_helper_builds_exactly_the_keys_the_gateway_returns(self, standin):
        produced = registry_scope.external_branches(standin)

        assert produced, "the stand-in declares two roots — the reader found neither"
        assert set(produced[0]) == set(_external("shared", "alpha")), (
            f"reader returns {sorted(produced[0])}, fixture builds {sorted(_external('shared', 'alpha'))}"
        )


class TestTheGatewaysImportCannotTakeDroneDown:
    """Containment must hold at IMPORT, not only at the call.

    ``TestGatewayFailureIsContained`` pinned a gateway that RAISES when called.
    The import itself was not pinned, and it was the unguarded half:
    ``registry_handler`` carried ``from aipass.memory.apps.modules import fleet``
    at module level, so anything raising inside @memory's import chain killed
    every import of drone — the router, ``drone rm``, ``drone systems``, all of
    it — before a single guard in this branch could run.

    Not hypothetical, and it is the CI red this class was written for.
    @memory's ``registry_scope.py`` runs ``REPO_ROOT = find_repo_root()`` at
    module level, and ``find_repo_root`` falls back to ``Path.cwd()`` when the
    walk up from ``__file__`` finds no ``AIPASS_REGISTRY.json``. A clean
    checkout has no registry (it is gitignored and machine-local), so a bare
    runner takes that fallback — and a process whose directory was deleted
    raises ENOENT there. Reported to @memory as theirs to fix; contained here
    because a consumer that dies with its dependency has no containment at all.

    The finder is a real import failure, not a mock: nothing this branch can
    patch reproduces a module that will not import.
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
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)

        assert result.returncode == 0, result.stderr
        assert "imported registry_handler" in result.stdout

    def test_a_gateway_that_will_not_import_is_contained_and_loud(self, tmp_path):
        """The tier is lost, resolution is not, and the loss is on the record."""
        import builtins

        real_import = builtins.__import__

        def refuse_memory(name, *args, **kwargs):
            if name.startswith("aipass.memory"):
                raise ImportError("simulated bare-world crash inside @memory")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", refuse_memory):
            with patch.object(registry_handler, "logger") as log:
                entries = registry_handler._external_branches(repo_root=tmp_path)

        assert entries == []
        assert log.error.called, "losing the tier at import must never pass in silence"
