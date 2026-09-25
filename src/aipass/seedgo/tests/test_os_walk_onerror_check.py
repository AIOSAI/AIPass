# =================== META ====================
# Name: test_os_walk_onerror_check.py
# Description: os_walk_onerror_check — an os.walk call in product code that names no onerror
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/os_walk_onerror_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import os_walk_onerror_check as checker


def _verdict(tmp_path, body, name="walk.py"):
    """(score, the one check's message) for a file planted under apps/."""
    apps = tmp_path / "apps"
    apps.mkdir(exist_ok=True)
    path = apps / name
    path.write_text(body, encoding="utf-8")
    result = checker.check_module(str(path))
    return result["score"], result["checks"][0]["message"]


#: The template's model module, the product side of the model file.
MODEL = Path(__file__).parent.parent / "apps" / "modules" / "readme_update.py"

#: @backup's apps/handlers/scan/walk.py, walk_project as on disk 2026-09-25, docstring cut.
#: The os.walk call is line 11 here, line 34 on disk.
SPECIMEN = """import os

from aipass.backup.apps.handlers.audit import trail


def walk_project(root: str):
    trail.log_operation("walk_project", {"root": root})
    root_path = os.path.realpath(root)


    for dirpath, _dirnames, filenames in os.walk(root_path, followlinks=False):
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.islink(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, root_path)
            yield abs_path, rel_path
"""

SPECIMEN_LINE = 11


class TestTheModelFilePasses:
    def test_the_model_module_scores_100(self):
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    def test_backups_scan_walk_is_convicted_on_its_line(self, tmp_path):
        score, message = _verdict(tmp_path, SPECIMEN)
        assert score == 0
        assert message.splitlines()[0].startswith(f"walk.py:{SPECIMEN_LINE} ")

    def test_a_finding_names_the_call_the_reason_and_the_cure(self, tmp_path):
        message = _verdict(tmp_path, "import os\nos.walk('.')\n")[1]
        assert message == (
            "walk.py:2 os.walk without onerror - an unreadable directory is skipped in silence; "
            "pass onerror= a callable that raises, or that records the error into what the function returns"
        )

    def test_the_cured_specimen_passes(self, tmp_path):
        cured = SPECIMEN.replace("followlinks=False)", "followlinks=False, onerror=_raise)")
        assert _verdict(tmp_path, cured) == (100, "Every os.walk call names an onerror")


class TestTheShape:
    def test_onerror_none_is_the_default_again(self, tmp_path):
        assert _verdict(tmp_path, "import os\nos.walk('.', onerror=None)\n")[0] == 0

    def test_every_hit_in_a_file_is_on_one_check(self, tmp_path):
        body = "import os\nos.walk('a')\nos.walk('b', topdown=False)\n"
        result_lines = _verdict(tmp_path, body)[1].splitlines()
        assert [line.split(" ")[0] for line in result_lines] == ["walk.py:2", "walk.py:3"]

    def test_a_walk_inside_a_nested_function_is_convicted(self, tmp_path):
        body = "import os\n\n\ndef outer():\n    def inner():\n        return list(os.walk('.'))\n    return inner\n"
        assert _verdict(tmp_path, body)[1].startswith("walk.py:6 ")


class TestAliasesAreFollowed:
    def test_import_os_as_an_alias(self, tmp_path):
        assert _verdict(tmp_path, "import os as o\no.walk('.')\n")[0] == 0

    def test_from_os_import_walk(self, tmp_path):
        assert _verdict(tmp_path, "from os import walk\nwalk('.')\n")[0] == 0

    def test_from_os_import_walk_as_an_alias(self, tmp_path):
        assert _verdict(tmp_path, "from os import walk as w\nw('.')\n")[0] == 0

    def test_an_import_inside_a_function(self, tmp_path):
        assert _verdict(tmp_path, "def scan():\n    from os import walk\n    return list(walk('.'))\n")[0] == 0


class TestWhatPasses:
    @pytest.mark.parametrize("hook", ["onerror=_raise", "onerror=errors.append", "onerror=lambda e: None"])
    def test_any_named_hook_passes(self, tmp_path, hook):
        assert _verdict(tmp_path, f"import os\nos.walk('.', {hook})\n")[0] == 100

    def test_the_third_positional_slot_is_onerror(self, tmp_path):
        assert _verdict(tmp_path, "import os\nos.walk('.', True, _raise)\n")[0] == 100

    def test_a_kwargs_splat_is_not_judged(self, tmp_path):
        assert _verdict(tmp_path, "import os\nos.walk('.', **options)\n")[0] == 100

    def test_a_walk_that_is_not_os_walk_is_not_judged(self, tmp_path):
        body = "import ast\nfrom pathlib import Path\nast.walk(tree)\nPath('.').walk()\nPath('.').rglob('*')\n"
        assert _verdict(tmp_path, body)[0] == 100

    def test_the_call_inside_a_string_is_not_convicted(self, tmp_path):
        body = "import os\nNOTE = \"os.walk('.') skips what it cannot list\"  # os.walk(root)\n"
        assert _verdict(tmp_path, body)[0] == 100


class TestTheEdges:
    def test_a_missing_file_scores_0(self, tmp_path):
        result = checker.check_module(str(tmp_path / "apps" / "gone.py"))
        assert (result["score"], result["passed"]) == (0, False)

    def test_an_unparseable_file_is_not_judged(self, tmp_path):
        score, message = _verdict(tmp_path, "def f(:\n    os.walk('.')\n")
        assert (score, message) == (100, "Not judged: the file does not parse (ruff convicts that)")

    def test_a_bypass_for_the_standard_passes_the_file(self, tmp_path):
        path = tmp_path / "apps" / "walk.py"
        path.parent.mkdir()
        path.write_text("import os\nos.walk('.')\n", encoding="utf-8")
        rules = [{"file": str(path), "standard": "os_walk_onerror"}]
        assert checker.check_module(str(path), bypass_rules=rules)["score"] == 100

    def test_a_bypass_for_one_line_clears_that_line_only(self, tmp_path):
        path = tmp_path / "apps" / "walk.py"
        path.parent.mkdir()
        path.write_text("import os\nos.walk('a')\nos.walk('b')\n", encoding="utf-8")
        rules = [{"file": str(path), "standard": "os_walk_onerror", "lines": [2]}]
        message = checker.check_module(str(path), bypass_rules=rules)["checks"][0]["message"]
        assert message.startswith("walk.py:3 ")
        assert len(message.splitlines()) == 1

    def test_the_standard_is_declared_production_only(self):
        assert (checker.APPLIES_TO, checker.AUDIT_SCOPE) == ("production", "all_files")
