# =================== META ====================
# Name: test_self_set_assert_check.py
# Description: self_set_assert_check — crack class E, a test asserting what it just wrote
# Version: 1.0.1
# Created: 2026-09-23
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/self_set_assert_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import self_set_assert_check as checker
from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"


def _scored(source):
    """Just the (line, path, shape) rows this rule charges."""
    return checker.scan(source)[0]


def _counted(source):
    """How many re-reads rode in the passing message instead."""
    return checker.scan(source)[1]


def _write(tmp_path, body, name="test_specimen.py"):
    """A file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_file_charges_nothing(self):
        """tests/test_readme_update.py asserts what the product computed."""
        assert _scored(MODEL.read_text(encoding="utf-8")) == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    """One per shape, because the three read completely differently in source."""

    def test_an_attribute_the_test_wrote_is_convicted(self):
        """test_snapshot_fidelity.py:63 — r.files_deleted = 5, then assert it is 5."""
        source = "def test_it():\n    r.files_deleted = 5\n    assert r.files_deleted == 5\n"
        assert _scored(source) == [(3, "r.files_deleted", checker.ATTRIBUTE)]

    def test_a_constructor_kwarg_read_straight_back_is_convicted(self):
        """test_handlers_filesystem.py:230 — 14 of the fleet's 15, and the invisible one."""
        source = 'def test_it():\n    result = BackupResult(mode="snapshot")\n    assert result.mode == "snapshot"\n'
        assert _scored(source) == [(3, "result.mode", checker.KWARG)]

    def test_a_dict_item_the_test_wrote_is_convicted(self):
        """The third spelling of the same write-then-read."""
        source = "def test_it():\n    inbox['unread'] = 0\n    assert inbox['unread'] == 0\n"
        assert _scored(source) == [(3, "inbox['unread']", checker.ITEM)]


class TestTheJudgementItMakes:
    """A call in between turns a tautology into a durability oracle."""

    def test_a_re_read_after_a_call_is_counted_not_scored(self):
        """'the product did not clobber this' is a real claim about the product."""
        source = (
            "def test_it():\n"
            "    client.tracker = 'abc'\n"
            "    assert client.get_or_create_folder() == 'found'\n"
            "    assert client.tracker == 'abc'\n"
        )
        assert _scored(source) == []
        assert _counted(source) == 1

    def test_a_call_that_ran_before_the_write_does_not_acquit(self):
        """Only a call BETWEEN the write and the read can have clobbered anything."""
        source = "def test_it():\n    run_it()\n    r.count = 5\n    assert r.count == 5\n"
        assert _scored(source) == [(4, "r.count", checker.ATTRIBUTE)]

    def test_the_constructor_call_itself_does_not_acquit_its_own_kwarg(self):
        """The call that SET the value is not a call that ran after it."""
        source = 'def test_it():\n    e = Event(level="error")\n    assert e.level == "error"\n'
        assert _scored(source) == [(3, "e.level", checker.KWARG)]


class TestTheOtherLineItHolds:
    """The comparison must be == against the SAME literal."""

    def test_a_property_read_back_from_a_backing_field_is_acquitted(self):
        """test_drive_pipeline.py:198 — _drive_service set, drive_service asserted."""
        source = "def test_it():\n    client._drive_service = service\n    assert client.drive_service is service\n"
        assert _scored(source) == []

    def test_an_is_comparison_is_not_this_rules_shape(self):
        """`is` is identity, not the value equality this rule reads."""
        assert _scored("def test_it():\n    r.flag = True\n    assert r.flag is True\n") == []

    def test_a_different_value_is_acquitted(self):
        """Writing 5 and asserting 6 is a test that can fail, which is the point."""
        assert _scored("def test_it():\n    r.count = 5\n    assert r.count == 6\n") == []

    def test_a_non_literal_write_is_not_judged(self):
        """`r.count = measure()` is the product's answer, not the test's."""
        assert _scored("def test_it():\n    r.count = measure()\n    assert r.count == 5\n") == []


class TestWhatIsNotJudged:
    """The rule reads test bodies, and only writes that precede a read."""

    def test_a_read_of_something_never_written_is_acquitted(self):
        """The default a dataclass supplies is the product's, not the test's."""
        source = 'def test_it():\n    r = BackupResult(mode="snapshot")\n    assert r.files_copied == 0\n'
        assert _scored(source) == []

    def test_a_helper_that_is_not_a_test_is_not_judged(self):
        """A fixture builder may legitimately assert its own scaffolding."""
        assert _scored("def build():\n    r.count = 5\n    assert r.count == 5\n") == []

    def test_an_unparseable_file_yields_nothing(self):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert checker.scan("def test_it(:\n") == ([], 0)

    def test_written_here_reads_all_three_shapes(self):
        """The one collector every verdict is built from."""
        import ast

        tree = ast.parse("def test_it():\n    a.b = 1\n    d['k'] = 2\n    o = C(x=3)\n")
        written = checker.written_here(tree.body[0])
        assert {path: value for path, (value, _shape, _line) in written.items()} == {
            "a.b": "1",
            "d['k']": "2",
            "o.x": "3",
        }


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, "def test_it():\n    r.count = 5\n    assert r.count == 5\n")
        assert checker.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = checker.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_the_durability_count_rides_in_the_passing_message(self, tmp_path):
        """The number rides along without becoming a verdict."""
        body = "def test_it():\n    c.t = 'a'\n    assert c.run() == 1\n    assert c.t == 'a'\n"
        result = checker.check_module(str(_write(tmp_path, body)))
        assert result["score"] == 100
        assert "1 assertion re-reads a value after a call ran" in result["checks"][0]["message"]

    def test_a_clean_file_reads_plainly(self, tmp_path):
        """No count to report, so no parenthetical to read past."""
        path = _write(tmp_path, "def test_it():\n    assert run() == 3\n")
        message = checker.check_module(str(path))["checks"][0]["message"]
        assert message == "Every assertion here compares a value the product produced"

    def test_the_message_names_the_path_the_shape_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        path = _write(tmp_path, 'def test_it():\n    e = Event(level="error")\n    assert e.level == "error"\n')
        message = checker.check_module(str(path))["checks"][0]["message"]
        assert f"e.level was set by this test ({checker.KWARG})" in message
        assert checker.CURE in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one assertion and '(+1 more)'."""
        body = "def test_it():\n    r.a = 1\n    r.b = 2\n    assert r.a == 1\n    assert r.b == 2\n"
        checks = checker.check_module(str(_write(tmp_path, body)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(checker.CURE) == 2

    def test_the_command_prints_the_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, "def test_it():\n    r.count = 5\n    assert r.count == 5\n")

        checklist.handle_command("checklist", [str(path)])

        assert "[FAIL] — self_set_assert" in capsys.readouterr().out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Production code setting and reading its own field is not an oracle."""
        assert checker.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A tautological assert belongs on the file that writes it."""
        assert checker.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "self_set_assert"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, "def test_it():\n    r.count = 5\n    assert r.count == 5\n")
        assert (
            checker.check_module(str(path), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules])["score"]
            == 100
        )
