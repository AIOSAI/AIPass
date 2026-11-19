# =================== AIPass ====================
# Name: test_fixed_depth_path_check.py
# Description: fixed_depth_path_check - a path climbed a fixed depth off __file__ that is wrong on a wheel install
# Version: 1.1.0
# Created: 2026-11-17
# Modified: 2026-11-18
# =============================================

"""Tests for apps/handlers/aipass_standards/fixed_depth_path_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# sentry: no-test-needed(shared) — applies_to_file's production/tests split; tests/test_applicability.py

import pytest

from aipass.sentry.apps.handlers.aipass_standards import fixed_depth_path_check as checker

#: Five levels below src/aipass: parents[3] is the branch root, parents[4] is src/aipass, parents[5] leaves it.
REL = "src/aipass/demo/apps/handlers/thing/mod.py"
#: The installer's home detector shape: the aipass package's own origin, climbed.
SPEC = "H = Path(importlib.util.find_spec('aipass').origin)"
#: A branch root bound at module level, then joined to an unshipped folder inside a function.
BOUND_THEN_LOGS = "from pathlib import Path\nB = Path(__file__).parents[3]\n\n\ndef f():\n    return B / 'logs'\n"
#: A name bound twice (a walk up to a marker) holds no fixed depth, so it is not followed.
REBOUND = "from pathlib import Path\nC = Path(__file__).parent\nC = C.parent\nL = C / 'logs'\n"
#: Two escaping sites: one at module level (line 2), one inside f (line 6).
TWO_SITES = (
    "from pathlib import Path\nA = Path(__file__).parents[5]\n\n\ndef f():\n    return Path(__file__).parents[6]\n"
)
#: A branch's own dot folder reached through os.path: four dirnames from REL land on the branch root.
DOT_BY_OS_PATH = "import os\nT = os.path.join(" + "os.path.dirname(" * 4 + "__file__))))" + ", '.ai_mail.local')\n"


def _write(tmp_path, source, rel=REL):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return str(target)


def _convicted(outcome):
    return [check["line"] for check in outcome["checks"] if not check["passed"]]


ROWS = [
    ("parents_escape", "from pathlib import Path\nROOT = Path(__file__).resolve().parents[5]\n", [2]),
    ("parent_chain_escape", "from pathlib import Path\nR = Path(__file__)" + ".parent" * 6 + "\n", [2]),
    ("dirname_escape", "import os\nR = " + "os.path.dirname(" * 6 + "__file__" + ")" * 6 + "\n", [2]),
    ("package_root_kept", "from pathlib import Path\nPKG = Path(__file__).parents[4]\n", []),
    ("branch_root_kept", "from pathlib import Path\nHOME = Path(__file__).parents[3]\nT = HOME / 'templates'\n", []),
    ("sibling_kept", "from pathlib import Path\nDATA = Path(__file__).parent / 'data.json'\n", []),
    ("logs_inside", "from pathlib import Path\nLOGS = Path(__file__).resolve().parents[3] / 'logs'\n", [2]),
    ("json_dir_inside", "from pathlib import Path\nJ = Path(__file__).parents[3] / 'demo_json'\n", [2]),
    ("dot_dir_at_branch_root", "from pathlib import Path\nT = Path(__file__).parents[3] / '.trinity' / 'x.json'\n", []),
    ("dot_dir_at_branch_root_os", DOT_BY_OS_PATH, []),
    ("dot_dir_above_the_branch", "from pathlib import Path\nC = Path(__file__).parents[4] / '.ai_central'\n", [2]),
    ("dot_dir_below_the_branch_root", "from pathlib import Path\nC = Path(__file__).parents[2] / '.cache'\n", [2]),
    ("bound_then_climbed", "from pathlib import Path\nHERE = Path(__file__).parent\nROOT = HERE.parents[4]\n", [3]),
    ("bound_then_logs", BOUND_THEN_LOGS, [6]),
    ("spec_origin_escape", "import importlib.util\nfrom pathlib import Path\n" + SPEC + ".parent.parent.parent\n", [3]),
    ("spec_origin_kept", "import importlib.util\nfrom pathlib import Path\n" + SPEC + ".parent\n", []),
    ("module_file_escape", "import aipass\nfrom pathlib import Path\nR = Path(aipass.__file__).parents[1]\n", [3]),
    ("escape_then_logs_once", "from pathlib import Path\nL = Path(__file__).parents[5] / 'logs'\n", [2]),
    ("dotdot_join_not_read", "import os\nL = os.path.join(os.path.dirname(__file__), '..', 'logs')\n", []),
    ("rebound_name_not_followed", REBOUND, []),
    ("no_climb", "from pathlib import Path\nP = Path('x') / 'logs'\n", []),
]


class TestTheRow:
    @pytest.mark.parametrize("source, lines", [r[1:] for r in ROWS], ids=[r[0] for r in ROWS])
    def test_a_climb_is_convicted_only_where_a_wheel_answers_wrong(self, tmp_path, source, lines):
        outcome = checker.check_module(_write(tmp_path, source))
        assert (_convicted(outcome), outcome["score"], outcome["passed"]) == (lines, 0 if lines else 100, not lines)

    def test_the_finding_says_where_the_climb_lands_and_the_cure(self, tmp_path):
        check = checker.check_module(_write(tmp_path, ROWS[0][1]))["checks"][0]
        assert "leaves the installed aipass package" in check["message"] and "mod.py:2" in check["message"]
        state = checker.check_module(_write(tmp_path, ROWS[6][1]))["checks"][0]
        assert "'logs' is not shipped in the wheel" in state["message"]

    def test_each_site_carries_its_function(self, tmp_path):
        assert checker.check_module(_write(tmp_path, BOUND_THEN_LOGS))["checks"][0]["function"] == "f"

    def test_a_file_outside_src_aipass_is_not_in_the_wheel_and_passes_saying_so(self, tmp_path):
        outcome = checker.check_module(_write(tmp_path, ROWS[0][1], "tools/script.py"))
        assert outcome["score"] == 100 and "outside src/aipass" in outcome["checks"][0]["message"]

    def test_a_file_python_cannot_parse_scores_zero_unjudged(self, tmp_path):
        outcome = checker.check_module(_write(tmp_path, "def broken(:\n"))
        assert (outcome["passed"], outcome["score"]) == (False, 0)
        assert "unjudged" in outcome["checks"][0]["message"]


CONFIG = "src/aipass/demo/apps/config.py"
HANDLER = "src/aipass/demo/apps/handlers/h.py"
#: The split form: the root counted in one file, joined in another.
ROOT_BOUND = "from pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\n"
JOINS = [
    ("imported_root_to_logs", "from aipass.demo.apps.config import ROOT\n\nLOG = ROOT / 'logs' / 'x.jsonl'\n", [3]),
    ("imported_root_aliased", "from aipass.demo.apps.config import ROOT as R\n\nJ = R / 'demo_json'\n", [3]),
    ("imported_root_to_dot_dir", "from aipass.demo.apps.config import ROOT\n\nS = ROOT / '.sentry'\n", []),
    ("imported_root_to_templates", "from aipass.demo.apps.config import ROOT\n\nT = ROOT / 'templates'\n", []),
    ("imported_root_to_runtime_file", "from aipass.demo.apps.config import ROOT\n\nD = ROOT / 'demo_data.json'\n", [3]),
    ("imported_root_to_shipped_file", "from aipass.demo.apps.config import ROOT\n\nD = ROOT / 'README.md'\n", []),
    ("imported_root_rebound", "from aipass.demo.apps.config import ROOT\n\nROOT = None\nL = ROOT / 'logs'\n", []),
    ("unrelated_name", "from aipass.demo.apps.config import OTHER\n\nL = OTHER / 'logs'\n", []),
]


class TestTheRootNamedInOneFile:
    @pytest.fixture
    def demo(self, tmp_path):
        _write(tmp_path, ROOT_BOUND, CONFIG)
        _write(tmp_path, "src/aipass/demo/demo_data.json\n", ".gitignore")
        return tmp_path

    @pytest.mark.parametrize("source, lines", [r[1:] for r in JOINS], ids=[r[0] for r in JOINS])
    def test_a_join_of_an_imported_root_is_convicted_at_the_join(self, demo, source, lines):
        assert _convicted(checker.check_module(_write(demo, source, HANDLER))) == lines

    def test_the_finding_names_where_the_root_was_counted(self, demo):
        outcome = checker.check_module(_write(demo, JOINS[0][1], HANDLER))
        assert "ROOT counted at apps/config.py:3" in outcome["checks"][0]["message"]

    def test_a_root_re_exported_through_a_second_file_is_followed(self, demo):
        _write(demo, "from aipass.demo.apps.config import ROOT\n", "src/aipass/demo/apps/handlers/paths.py")
        source = "from aipass.demo.apps.handlers.paths import ROOT\n\nL = ROOT / 'logs'\n"
        assert _convicted(checker.check_module(_write(demo, source, HANDLER))) == [3]

    def test_a_root_from_another_branch_is_not_followed(self, demo):
        _write(demo, ROOT_BOUND, "src/aipass/other/apps/config.py")
        source = "from aipass.other.apps.config import ROOT\n\nL = ROOT / 'logs'\n"
        assert _convicted(checker.check_module(_write(demo, source, HANDLER))) == []


class TestBypass:
    TWO = TWO_SITES

    def test_a_lines_row_waives_exactly_its_line(self, tmp_path):
        rule = {"file": "mod.py", "standard": "fixed_depth_path", "lines": [2]}
        assert _convicted(checker.check_module(_write(tmp_path, self.TWO), [rule])) == [6]

    def test_a_functions_row_waives_exactly_its_function(self, tmp_path):
        rule = {"file": "mod.py", "standard": "fixed_depth_path", "functions": ["f"]}
        assert _convicted(checker.check_module(_write(tmp_path, self.TWO), [rule])) == [2]

    def test_a_whole_file_row_waives_every_site(self, tmp_path):
        rule = {"file": "mod.py", "standard": "fixed_depth_path"}
        assert checker.check_module(_write(tmp_path, self.TWO), [rule])["score"] == 100
