# =================== AIPass ====================
# Name: test_host_roots.py
# Description: Tests for the roots roster and the widened name fence
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-08-18
# =============================================

"""Tests for the four-kind name fence and /v1/roots (FPLAN-0443 Phase 1).

Patrick, 2026-08-18: "rn I can only see into agent files... I cant explore
home. or project files outside agents."

THE FENCE IS NOT DELETED HERE, IT LEARNS MORE WORDS. The client still sends a
NAME and the server still decides what it means; what changed is that there are
now four kinds of name instead of one. So every test below that proves a root
resolves is paired with one proving the containment underneath still refuses —
a wider fence that stopped fencing would be the whole point thrown away.

THE EXPOSURE IS ON THE RECORD, not smuggled: with a `home` root and Patrick's
FULLY OPEN ruling (FPLAN-0443 Notes, his standing S247 line), a read-scope token
reads ~/.ssh and friends from the phone. The fixture below builds a `.ssh` and
the tests read through it deliberately, because a test suite that quietly
avoided the case would leave the ruling undocumented in the one place that runs.

Tests — resolve_root, the four kinds:
- branch kind answers exactly what resolve_branch_root answers
- branch kind with no name is refused (the existing sentence, unchanged)
- home kind resolves to the home directory
- aipass kind resolves to the seat's own repository root
- project kind resolves through @baud's census, never a composed path
- project kind matches the census spelling exactly, refusing a near miss
- an unknown kind is refused and the sentence names the four
- an EMPTY kind is refused here — the branch default lives in the read lane
- project kind with no name is refused
- census failure is ReadUnavailable in @baud's own words
- unknown project name is ReadRefused, not a 503
- a census row pointing nowhere is ReadUnavailable
- a census row naming no path is ReadUnavailable, never the server's cwd
- a registry row naming no path is ReadUnavailable, never the server's cwd
- a home that is not a directory is ReadUnavailable

Tests — kinds that name nothing refuse a name:
- a nameless root may name ITSELF (branch=home&root=home) — the carve-out
- the stand-in must equal the kind exactly, not merely resemble it
- a read stands on home through the stand-in, the wire shape end to end
- home with any OTHER name is refused rather than silently ignoring it
- aipass with a name is refused
- home with a project is refused (a project cannot scope a home directory)
- project kind with a project parameter is refused
- branch kind still honours project (the foreign-branch lane, untouched)

Tests — the fence covers every root:
- '..' refused under home
- an absolute name refused under a project root
- a symlink out of home refused by the post-resolution check
- an ordinary nested read under home is allowed (the fence is not a wall)

Tests — reads standing on a root:
- list_dir on home lists home's own level
- read_file on home returns the file's bytes
- the answer names the root it stood on
- noise directories are still filtered outside a branch
- the audit record names the root, so a home read is not indistinguishable
  from a branch read in the trail

Tests — absent root is today's answer plus the floor (the pin, re-frozen):
- list_dir's document is its four keys plus `floor`, nothing else moved
- read_file's document is its five keys plus `floor`

Tests — the floor (@devpulse's rider, the copy-path button):
- every lane carries the absolute path of the root it stood on
- the floor is absolute, and follows the ROOT rather than the descent
- floor + entry path is a real file — the composition the face performs
- a file read carries it too, for the Reader's own button
- naming the branch kind explicitly answers the same thing plus the root

Tests — the roster:
- carries home, aipass and every project the census knows
- the anchor project is not published twice under two kinds
- labels: home says home, aipass and projects say their own directory
- no branch rows — agents already have a door, and a branch row could not
  carry the project that qualifies it
- a census failure refuses the WHOLE roster rather than serving a partial one
- every published row resolves (the roster cannot advertise a floor the fence
  would refuse)

Tests — the route roll-call (found while adding a door):
- every registered /v1 route is named in the record create_app writes
- a new door appears in it without being added by hand

Tests — routes:
- GET /v1/roots: 401 without a token
- GET /v1/roots: 200 with the roster
- GET /v1/roots: 503 when the census cannot be produced
- GET /v1/dir: root=home lists home
- GET /v1/dir: branch=home&root=home — the phone's actual request, served
- GET /v1/dir: branch=aipass&root=aipass — the other stand-in
- GET /v1/files: a file reads through the stand-in
- GET /v1/files: root=home reads a file
- GET /v1/dir: an unknown root is 400 in the error envelope
- GET /v1/dir: root=home with a branch is 400, never a silent drop
- GET /v1/files: no root and no branch is 400 from the fence, not 422 from
  validation — the one visible shift this round
- GET /v1/dir: no root at all answers the pre-roots document exactly
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens


PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_READS_LOGGER = "aipass.api.apps.handlers.host.reads.logger"
PATCH_READS_JSON = "aipass.api.apps.handlers.host.reads.json_handler"
PATCH_READS_DRONE = "aipass.api.apps.handlers.host.reads.drone"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"


class _BranchNotFound(Exception):
    """Stand-in for drone.BranchNotFoundError."""


class _RegistryBroken(Exception):
    """Stand-in for drone.RegistryError."""


@pytest.fixture
def world(tmp_path: Path):
    """A registry, a branch, a home and a census — every root kind, all fake.

    Nothing here touches the operator's real home or the real census: the two
    doors this handler resolves through (@drone's registry, @baud's exec) are
    both stood in for, and `Path.home` is pointed at tmp. A test that read the
    real home would be reading the machine it happens to run on.
    """
    root = tmp_path / "FakeRepo"
    branch = root / "src" / "aipass" / "demo"
    branch.mkdir(parents=True)
    (branch / "hello.txt").write_text("hello world", encoding="utf-8")
    (branch / "nested").mkdir()
    (branch / "nested" / "deep.txt").write_text("deep", encoding="utf-8")
    (root / "secret.txt").write_text("do not read me", encoding="utf-8")

    home = tmp_path / "home" / "operator"
    home.mkdir(parents=True)
    (home / "todo.txt").write_text("buy milk", encoding="utf-8")
    (home / "notes").mkdir()
    (home / "notes" / "day.md").write_text("# day", encoding="utf-8")
    # Patrick's FULLY OPEN ruling, built rather than described. See the module
    # docstring: this is reachable by design, and the suite says so out loud.
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY", encoding="utf-8")
    # Noise is machine residue wherever it sits, not only inside a branch.
    (home / "__pycache__").mkdir()

    other = tmp_path / "Projects" / "Vera-Studio"
    other.mkdir(parents=True)
    (other / "app.py").write_text("print('hi')\n", encoding="utf-8")

    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps({"branches": [{"name": "DEMO", "path": str(branch), "email": "@demo"}]}),
        encoding="utf-8",
    )

    census = {
        "projects": [
            {"name": "FAKEREPO", "root": str(root), "anchor": True, "active": True},
            {"name": "VERA-STUDIO", "root": str(other), "anchor": False, "active": False},
        ],
        "generated_at": "2026-08-18T00:00:00Z",
        "error": None,
    }

    fake_drone = MagicMock()
    fake_drone.BranchNotFoundError = _BranchNotFound
    fake_drone.RegistryError = _RegistryBroken
    fake_drone.get_registry_path.return_value = str(registry)

    def _info(name: str) -> dict:
        if name.lower() not in ("demo", "@demo"):
            raise _BranchNotFound(name)
        return {"name": "DEMO", "path": str(branch), "email": "@demo"}

    fake_drone.get_branch_info.side_effect = _info

    with (
        patch(PATCH_READS_DRONE, fake_drone),
        patch(PATCH_READS_LOGGER),
        patch(PATCH_READS_JSON) as audit,
        patch("pathlib.Path.home", return_value=home),
        patch.object(host_fleet, "list_projects", return_value=census),
    ):
        yield {
            "root": root,
            "branch": branch,
            "home": home,
            "other": other,
            "census": census,
            "drone": fake_drone,
            "audit": audit,
        }


class TestTheRootKinds:
    """Four kinds of word, all resolved server-side, none of them a path."""

    def test_branch_kind_is_the_same_answer_the_branch_door_gives(self, world: dict) -> None:
        """The branch arm IS resolve_branch_root — not a second implementation."""
        assert host_reads.resolve_root(host_reads.ROOT_BRANCH, "demo") == host_reads.resolve_branch_root("demo")

    def test_branch_kind_with_no_name_is_refused(self, world: dict) -> None:
        """The existing sentence, reached through the new door."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_root(host_reads.ROOT_BRANCH, "")

    def test_home_resolves_to_the_home_directory(self, world: dict) -> None:
        """The root Patrick named first."""
        assert host_reads.resolve_root(host_reads.ROOT_HOME) == world["home"].resolve()

    def test_aipass_resolves_to_the_seats_own_repository(self, world: dict) -> None:
        """Resolved locally through the registry, never through the census."""
        assert host_reads.resolve_root(host_reads.ROOT_AIPASS) == world["root"].resolve()

    def test_project_resolves_through_the_census(self, world: dict) -> None:
        """@baud's discovery is the one implementation of where a project lives."""
        assert host_reads.resolve_root(host_reads.ROOT_PROJECT, "VERA-STUDIO") == world["other"].resolve()

    def test_project_matches_the_census_spelling_exactly(self, world: dict) -> None:
        """The name came from a roster this server published from the census
        itself, so an exact comparison IS the census's own spelling. A fourth
        case rule in a file that already documents three would be worse than a
        refusal that names where the right spelling comes from."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root(host_reads.ROOT_PROJECT, "vera-studio")

        assert "roster" in str(exc.value).lower()

    def test_an_unknown_kind_is_refused_and_names_the_four(self, world: dict) -> None:
        """A caller learns the vocabulary from the refusal, not from a doc."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root("elsewhere", "demo")

        said = str(exc.value)
        for kind in host_reads.ROOT_KINDS:
            assert kind in said

    def test_an_empty_kind_is_refused_here(self, world: dict) -> None:
        """The branch default belongs to the read lane, where 'absent' is a
        request that named no root. A resolver that guessed would make every
        typo resolve to somebody's branch.

        THE REFUSAL MUST BE ABOUT THE KIND. Written as a bare `raises` first,
        this passed even with the kind guard letting an empty string through —
        the empty kind fell to the project arm and was refused for naming no
        project. Same wrong-reason species as the traversal test above.
        """
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root("", "demo")

        assert "root kind" in str(exc.value).lower()

    def test_project_kind_with_no_name_is_refused(self, world: dict) -> None:
        """A kind that names something cannot be handed nothing."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_root(host_reads.ROOT_PROJECT, "")

    def test_a_broken_census_is_unavailable_in_bauds_words(self, world: dict) -> None:
        """Their sentence, not our paraphrase — the same rule the attach lane
        and the foreign-branch lane already follow."""
        with patch.object(host_fleet, "list_projects", side_effect=host_fleet.FleetUnavailable("binary is gated")):
            with pytest.raises(host_reads.ReadUnavailable) as exc:
                host_reads.resolve_root(host_reads.ROOT_PROJECT, "VERA-STUDIO")

        assert "binary is gated" in str(exc.value)

    def test_an_unknown_project_is_refused_not_unavailable(self, world: dict) -> None:
        """The caller named something that is not there: their mistake, 400,
        kept distinct from a census that could not be produced at all."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_root(host_reads.ROOT_PROJECT, "GHOST")

    def test_a_census_row_pointing_nowhere_is_unavailable(self, world: dict) -> None:
        """The census said it exists and it does not — ours to report."""
        census = {"projects": [{"name": "GONE", "root": str(world["root"] / "vanished")}], "error": None}
        with patch.object(host_fleet, "list_projects", return_value=census):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.resolve_root(host_reads.ROOT_PROJECT, "GONE")

    def test_a_census_row_with_no_path_is_unavailable_never_the_servers_cwd(self, world: dict) -> None:
        """A row that names no path must NOT resolve to wherever this process
        happens to be standing: Path("") resolves to the cwd, which is a real
        directory, so the read would succeed and serve the wrong tree."""
        census = {"projects": [{"name": "BLANK", "root": ""}], "error": None}
        with patch.object(host_fleet, "list_projects", return_value=census):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.resolve_root(host_reads.ROOT_PROJECT, "BLANK")

    def test_a_registry_row_with_no_path_is_unavailable_never_the_servers_cwd(self, world: dict) -> None:
        """The same species one door along, found while widening the fence and
        fixed here rather than left: a citizen registered without a path would
        have resolved to this process's cwd and read as that branch's root."""
        world["drone"].get_branch_info.side_effect = None
        world["drone"].get_branch_info.return_value = {"name": "DEMO", "path": ""}

        with pytest.raises(host_reads.ReadUnavailable):
            host_reads.resolve_branch_root("demo")

    def test_a_home_that_is_not_a_directory_is_unavailable(self, world: dict) -> None:
        """Not the caller's fault and not a blank listing."""
        with patch("pathlib.Path.home", return_value=world["home"] / "todo.txt"):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.resolve_root(host_reads.ROOT_HOME)


class TestKindsThatNameNothingRefuseAName:
    """A parameter that cannot mean anything is refused, never dropped.

    Same doctrine as /v1/roster's blanket refusal: a silently ignored argument
    lets a caller believe an answer is scoped when it is not.
    """

    def test_a_nameless_root_may_name_ITSELF(self, world: dict) -> None:
        """THE CARVE-OUT (@devpulse's ruling, 2026-08-18), measured not guessed.

        @baud's picker sends the first path component for EVERY root, and the
        kinds that name nothing stand in for themselves rather than send an
        empty component that composes a leading slash their own transport
        refuses (`name: root.name || root.kind`, PhoneApp.tsx). So the wire
        carries branch=home&root=home.

        That is not a parameter which cannot mean anything — it names the root
        itself, straight off the roster row. It is accepted and stripped; any
        OTHER name stays refused exactly as before, so the doctrine holds:
        nothing meaningless is dropped, nothing meaningful is refused.
        """
        assert host_reads.resolve_root(host_reads.ROOT_HOME, host_reads.ROOT_HOME) == world["home"].resolve()
        assert host_reads.resolve_root(host_reads.ROOT_AIPASS, host_reads.ROOT_AIPASS) == world["root"].resolve()

    def test_the_stand_in_is_the_kind_EXACTLY(self, world: dict) -> None:
        """Equal to the kind, not merely close to it. The word came from a
        roster this server published, so an exact comparison is a comparison
        against our own spelling — the same rule the project names follow.

        And the refusal names the way through, because @baud's face prints it
        verbatim: a sentence that said 'send no name' while a name was in fact
        accepted would be a small lie told to whoever hits it next.
        """
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root(host_reads.ROOT_HOME, "HOME")

        assert "the kind itself" in str(exc.value)

    def test_a_read_stands_on_home_through_the_stand_in(self, world: dict) -> None:
        """The whole wire shape end to end on the handler, not just the
        resolver — this is the request @baud's browser actually sends."""
        result = host_reads.list_dir(host_reads.ROOT_HOME, root=host_reads.ROOT_HOME)

        assert "todo.txt" in [entry["name"] for entry in result["entries"]]

    def test_home_with_a_name_is_refused(self, world: dict) -> None:
        """'home' names nothing — a name alongside it is a caller error."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root(host_reads.ROOT_HOME, "demo")

        assert "names nothing" in str(exc.value).lower()

    def test_aipass_with_a_name_is_refused(self, world: dict) -> None:
        """Same rule, same sentence, the other nameless kind."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_root(host_reads.ROOT_AIPASS, "demo")

    def test_home_with_a_project_is_refused(self, world: dict) -> None:
        """A home directory does not live inside a project."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root(host_reads.ROOT_HOME, "", project="VERA-STUDIO")

        assert "project" in str(exc.value).lower()

    def test_project_kind_with_a_project_parameter_is_refused(self, world: dict) -> None:
        """The project IS the name here; a second one could only disagree."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.resolve_root(host_reads.ROOT_PROJECT, "VERA-STUDIO", project="FAKEREPO")

    def test_branch_kind_still_honours_a_project(self, world: dict) -> None:
        """The foreign-branch lane is untouched: project qualifies a branch."""
        row = {"path": str(world["branch"])}
        with patch.object(host_fleet, "resolve_branch", return_value=row):
            assert host_reads.resolve_root(host_reads.ROOT_BRANCH, "demo", project="OTHER") == world["branch"].resolve()


class TestTheFenceCoversEveryRoot:
    """Wider does not mean weaker — the containment is the same code."""

    def test_parent_traversal_refused_under_home(self, world: dict) -> None:
        """The one gate that must never care which root it is standing on.

        THE TARGET EXISTS, and the refusal must not be about its absence.
        Written the obvious way first — a '..' at a file that was not there —
        this passed with the whole '..' gate deleted, because the read was
        refused for being missing rather than for being outside. A traversal
        test that can be satisfied by an empty directory is not a traversal
        test (S89's species: green for the wrong reason).
        """
        outside = world["root"] / "secret.txt"
        assert outside.is_file(), "fixture broken: the traversal target must exist"

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("", f"../../{world['root'].name}/secret.txt", root=host_reads.ROOT_HOME)

        assert "no such file" not in str(exc.value).lower()

    def test_absolute_name_refused_under_a_project(self, world: dict) -> None:
        """An absolute name is the exact thing the fence exists to reject."""
        with pytest.raises(host_reads.ReadRefused):
            host_reads.read_file("VERA-STUDIO", "/etc/passwd", root=host_reads.ROOT_PROJECT)

    def test_symlink_out_of_home_refused(self, world: dict) -> None:
        """The post-resolution check — the only gate that sees a symlink out.

        This is the gate that carries the class. Deleting the '..' check alone
        leaves every test here green, and that is the three gates overlapping
        by design rather than a hole: containment still refuses. Deleting THIS
        one turns the whole class red (mutation-checked 2026-08-18).
        """
        link = world["home"] / "escape.txt"
        try:
            link.symlink_to(world["root"] / "secret.txt")
        except (OSError, NotImplementedError):
            pytest.skip("this platform cannot construct a symlink here")

        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.read_file("", "escape.txt", root=host_reads.ROOT_HOME)

        assert "outside" in str(exc.value).lower()

    def test_an_ordinary_nested_read_under_home_is_allowed(self, world: dict) -> None:
        """The fence is not a wall: the ruling is FULLY OPEN inside the root."""
        result = host_reads.read_file("", "notes/day.md", root=host_reads.ROOT_HOME)

        assert result["content"] == "# day"


class TestReadsStandingOnARoot:
    """The two verbs, standing somewhere that is not agent-land."""

    def test_list_dir_lists_homes_own_level(self, world: dict) -> None:
        """One level, the same shape the branch lane has always answered."""
        result = host_reads.list_dir("", root=host_reads.ROOT_HOME)
        names = [entry["name"] for entry in result["entries"]]

        assert "todo.txt" in names
        assert "notes" in names

    def test_the_home_exposure_is_real_and_deliberate(self, world: dict) -> None:
        """Patrick's ruling, executed rather than described. If this test ever
        has to change, the ruling changed — which is exactly when someone
        should have to come here and say so."""
        result = host_reads.read_file("", ".ssh/id_ed25519", root=host_reads.ROOT_HOME)

        assert result["content"] == "PRIVATE KEY"

    def test_the_answer_names_the_root_it_stood_on(self, world: dict) -> None:
        """A document that did not say where it stood would read as a branch."""
        result = host_reads.list_dir("", root=host_reads.ROOT_HOME)

        assert result["root"] == host_reads.ROOT_HOME

    def test_noise_is_still_filtered_outside_a_branch(self, world: dict) -> None:
        """Machine residue is residue wherever it sits."""
        result = host_reads.list_dir("", root=host_reads.ROOT_HOME)

        assert "__pycache__" not in [entry["name"] for entry in result["entries"]]

    def test_the_audit_record_names_the_root(self, world: dict) -> None:
        """A home read and a branch read must not be the same line in the
        trail — the exposure is on the record, so the record has to carry it."""
        host_reads.read_file("", "todo.txt", root=host_reads.ROOT_HOME)

        payload = world["audit"].log_operation.call_args[0][1]
        assert payload["root"] == host_reads.ROOT_HOME


class TestAbsentRootIsTodaysAnswerPlusTheFloor:
    """The no-regression pin, RE-FROZEN once and deliberately.

    It was written to guard the roots round: absent root = the pre-roots
    document, key for key. @devpulse's rider (2026-08-18) adds exactly one key
    to every lane — `floor`, the absolute path of the root the answer stands
    on — because Patrick wants a copy-path button and the ABSOLUTE path is what
    pastes into a terminal, which is server knowledge the face cannot compose.

    So the pin now says: today's document plus `floor`, nothing else moved. It
    is still a whole-key-set assertion rather than a spot check, because the
    point of it is that a SECOND key cannot arrive unannounced — the day one
    does, this test is where the argument has to be had.
    """

    def test_list_dirs_document_is_todays_plus_the_floor(self, world: dict) -> None:
        """One key added, every other key and value untouched."""
        result = host_reads.list_dir("demo")

        assert set(result) == {"branch", "dir", "entries", "truncated", "floor"}
        assert result["branch"] == "demo"
        assert result["floor"] == str(world["branch"].resolve())

    def test_read_files_document_is_todays_plus_the_floor(self, world: dict) -> None:
        """Same pin on the other verb."""
        result = host_reads.read_file("demo", "hello.txt")

        assert set(result) == {"branch", "file", "bytes", "truncated", "content", "floor"}
        assert result["content"] == "hello world"
        assert result["floor"] == str(world["branch"].resolve())

    def test_naming_the_branch_kind_answers_the_same_thing(self, world: dict) -> None:
        """Explicit and absent are the same read; only the echo differs."""
        absent = host_reads.list_dir("demo")
        named = host_reads.list_dir("demo", root=host_reads.ROOT_BRANCH)

        assert {key: value for key, value in named.items() if key != "root"} == absent
        assert named["root"] == host_reads.ROOT_BRANCH


class TestTheFloorTravels:
    """The absolute path of the root the answer stands on (@devpulse's rider).

    THE FACE CANNOT COMPOSE IT. It knows `<root>/<relative>` and nothing about
    where the root sits on disk — that is server knowledge, and a copy-path
    button that pasted a relative path into a terminal would be a button that
    quietly does not work.
    """

    def test_every_lane_carries_its_own_floor(self, world: dict) -> None:
        """All four kinds, because all four pass through resolve_root."""
        assert host_reads.list_dir("demo")["floor"] == str(world["branch"].resolve())
        assert host_reads.list_dir(root=host_reads.ROOT_HOME)["floor"] == str(world["home"].resolve())
        assert host_reads.list_dir(root=host_reads.ROOT_AIPASS)["floor"] == str(world["root"].resolve())
        assert host_reads.list_dir("VERA-STUDIO", root=host_reads.ROOT_PROJECT)["floor"] == str(
            world["other"].resolve()
        )

    def test_the_floor_is_absolute(self, world: dict) -> None:
        """A relative floor would paste into a terminal and land elsewhere."""
        assert Path(host_reads.list_dir(root=host_reads.ROOT_HOME)["floor"]).is_absolute()

    def test_floor_plus_entry_path_is_the_real_file(self, world: dict) -> None:
        """THE COMPOSITION THE FACE ACTUALLY PERFORMS, pinned rather than
        assumed: every row the browser paints must join with the floor into a
        path that exists on disk. This is the whole feature in one assertion."""
        answer = host_reads.list_dir(root=host_reads.ROOT_HOME)

        for entry in answer["entries"]:
            assert (Path(answer["floor"]) / entry["path"]).exists()

    def test_the_floor_follows_a_descent(self, world: dict) -> None:
        """The floor is the ROOT, not the directory being listed — a floor that
        walked with `dir` would double-count the relative part on the join."""
        answer = host_reads.list_dir(root=host_reads.ROOT_HOME, dir="notes")

        assert answer["floor"] == str(world["home"].resolve())
        assert (Path(answer["floor"]) / answer["entries"][0]["path"]).is_file()

    def test_a_read_carries_the_floor_too(self, world: dict) -> None:
        """The Reader's own copy-path button asks the same question."""
        result = host_reads.read_file("", "notes/day.md", root=host_reads.ROOT_HOME)

        assert (Path(result["floor"]) / result["file"]).read_text(encoding="utf-8") == "# day"


class TestTheRoster:
    """What the server publishes as places to stand."""

    def test_it_carries_home_aipass_and_every_project(self, world: dict) -> None:
        """The picker renders what the server holds, never a guessed list."""
        rows = host_reads.list_roots()["roots"]
        kinds = [row["kind"] for row in rows]
        names = [row["name"] for row in rows]

        assert host_reads.ROOT_HOME in kinds
        assert host_reads.ROOT_AIPASS in kinds
        assert "VERA-STUDIO" in names

    def test_the_anchor_project_is_not_published_twice(self, world: dict) -> None:
        """'aipass' and the anchor census row are the SAME floor. Two rows
        pointing at one directory is a roster that lies about how many places
        there are — the duplicate goes, the resolution for both stays."""
        rows = host_reads.list_roots()["roots"]

        assert "FAKEREPO" not in [row["name"] for row in rows]
        assert host_reads.resolve_root(host_reads.ROOT_PROJECT, "FAKEREPO") == world["root"].resolve()

    def test_labels_say_what_the_floor_is_called(self, world: dict) -> None:
        """home says home; the others say their own directory's name, which is
        what a person calls them — the census name rides alongside as the word
        the fence will actually be handed."""
        rows = {row["kind"]: row for row in host_reads.list_roots()["roots"] if row["kind"] != "project"}
        projects = [row for row in host_reads.list_roots()["roots"] if row["kind"] == "project"]

        assert rows[host_reads.ROOT_HOME]["label"] == "home"
        assert rows[host_reads.ROOT_AIPASS]["label"] == world["root"].name
        assert projects[0]["label"] == world["other"].name

    def test_no_branch_rows(self, world: dict) -> None:
        """Agents already have a door, and a branch row could not carry the
        project that qualifies it — the roster would be true only at the seat."""
        assert host_reads.ROOT_BRANCH not in [row["kind"] for row in host_reads.list_roots()["roots"]]

    def test_a_broken_census_refuses_the_whole_roster(self, world: dict) -> None:
        """MEASURED AGAINST THE CONSUMER, not assumed: @baud's RootsScreen
        renders `body.roots` and ignores every other field, so a partial roster
        carrying an error nobody reads would print as 'there are no projects'.
        A refusal it shows in our own words is the honest answer."""
        with patch.object(host_fleet, "list_projects", side_effect=host_fleet.FleetUnavailable("no census today")):
            with pytest.raises(host_reads.ReadUnavailable) as exc:
                host_reads.list_roots()

        assert "no census today" in str(exc.value)

    def test_every_published_row_resolves(self, world: dict) -> None:
        """The roster cannot advertise a floor the fence would refuse: a row
        the picker draws and the browse then denies is worse than no row."""
        for row in host_reads.list_roots()["roots"]:
            assert host_reads.resolve_root(row["kind"], row["name"]).is_dir()


PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"


fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def client(tmp_path: Path):
    """TestClient with an isolated token store."""
    from fastapi.testclient import TestClient

    store = tmp_path / "secrets"
    store.mkdir()
    with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
            _, raw = host_tokens.issue_token("phone", "read")
            yield TestClient(host_server.create_app(), raise_server_exceptions=False), raw


@fastapi_required
class TestTheRollCallIsDerivedNotWrittenDown:
    """Found while adding a route: the list that names them had drifted.

    `create_app` logged and audited a hand-written `routes = [...]`. It named
    18 doors while the app registered nearly forty — /v1/dir, /v1/projects,
    every git route and every settings route were missing, and had been for as
    long as they had existed. A roll-call that claims to name every door and
    names half is worse than no roll-call: it reads as a complete answer.

    Same species as the status codes and the manifest count — a written-down
    copy of a truth that has its own source. So it is derived from the app's
    own routing table, and this test is what stops it being written down again.
    """

    def _routes_logged(self) -> list:
        """The route list create_app actually recorded, and the app's own."""
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_JSON) as audit, patch(PATCH_SERVER_LOGGER):
            app = host_server.create_app()
            TestClient(app)

        recorded = None
        for call in audit.log_operation.call_args_list:
            if call[0][0] == "host_api_app_created":
                recorded = call[0][1]["routes"]

        registered = sorted(
            {path for path in (getattr(route, "path", "") for route in app.routes) if path.startswith("/v1")}
        )
        return [recorded, registered]

    def test_every_registered_v1_route_is_named(self, world: dict) -> None:
        """The whole point: no door goes unlisted, including tomorrow's."""
        recorded, registered = self._routes_logged()

        assert sorted(recorded) == registered

    def test_the_new_roots_door_appears_without_being_added_by_hand(self, world: dict) -> None:
        """A derived list is one nobody has to remember to update."""
        recorded, _ = self._routes_logged()

        assert "/v1/roots" in recorded
        assert "/v1/dir" in recorded


@fastapi_required
class TestRootRoutes:
    """The doors @baud's picker and browser actually knock on."""

    def test_roots_requires_auth(self, client: Any, world: dict) -> None:
        """The roster is behind the same wall as the data it points at."""
        api, _ = client

        assert api.get("/v1/roots").status_code == 401

    def test_roots_returns_the_roster(self, client: Any, world: dict) -> None:
        """The shape @baud codes against: {roots: [{kind, name, label}]}."""
        api, raw = client

        response = api.get("/v1/roots", headers={"Authorization": f"Bearer {raw}"})
        body = response.json()

        assert response.status_code == 200
        assert set(body) == {"roots"}
        assert set(body["roots"][0]) == {"kind", "name", "label"}

    def test_roots_is_503_when_the_census_cannot_be_produced(self, client: Any, world: dict) -> None:
        """Not an empty list — an empty roster and a broken one are different
        answers and the phone must be able to tell them apart."""
        api, raw = client

        with patch.object(host_fleet, "list_projects", side_effect=host_fleet.FleetUnavailable("gated")):
            response = api.get("/v1/roots", headers={"Authorization": f"Bearer {raw}"})

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "roots_unavailable"

    def test_dir_stands_on_home(self, client: Any, world: dict) -> None:
        """The end-to-end of Patrick's ask, one tap deep."""
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"root": "home"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200
        assert "todo.txt" in [entry["name"] for entry in response.json()["entries"]]

    def test_files_reads_under_home(self, client: Any, world: dict) -> None:
        """And the Reader on the other side of the tap."""
        api, raw = client

        response = api.get(
            "/v1/files",
            params={"root": "home", "file": "todo.txt"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200
        assert response.json()["content"] == "buy milk"

    def test_the_phones_actual_home_request_is_served(self, client: Any, world: dict) -> None:
        """THE WIRE SHAPE @baud SENDS, verbatim: branch=home&root=home.

        Their picker composes the first path component for every root and the
        nameless kinds stand in for themselves. This test exists because the
        first cut of the fence 400'd exactly this request — the collision was
        found by probing the two trees against each other, not by reading
        either one (@devpulse, 2026-08-18).
        """
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"branch": "home", "root": "home"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200
        assert "todo.txt" in [entry["name"] for entry in response.json()["entries"]]

    def test_the_phones_actual_aipass_request_is_served(self, client: Any, world: dict) -> None:
        """The other nameless kind, same shape, same stand-in."""
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"branch": "aipass", "root": "aipass"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200

    def test_a_file_reads_through_the_stand_in(self, client: Any, world: dict) -> None:
        """And the Reader on the other side of the tap, same shape."""
        api, raw = client

        response = api.get(
            "/v1/files",
            params={"branch": "home", "root": "home", "file": "todo.txt"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200
        assert response.json()["content"] == "buy milk"

    def test_the_floor_reaches_the_face(self, client: Any, world: dict) -> None:
        """Handler-deep is not the contract — the phone reads the route."""
        api, raw = client

        body = api.get(
            "/v1/dir",
            params={"branch": "home", "root": "home"},
            headers={"Authorization": f"Bearer {raw}"},
        ).json()

        assert body["floor"] == str(world["home"].resolve())
        assert set(body) == {"branch", "dir", "entries", "truncated", "root", "floor"}

    def test_an_unknown_root_is_400_in_the_envelope(self, client: Any, world: dict) -> None:
        """A refused root comes back as the one error shape, and the face
        prints our sentence verbatim — so the sentence has to be the useful one."""
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"root": "elsewhere"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"

    def test_a_nameless_root_with_a_branch_is_400(self, client: Any, world: dict) -> None:
        """Never a silent drop: the caller believes they scoped something."""
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"root": "home", "branch": "demo"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400

    def test_a_branchless_request_on_the_branch_lane_is_now_a_400(self, client: Any, world: dict) -> None:
        """THE ONE VISIBLE SHIFT THIS ROUND, pinned rather than mentioned.

        `branch` had to stop being required by the signature, because `home`
        and `aipass` name nothing. So a request that names neither a root nor a
        branch is refused by the fence (400, in words) where validation used to
        refuse it (422). Both are refusals in the same envelope; the shape of
        the answer moved, and this is where that is written down.
        """
        api, raw = client

        response = api.get(
            "/v1/files",
            params={"file": "hello.txt"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"
        assert "branch" in response.json()["error"]["message"].lower()

    def test_no_root_at_all_answers_the_pre_roots_document(self, client: Any, world: dict) -> None:
        """The route-level half of the no-regression pin."""
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"branch": "demo"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200
        assert set(response.json()) == {"branch", "dir", "entries", "truncated", "floor"}
