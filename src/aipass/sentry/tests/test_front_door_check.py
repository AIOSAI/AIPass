# =================== AIPass ====================
# Name: test_front_door_check.py
# Description: front_door_check — the gating row: per-site findings, scoped and whole-file waivers
# Version: 1.0.0
# Created: 2026-11-16
# Modified: 2026-11-16
# =============================================

"""Tests for apps/handlers/aipass_standards/front_door_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(shared) — scan_source's reading of each import shape; tests/test_front_door_count.py
# sentry: no-test-needed(shared) — matching_rule's file and scope matching; tests/test_bypass.py

import pytest

from aipass.sentry.apps.handlers.aipass_standards import front_door_check as checker

#: Where every specimen is written, so its owner is sentry.
REL = "src/aipass/sentry/apps/modules/specimen.py"

CASES = [
    ("modules", "from aipass.cli.apps.modules import console\n", [1]),
    ("handlers", "from aipass.flow.apps.handlers.plan.validator import validate_plan\n", [1]),
    ("door", "from aipass.prax import logger\n", []),
    ("own_branch", "from aipass.sentry.apps.handlers.json import json_handler\n", []),
    ("relative", "from ..handlers import json\n", []),
    ("in_function", "def run():\n    from aipass.memory.apps.modules.fleet import fleet\n", [2]),
    ("type_only", "if TYPE_CHECKING:\n    from aipass.cli.apps.modules import x\n", [2]),
    ("import_module", 'import importlib\nimportlib.import_module("aipass.memory.apps.modules.door_x")\n', [2]),
    ("patch", 'from unittest.mock import patch\npatch("aipass.cli.apps.modules.display.console")\n', [2]),
    ("prose", '"""from aipass.cli.apps.modules import console"""\nprint("aipass.cli.apps.modules")\n', []),
    ("import_as", "import aipass.trigger.apps.modules.core as core\n", [1]),
    ("nested_lib", "from aipass.skills.lib.drone_commands.apps.handlers.run import go\n", [1]),
]

#: Two sites, one at module level and one inside run().
TWO_SITES = (
    "from aipass.cli.apps.modules import console\n\n\ndef run():\n    from aipass.prax.apps.modules import logger\n"
)


def _write(tmp_path, source, rel=REL):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return str(target)


def _convicted(outcome):
    return [check["line"] for check in outcome["checks"] if not check["passed"]]


class TestTheRow:
    @pytest.mark.parametrize("source, lines", [case[1:] for case in CASES], ids=[case[0] for case in CASES])
    def test_the_row_convicts_and_acquits_what_the_scanner_reads(self, tmp_path, source, lines):
        outcome = checker.check_module(_write(tmp_path, source))
        assert (_convicted(outcome), outcome["score"], outcome["passed"]) == (lines, 0 if lines else 100, not lines)

    def test_a_test_file_reaching_into_another_branch_is_convicted(self, tmp_path):
        path = _write(tmp_path, "from aipass.cli.apps.modules import display\n", "src/aipass/sentry/tests/test_x.py")
        assert _convicted(checker.check_module(path)) == [1]

    def test_each_site_carries_its_line_function_and_the_door_cure(self, tmp_path):
        checks = checker.check_module(_write(tmp_path, TWO_SITES))["checks"]
        assert [(c["line"], c["function"]) for c in checks] == [(1, "<module>"), (5, "run")]
        assert "from aipass.prax import <name>" in checks[1]["message"]

    def test_a_site_in_a_nested_def_names_the_innermost_function(self, tmp_path):
        source = "def outer():\n    def inner():\n        from aipass.cli.apps.modules import x\n"
        assert [c["function"] for c in checker.check_module(_write(tmp_path, source))["checks"]] == ["inner"]

    def test_the_aipass_branch_importing_its_own_apps_is_acquitted(self, tmp_path):
        rel = "src/aipass/aipass/apps/modules/doctor.py"
        path = _write(tmp_path, "from aipass.aipass.apps.handlers.x import y\n", rel)
        assert checker.check_module(path)["score"] == 100

    def test_a_file_python_cannot_parse_scores_zero_unjudged(self, tmp_path):
        outcome = checker.check_module(_write(tmp_path, "def broken(:\n"))
        assert (outcome["passed"], outcome["score"]) == (False, 0)
        assert "Cannot be read as Python" in outcome["checks"][0]["message"]


class TestBypass:
    def _rule(self, **scope):
        return [{"file": REL, "standard": "front_door", "reason": "pin", **scope}]

    def test_a_lines_row_waives_exactly_its_line(self, tmp_path):
        outcome = checker.check_module(_write(tmp_path, TWO_SITES), self._rule(lines=[5]))
        assert _convicted(outcome) == [1]

    def test_a_functions_row_waives_exactly_its_function(self, tmp_path):
        outcome = checker.check_module(_write(tmp_path, TWO_SITES), self._rule(functions=["run"]))
        assert _convicted(outcome) == [1]

    def test_a_whole_file_row_waives_every_site(self, tmp_path):
        outcome = checker.check_module(_write(tmp_path, TWO_SITES), self._rule())
        assert (outcome["passed"], outcome["score"]) == (True, 100)

    def test_a_row_for_another_standard_waives_nothing(self, tmp_path):
        rules = [{"file": REL, "standard": "encapsulation", "reason": "pin"}]
        assert _convicted(checker.check_module(_write(tmp_path, TWO_SITES), rules)) == [1, 5]
