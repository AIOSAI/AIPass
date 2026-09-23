# =================== META ====================
# Name: test_weak_oracle_check.py
# Description: weak_oracle_check — crack class D, a test whose whole oracle cannot fail
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/weak_oracle_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the form and the test name are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs, weak_oracle_check
from aipass.seedgo.apps.modules import checklist

#: The model file for the whole per-item series. It passes, and it is the
#: shape every planted specimen below is a mutation of.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: @backup's real -> None function, the one D6 instance the dispatch named.
TRAIL_IMPORT = "from aipass.backup.apps.handlers.audit import trail"


def _forms(source):
    """Just the scored forms, in line order."""
    return [form for _line, _name, form in weak_oracle_check.scan(source)[0]]


def _names(source):
    """Just the convicted test names, in line order."""
    return [name for _line, name, _form in weak_oracle_check.scan(source)[0]]


def _counted(source):
    """The soft forms reported with a count and charged to nobody."""
    return weak_oracle_check.scan(source)[1]


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
        """tests/test_readme_update.py convicts no test."""
        assert weak_oracle_check.scan(MODEL.read_text(encoding="utf-8"))[0] == []

    def test_the_model_file_scores_100_through_check_module(self):
        """And the same answer arrives through the pack's entry point."""
        assert weak_oracle_check.check_module(str(MODEL))["score"] == 100


class TestTheSixScoredForms:
    """One specimen per form, each a thing a test cannot satisfy by accident."""

    def test_d1_an_assert_on_a_constant(self):
        """assert True cannot fail. There is not one in the fleet."""
        source = "def test_it():\n    assert True\n"
        assert _forms(source) == [weak_oracle_check.D1]

    def test_d2_a_bare_names_truthiness(self):
        """A local's truthiness says nothing about what produced it."""
        source = "def test_it():\n    result = run()\n    assert result\n"
        assert _forms(source) == [weak_oracle_check.D2]

    def test_d3_is_not_none_alone(self):
        """test_module_isolation.py:48 — every object is not None."""
        source = "def test_it():\n    twin = run()\n    assert twin is not None\n"
        assert _forms(source) == [weak_oracle_check.D3]

    def test_d4_isinstance_alone(self):
        """The type, never the value. A stub of the right class satisfies it."""
        source = "def test_it():\n    assert isinstance(run(), Path)\n"
        assert _forms(source) == [weak_oracle_check.D4]

    def test_d5_assert_called_with_no_argument_check(self):
        """test_cli_routing.py:328 — spy.assert_called() with 11 params unpinned."""
        source = "def test_it():\n    run(spy)\n    spy.assert_called()\n"
        assert _forms(source) == [weak_oracle_check.D5]

    def test_d5_covers_assert_called_once_too(self):
        """Once is still no claim about what the call was given."""
        source = "def test_it():\n    run(spy)\n    spy.assert_called_once()\n"
        assert _forms(source) == [weak_oracle_check.D5]

    def test_d6_is_none_on_a_function_annotated_none(self):
        """A local -> None function cannot return anything else."""
        source = "def helper() -> None:\n    pass\ndef test_it():\n    assert helper() is None\n"
        assert _forms(source) == [weak_oracle_check.D6]

    def test_d6_resolves_a_function_through_its_module_alias(self):
        """test_error_resilience.py:372. Reading only `from x import f` found ZERO."""
        source = f"{TRAIL_IMPORT}\ndef test_it():\n    assert trail.log_operation('x', {{}}) is None\n"
        assert _forms(source) == [weak_oracle_check.D6]

    def test_the_convicted_test_is_named(self):
        """A finding that does not say which test is a chore, not a cure."""
        source = "def test_the_guard_refuses():\n    assert True\n"
        assert _names(source) == ["test_the_guard_refuses"]


class TestWhatIsStrongEnoughToAcquit:
    """One real assertion anywhere in the test acquits every weak form in it."""

    def test_a_predicate_calls_truthiness_is_the_claim(self):
        """Scoring this cost 1,356 false hits and failed the model file."""
        source = "def test_it():\n    assert is_ignored('app.log', spec)\n"
        assert _forms(source) == []

    def test_hasattr_is_a_real_question(self):
        """The model file's second assertion, and the reason it went red."""
        source = "def test_it():\n    assert hasattr(generator, 'update_readme_auto_sections')\n"
        assert _forms(source) == []

    def test_a_compare_against_a_value_acquits_the_isinstance_beside_it(self):
        """test_handlers_filesystem.py — the dispatch declined these in advance."""
        source = (
            "def test_it():\n"
            "    result = backup_root(str(tmp_path))\n"
            "    assert isinstance(result, Path)\n"
            "    assert result.name == '.backup'\n"
        )
        assert _forms(source) == []

    def test_pytest_raises_acquits_outright(self):
        """'It raised the right exception' is often the only oracle a refusal needs."""
        source = "def test_it():\n    with pytest.raises(ValueError):\n        run()\n    assert True\n"
        assert _forms(source) == []

    def test_a_test_with_no_oracle_at_all_is_not_scored(self):
        """An indirect assertion helper leaves no assert here; the rule does not guess."""
        source = "def test_it():\n    assert_report_is_sound(run())\n"
        assert _forms(source) == []

    def test_router_assert_is_not_charged_twice(self):
        """assert handle_command(...) is True is a Compare, which reads as strong."""
        source = "def test_it():\n    assert handle_command('x', []) is True\n"
        assert _forms(source) == []


class TestASoftCompanionDoesNotAcquit:
    """The one place the rule bites harder than it reads, so it is pinned."""

    def test_a_not_in_beside_is_not_none_still_convicts(self):
        """test_module_isolation.py:48, exactly as the dispatch asked for it."""
        source = (
            "def test_it():\n    twin = run()\n    assert twin is not None\n    assert 'drive' not in sys.modules\n"
        )
        assert _forms(source) == [weak_oracle_check.D3]

    def test_two_substring_checks_beside_is_not_none_still_convict(self):
        """test_ceiling_guard.py 153 and 162 — nothing pins a computed value."""
        source = (
            "def test_it():\n"
            "    breach = check_ceiling(files, ceiling)\n"
            "    assert breach is not None\n"
            "    text = '\\n'.join(breach.detail_lines())\n"
            "    assert 'max_backup_files' in text\n"
        )
        assert _forms(source) == [weak_oracle_check.D3]


class TestTheSoftFormsAreCountedNeverScored:
    """Each can legitimately be the right oracle and a rule cannot tell which."""

    @pytest.mark.parametrize(
        "oracle,form",
        [
            ("assert check_ceiling(files, ceiling) is None", weak_oracle_check.SOFT_NONE),
            ("assert len(rows) == 3", weak_oracle_check.SOFT_LEN),
            ("assert size >= 1024", weak_oracle_check.SOFT_BOUND),
            ("assert 'refused' in out", weak_oracle_check.SOFT_IN),
            ("assert load_config(p) == {}", weak_oracle_check.SOFT_EMPTY),
        ],
    )
    def test_a_soft_oracle_is_counted_and_not_scored(self, oracle, form):
        """test_ceiling_guard.py:107 is the first row: a real claim about a real return."""
        source = f"def test_it():\n    {oracle}\n"
        assert _forms(source) == []
        assert _counted(source) == [form]

    def test_the_passing_message_carries_the_count(self, tmp_path):
        """The number the owner asked for rides along, and nobody is charged."""
        path = _write(tmp_path, "def test_it():\n    assert 'refused' in out\n")
        result = weak_oracle_check.check_module(str(path))
        assert result["score"] == 100
        assert "1 soft oracles in 1 form are counted" in result["checks"][0]["message"]

    def test_a_file_with_no_soft_oracle_says_so_plainly(self, tmp_path):
        """No count to report, so no parenthetical to read past."""
        path = _write(tmp_path, "def test_it():\n    assert run() == 3\n")
        message = weak_oracle_check.check_module(str(path))["checks"][0]["message"]
        assert message == "Every test here asserts something that can fail"


class TestTheEntryPoint:
    """check_module's own paths, which scan never sees."""

    def test_a_convicted_file_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per file."""
        path = _write(tmp_path, "def test_it():\n    assert True\n")
        assert weak_oracle_check.check_module(str(path))["score"] == 0

    def test_a_missing_file_fails_by_name(self, tmp_path):
        """Not a crash, and not a silent pass."""
        result = weak_oracle_check.check_module(str(tmp_path / "gone.py"))
        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        path = _write(tmp_path, "def test_it(:\n")
        assert weak_oracle_check.check_module(str(path))["score"] == 100

    def test_the_message_names_the_test_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        path = _write(tmp_path, "def test_the_guard_refuses():\n    assert True\n")
        message = weak_oracle_check.check_module(str(path))["checks"][0]["message"]
        assert "test_the_guard_refuses" in message
        assert weak_oracle_check.CURE in message


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    @pytest.fixture(autouse=True)
    def _let_tmp_path_be_audited(self, monkeypatch):
        """tmp_path lives under a temp root the checklist skips by default."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_two_hits_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one test and '(+1 more)'."""
        path = _write(tmp_path, "def test_a():\n    assert True\ndef test_b():\n    assert True\n")
        checks = weak_oracle_check.check_module(str(path))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(weak_oracle_check.D1) == 2

    def test_the_command_prints_every_hit(self, tmp_path, capsys):
        """The message survives the formatter the hook actually calls."""
        path = _write(tmp_path, "def test_the_guard_refuses():\n    assert True\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — weak_oracle" in out
        assert "test_the_guard_refuses" in out


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """Production code has no def test_*; running it there is noise."""
        assert weak_oracle_check.APPLIES_TO == "tests"

    def test_it_reports_per_file(self):
        """A verdict about a test's oracle belongs on the file that holds it."""
        assert weak_oracle_check.AUDIT_SCOPE == "all_files"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "weak_oracle", "pattern": "*"}]])
    def test_a_bypassed_file_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        path = _write(tmp_path, "def test_it():\n    assert True\n")
        assert weak_oracle_check.check_module(str(path), bypass_rules=rules)["score"] == 100
