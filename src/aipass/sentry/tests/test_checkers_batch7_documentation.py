# =================== AIPass ====================
# Name: test_checkers_batch7_documentation.py
# Description: documentation_check: function and module docstrings by AST (split from test_checkers_batch7.py)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/aipass_standards/documentation_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports
# sentry: no-test-needed(stdlib) — ast.parse's parsing; the checkers only walk the tree it returns

import ast

import pytest

from aipass.sentry.apps.handlers.aipass_standards import documentation_check
from aipass.sentry.apps.handlers.aipass_standards.documentation_check import check_function_docstrings
from aipass.sentry.apps.handlers.bypass.utils import FILE_SCOPE

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestFunctionDocstringsReadTheSourceNotTheStrings:
    """Caught by dogfooding: my own new nominator scored 50 on documentation
    for a function that does not exist: three lines of a CODE EXAMPLE inside the module docstring."""

    def _check(self, source):
        return check_function_docstrings(source, source.split("\n"))

    def test_a_def_inside_a_docstring_is_not_a_function(self):
        """The exact shape that flagged my own nominator: a code example whose
        next `def`-or-`class` sentinel arrives before the docstring closes."""
        source = (
            '"""Module.\n'
            "\n"
            '    @pytest.mark.parametrize("item", collect())\n'
            "    def test_every_found_item_is_valid(item):\n"
            '        assert item["ok"]\n'
            '"""\n'
            "\n"
            "def real_one(x):\n"
            '    """Documented."""\n'
            "    return x\n"
        )
        # The fixture must PARSE, or this exercises the SyntaxError fallback, not the AST path.
        import ast

        ast.parse(source)
        result = self._check(source)
        assert result["passed"] is True, result["message"]

    def test_a_def_inside_a_string_constant_is_not_a_function(self):
        """The dead-cwd worlds' shape: a whole module built as a string and fed
        to a child. @canary, @api and @skills all carry one."""
        source = (
            'WORLD = """\nimport os\ndef realpath(p, *a, **k):\n    return p\n\ndef helper(q):\n    return q\n"""\n'
        )
        result = self._check(source)
        assert result["passed"] is True, result["message"]

    def test_a_real_undocumented_function_still_fails(self):
        """Negative control. Without this the fix reads as "documentation is
        optional now"."""
        result = self._check("def visible(x):\n    return x\n")
        assert result["passed"] is False
        assert "visible" in result["message"]

    def test_an_undocumented_async_function_is_finally_seen(self):
        """The line scan matched 'def ' and never 'async def', so @skills'"""
        result = self._check("async def main() -> None:\n    return None\n")
        assert result["passed"] is False
        assert "main" in result["message"]

    def test_a_documented_async_function_passes(self):
        assert self._check('async def main() -> None:\n    """Does a thing."""\n')["passed"] is True

    def test_a_private_function_is_still_exempt(self):
        assert self._check("def _hidden(x):\n    return x\n")["passed"] is True

    def test_an_unparseable_file_keeps_the_line_scans_answer(self):
        """Ignorance is not evidence. A file whose AST cannot be built has not
        been PROVEN to document everything, so it falls back rather than being exempted by the failure."""
        result = self._check("def visible(:\n    return 1\n")
        assert result["passed"] is False

    def test_the_reported_line_is_the_def_not_an_index(self):
        """@memory was sent to line 40 for a violation at line 106 once. The
        line in the message must be the line in the file."""
        source = "\n\n\n\n\ndef visible(x):\n    return x\n"
        assert "line 6" in self._check(source)["message"]


class TestModuleDocstringReadsThePositionNotTheSpelling:
    """The sibling defect, found the same way: by auditing a file of my own."""

    def test_an_r_prefixed_docstring_is_a_docstring(self):
        """The false negative that started it."""
        source = 'r"""Raw module docstring."""\n\n\ndef f():\n    pass\n'
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is True

    @pytest.mark.parametrize("prefix", ["r", "R", "u", "b", "rb", "f"])
    def test_every_string_prefix_python_accepts_is_accepted_here(self, prefix):
        """A literal table over the prefixes, so this one cannot vanish. b and
        rb are not docstrings to ``ast.get_docstring``: the ANSWER is Python's, never a first-character guess."""
        source = prefix + '"""Text."""\n'
        expected = ast.get_docstring(ast.parse(source)) is not None
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is expected

    def test_a_string_after_an_import_is_not_a_module_docstring(self):
        """@ai_mail's header.py, reduced. Python evaluates and discards it;
        ``help()`` shows nothing. A reader sees documentation, which is exactly
        why the scan agreed with the reader and not with the interpreter."""
        source = 'import os\n\n"""Looks like documentation."""\n'
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is False

    def test_a_function_docstring_is_not_credited_to_the_module(self):
        """@skills' registry.py, reduced - five files of theirs scored 100 on
        the strength of the first function's docstring."""
        source = 'from pathlib import Path\n\n\ndef f():\n    """Real, and not the module\'s."""\n'
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is False

    def test_a_class_docstring_is_not_credited_to_the_module(self):
        """@hooks' test_live_config_timeouts.py, reduced."""
        source = 'import json\n\n\nclass TestX:\n    """A class docstring."""\n'
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is False

    def test_a_real_module_docstring_still_passes(self):
        """The positive control. A rule that failed everything would satisfy
        every negative pin above and teach nothing."""
        source = '"""The module docstring."""\n\n\ndef f():\n    pass\n'
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is True

    def test_a_docstring_after_the_aipass_header_still_passes(self):
        """Every file in the fleet opens with a comment banner. If the AST arm
        had been wrong about comments, 1,677 files would have gone red at once -
        which is the kind of blast radius worth pinning rather than assuming."""
        source = "# === AIPass ===\n# Name: x.py\n# ===\n\n" + '"""Doc."""\n'
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is True

    def test_an_unparseable_file_falls_back_and_says_so(self):
        """The fallback must not read as a verdict from the real arm. My own
        exemption bought with a SyntaxError is an exemption granted on ignorance."""
        source = '"""Doc."""\n\ndef broken(\n'
        with pytest.raises(SyntaxError):
            ast.parse(source)
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is True
        assert "does not parse" in result["message"]

    def test_the_unparseable_fallback_can_still_fail(self):
        """The negative control for the control. A fallback that always passes
        would make every unparseable file clean, which is the exemption-on-
        ignorance shape one level down."""
        source = "import os\n\ndef broken(\n"
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is False
        assert "does not parse" in result["message"]


_UNDOCUMENTED = "import os\n\n\ndef alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"


def _documentation_under(tmp_path, **scope) -> dict:
    """documentation on apps/mod.py (no module docstring; alpha at line 4, beta at line 8) under one row."""
    target = tmp_path / "apps" / "mod.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_UNDOCUMENTED, encoding="utf-8")
    rules = [{"file": "apps/mod.py", "standard": "documentation", "reason": "t", **scope}] if scope else []
    return documentation_check.check_module(str(target), bypass_rules=rules)


def _verdicts(result) -> dict:
    return {c["name"]: (c["passed"], c["message"]) for c in result["checks"]}


class TestDocumentationAsksTheBypassTablePerSite:
    """An undocumented function is a site at its def; a missing module docstring is FILE_SCOPE."""

    def test_with_no_row_both_findings_are_reported(self, tmp_path):
        verdicts = _verdicts(_documentation_under(tmp_path))
        assert verdicts["Module docstring"][0] is False
        assert verdicts["Function docstrings"] == (False, "2 public functions missing docstrings: alpha (line 4)")

    def test_a_line_row_waives_its_def_and_the_other_function_still_convicts(self, tmp_path):
        result = _documentation_under(tmp_path, lines=[4])
        beta_open = (False, "1 public functions missing docstrings: beta (line 8)")
        assert _verdicts(result)["Function docstrings"] == beta_open
        assert (result["passed"], result["score"]) == (False, 0)

    def test_a_function_row_waives_the_functions_it_names_only(self, tmp_path):
        one = _verdicts(_documentation_under(tmp_path, functions=["beta"]))
        both = _verdicts(_documentation_under(tmp_path, functions=["alpha", "beta"]))
        assert one["Function docstrings"] == (False, "1 public functions missing docstrings: alpha (line 4)")
        assert both["Function docstrings"][0] is True
        assert both["Module docstring"][0] is False

    def test_a_file_scope_row_waives_the_module_docstring_and_no_function(self, tmp_path):
        verdicts = _verdicts(_documentation_under(tmp_path, functions=[FILE_SCOPE]))
        assert (verdicts["Module docstring"][0], FILE_SCOPE in verdicts["Module docstring"][1]) == (True, True)
        assert verdicts["Function docstrings"][0] is False

    def test_a_line_row_never_reaches_the_module_docstring(self, tmp_path):
        assert _verdicts(_documentation_under(tmp_path, lines=[1, 4, 8]))["Module docstring"][0] is False

    def test_every_site_waived_passes_and_a_whole_file_row_still_waives_all(self, tmp_path):
        assert _documentation_under(tmp_path, functions=[FILE_SCOPE, "alpha", "beta"])["score"] == 100
        assert _documentation_under(tmp_path, lines=None)["checks"][0]["name"] == "Bypassed"

    def test_an_unparseable_file_still_waives_by_line(self, tmp_path):
        target = tmp_path / "apps" / "mod.py"
        target.parent.mkdir(parents=True)
        target.write_text('"""Doc."""\n\ndef alpha():\n    return 1\n\ndef beta(\n', encoding="utf-8")
        rules = [{"file": "apps/mod.py", "standard": "documentation", "reason": "t", "lines": [3]}]
        verdicts = _verdicts(documentation_check.check_module(str(target), bypass_rules=rules))
        assert verdicts["Function docstrings"] == (False, "1 public functions missing docstrings: beta (line 6)")
