# =================== AIPass ====================
# Name: test_roots_lifecycle.py
# Description: Pins the template, verbs and healing for AIPASS_ROOTS.json
# Version: 1.0.2
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/roots.py and apps/handlers/monitor/roots_file.py."""

# The anchor is written by code, from a template. The writer refuses every row the reader would drop,
# and healing is a deliberate verb, never a side effect of reading (zero roots is a legal state).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — handle_command's writing verbs hit the live find_repo_root() file; add_root() pinned
# seedgo: no-test-needed(shared) — show_roots() table text; list_roots() rows it prints are pinned here
# seedgo: no-test-needed(shared) — json_handler.log_operation() audit line on each roots command

import json
import pathlib
from pathlib import Path

import pytest

from aipass.cli.apps.modules import reset_command_state, resolve_exit
from aipass.memory.apps.handlers.monitor import registry_scope as rs
from aipass.memory.apps.handlers.monitor import roots_file as rf
from aipass.memory.apps.modules import fleet, roots


TODAY = "2026-08-30"


@pytest.fixture
def home(tmp_path):
    """An AIPass home with a real sibling to declare, and one that overlaps."""
    root = tmp_path / "AIPass"
    (root / "projects" / "inside").mkdir(parents=True)
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    (tmp_path / "wren").mkdir()
    (tmp_path / "Demo").mkdir()
    (tmp_path / "loose.txt").write_text("not a repo", encoding="utf-8")
    return root


def _read(home_path):
    return json.loads((home_path / rs.DECLARED_ROOTS).read_text(encoding="utf-8"))


class TestTheTemplateIsTheDefaultShape:
    """A template that has drifted from the reader is worse than no template."""

    def test_the_template_ships_in_the_branch(self):
        assert rf.template_path().is_file(), f"no template at {rf.template_path()}"

    def test_the_template_declares_nothing(self):
        """An empty roots[] is the only honest default: nobody has declared yet."""
        assert json.loads(rf.template_path().read_text(encoding="utf-8"))["roots"] == []

    def test_the_scaffold_is_empty_even_if_the_template_stops_being(self, tmp_path, monkeypatch):
        """The renderer forces ``roots = []`` even when the template carries an example root."""
        stub = tmp_path / "stub.template.json"
        stub.write_text(
            json.dumps({"metadata": {"version": "1.0.0"}, "roots": [{"path": "../example", "status": "active"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(rf, "template_path", lambda: stub)
        assert rf.render_scaffold(TODAY)["roots"] == []

    def test_the_rendered_scaffold_is_what_the_reader_accepts(self, home):
        """The template and the reader are pinned to each other: a fresh scaffold needs no repair."""
        rf.init_roots(home, today=TODAY)
        assert rs.declared_roots(home) == []
        document = _read(home)
        assert document["roots"] == []
        assert document["metadata"]["version"] == rf.ROOTS_SCHEMA_VERSION
        assert document["metadata"]["last_updated"] == TODAY


class TestInitNeverClobbers:
    """The one file whose accidental overwrite loses declarations nobody else holds."""

    def test_init_creates_it_when_absent(self, home):
        ok, message = rf.init_roots(home, today=TODAY)
        assert ok, message
        assert (home / rs.DECLARED_ROOTS).is_file()

    def test_init_refuses_when_it_already_exists(self, home):
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        ok, message = rf.init_roots(home, today=TODAY)
        assert not ok
        assert rs.DECLARED_ROOTS in message
        assert [row["path"] for row in _read(home)["roots"]] == ["../wren"], "init overwrote a declaration"

    def test_init_refuses_a_corrupt_file_too(self, home):
        """Unreadable is not absent. Overwriting it here would be the silent rebuild."""
        (home / rs.DECLARED_ROOTS).write_text("{ broken", encoding="utf-8")
        ok, _ = rf.init_roots(home, today=TODAY)
        assert not ok
        assert (home / rs.DECLARED_ROOTS).read_text(encoding="utf-8") == "{ broken"


class TestAddRefusesAtWriteWhatTheReaderRefusesAtRead:
    """One predicate, two enforcement points. Never two predicates."""

    def test_a_real_sibling_is_declared_and_relative(self, home):
        rf.init_roots(home, today=TODAY)
        ok, message = rf.add_root(home, str(home.parent / "wren"), today=TODAY)
        assert ok, message
        row = _read(home)["roots"][0]
        assert row["path"] == "../wren", "an absolute path was stored where a relative one fits"
        assert row["status"] == "active"
        assert [path.name for path in rs.declared_roots(home)] == ["wren"]

    def test_a_path_that_does_not_exist_is_refused_by_that_name(self, home):
        """A missing path and a non-directory are different diagnoses; the "does not exist" wording is the pin."""
        rf.init_roots(home, today=TODAY)
        ok, message = rf.add_root(home, "../nowhere", today=TODAY)
        assert not ok
        assert "does not exist" in message
        assert _read(home)["roots"] == []

    def test_a_file_outside_home_is_refused_as_not_a_directory(self, home):
        """Outside home DELIBERATELY: a file inside it is refused by the overlap guard first."""
        rf.init_roots(home, today=TODAY)
        ok, message = rf.add_root(home, "../loose.txt", today=TODAY)
        assert not ok
        assert "not a directory" in message
        assert _read(home)["roots"] == []

    @pytest.mark.parametrize("candidate", [".", "projects/inside", ".."])
    def test_a_root_overlapping_home_is_refused_at_write_time(self, home, candidate):
        """The reader's double-count guard, enforced at write time too."""
        rf.init_roots(home, today=TODAY)
        ok, message = rf.add_root(home, candidate, today=TODAY)
        assert not ok
        assert "overlap" in message.lower()
        assert _read(home)["roots"] == []

    def test_the_same_root_cannot_be_declared_twice(self, home):
        """Mutant: add_root's duplicate refusal writes a second row before refusing — killed."""
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        ok, message = rf.add_root(home, str(home.parent / "wren"), today=TODAY)
        assert not ok, "the same directory was declared twice under two spellings"
        assert "already" in message.lower()
        assert [row["path"] for row in _read(home)["roots"]] == ["../wren"]

    def test_the_label_defaults_to_the_directory_name(self, home):
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        assert _read(home)["roots"][0]["label"] == "wren"

    def test_a_given_label_is_kept(self, home):
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", label="the-fence", today=TODAY)
        assert _read(home)["roots"][0]["label"] == "the-fence"

    def test_adding_stamps_the_file(self, home):
        rf.init_roots(home, today="2026-01-01")
        rf.add_root(home, "../wren", today=TODAY)
        assert _read(home)["metadata"]["last_updated"] == TODAY

    def test_add_refuses_when_the_file_is_absent(self, home):
        """Never create by side effect. `init` is the verb that creates."""
        ok, message = rf.add_root(home, "../wren", today=TODAY)
        assert not ok
        assert "init" in message.lower()
        assert not (home / rs.DECLARED_ROOTS).exists()


class TestRemoveTakesOnlyWhatIsThere:
    def test_a_declared_root_is_removed_by_any_spelling(self, home):
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        rf.add_root(home, "../Demo", today=TODAY)
        ok, message = rf.remove_root(home, str(home.parent / "wren"), today=TODAY)
        assert ok, message
        assert [row["path"] for row in _read(home)["roots"]] == ["../Demo"]

    def test_removing_something_never_declared_is_refused_not_ignored(self, home):
        """A no-op that reports success teaches the operator the wrong thing; nothing is written."""
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        ok, message = rf.remove_root(home, "../Demo", today=TODAY)
        assert not ok
        assert "not declared" in message.lower()
        assert [row["path"] for row in _read(home)["roots"]] == ["../wren"]
        assert len(_read(home)["roots"]) == 1

    def test_a_root_that_no_longer_exists_on_disk_can_still_be_removed(self, home):
        """Retiring a deleted repo must not require resurrecting it first."""
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../Demo", today=TODAY)
        (home.parent / "Demo").rmdir()
        ok, message = rf.remove_root(home, "../Demo", today=TODAY)
        assert ok, message
        assert _read(home)["roots"] == []


class TestListReportsResolutionNotJustRows:
    def test_it_reports_what_each_row_resolves_to(self, home):
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        rows = rf.list_roots(home)
        assert len(rows) == 1
        assert rows[0]["path"] == "../wren"
        assert rows[0]["resolves"] == home.parent / "wren"
        assert rows[0]["reachable"] is True

    def test_a_row_the_reader_would_drop_is_shown_as_unreachable(self, home):
        """The whole point of a list verb: show the rows that are quietly dead."""
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../Demo", today=TODAY)
        (home.parent / "Demo").rmdir()
        assert rf.list_roots(home)[0]["reachable"] is False

    def test_listing_an_absent_file_is_empty_and_not_an_error(self, home):
        assert rf.list_roots(home) == []


class TestHealingIsDeliberateAndNeverReDeclares:
    """The ruling, pinned: a rebuild may lose declarations but must never invent them."""

    def test_reading_a_corrupt_file_does_not_heal_it(self, home):
        """Healing stays out of the read path: the reader stays a reader."""
        (home / rs.DECLARED_ROOTS).write_text("{ broken", encoding="utf-8")
        assert rs.declared_roots(home) == []
        assert (home / rs.DECLARED_ROOTS).read_text(encoding="utf-8") == "{ broken"

    def test_heal_refuses_a_healthy_file(self, home):
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        ok, message, salvaged = rf.heal(home, today=TODAY)
        assert not ok
        assert "nothing to heal" in message.lower()
        assert salvaged == []
        assert len(_read(home)["roots"]) == 1

    def test_heal_rebuilds_an_empty_scaffold_never_a_populated_one(self, home):
        (home / rs.DECLARED_ROOTS).write_text('{"roots": [{"path": "../wren"', encoding="utf-8")
        ok, message, salvaged = rf.heal(home, today=TODAY)
        assert ok, message
        assert _read(home)["roots"] == [], "healing re-declared on the operator's behalf"

    def test_heal_preserves_the_original_bytes_rather_than_deleting_them(self, home):
        broken = '{"roots": [{"path": "../wren"'
        (home / rs.DECLARED_ROOTS).write_text(broken, encoding="utf-8")
        rf.heal(home, today=TODAY)
        preserved = home / rf.CORRUPT_SUFFIX_NAME
        assert preserved.is_file(), "the corrupt file was destroyed instead of set aside"
        assert preserved.read_text(encoding="utf-8") == broken

    def test_heal_reports_the_declarations_it_could_not_carry_across(self, home):
        """Report, never restore. The strings are for a human to re-declare."""
        (home / rs.DECLARED_ROOTS).write_text(
            '{"roots": [{"path": "../wren"}, {"path": "../Demo"} BROKEN', encoding="utf-8"
        )
        ok, _, salvaged = rf.heal(home, today=TODAY)
        assert ok
        assert set(salvaged) == {"../wren", "../Demo"}
        assert _read(home)["roots"] == [], "a salvaged path was silently re-declared"

    def test_heal_refuses_when_there_is_no_file_at_all(self, home):
        """Absent is `init`'s job; heal must not create the file."""
        ok, message, salvaged = rf.heal(home, today=TODAY)
        assert not ok
        assert "init" in message.lower()
        assert salvaged == []
        assert not (home / rs.DECLARED_ROOTS).exists(), "heal created the file init owns"


class TestOnePredicateNotTwo:
    """The write-time guard must BE the read-time guard, not agree with it."""

    def test_the_overlap_rule_is_the_readers_own(self):
        assert rf.overlaps_home is rs.overlaps_home

    def test_the_filename_is_the_readers_own(self):
        assert rf.ROOTS_FILE is rs.DECLARED_ROOTS


class TestTheLiveFileMatchesWhatTheVerbsWouldProduce:
    """Task 4: adopt the owner's hand-made file, or say exactly how it differs."""

    def test_the_blessed_declarations_survive_a_regeneration(self, tmp_path):
        live = rs.find_repo_root() / rs.DECLARED_ROOTS
        if not live.is_file():
            pytest.skip(f"no live {rs.DECLARED_ROOTS} on this machine -- adoption guard skipped")
        blessed = json.loads(live.read_text(encoding="utf-8"))

        stand_in = tmp_path / "AIPass"
        stand_in.mkdir()
        (stand_in / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        for row in blessed["roots"]:
            (stand_in.parent / Path(row["path"]).name).mkdir(exist_ok=True)
        rf.init_roots(stand_in, today=blessed["metadata"]["last_updated"])
        for row in blessed["roots"]:
            ok, message = rf.add_root(
                stand_in, row["path"], label=row["label"], today=blessed["metadata"]["last_updated"]
            )
            assert ok, f"the verbs refuse a blessed declaration: {message}"

        rebuilt = json.loads((stand_in / rs.DECLARED_ROOTS).read_text(encoding="utf-8"))
        assert rebuilt["roots"] == blessed["roots"], (
            "the verbs do not reproduce the owner's declarations -- his blessing is what must survive"
        )

    def test_the_live_file_is_exactly_what_the_verbs_produce(self, tmp_path):
        """The live file is byte-identical to its generator; a failure means it was hand-edited again."""
        live = rs.find_repo_root() / rs.DECLARED_ROOTS
        if not live.is_file():
            pytest.skip(f"no live {rs.DECLARED_ROOTS} on this machine -- adoption guard skipped")
        blessed = json.loads(live.read_text(encoding="utf-8"))

        stand_in = tmp_path / "AIPass"
        stand_in.mkdir()
        (stand_in / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        for row in blessed["roots"]:
            (stand_in.parent / Path(row["path"]).name).mkdir(exist_ok=True)
        rf.init_roots(stand_in, today=blessed["metadata"]["last_updated"])
        for row in blessed["roots"]:
            rf.add_root(stand_in, row["path"], label=row["label"], today=blessed["metadata"]["last_updated"])

        produced = (stand_in / rs.DECLARED_ROOTS).read_text(encoding="utf-8")
        assert produced == live.read_text(encoding="utf-8"), (
            "the live AIPASS_ROOTS.json is not byte-identical to what the verbs render"
        )


class TestTheOperatorLane:
    """The CLI, tested AFTER the handler: these pins are proven by mutation, not red-first."""

    def test_it_answers_only_its_own_command(self):
        assert roots.handle_command("rollover", []) is False
        assert roots.handle_command("search", ["x"]) is False

    @pytest.mark.parametrize("args", [[], ["--help"], ["-h"], ["help"], ["add", "--help"]])
    def test_help_is_reachable_from_any_position(self, capsys, args):
        """`roots add --help` shows help, never treats `--help` as a path."""
        assert roots.handle_command("roots", args) is True
        assert "roots Module" in capsys.readouterr().out

    def test_an_unknown_subcommand_is_named_not_swallowed(self, capsys):
        """An unknown subcommand is named AND exits non-zero."""
        reset_command_state()
        assert roots.handle_command("roots", ["nonsense"]) is True
        assert resolve_exit(True) == 2, "an unknown subcommand refused but would exit 0"
        captured = capsys.readouterr()
        assert "nonsense" in captured.out + captured.err

    @pytest.mark.parametrize("verb", ["add", "remove"])
    def test_a_verb_that_needs_a_path_refuses_without_one(self, capsys, verb):
        """Never operate on a default. A missing path is a question, not a zero."""
        reset_command_state()
        assert roots.handle_command("roots", [verb]) is True
        assert resolve_exit(True) == 2, f"roots {verb} refused but would exit 0"
        captured = capsys.readouterr()
        assert "needs a path" in captured.out + captured.err

    def test_the_module_is_discovered_but_the_gateway_is_not_this(self):
        """The write verbs stay off the read-only ``fleet`` gateway."""
        assert hasattr(roots, "handle_command")
        assert not hasattr(fleet, "add_root"), "the write lane leaked onto the read gateway"


class _WindowsFlavour(pathlib.PureWindowsPath):
    """A path that spells itself the way Windows does, on any machine, so the ``_spell`` pin has teeth on Linux."""

    def resolve(self):
        return self


class TestTheDeclaredSpellingIsPosixOnEveryMachine:
    """One declaration, one spelling: forward slashes, the only spelling both platforms read."""

    def test_a_sibling_is_spelled_with_forward_slashes(self, monkeypatch):
        monkeypatch.setattr(rf, "Path", _WindowsFlavour)

        spelled = rf._spell(_WindowsFlavour(r"C:\proj\AIPass"), _WindowsFlavour(r"C:\proj\wren"))

        assert spelled == "../wren"

    def test_an_absolute_declaration_is_spelled_with_forward_slashes_too(self, monkeypatch):
        """The other return path. A contract honoured on one branch is a coincidence."""
        monkeypatch.setattr(rf, "Path", _WindowsFlavour)

        spelled = rf._spell(_WindowsFlavour(r"C:\proj\AIPass"), _WindowsFlavour(r"D:\elsewhere\wren"))

        assert spelled == "D:/elsewhere/wren"

    def test_no_declaration_this_verb_writes_can_carry_a_backslash(self, home):
        """The end-to-end guard, in the file that ships."""
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, str(home.parent / "wren"), today=TODAY)

        assert "\\" not in (home / rs.DECLARED_ROOTS).read_text(encoding="utf-8")

    def test_the_reader_resolves_what_the_writer_spelled(self, home):
        """Writer and reader are pinned by round trip, not against a literal."""
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, str(home.parent / "wren"), today=TODAY)

        assert rs.declared_roots(home) == [(home.parent / "wren").resolve()]
