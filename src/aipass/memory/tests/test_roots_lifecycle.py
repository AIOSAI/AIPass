# =================== AIPass ====================
# Name: test_roots_lifecycle.py
# Description: Pins the template, verbs and healing for AIPASS_ROOTS.json
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""The anchor is written by code, from a template, or it is not written.

FPLAN-0460 phase 4. @devpulse created AIPASS_ROOTS.json by hand this morning and
Patrick ruled on seeing it, verbatim: "jsons are normally created by code, so if
they corrupt or get deleted they are always rebuilt from default settings from a
template directory."

THE ASYMMETRY THAT SHAPES ALL OF THIS. The reader already refuses a row it cannot
use -- a path that does not exist, one that overlaps AIPass home, a duplicate.
Refusing at READ time means the file is allowed to carry a row that will never be
honoured, and the only place that fact appears is a log line nobody is reading.
So every one of those refusals now happens at WRITE time too, against the same
predicate, so the file cannot contain a declaration the reader will silently
drop.

HEALING IS A SEPARATE, DELIBERATE VERB, never a side effect of reading. Stated
here because it is a design ruling and not an implementation detail: an automatic
rebuild would replace Patrick's declarations with an empty scaffold as a
side effect of any lane that happened to read the file first -- rollover, lint,
health, @daemon's scheduler -- and because ZERO ROOTS IS A LEGAL STATE, nothing
downstream would fail. The system would keep running and quietly maintain
nothing. That is re-declaring on Patrick's behalf, which is exactly what
declaration-is-the-credential forbids. Same principle as the One Law's fourth
hat: unreadable gold REFUSES rather than scoring zero.

So: the reader keeps refusing, exactly as it does today, and ``roots heal`` is
the one thing that may write a scaffold over a broken file -- after preserving
the original bytes and printing what it could not carry across.
"""

import json
import pathlib
from pathlib import Path

import pytest

from aipass.memory.apps.handlers.monitor import registry_scope as rs
from aipass.memory.apps.handlers.monitor import roots_file as rf


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
        """Belt and braces, made load-bearing rather than left as decoration.

        Found by mutation: dropping the ``roots = []`` line in the renderer
        survived, because today's template happens to be empty. The line is the
        guarantee that a template edited to carry an example root cannot declare
        on an installation's behalf the moment it renders — so it is pinned
        against a template that does exactly that.
        """
        stub = tmp_path / "stub.template.json"
        stub.write_text(
            json.dumps({"metadata": {"version": "1.0.0"}, "roots": [{"path": "../example", "status": "active"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(rf, "template_path", lambda: stub)
        assert rf.render_scaffold(TODAY)["roots"] == []

    def test_the_rendered_scaffold_is_what_the_reader_accepts(self, home):
        """The template and the reader are pinned to each other, not just to a schema.

        A scaffold the reader rejects would be a template that produces a file
        needing repair the moment it is created.
        """
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
        """The MESSAGE is the pin, because the guard is otherwise redundant.

        Found by mutation: deleting the existence check survived, since
        ``Path.is_dir()`` is already False for a path that is not there. What
        the check actually buys is a different DIAGNOSIS — "you named something
        that is not on this machine" and "you named something that is not a
        directory" send an operator to two different places. A branch that
        exists only for its wording is pinned on its wording or it is dead code.
        """
        rf.init_roots(home, today=TODAY)
        ok, message = rf.add_root(home, "../nowhere", today=TODAY)
        assert not ok
        assert "does not exist" in message
        assert _read(home)["roots"] == []

    def test_a_file_outside_home_is_refused_as_not_a_directory(self, home):
        """Outside home DELIBERATELY: a file inside it is refused by the overlap
        guard first, so testing that one proved nothing about this one — which
        is exactly how the missing case hid."""
        rf.init_roots(home, today=TODAY)
        ok, message = rf.add_root(home, "../loose.txt", today=TODAY)
        assert not ok
        assert "not a directory" in message
        assert _read(home)["roots"] == []

    @pytest.mark.parametrize("candidate", [".", "projects/inside", ".."])
    def test_a_root_overlapping_home_is_refused_at_write_time(self, home, candidate):
        """The double-count guard, moved forward to where it can be answered.

        The reader refuses these already. Refusing them here means the file
        never carries a row whose only trace of being wrong is a log line.
        """
        rf.init_roots(home, today=TODAY)
        ok, message = rf.add_root(home, candidate, today=TODAY)
        assert not ok
        assert "overlap" in message.lower()
        assert _read(home)["roots"] == []

    def test_the_same_root_cannot_be_declared_twice(self, home):
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        ok, message = rf.add_root(home, str(home.parent / "wren"), today=TODAY)
        assert not ok, "the same directory was declared twice under two spellings"
        assert "already" in message.lower()
        assert len(_read(home)["roots"]) == 1

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
        """A no-op that reports success teaches the operator the wrong thing."""
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, "../wren", today=TODAY)
        ok, message = rf.remove_root(home, "../Demo", today=TODAY)
        assert not ok
        assert "not declared" in message.lower()
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
        """The pin that keeps healing out of the read path.

        If any lane could trigger a rebuild by reading, a corrupt file would be
        replaced with an empty scaffold as a side effect, and because zero roots
        is a LEGAL state nothing downstream would fail. This asserts the reader
        stayed a reader.
        """
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
        """Absent is `init`'s job. Two verbs that both create is one too many."""
        ok, message, _ = rf.heal(home, today=TODAY)
        assert not ok
        assert "init" in message.lower()


class TestOnePredicateNotTwo:
    """The write-time guard must BE the read-time guard, not agree with it."""

    def test_the_overlap_rule_is_the_readers_own(self):
        assert rf.overlaps_home is rs.overlaps_home

    def test_the_filename_is_the_readers_own(self):
        assert rf.ROOTS_FILE is rs.DECLARED_ROOTS


class TestTheLiveFileMatchesWhatTheVerbsWouldProduce:
    """Task 4: adopt Patrick's hand-made file, or say exactly how it differs."""

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
            "the verbs do not reproduce Patrick's declarations -- his blessing is what must survive"
        )

    def test_the_live_file_is_exactly_what_the_verbs_produce(self, tmp_path):
        """After adoption there is no daylight between the file and its generator.

        The declarations are Patrick's and are asserted above; THIS is the pin
        that says the hand-made file has been brought under code management
        rather than merely tolerated. If it fails, the live file was edited by
        hand again.
        """
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
    """The CLI, tested AFTER the handler rather than before it — stated, not hidden.

    The handler below it was written red-first; this layer was not, so every pin
    here is proven by mutation instead of by having watched it fail. That is a
    weaker guarantee and it is named as one.
    """

    def test_it_answers_only_its_own_command(self):
        from aipass.memory.apps.modules import roots

        assert roots.handle_command("rollover", []) is False
        assert roots.handle_command("search", ["x"]) is False

    @pytest.mark.parametrize("args", [[], ["--help"], ["-h"], ["help"], ["add", "--help"]])
    def test_help_is_reachable_from_any_position(self, capsys, args):
        """`roots add --help` is what a person types when the order escapes them.

        A gate reading args[0] alone treats that as a path and refuses, which is
        the worst possible answer to a request for help.
        """
        from aipass.memory.apps.modules import roots

        assert roots.handle_command("roots", args) is True
        assert "roots Module" in capsys.readouterr().out

    def test_an_unknown_subcommand_is_named_not_swallowed(self, capsys):
        from aipass.memory.apps.modules import roots

        assert roots.handle_command("roots", ["nonsense"]) is True
        captured = capsys.readouterr()
        assert "nonsense" in captured.out + captured.err

    @pytest.mark.parametrize("verb", ["add", "remove"])
    def test_a_verb_that_needs_a_path_refuses_without_one(self, capsys, verb):
        """Never operate on a default. A missing path is a question, not a zero."""
        from aipass.memory.apps.modules import roots

        assert roots.handle_command("roots", [verb]) is True
        captured = capsys.readouterr()
        assert "needs a path" in captured.out + captured.err

    def test_the_module_is_discovered_but_the_gateway_is_not_this(self):
        """Two modules, two jobs: the library door stays a door.

        ``modules/fleet.py`` carries a pin that its command surface computes
        nothing. These verbs write files, which is why they are not on it.
        """
        from aipass.memory.apps.modules import fleet, roots

        assert hasattr(roots, "handle_command")
        assert not hasattr(fleet, "add_root"), "the write lane leaked onto the read gateway"


class _WindowsFlavour(pathlib.PureWindowsPath):
    """A path that spells itself the way Windows does, on any machine.

    ``_spell`` is a STRING contract, and on Linux every separator is already a
    forward slash — so a test that just asserts "no backslash" passes whether
    or not the code does anything, which is a green light wired to nothing. The
    flavour is what has to be injected for the pin to have teeth here.

    ``resolve`` returns self because these paths are already absolute and there
    is no filesystem behind them; the walk being pinned is arithmetic on names.
    """

    def resolve(self):
        return self


class TestTheDeclaredSpellingIsPosixOnEveryMachine:
    """One declaration, one spelling — decided after a Windows CI red.

    ``str()`` on a Windows path yields ``..\\wren``, so before this the same
    ``roots add`` produced two different rows depending on which machine ran
    it. Forward slashes are the only spelling BOTH platforms read: Windows
    resolves ``../wren`` correctly, while ``..\\wren`` on POSIX is a FILENAME
    containing a backslash, not a path — so the row that a Windows box wrote
    would silently declare a root that does not exist when read back on Linux.

    The anchor is a file Patrick blesses. It has to read the same to a human on
    either machine, and it has to diff.
    """

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
        """The two halves are pinned against each other, not against a literal.

        A writer and a reader that agree because both were changed to match a
        test string agree about the test. This asserts the round trip.
        """
        rf.init_roots(home, today=TODAY)
        rf.add_root(home, str(home.parent / "wren"), today=TODAY)

        assert rs.declared_roots(home) == [(home.parent / "wren").resolve()]
