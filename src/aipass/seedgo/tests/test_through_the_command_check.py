# =================== META ====================
# Name: test_through_the_command_check.py
# Description: through_the_command_check — test template v1 item 10, no underscore helper called from a test
# Version: 1.0.0
# Created: 2026-09-21
# =============================================

"""Tests for apps/handlers/aipass_standards/through_the_command_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of FIX; the shapes and line numbers are asserted

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import skip_dirs, through_the_command_check
from aipass.seedgo.apps.modules import checklist

_PRODUCT = "aipass.memory.apps.handlers.chroma.chroma_subprocess"


def _write(tmp_path, body, name="test_thing.py"):
    """A test file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _names(source):
    """Just the name strings from a scan, in line order."""
    return [name for _line, name, _fix in through_the_command_check.scan(source)]


class TestAPrivateImportIsConvicted:
    """Shape (a). Importing the helper is already reaching past the command."""

    def test_a_private_name_imported_from_a_product_module_is_a_hit(self):
        source = f"from {_PRODUCT} import _source_matches\n"

        assert _names(source) == [f"imports the private name {_PRODUCT}._source_matches"]

    def test_an_import_inside_a_function_is_a_hit_too(self):
        """Item 10 says at any scope; item 8 is what convicts the placement."""
        source = f"def test_x():\n    from {_PRODUCT} import _source_matches\n    assert _source_matches\n"

        assert _names(source) == [f"imports the private name {_PRODUCT}._source_matches"]

    def test_each_private_name_in_one_statement_is_its_own_hit(self):
        source = f"from {_PRODUCT} import _a, _b, public\n"

        assert _names(source) == [
            f"imports the private name {_PRODUCT}._a",
            f"imports the private name {_PRODUCT}._b",
        ]

    def test_an_aliased_private_import_is_still_a_hit(self):
        """Renaming it on the way in does not make it public."""
        source = f"from {_PRODUCT} import _source_matches as matches\n"

        assert _names(source) == [f"imports the private name {_PRODUCT}._source_matches"]

    def test_the_line_number_is_the_import_statement(self):
        source = f"import os\n\nfrom {_PRODUCT} import _source_matches\n"

        assert through_the_command_check.scan(source)[0][0] == 3


class TestAPrivateReachThroughAProductBaseIsConvicted:
    """Shape (b). The call site, whichever way the module was bound."""

    def test_a_call_on_a_from_imported_module_is_a_hit(self):
        source = (
            "from aipass.memory.apps.handlers.chroma import chroma_subprocess\n"
            "\n"
            "def test_x():\n"
            '    assert chroma_subprocess._source_matches("a", "b")\n'
        )

        assert _names(source) == ["reaches the private name chroma_subprocess._source_matches"]

    def test_a_call_on_an_aliased_module_is_a_hit(self):
        source = f"import {_PRODUCT} as cs\n\ndef test_x():\n    assert cs._source_matches()\n"

        assert _names(source) == ["reaches the private name cs._source_matches"]

    def test_a_full_dotted_chain_from_a_plain_import_is_a_hit(self):
        """A bare `import aipass.a.b` binds only `aipass`, so the chain roots there."""
        source = f"import {_PRODUCT}\n\ndef test_x():\n    assert {_PRODUCT}._source_matches()\n"

        assert _names(source) == [f"reaches the private name {_PRODUCT}._source_matches"]

    def test_an_attribute_read_that_is_not_a_call_is_a_hit(self):
        """A private constant is as much of a non-contract as a private function."""
        source = f"import {_PRODUCT} as cs\n\ndef test_x():\n    assert cs._TABLE == {{}}\n"

        assert _names(source) == ["reaches the private name cs._TABLE"]

    def test_every_call_site_is_its_own_hit(self):
        source = (
            f"import {_PRODUCT} as cs\n"
            "\n"
            "def test_x():\n"
            "    assert cs._source_matches()\n"
            "    assert cs._source_matches()\n"
        )

        assert len(_names(source)) == 2


class TestWhatIsNeverConvicted:
    def test_a_public_name_is_not_a_hit(self):
        source = f"from {_PRODUCT} import handle_command\n\ndef test_x():\n    handle_command([])\n"

        assert _names(source) == []

    def test_a_dunder_is_not_a_hit(self):
        """__version__ is language surface, not a private helper."""
        source = f"import {_PRODUCT} as cs\n\ndef test_x():\n    assert cs.__version__\n"

        assert _names(source) == []

    def test_a_helper_the_test_file_defines_itself_is_not_a_hit(self):
        """The test's own scaffolding is not the product."""
        source = "def _make_row():\n    return {}\n\n\ndef test_x():\n    assert _make_row() == {}\n"

        assert _names(source) == []

    def test_a_private_name_imported_from_a_test_module_is_not_a_hit(self):
        """A shared fixture in another test file is scaffolding, not product."""
        source = "from aipass.memory.tests.conftest import _make_row\n"

        assert _names(source) == []

    def test_a_module_whose_name_merely_starts_with_aipass_is_not_a_hit(self):
        """The product root is a path SEGMENT, not a prefix: `aipassx` is somebody else."""
        source = "from aipassx.thing import _helper\n"

        assert _names(source) == []

    def test_a_private_name_bound_by_an_import_is_not_also_a_base(self):
        """`_helper.attr` must be one hit (the import), not two.

        A private import is shape (a) already; binding it as a base as well
        would charge the same reach twice.
        """
        source = f"from {_PRODUCT} import _source_matches\n\ndef test_x():\n    assert _source_matches._inner\n"

        assert _names(source) == [f"imports the private name {_PRODUCT}._source_matches"]

    def test_a_private_attribute_on_a_third_party_module_is_not_a_hit(self):
        source = "import pytest\n\ndef test_x():\n    assert pytest._version\n"

        assert _names(source) == []

    def test_a_private_read_on_a_name_the_file_never_imported_is_not_a_hit(self):
        """The base is resolved from this file's own bindings, and nothing deeper."""
        source = "def test_x(fixture):\n    assert fixture._internal\n"

        assert _names(source) == []

    def test_a_private_read_on_a_call_result_is_not_a_hit(self):
        """Dataflow the checker declines to follow, stated as a limit rather than guessed at."""
        source = f"from {_PRODUCT} import handle_command\n\ndef test_x():\n    assert handle_command([])._internal\n"

        assert _names(source) == []

    def test_a_write_to_a_private_name_is_left_to_item_15(self):
        """`m._cache = {}` is mock-at-the-edge, a different rule with a different cure."""
        source = f"import {_PRODUCT} as cs\n\ndef test_x():\n    cs._cache = {{}}\n"

        assert _names(source) == []

    def test_a_deletion_of_a_private_name_is_left_to_item_15(self):
        source = f"import {_PRODUCT} as cs\n\ndef test_x():\n    del cs._cache\n"

        assert _names(source) == []

    def test_a_monkeypatch_setattr_naming_a_private_name_is_left_to_item_15(self):
        source = f'import {_PRODUCT} as cs\n\ndef test_x(monkeypatch):\n    monkeypatch.setattr(cs, "_cache", {{}})\n'

        assert _names(source) == []

    def test_a_patch_target_string_naming_a_private_name_is_left_to_item_15(self):
        source = f'def test_x():\n    with patch("{_PRODUCT}._source_matches"):\n        pass\n'

        assert _names(source) == []


class TestTheFixIsTheSameForBothShapes:
    def test_the_fix_names_the_command_and_the_escalation(self):
        source = f"from {_PRODUCT} import _source_matches\n"

        fix = through_the_command_check.scan(source)[0][2]

        assert "through the command or a public function" in fix
        assert "@devpulse" in fix


class TestCheckModuleIsThePerFileLane:
    def test_a_clean_file_scores_a_hundred(self, tmp_path):
        path = _write(tmp_path, f"from {_PRODUCT} import handle_command\n\n\ndef test_x():\n    handle_command([])\n")

        result = through_the_command_check.check_module(str(path))

        assert result["passed"] is True
        assert result["score"] == 100

    def test_a_convicted_file_scores_zero(self, tmp_path):
        path = _write(tmp_path, f"from {_PRODUCT} import _source_matches\n")

        result = through_the_command_check.check_module(str(path))

        assert result["passed"] is False
        assert result["score"] == 0

    def test_every_hit_gets_its_own_line_with_file_and_number(self, tmp_path):
        """checklist._format_failure prints the FIRST failed check and counts the rest.

        So N checks would show one hit and hide the others; the lines live in
        one message instead, and this pins that they all survive.
        """
        path = _write(
            tmp_path,
            f"from {_PRODUCT} import _source_matches\n"
            f"import {_PRODUCT} as cs\n"
            "\n"
            "\n"
            "def test_x():\n"
            "    assert cs._check_plan()\n",
        )

        message = through_the_command_check.check_module(str(path))["checks"][0]["message"]

        assert message.splitlines() == [
            f"test_thing.py:1 imports the private name {_PRODUCT}._source_matches - {through_the_command_check.FIX}",
            f"test_thing.py:6 reaches the private name cs._check_plan - {through_the_command_check.FIX}",
        ]

    def test_a_missing_file_fails_rather_than_passes_quietly(self, tmp_path):
        result = through_the_command_check.check_module(str(tmp_path / "tests" / "gone.py"))

        assert result["passed"] is False
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_no_hits(self, tmp_path):
        """ruff already convicts the syntax error; guessing at line numbers would not help."""
        path = _write(tmp_path, "def test_x(:\n")

        assert through_the_command_check.check_module(str(path))["passed"] is True

    def test_a_file_bypass_acquits_the_whole_file(self, tmp_path):
        path = _write(tmp_path, f"from {_PRODUCT} import _source_matches\n")
        rules = [{"standard": "through_the_command", "file": str(path), "reason": "measured"}]

        result = through_the_command_check.check_module(str(path), bypass_rules=rules)

        assert result["passed"] is True
        assert "bypassed" in result["checks"][0]["message"]


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_a_private_reach(self, tmp_path, capsys):
        path = _write(tmp_path, f"import {_PRODUCT} as cs\n\n\ndef test_x():\n    assert cs._check_plan()\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — through_the_command" in out
        assert "reach it through the command or a public function" in out

    def test_the_command_stays_quiet_on_a_clean_file(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        path = _write(tmp_path, f"from {_PRODUCT} import handle_command\n\n\ndef test_x():\n    handle_command([])\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ through_the_command" in out
        assert "reach it through the command or a public function" not in out
