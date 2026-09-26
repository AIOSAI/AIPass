# =================== META ====================
# Name: test_unconsumed_side_effect_check.py
# Description: unconsumed_side_effect_check — crack class F, queued mock answers nothing counts
# Version: 1.0.1
# Created: 2026-09-23
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/unconsumed_side_effect_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.handlers.aipass_standards import unconsumed_side_effect_check as checker
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: The planted specimen: three answers queued, nothing counting them.
QUEUED = "def test_it():\n    drive_api.side_effect = [{'files': []}, {'id': 'new'}, {'name': 'Backups'}]\n"


def _scored(source):
    """Just the (line, mock, count) rows this rule charges."""
    return checker.scan(source)[0]


def _counted(source):
    """How many queues rode in the passing message instead."""
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
        """tests/test_readme_update.py queues nothing it does not count."""
        assert _scored(MODEL.read_text(encoding="utf-8")) == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    """test_drive_pipeline.py:231 — three answers, and nothing says three."""

    def test_a_queue_nothing_counts_is_convicted(self):
        """If the product calls twice the third answer is silently lost."""
        assert _scored(QUEUED) == [(2, "drive_api", 3)]

    def test_a_dotted_mock_is_named_in_full(self):
        """test_share.py's client._api_call must be findable from the finding."""
        source = "def test_it():\n    client._api_call.side_effect = [1, 2]\n"
        assert _scored(source) == [(2, "client._api_call", 2)]

    def test_a_tuple_queue_is_the_same_shape(self):
        """A tuple of answers loses its tail exactly as a list does."""
        assert _scored("def test_it():\n    m.side_effect = (1, 2, 3)\n") == [(2, "m", 3)]


class TestWhatAcquits:
    """One assertion on the calls turns the list's length into a claim."""

    @pytest.mark.parametrize(
        "claim",
        [
            "assert m.call_count == 2",
            "m.assert_has_calls([call(1), call(2)])",
            "m.assert_called_once_with(1)",
            "m.assert_not_called()",
            "assert m.mock_calls == []",
            "assert m.call_args.args == (1,)",
        ],
    )
    def test_every_consumer_acquits(self, claim):
        """Each is a different way of saying how many times, or with what."""
        assert _scored(f"def test_it():\n    m.side_effect = [1, 2]\n    {claim}\n") == []

    def test_a_consumer_on_a_different_mock_does_not_acquit(self):
        """Counting one mock says nothing about the queue on another."""
        source = "def test_it():\n    m.side_effect = [1, 2]\n    assert other.call_count == 2\n"
        assert _scored(source) == [(2, "m", 2)]

    def test_counted_calls_is_the_one_collector(self):
        """The acquittal set every verdict is built from."""
        import ast

        tree = ast.parse("def test_it():\n    assert a.call_count == 1\n    b.assert_has_calls([])\n")
        assert checker.counted_calls(tree.body[0]) == {"a", "b"}


class TestWhatIsCountedAndNotScored:
    """The mock is watched, just not counted — the owner should see it, not wear it."""

    def test_a_mock_asserted_some_other_way_is_counted(self):
        """Its return value reaches an assert, so the test is looking at it."""
        source = "def test_it():\n    m.side_effect = [1, 2]\n    assert m.return_value == 7\n"
        assert _scored(source) == []
        assert _counted(source) == 1

    def test_the_count_rides_in_the_passing_message(self, tmp_path):
        """A number the owner asked for, never a verdict."""
        body = "def test_it():\n    m.side_effect = [1, 2]\n    assert m.return_value == 7\n"
        result = checker.check_module(str(_write(tmp_path, body)))
        assert result["score"] == 100
        assert "1 queue is watched some other way but never counted" in result["checks"][0]["message"]


class TestWhatIsNotJudged:
    """A single answer has no tail to lose."""

    def test_a_queue_of_one_is_never_judged(self):
        """One queued answer is a return value spelled differently."""
        assert _scored("def test_it():\n    m.side_effect = [1]\n") == []

    def test_a_callable_side_effect_is_not_a_queue(self):
        """`side_effect = fn` routes every call; there is no list to exhaust."""
        assert _scored("def test_it():\n    m.side_effect = OSError\n") == []

    def test_a_helper_that_is_not_a_test_is_not_judged(self):
        """A fixture builder's queue is consumed by the tests that request it."""
        assert _scored("def build():\n    m.side_effect = [1, 2]\n") == []

    def test_an_unparseable_file_yields_nothing(self):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert checker.scan("def test_it(:\n") == ([], 0)


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        assert checker.check_module(str(_write(tmp_path, QUEUED)))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = checker.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_a_clean_file_reads_plainly(self, tmp_path):
        """No count to report, so no parenthetical to read past."""
        path = _write(tmp_path, "def test_it():\n    assert run() == 3\n")
        message = checker.check_module(str(path))["checks"][0]["message"]
        assert message == "Every queued side effect here is claimed by an assertion"

    def test_the_message_names_the_mock_the_count_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        message = checker.check_module(str(_write(tmp_path, QUEUED)))["checks"][0]["message"]
        assert "drive_api is queued 3 answers and nothing counts them" in message
        assert checker.CURE in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one mock and '(+1 more)'."""
        body = "def test_a():\n    m.side_effect = [1, 2]\ndef test_b():\n    n.side_effect = [3, 4]\n"
        checks = checker.check_module(str(_write(tmp_path, body)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(checker.CURE) == 2

    def test_the_command_prints_the_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, QUEUED)

        checklist.handle_command("checklist", [str(path)])

        assert "[FAIL] — unconsumed_side_effect" in capsys.readouterr().out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Only a test queues answers for a mock."""
        assert checker.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """An uncounted queue belongs on the file that writes it."""
        assert checker.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "unconsumed_side_effect"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, QUEUED)
        assert (
            checker.check_module(str(path), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules])["score"]
            == 100
        )
