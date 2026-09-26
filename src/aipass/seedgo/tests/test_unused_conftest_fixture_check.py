# =================== META ====================
# Name: test_unused_conftest_fixture_check.py
# Description: unused_conftest_fixture_check — crack class G, a shared fixture nothing requests
# Version: 1.0.2
# Created: 2026-09-22
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/unused_conftest_fixture_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURE; the line and the name are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import unused_conftest_fixture_check

#: This branch, whose own conftest is the rule's live subject.
SELF = Path(__file__).resolve().parents[1]

#: A conftest the whole file reuses: one fixture, spelled the ordinary way.
ONE_FIXTURE = "import pytest\n\n\n@pytest.fixture\ndef temp_dir():\n    return 1\n"


def _branch(tmp_path, conftest=ONE_FIXTURE, **tests):
    """A branch root with a tests/ tree: conftest plus whatever test files are named."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "conftest.py").write_text(conftest, encoding="utf-8")
    for name, body in tests.items():
        (tests_dir / f"{name}.py").write_text(body, encoding="utf-8")
    return tmp_path


def _names(findings):
    """Just the fixture names, for the assertions that do not care where."""
    return [name for _, _, name in findings]


class TestTheModelBranchPasses:
    """seedgo's own tests/ tree is the floor: if it fails, the rule is wrong."""

    def test_this_branch_requests_every_fixture_it_shares(self):
        """Dogfood — seedgo cannot convict the fleet of what it does itself."""
        assert unused_conftest_fixture_check.scan(SELF) == []

    def test_this_branch_scores_100_through_check_branch(self):
        """And the same answer arrives through the pack's entry point."""
        assert unused_conftest_fixture_check.check_branch(str(SELF))["score"] == 100


class TestThePlantedSpecimen:
    """backup/tests/conftest.py fixtures `temp_dir`, `sample_data` and `mock_logger`, by name."""

    def test_a_fixture_no_test_requests_is_convicted(self, tmp_path):
        """Defined, shared, and reached by nothing."""
        root = _branch(tmp_path, test_a="def test_it():\n    assert True\n")
        assert unused_conftest_fixture_check.scan(root) == [(root / "tests" / "conftest.py", 5, "temp_dir")]

    def test_three_unrequested_fixtures_are_all_named(self, tmp_path):
        """@backup's three arrive as three findings, not one and a count."""
        conftest = (
            "import pytest\n\n\n@pytest.fixture\ndef temp_dir():\n    return 1\n\n\n"
            "@pytest.fixture\ndef sample_data():\n    return 2\n\n\n"
            "@pytest.fixture\ndef mock_logger():\n    return 3\n"
        )
        root = _branch(tmp_path, conftest=conftest, test_a="def test_it():\n    assert True\n")
        assert _names(unused_conftest_fixture_check.scan(root)) == ["temp_dir", "sample_data", "mock_logger"]

    def test_the_findings_carry_the_line_the_fixture_sits_on(self, tmp_path):
        """A name without a line makes the owner grep for their own file."""
        root = _branch(tmp_path, test_a="def test_it():\n    assert True\n")
        assert unused_conftest_fixture_check.scan(root)[0][1] == 5


class TestEveryWayAFixtureCanBeRequested:
    """Miss one and the rule convicts a fixture that is in daily use."""

    def test_a_parameter_name_is_a_request(self, tmp_path):
        """The ordinary way: a test takes it as an argument."""
        root = _branch(tmp_path, test_a="def test_it(temp_dir):\n    assert temp_dir\n")
        assert unused_conftest_fixture_check.scan(root) == []

    def test_another_fixture_requesting_it_is_a_request(self, tmp_path):
        """A fixture nothing requests DIRECTLY may still be a chain's root."""
        conftest = ONE_FIXTURE + "\n\n@pytest.fixture\ndef workspace(temp_dir):\n    return temp_dir\n"
        root = _branch(tmp_path, conftest=conftest, test_a="def test_it(workspace):\n    assert workspace\n")
        assert unused_conftest_fixture_check.scan(root) == []

    def test_usefixtures_names_it_with_a_string(self, tmp_path):
        """A fixture used only for its side effect is never a parameter."""
        body = "import pytest\n\n\n@pytest.mark.usefixtures('temp_dir')\ndef test_it():\n    assert True\n"
        assert unused_conftest_fixture_check.scan(_branch(tmp_path, test_a=body)) == []

    def test_getfixturevalue_names_it_with_a_string_too(self, tmp_path):
        """The dynamic spelling, requested at runtime from the request object."""
        body = "def test_it(request):\n    assert request.getfixturevalue('temp_dir')\n"
        assert unused_conftest_fixture_check.scan(_branch(tmp_path, test_a=body)) == []

    def test_autouse_needs_no_request_at_all(self, tmp_path):
        """autouse=True means "nothing needs to ask" — convicting it is a false hit."""
        conftest = "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef seal():\n    return 1\n"
        root = _branch(tmp_path, conftest=conftest, test_a="def test_it():\n    assert True\n")
        assert unused_conftest_fixture_check.scan(root) == []


class TestWhatIsNotJudged:
    """The rule is about the SHARED file, and only about fixtures."""

    def test_a_fixture_in_a_test_file_is_not_this_rules_business(self, tmp_path):
        """A local fixture is its own file's business; conftest is the shared one."""
        body = "import pytest\n\n\n@pytest.fixture\ndef local_only():\n    return 1\n"
        assert unused_conftest_fixture_check.scan(_branch(tmp_path, conftest="", test_a=body)) == []

    def test_a_plain_helper_in_conftest_is_not_a_fixture(self, tmp_path):
        """No decorator, no fixture, no verdict."""
        root = _branch(tmp_path, conftest="def build_tree(path):\n    return path\n")
        assert unused_conftest_fixture_check.scan(root) == []

    def test_a_branch_with_no_tests_directory_yields_nothing(self, tmp_path):
        """Nothing to read is not a violation."""
        assert unused_conftest_fixture_check.scan(tmp_path) == []

    def test_an_unparseable_conftest_yields_nothing(self, tmp_path):
        """ruff already convicts the syntax error; a second verdict misdirects."""
        assert unused_conftest_fixture_check.scan(_branch(tmp_path, conftest="def broken(:\n")) == []


class TestTheEntryPoint:
    """check_branch's own paths, which scan never sees."""

    def test_a_convicted_branch_scores_zero(self, tmp_path):
        """No partial credit: the lane is pass/fail per branch."""
        root = _branch(tmp_path, test_a="def test_it():\n    assert True\n")
        assert unused_conftest_fixture_check.check_branch(str(root))["score"] == 0

    def test_a_clean_branch_reads_plainly(self, tmp_path):
        """Nothing to report, so nothing to read past."""
        root = _branch(tmp_path, test_a="def test_it(temp_dir):\n    assert temp_dir\n")
        message = unused_conftest_fixture_check.check_branch(str(root))["checks"][0]["message"]
        assert message == "Every conftest fixture here is requested by something"

    def test_the_message_names_the_file_the_line_and_the_cure(self, tmp_path):
        """A finding that does not say what to do is a chore, not a cure."""
        root = _branch(tmp_path, test_a="def test_it():\n    assert True\n")
        message = unused_conftest_fixture_check.check_branch(str(root))["checks"][0]["message"]
        assert "tests/conftest.py:5 temp_dir is defined and never requested" in message
        assert unused_conftest_fixture_check.CURE in message

    def test_every_hit_rides_on_one_check(self, tmp_path):
        """checklist._format_failure prints the FIRST failed check and hides the rest."""
        conftest = ONE_FIXTURE + "\n\n@pytest.fixture\ndef sample_data():\n    return 2\n"
        root = _branch(tmp_path, conftest=conftest, test_a="def test_it():\n    assert True\n")
        checks = unused_conftest_fixture_check.check_branch(str(root))["checks"]
        assert len(checks) == 1
        assert checks[0]["message"].count(unused_conftest_fixture_check.CURE) == 2


class TestItDeclaresItsScope:
    """The two constants the audit engine consults before it runs this rule."""

    def test_it_applies_to_tests_only(self):
        """conftest.py is a test file; production code has no fixtures."""
        assert unused_conftest_fixture_check.APPLIES_TO == "tests"

    def test_it_reports_per_branch_not_per_file(self):
        """ "Is this requested" is a fact about the whole tests/ tree, not one file."""
        assert unused_conftest_fixture_check.AUDIT_SCOPE == "branch_level"


class TestTheBypass:
    """Every checker in the pack answers to .seedgo/bypass.json."""

    @pytest.mark.parametrize("rules", [[{"standard": "unused_conftest_fixture"}]])
    def test_a_bypassed_branch_passes(self, tmp_path, rules):
        """A deliberate exception is not a violation."""
        root = _branch(tmp_path, test_a="def test_it():\n    assert True\n")
        assert (
            unused_conftest_fixture_check.check_branch(
                str(root), bypass_rules=[{**rule, "file": str(tmp_path)} for rule in rules]
            )["score"]
            == 100
        )
