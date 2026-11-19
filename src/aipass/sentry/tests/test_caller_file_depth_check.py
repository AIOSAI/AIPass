# =================== AIPass ====================
# Name: test_caller_file_depth_check.py
# Description: caller_file_depth_check - a caller's __file__ handed to a depth-climbing function from a wrong layout
# Version: 1.1.0
# Created: 2026-11-17
# Modified: 2026-11-18
# =============================================

"""Tests for apps/handlers/aipass_standards/caller_file_depth_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py

import pytest

from aipass.sentry.apps.handlers.aipass_standards import caller_file_depth_check as checker

#: A depth function: the branch root is parents[3] of the file it is handed.
SERVICE = "from pathlib import Path\n\n\ndef for_module(file):\n    return Path(file).parents[3]\n"
#: A shallow helper: one level up from a parameter finds a directory, not a branch.
SHALLOW = "from pathlib import Path\n\n\ndef folder_of(file):\n    return Path(file).parent\n"
CALLER = "from aipass.lib import service\n\nHANDLE = service.for_module(__file__)\n"
#: One call at module level (line 3), one inside f (line 7).
TWO_CALLS = CALLER + "\n\ndef f():\n    return service.for_module(__file__)\n"
RIGHT = "demo/apps/handlers/json/jh.py"


@pytest.fixture
def tree(tmp_path):
    pkg = tmp_path / "src" / "aipass"

    def write(rel, source):
        target = pkg / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        return target

    write("lib/apps/handlers/service.py", SERVICE)
    write("lib/apps/handlers/shallow.py", SHALLOW)
    checker.depth_functions.cache_clear()
    yield write
    checker.depth_functions.cache_clear()


def _convicted(outcome):
    return [check["line"] for check in outcome["checks"] if not check["passed"]]


class TestTheCallSite:
    def test_a_caller_at_the_layout_the_function_assumes_passes(self, tree):
        outcome = checker.check_module(str(tree(RIGHT, CALLER)))
        assert (outcome["score"], _convicted(outcome)) == (100, [])

    def test_a_caller_at_another_depth_is_convicted(self, tree):
        outcome = checker.check_module(str(tree("demo/apps/modules/jh.py", CALLER)))
        assert (outcome["score"], _convicted(outcome)) == (0, [3])
        assert "for_module" in outcome["checks"][0]["message"]

    def test_a_caller_that_also_runs_from_a_copy_beside_apps_is_convicted(self, tree):
        tree(RIGHT, CALLER)
        tree("demo/.live-1/handlers/json/jh.py", CALLER)
        outcome = checker.check_module(str(tree(RIGHT, CALLER)))
        assert (outcome["score"], _convicted(outcome)) == (0, [3])
        assert ".live-1" in outcome["checks"][0]["message"]

    def test_a_claimed_branch_is_convicted_with_the_by_name_line_as_the_cure(self, tree):
        tree("hooks/.live-1/handlers/json/jh.py", CALLER)
        outcome = checker.check_module(str(tree("hooks/apps/handlers/json/jh.py", CALLER)))
        assert _convicted(outcome) == [3]
        assert '_h = json_handler.for_branch("hooks")' in outcome["checks"][0]["message"]

    def test_the_by_name_line_from_a_snapshot_copy_is_not_convicted(self, tree):
        by_name = '_h = json_handler.for_branch("hooks")\n'
        tree("hooks/.live-1/handlers/json/jh.py", by_name)
        outcome = checker.check_module(str(tree("hooks/apps/handlers/json/jh.py", by_name)))
        assert (outcome["score"], _convicted(outcome)) == (100, [])

    def test_a_whole_branch_copy_elsewhere_is_not_a_run_location(self, tree):
        tree("demo/docs.local/snap/apps/handlers/json/jh.py", CALLER)
        assert checker.check_module(str(tree(RIGHT, CALLER)))["score"] == 100

    def test_an_archive_copy_is_never_read(self, tree):
        tree("demo/.archive/handlers/json/jh.py", CALLER)
        assert checker.check_module(str(tree(RIGHT, CALLER)))["score"] == 100

    def test_a_path_other_than_the_callers_own_file_is_not_this_class(self, tree):
        source = "from aipass.lib import service\n\nHANDLE = service.for_module(SOME_PATH)\n"
        assert checker.check_module(str(tree("demo/apps/modules/jh.py", source)))["score"] == 100

    def test_a_one_level_climb_is_not_a_depth_function(self, tree):
        source = "from aipass.lib import shallow\n\nD = shallow.folder_of(__file__)\n"
        assert checker.check_module(str(tree("demo/apps/modules/jh.py", source)))["score"] == 100

    def test_a_file_python_cannot_parse_scores_zero_unjudged(self, tree):
        outcome = checker.check_module(str(tree(RIGHT, "def broken(:\n")))
        assert (outcome["score"], "unjudged" in outcome["checks"][0]["message"]) == (0, True)


class TestTheFunctionsFound:
    def test_the_depth_function_is_found_with_its_climb(self, tree):
        found = checker.depth_functions(str(tree(RIGHT, CALLER).parents[4]))
        assert found["for_module"] == 4 and "folder_of" not in found


class TestBypass:
    WRONG = "demo/apps/modules/jh.py"

    def test_a_lines_row_waives_exactly_its_line(self, tree):
        rule = {"file": "jh.py", "standard": "caller_file_depth", "lines": [3]}
        assert _convicted(checker.check_module(str(tree(self.WRONG, TWO_CALLS)), [rule])) == [7]

    def test_a_functions_row_waives_exactly_its_function(self, tree):
        rule = {"file": "jh.py", "standard": "caller_file_depth", "functions": ["f"]}
        assert _convicted(checker.check_module(str(tree(self.WRONG, TWO_CALLS)), [rule])) == [3]
