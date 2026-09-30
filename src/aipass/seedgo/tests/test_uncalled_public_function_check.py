# =================== META ====================
# Name: test_uncalled_public_function_check.py
# Description: uncalled_public_function_check — crack class O, a subject's untested export
# Version: 1.0.2
# Created: 2026-09-22
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/uncalled_public_function_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the function, line and shape are asserted

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import uncalled_public_function_check

#: A subject module with one public export and one private helper.
SUBJECT = "def discover():\n    return []\ndef _hidden():\n    return 1\n"

#: The docstring line that makes a test file declare what it tests — template item 6.
DECLARES = '"""Tests for apps/modules/thing.py."""\n'


def _branch(tmp_path, subject=SUBJECT, tests=DECLARES, extra=None):
    """A branch root with a subject module under apps/ and a tests/ tree."""
    modules = tmp_path / "apps" / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / "thing.py").write_text(subject, encoding="utf-8")
    if extra:
        for name, source in extra.items():
            (modules / name).write_text(source, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_thing.py").write_text(tests, encoding="utf-8")
    return tmp_path


def _names(tmp_path, tests, subject=SUBJECT, extra=None):
    """Just the convicted function names."""
    findings, _acquitted = uncalled_public_function_check.scan(_branch(tmp_path, subject, tests, extra))
    return [name for _path, _line, name, _shape in findings]


def _shapes(tmp_path, tests, subject=SUBJECT):
    """Just the shapes, in line order — O1 or O2."""
    findings, _acquitted = uncalled_public_function_check.scan(_branch(tmp_path, subject, tests))
    return [shape for _path, _line, _name, shape in findings]


class TestThePlantedSpecimens:
    """One specimen per shape, both taken from @backup."""

    def test_o1_a_function_named_only_as_a_patch_target(self, tmp_path):
        """apps/backup.py:125 discover_modules — four sites replace it, none runs it."""
        tests = (
            DECLARES + "def test_it():\n    with patch.object(entry, 'discover', return_value=[]):\n        main()\n"
        )
        assert _names(tmp_path, tests) == ["discover"]
        assert _shapes(tmp_path, tests) == [uncalled_public_function_check.REPLACED]

    def test_o2_a_function_no_test_names_at_all(self, tmp_path):
        """result.py:50 new_result — defined once, referenced nowhere."""
        assert _names(tmp_path, DECLARES) == ["discover"]
        assert _shapes(tmp_path, DECLARES) == [uncalled_public_function_check.UNREACHED]

    def test_the_finding_names_the_function_and_its_line(self, tmp_path):
        """A finding that does not say where to look is a chore, not a cure."""
        findings, _acquitted = uncalled_public_function_check.scan(_branch(tmp_path))
        path, line, name, _shape = findings[0]
        assert (path.name, line, name) == ("thing.py", 1, "discover")


class TestWhatCountsAsCalled:
    """Named in a Call, or an attribute access that is then called."""

    def test_a_direct_call_acquits(self, tmp_path):
        """The plain case."""
        assert _names(tmp_path, DECLARES + "def test_it():\n    discover()\n") == []

    def test_an_attribute_call_acquits(self, tmp_path):
        """test_caller_path.py:86 calls share_mod.run_share(file_arg) for real."""
        assert _names(tmp_path, DECLARES + "def test_it():\n    thing_mod.discover()\n") == []

    def test_reaching_it_through_the_product_acquits(self, tmp_path):
        """route_command and every print_introspection are acquitted this way."""
        subject = "def run():\n    return discover()\ndef discover():\n    return []\n"
        assert _names(tmp_path, DECLARES + "def test_it():\n    run()\n", subject=subject) == []

    def test_the_reachability_guard_is_transitive(self, tmp_path):
        """A fixed point, not one hop: main() -> route_command() -> print_introspection()."""
        subject = (
            "def run():\n    return middle()\ndef middle():\n    return discover()\ndef discover():\n    return []\n"
        )
        assert _names(tmp_path, DECLARES + "def test_it():\n    run()\n", subject=subject) == []

    def test_a_patched_function_also_named_elsewhere_is_reported_not_scored(self, tmp_path):
        """Named ONLY as a patch target is the rule; named twice is not that."""
        tests = DECLARES + "def test_it():\n    patch.object(entry, 'discover')\n    assert discover.__doc__\n"
        assert _names(tmp_path, tests) == []


class TestTheSubjectLine:
    """No subject, no verdict — 492 of the fleet's 561 test files say nothing."""

    def test_a_file_with_no_subject_path_judges_nothing(self, tmp_path):
        """The rule cannot judge a file that never says what it tests."""
        assert _names(tmp_path, '"""Tests for the thing."""\n') == []

    def test_a_docstring_naming_two_modules_declares_both(self, tmp_path):
        """findall, not search: taking the first mis-attributes the second."""
        declares = '"""Tests for apps/modules/thing.py and apps/modules/other.py."""\n'
        extra = {"other.py": "def orphan():\n    return 1\n"}
        assert sorted(_names(tmp_path, declares, extra=extra)) == ["discover", "orphan"]

    def test_a_subject_path_that_does_not_exist_is_skipped(self, tmp_path):
        """A stale docstring path is file_top's finding, not a function verdict."""
        assert _names(tmp_path, '"""Tests for apps/modules/gone.py."""\n') == []

    def test_a_private_function_is_never_judged(self, tmp_path):
        """The subject of the rule is the module's exported surface."""
        assert "_hidden" not in _names(tmp_path, DECLARES)


class TestTheEntryPoint:
    """check_branch's own paths, which scan never sees."""

    def test_a_convicted_branch_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per branch."""
        assert uncalled_public_function_check.check_branch(str(_branch(tmp_path)))["score"] == 0

    def test_a_branch_with_no_tests_scores_100(self, tmp_path):
        """Nothing declares a subject, so nothing may be charged."""
        (tmp_path / "apps").mkdir()
        assert uncalled_public_function_check.check_branch(str(tmp_path))["score"] == 100

    def test_the_acquitted_count_rides_in_the_passing_message(self, tmp_path):
        """The rule's biggest judgement is reported, not hidden."""
        subject = "def run():\n    return discover()\ndef discover():\n    return []\n"
        branch = _branch(tmp_path, subject=subject, tests=DECLARES + "def test_it():\n    run()\n")
        message = uncalled_public_function_check.check_branch(str(branch))["checks"][0]["message"]
        assert "1 are reached only through the product" in message

    def test_the_message_names_the_shape_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        message = uncalled_public_function_check.check_branch(str(_branch(tmp_path)))["checks"][0]["message"]
        assert uncalled_public_function_check.UNREACHED in message
        assert uncalled_public_function_check.CURE in message

    def test_an_unparseable_subject_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert (
            uncalled_public_function_check.check_branch(str(_branch(tmp_path, subject="def discover(:\n")))["score"]
            == 100
        )


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    def test_two_functions_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one function and '(+1 more)'."""
        subject = "def discover():\n    return []\ndef collect():\n    return []\n"
        checks = uncalled_public_function_check.check_branch(str(_branch(tmp_path, subject=subject)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(uncalled_public_function_check.CURE) == 2


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """The question is whether a TEST calls the function."""
        assert uncalled_public_function_check.APPLIES_TO == "tests"

    def test_it_reports_per_branch(self):
        """Declared subjects against the whole tests/ tree."""
        assert uncalled_public_function_check.AUDIT_SCOPE == "branch_level"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "uncalled_public_function"}]])
    def test_a_bypassed_branch_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        assert (
            uncalled_public_function_check.check_branch(
                str(_branch(tmp_path)), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules]
            )["score"]
            == 100
        )
