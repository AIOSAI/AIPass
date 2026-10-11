# =================== AIPass ====================
# Name: test_checkers_batch7_documentation.py
# Description: documentation_check: function and module docstrings by AST (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/aipass_standards/documentation_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; the checkers only walk the tree it returns

import ast

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import documentation_check
from aipass.seedgo.apps.handlers.aipass_standards.documentation_check import check_function_docstrings

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestFunctionDocstringsReadTheSourceNotTheStrings:
    """Caught by dogfooding: my own new nominator scored 50 on documentation
    for ``test_every_found_item_is_valid`` — a function that does not exist. It
    is three lines of a CODE EXAMPLE inside the module docstring.

    ``check_function_docstrings`` was a line scan: ``stripped.startswith("def ")``
    over the raw file, so any ``def`` inside a string literal was read as a real
    function. Every branch that built a subprocess world this week embedded
    Python in a string and got flagged for it — @api, @canary, @skills and two
    of my own files.

    The same scan had the mirror defect: it never matched ``async def`` at all,
    so an undocumented async function was invisible. ``find_import_section_end``
    in the same pack has handled ``async def`` since it was written.

    AST reads what Python reads. MEASURED before landing: 1841 files, 7 verdicts
    change — 5 false positives cleared, 2 genuine misses found, both of them
    async. Scope is unchanged on purpose: nested functions still count, because
    narrowing that would be a 40-file amnesty and a different decision.
    """

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
        # The fixture must PARSE, or this exercises the SyntaxError fallback and
        # proves nothing about the AST path. Caught while writing it: the first
        # version left the module docstring unterminated and went red for that.
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
        """The line scan matched 'def ' and never 'async def', so @skills'
        telethon_auth.main has been invisible for as long as it has existed."""
        result = self._check("async def main() -> None:\n    return None\n")
        assert result["passed"] is False
        assert "main" in result["message"]

    def test_a_documented_async_function_passes(self):
        assert self._check('async def main() -> None:\n    """Does a thing."""\n')["passed"] is True

    def test_a_private_function_is_still_exempt(self):
        assert self._check("def _hidden(x):\n    return x\n")["passed"] is True

    def test_an_unparseable_file_keeps_the_line_scans_answer(self):
        """Ignorance is not evidence. A file whose AST cannot be built has not
        been PROVEN to document everything, so it falls back rather than being
        exempted by the failure — the direction json_structure's bootstrap
        clause errs in."""
        result = self._check("def visible(:\n    return 1\n")
        assert result["passed"] is False

    def test_the_reported_line_is_the_def_not_an_index(self):
        """@memory was sent to line 40 for a violation at line 106 once. The
        line in the message must be the line in the file."""
        source = "\n\n\n\n\ndef visible(x):\n    return x\n"
        assert "line 6" in self._check(source)["message"]


class TestModuleDocstringReadsThePositionNotTheSpelling:
    """The sibling defect, found the same way: by auditing a file of my own.

    ``check_module_docstring`` was a line scan for a line STARTING with a triple
    quote in the first 30. That is wrong in both directions, and both were
    measured across 1,845 files before the rule changed:

      - an r-prefixed module docstring does not start with a quote character, so
        the scan reported MISSING on a file that has one (this checker's own
        ``posix_literal_check.py``, scored 50 for a docstring it carries);
      - any triple-quoted string in the first 30 lines was credited to the
        module - a class docstring, a function docstring on a short file, a
        string sitting after an import where Python discards it. Seven files
        fleet-wide, and that is the direction that matters: a false negative
        gets believed.

    Blast radius measured with the real checker before the change: 8 verdicts
    move across 1,560 files. Six from 100 to 50 (@skills 5, @ai_mail 1), one
    from 50 to 0 (@hooks), one from 50 to 100 (mine). Owners mailed - reported,
    never edited.
    """

    def test_an_r_prefixed_docstring_is_a_docstring(self):
        """The false negative that started it."""
        source = 'r"""Raw module docstring."""\n\n\ndef f():\n    pass\n'
        result = documentation_check.check_module_docstring(list(source.split("\n")))
        assert result["passed"] is True

    @pytest.mark.parametrize("prefix", ["r", "R", "u", "b", "rb", "f"])
    def test_every_string_prefix_python_accepts_is_accepted_here(self, prefix):
        """A literal table over the prefixes, so this one cannot vanish. b and
        rb are not docstrings to ``ast.get_docstring`` and f-strings are not
        constants at all - the point of the row is that the ANSWER is Python's,
        whatever it is, rather than a guess made by looking at the first
        character."""
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
        round-2 sentence: an exemption bought with a SyntaxError is an exemption
        granted on ignorance."""
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
