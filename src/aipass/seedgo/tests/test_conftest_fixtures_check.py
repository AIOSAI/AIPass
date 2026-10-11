# =================== META ====================
# Name: test_conftest_fixtures_check.py
# Description: conftest_fixtures_check — test template v1 item 20, the branch conftest
# Version: 1.0.1
# Created: 2026-09-22
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/conftest_fixtures_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of CURES; the sub-rule codes are asserted

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import conftest_fixtures_check, skip_dirs
from aipass.seedgo.apps.modules import checklist

#: The fleet's only conftest that passes item 20 today, resolved from this
#: file's own location so the test reads the real thing on any host.
MODEL = Path(__file__).resolve().parent / "conftest.py"

#: The import that makes a name a PRODUCT console. Without it the same fixture
#: text pins a console the product never prints to.
IMPORT = "from aipass.cli.apps.modules import display\n"

#: C1 as the template page spells it.
PIN = (
    "@pytest.fixture(autouse=True, scope='session')\n"
    "def pinned_console_width():\n"
    "    for console in (display.CONSOLE, display.err_console):\n"
    "        console.width = 200\n"
)

#: C2 as the template page spells it.
RESET = "@pytest.fixture(autouse=True)\ndef clean_command_state():\n    yield\n    display.reset_command_state()\n"


def _write(tmp_path, body, name="conftest.py"):
    """A file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _missing(source):
    """Just the sub-rule codes, in order."""
    return [rule[:2] for rule, _cure in conftest_fixtures_check.scan(source)]


class TestTheUnitIsTheConftest:
    """563 other files under tests/ are not this rule's business."""

    def test_a_conftest_with_both_fixtures_passes(self, tmp_path):
        path = _write(tmp_path, IMPORT + PIN + RESET)

        assert conftest_fixtures_check.check_module(str(path))["score"] == 100

    def test_a_test_file_is_never_judged_even_when_it_has_neither(self, tmp_path):
        """Item 16 puts these fixtures in one place; asking every file is noise."""
        path = _write(tmp_path, "def test_x():\n    assert True\n", name="test_thing.py")

        result = conftest_fixtures_check.check_module(str(path))

        assert result["score"] == 100
        assert "not this file's business" in result["checks"][0]["message"]

    def test_the_unit_predicate_is_the_filename(self, tmp_path):
        assert conftest_fixtures_check.is_the_unit(str(tmp_path / "conftest.py")) is True
        assert conftest_fixtures_check.is_the_unit(str(tmp_path / "test_conftest.py")) is False


class TestC1TheWidthPin:
    """Rich sizes an unpinned console on every print. 1 of 18 branches pins it."""

    def test_a_conftest_with_no_pin_is_convicted(self):
        assert _missing(IMPORT + RESET) == ["C1"]

    def test_the_template_spelling_satisfies_it(self):
        assert _missing(IMPORT + PIN + RESET) == []

    def test_a_direct_write_to_the_imported_console_satisfies_it(self):
        """Not every branch has to spell it as a loop."""
        source = (
            IMPORT
            + (
                "@pytest.fixture(autouse=True, scope='session')\n"
                "def pin():\n"
                "    display.CONSOLE.width = 200\n"
                "    display.err_console.width = 200\n"
            )
            + RESET
        )

        assert _missing(source) == []

    def test_a_console_the_fixture_built_itself_pins_nothing(self):
        """The product never prints to it. Same install-site rule as mock_console."""
        source = (
            IMPORT
            + (
                "@pytest.fixture(autouse=True, scope='session')\n"
                "def pin():\n"
                "    mine = Console(width=200)\n"
                "    mine.width = 200\n"
            )
            + RESET
        )

        assert _missing(source) == ["C1"]

    def test_a_width_name_from_no_aipass_import_pins_nothing(self):
        """Same fixture text, no product import: C1's name resolves to nothing.

        C2 still passes on the same file, and deliberately: `reset_command_state`
        is one unambiguous name, and a conftest calling it without the import
        raises NameError on the first test rather than leaking anything.
        """
        source = PIN + RESET

        assert _missing(source) == ["C1"]

    def test_a_function_scope_pin_does_not_satisfy_it(self):
        """The page says session scope. Per-test is a pin re-applied 4,798 times."""
        source = IMPORT + PIN.replace(", scope='session'", "") + RESET

        assert _missing(source) == ["C1"]

    def test_a_pin_that_is_not_autouse_does_not_satisfy_it(self):
        """A fixture nobody requests never runs."""
        source = IMPORT + PIN.replace("autouse=True, ", "") + RESET

        assert _missing(source) == ["C1"]

    def test_a_loop_over_a_locally_built_console_is_not_laundered(self):
        """Every element of the iterable has to be a product console."""
        source = (
            IMPORT
            + (
                "@pytest.fixture(autouse=True, scope='session')\n"
                "def pin():\n"
                "    for console in (display.CONSOLE, Console()):\n"
                "        console.width = 200\n"
            )
            + RESET
        )

        assert _missing(source) == ["C1"]


class TestC2TheCommandStateReset:
    """error() marks the process failed; 2 of 18 branches put that back."""

    def test_a_conftest_with_no_reset_is_convicted(self):
        assert _missing(IMPORT + PIN) == ["C2"]

    def test_the_template_spelling_satisfies_it(self):
        """Mutant: C2 credited only beside a product import, in conftest_fixtures_check.py — killed."""
        assert _missing(RESET) == ["C1"]

    def test_a_reset_before_the_yield_does_not_count(self):
        """It clears the PREVIOUS test's flag and hands this test's flag straight on."""
        source = (
            IMPORT
            + PIN
            + ("@pytest.fixture(autouse=True)\ndef clean():\n    display.reset_command_state()\n    yield\n")
        )

        assert _missing(source) == ["C2"]

    def test_a_reset_with_no_yield_at_all_does_not_count(self):
        """No yield means it never runs after the test."""
        source = IMPORT + PIN + "@pytest.fixture(autouse=True)\ndef clean():\n    display.reset_command_state()\n"

        assert _missing(source) == ["C2"]

    def test_a_reset_that_is_not_autouse_does_not_count(self):
        source = IMPORT + PIN + RESET.replace("autouse=True", "")

        assert _missing(source) == ["C2"]

    def test_the_reset_needs_no_session_scope(self):
        """C2 runs per test by design. Mutant: C2 refuses a scoped reset, conftest_fixtures_check.py — killed."""
        per_test = RESET.replace("autouse=True", "autouse=True, scope='function'")

        assert _missing(IMPORT + PIN + per_test) == []


class TestTheMessageAnAuthorReads:
    """Both sub-rules on one check, because _format_failure hides the rest."""

    def test_both_missing_share_one_check(self, tmp_path):
        path = _write(tmp_path, "import pytest\n")

        result = conftest_fixtures_check.check_module(str(path))

        assert len(result["checks"]) == 1
        assert result["checks"][0]["message"].count("conftest.py:") == 2

    def test_the_message_names_the_sub_rule_and_the_cure(self, tmp_path):
        path = _write(tmp_path, IMPORT + PIN)

        message = conftest_fixtures_check.check_module(str(path))["checks"][0]["message"]

        assert message == (
            "conftest.py: C2 no autouse fixture calls display.reset_command_state() after the test "
            "- @pytest.fixture(autouse=True) that yields, then calls display.reset_command_state()"
        )

    def test_the_c1_cure_is_the_fixture_from_the_template_page(self, tmp_path):
        path = _write(tmp_path, IMPORT + RESET)

        message = conftest_fixtures_check.check_module(str(path))["checks"][0]["message"]

        assert 'scope="session"' in message
        assert "display.CONSOLE and display.err_console" in message

    def test_a_passing_conftest_says_what_it_did(self, tmp_path):
        path = _write(tmp_path, IMPORT + PIN + RESET)

        message = conftest_fixtures_check.check_module(str(path))["checks"][0]["message"]

        assert message == "Width is pinned once and the command state is reset after every test"

    def test_a_missing_file_scores_zero_and_says_which(self, tmp_path):
        result = conftest_fixtures_check.check_module(str(tmp_path / "tests" / "conftest.py"))

        assert result["score"] == 0
        assert "File not found" in result["checks"][0]["message"]

    def test_a_syntax_error_yields_nothing(self):
        """ruff already convicts it, and a verdict on an unparseable file is a guess."""
        assert conftest_fixtures_check.scan("def broken(:\n") == []


class TestTheModelFileHoldsTheLine:
    """seedgo's own conftest is the fleet's only passing one, so it defines the shape."""

    def test_the_model_passes(self):
        assert conftest_fixtures_check.check_module(str(MODEL))["score"] == 100

    def test_the_model_with_the_width_fixture_gutted_is_convicted_naming_c1(self, tmp_path):
        source = MODEL.read_text(encoding="utf-8").replace(
            "    for console in (display.CONSOLE, display.err_console):\n        console.width = 200\n",
            "    return\n",
        )
        path = _write(tmp_path, source)

        result = conftest_fixtures_check.check_module(str(path))

        assert result["score"] == 0
        assert result["checks"][0]["message"].count("conftest.py:") == 1
        assert "C1" in result["checks"][0]["message"]

    def test_the_model_with_the_reset_gutted_is_convicted_naming_c2(self, tmp_path):
        source = MODEL.read_text(encoding="utf-8").replace("    display.reset_command_state()", "    pass")
        path = _write(tmp_path, source)

        result = conftest_fixtures_check.check_module(str(path))

        assert result["score"] == 0
        assert "C2" in result["checks"][0]["message"]

    def test_the_model_pinning_a_console_it_built_is_convicted(self, tmp_path):
        """The pin has to land on the product's consoles, on the real file too."""
        source = MODEL.read_text(encoding="utf-8").replace(
            "    for console in (display.CONSOLE, display.err_console):\n        console.width = 200\n",
            "    mine = Console(width=200)\n    mine.width = 200\n",
        )
        path = _write(tmp_path, source)

        assert conftest_fixtures_check.check_module(str(path))["score"] == 0


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_a_bare_conftest(self, tmp_path, capsys):
        path = _write(tmp_path, "import pytest\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — conftest_fixtures" in out
        assert "C1" in out

    def test_the_command_stays_quiet_on_a_conftest_with_both(self, tmp_path, capsys):
        path = _write(tmp_path, IMPORT + PIN + RESET)

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ conftest_fixtures" in out
        assert "[FAIL] — conftest_fixtures" not in out
