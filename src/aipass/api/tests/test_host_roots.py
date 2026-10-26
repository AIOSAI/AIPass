# =================== AIPass ====================
# Name: test_host_roots.py
# Description: Tests for the roots roster and the widened name fence
# Version: 1.1.1
# Created: 2026-08-18
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/host/reads.py's four-kind name fence, /v1/dir paging and the /v1/roots route."""

# Each root that resolves is paired with a test that the containment under it still refuses.
# A read-scope token reads ~/.ssh by the owner's FULLY OPEN ruling; the suite reads it on purpose.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(duplicate_test) — the branch read lane with no root, tests/test_host_read_lane.py
# seedgo: no-test-needed(duplicate_test) — issue_token() and verify_token() themselves, tests/test_host_api_config.py

import json
import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import denials as host_denials
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

    home_root, not pathlib's Path.home: a patch of Path.home replaces it for every reader in the process.
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
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE KEY", encoding="utf-8")
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
        patch.object(host_reads, "home_root", return_value=home),
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
        """The root the owner named first."""
        assert host_reads.resolve_root(host_reads.ROOT_HOME) == world["home"].resolve()

    def test_aipass_resolves_to_the_seats_own_repository(self, world: dict) -> None:
        """Resolved locally through the registry, never through the census."""
        assert host_reads.resolve_root(host_reads.ROOT_AIPASS) == world["root"].resolve()

    def test_project_resolves_through_the_census(self, world: dict) -> None:
        """@baud's discovery is the one implementation of where a project lives."""
        assert host_reads.resolve_root(host_reads.ROOT_PROJECT, "VERA-STUDIO") == world["other"].resolve()

    def test_project_matches_the_census_spelling_exactly(self, world: dict) -> None:
        """The name came from a roster published from the census, so exact
        comparison IS the census's spelling; the refusal names the roster."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root(host_reads.ROOT_PROJECT, "vera-studio")

        assert "roster" in str(exc.value).lower()

    def test_an_unknown_kind_is_refused_and_names_the_four(self, world: dict) -> None:
        """A caller learns the vocabulary from the refusal, not from a doc."""
        with pytest.raises(host_reads.ReadRefused) as exc:
            host_reads.resolve_root("elsewhere", "demo")

        said = str(exc.value)

        assert host_reads.ROOT_KINDS, "the vocabulary is empty — the refusal was checked against nothing"

        for kind in host_reads.ROOT_KINDS:
            assert kind in said

    def test_an_empty_kind_is_refused_here(self, world: dict) -> None:
        """The branch default belongs to the read lane, where 'absent' is a
        request that named no root. A resolver that guessed would make every
        typo resolve to somebody's branch.

        The refusal must be about the kind: a bare `raises` passes on the project arm's refusal.
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
        """Path("") resolves to the cwd, a real directory, so the read would serve the wrong tree."""
        census = {"projects": [{"name": "BLANK", "root": ""}], "error": None}
        with patch.object(host_fleet, "list_projects", return_value=census):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.resolve_root(host_reads.ROOT_PROJECT, "BLANK")

    def test_a_registry_row_with_no_path_is_unavailable_never_the_servers_cwd(self, world: dict) -> None:
        """A citizen registered without a path must not resolve to this process's cwd."""
        world["drone"].get_branch_info.side_effect = None
        world["drone"].get_branch_info.return_value = {"name": "DEMO", "path": ""}

        with pytest.raises(host_reads.ReadUnavailable):
            host_reads.resolve_branch_root("demo")

    def test_a_home_that_is_not_a_directory_is_unavailable(self, world: dict) -> None:
        """Not the caller's fault and not a blank listing."""
        with patch.object(host_reads, "home_root", return_value=world["home"] / "todo.txt"):
            with pytest.raises(host_reads.ReadUnavailable):
                host_reads.resolve_root(host_reads.ROOT_HOME)


class TestKindsThatNameNothingRefuseAName:
    """A parameter that cannot mean anything is refused, never dropped.

    A silently ignored argument lets a caller believe an answer is scoped when it is not.
    """

    def test_a_nameless_root_may_name_itself(self, world: dict) -> None:
        """THE CARVE-OUT, measured not guessed.

        @baud's picker sends `name: root.name || root.kind` (PhoneApp.tsx), so the wire
        carries branch=home&root=home; that name is accepted, any OTHER stays refused.
        """
        assert host_reads.resolve_root(host_reads.ROOT_HOME, host_reads.ROOT_HOME) == world["home"].resolve()
        assert host_reads.resolve_root(host_reads.ROOT_AIPASS, host_reads.ROOT_AIPASS) == world["root"].resolve()

    def test_the_stand_in_is_the_kind_exactly(self, world: dict) -> None:
        """Equal to the kind, not merely close to it. The word came from a
        roster this server published, so an exact comparison is a comparison
        against our own spelling — the same rule the project names follow.

        The refusal names the way through, because @baud's face prints it verbatim.
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

        THE TARGET EXISTS, so the refusal cannot be about its absence: a '..'
        at a missing file passes with the whole '..' gate deleted.
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

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="constructing a symlink needs a privilege the CI account may not hold",
    )
    def test_symlink_out_of_home_refused(self, world: dict) -> None:
        """The post-resolution check — the only gate that sees a symlink out.

        This gate carries the class: deleting it turns the whole class red.
        """
        link = world["home"] / "escape.txt"
        # No try/except: a machine that can make a symlink and fails to must go red, not skip.
        link.symlink_to(world["root"] / "secret.txt")

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
        """The owner's FULLY OPEN ruling, executed; if this test changes, the ruling changed."""
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
    """The no-regression pin, RE-FROZEN deliberately: floor, then offset and total.

    A whole-key-set assertion, so no further key can arrive unannounced.
    """

    def test_list_dirs_document_is_todays_plus_the_floor(self, world: dict) -> None:
        """One key added, every other key and value untouched."""
        result = host_reads.list_dir("demo")

        assert set(result) == {"branch", "dir", "entries", "truncated", "offset", "total", "floor"}
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

    The face cannot compose it: where a root sits on disk is server knowledge.
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

        assert answer["entries"], "the listing was empty, so no floor+path join was ever performed"

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


@pytest.fixture
def crowded(world: dict) -> dict:
    """1059 entries under home, 937 files and 122 dirs, plus a noise dir the filter drops."""
    big = world["home"] / "big"
    big.mkdir()
    for n in range(122):
        (big / f"d{n:04d}").mkdir()
    for n in range(937):
        (big / f"f{n:04d}.txt").write_text("x", encoding="utf-8")
    (big / "node_modules").mkdir()
    names = [f"d{n:04d}" for n in range(122)] + [f"f{n:04d}.txt" for n in range(937)]
    return {**world, "names": names}


def _page(offset: Any) -> dict:
    return host_reads.list_dir(root=host_reads.ROOT_HOME, dir="big", offset=offset)


class TestDirPaging:
    """GET /v1/dir pages by offset under the 400 cap, with the total @baud's 'show more' row counts."""

    def test_the_first_page_is_400_of_the_filtered_total_and_says_more(self, crowded: dict) -> None:
        page = _page(0)

        assert [entry["name"] for entry in page["entries"]] == crowded["names"][:400]
        assert (page["offset"], page["total"], page["truncated"]) == (0, 1059, True)

    def test_pages_join_into_the_whole_sorted_listing_and_the_last_says_done(self, crowded: dict) -> None:
        pages = [_page(start) for start in (0, 400, 800)]

        assert [entry["name"] for page in pages for entry in page["entries"]] == crowded["names"]
        assert [page["truncated"] for page in pages] == [True, True, False]
        assert len(pages[2]["entries"]) == 259

    @pytest.mark.parametrize("offset", [1059, 1200])
    def test_an_offset_at_or_past_the_total_answers_empty_with_the_total(self, crowded: dict, offset: int) -> None:
        page = _page(offset)

        assert (page["entries"], page["total"], page["truncated"], page["offset"]) == ([], 1059, False, offset)

    def test_a_listing_under_the_cap_is_one_page_at_offset_zero(self, world: dict) -> None:
        page = host_reads.list_dir(root=host_reads.ROOT_HOME)

        assert (page["offset"], page["total"], page["truncated"]) == (0, len(page["entries"]), False)

    @pytest.mark.parametrize("offset", ["-1", "abc", "1.5", "", True])
    def test_a_negative_or_non_integer_offset_is_refused(self, crowded: dict, offset: Any) -> None:
        with pytest.raises(host_reads.ReadRefused):
            _page(offset)

    def test_the_audit_line_carries_offset_and_total(self, crowded: dict) -> None:
        _page("400")

        crowded["audit"].log_operation.assert_called_once()
        event, audit = crowded["audit"].log_operation.call_args.args
        assert event == "host_api_dir_list"
        assert (audit["offset"], audit["total"], audit["entries"], audit["truncated"]) == (400, 1059, 400, True)


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
        """'aipass' and the anchor census row are the SAME floor: one row, both resolve."""
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
        """@baud's RootsScreen renders only `body.roots`, so a partial roster with
        an error field would print as 'there are no projects'."""
        with patch.object(host_fleet, "list_projects", side_effect=host_fleet.FleetUnavailable("no census today")):
            with pytest.raises(host_reads.ReadUnavailable) as exc:
                host_reads.list_roots()

        assert "no census today" in str(exc.value)

    def test_every_published_row_resolves(self, world: dict) -> None:
        """The roster cannot advertise a floor the fence would refuse: a row
        the picker draws and the browse then denies is worse than no row."""
        published = host_reads.list_roots()["roots"]

        assert published, "the roster advertised no roots at all"

        for row in published:
            assert host_reads.resolve_root(row["kind"], row["name"]).is_dir()


PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"


fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def client(tmp_path: Path, host_app: Any):
    """TestClient with an isolated token store."""
    from fastapi.testclient import TestClient

    store = tmp_path / "secrets"
    store.mkdir()
    with patch(PATCH_SECRETS_BASE, store), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER), patch(PATCH_SERVER_LOGGER):
            _, raw = host_tokens.issue_token("phone", "read")
            yield TestClient(host_app, raise_server_exceptions=False), raw


@fastapi_required
class TestTheRollCallIsDerivedNotWrittenDown:
    """Found while adding a route: the list that names them had drifted.

    The roll-call is derived from the app's routing table; this stops it being hand-written again.
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
        """The end-to-end of the owner's ask, one tap deep."""
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

        The nameless kinds stand in for themselves as the first path component.
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
        assert set(body) == {"branch", "dir", "entries", "truncated", "offset", "total", "root", "floor"}

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

        `branch` is optional because `home` and `aipass` name nothing, so naming
        neither root nor branch is the fence's 400, not validation's 422.
        """
        api, raw = client

        response = api.get(
            "/v1/files",
            params={"file": "hello.txt"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "read_refused"
        assert error["message"] == host_denials.SENTENCES["read_refused"]
        assert re.fullmatch("[0-9a-f]{12}", error["ref"])
        assert "branch name is required" not in response.text

    def test_no_root_at_all_answers_the_pre_roots_document(self, client: Any, world: dict) -> None:
        """The route-level half of the no-regression pin."""
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"branch": "demo"},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 200
        assert set(response.json()) == {"branch", "dir", "entries", "truncated", "offset", "total", "floor"}

    def test_offset_reaches_the_route_and_pages(self, client: Any, crowded: dict) -> None:
        api, raw = client

        body = api.get(
            "/v1/dir",
            params={"root": "home", "dir": "big", "offset": "800"},
            headers={"Authorization": f"Bearer {raw}"},
        ).json()

        assert (body["offset"], body["total"], body["truncated"], len(body["entries"])) == (800, 1059, False, 259)

    @pytest.mark.parametrize("offset", ["-1", "abc"])
    def test_a_bad_offset_is_400_read_refused_not_422(self, client: Any, crowded: dict, offset: str) -> None:
        api, raw = client

        response = api.get(
            "/v1/dir",
            params={"root": "home", "dir": "big", "offset": offset},
            headers={"Authorization": f"Bearer {raw}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "read_refused"
