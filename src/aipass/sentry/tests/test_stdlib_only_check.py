# =================== AIPass ====================
# Name: test_stdlib_only_check.py
# Description: stdlib_only_check - a listed file's stdlib-only, no-I/O claim proven; json_structure relief for it
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/aipass_standards/stdlib_only_check.py and its json_structure relief."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(shared) — json_structure's wiring checks for unclaimed files; tests/test_json_structure*.py

import pytest

from aipass.sentry.apps.handlers.aipass_standards import json_structure_check
from aipass.sentry.apps.handlers.aipass_standards import stdlib_only_check as checker

CLAIM = "demo/apps/handlers/pure.py"
CLEAN = 'REGISTRY_SUFFIX = "_REGISTRY.json"\n\n\ndef is_registry(name):\n    return name.endswith(REGISTRY_SUFFIX)\n'


def _branch(tmp_path, source=CLEAN, rel=CLAIM):
    target = tmp_path / "src" / "aipass" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return tmp_path / "src" / "aipass" / "demo", target


@pytest.fixture
def claimed(monkeypatch):
    monkeypatch.setattr(checker, "CLAIMS", (CLAIM,))


BROKEN = [
    ("aipass_import", "from aipass.prax import logger\n", "aipass import"),
    ("relative_import", "from . import sibling\n", "relative import"),
    ("third_party_import", "import requests\n", "not in the standard library"),
    ("io_module_import", "import subprocess\n", "does I/O"),
    ("open_call", "def f(p):\n    return open(p)\n", "open"),
    ("path_read", "def f(p):\n    return p.read_text()\n", "read_text"),
    ("path_write", "def f(p):\n    p.write_bytes(b'')\n", "write_bytes"),
    ("disk_listing", "import os\n\n\ndef f(p):\n    return os.listdir(p)\n", "listdir"),
    ("environ_read", "import os\n\nHOME = os.environ['HOME']\n", "environ"),
    ("environ_imported", "from os import environ\n", "environ"),
    ("getenv_call", "import os\n\nH = os.getenv('HOME')\n", "getenv"),
    ("process_run", "import os\n\n\ndef f():\n    os.system('ls')\n", "system"),
    ("exec_family", "import os\n\n\ndef f():\n    os.execvp('ls', ['ls'])\n", "execvp"),
    ("dynamic_import", "import importlib\n\nM = importlib.import_module('aipass.prax')\n", "import_module"),
]


@pytest.mark.usefixtures("claimed")
class TestTheClaimIsProven:
    def test_a_listed_clean_file_passes_at_100(self, tmp_path):
        branch, _ = _branch(tmp_path)
        outcome = checker.check_branch(str(branch))
        assert (outcome["passed"], outcome["score"]) == (True, 100)

    @pytest.mark.parametrize("source, reason", [r[1:] for r in BROKEN], ids=[r[0] for r in BROKEN])
    def test_a_listed_file_breaking_the_promise_fails_naming_why(self, tmp_path, source, reason):
        branch, _ = _branch(tmp_path, CLEAN + source)
        outcome = checker.check_branch(str(branch))
        sites = [site for check in outcome["checks"] for site in check.get("sites", [])]
        assert (outcome["passed"], outcome["score"]) == (False, 0)
        assert any(reason in site["name"] and site["file"] == CLAIM for site in sites)

    def test_a_listed_path_that_does_not_exist_fails(self, tmp_path):
        branch = tmp_path / "src" / "aipass" / "demo"
        branch.mkdir(parents=True)
        outcome = checker.check_branch(str(branch))
        assert (outcome["passed"], outcome["score"]) == (False, 0)
        assert "does not exist" in outcome["checks"][0]["message"]

    def test_a_file_python_cannot_parse_is_not_proven(self, tmp_path):
        branch, _ = _branch(tmp_path, "def broken(:\n")
        assert checker.check_branch(str(branch))["score"] == 0

    def test_a_branch_with_no_claim_stands_down_unmeasured(self, tmp_path):
        branch, _ = _branch(tmp_path, rel="other/apps/handlers/pure.py")
        assert checker.check_branch(str(branch.parent / "other"))["not_applicable"] is True


class TestJsonStructureRelief:
    @pytest.mark.usefixtures("claimed")
    def test_a_listed_proven_file_is_skipped_saying_why(self, tmp_path):
        _, target = _branch(tmp_path)
        outcome = json_structure_check.check_module(str(target))
        assert outcome["score"] == 100 and outcome["checks"][0].get("declined") is True
        assert "stdlib_only" in outcome["checks"][0]["message"]

    @pytest.mark.usefixtures("claimed")
    def test_a_listed_file_that_breaks_the_promise_gets_no_relief(self, tmp_path):
        _, target = _branch(tmp_path, CLEAN + "import requests\n")
        assert json_structure_check.check_module(str(target))["score"] < 100

    def test_an_unlisted_clean_file_is_still_convicted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(checker, "CLAIMS", ())
        _, target = _branch(tmp_path)
        assert json_structure_check.check_module(str(target))["score"] < 100


def test_the_list_holds_drones_registry_name():
    assert "drone/apps/handlers/registry_name.py" in checker.CLAIMS
