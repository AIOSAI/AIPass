# =================== META ====================
# Name: test_flag_never_passed_check.py
# Description: flag_never_passed_check — crack class P, a parsed flag no test passes
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/flag_never_passed_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the flag and its parse line are asserted

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import flag_never_passed_check

#: A parser that reads one flag out of args, which is the whole product side.
PARSER = "def handle_command(command, args):\n    loud = '--loud' in args\n    return loud\n"


def _branch(tmp_path, apps=PARSER, tests="", apps_name="thing.py", tests_name="test_thing.py"):
    """A branch root with an apps/ parser and a tests/ tree, which is the rule's unit."""
    modules = tmp_path / "apps" / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    (modules / apps_name).write_text(apps, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / tests_name).write_text(tests, encoding="utf-8")
    return tmp_path


def _flags(tmp_path, tests):
    """Just the convicted flags for a branch whose tests are this source."""
    return [flag for _path, _line, flag in flag_never_passed_check.scan(_branch(tmp_path, tests=tests))[0]]


def _shadowed(tmp_path, tests):
    """The flags counted as riding only in a --help argv."""
    return flag_never_passed_check.scan(_branch(tmp_path, tests=tests))[1]


class TestThePlantedSpecimen:
    """The shape the reviewers found, at @backup's share.py:129."""

    def test_a_parsed_flag_no_test_passes_is_convicted(self, tmp_path):
        """public = False survived all 21 share tests. Nothing handed it over."""
        assert _flags(tmp_path, "def test_it():\n    handle_command('thing', [])\n") == ["--loud"]

    def test_the_finding_names_the_parse_site(self, tmp_path):
        """A finding that does not say where the flag is read is a chore."""
        findings, _counted = flag_never_passed_check.scan(_branch(tmp_path))
        path, line, flag = findings[0]
        assert (path.name, line, flag) == ("thing.py", 2, "--loud")


class TestWhatCountsAsPassingIt:
    """The literal must reach an ARGUMENT of some call."""

    def test_a_list_handed_to_the_parser_acquits(self, tmp_path):
        """The direct form."""
        assert _flags(tmp_path, "def test_it():\n    handle_command('thing', ['--loud'])\n") == []

    def test_a_sub_handler_acquits(self, tmp_path):
        """@spawn tests handle_create([target, '--dry-run']) and never names handle_command."""
        assert _flags(tmp_path, "def test_it():\n    handle_thing(['--loud'])\n") == []

    def test_an_argv_set_before_main_acquits(self, tmp_path):
        """monkeypatch.setattr(sys, 'argv', [...]) is an argument like any other."""
        source = "def test_it(monkeypatch):\n    monkeypatch.setattr(sys, 'argv', ['thing', '--loud'])\n    main()\n"
        assert _flags(tmp_path, source) == []

    def test_a_name_bound_to_an_argv_acquits(self, tmp_path):
        """The list is built first and handed over second."""
        source = "def test_it():\n    argv = ['--loud']\n    handle_command('thing', argv)\n"
        assert _flags(tmp_path, source) == []

    def test_a_parametrize_argvalue_acquits(self, tmp_path):
        """The parameter name is bound to the argvalues behind it."""
        source = (
            "@pytest.mark.parametrize('args', [['--loud'], []])\n"
            "def test_it(args):\n"
            "    handle_command('thing', args)\n"
        )
        assert _flags(tmp_path, source) == []

    def test_a_tuple_that_is_only_iterated_does_not_acquit(self, tmp_path):
        """@backup's help sweep names --public and never hands it to the parser."""
        source = "def test_it():\n    for flag in ('--loud', '--quiet'):\n        assert flag in printed\n"
        assert _flags(tmp_path, source) == ["--loud"]

    def test_a_help_substring_does_not_acquit(self, tmp_path):
        """test_share.py:107 asserts a usage line, which is not a whole-string flag."""
        source = "def test_it():\n    assert 'drone @thing <path> [--loud]' in printed\n"
        assert _flags(tmp_path, source) == ["--loud"]


class TestAHelpArgvExercisesNothingElse:
    """The product returns from print_help() before it reads any other flag."""

    HELP_ROW = "def test_it():\n    handle_command('thing', ['x', '--loud', '--help'])\n"

    def test_a_flag_riding_in_a_help_argv_is_still_convicted(self, tmp_path):
        """Without this, @backup's sweep acquitted three of the five named flags."""
        assert _flags(tmp_path, self.HELP_ROW) == ["--loud"]

    def test_that_flag_is_counted_as_help_shadowed(self, tmp_path):
        """It is named in the branch; the rule says what it saw and why it stands."""
        assert _shadowed(tmp_path, self.HELP_ROW) == {"--loud"}

    def test_help_itself_is_exercised_by_a_help_argv(self, tmp_path):
        """--help IS the flag that row pins."""
        apps = "def handle_command(command, args):\n    if '--help' in args:\n        return True\n"
        branch = _branch(tmp_path, apps=apps, tests=self.HELP_ROW)
        assert flag_never_passed_check.scan(branch)[0] == []


class TestWhatIsNotEvenDeclared:
    """The declared set starts at handle_command, not at every string in apps/."""

    def test_a_flag_parsed_only_in_main_is_never_convicted(self, tmp_path):
        """The judgement the dispatch asked to have named. A different surface."""
        apps = "def handle_command(command, args):\n    return True\nif __name__ == '__main__':\n    q = '--quiet' in sys.argv\n"
        assert flag_never_passed_check.scan(_branch(tmp_path, apps=apps))[0] == []

    def test_a_flag_parsed_in_a_helper_the_parser_calls_is_declared(self, tmp_path):
        """A parser is routinely one delegation deep."""
        apps = "def _parse(args):\n    return '--loud' in args\ndef handle_command(command, args):\n    return _parse(args)\n"
        findings = flag_never_passed_check.scan(_branch(tmp_path, apps=apps))[0]
        assert [flag for _p, _l, flag in findings] == ["--loud"]

    def test_a_module_with_no_handle_command_declares_nothing(self, tmp_path):
        """Only a parser's flags are the router's contract."""
        apps = "def helper(args):\n    return '--loud' in args\n"
        assert flag_never_passed_check.scan(_branch(tmp_path, apps=apps))[0] == []


class TestTheEntryPoint:
    """check_branch's own paths, which scan never sees."""

    def test_a_convicted_branch_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per branch."""
        assert flag_never_passed_check.check_branch(str(_branch(tmp_path)))["score"] == 0

    def test_a_branch_with_no_apps_scores_100(self, tmp_path):
        """Nothing parses a flag there, so nothing may be charged."""
        result = flag_never_passed_check.check_branch(str(tmp_path))
        assert result["score"] == 100
        assert "No apps/" in result["checks"][0]["message"]

    def test_a_branch_whose_only_flag_is_help_reads_plainly(self, tmp_path):
        """--help IS pinned by a help argv, so there is no count to read past."""
        apps = "def handle_command(command, args):\n    if '--help' in args:\n        return True\n"
        tests = "def test_it():\n    handle_command('thing', ['--help'])\n"
        message = flag_never_passed_check.check_branch(str(_branch(tmp_path, apps=apps, tests=tests)))["checks"][0]
        assert message["message"] == "Every flag this branch parses is passed to it by a test"

    def test_the_message_names_the_flag_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        message = flag_never_passed_check.check_branch(str(_branch(tmp_path)))["checks"][0]["message"]
        assert "--loud" in message
        assert flag_never_passed_check.CURE in message

    def test_an_unparseable_module_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert (
            flag_never_passed_check.check_branch(str(_branch(tmp_path, apps="def handle_command(:\n")))["score"] == 100
        )


class TestEveryHitRidesOnOneCheck:
    """checklist._format_failure prints the FIRST failed check and hides the rest."""

    def test_two_flags_arrive_on_a_single_check(self, tmp_path):
        """Two checks would show one flag and '(+1 more)'."""
        apps = "def handle_command(command, args):\n    a = '--loud' in args\n    b = '--quiet' in args\n    return a or b\n"
        checks = flag_never_passed_check.check_branch(str(_branch(tmp_path, apps=apps)))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(flag_never_passed_check.CURE) == 2


class TestItDeclaresItsScope:
    """The two constants both lanes consult before they run it."""

    def test_it_applies_to_tests_only(self):
        """The question is whether a TEST passes the flag."""
        assert flag_never_passed_check.APPLIES_TO == "tests"

    def test_it_reports_per_branch(self):
        """apps/ against the whole tests/ tree, so no single file owns the verdict."""
        assert flag_never_passed_check.AUDIT_SCOPE == "branch_level"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "flag_never_passed", "pattern": "*"}]])
    def test_a_bypassed_branch_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        assert flag_never_passed_check.check_branch(str(_branch(tmp_path)), bypass_rules=rules)["score"] == 100
