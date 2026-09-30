# =================== META ====================
# Name: test_import_site_check.py
# Description: import_site_check — test template v1 item 8, product imports at the top of a test file
# Version: 1.1.0
# Created: 2026-09-21
# Modified: 2026-09-23
# =============================================

"""Tests for apps/handlers/aipass_standards/import_site_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — that ast.parse builds the tree it documents
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py
# seedgo: no-test-needed(constant) — the prose of FIX_IMPORT and FIX_STUB; both are asserted BY NAME

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import import_site_check, skip_dirs
from aipass.seedgo.apps.modules import checklist


def _write(tmp_path, body, name="test_thing.py"):
    """A test file on disk under a tests/ directory, which is what the rule scopes to."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    path = tests_dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _shapes(source):
    """Just the shape strings from a scan, in line order."""
    return [shape for _line, shape, _fix in import_site_check.scan(source)]


class TestADeferredProductImportIsConvicted:
    """Shape (a). An import inside a test runs after the test could have replaced it."""

    def test_a_from_import_in_a_function_is_a_hit(self):
        source = "def test_x():\n    from aipass.prax import logger\n    assert logger\n"

        assert _shapes(source) == ["product import inside a function (from aipass.prax import ...)"]

    def test_a_plain_import_in_a_function_is_a_hit(self):
        source = "def test_x():\n    import aipass.prax\n    assert aipass.prax\n"

        assert _shapes(source) == ["product import inside a function (import aipass.prax)"]

    def test_an_import_in_a_method_is_a_hit(self):
        source = (
            "class TestThing:\n    def test_x(self):\n        from aipass.prax import logger\n        assert logger\n"
        )

        assert _shapes(source) == ["product import inside a function (from aipass.prax import ...)"]

    def test_an_import_in_a_class_body_is_a_hit(self):
        """A class body runs at import time, but the name never reaches module scope."""
        source = "class TestThing:\n    from aipass.prax import logger\n"

        assert _shapes(source) == ["product import inside a function (from aipass.prax import ...)"]

    def test_an_import_staged_behind_a_patch_is_a_hit(self):
        """The worst shape in the fleet: 277 hits sit inside a with-block."""
        source = (
            "def test_x():\n"
            "    with patch('aipass.flow.apps.modules.list_plans.console'):\n"
            "        from aipass.flow.apps.modules.list_plans import list_plans\n"
            "        list_plans()\n"
        )

        assert _shapes(source) == [
            "product import inside a function (from aipass.flow.apps.modules.list_plans import ...)"
        ]

    def test_a_method_import_is_counted_once_not_twice(self):
        """An import in a method has BOTH a ClassDef and a FunctionDef ancestor.

        Counting per scope rather than per node reported the fleet at 9,174
        hits against a real 5,175 — the number that would have been quoted to
        the owner.
        """
        source = (
            "class TestThing:\n"
            "    class Inner:\n"
            "        def test_x(self):\n"
            "            from aipass.prax import logger\n"
            "            assert logger\n"
        )

        assert len(_shapes(source)) == 1

    def test_the_line_number_is_the_import_not_the_function(self):
        source = "def test_x():\n    pass\n\n\ndef test_y():\n    from aipass.prax import logger\n    assert logger\n"

        assert import_site_check.scan(source)[0][0] == 6

    def test_the_fix_names_the_move(self):
        source = "def test_x():\n    from aipass.prax import logger\n    assert logger\n"

        assert import_site_check.scan(source)[0][2] == import_site_check.FIX_IMPORT


class TestModuleLevelAndForeignImportsAreLeftAlone:
    """Over-refusal guard. The rule is a prohibition on one mechanism, not tidiness."""

    def test_a_module_level_product_import_is_not_a_hit(self):
        source = "from aipass.prax import logger\n\n\ndef test_x():\n    assert logger\n"

        assert _shapes(source) == []

    def test_a_module_level_plain_import_is_not_a_hit(self):
        """Both import forms have their own branch, so both need their own acquittal.

        Added 2026-09-21 after a mutant that convicted every `import aipass...`
        regardless of where it sat survived the whole file: every other
        module-level test used the `from ... import` form.
        """
        source = "import aipass.prax\n\n\ndef test_x():\n    assert aipass.prax\n"

        assert _shapes(source) == []

    def test_a_module_level_try_guarded_import_is_not_a_hit(self):
        """Nothing at module level can be preceded by a test's own patching."""
        source = "try:\n    from aipass.prax import logger\nexcept ImportError:\n    logger = None\n"

        assert _shapes(source) == []

    def test_a_module_level_type_checking_import_is_not_a_hit(self):
        source = "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from aipass.prax import logger\n"

        assert _shapes(source) == []

    def test_a_stdlib_import_inside_a_function_is_not_a_hit(self):
        source = "def test_x():\n    import json\n    assert json\n"

        assert _shapes(source) == []

    def test_a_third_party_import_inside_a_function_is_not_a_hit(self):
        source = "def test_x():\n    from rich.console import Console\n    assert Console\n"

        assert _shapes(source) == []

    def test_a_module_whose_name_merely_starts_with_aipass_is_not_a_hit(self):
        """The root segment is matched, not a prefix: aipassport is somebody else's package."""
        source = "def test_x():\n    import aipassport\n    assert aipassport\n"

        assert _shapes(source) == []


class TestTheStubMechanismIsConvicted:
    """Shape (b). Rebuilding the module under test is the defect the rule exists for."""

    @pytest.mark.parametrize(
        "statement,expected",
        [
            ('sys.modules["aipass.prax"] = stub', "sys.modules[...] = ..."),
            ('del sys.modules["aipass.prax"]', "del sys.modules[...]"),
            ('sys.modules.pop("aipass.prax", None)', "sys.modules.pop(...)"),
            ('patch.dict(sys.modules, {"aipass.prax": stub})', "patch.dict(sys.modules, ...)"),
            ('monkeypatch.setitem(sys.modules, "aipass.prax", stub)', "monkeypatch.setitem(sys.modules, ...)"),
            ('monkeypatch.delitem(sys.modules, "aipass.prax")', "monkeypatch.delitem(sys.modules, ...)"),
            ('importlib.import_module("aipass.prax")', "importlib.import_module(...)"),
            ("importlib.reload(aipass.prax)", "importlib.reload(...)"),
        ],
    )
    def test_each_mechanism_is_named_in_the_hit(self, statement, expected):
        source = f"def test_x():\n    {statement}\n"

        assert _shapes(source) == [f"sys.modules stub ({expected})"]

    def test_a_module_level_sys_modules_write_is_still_convicted(self):
        """At module level it poisons every test in the file rather than one."""
        source = 'sys.modules["aipass.prax"] = stub\n'

        assert _shapes(source) == ["sys.modules stub (sys.modules[...] = ...)"]

    def test_a_module_level_importlib_call_is_not_convicted(self):
        """It runs before any test could stage a replacement for it to pick up.

        prax/tests/test_commons_feed.py:25 is the fleet's only instance.
        """
        source = 'feed = importlib.import_module("aipass.prax.apps.handlers.monitoring.commons_feed")\n'

        assert _shapes(source) == []

    def test_a_sys_modules_write_naming_no_product_is_not_convicted(self):
        """A test has every right to stub a third-party module."""
        source = 'def test_x():\n    monkeypatch.setitem(sys.modules, "requests", stub)\n'

        assert _shapes(source) == []

    def test_a_product_module_named_through_a_variable_is_missed(self):
        """The known limit, pinned so it cannot be lost: one statement, not dataflow."""
        source = 'def test_x():\n    key = "aipass.prax"\n    sys.modules[key] = stub\n'

        assert _shapes(source) == []

    def test_the_fix_names_the_edge(self):
        source = 'def test_x():\n    monkeypatch.setitem(sys.modules, "aipass.prax", stub)\n'

        assert import_site_check.scan(source)[0][2] == import_site_check.FIX_STUB


class TestCheckModuleIsThePerFileLane:
    def test_a_clean_file_scores_a_hundred(self, tmp_path):
        path = _write(tmp_path, "from aipass.prax import logger\n\n\ndef test_x():\n    assert logger\n")

        result = import_site_check.check_module(str(path))

        assert result["passed"] is True
        assert result["score"] == 100

    def test_a_convicted_file_scores_zero(self, tmp_path):
        path = _write(tmp_path, "def test_x():\n    from aipass.prax import logger\n    assert logger\n")

        result = import_site_check.check_module(str(path))

        assert result["passed"] is False
        assert result["score"] == 0

    def test_every_hit_gets_its_own_line_with_file_and_number(self, tmp_path):
        """checklist._format_failure prints the FIRST failed check and counts the rest.

        So N checks would show one hit and hide the others; the lines live in
        one message instead, and this pins that they all survive.
        """
        path = _write(
            tmp_path,
            "def test_x():\n"
            "    from aipass.prax import logger\n"
            "    assert logger\n"
            "\n"
            "\n"
            "def test_y():\n"
            "    from aipass.cli import display\n"
            "    assert display\n",
        )

        message = import_site_check.check_module(str(path))["checks"][0]["message"]

        fix = import_site_check.FIX_IMPORT
        assert message.splitlines() == [
            f"test_thing.py:2 product import inside a function (from aipass.prax import ...) - {fix}",
            f"test_thing.py:7 product import inside a function (from aipass.cli import ...) - {fix}",
        ]

    def test_a_missing_file_fails_rather_than_passes_quietly(self, tmp_path):
        result = import_site_check.check_module(str(tmp_path / "tests" / "gone.py"))

        assert result["passed"] is False
        assert "File not found" in result["checks"][0]["message"]

    def test_an_unparseable_file_yields_no_hits(self, tmp_path):
        """ruff already convicts the syntax error; guessing at line numbers would not help."""
        path = _write(tmp_path, "def test_x(:\n")

        assert import_site_check.check_module(str(path))["passed"] is True

    def test_a_file_bypass_acquits_the_whole_file(self, tmp_path):
        path = _write(tmp_path, "def test_x():\n    from aipass.prax import logger\n    assert logger\n")
        rules = [{"standard": "import_site", "file": str(path), "reason": "measured"}]

        result = import_site_check.check_module(str(path), bypass_rules=rules)

        assert result["passed"] is True
        assert "bypassed" in result["checks"][0]["message"]


class TestThroughTheChecklistCommand:
    """The door an agent actually meets the rule through: the PostToolUse lane."""

    @pytest.fixture(autouse=True)
    def _not_a_scratchpad(self, monkeypatch):
        """tmp_path lives under a temp root, and checklist skips those by design."""
        monkeypatch.setattr(skip_dirs, "_get_temp_roots", lambda: [])

    def test_the_command_convicts_a_deferred_import(self, tmp_path, capsys):
        path = _write(tmp_path, "def test_x():\n    from aipass.prax import logger\n    assert logger\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "[FAIL] — import_site" in out
        assert import_site_check.FIX_IMPORT in out

    def test_the_command_stays_quiet_on_a_clean_file(self, tmp_path, capsys):
        """The standard still prints — as a tick. The absence to assert is the conviction."""
        path = _write(tmp_path, "from aipass.prax import logger\n\n\ndef test_x():\n    assert logger\n")

        checklist.handle_command("checklist", [str(path)])

        out = capsys.readouterr().out
        assert "✓ import_site" in out
        assert import_site_check.FIX_IMPORT not in out
