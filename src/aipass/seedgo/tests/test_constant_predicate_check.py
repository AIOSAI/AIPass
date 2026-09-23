# =================== META ====================
# Name: test_constant_predicate_check.py
# Description: constant_predicate_check — crack class C, a lambda that cannot discriminate
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/constant_predicate_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the line and the constant are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import constant_predicate_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"


def _scored(source):
    """Just the (line, constant) pairs this rule charges."""
    return constant_predicate_check.scan(source)[0]


def _counted(source):
    """The constants reported with a count and charged to nobody."""
    return constant_predicate_check.scan(source)[1]


def _write(tmp_path, body, name="test_specimen.py"):
    """A file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_file_scores_nothing(self):
        """tests/test_readme_update.py charges no lambda."""
        assert _scored(MODEL.read_text(encoding="utf-8")) == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert constant_predicate_check.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    """test_ignore_pathspec.py:491 — mirror.py:95 never calls should_ignore."""

    def test_a_false_predicate_handed_to_the_product_is_convicted(self):
        """It answers False for every path, so it can discriminate nothing."""
        source = "def test_it():\n    mirror_tree(src, dst, should_ignore=lambda p: False)\n"
        assert _scored(source) == [(2, "False")]

    def test_a_true_predicate_is_convicted_too(self):
        """The constant's value is not the point; that it never changes is."""
        assert _scored("def test_it():\n    walk(root, keep=lambda p: True)\n") == [(2, "True")]

    def test_a_positional_lambda_is_convicted(self):
        """A keyword is not required — the ARGUMENT position is the rule."""
        assert _scored("def test_it():\n    walk(root, lambda p: False)\n") == [(2, "False")]


class TestWhatIsCountedAndNotScored:
    """Each can legitimately be the right stub and a rule cannot tell which."""

    def test_a_none_returning_callback_is_counted(self):
        """236 of the fleet's 309 — an on_progress or a logger, not a predicate."""
        source = "def test_it():\n    run(path, on_progress=lambda *a: None)\n"
        assert _scored(source) == []
        assert _counted(source) == ["None"]

    def test_a_value_returning_stand_in_is_counted(self):
        """It answers the product's question; it does not refuse to."""
        source = "def test_it():\n    render(rows, header=lambda r: 'HEADER')\n"
        assert _scored(source) == []
        assert _counted(source) == ["'HEADER'"]

    def test_zero_is_counted_not_scored(self):
        """isinstance(True, int) is True in Python, so bool is checked FIRST."""
        source = "def test_it():\n    measure(path, size=lambda p: 0)\n"
        assert _scored(source) == []
        assert _counted(source) == ["0"]


class TestWhatIsNotJudged:
    """The argument position is what makes a lambda a predicate."""

    def test_a_lambda_that_is_never_handed_over_is_acquitted(self):
        """Bound to a name and left there, it is not yet consulted by anything."""
        assert _scored("def test_it():\n    never = lambda p: False\n") == []

    def test_a_lambda_with_a_real_body_is_acquitted(self):
        """It depends on its argument, which is the whole cure."""
        assert _scored("def test_it():\n    walk(root, keep=lambda p: p.suffix == '.py')\n") == []

    def test_an_unparseable_file_yields_nothing(self):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert constant_predicate_check.scan("def test_it(:\n") == ([], [])


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, "def test_it():\n    walk(root, keep=lambda p: False)\n")
        assert constant_predicate_check.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = constant_predicate_check.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_the_counted_stubs_ride_in_the_passing_message(self, tmp_path):
        """The number the owner asked for rides along, and nobody is charged."""
        path = _write(tmp_path, "def test_it():\n    run(p, on_progress=lambda *a: None)\n")
        result = constant_predicate_check.check_module(str(path))
        assert result["score"] == 100
        assert "1 inert callback stub are counted" in result["checks"][0]["message"]

    def test_a_file_with_no_stub_reads_plainly(self, tmp_path):
        """No count to report, so no parenthetical to read past."""
        path = _write(tmp_path, "def test_it():\n    assert run() == 3\n")
        message = constant_predicate_check.check_module(str(path))["checks"][0]["message"]
        assert message == "Every callable handed to the product here can discriminate"

    def test_the_message_names_the_constant_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        path = _write(tmp_path, "def test_it():\n    walk(root, keep=lambda p: False)\n")
        message = constant_predicate_check.check_module(str(path))["checks"][0]["message"]
        assert "always returns False" in message
        assert constant_predicate_check.CURE in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one lambda and '(+1 more)'."""
        body = "def test_a():\n    walk(r, keep=lambda p: False)\ndef test_b():\n    walk(r, keep=lambda p: True)\n"
        checks = constant_predicate_check.check_module(str(_write(tmp_path, body)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(constant_predicate_check.CURE) == 2

    def test_the_command_prints_the_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, "def test_it():\n    walk(root, keep=lambda p: False)\n")

        checklist.handle_command("checklist", [str(path)])

        assert "[FAIL] — constant_predicate" in capsys.readouterr().out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """A constant lambda in production code is a different question."""
        assert constant_predicate_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A lambda's verdict belongs on the file that hands it over."""
        assert constant_predicate_check.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "constant_predicate", "pattern": "*"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, "def test_it():\n    walk(root, keep=lambda p: False)\n")
        assert constant_predicate_check.check_module(str(path), bypass_rules=rules)["score"] == 100
