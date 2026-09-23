# =================== META ====================
# Name: test_sleep_in_test_check.py
# Description: sleep_in_test_check — crack class N, a test that waits instead of asserting
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/sleep_in_test_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the line and the spelling are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs, sleep_in_test_check
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"


def _write(tmp_path, body, name="test_specimen.py"):
    """A file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_file_never_waits(self):
        """tests/test_readme_update.py holds no sleep."""
        assert sleep_in_test_check.scan(MODEL.read_text(encoding="utf-8")) == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert sleep_in_test_check.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    """test_versioned_engine.py 89/110/126/240/315/441 — @backup's mtime nudges."""

    def test_the_mtime_nudge_is_convicted(self):
        """0.01s does not move an mtime on a one-second-granularity filesystem."""
        source = "def test_it():\n    path.write_text('v2')\n    time.sleep(0.01)\n"
        assert sleep_in_test_check.scan(source) == [(3, "time.sleep")]

    def test_a_polling_loop_is_convicted(self):
        """A fixed wait is a bet the machine is fast enough today."""
        source = "def test_it():\n    while not done:\n        time.sleep(0.1)\n"
        assert sleep_in_test_check.scan(source) == [(3, "time.sleep")]

    def test_every_sleep_is_scored_and_none_is_merely_counted(self):
        """The dispatch's ruling: score all. Both shapes have a strictly better cure."""
        source = "def test_a():\n    time.sleep(1)\ndef test_b():\n    time.sleep(2)\n"
        assert sleep_in_test_check.scan(source) == [(2, "time.sleep"), (4, "time.sleep")]


class TestItMatchesThroughTheAlias:
    """The implementation lesson: match the call's TAIL name, not ``time.sleep``."""

    @pytest.mark.parametrize(
        "spelling",
        ["time.sleep", "_time.sleep", "time_module.sleep", "time_mod.sleep"],
    )
    def test_each_spelling_the_fleet_uses_is_caught(self, spelling):
        """Matching only time.sleep found 14 files and missed eight calls."""
        found = sleep_in_test_check.scan(f"def test_it():\n    {spelling}(0.01)\n")
        assert found == [(2, spelling)]

    def test_a_bare_sleep_is_caught_and_named_plainly(self):
        """from time import sleep has no module to name, so the finding says sleep."""
        assert sleep_in_test_check.scan("def test_it():\n    sleep(0.5)\n") == [(2, "sleep")]


class TestWhatIsNotJudged:
    """A name that merely ends in sleep is not a call to one."""

    def test_an_attribute_that_is_never_called_is_acquitted(self):
        """Handing the function somewhere is not waiting on it here."""
        assert sleep_in_test_check.scan("def test_it():\n    assert fn is time.sleep\n") == []

    def test_a_different_verb_on_the_time_module_is_acquitted(self):
        """time.time() reads the clock; it does not stop for it."""
        assert sleep_in_test_check.scan("def test_it():\n    start = time.time()\n") == []

    def test_an_unparseable_file_yields_nothing(self):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert sleep_in_test_check.scan("def test_it(:\n") == []


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, "def test_it():\n    time.sleep(0.01)\n")
        assert sleep_in_test_check.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = sleep_in_test_check.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_a_clean_file_reads_plainly(self, tmp_path):
        """Nothing to report, so nothing to read past."""
        path = _write(tmp_path, "def test_it():\n    assert run() == 3\n")
        message = sleep_in_test_check.check_module(str(path))["checks"][0]["message"]
        assert message == "Nothing here waits on the clock"

    def test_the_message_names_the_line_the_spelling_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        path = _write(tmp_path, "def test_it():\n    time_mod.sleep(0.1)\n")
        message = sleep_in_test_check.check_module(str(path))["checks"][0]["message"]
        assert "test_specimen.py:2 time_mod.sleep" in message
        assert sleep_in_test_check.CURE in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one sleep and '(+1 more)'."""
        body = "def test_a():\n    time.sleep(1)\ndef test_b():\n    sleep(2)\n"
        checks = sleep_in_test_check.check_module(str(_write(tmp_path, body)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(sleep_in_test_check.CURE) == 2

    def test_the_command_prints_the_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, "def test_it():\n    time.sleep(0.01)\n")

        checklist.handle_command("checklist", [str(path)])

        assert "[FAIL] — sleep_in_test" in capsys.readouterr().out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """A sleep in a daemon is the product's business, not a test smell."""
        assert sleep_in_test_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A sleep's verdict belongs on the file that waits."""
        assert sleep_in_test_check.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "sleep_in_test", "pattern": "*"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, "def test_it():\n    time.sleep(0.01)\n")
        assert sleep_in_test_check.check_module(str(path), bypass_rules=rules)["score"] == 100
