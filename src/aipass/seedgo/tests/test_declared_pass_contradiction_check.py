# =================== META ====================
# Name: test_declared_pass_contradiction_check.py
# Description: declared_pass_contradiction_check — crack class H, a declared pass the file breaks
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""Tests for apps/handlers/aipass_standards/declared_pass_contradiction_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import declared_pass_contradiction_check as checker
from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: A declared pass that names a constant, the category a value can contradict.
DECLARES = "# seedgo: no-test-needed(constant) — TRACKER_FILENAME's string\n"


def _branch(tmp_path, product, test_body, declared=DECLARES):
    """A branch tree the rule can resolve: apps/ to read, tests/ to judge."""
    apps = tmp_path / "apps"
    apps.mkdir(exist_ok=True)
    (apps / "names.py").write_text(product, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    path = tests / "test_specimen.py"
    path.write_text(f'"""Tests."""\n{declared}\n{test_body}', encoding="utf-8")
    checker.product_facts.cache_clear()
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_files_declared_pass_holds(self):
        """tests/test_readme_update.py declares nothing it then contradicts."""
        assert checker.check_module(str(MODEL))["score"] == 100

    def test_the_model_files_prose_lines_ride_as_a_count(self):
        """Its declarations name prose, which is a legitimate declaration."""
        message = checker.check_module(str(MODEL))["checks"][0]["message"]
        assert "lines name prose or a stdlib call" in message


class TestThePlantedSpecimen:
    """test_drive_pipeline.py:13 declares TRACKER_FILENAME; 451, 462, 471 pin its string."""

    def test_a_declared_constant_whose_value_is_asserted_is_convicted(self, tmp_path):
        """The file says the value needs no test, then pins exactly that value."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    assert path.name == "drive_tracker.json"\n',
        )
        findings, _ = checker.scan(path.read_text(encoding="utf-8"), tmp_path)
        assert [(name, "asserted as a literal" in why) for _line, name, why in findings] == [("TRACKER_FILENAME", True)]

    def test_a_declared_symbol_that_exists_nowhere_is_convicted(self, tmp_path):
        """test_ceiling_guard.py:14 names DEFAULT_MAX_SIZE_GB; the constant is DEFAULT_MAX_TOTAL_GB."""
        path = _branch(
            tmp_path,
            "DEFAULT_MAX_TOTAL_GB = 10\n",
            "def test_it():\n    assert check() == 10\n",
            declared="# seedgo: no-test-needed(constant) — DEFAULT_MAX_SIZE_GB constant value\n",
        )
        findings, _ = checker.scan(path.read_text(encoding="utf-8"), tmp_path)
        assert [(name, "names nothing" in why) for _line, name, why in findings] == [("DEFAULT_MAX_SIZE_GB", True)]

    def test_the_finding_names_the_declared_line(self, tmp_path):
        """The owner has to find the line they wrote, not grep for the symbol."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    assert p.name == "drive_tracker.json"\n',
        )
        assert checker.scan(path.read_text(encoding="utf-8"), tmp_path)[0][0][0] == 2


class TestTheJudgementItMakes:
    """Using a constant by name is consistent with declaring its prose untested."""

    def test_a_constant_used_by_name_is_acquitted(self, tmp_path):
        """assert CURE in message survives any change to CURE's text."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            "def test_it():\n    assert TRACKER_FILENAME in message\n",
        )
        assert checker.scan(path.read_text(encoding="utf-8"), tmp_path)[0] == []

    def test_the_literal_outside_an_assert_is_acquitted(self, tmp_path):
        """Building a fixture with the string is not pinning it."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    written = tmp / "drive_tracker.json"\n    assert written.exists()\n',
        )
        assert checker.scan(path.read_text(encoding="utf-8"), tmp_path)[0] == []

    def test_only_the_constant_category_is_judged_for_a_pinned_value(self, tmp_path):
        """A (shared) or (stdlib) line makes no promise about a VALUE."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    assert p.name == "drive_tracker.json"\n',
            declared="# seedgo: no-test-needed(stdlib) — TRACKER_FILENAME's handling by pathlib\n",
        )
        assert checker.scan(path.read_text(encoding="utf-8"), tmp_path)[0] == []


class TestAnAbsentNameIsSearchedInTheSourceText:
    """86 live symbols were convicted before the search moved off the AST's names."""

    @pytest.mark.parametrize(
        "product",
        [
            'VALUE = os.environ.get("AIPASS_CALLER_CWD")\n',
            "class Config:\n    backup_mode: str = 'snapshot'\n",
            'ROOT = Path("handlers") / "tests_lane"\n',
        ],
    )
    def test_a_name_the_ast_cannot_see_still_counts_as_existing(self, tmp_path, product):
        """An env-var string, an annotated field and a path segment are all real uses."""
        for name in ("AIPASS_CALLER_CWD", "backup_mode", "tests_lane"):
            if name not in product:
                continue
            path = _branch(
                tmp_path,
                product,
                "def test_it():\n    assert run() == 1\n",
                declared=f"# seedgo: no-test-needed(constant) — the {name} value\n",
            )
            assert checker.scan(path.read_text(encoding="utf-8"), tmp_path)[0] == []

    def test_a_covered_elsewhere_reference_is_not_a_symbol(self, tmp_path):
        """'covered by tests/test_bypass.py' is the declaration working, not failing."""
        path = _branch(
            tmp_path,
            "def is_bypassed(path):\n    return False\n",
            "def test_it():\n    assert run() == 1\n",
            declared="# seedgo: no-test-needed(shared) — is_bypassed's rules; tests/test_bypass.py\n",
        )
        assert checker.scan(path.read_text(encoding="utf-8"), tmp_path)[0] == []

    def test_a_branch_that_cannot_be_resolved_scores_no_absence(self, tmp_path):
        """With no apps/ to read, "does this exist" has no answer and none is invented."""
        path = tmp_path / "test_loose.py"
        path.write_text(f'"""Tests."""\n{DECLARES}\ndef test_it():\n    assert run()\n', encoding="utf-8")
        assert checker.scan(path.read_text(encoding="utf-8"), None) == ([], 0)


class TestWhatIsCountedAndNotScored:
    """Each is a legitimate declaration a rule cannot tell from a broken one."""

    def test_a_prose_only_line_is_counted(self, tmp_path):
        """'mock call arguments and assertion shapes' names no symbol, and may not need to."""
        path = _branch(
            tmp_path,
            "VALUE = 1\n",
            "def test_it():\n    assert run()\n",
            declared="# seedgo: no-test-needed(generated) — mock call arguments\n",
        )
        findings, reported = checker.scan(path.read_text(encoding="utf-8"), tmp_path)
        assert findings == []
        assert reported == 1

    def test_a_dotted_stdlib_name_is_counted(self, tmp_path):
        """A test's incidental Path.resolve() is indistinguishable from testing it."""
        path = _branch(
            tmp_path,
            "VALUE = 1\n",
            "def test_it():\n    assert p.resolve().name\n",
            declared="# seedgo: no-test-needed(stdlib) — Path.resolve behaviour\n",
        )
        findings, reported = checker.scan(path.read_text(encoding="utf-8"), tmp_path)
        assert findings == []
        assert reported == 1


class TestWhatIsNotJudged:
    """A file with nothing declared makes no promise to break."""

    def test_a_file_with_no_declared_pass_yields_nothing(self):
        """file_top owns the missing declaration; this rule owns a broken one."""
        assert checker.scan("def test_it():\n    assert run()\n", None) == ([], 0)

    def test_an_unparseable_file_yields_nothing(self):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert checker.scan(f"{DECLARES}def test_it(:\n", None) == ([], 0)

    def test_declarations_reads_the_line_and_the_category(self):
        """The two halves every verdict is built from."""
        found = checker.declarations(f"x = 1\n{DECLARES}")
        assert found == [(2, "constant", "TRACKER_FILENAME's string")]


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    assert p.name == "drive_tracker.json"\n',
        )
        assert checker.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = checker.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_a_clean_file_reads_plainly(self, tmp_path):
        """No count to report, so no parenthetical to read past."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            "def test_it():\n    assert TRACKER_FILENAME in message\n",
        )
        message = checker.check_module(str(path))["checks"][0]["message"]
        assert message == "Every declared pass here holds"

    def test_the_message_names_the_symbol_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    assert p.name == "drive_tracker.json"\n',
        )
        message = checker.check_module(str(path))["checks"][0]["message"]
        assert "declares TRACKER_FILENAME needs no test" in message
        assert checker.CURE_PINNED in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one declaration and '(+1 more)'."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\nFOLDER_MIME = "application/folder"\n',
            'def test_it():\n    assert a == "drive_tracker.json"\n    assert b == "application/folder"\n',
            declared="# seedgo: no-test-needed(constant) — TRACKER_FILENAME and FOLDER_MIME\n",
        )
        checks = checker.check_module(str(path))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(checker.CURE_PINNED) == 2

    def test_the_command_prints_the_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    assert p.name == "drive_tracker.json"\n',
        )

        checklist.handle_command("checklist", [str(path)])

        assert "[FAIL] — declared_pass_contradiction" in capsys.readouterr().out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Only a test file carries a declared pass."""
        assert checker.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A broken promise belongs on the file that made it."""
        assert checker.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "declared_pass_contradiction", "pattern": "*"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _branch(
            tmp_path,
            'TRACKER_FILENAME = "drive_tracker.json"\n',
            'def test_it():\n    assert p.name == "drive_tracker.json"\n',
        )
        assert checker.check_module(str(path), bypass_rules=rules)["score"] == 100
