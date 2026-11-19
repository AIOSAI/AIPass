# =================== AIPass ====================
# Name: test_checkers_batch7_handlers.py
# Description: handlers_check auto-detection rulings (split from test_checkers_batch7.py)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-16
# =============================================

"""Tests for apps/handlers/aipass_standards/handlers_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

from typing import Any

import pytest

from aipass.sentry.apps.handlers.aipass_standards import handlers_check
from aipass.sentry.apps.handlers.aipass_standards.handlers_check import check_auto_detection
from aipass.sentry.apps.handlers.bypass.utils import FILE_SCOPE

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestAutoDetectionAsksAboutThePublicSurface:
    """The auto-detection rule means "a caller should not have to name itself",
    and that is a question about a handler's PUBLISHED functions, never a private helper's parameter name."""

    def _check(self, content):
        return handlers_check.check_auto_detection(content)

    def test_a_public_function_taking_module_name_still_needs_auto_detection(self):
        result = self._check("def log_operation(operation, data, module_name=None):\n    pass\n")
        assert result is not None and result["passed"] is False

    def test_a_private_helper_taking_module_name_is_not_the_rules_business(self):
        assert self._check("def _module_file(module_name, source_root):\n    return None\n") is None

    def test_a_keyword_only_module_name_on_a_public_function_still_counts(self):
        result = self._check("def write(data, *, module_name=None):\n    pass\n")
        assert result is not None and result["passed"] is False

    def test_a_public_function_with_auto_detection_passes(self):
        content = (
            "import inspect\n\n"
            "def log_operation(operation, data, module_name=None):\n"
            "    frame = inspect.stack()[1]\n    return frame\n"
        )
        result = self._check(content)
        assert result is not None and result["passed"] is True

    def test_a_file_with_no_module_name_parameter_is_silent(self):
        assert self._check("def check(path):\n    return path\n") is None

    def test_the_word_in_a_docstring_or_a_call_does_not_convict(self):
        """The old text scan keyed on `def name(... module_name`; the AST keys on
        the parameter itself, so prose and call sites cannot trigger it."""
        content = (
            'def resolve(path):\n    """Resolves a module_name for the caller."""\n    return log(module_name=path)\n'
        )
        assert self._check(content) is None

    def test_an_unparseable_file_falls_back_to_the_text_scan(self):
        """A file we could not read is not evidence the parameter is absent."""
        result = self._check("def log_operation(operation, module_name=None):\n    pass\n\ndef broken(:\n")
        assert result is not None and result["passed"] is False


class TestAutoDetectionNoLongerMandatesTheDeadCwdDefect:
    """@prax's report (2026-08-31): the checker's proof of auto-detection was
    the literal string ``inspect.stack()``, and its failure message said "use inspect.stack()"."""

    def _check(self, content) -> Any:
        return check_auto_detection(content)

    def test_the_cured_shape_passes_without_a_specially_named_helper(self):
        """@prax's blocking case. sys._getframe answers the same question and
        cannot die with no working directory."""
        content = (
            "import sys\n\n"
            "def log_operation(op, module_name=None):\n"
            "    if module_name is None:\n"
            "        module_name = sys._getframe(1).f_code.co_name\n"
            "    return module_name\n"
        )
        assert self._check(content)["passed"] is True

    def test_inspect_stack_still_counts_as_an_answer(self):
        """Widening, not a ban. Whether inspect.stack() is the RIGHT mechanism
        is @drone's dead-cwd sweep, a different standard; this one only asks whether the caller is detected."""
        content = (
            "import inspect\n\n"
            "def log_operation(op, module_name=None):\n"
            "    if module_name is None:\n"
            "        module_name = inspect.stack()[1]\n"
            "    return module_name\n"
        )
        assert self._check(content)["passed"] is True

    def test_the_mechanism_must_be_called_not_merely_mentioned(self):
        """The substring hole, closed. A file whose only ``inspect.stack()`` is
        in a docstring was passing: a string rule is too broad and too narrow at once."""
        content = (
            '"""We used to call inspect.stack() here — see the dead-cwd note."""\n'
            "import inspect\n\n"
            "def log_operation(op, module_name=None):\n    return module_name\n"
        )
        assert self._check(content)["passed"] is False

    def test_a_required_module_name_is_not_applicable(self):
        """Nothing to detect: every caller supplies it at every call site, so
        the prescribed frame walk would be dead code."""
        assert self._check("def run(module_name: str):\n    return module_name\n") is None

    def test_an_optional_module_name_is_still_in_scope(self):
        """Negative control on the clause above — the narrowing must not
        exempt the population the standard is actually about."""
        assert self._check("def run(module_name=None):\n    return module_name\n")["passed"] is False

    def test_a_keyword_only_module_name_with_a_default_is_in_scope(self):
        """Boundary: the default lives in kw_defaults, a different list. Reading
        only positional defaults would silently exempt every keyword-only API."""
        assert self._check("def run(*, module_name=None):\n    return module_name\n")["passed"] is False

    def test_a_keyword_only_module_name_without_a_default_is_not(self):
        content = "def run(*, module_name: str):\n    return module_name\n"
        assert self._check(content) is None

    def test_the_failure_message_names_the_blind_spot(self):
        """@trigger's events/warning_logged.py carries a ``module_name`` that is
        an event PAYLOAD field while its caller is the event bus; the checker reads the NAME, so the finding says so."""
        result = self._check("def run(module_name=None):\n    return module_name\n")
        assert "event payload" in result["message"]

    def test_other_frame_walk_spellings_are_accepted_too(self):
        """The standard's question is whether the caller is detected, never
        which library spells it."""
        for call in ("inspect.currentframe()", "traceback.extract_stack()", "inspect.getouterframes(None)"):
            content = f"import inspect, traceback\n\ndef run(module_name=None):\n    x = {call}\n    return x\n"
            assert self._check(content)["passed"] is True, call


class TestScopedBypassRows:
    """Each import is a site (line, enclosing function); the auto-detection finding is file-level."""

    _TWO_IMPORTS = (
        '"""Doc."""\n'
        "\n"
        "\n"
        "def load():\n"
        "    from aipass.flow.apps.handlers.plan import ops\n"
        "    return ops\n"
        "\n"
        "\n"
        "def save():\n"
        "    from aipass.demo.apps.modules import door\n"
        "    from aipass.memory.apps.handlers.json import store\n"
        "    return door, store\n"
    )

    @staticmethod
    def _verdicts(tmp_path, source: str, **scope) -> dict:
        """handlers check_module on demo/apps/handlers/work/thing.py under one row of the scope given."""
        target = tmp_path / "demo" / "apps" / "handlers" / "work" / "thing.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        rules = (
            [{"file": "apps/handlers/work/thing.py", "standard": "handlers", "reason": "t", **scope}] if scope else []
        )
        result = handlers_check.check_module(str(target), bypass_rules=rules)
        return {"score": result["score"], **{check["name"]: check for check in result["checks"]}}

    def test_a_line_row_waives_its_import_and_the_other_still_convicts(self, tmp_path):
        """Mutant: the per-site ask drops line= — killed."""
        verdict = self._verdicts(tmp_path, self._TWO_IMPORTS, lines=[5])
        assert verdict["Handler independence"]["passed"] is False
        assert "line 11" in verdict["Handler independence"]["message"]
        assert "line 5" not in verdict["Handler independence"]["message"]

    def test_a_function_row_waives_the_imports_inside_that_function_only(self, tmp_path):
        """Mutant: the per-site ask drops name= — killed."""
        verdict = self._verdicts(tmp_path, self._TWO_IMPORTS, functions=["save"])
        assert verdict["No orchestration"]["passed"] is True
        assert verdict["Handler independence"]["message"].endswith(
            "line 5: from aipass.flow.apps.handlers.plan import ops"
        )

    def test_rows_on_every_site_pass_and_a_whole_file_row_still_waives(self, tmp_path):
        """Mutant: one waived site waives every site — killed by the line-row pin."""
        assert self._verdicts(tmp_path, self._TWO_IMPORTS, functions=["load", "save"])["score"] == 100
        assert self._verdicts(tmp_path, self._TWO_IMPORTS, lines=None)["score"] == 100

    def test_auto_detection_is_waived_by_the_file_scope_name_and_not_by_a_line(self, tmp_path):
        """Mutant: the file-level waiver drops name=FILE_SCOPE — killed."""
        source = '"""Doc."""\n\n\ndef log(message, module_name=None):\n    return message\n'
        by_scope = self._verdicts(tmp_path, source, functions=[FILE_SCOPE])
        by_line = self._verdicts(tmp_path, source, lines=[4])
        assert (by_scope["Auto-detection pattern"]["passed"], by_line["Auto-detection pattern"]["passed"]) == (
            True,
            False,
        )
