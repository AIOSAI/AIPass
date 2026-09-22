# =================== META ====================
# Name: test_file_top_check.py
# Description: file_top_check — test template v1 items 5, 6 and 7, the top of a test file
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""Tests for apps/handlers/aipass_standards/file_top_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.get_docstring returns the module docstring
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of FIX; every sub-rule message is asserted whole

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import file_top_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The fleet's gold test file for these items, resolved from this file's own
#: location so the test reads the real thing on any host.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: A top that satisfies all three items, built once and cut apart per test.
HEADER = (
    "# =================== META ====================\n"
    "# Name: test_thing.py\n"
    "# Description: Tests for the thing\n"
    "# Version: 1.0.0\n"
    "# Created: 2026-09-22\n"
    "# Modified: 2026-09-22\n"
    "# =============================================\n"
)
DOCSTRING = '\n"""Tests for apps/modules/thing.py and the handlers it drives."""\n'
DECLARED_PASS = (
    "\n# The declared pass — what is NOT tested here, and what covers it instead:\n"
    "# seedgo: no-test-needed(stdlib) — that json.loads parses json\n"
)
BODY = "\nimport pytest\n"


def _write(tmp_path, body, name="test_thing.py"):
    """A test file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheWholeTopInOrderPasses:
    def test_header_docstring_declared_pass_is_clean(self):
        assert file_top_check.scan(HEADER + DOCSTRING + DECLARED_PASS + BODY) == []

    def test_the_declared_pass_may_hold_no_markers(self):
        """A file with nothing to declare still says so — the block must exist, not be full."""
        empty = "\n# The declared pass — what is NOT tested here, and what covers it instead:\n"

        assert file_top_check.scan(HEADER + DOCSTRING + empty + BODY) == []


class TestItemFiveTheHeaderComesFirst:
    """367 of 579 fleet test files open with the block; 212 do not."""

    def test_a_file_that_opens_with_code_is_convicted(self):
        findings = file_top_check.scan("import pytest\n")

        assert findings[0] == "item 5 META header: the file opens with code — the header block comes first"

    def test_a_file_that_opens_with_its_docstring_is_convicted(self):
        """105 fleet-wide. The header is present, just not first — order is half the rule."""
        source = DOCSTRING.lstrip("\n") + "\n" + HEADER + DECLARED_PASS + BODY

        findings = file_top_check.scan(source)

        assert findings[0] == "item 5 META header: the file opens with a docstring — the header block comes first"

    def test_the_banner_word_must_be_the_one_the_template_names(self):
        """345 fleet files spell it AIPass and 72 spell it AIPASS; the template says META."""
        source = HEADER.replace("META", "AIPass", 1) + DOCSTRING + DECLARED_PASS + BODY

        assert file_top_check.scan(source) == ["item 5 META header: the banner word is AIPass, not META"]

    def test_a_missing_field_is_named(self):
        source = HEADER.replace("# Modified: 2026-09-22\n", "") + DOCSTRING + DECLARED_PASS + BODY

        assert file_top_check.scan(source) == ["item 5 META header: missing Modified"]

    def test_several_missing_fields_are_named_together(self):
        """66 files fleet-wide are short of three at once — one row, not three."""
        thin = (
            "# =================== META ====================\n"
            "# Name: test_thing.py\n"
            "# Version: 1.0.0\n"
            "# =============================================\n"
        )

        assert file_top_check.scan(thin + DOCSTRING + DECLARED_PASS + BODY) == [
            "item 5 META header: missing Description, Created, Modified"
        ]


class TestItemSixOneLineNamingTheSubject:
    """223 of 579 carry a one-line docstring; 562 carry one at all."""

    def test_a_missing_docstring_is_convicted(self):
        findings = file_top_check.scan(HEADER + "\nimport pytest\n")

        assert "item 6 subject docstring: missing — one line naming the module this file tests" in findings

    def test_a_multi_line_docstring_is_convicted_with_its_count(self):
        long_doc = '\n"""Tests for apps/modules/thing.py.\n\nAnd a second paragraph nobody reads.\n"""\n'

        findings = file_top_check.scan(HEADER + long_doc + DECLARED_PASS + BODY)

        assert findings == ["item 6 subject docstring: 3 lines, not 1 — one line naming the module this file tests"]

    def test_a_one_line_docstring_naming_no_path_is_convicted(self):
        """164 fleet-wide. "Unit tests for the widget" does not say which file."""
        vague = '\n"""Unit tests for the dispatch monitor."""\n'

        findings = file_top_check.scan(HEADER + vague + DECLARED_PASS + BODY)

        assert findings == ["item 6 subject docstring: names no path — say which module it tests, as a path"]


class TestItemSevenTheDeclaredPass:
    """7 of 579 fleet test files carry one — the item with no habit behind it."""

    def test_a_missing_block_is_convicted(self):
        findings = file_top_check.scan(HEADER + DOCSTRING + BODY)

        assert findings == ["item 7 declared pass: missing — what is NOT tested here, and what covers it"]

    def test_a_comment_that_is_not_a_marker_is_named_by_line(self):
        """The block is a roster, not a scratchpad: a stray note hides a missing decision."""
        stray = (
            "\n# The declared pass — what is NOT tested here, and what covers it instead:\n"
            "# a note to self, not a marker\n"
        )

        findings = file_top_check.scan(HEADER + DOCSTRING + stray + BODY)

        assert findings == ["item 7 declared pass: line 12 is not a seedgo: no-test-needed(...) marker"]

    def test_a_block_above_the_docstring_is_convicted(self):
        source = HEADER + DECLARED_PASS + DOCSTRING + BODY

        findings = file_top_check.scan(source)

        assert findings[0] == (
            "item 7 declared pass: the block is above the docstring — header, docstring, declared pass"
        )


class TestEverySubRuleReportsItself:
    """The dispatch's ask: an author must see which of the three is missing."""

    def test_all_three_appear_together(self):
        findings = file_top_check.scan("import pytest\n")

        assert findings == [
            "item 5 META header: the file opens with code — the header block comes first",
            "item 6 subject docstring: missing — one line naming the module this file tests",
            "item 7 declared pass: missing — what is NOT tested here, and what covers it",
        ]

    def test_all_three_survive_into_one_check_message(self, tmp_path):
        """checklist._format_failure prints the FIRST failed check and counts the rest.

        Three checks would show one sub-rule and hide two, so the three lines
        live in one message instead.
        """
        path = _write(tmp_path, "import pytest\n")

        message = file_top_check.check_module(str(path))["checks"][0]["message"]

        assert message.splitlines() == [
            "test_thing.py: item 5 META header: the file opens with code — the header block comes first",
            "test_thing.py: item 6 subject docstring: missing — one line naming the module this file tests",
            "test_thing.py: item 7 declared pass: missing — what is NOT tested here, and what covers it",
            file_top_check.FIX,
        ]


class TestConftestIsJudgedOnItemFiveOnly:
    """Decided from the template's text: a conftest has no subject and holds no tests."""

    def test_a_conftest_needs_no_docstring_or_declared_pass(self):
        assert file_top_check.scan(HEADER + BODY, conftest=True) == []

    def test_a_conftest_still_needs_the_header(self):
        findings = file_top_check.scan("import pytest\n", conftest=True)

        assert findings == ["item 5 META header: the file opens with code — the header block comes first"]

    def test_the_conftest_name_is_what_decides_it(self):
        assert file_top_check.is_conftest("tests/conftest.py") is True
        assert file_top_check.is_conftest("tests/test_conftest_thing.py") is False

    def test_a_clean_conftest_says_which_items_did_not_reach_it(self, tmp_path):
        path = _write(tmp_path, HEADER.replace("test_thing.py", "conftest.py") + BODY, name="conftest.py")

        message = file_top_check.check_module(str(path))["checks"][0]["message"]

        assert message == "The header block is first (items 6 and 7 do not reach a conftest)"


class TestCheckModuleIsThePerFileLane:
    def test_a_clean_file_scores_a_hundred(self, tmp_path):
        path = _write(tmp_path, HEADER + DOCSTRING + DECLARED_PASS + BODY)

        result = file_top_check.check_module(str(path))

        assert result["passed"] is True
        assert result["score"] == 100

    def test_a_convicted_file_scores_zero(self, tmp_path):
        path = _write(tmp_path, "import pytest\n")

        result = file_top_check.check_module(str(path))

        assert result["passed"] is False
        assert result["score"] == 0

    def test_a_missing_file_fails_rather_than_passes_quietly(self, tmp_path):
        result = file_top_check.check_module(str(tmp_path / "tests" / "gone.py"))

        assert result["passed"] is False
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_no_findings(self, tmp_path):
        """ruff already convicts the syntax error; naming a missing docstring would mislead."""
        path = _write(tmp_path, "def test_x(:\n")

        assert file_top_check.check_module(str(path))["passed"] is True

    def test_a_file_bypass_acquits_the_whole_file(self, tmp_path):
        path = _write(tmp_path, "import pytest\n")
        rules = [{"standard": "file_top", "file": str(path), "reason": "measured"}]

        result = file_top_check.check_module(str(path), bypass_rules=rules)

        assert result["passed"] is True
        assert "bypassed" in result["checks"][0]["message"]

    def test_the_rule_scopes_to_tests_and_scores_every_file(self):
        assert file_top_check.APPLIES_TO == "tests"
        assert file_top_check.AUDIT_SCOPE == "all_files"


class TestTheModelFileHoldsTheLine:
    """tests/test_readme_update.py is the fleet's gold test file for these items."""

    def test_the_model_file_passes(self):
        assert file_top_check.check_module(str(MODEL))["score"] == 100

    def test_the_model_file_with_its_docstring_lifted_above_the_header_is_convicted(self, tmp_path):
        """Not a hand-written sample: the real file, its two top blocks swapped."""
        lines = MODEL.read_text(encoding="utf-8").splitlines(keepends=True)
        index = next(i for i, line in enumerate(lines) if line.startswith('"""Tests for'))
        swapped = "".join([lines[index], "\n"] + lines[:index] + lines[index + 1 :])

        result = file_top_check.check_module(str(_write(tmp_path, swapped, name="test_readme_update.py")))

        assert result["score"] == 0
        assert "the file opens with a docstring" in result["checks"][0]["message"]

    def test_the_model_file_with_its_declared_pass_removed_is_convicted(self, tmp_path):
        source = MODEL.read_text(encoding="utf-8")
        stripped = "".join(
            line
            for line in source.splitlines(keepends=True)
            if "declared pass" not in line and "no-test-needed" not in line
        )

        result = file_top_check.check_module(str(_write(tmp_path, stripped, name="test_readme_update.py")))

        assert result["score"] == 0
        assert "item 7 declared pass: missing" in result["checks"][0]["message"]


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_a_bare_top(self, tmp_path, capsys):
        path = _write(tmp_path, "import pytest\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — file_top" in out

    def test_the_command_stays_quiet_on_a_clean_top(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        path = _write(tmp_path, HEADER + DOCSTRING + DECLARED_PASS + BODY)

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ file_top" in out
        assert "[FAIL] — file_top" not in out
